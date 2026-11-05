"""Tests for multi-client installer and .env management in scripts/setup_skill.py."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("setup_skill", ROOT / "scripts" / "setup_skill.py")
setup_skill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup_skill)


class SetupSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.enterContext(patch.dict("os.environ", {}, clear=True))

    def test_agent_mode_creates_env_placeholder_and_installs_skills(self):
        env_path = self.home / ".codex" / ".env"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = setup_skill.main([
                "--repo-root", str(ROOT),
                "--home", str(self.home),
                "--agent-mode",
                "--clients", "codex,workbuddy,agents",
                "--env-path", str(env_path),
            ])
        self.assertEqual(rc, 0)
        self.assertTrue(env_path.is_file())
        env_text = env_path.read_text(encoding="utf-8")
        self.assertIn("OPENAI_BASE_URL=https://jp.xcli.si/v1", env_text)
        self.assertIn("OPENAI_API_KEY=YOUR_API_KEY_HERE", env_text)

        for rel in (".codex/skills/gpt-image", ".workbuddy/skills/gpt-image", ".agents/skills/gpt-image"):
            skill_dir = self.home / rel
            self.assertTrue((skill_dir / "SKILL.md").is_file(), f"Missing SKILL.md in {skill_dir}")
            self.assertTrue((skill_dir / "scripts" / "generate.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "gpt_image_cli" / "cli.py").is_file())

        stdout_text = out.getvalue()
        self.assertIn(f"ENV_FILE={env_path.resolve()}", stdout_text)
        self.assertIn("OPENAI_API_KEY=待填写", stdout_text)

    def test_agent_mode_preserves_existing_real_api_key(self):
        env_path = self.home / ".codex" / ".env"
        env_path.parent.mkdir(parents=True)
        env_path.write_text(
            "OPENAI_BASE_URL=https://jp.xcli.si/v1\nOPENAI_API_KEY=real-secret-token-xyz\n",
            encoding="utf-8",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = setup_skill.main([
                "--repo-root", str(ROOT),
                "--home", str(self.home),
                "--agent-mode",
                "--clients", "codex",
                "--env-path", str(env_path),
            ])
        self.assertEqual(rc, 0)
        env_text = env_path.read_text(encoding="utf-8")
        self.assertIn("OPENAI_API_KEY=real-secret-token-xyz", env_text)
        self.assertIn("OPENAI_API_KEY=已配置", out.getvalue())


if __name__ == "__main__":
    unittest.main()
