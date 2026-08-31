from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "converge_bootstrap",
        ROOT / "scripts" / "bootstrap.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap_mod = _load_bootstrap()


class BootstrapExtrasTest(unittest.TestCase):
    def test_parse_extras_empty(self) -> None:
        self.assertEqual(bootstrap_mod.parse_extras([]), [])

    def test_parse_extras_comma_and_repeat(self) -> None:
        self.assertEqual(
            bootstrap_mod.parse_extras(["demo", "reranker,preprocess"]),
            ["demo", "reranker", "preprocess"],
        )

    def test_parse_extras_all_and_dev(self) -> None:
        self.assertEqual(bootstrap_mod.parse_extras(["all"]), ["demo", "reranker", "preprocess"])
        self.assertEqual(bootstrap_mod.parse_extras(["dev"]), ["demo", "reranker", "preprocess"])

    def test_parse_extras_unknown(self) -> None:
        with self.assertRaises(SystemExit):
            bootstrap_mod.parse_extras(["torch"])

    def test_requirement_files_core_and_dev(self) -> None:
        self.assertEqual(
            bootstrap_mod.requirement_files([]),
            [ROOT / "requirements.txt"],
        )
        self.assertEqual(
            bootstrap_mod.requirement_files(["demo", "reranker", "preprocess"]),
            [ROOT / "requirements-dev.txt"],
        )
        self.assertEqual(
            bootstrap_mod.requirement_files(["demo"]),
            [ROOT / "requirements-demo.txt"],
        )


class BootstrapHelpTest(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--extras", result.stdout)
        self.assertIn("--run", result.stdout)

    def test_check_reports_python(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("[OK", result.stdout)
        self.assertIn("python", result.stdout)
        self.assertIn("fts5", result.stdout)


class BootstrapHelpersTest(unittest.TestCase):
    def test_model_present(self) -> None:
        self.assertTrue(bootstrap_mod.model_present(["qwen3.5:4b"], "qwen3.5:4b"))
        self.assertTrue(
            bootstrap_mod.model_present(["qwen3.5:4b-q8_0"], "qwen3.5:4b")
        )
        self.assertFalse(bootstrap_mod.model_present(["llama3.2:3b"], "qwen3.5:4b"))

    def test_load_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nlu.env"
            path.write_text(
                "# comment\nAGENT_NLU_MODEL=probe-model\n\nAGENT_NLU_HOST=http://127.0.0.1:11434\n",
                encoding="utf-8",
            )
            loaded = bootstrap_mod.load_env_file(path)
        self.assertEqual(loaded["AGENT_NLU_MODEL"], "probe-model")
        self.assertEqual(loaded["AGENT_NLU_HOST"], "http://127.0.0.1:11434")

    def test_empty_requirements_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text("# comments only\n", encoding="utf-8")
            self.assertFalse(bootstrap_mod.requirement_has_specs(path))
            with patch.object(bootstrap_mod, "run_python") as run_python:
                bootstrap_mod.pip_install([path])
            run_python.assert_not_called()

    def test_python_and_fts5_ok(self) -> None:
        ok, detail = bootstrap_mod.python_ok()
        self.assertTrue(ok, detail)
        ok, detail = bootstrap_mod.fts5_ok()
        self.assertTrue(ok, detail)

    def test_run_demo_implies_demo_extra(self) -> None:
        with patch.object(bootstrap_mod, "print_check", return_value=0) as check:
            code = bootstrap_mod.main(["--check", "--run", "demo"])
        self.assertEqual(code, 0)
        check.assert_called_once_with(["demo"])

    def test_aliases_and_chainlit_app_root_ok(self) -> None:
        ok, detail = bootstrap_mod.aliases_ok()
        self.assertTrue(ok, detail)
        ok, detail = bootstrap_mod.chainlit_app_root_ok()
        self.assertTrue(ok, detail)
        self.assertIn("demo", detail)
        self.assertTrue((ROOT / "demo" / ".chainlit" / "config.toml").is_file())

    def test_discard_stale_root_chainlit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            stale = base / ".chainlit"
            (stale / "translations").mkdir(parents=True)
            (stale / "config.toml").write_text('name = "Assistant"\n', encoding="utf-8")
            protected = base / "demo" / ".chainlit"
            protected.mkdir(parents=True)
            (protected / "config.toml").write_text(
                'name = "Shopping Copilot"\n', encoding="utf-8"
            )
            self.assertTrue(bootstrap_mod.discard_stale_root_chainlit(base))
            self.assertFalse(stale.exists())
            self.assertTrue((protected / "config.toml").is_file())
            self.assertFalse(bootstrap_mod.discard_stale_root_chainlit(base))

    def test_launch_demo_pins_demo_app_root(self) -> None:
        with (
            patch.object(bootstrap_mod, "import_ok", return_value=True),
            patch.object(bootstrap_mod, "apply_env_file"),
            patch.object(bootstrap_mod.subprocess, "call", return_value=0) as call,
        ):
            code = bootstrap_mod.launch("demo", 8005)
        self.assertEqual(code, 0)
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["cwd"], str(ROOT / "demo"))
        self.assertEqual(kwargs["env"]["CHAINLIT_APP_ROOT"], str(ROOT / "demo"))
        self.assertEqual(call.call_args.args[0][7], "8005")

    def test_default_demo_port(self) -> None:
        self.assertEqual(bootstrap_mod.DEFAULT_CHAINLIT_PORT, 8006)
        parser = bootstrap_mod.build_parser()
        self.assertEqual(parser.parse_args([]).port, 8006)


if __name__ == "__main__":
    unittest.main()
