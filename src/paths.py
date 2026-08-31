"""Resolved paths for the submission package.

Runtime assets live next to this file. Data and cache follow the project
root: the kit repo when ``evaluator/`` and ``starter/`` sit beside this
package, otherwise this folder (contest zip unpacked as cwd).
"""

from pathlib import Path


def detect_project_root(submission_root: Path) -> Path:
    """Kit checkout vs zip-as-root.

    Kit layout: ``<repo>/submission/src/paths.py`` with ``evaluator/`` and
    ``starter/`` next to ``submission/``. Zip layout: this folder is the
    working tree; catalog and ``.cache/`` live here.
    """

    resolved = submission_root.resolve()
    parent = resolved.parent
    if (parent / "evaluator").is_dir() and (parent / "starter").is_dir():
        return parent
    return resolved


SRC_ROOT = Path(__file__).resolve().parent
SUBMISSION_ROOT = SRC_ROOT.parent
PROJECT_ROOT = detect_project_root(SUBMISSION_ROOT)
KIT_ROOT = PROJECT_ROOT
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / ".cache"
ASSETS_DIR = SRC_ROOT / "assets"
ALIASES_DIR = ASSETS_DIR / "aliases"
NLU_ENV_FILE = ASSETS_DIR / "nlu.env"
RERANKER_ENV_FILE = ASSETS_DIR / "reranker.env"
