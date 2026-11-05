#!/usr/bin/env sh
# One-command installer for GPT-Image2-Skill (Relay + Multi-Client Edition)
#
# Interactive human install:
#   curl -fsSL https://raw.githubusercontent.com/Masikomoore/GPT-Image2-Skill/main/install.sh | sh
#
# AI Agent non-interactive install (prints .env path for user to fill in):
#   curl -fsSL https://raw.githubusercontent.com/Masikomoore/GPT-Image2-Skill/main/install.sh | sh -s -- --agent-mode

set -eu

REPO_URL="${GPT_IMAGE_SKILL_REPO:-https://github.com/Masikomoore/GPT-Image2-Skill.git}"
BRANCH="${GPT_IMAGE_SKILL_BRANCH:-main}"

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Error: Python 3.9+ is required to install GPT-Image2-Skill." >&2
  exit 1
fi

# Determine whether we are running from an existing checkout or via curl | sh
SCRIPT_DIR=""
if [ -n "${0:-}" ] && [ "$0" != "sh" ] && [ "$0" != "-sh" ] && [ "$0" != "bash" ] && [ "$0" != "zsh" ]; then
   CANDIDATE_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
  if [ -n "$CANDIDATE_DIR" ] && [ -f "$CANDIDATE_DIR/scripts/setup_skill.py" ] && [ -d "$CANDIDATE_DIR/skills/gpt-image" ]; then
    SCRIPT_DIR="$CANDIDATE_DIR"
  fi
fi

TMP_DIR=""
cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT INT TERM

if [ -z "$SCRIPT_DIR" ]; then
  TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t gpt-image-skill)"
  echo "Downloading GPT-Image2-Skill from $REPO_URL ($BRANCH)..."
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP_DIR/repo" >/dev/null 2>&1
    SCRIPT_DIR="$TMP_DIR/repo"
  else
    ARCHIVE_URL="https://github.com/Masikomoore/GPT-Image2-Skill/archive/refs/heads/${BRANCH}.tar.gz"
    curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$TMP_DIR"
    SCRIPT_DIR="$(find "$TMP_DIR" -maxdepth 2 -name "setup_skill.py" -exec dirname {} \; | head -n 1)/.."
    SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"
  fi
fi

# Install Python runtime dependency (openai + python-dotenv) into uv/pipx or user site-packages when possible
if command -v uv >/dev/null 2>&1; then
  uv tool install --force "$SCRIPT_DIR" >/dev/null 2>&1 || true
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force "$SCRIPT_DIR" >/dev/null 2>&1 || true
else
  "$PYTHON_BIN" -m pip install --user --quiet -e "$SCRIPT_DIR" >/dev/null 2>&1 || \
  "$PYTHON_BIN" -m pip install --quiet -e "$SCRIPT_DIR" >/dev/null 2>&1 || true
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/scripts/setup_skill.py" --repo-root "$SCRIPT_DIR" "$@"
