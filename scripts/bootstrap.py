#!/usr/bin/env python3
"""Prepare a local Converge checkout: extras, catalog, sidecar, Ollama, optional launch.

Stdlib only. Safe to run before any pip extras are installed.

Examples (from repo root, preferably inside a venv):

    python scripts/bootstrap.py --check
    python scripts/bootstrap.py --extras demo
    python scripts/bootstrap.py --extras demo --run demo
    python scripts/bootstrap.py --extras all --warm-index
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "catalog.jsonl"
PUBLIC_SET = ROOT / "data" / "public_set.jsonl"
SLOTS = ROOT / ".cache" / "catalog_preprocess" / "product_slots.sqlite3"
NLU_ENV = ROOT / "scripts" / "nlu.env"
DEMO_DIR = ROOT / "demo"
CHAINLIT_CONFIG = DEMO_DIR / ".chainlit" / "config.toml"
ALIASES_DIR = ROOT / "scripts" / "catalog_preprocess" / "aliases"
DEFAULT_NLU_MODEL = "qwen3.5:4b"
DEFAULT_NLU_HOST = "http://127.0.0.1:11434"
DEFAULT_CHAINLIT_PORT = 8006
OLLAMA_DOWNLOAD = "https://ollama.com/download"
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
    "demo": ROOT / "requirements-demo.txt",
    "reranker": ROOT / "requirements-reranker.txt",
    "preprocess": ROOT / "requirements-preprocess.txt",
}
ALL_EXTRAS = ("demo", "reranker", "preprocess")
RUN_CHOICES = ("none", "demo", "eval", "tests", "console")


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
        return [ROOT / "requirements-dev.txt"]
    if extras:
        return [EXTRA_FILES[name] for name in extras]
    return [ROOT / "requirements.txt"]


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


def prepend_ollama_path() -> None:
    if sys.platform != "win32":
        return
    local_app = os.environ.get("LOCALAPPDATA", "")
    if not local_app:
        return
    ollama_dir = Path(local_app) / "Programs" / "Ollama"
    if not ollama_dir.is_dir():
        return
    current = os.environ.get("PATH", "")
    if str(ollama_dir) in current.split(os.pathsep):
        return
    os.environ["PATH"] = str(ollama_dir) + os.pathsep + current


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
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agent.retrieve.catalog.slots_sidecar import catalog_fingerprint, sidecar_is_current

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
    command = [str(ROOT / "scripts" / "download_catalog.py"), "--output", str(CATALOG)]
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
    code = run_python([str(ROOT / "scripts" / "extract_catalog_slots.py")])
    if code != 0:
        raise SystemExit(f"sidecar build failed (exit {code})")


def warm_index() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agent.retrieve.catalog.index_path import resolve_index_path
    from agent.retrieve.catalog.retriever import CatalogRetriever

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
    """Canonical Chainlit APP_ROOT is demo/; repo-root .chainlit is unused."""

    if not CHAINLIT_CONFIG.is_file():
        return False, f"missing {CHAINLIT_CONFIG.relative_to(ROOT)}"
    missing = [
        str(path.relative_to(ROOT)) for path in CHAINLIT_PUBLIC_FILES if not path.is_file()
    ]
    if missing:
        return False, f"missing demo public assets: {', '.join(missing)}"
    return True, f"APP_ROOT={DEMO_DIR} ({CHAINLIT_CONFIG.relative_to(ROOT)})"


def discard_stale_root_chainlit(root: Path | None = None) -> bool:
    """Delete a leftover repository-root ``.chainlit/``. Never touches ``demo/``."""

    base = (root or ROOT).resolve()
    stale = (base / ".chainlit").resolve()
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
    log("  python scripts/bootstrap.py --extras demo")
    log("  python scripts/bootstrap.py --extras demo --run demo")
    log("  powershell -ExecutionPolicy Bypass -File scripts/setup.ps1")
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
        # Always pin demo/ so a leftover repo-root .chainlit is never used.
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
        log("Running unittest discovery in tests/")
        return run_python(["-m", "unittest", "discover", "-s", "tests", "-v"])
    if kind == "console":
        return run_python([str(ROOT / "scripts" / "nlu_console.py")])
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
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
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
        step("Install Python extras")
        pip_install(requirement_files(extras))
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
            "or python scripts/download_catalog.py"
        )

    if args.run == "none":
        step("Ready")
        log("Core setup finished. Useful next commands:")
        log("  python scripts/bootstrap.py --extras demo --run demo")
        log("  python scripts/nlu_console.py")
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
