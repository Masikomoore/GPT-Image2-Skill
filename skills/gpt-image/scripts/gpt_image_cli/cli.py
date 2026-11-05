#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=2.32.0",
#     "python-dotenv>=1.0",
# ]
# ///
"""General-purpose CLI for OpenAI GPT Image 2 and 2.5.

Mirrors the two official endpoints from the OpenAI cookbook using the official
`openai` Python SDK:

    client.images.generate(...)   — text → image          (no  -i)
    client.images.edit(...)       — text + image(s) → image (with -i; mask via -m)

Common generation and editing parameters are exposed as flags. Reads OPENAI_API_KEY and
OPENAI_BASE_URL from process env, then local/client .env files (./.env, <skill>/.env,
~/.codex/.env, ~/.workbuddy/.env, ~/.codebuddy/.env, ~/.claude/.env, ~/.cursor/.env,
~/.agents/.env, ~/.env) without overriding existing env. Writes the
returned PNG/JPEG/WebP bytes to disk and prints the output path(s) on stdout.

Exit codes: 0 success, 1 API error, 2 bad args.

Examples:
    # Basic generate, auto filename, 1K square
    gpt-image -p "a cat astronaut on the moon"

    # Named output, portrait 2K, high quality
    gpt-image -p "Chinese tea poster" -f poster.png --size 2k --quality high

    # Edit existing image (colorize, restyle, translate text, etc.)
    gpt-image -p "colorize this manga page" -i page.jpg -f colored.png

    # Multi-reference edit (outfit transfer, pet + brand, etc.)
    gpt-image -p "77 × KFC collab poster" -i cat.png -i kfc_logo.png -f collab.png

    # Alpha-channel inpaint (mask opaque = keep, transparent = regenerate)
    gpt-image -p "replace sky with aurora" -i photo.jpg -m sky_mask.png -f aurora.png

    # Grid of 4, opaque background, webp
    gpt-image -p "isometric chair, minimalist" -n 4 --background opaque --format webp

    # Skill launcher (same implementation, installed skill-folder path)
    uv run "$SKILL_DIR/scripts/generate.py" -p "a cat astronaut on the moon"
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values, load_dotenv
from openai import APIError, OpenAI


MAX_INLINE_PREVIEW_BYTES = 10 * 1024 * 1024
PLACEHOLDER_KEYS = {
    "",
    "YOUR_API_KEY_HERE",
    "YOUR-API-KEY",
    "sk-...",
    "sk-xxxx",
    "your_api_key_here",
    "your-api-key",
}


def _is_placeholder_key(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip() in PLACEHOLDER_KEYS

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


def normalize_base_url(value: str | None) -> str | None:
    """Normalize an OpenAI-compatible relay base URL to end with /v1 when bare."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
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


def _env_file_candidates() -> list[Path]:
    """Return ordered .env file locations across project, skill, and IDE/CLI clients."""
    cwd = Path.cwd()
    home = Path.home()
    candidates: list[Path] = [cwd / ".env"]

    skill_dir_env = os.environ.get("GPT_IMAGE_SKILL_DIR", "").strip()
    if skill_dir_env:
        candidates.append(Path(skill_dir_env) / ".env")

    script_path = Path(__file__).resolve()
    if len(script_path.parents) >= 3 and script_path.parents[1].name == "scripts":
        candidates.append(script_path.parents[2] / ".env")

    codex_home_env = os.environ.get("CODEX_HOME", "").strip()
    if codex_home_env:
        candidates.append(Path(codex_home_env) / ".env")
    candidates.extend([
        home / ".codex" / ".env",
        home / ".workbuddy" / ".env",
        home / ".codebuddy" / ".env",
        home / ".claude" / ".env",
        home / ".cursor" / ".env",
        home / ".agents" / ".env",
        home / ".env",
    ])

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _load_env_chain() -> None:
    """Resolve OPENAI_API_KEY and OPENAI_BASE_URL without overriding runtime-provided env.

    Order: process env → ./.env → <skill>/.env → ~/.codex/.env → client .env files → ~/.env.
    Existing process env wins so hosted agents or explicit shell exports are not replaced.
    However, if OPENAI_BASE_URL is not set in process env and is loaded from a .env file that
    also defines a non-placeholder API key, keep the URL and key paired from that .env file.
    """
    process_had_base_url = any(
        os.environ.get(k, "").strip()
        for k in ("OPENAI_BASE_URL", "GPT_IMAGE_BASE_URL", "XCLI_BASE_URL", "BASE_URL")
    )
    paired_relay_key: str | None = None
    paired_relay_url: str | None = None

    for env_path in _env_file_candidates():
        if env_path.is_file():
            if not process_had_base_url and paired_relay_url is None:
                vals = dotenv_values(env_path)
                file_url = (
                    vals.get("OPENAI_BASE_URL")
                    or vals.get("GPT_IMAGE_BASE_URL")
                    or vals.get("XCLI_BASE_URL")
                    or vals.get("BASE_URL")
                    or ""
                ).strip()
                file_key = (
                    vals.get("OPENAI_API_KEY")
                    or vals.get("GPT_IMAGE_API_KEY")
                    or vals.get("XCLI_API_KEY")
                    or ""
                ).strip()
                if file_url:
                    paired_relay_url = normalize_base_url(file_url)
                    if not _is_placeholder_key(file_key):
                        paired_relay_key = file_key
            load_dotenv(env_path, override=False)

    if not process_had_base_url and paired_relay_url:
        os.environ["OPENAI_BASE_URL"] = paired_relay_url
        if paired_relay_key:
            os.environ["OPENAI_API_KEY"] = paired_relay_key

    if "OPENAI_API_KEY" not in os.environ:
        for alias in ("GPT_IMAGE_API_KEY", "XCLI_API_KEY"):
            val = os.environ.get(alias, "").strip()
            if val:
                os.environ["OPENAI_API_KEY"] = val
                break

    if "OPENAI_BASE_URL" not in os.environ:
        for alias in ("GPT_IMAGE_BASE_URL", "XCLI_BASE_URL", "BASE_URL"):
            val = os.environ.get(alias, "").strip()
            if val:
                normalized = normalize_base_url(val)
                if normalized:
                    os.environ["OPENAI_BASE_URL"] = normalized
                break
    elif os.environ.get("OPENAI_BASE_URL", "").strip():
        normalized = normalize_base_url(os.environ["OPENAI_BASE_URL"])
        if normalized:
            os.environ["OPENAI_BASE_URL"] = normalized


SIZE_SHORTCUTS: dict[str, str] = {
    "1k": "1024x1024",
    "2k": "2048x2048",
    "2k-landscape": "2048x1152",
    "2k-wide": "2048x1152",
    "2k-portrait": "1152x2048",
    "2k-tall": "1152x2048",
    "2k-4:3": "2048x1536",
    "2.5k": "2560x1440",
    "2.5k-landscape": "2560x1440",
    "2.5k-wide": "2560x1440",
    "2.5k-portrait": "1440x2560",
    "2.5k-tall": "1440x2560",
    "2.5k-square": "2560x2560",
    "2.5k-4:3": "2560x2064",
    "4k": "3840x2160",
    "4k-landscape": "3840x2160",
    "4k-wide": "3840x2160",
    "4k-portrait": "2160x3840",
    "4k-tall": "2160x3840",
    "4k-square": "2880x2880",
    "4k-4:3": "3264x2448",
    "portrait": "1024x1536",
    "landscape": "1536x1024",
    "square": "1024x1024",
    "wide": "2048x1152",
    "tall": "2160x3840",
}

DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_MODERATION = "low"


def slugify(text: str, max_len: int = 30) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[-\s]+", "-", s)[:max_len]
    return s or "image"


def default_output_path(prompt: str, extension: str) -> Path:
    cwd = Path.cwd()
    target_dir = cwd / "fig" if (cwd / "fig").is_dir() else cwd
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return target_dir / f"{stamp}-{slugify(prompt)}.{extension}"


def resolve_size(value: str) -> str:
    return SIZE_SHORTCUTS.get(value.lower(), value)


def model_rejects_input_fidelity(model: str) -> bool:
    return re.fullmatch(r"gpt-image-2(?:-\d{4}-\d{2}-\d{2})?", model) is not None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="gpt-image",
        description="Call OpenAI GPT Image 2/2.5 (generations or edits) via the official openai Python SDK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-p", "--prompt", required=True, help="Text prompt / edit instruction.")
    p.add_argument(
        "-f", "--file",
        help="Output path. Auto-generated as YYYY-MM-DD-HH-MM-SS-<slug>.<ext> if omitted "
             "(written to ./fig/ if that dir exists, else ./).",
    )
    p.add_argument(
        "-i", "--image", action="append", type=Path, default=None,
        help="Reference image path. Repeat flag for multi-reference edits. "
             "Presence of any -i switches endpoint to client.images.edit().",
    )
    p.add_argument(
        "-m", "--mask", type=Path, default=None,
        help="Alpha-channel PNG mask (opaque = preserved, transparent = regenerated). "
             "Edits endpoint only; requires -i.",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Model ID: gpt-image-2.5-flare, gpt-image-2.5-sunburst, or {DEFAULT_MODEL} (compatibility default).")
    p.add_argument(
        "--size", default=DEFAULT_SIZE,
        help="Image size. Accepts literals (1024x1024, 1536x1024, 2048x2048, 3840x2160, "
             "any 16px-multiple up to 3840 max edge, 3:1 ratio cap) or shortcuts "
             "(1k, 2k, 4k, portrait, landscape, square, wide, tall). Default 1024x1024.",
    )
    p.add_argument(
        "--quality", default="high", choices=["auto", "low", "medium", "high", "xhigh", "max"],
        help="Rendering fidelity / budget knob. Default high; xhigh/max require GPT Image 2.5. "
             "Use low for cheap drafts, medium for normal exploration, high for final text-heavy or shipping-facing assets.",
    )
    p.add_argument("-n", "--n", type=int, default=1, help="Number of images to return. Default 1.")
    p.add_argument(
        "--background", default=None, choices=["auto", "opaque", "transparent"],
        help="`transparent` requires png or webp. Default API-side auto.",
    )
    p.add_argument(
        "--moderation", default=DEFAULT_MODERATION, choices=["auto", "low"],
        help="Generations only. Default low. Use `auto` if you want the stricter API-side default.",
    )
    p.add_argument(
        "--input-fidelity", dest="input_fidelity", default=None, choices=["low", "high"],
        help="Edits only; omitted by default. Dropped for gpt-image-2; explicit 2.5 values are passed to the API (support unverified).",
    )
    p.add_argument(
        "--format", dest="output_format", default=None,
        choices=["png", "jpeg", "webp"],
        help="Output encoding. Default png.",
    )
    p.add_argument(
        "--compression", dest="output_compression", type=int, default=None,
        help="0-100 compression level for jpeg/webp. Ignored for png.",
    )
    p.add_argument(
        "--user", default=None,
        help="Optional end-user identifier forwarded to OpenAI for abuse tracking.",
    )
    p.add_argument(
        "--base-url", dest="base_url", default=None,
        help="OpenAI-compatible relay base URL (e.g. https://jp.xcli.si/v1). "
             "Overrides OPENAI_BASE_URL / GPT_IMAGE_BASE_URL / XCLI_BASE_URL.",
    )
    p.add_argument(
        "--api-key", dest="api_key", default=None,
        help="API key override (prefer configuring OPENAI_API_KEY in ~/.codex/.env or .env).",
    )
    p.add_argument(
        "--preview", default=None, choices=["auto", "osc1337", "kitty", "open", "off"],
        help="Preview generated image(s) in supported TUI terminals (iTerm2/WezTerm/Warp OSC 1337, "
             "Kitty/Ghostty APC) via /dev/tty or open in OS viewer without polluting stdout.",
    )
    p.add_argument(
        "--open", dest="open_viewer", action="store_true",
        help="Open generated image(s) in the system default image viewer (alias for --preview open).",
    )
    args = p.parse_args()
    image25 = re.fullmatch(r"gpt-image-2\.5-(?:flare|sunburst)(?:-\d{4}-\d{2}-\d{2})?", args.model) is not None
    if args.quality in ("xhigh", "max") and not image25:
        p.error("--quality xhigh/max requires --model gpt-image-2.5-flare or gpt-image-2.5-sunburst")
    if args.background == "transparent" and args.output_format == "jpeg":
        p.error("--background transparent requires --format png or webp")
    if not 1 <= args.n <= 10:
        p.error("--n must be between 1 and 10")
    if args.output_compression is not None and not 0 <= args.output_compression <= 100:
        p.error("--compression must be between 0 and 100")
    if args.mask and not args.image:
        p.error("--mask requires --image (edits endpoint only)")
    size = resolve_size(args.size)
    if (image25 or model_rejects_input_fidelity(args.model)) and size != "auto":
        match = re.fullmatch(r"(\d+)x(\d+)", size)
        if not match:
            p.error("--size must be auto, a size shortcut, or WIDTHxHEIGHT")
        width, height = map(int, match.groups())
        if (min(width, height) <= 0 or max(width, height) > 3840
                or width % 16 or height % 16 or max(width, height) > 3 * min(width, height)
                or not 655360 <= width * height <= 8294400):
            p.error(
                "--size requires 16px multiples, edges <=3840px, aspect ratio <=3:1, and 655360–8294400 pixels "
                "(e.g. use 2048x1152, 2560x1440, or 3840x2160 instead of 1920x1080; 2880x2880 for 4K square)"
            )
    return args


def _filter_none(d: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None — SDK treats missing vs None differently."""
    return {k: v for k, v in d.items() if v is not None}


def call_generate(client: OpenAI, args: argparse.Namespace) -> Any:
    return client.images.generate(**_filter_none({
        "model": args.model,
        "prompt": args.prompt,
        "size": resolve_size(args.size),
        "quality": args.quality,
        "n": args.n,
        "background": args.background,
        "moderation": args.moderation,
        "output_format": args.output_format,
        "output_compression": args.output_compression if args.output_format in ("jpeg", "webp") else None,
        "user": args.user,
    }))


def call_edit(client: OpenAI, args: argparse.Namespace) -> Any:
    for p in args.image:
        if not p.is_file():
            print(f"error: --image not found: {p}", file=sys.stderr)
            sys.exit(2)
    if args.mask and not args.mask.is_file():
        print(f"error: --mask not found: {args.mask}", file=sys.stderr)
        sys.exit(2)

    input_fidelity = args.input_fidelity
    if input_fidelity and model_rejects_input_fidelity(args.model):
        print(
            "note: dropping --input-fidelity because gpt-image-2 rejects that parameter.",
            file=sys.stderr,
        )
        input_fidelity = None

    image_handles = [p.open("rb") for p in args.image]
    mask_handle = args.mask.open("rb") if args.mask else None
    try:
        return client.images.edit(**_filter_none({
            "model": args.model,
            "image": image_handles,
            "mask": mask_handle,
            "prompt": args.prompt,
            "size": resolve_size(args.size),
            "quality": args.quality,
            "n": args.n,
            "background": args.background,
            "input_fidelity": input_fidelity,
            "output_format": args.output_format,
            "output_compression": args.output_compression if args.output_format in ("jpeg", "webp") else None,
            "user": args.user,
        }))
    finally:
        for h in image_handles:
            h.close()
        if mask_handle:
            mask_handle.close()


def write_outputs(data: list[Any], out_path: Path, n: int) -> list[Path]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i, item in enumerate(data):
        b64 = item.get("b64_json") if isinstance(item, Mapping) else getattr(item, "b64_json", None)
        url = item.get("url") if isinstance(item, Mapping) else getattr(item, "url", None)
        if b64:
            raw = base64.b64decode(b64)
        elif url:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 — OpenAI/relay pre-signed URL
                raw = r.read()
        else:
            print(f"error: response item {i} has neither b64_json nor url", file=sys.stderr)
            sys.exit(1)

        if n == 1:
            target = out_path
        else:
            stem = out_path.with_suffix("")
            target = stem.parent / f"{stem.name}_{i}{out_path.suffix}"
        target.write_bytes(raw)
        written.append(target)
    return written


def detect_terminal_preview_protocol(env: Mapping[str, str] | None = None) -> str | None:
    """Detect inline terminal graphics protocol (kitty or osc1337) from terminal env vars."""
    environ = os.environ if env is None else env
    if environ.get("TMUX"):
        return None
    term = environ.get("TERM", "").lower()
    term_program = environ.get("TERM_PROGRAM", "")
    if environ.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        return "kitty"
    if environ.get("GHOSTTY_RESOURCES_DIR") or term == "xterm-ghostty" or term_program.lower() == "ghostty":
        return "kitty"
    if environ.get("WEZTERM_EXECUTABLE") or term_program == "WezTerm":
        return "osc1337"
    if term_program in ("iTerm.app", "WarpTerminal", "Rio", "Hyper") or environ.get("LC_TERMINAL") == "iTerm2":
        return "osc1337"
    if environ.get("KONSOLE_VERSION"):
        return "osc1337"
    return None


def _format_osc1337_image(path: Path, raw: bytes) -> str:
    name_b64 = base64.b64encode(path.name.encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(raw).decode("ascii")
    return (
        f"\033]1337;File=name={name_b64};size={len(raw)};inline=1;"
        f"width=auto;preserveAspectRatio=1:{payload_b64}\a\n"
    )


def _format_kitty_image(raw: bytes) -> str:
    payload_b64 = base64.b64encode(raw).decode("ascii")
    chunks = [payload_b64[i : i + 4096] for i in range(0, len(payload_b64), 4096)] or [""]
    out: list[str] = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        if index == 0:
            out.append(f"\033_Ga=T,f=100,m={more};{chunk}\033\\")
        else:
            out.append(f"\033_Gm={more};{chunk}\033\\")
    out.append("\n")
    return "".join(out)


def _open_in_system_viewer(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def render_preview(paths: list[Path], preview_mode: str | None = None, open_viewer: bool = False) -> None:
    """Render optional TUI inline preview to /dev/tty or open in OS viewer without touching stdout."""
    mode = "open" if open_viewer else (preview_mode or os.environ.get("GPT_IMAGE_PREVIEW") or "off").strip().lower()
    if mode in ("", "off"):
        return
    if mode == "open":
        for path in paths:
            _open_in_system_viewer(path)
        return
    if mode == "auto":
        if not sys.stdout.isatty():
            return
        protocol = detect_terminal_preview_protocol(os.environ)
        if not protocol:
            return
    elif mode in ("osc1337", "kitty"):
        protocol = mode
    else:
        return

    tty_path = Path("/dev/tty")
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > MAX_INLINE_PREVIEW_BYTES:
            continue
        sequence = _format_osc1337_image(path, raw) if protocol == "osc1337" else _format_kitty_image(raw)
        try:
            if tty_path.exists():
                with tty_path.open("w", encoding="ascii", errors="ignore") as tty:
                    tty.write(sequence)
                    tty.flush()
        except OSError:
            continue


def main() -> int:
    args = parse_args()

    _load_env_chain()
    api_key = (args.api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if _is_placeholder_key(api_key):
        print(
            "error: OPENAI_API_KEY not set. Add OPENAI_API_KEY (and optional OPENAI_BASE_URL) to "
            "~/.codex/.env, ./.env, or ~/.env, or use your host agent's native image tool.",
            file=sys.stderr,
        )
        return 2

    if args.api_key:
        os.environ["OPENAI_API_KEY"] = api_key

    raw_base_url = (args.base_url or "").strip() or os.environ.get("OPENAI_BASE_URL", "").strip()
    base_url = normalize_base_url(raw_base_url) if raw_base_url else None
    if base_url:
        os.environ["OPENAI_BASE_URL"] = base_url

    ext = args.output_format or "png"
    out_path = Path(args.file).expanduser().resolve() if args.file else default_output_path(args.prompt, ext)

    client_kwargs: dict[str, Any] = {"max_retries": 0}
    if base_url:
        client_kwargs["base_url"] = base_url
    if args.api_key:
        client_kwargs["api_key"] = api_key
    client = OpenAI(**client_kwargs)  # No hidden retries of potentially billable generation requests.

    try:
        result = call_edit(client, args) if args.image else call_generate(client, args)
    except APIError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    data = result.data or []
    if not data:
        print(f"error: no image data in response: {result}", file=sys.stderr)
        return 1

    written = write_outputs(data, out_path, args.n)
    render_preview(written, preview_mode=args.preview, open_viewer=args.open_viewer)
    for p in written:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
