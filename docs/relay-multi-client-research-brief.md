# Feature Research Brief: Third-Party Relay, Multi-Client IDE/TUI Support & One-Step Installer

## 1. Decision summary

- **Feature**: Transform `GPT-Image2-Skill` into a third-party OpenAI-compatible relay image-generation & prompt-extraction skill supporting Codex, WorkBuddy, Claude Code, Cursor, Cline, Roo Code, OpenCode, Pi, OpenClaw, Hermes Agent, and TUI inline terminal preview, with a one-command interactive installer and a one-sentence AI Agent non-interactive installer.
- **User outcome**: Users can install the skill via a single shell command (interactively entering their relay Base URL and API Key) or by giving an AI Agent a single sentence (which installs the skill non-interactively and outputs the exact `.env` file path for the user to complete locally).
- **Recommended outcome**: **Adapt & Build**
- **Recommended solution**:
  1. Extend `src/gpt_image_cli/cli.py` and vendored `skills/gpt-image/scripts/gpt_image_cli/cli.py` to load multi-client `.env` files (`./.env`, `<skill_dir>/.env`, `${CODEX_HOME:-~/.codex}/.env`, `~/.workbuddy/.env`, `~/.codebuddy/.env`, `~/.claude/.env`, `~/.cursor/.env`, `~/.agents/.env`, `~/.env` with `override=False`), normalize relay URLs (`https://jp.xcli.si` -> `https://jp.xcli.si/v1`), add 2K/2.5K/4K resolution shortcuts, send `User-Agent: Mozilla/5.0` on pre-signed URL downloads, and support stdout-safe TUI inline image preview (`--preview auto|osc1337|kitty|open|off`, `--open`).
  2. Provide `install.sh`, `install.ps1`, and `scripts/setup_skill.py` supporting both `/dev/tty`-safe interactive setup (`curl -fsSL ... | sh`) and `--agent-mode` (`--non-interactive`) setup that seeds `~/.codex/.env` (chmod `0600`) while preserving existing keys and printing the `.env` path.
- **Why this wins**: Zero extra runtime dependencies, 100% backward-compatible with existing offline unit tests, safe against secret leakage in chat transcripts, and works standalone even when only `skills/gpt-image` is copied.
- **Decision date**: 2026-11-05

## 2. Current product baseline

- **Current behavior**:
  - `src/gpt_image_cli/cli.py` only loads `./.env` and `~/.env`, only checks `OPENAI_API_KEY`, constructs `OpenAI(max_retries=0)`, fetches `url` items without a `User-Agent` header, and prints file paths to stdout.
  - `skills/gpt-image/scripts/generate.py` falls back to `uvx --from git+https://github.com/wuyoscar/gpt_image_2_skill` when copied outside the repo checkout.
  - User's active relay configuration lives at `/Users/mixi/.codex/.env` with `OPENAI_BASE_URL=https://jp.xcli.si/v1` and `OPENAI_API_KEY=<redacted>`.
- **Constraints and non-goals**:
  - Never print, log, or ask users to paste secret API keys in AI agent chat sessions.
  - Keep `stdout` strictly limited to generated file paths so agent tool-output parsers never break.

## 3. Competitor and adjacent-product evidence

| Product / Pattern | Verified workflow/mechanism | What it solves | Better than current? | Adapt | Reject | Source/date |
|---|---|---|---|---|---|---|
| `Multi-model-sync` (`codex-model-sync`) | `install.sh` + `install.ps1` + Python stdlib interactive/non-interactive setup with `0600` permissions | Idempotent local setup with hidden API key prompt and placeholder fallback | Yes | Interactive prompt + placeholder `.env` path output | `sys.stdin.isatty()` check alone (breaks `curl \| sh` pipes) | Local repo `/Users/mixi/Downloads/myworks/xclis/Multi-model-sync`, 2026-11-05 |
| `vercel-labs/skills` (`npx skills add`) | Copies `SKILL.md` directories across `--agent` targets (`codex`, `claude-code`, `cursor`, `opencode`, `roo`, `codebuddy`) | Multi-client skill distribution | Partial | Client directory mapping table | Does not seed `.env` or configure relay `OPENAI_BASE_URL` | GitHub `vercel-labs/skills`, 2026-11-05 |
| Hermes / iTerm2 / Kitty inline images | OSC 1337 (`\033]1337;File=inline=1...`) and Kitty APC (`\033_Ga=T,f=100...`) written to `/dev/tty` | Renders generated PNGs directly inside capable TUI terminals | Yes | Opt-in/auto `/dev/tty` rendering for Kitty/Ghostty/iTerm2/WezTerm/Warp | Writing escape codes to `stdout` (corrupts agent path parsing) | iTerm2 & Kitty protocol docs, 2026-11-05 |

## 4. Client & TUI options

| Client / Surface | Skill directory | Image display mechanism | Verdict |
|---|---|---|---|
| Codex (Desktop & CLI) | `~/.codex/skills` & `~/.agents/skills` | Desktop renders Markdown `![alt](/abs/path.png)`; CLI TUI supports terminal preview via `/dev/tty` or `--open` | Support both roots |
| WorkBuddy / CodeBuddy | `~/.workbuddy/skills` & `~/.codebuddy/skills` (`~/.agents/skills` shared) | GUI chat renders Markdown `![alt](/abs/path.png)` and workspace file preview | Support both roots |
| Claude Code | `~/.claude/skills` | IDE extension renders Markdown/webview; CLI TUI uses path + optional `/dev/tty` preview | Support |
| Cursor / Cline / Roo Code | `~/.cursor/skills`, `~/.cline/skills`, `~/.roo/skills` | GUI Agent chat renders Markdown image links | Support |
| OpenCode / Pi / OpenClaw / Hermes | `~/.config/opencode/skills`, `~/.pi/agent/skills`, `~/.openclaw/skills`, `~/.hermes/skills` | TUI agents read stdout path; optional `/dev/tty` OSC 1337 / Kitty preview or `--open` | Support |

## 5. Backend, service, and open-source options

| Option | Architecture/data model | Security/integrity | Operations | Verdict |
|---|---|---|---|---|
| **Option A (Selected): Vendored CLI + Multi-path `.env` + `setup_skill.py`** | Single canonical `cli.py` mirrored into `skills/gpt-image/scripts/gpt_image_cli/`, plus stdlib installer | `0600` `.env`, `/dev/tty` hidden `getpass`, no secrets in chat or argv | Works offline once installed, works with `uv run` or `gpt-image` | **Adapt & Build** |
| Option B: `uvx` remote git fallback only | Calls `uvx --from git+...` on every run | Requires GitHub network access on cold start | Slow and fragile in restricted networks | Reject as primary |
| Option C: External TUI libraries (`rich`/`chafa`) | Extra binary/pip dependencies for terminal preview | Expands dependency surface | Breaks zero-extra-dep PEP 723 script contract | Reject |

## 6. Decision matrix

| Criterion | Weight | Option A (Vendored + Stdlib Setup) | Option B (`uvx` Only) | Option C (Extra Deps) |
|---|---:|---:|---:|---:|
| Product fit | 5 | 5 | 3 | 3 |
| User experience | 5 | 5 | 3 | 4 |
| Current-stack compatibility | 4 | 5 | 4 | 2 |
| Implementation effort | 3 | 5 | 5 | 3 |
| Maturity/maintainability | 4 | 5 | 3 | 3 |
| Accessibility/performance | 3 | 5 | 2 | 4 |
| Security/privacy/integrity | 5 | 5 | 4 | 4 |
| License/total cost | 3 | 5 | 5 | 4 |
| Operational burden/lock-in | 4 | 5 | 3 | 3 |
| Reversibility | 4 | 5 | 5 | 3 |

## 7. Recommended design

- **`.env` loading order (`override=False`)**:
  `process.env` → `./.env` → `<skill_dir>/.env` → `${CODEX_HOME:-~/.codex}/.env` → `~/.workbuddy/.env` → `~/.codebuddy/.env` → `~/.claude/.env` → `~/.cursor/.env` → `~/.agents/.env` → `~/.env`.
- **Variable & flag precedence**:
  - API Key: `--api-key` → `GPT_IMAGE_API_KEY` → `OPENAI_API_KEY` → `XCLI_API_KEY`.
  - Base URL: `--base-url` → `GPT_IMAGE_BASE_URL` → `OPENAI_BASE_URL` → `XCLI_BASE_URL` → `BASE_URL`.
  - Base URL normalization: strips trailing `/`, strips `/v1/images/generations` or `/v1/images/edits` or `/v1/chat/completions`, appends `/v1` when path is empty (so `https://jp.xcli.si` and `https://jp.xcli.si/v1` both resolve to `https://jp.xcli.si/v1`).
- **TUI preview (`--preview auto|osc1337|kitty|open|off`, `--open`)**:
  - Default `off` when invoked by non-TTY subshells; when `--preview auto` (or `GPT_IMAGE_PREVIEW=auto`) is used in an interactive terminal, detects Kitty/Ghostty (`kitty` protocol) or iTerm2/WezTerm/Warp/Konsole (`osc1337` protocol) and writes the inline image sequence directly to `/dev/tty`, keeping `stdout` strictly limited to the output file path(s).

## 8. Risks, unknowns, and authority needed

| Risk | Evidence | Mitigation | Needs user decision? |
|---|---|---|---|
| `curl \| sh` consumes stdin | `Anscombe` packet | Open `/dev/tty` explicitly for interactive prompts; fall back to `--agent-mode` if `/dev/tty` is unavailable | No |
| Pre-signed image URLs return HTTP 403 | `docsGptImage.ts` & `Pasteur` packet | Pass `User-Agent: Mozilla/5.0` in `urllib.request.Request` | No |
| Standalone skill copy lacks `src/gpt_image_cli` | `Pasteur` packet | Vendor `gpt_image_cli` into `skills/gpt-image/scripts/gpt_image_cli/` and enforce byte-identity in unit tests | No |

## 9. Acceptance criteria

- [x] Forked repository exists at `https://github.com/Masikomoore/GPT-Image2-Skill`.
- [ ] `cli.py` and `generate.py` load `/Users/mixi/.codex/.env` (`OPENAI_BASE_URL` and `OPENAI_API_KEY`), normalize relay base URLs, support 2K/2.5K/4K shortcuts, fetch URLs with `User-Agent`, and support `--preview` / `--open`.
- [ ] `install.sh`, `install.ps1`, and `scripts/setup_skill.py` support interactive one-line installation and non-interactive AI Agent installation across Codex, WorkBuddy, Claude Code, Cursor, Cline, Roo Code, OpenCode, Pi, OpenClaw, Hermes, and AgentSkills.
- [ ] All existing and new unit tests pass (`unittest discover -s tests -v`).
- [ ] Local installed skills in `/Users/mixi/.codex/skills/` and `/Users/mixi/.agents/skills/` are updated and verified, and changes are pushed to `https://github.com/Masikomoore/GPT-Image2-Skill`.

## 10. Implementation plan

1. Update `src/gpt_image_cli/cli.py` and sync to `skills/gpt-image/scripts/gpt_image_cli/cli.py` + `skills/gpt-image/scripts/generate.py` → verify with unit tests.
2. Add `scripts/setup_skill.py`, `install.sh`, and `install.ps1` → verify interactive `/dev/tty` simulation and `--agent-mode` `.env` seeding in temp dirs.
3. Update `skills/gpt-image/SKILL.md`, `skills/gpt-image/references/models.md`, `README.md`, `README.zh.md`, `pyproject.toml`, and `.claude-plugin/` → verify skill validation and full test suite.
4. Sync updated skills to local `~/.codex/skills` and `~/.agents/skills`, commit, and push to `Masikomoore/GPT-Image2-Skill` → verify remote state and subagent audit.

## 11. Sources and research record

- Research date: 2026-11-05
- Luna worker packets and terminal states:
  - `01a1ad6a-58a6-72d3-8686-bdab14ff9307` (`Anscombe` - `luna_worker`): completed & closed.
  - `01a1ad6a-59a7-7523-a547-051078a70a7b` (`Bernoulli` - `luna_worker`): completed & closed.
  - `01a1ad6a-59e8-7791-9512-f9d966fa7e3b` (`Pasteur` - `luna_worker`): completed & closed.
- Official & local sources: `/Users/mixi/.codex/.env` (keys only), `/Users/mixi/Downloads/myworks/xclis/xclis-frontend/src/data/docsGptImage.ts`, `/Users/mixi/Downloads/myworks/xclis/xclis-frontend/src/data/docsIntegrations.ts`, `/Users/mixi/Downloads/myworks/xclis/Multi-model-sync`.
