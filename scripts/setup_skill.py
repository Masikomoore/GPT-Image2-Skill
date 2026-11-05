#!/usr/bin/env python3
"""Cross-client installer and relay .env configurator for GPT-Image2-Skill.

Supports two modes:
1. Interactive mode (default when a terminal /dev/tty is available):
   Prompts for the third-party relay base URL (default: https://jp.xcli.si/v1)
   and API key (hidden input), installs `gpt-image` and `get-prompt-from-image`
   across Codex, WorkBuddy, Claude Code, Cursor, Cline, Roo Code, OpenCode, Pi,
   OpenClaw, Hermes, and AgentSkills directories, and writes `.env` (chmod 0600).
2. AI Agent / non-interactive mode (`--agent-mode` or `--non-interactive`, or when no TTY exists):
   Installs the skills without prompting, creates or preserves `.env` with
   `OPENAI_BASE_URL` and `OPENAI_API_KEY` placeholders if missing, and prints
   the exact `.env` file path for the user to fill in locally.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import termios
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_BASE_URL = "https://jp.xcli.si/v1"
PLACEHOLDER_API_KEY = "YOUR_API_KEY_HERE"
SKILL_NAMES = ("gpt-image", "get-prompt-from-image")

RELAY_PRESETS = {
    "1": ("jp", "https://jp.xcli.si/v1"),
    "2": ("us", "https://us.xcli.si/v1"),
}

_ENDPOINT_SUFFIXES = (
    "/v1/images/generations",
    "/v1/images/edits",
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/models",
    "/images/generations",
    "/images/edits",
    "/chat/completions",
    "/responses",
)


def normalize_base_url(value: str | None) -> str:
    """Normalize an OpenAI-compatible relay base URL so bare hosts get /v1."""
    if value is None:
        return DEFAULT_BASE_URL
    cleaned = value.strip()
    if not cleaned:
        return DEFAULT_BASE_URL
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        return cleaned.rstrip("/")
    path = parts.path.rstrip("/")
    lower_path = path.lower()
    for suffix in _ENDPOINT_SUFFIXES:
        if lower_path.endswith(suffix):
            if suffix.startswith("/v1/"):
                path = path[: len(path) - len(suffix)] + "/v1"
            else:
                path = path[: len(path) - len(suffix)]
            break
    while path.lower().endswith("/v1/v1"):
        path = path[:-3]
    if not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def client_skill_roots(home: Path, codex_home: Path) -> dict[str, Path]:
    """Return supported IDE / CLI agent skill directories."""
    return {
        "codex": codex_home / "skills",
        "agents": home / ".agents" / "skills",
        "workbuddy": home / ".workbuddy" / "skills",
        "codebuddy": home / ".codebuddy" / "skills",
        "claude": home / ".claude" / "skills",
        "cursor": home / ".cursor" / "skills",
        "cline": home / ".cline" / "skills",
        "roo": home / ".roo" / "skills",
        "opencode": home / ".config" / "opencode" / "skills",
        "pi": home / ".pi" / "agent" / "skills",
        "openclaw": home / ".openclaw" / "skills",
        "hermes": home / ".hermes" / "skills",
    }


def resolve_target_clients(requested: list[str], home: Path, codex_home: Path) -> list[tuple[str, Path]]:
    """Determine which client skill directories to install into."""
    roots = client_skill_roots(home, codex_home)
    tokens: list[str] = []
    for item in requested or ["auto"]:
        for part in item.split(","):
            cleaned = part.strip().lower()
            if cleaned:
                tokens.append(cleaned)
    if not tokens:
        tokens = ["auto"]

    selected: list[str] = []
    if "all" in tokens:
        selected = list(roots.keys())
    elif "auto" in tokens:
        selected.extend(["codex", "agents"])
        detection_parents = {
            "workbuddy": home / ".workbuddy",
            "codebuddy": home / ".codebuddy",
            "claude": home / ".claude",
            "cursor": home / ".cursor",
            "cline": home / ".cline",
            "roo": home / ".roo",
            "opencode": home / ".config" / "opencode",
            "pi": home / ".pi" / "agent",
            "openclaw": home / ".openclaw",
            "hermes": home / ".hermes",
        }
        for name, parent in detection_parents.items():
            if parent.exists() and name not in selected:
                selected.append(name)
        for token in tokens:
            if token != "auto" and token in roots and token not in selected:
                selected.append(token)
    else:
        for token in tokens:
            alias = "claude" if token == "claude-code" else token
            if alias not in roots:
                valid = ", ".join(["auto", "all", *roots.keys()])
                raise RuntimeError(f"unknown client {token!r}; supported values: {valid}")
            if alias not in selected:
                selected.append(alias)

    result: list[tuple[str, Path]] = []
    seen_paths: set[Path] = set()
    for name in selected:
        target = roots[name]
        if target not in seen_paths:
            seen_paths.add(target)
            result.append((name, target))
    return result


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from an existing .env file."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def is_placeholder_key(value: str | None) -> bool:
    if not value:
        return True
    cleaned = value.strip()
    return cleaned in {
        "",
        PLACEHOLDER_API_KEY,
        "YOUR-API-KEY",
        "sk-...",
        "your_api_key_here",
        "your-api-key",
    }


def upsert_env_file(
    env_path: Path,
    base_url: str,
    api_key: str,
    overwrite: bool = False,
) -> tuple[str, bool]:
    """Create or update OPENAI_BASE_URL and OPENAI_API_KEY in env_path with 0600 permissions.

    Returns (effective_base_url, has_real_api_key).
    """
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = parse_env_file(env_path)

    existing_url = existing.get("OPENAI_BASE_URL") or existing.get("GPT_IMAGE_BASE_URL") or existing.get("XCLI_BASE_URL")
    existing_key = existing.get("OPENAI_API_KEY") or existing.get("GPT_IMAGE_API_KEY") or existing.get("XCLI_API_KEY")

    final_url = normalize_base_url(
        base_url if (overwrite or not existing_url) else existing_url
    )
    if overwrite:
        final_key = api_key.strip() if api_key.strip() else (existing_key or PLACEHOLDER_API_KEY)
    else:
        if not is_placeholder_key(api_key):
            final_key = api_key.strip()
        elif not is_placeholder_key(existing_key):
            final_key = existing_key  # type: ignore[assignment]
        else:
            final_key = PLACEHOLDER_API_KEY

    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()

    updated_url = False
    updated_key = False
    new_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            check = stripped[len("export ") :].strip() if stripped.startswith("export ") else stripped
            k, _ = check.split("=", 1)
            k = k.strip()
            if k == "OPENAI_BASE_URL":
                if not updated_url:
                    new_lines.append(f"OPENAI_BASE_URL={final_url}")
                    updated_url = True
                continue
            if k == "OPENAI_API_KEY":
                if not updated_key:
                    new_lines.append(f"OPENAI_API_KEY={final_key}")
                    updated_key = True
                continue
        new_lines.append(raw)

    if not updated_url:
        new_lines.append(f"OPENAI_BASE_URL={final_url}")
    if not updated_key:
        new_lines.append(f"OPENAI_API_KEY={final_key}")

    content = "\n".join(new_lines).rstrip("\n") + "\n"
    tmp_path = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    try:
        tmp_path.chmod(0o600)
    except OSError:
        pass
    tmp_path.replace(env_path)
    try:
        env_path.chmod(0o600)
    except OSError:
        pass

    return final_url, not is_placeholder_key(final_key)


class ConsoleIO:
    """TTY-aware reader/writer that works even when stdin is piped (`curl | sh`)."""

    def __init__(self, force_non_interactive: bool = False) -> None:
        self.tty_in = None
        self.tty_out = None
        self.interactive = False
        if force_non_interactive:
            return
        if sys.stdin.isatty() and sys.stdout.isatty():
            self.tty_in = sys.stdin
            self.tty_out = sys.stdout
            self.interactive = True
            return
        try:
            self.tty_in = open("/dev/tty", "r", encoding="utf-8", errors="replace")
            self.tty_out = open("/dev/tty", "w", encoding="utf-8", errors="replace")
            self.interactive = True
        except OSError:
            self.close()

    def close(self) -> None:
        for handle in (self.tty_in, self.tty_out):
            if handle is not None and handle not in (sys.stdin, sys.stdout, sys.stderr):
                try:
                    handle.close()
                except OSError:
                    pass
        self.tty_in = None
        self.tty_out = None
        self.interactive = False

    def prompt_line(self, message: str) -> str:
        if not self.interactive or self.tty_in is None or self.tty_out is None:
            return ""
        self.tty_out.write(message)
        self.tty_out.flush()
        line = self.tty_in.readline()
        return line.strip() if line else ""

    def prompt_secret(self, message: str) -> str:
        if not self.interactive or self.tty_in is None or self.tty_out is None:
            return ""
        self.tty_out.write(message)
        self.tty_out.flush()
        fd = self.tty_in.fileno()
        old = None
        try:
            old = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] = new[3] & ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            line = self.tty_in.readline()
        except Exception:
            line = self.tty_in.readline()
        finally:
            if old is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except Exception:
                    pass
            self.tty_out.write("\n")
            self.tty_out.flush()
        return line.strip() if line else ""


def copy_skill_tree(source_skill: Path, target_skill: Path) -> None:
    """Copy a skill folder cleanly without .git or __pycache__."""
    target_skill.parent.mkdir(parents=True, exist_ok=True)
    if target_skill.is_symlink() or target_skill.is_file():
        target_skill.unlink()
    elif target_skill.is_dir():
        shutil.rmtree(target_skill)
    shutil.copytree(
        source_skill,
        target_skill,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )
    launcher = target_skill / "scripts" / "generate.py"
    if launcher.is_file():
        try:
            launcher.chmod(0o755)
        except OSError:
            pass


def sync_vendored_cli(repo_root: Path) -> None:
    """Ensure skills/gpt-image/scripts/gpt_image_cli matches src/gpt_image_cli."""
    src_pkg = repo_root / "src" / "gpt_image_cli"
    dst_pkg = repo_root / "skills" / "gpt-image" / "scripts" / "gpt_image_cli"
    if not (src_pkg / "cli.py").is_file():
        return
    dst_pkg.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "cli.py"):
        src_file = src_pkg / name
        if src_file.is_file():
            shutil.copy2(src_file, dst_pkg / name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install GPT-Image2-Skill across Codex, WorkBuddy, and other IDE/CLI clients and configure relay .env."
    )
    parser.add_argument(
        "--client",
        "--clients",
        dest="client",
        action="append",
        default=[],
        help="Target client(s): auto (default), all, codex, workbuddy, codebuddy, claude, cursor, cline, roo, opencode, pi, openclaw, hermes, agents.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Optional repository root path (defaults to parent of scripts/).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"Relay OPENAI_BASE_URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Relay OPENAI_API_KEY (prefer interactive hidden prompt or editing .env directly).",
    )
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read OPENAI_API_KEY from the first line of stdin.",
    )
    parser.add_argument(
        "--env-file",
        "--env-path",
        dest="env_file",
        default=None,
        help="Explicit .env file path to create/update (default: ${CODEX_HOME:-~/.codex}/.env).",
    )
    parser.add_argument(
        "--home",
        default=None,
        help="Override HOME directory (for isolated testing).",
    )
    parser.add_argument(
        "--codex-home",
        default=None,
        help="Override CODEX_HOME directory (default: ~/.codex).",
    )
    parser.add_argument(
        "--agent-mode",
        "--non-interactive",
        dest="non_interactive",
        action="store_true",
        help="Non-interactive mode for AI Agents: never prompt for input; create/preserve .env and print its path.",
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="Overwrite existing OPENAI_BASE_URL / OPENAI_API_KEY in .env.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    sync_vendored_cli(repo_root)

    home = Path(args.home).expanduser().resolve() if args.home else Path.home()
    raw_codex_home = args.codex_home or os.environ.get("CODEX_HOME") or str(home / ".codex")
    codex_home = Path(raw_codex_home).expanduser().resolve()
    env_path = Path(args.env_file).expanduser().resolve() if args.env_file else (codex_home / ".env")

    targets = resolve_target_clients(args.client, home, codex_home)
    installed_paths: list[tuple[str, Path]] = []
    for client_name, skill_root in targets:
        for skill_name in SKILL_NAMES:
            src_skill = repo_root / "skills" / skill_name
            if not src_skill.is_dir():
                raise RuntimeError(f"missing skill directory: {src_skill}")
            dst_skill = skill_root / skill_name
            copy_skill_tree(src_skill, dst_skill)
            installed_paths.append((client_name, dst_skill))

    existing_env = parse_env_file(env_path)
    existing_url = (
        existing_env.get("OPENAI_BASE_URL")
        or existing_env.get("GPT_IMAGE_BASE_URL")
        or existing_env.get("XCLI_BASE_URL")
        or DEFAULT_BASE_URL
    )
    existing_key = (
        existing_env.get("OPENAI_API_KEY")
        or existing_env.get("GPT_IMAGE_API_KEY")
        or existing_env.get("XCLI_API_KEY")
        or ""
    )

    chosen_url = args.base_url or os.environ.get("GPT_IMAGE_BASE_URL")
    chosen_key = args.api_key or os.environ.get("GPT_IMAGE_API_KEY") or ""
    if args.api_key_stdin:
        chosen_key = sys.stdin.readline().rstrip("\r\n")

    console = ConsoleIO(force_non_interactive=args.non_interactive or args.api_key_stdin)
    try:
        if console.interactive:
            if not args.base_url:
                default_url = normalize_base_url(existing_url)
                prompt_msg = (
                    f"\n[1/2] 请输入中转站地址 OPENAI_BASE_URL "
                    f"(1=亚洲 https://jp.xcli.si/v1, 2=北美 https://us.xcli.si/v1, 或直接输入自定义 URL) "
                    f"[默认 {default_url}]: "
                )
                ans = console.prompt_line(prompt_msg)
                if not ans:
                    chosen_url = default_url
                elif ans in RELAY_PRESETS:
                    chosen_url = RELAY_PRESETS[ans][1]
                else:
                    chosen_url = normalize_base_url(ans)

            if not args.api_key:
                if not is_placeholder_key(existing_key) and not args.reconfigure:
                    ans_key = console.prompt_secret(
                        "[2/2] 检测到已有 OPENAI_API_KEY，直接回车保留现有 Key，或输入新 Key 覆盖: "
                    )
                    chosen_key = ans_key if ans_key else existing_key
                else:
                    ans_key = console.prompt_secret(
                        "[2/2] 请输入中转站 API Key (输入隐藏，直接回车可稍后在 .env 中填写): "
                    )
                    chosen_key = ans_key if ans_key else PLACEHOLDER_API_KEY
    finally:
        console.close()

    final_url, has_real_key = upsert_env_file(
        env_path,
        base_url=chosen_url or existing_url or DEFAULT_BASE_URL,
        api_key=chosen_key or existing_key or PLACEHOLDER_API_KEY,
        overwrite=bool(args.reconfigure or args.base_url or args.api_key or args.api_key_stdin),
    )

    # If user explicitly requested workbuddy or codebuddy, also mirror .env into that client dir if missing
    requested_names = {name for name, _ in targets}
    for extra_client, extra_dir in (("workbuddy", home / ".workbuddy"), ("codebuddy", home / ".codebuddy")):
        if extra_client in requested_names and extra_dir.exists():
            extra_env = extra_dir / ".env"
            if extra_env != env_path and not extra_env.exists():
                upsert_env_file(
                    extra_env,
                    base_url=final_url,
                    api_key=chosen_key or existing_key or PLACEHOLDER_API_KEY,
                    overwrite=False,
                )

    print("=== GPT-Image2-Skill 安装完成 ===")
    grouped: dict[str, list[str]] = {}
    for client_name, path in installed_paths:
        grouped.setdefault(client_name, []).append(str(path))
    for client_name, paths in grouped.items():
        print(f"  - 客户端 [{client_name}]: {', '.join(paths)}")
    print(f"ENV_FILE={env_path}")
    print(f"OPENAI_BASE_URL={final_url}")
    if has_real_key:
        print("OPENAI_API_KEY=已配置 (值已隐藏)")
    else:
        print(
            f"OPENAI_API_KEY=待填写 -> 请打开 {env_path} 填写你的 OPENAI_API_KEY 和 OPENAI_BASE_URL 后即可使用。"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
