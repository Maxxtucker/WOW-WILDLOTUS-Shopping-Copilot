"""Purpose: make the local Ollama daemon reachable for NLU.

Input: host and model from env (after load_nlu_env).
Output: True if the daemon answers; last_error when it does not.
Role: Agent nlu startup. Does not pull models. Does not write SessionState.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .llm_nlu import nlu_host, nlu_model, nlu_timeout

PING_TIMEOUT_S = 2.0
READY_DEADLINE_S = 20.0

last_error: str | None = None


def ollama_reachable() -> bool:
    """True when GET /api/tags succeeds."""

    url = nlu_host().rstrip("/") + "/api/tags"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=PING_TIMEOUT_S) as response:
            response.read()
        return True
    except (TimeoutError, urllib.error.URLError, OSError):
        return False


def prepend_ollama_path() -> None:
    """Add the usual Windows Ollama install dir to PATH when it exists."""

    if sys.platform != "win32":
        return
    local_app = os.environ.get("LOCALAPPDATA", "")
    if not local_app:
        return
    ollama_dir = os.path.join(local_app, "Programs", "Ollama")
    if not os.path.isdir(ollama_dir):
        return
    current = os.environ.get("PATH", "")
    if ollama_dir in current.split(os.pathsep):
        return
    os.environ["PATH"] = ollama_dir + os.pathsep + current


def _spawn_serve() -> None:
    global last_error
    binary = shutil.which("ollama")
    if not binary:
        last_error = "ollama executable not found"
        return
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
        last_error = f"failed to spawn ollama serve: {exc}"


def _wait_until_ready(deadline_s: float) -> bool:
    until = time.monotonic() + deadline_s
    while time.monotonic() < until:
        if ollama_reachable():
            return True
        time.sleep(0.4)
    return False


def load_configured_model() -> None:
    """Ask Ollama to load weights. Failures are recorded, not raised."""

    global last_error
    host = nlu_host().rstrip("/")
    body = {
        "model": nlu_model(),
        "prompt": " ",
        "stream": False,
        "keep_alive": "10m",
        "options": {"num_predict": 1},
    }
    timeout = max(PING_TIMEOUT_S, min(nlu_timeout(), 60.0))
    request = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        last_error = f"model warmup failed: {exc}"


def ensure_llm_runtime() -> bool:
    """Ping Ollama, spawn serve if needed, then load the configured model."""

    global last_error
    last_error = None
    prepend_ollama_path()
    if not ollama_reachable():
        _spawn_serve()
        if not _wait_until_ready(READY_DEADLINE_S):
            if last_error is None:
                last_error = "Ollama did not become ready"
            return False
    load_configured_model()
    return True
