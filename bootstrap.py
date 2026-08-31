#!/usr/bin/env python3
"""Prepare catalog, sidecar, Ollama, and optional Chainlit.

Stdlib only. Safe to run before any pip extras are installed. When ``ollama``
is missing, this script tries to install the CLI (Windows winget / official
installer, macOS Homebrew, Linux install.sh) and then pulls the NLU model.

From this directory (contest zip) or via the kit ``scripts/`` wrappers:

    python bootstrap.py --check
    python bootstrap.py --extras demo
    python bootstrap.py --extras demo --run demo
    python bootstrap.py --extras all --warm-index
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _project_root(submission: Path) -> Path:
    parent = submission.resolve().parent
    if (parent / "evaluator").is_dir() and (parent / "starter").is_dir():
        return parent
    return submission.resolve()


SUBMISSION = Path(__file__).resolve().parent
ROOT = _project_root(SUBMISSION)
CATALOG = ROOT / "data" / "catalog.jsonl"
PUBLIC_SET = ROOT / "data" / "public_set.jsonl"
SLOTS = ROOT / ".cache" / "catalog_preprocess" / "product_slots.sqlite3"
NLU_ENV = SUBMISSION / "src" / "assets" / "nlu.env"
DEMO_DIR = SUBMISSION / "demo"
CHAINLIT_CONFIG = DEMO_DIR / ".chainlit" / "config.toml"
ALIASES_DIR = SUBMISSION / "src" / "assets" / "aliases"
DEFAULT_NLU_MODEL = "qwen3.5:4b"
DEFAULT_NLU_HOST = "http://127.0.0.1:11434"
DEFAULT_CHAINLIT_PORT = 8006
OLLAMA_DOWNLOAD = "https://ollama.com/download"
OLLAMA_WINDOWS_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_INSTALL_SH = "https://ollama.com/install.sh"
OLLAMA_INSTALL_TIMEOUT_S = 1200
OLLAMA_DOWNLOAD_TIMEOUT_S = 600
REQUIRED_ALIAS_FILES = (
    "color_aliases.json",
    "material_aliases.json",
    "category_tree.json",
    "category_parents.json",
)
CHAINLIT_PUBLIC_FILES = (
    DEMO_DIR / "public" / "stylesheet.css",
    DEMO_DIR / "public" / "eval-composer.js",
    DEMO_DIR / "public" / "logo_dark.png",
    DEMO_DIR / "public" / "elements" / "PipelineCircuit.jsx",
    DEMO_DIR / "public" / "elements" / "ProductShelf.jsx",
    DEMO_DIR / "public" / "elements" / "EvalDock.jsx",
)

EXTRA_FILES = {
    "demo": SUBMISSION / "requirements-demo.txt",
    "reranker": SUBMISSION / "requirements-reranker.txt",
    "preprocess": SUBMISSION / "requirements-preprocess.txt",
}
ALL_EXTRAS = ("demo", "reranker", "preprocess")
RUN_CHOICES = ("none", "demo", "eval", "tests", "console")


def ensure_import_path() -> None:
    for path in (ROOT, SUBMISSION):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def log(message: str) -> None:
    print(message, flush=True)


def step(title: str) -> None:
    log(f"\n==> {title}")


def parse_extras(values: list[str]) -> list[str]:
    """Expand comma-separated --extras tokens. ``all`` / ``dev`` mean every extra."""

    tokens: list[str] = []
    for value in values:
        tokens.extend(
            part.strip().casefold() for part in value.split(",") if part.strip()
        )
    if any(token in {"all", "dev"} for token in tokens):
        return list(ALL_EXTRAS)
    unknown = [token for token in tokens if token not in EXTRA_FILES]
    if unknown:
        raise SystemExit(
            f"Unknown extras {unknown}. Use demo, reranker, preprocess, all, or dev."
        )
    ordered: list[str] = []
    for token in tokens:
        if token not in ordered:
            ordered.append(token)
    return ordered


def requirement_files(extras: list[str]) -> list[Path]:
    if extras == list(ALL_EXTRAS):
        return [SUBMISSION / "requirements-dev.txt"]
    if extras:
        return [EXTRA_FILES[name] for name in extras]
    return [SUBMISSION / "requirements.txt"]


def load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            loaded[key] = value
    return loaded


def apply_env_file(path: Path, *, overwrite: bool = False) -> dict[str, str]:
    loaded = load_env_file(path)
    for key, value in loaded.items():
        if key in os.environ and os.environ[key] != "" and not overwrite:
            continue
        os.environ[key] = value
    return loaded


def python_ok() -> tuple[bool, str]:
    version = sys.version.split()[0]
    ok = sys.version_info >= (3, 10)
    return ok, f"Python {version} ({sys.executable})"


def fts5_ok() -> tuple[bool, str]:
    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return False, f"SQLite FTS5 unavailable: {exc}"
    return True, f"SQLite FTS5 ok ({sqlite3.sqlite_version})"


def import_ok(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def ollama_install_dirs() -> list[Path]:
    """Usual Windows locations after a user-scope or Program Files install."""

    if sys.platform != "win32":
        return []
    directories: list[Path] = []
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        directories.append(Path(local_app) / "Programs" / "Ollama")
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    if program_files:
        directories.append(Path(program_files) / "Ollama")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    if program_files_x86:
        directories.append(Path(program_files_x86) / "Ollama")
    return directories


def prepend_ollama_path() -> None:
    if sys.platform != "win32":
        return
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    prefix: list[str] = []
    for directory in ollama_install_dirs():
        text = str(directory)
        if directory.is_dir() and text not in parts and text not in prefix:
            prefix.append(text)
    if prefix:
        os.environ["PATH"] = os.pathsep.join(prefix + ([current] if current else []))


def _run_command(command: list[str], *, timeout: int) -> int:
    log(" ".join(command))
    try:
        return subprocess.call(command, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"timed out after {timeout}s: {' '.join(command)}")
        return 1
    except OSError as exc:
        log(f"failed to run {command[0]}: {exc}")
        return 1


def _download_file(url: str, dest: Path, timeout: float = OLLAMA_DOWNLOAD_TIMEOUT_S) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "converge-shopping-copilot-setup"},
        method="GET",
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response, dest.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _install_ollama_windows_setup_exe() -> tuple[bool, str]:
    dest = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    log(f"Downloading {OLLAMA_WINDOWS_SETUP_URL} ...")
    try:
        _download_file(OLLAMA_WINDOWS_SETUP_URL, dest)
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return False, f"could not download Ollama installer: {exc}"
    log("Running OllamaSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART")
    proc = None
    try:
        proc = subprocess.Popen(
            [str(dest), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        )
        code = proc.wait(timeout=OLLAMA_INSTALL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
        return False, "OllamaSetup.exe timed out"
    except OSError as exc:
        return False, f"OllamaSetup.exe failed: {exc}"
    time.sleep(2)
    prepend_ollama_path()
    binary = shutil.which("ollama")
    if binary:
        return True, f"installed Ollama via OllamaSetup.exe: {binary}"
    return (
        False,
        f"OllamaSetup.exe exited {code} but ollama is still not on PATH. "
        f"Install from {OLLAMA_DOWNLOAD}",
    )


def _install_ollama_windows() -> tuple[bool, str]:
    winget = shutil.which("winget")
    if winget:
        log("Installing Ollama with winget (Ollama.Ollama)...")
        _run_command(
            [
                winget,
                "install",
                "-e",
                "--id",
                "Ollama.Ollama",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            timeout=OLLAMA_INSTALL_TIMEOUT_S,
        )
        prepend_ollama_path()
        binary = shutil.which("ollama")
        if binary:
            return True, f"installed Ollama via winget: {binary}"
        log("winget did not put ollama on PATH; trying the official installer")
    return _install_ollama_windows_setup_exe()


def _install_ollama_macos() -> tuple[bool, str]:
    brew = shutil.which("brew")
    if brew:
        log("Installing Ollama with Homebrew...")
        _run_command([brew, "install", "ollama"], timeout=OLLAMA_INSTALL_TIMEOUT_S)
        binary = shutil.which("ollama")
        if binary:
            return True, f"installed Ollama via Homebrew: {binary}"
        log("brew install ollama finished but ollama is not on PATH")
    return (
        False,
        f"Could not auto-install Ollama on macOS. Install from {OLLAMA_DOWNLOAD} "
        "or: brew install ollama",
    )


def _install_ollama_unix() -> tuple[bool, str]:
    curl = shutil.which("curl")
    if not curl:
        return False, f"curl not found; install Ollama from {OLLAMA_DOWNLOAD}"
    log(f"Downloading official {OLLAMA_INSTALL_SH}")
    try:
        downloaded = subprocess.run(
            [curl, "-fsSL", OLLAMA_INSTALL_SH],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not download install.sh: {exc}"
    if downloaded.returncode != 0:
        err = (downloaded.stderr or b"").decode("utf-8", "replace")[:400]
        return False, f"download install.sh failed: {err}"
    log("Running Ollama install.sh (may prompt for sudo)")
    try:
        completed = subprocess.run(
            ["sh", "-s"],
            input=downloaded.stdout,
            timeout=OLLAMA_INSTALL_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"install.sh failed: {exc}"
    binary = shutil.which("ollama")
    if binary:
        return True, f"installed Ollama via install.sh: {binary}"
    return (
        False,
        f"install.sh exited {completed.returncode}; install from {OLLAMA_DOWNLOAD}",
    )


def install_ollama_binary() -> tuple[bool, str]:
    """Install the Ollama CLI when missing. Never raises; setup can still continue."""

    prepend_ollama_path()
    existing = shutil.which("ollama")
    if existing:
        return True, f"ollama already installed: {existing}"
    log("Ollama executable not found. Attempting automatic install...")
    if sys.platform == "win32":
        return _install_ollama_windows()
    if sys.platform == "darwin":
        return _install_ollama_macos()
    return _install_ollama_unix()


def nlu_settings() -> tuple[str, str]:
    apply_env_file(NLU_ENV)
    host = os.environ.get("AGENT_NLU_HOST", DEFAULT_NLU_HOST).strip() or DEFAULT_NLU_HOST
    model = os.environ.get("AGENT_NLU_MODEL", DEFAULT_NLU_MODEL).strip() or DEFAULT_NLU_MODEL
    return host.rstrip("/"), model


def ollama_tags(host: str, timeout: float = 2.0) -> list[str] | None:
    request = urllib.request.Request(host + "/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    names: list[str] = []
    for item in payload.get("models") or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def model_present(names: list[str], model: str) -> bool:
    wanted = model.casefold()
    for name in names:
        folded = name.casefold()
        if folded == wanted or folded.startswith(wanted):
            return True
    return False


def spawn_ollama_serve() -> str | None:
    binary = shutil.which("ollama")
    if not binary:
        return "ollama executable not found"
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([binary, "serve"], **kwargs)
    except OSError as exc:
        return f"failed to spawn ollama serve: {exc}"
    return None


def wait_for_ollama(host: str, seconds: float = 20.0) -> list[str] | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        names = ollama_tags(host)
        if names is not None:
            return names
        time.sleep(0.4)
    return None


def sidecar_current() -> tuple[bool, str]:
    if not CATALOG.is_file():
        return False, f"catalog missing: {CATALOG}"
    if not SLOTS.is_file():
        return False, f"sidecar missing: {SLOTS}"
    ensure_import_path()
    from src.retrieve.catalog.slots_sidecar import catalog_fingerprint, sidecar_is_current

    fingerprint = catalog_fingerprint(CATALOG)
    if sidecar_is_current(SLOTS, fingerprint):
        return True, f"current sidecar {SLOTS}"
    return False, f"stale sidecar {SLOTS}"


def run_python(args: list[str], *, cwd: Path | None = None) -> int:
    return subprocess.call([sys.executable, *args], cwd=str(cwd or ROOT))


def requirement_has_specs(path: Path) -> bool:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def pip_install(files: list[Path]) -> None:
    for path in files:
        label = str(path)
        try:
            label = str(path.relative_to(ROOT))
        except ValueError:
            pass
        if not requirement_has_specs(path):
            log(f"Skipping empty requirements file {label}")
            continue
        log(f"pip install -r {label}")
        code = run_python(["-m", "pip", "install", "--disable-pip-version-check", "-r", str(path)])
        if code != 0:
            raise SystemExit(f"pip failed for {path} (exit {code})")


def ensure_dotenv_example() -> None:
    example = ROOT / ".env.example"
    target = ROOT / ".env"
    if example.is_file() and not target.is_file():
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        log(f"Copied {example.name} -> {target.name} (fill in keys only if you use Scenario modes 2-4)")


def ensure_catalog(*, force: bool) -> None:
    if CATALOG.is_file() and not force:
        log(f"Catalog already present: {CATALOG}")
        return
    log("Downloading the official 50,000-product catalog (SHA-256 verified)...")
    command = [str(SUBMISSION / "download_catalog.py"), "--output", str(CATALOG)]
    if force:
        command.append("--force")
    code = run_python(command)
    if code != 0:
        raise SystemExit(f"catalog download failed (exit {code})")


def ensure_sidecar(*, force: bool) -> None:
    current, detail = sidecar_current()
    if current and not force:
        log(detail)
        return
    log("Building the product-slot sidecar. This can take a few minutes...")
    if not current:
        log(detail)
    code = run_python(
        [
            str(SUBMISSION / "extract_slots.py"),
            "--catalog",
            str(CATALOG),
            "--output",
            str(SLOTS),
        ]
    )
    if code != 0:
        raise SystemExit(f"sidecar build failed (exit {code})")


def warm_index() -> None:
    ensure_import_path()
    from src.retrieve.catalog.index_path import resolve_index_path
    from src.retrieve.catalog.retriever import CatalogRetriever

    index_path = resolve_index_path(CATALOG)
    log(f"Warming FTS/signature index at {index_path}. First build can take several minutes...")
    retriever = CatalogRetriever(CATALOG, index_path=index_path)
    count = len(retriever)
    retriever.close()
    log(f"Index ready ({count} products)")


def ensure_ollama(*, skip: bool, pull: bool) -> tuple[bool, str]:
    if skip:
        return True, "Ollama check skipped"
    prepend_ollama_path()
    host, model = nlu_settings()
    names = ollama_tags(host)
    if shutil.which("ollama") is None and names is None:
        installed, install_detail = install_ollama_binary()
        log(install_detail)
        prepend_ollama_path()
        if not installed:
            return (
                False,
                f"Ollama not found. Auto-install failed. Install from {OLLAMA_DOWNLOAD}, "
                f"then: ollama pull {model}",
            )
    binary = shutil.which("ollama")
    names = ollama_tags(host)
    if names is None:
        if not binary:
            return (
                False,
                f"Ollama not found. Install it from {OLLAMA_DOWNLOAD}, then: ollama pull {model}",
            )
        log("Starting ollama serve...")
        error = spawn_ollama_serve()
        if error:
            return False, error
        names = wait_for_ollama(host)
        if names is None:
            return False, f"Ollama did not become ready at {host}"
    if model_present(names, model):
        return True, f"Ollama ready at {host} with {model}"
    if not pull:
        return False, f"Ollama is up but {model} is not installed. Run: ollama pull {model}"
    log(f"Pulling Ollama model {model} (large download on first run)...")
    binary = shutil.which("ollama")
    if not binary:
        return False, f"ollama executable not found; cannot pull {model}"
    code = subprocess.call([binary, "pull", model])
    if code != 0:
        return False, f"ollama pull {model} failed (exit {code})"
    names = ollama_tags(host) or []
    if model_present(names, model):
        return True, f"Ollama ready at {host} with {model}"
    return False, f"Pulled {model} but /api/tags does not list it yet"


def aliases_ok() -> tuple[bool, str]:
    missing = [name for name in REQUIRED_ALIAS_FILES if not (ALIASES_DIR / name).is_file()]
    if missing:
        return False, f"missing alias files: {', '.join(missing)}"
    return True, str(ALIASES_DIR)


def chainlit_app_root_ok() -> tuple[bool, str]:
    """Canonical Chainlit APP_ROOT is submission/demo/; repo-root .chainlit is unused."""

    if not CHAINLIT_CONFIG.is_file():
        return False, f"missing {CHAINLIT_CONFIG.relative_to(ROOT)}"
    missing = [
        str(path.relative_to(ROOT)) for path in CHAINLIT_PUBLIC_FILES if not path.is_file()
    ]
    if missing:
        return False, f"missing demo public assets: {', '.join(missing)}"
    return True, f"APP_ROOT={DEMO_DIR} ({CHAINLIT_CONFIG.relative_to(ROOT)})"


def discard_stale_root_chainlit(root: Path | None = None) -> bool:
    """Delete a leftover project-root ``.chainlit/``. Never touches the demo APP_ROOT."""

    base = (root or ROOT).resolve()
    stale = (base / ".chainlit").resolve()
    protected = (base / "submission" / "demo" / ".chainlit").resolve()
    if not protected.exists():
        protected = (base / "demo" / ".chainlit").resolve()
    if stale == protected or stale.name != ".chainlit" or stale.parent != base:
        return False
    if not stale.exists():
        return False
    try:
        shutil.rmtree(stale)
    except OSError as exc:
        log(f"WARNING: could not remove {stale}: {exc}; using {protected}")
        return False
    log(f"Removed unused {stale}; canonical config is {protected / 'config.toml'}")
    return True


def print_check(extras: list[str]) -> int:
    step("Environment check")
    rows: list[tuple[str, bool, str]] = []
    ok, detail = python_ok()
    rows.append(("python", ok, detail))
    ok, detail = fts5_ok()
    rows.append(("fts5", ok, detail))
    rows.append(("catalog", CATALOG.is_file(), str(CATALOG)))
    rows.append(("public_set", PUBLIC_SET.is_file(), str(PUBLIC_SET)))
    rows.append(("nlu.env", NLU_ENV.is_file(), str(NLU_ENV)))
    ok, detail = aliases_ok()
    rows.append(("aliases", ok, detail))
    current, detail = sidecar_current() if CATALOG.is_file() else (False, "catalog missing")
    rows.append(("sidecar", current, detail))
    rows.append(("chainlit", import_ok("chainlit"), "import chainlit"))
    ok, detail = chainlit_app_root_ok()
    rows.append(("demo_ui", ok, detail))
    rows.append(
        (
            "reranker",
            import_ok("sentence_transformers"),
            "import sentence_transformers",
        )
    )
    rows.append(("pandas", import_ok("pandas"), "import pandas (alias rebuild only)"))
    prepend_ollama_path()
    host, model = nlu_settings()
    names = ollama_tags(host)
    if names is None:
        rows.append(("ollama", False, f"not reachable at {host}"))
    else:
        rows.append(("ollama", model_present(names, model), f"{host} model={model}"))
    requested = ", ".join(extras) if extras else "(core only)"
    log(f"Requested extras: {requested}")
    failed = 0
    for name, passed, text in rows:
        mark = "OK" if passed else "MISSING"
        if not passed:
            failed += 1
        log(f"  [{mark:<7}] {name:<10} {text}")
    log("\nNext:")
    log("  python bootstrap.py --extras demo")
    log("  python bootstrap.py --extras demo --run demo")
    log("  powershell -ExecutionPolicy Bypass -File setup.ps1")
    return 0 if rows[0][1] and rows[1][1] else 1


def launch(kind: str, port: int) -> int:
    apply_env_file(NLU_ENV)
    if kind == "demo":
        if not import_ok("chainlit"):
            raise SystemExit("chainlit is not installed. Re-run with --extras demo")
        ok, detail = chainlit_app_root_ok()
        if not ok:
            raise SystemExit(detail)
        discard_stale_root_chainlit()
        # Chainlit sets APP_ROOT from getcwd() / CHAINLIT_APP_ROOT at import.
        # Always pin submission/demo so a leftover repo-root .chainlit is never used.
        env = os.environ.copy()
        env["CHAINLIT_APP_ROOT"] = str(DEMO_DIR)
        log(
            f"Starting Chainlit on http://localhost:{port} "
            f"(cwd=demo, APP_ROOT={DEMO_DIR})"
        )
        if port != 8005:
            log(
                "Close any leftover tab on http://localhost:8005 — that origin "
                "caches the old Chainlit shell."
            )
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "chainlit",
                "run",
                "chainlit_app.py",
                "-w",
                "--port",
                str(port),
            ],
            cwd=str(DEMO_DIR),
            env=env,
        )
    if kind == "eval":
        evaluator = ROOT / "evaluator" / "local_evaluator.py"
        if not evaluator.is_file() or not PUBLIC_SET.is_file():
            raise SystemExit(
                "Public-set eval needs the kit evaluator/ package and "
                f"data/public_set.jsonl (missing {evaluator if not evaluator.is_file() else PUBLIC_SET})"
            )
        log("Running the public-set local evaluator (this can take a long time)...")
        return run_python(
            [
                "-m",
                "evaluator.local_evaluator",
                "--catalog",
                str(CATALOG),
                "--dataset",
                str(PUBLIC_SET),
                "--output",
                str(ROOT / "results.json"),
            ]
        )
    if kind == "tests":
        tests_dir = ROOT / "tests"
        if not tests_dir.is_dir():
            raise SystemExit("unittest discovery needs the kit tests/ directory")
        log("Running unittest discovery in tests/")
        return run_python(["-m", "unittest", "discover", "-s", "tests", "-v"])
    if kind == "console":
        return run_python([str(SUBMISSION / "nlu_console.py")])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extras",
        action="append",
        default=[],
        help="demo, reranker, preprocess, all, or dev. Repeatable or comma-separated.",
    )
    parser.add_argument("--check", action="store_true", help="Print readiness and exit")
    parser.add_argument("--skip-pip", action="store_true")
    parser.add_argument("--skip-catalog", action="store_true")
    parser.add_argument("--skip-sidecar", action="store_true")
    parser.add_argument("--skip-ollama", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--force-catalog", action="store_true")
    parser.add_argument("--force-sidecar", action="store_true")
    parser.add_argument(
        "--warm-index",
        action="store_true",
        help="Build or reuse the FTS/signature index before launch",
    )
    parser.add_argument(
        "--run",
        choices=RUN_CHOICES,
        default="none",
        help="demo starts Chainlit; eval runs the public harness; tests/console as named",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_CHAINLIT_PORT,
        help="Chainlit port for --run demo (default 8006; 8005 may be a cached old shell)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    os.chdir(ROOT)
    ensure_import_path()
    args = build_parser().parse_args(argv)
    extras = parse_extras(args.extras)
    if args.run == "demo" and "demo" not in extras:
        extras.append("demo")
    if args.run == "tests" and "demo" not in extras:
        extras.append("demo")

    if args.check:
        return print_check(extras)

    py_ok, py_detail = python_ok()
    log(py_detail)
    if not py_ok:
        raise SystemExit("Python 3.10 or newer is required")
    sqlite_ok, sqlite_detail = fts5_ok()
    log(sqlite_detail)
    if not sqlite_ok:
        raise SystemExit("SQLite FTS5 is required")

    if not args.skip_pip:
        step("Install Python packages")
        files = requirement_files(extras)
        core = SUBMISSION / "requirements.txt"
        if extras and core not in files:
            files = [core, *files]
        pip_install(files)
    else:
        log("Skipping pip")

    ensure_dotenv_example()

    if not args.skip_catalog:
        step("Catalog")
        ensure_catalog(force=args.force_catalog)
    if not PUBLIC_SET.is_file():
        log(f"WARNING: {PUBLIC_SET} is missing; local evaluation will not run")

    if not args.skip_sidecar:
        if not CATALOG.is_file():
            log("Skipping sidecar; catalog is missing")
        else:
            step("Slot sidecar")
            ensure_sidecar(force=args.force_sidecar)

    step("Ollama NLU")
    ollama_ok, ollama_detail = ensure_ollama(skip=args.skip_ollama, pull=not args.skip_ollama)
    log(ollama_detail)
    if not ollama_ok:
        log(
            "Understand will fall back to regex after failed NLU attempts. "
            f"Install Ollama from {OLLAMA_DOWNLOAD} for the default live path."
        )

    should_warm = args.warm_index or args.run in {"demo", "eval"}
    if should_warm and not args.skip_index:
        if not CATALOG.is_file():
            log("Skipping index warm; catalog is missing")
        else:
            step("Catalog index")
            warm_index()

    if args.run in {"demo", "eval"} and not CATALOG.is_file():
        raise SystemExit(
            f"Catalog not found: {CATALOG}. Re-run without --skip-catalog "
            "or python download_catalog.py"
        )

    if args.run == "none":
        step("Ready")
        log("Core setup finished. Useful next commands:")
        log("  python bootstrap.py --extras demo --run demo")
        log("  python nlu_console.py")
        if (ROOT / "evaluator" / "local_evaluator.py").is_file():
            log("  python -m evaluator.local_evaluator --catalog data/catalog.jsonl --dataset data/public_set.jsonl --output results.json")
            log("  python -m unittest discover -s tests -v")
        return 0

    step(f"Run {args.run}")
    return launch(args.run, args.port)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        raise SystemExit(130)
