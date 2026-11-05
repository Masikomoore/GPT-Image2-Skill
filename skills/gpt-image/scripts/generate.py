#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=2.32.0",
#     "python-dotenv>=1.0",
# ]
# ///
"""Skill launcher for the shared gpt-image CLI.

Resolution order:
1. Repo checkout / full plugin install: import ../../../src/gpt_image_cli/cli.py.
2. Standalone skill copy: import vendored ./gpt_image_cli/cli.py.
3. Python environment already has gpt_image_cli installed: import it directly.
4. Shell has a gpt-image executable: delegate to it.
5. Final fallback: uvx installs/runs the GitHub CLI package transiently.

This keeps `skills/gpt-image` usable when copied as a standalone skill folder
while preserving one canonical implementation for the installable Python CLI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_URL = "git+https://github.com/Masikomoore/GPT-Image2-Skill"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines with standard library only. Ignores blanks and comments."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
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


def _preload_relay_env(skill_dir: Path) -> None:
    """Preload OPENAI_API_KEY and OPENAI_BASE_URL from local/client .env files without overriding process env."""
    os.environ.setdefault("GPT_IMAGE_SKILL_DIR", str(skill_dir))
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    candidates = [
        Path.cwd() / ".env",
        skill_dir / ".env",
        codex_home / ".env",
        home / ".codex" / ".env",
        home / ".workbuddy" / ".env",
        home / ".codebuddy" / ".env",
        home / ".claude" / ".env",
        home / ".cursor" / ".env",
        home / ".agents" / ".env",
        home / ".env",
    ]
    merged: dict[str, str] = {}
    for env_path in candidates:
        if env_path.is_file():
            for k, v in _parse_env_file(env_path).items():
                merged.setdefault(k, v)

    if "OPENAI_API_KEY" not in os.environ:
        api_key = (
            merged.get("GPT_IMAGE_API_KEY")
            or merged.get("OPENAI_API_KEY")
            or merged.get("XCLI_API_KEY")
            or ""
        ).strip()
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key

    if "OPENAI_BASE_URL" not in os.environ:
        base_url = (
            merged.get("GPT_IMAGE_BASE_URL")
            or merged.get("OPENAI_BASE_URL")
            or merged.get("XCLI_BASE_URL")
            or merged.get("BASE_URL")
            or ""
        ).strip()
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url


def _import_local_or_installed_main():
    """Return gpt_image_cli.cli.main from repo-local src, vendored scripts/, or installed package."""
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent

    if (script_dir / "gpt_image_cli" / "cli.py").is_file():
        sys.path.insert(0, str(script_dir))

    # Full plugin/repo layout: <repo>/skills/gpt-image/scripts/generate.py
    # Standalone skill installs do not have this sibling src/ tree, so guard it.
    if len(script_path.parents) > 3:
        repo_src = script_path.parents[3] / "src"
        if (repo_src / "gpt_image_cli" / "cli.py").is_file():
            sys.path.insert(0, str(repo_src))

    try:
        from gpt_image_cli.cli import main  # type: ignore
    except ModuleNotFoundError:
        return None
    return main


def _delegate(command: list[str]) -> int:
    """Run another CLI process with the original argv and return its exit code."""
    completed = subprocess.run(command + sys.argv[1:], check=False)
    return completed.returncode


def main() -> int:
    script_path = Path(__file__).resolve()
    skill_dir = script_path.parents[1] if len(script_path.parents) > 1 else script_path.parent
    _preload_relay_env(skill_dir)
    cli_main = _import_local_or_installed_main()
    if cli_main is not None:
        return int(cli_main() or 0)

    executable = shutil.which("gpt-image")
    if executable:
        return _delegate([executable])

    uvx = shutil.which("uvx") or shutil.which("uv")
    if uvx:
        if Path(uvx).name == "uv":
            return _delegate([uvx, "tool", "run", "--from", _REPO_URL, "gpt-image"])
        return _delegate([uvx, "--from", _REPO_URL, "gpt-image"])

    print(
        "error: could not find the gpt-image CLI backend. Install uv and run this skill "
        "again, or install the CLI first with:\n"
        f"  uv tool install {_REPO_URL}\n"
        "Then retry the same command.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
