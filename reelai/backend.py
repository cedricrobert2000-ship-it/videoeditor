"""Choisit où exécuter le travail lourd : dans Resolve, ou dans le Python où ReelAI est installé."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from typing import Callable, Optional

from .config import Settings

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = ("faster_whisper", "anthropic", "av", "numpy", "PIL")


def deps_available() -> bool:
    try:
        for name in REQUIRED:
            __import__(name)
        return True
    except Exception:
        return False


def find_python(settings: Settings) -> Optional[str]:
    candidates = [settings.python_path] if settings.python_path else []
    candidates += [
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11",
        shutil.which("python3.12") or "",
        shutil.which("python3") or "",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


class LocalBackend:
    """Exécute dans le processus courant (tests, ou Python de Resolve complet)."""

    def __init__(self, ai_client=None, hf_client=None):
        self.ai_client, self.hf_client = ai_client, hf_client

    def run(self, task: str, payload: dict, settings: Settings, log: Callable[[str], None]) -> dict:
        from .worker import run_task
        payload = dict(payload, settings=asdict(settings))
        return run_task(task, payload, log=log, ai_client=self.ai_client, hf_client=self.hf_client)


def _apple_silicon() -> bool:
    """Vrai sur un Mac à puce Apple, même si Resolve tourne sous Rosetta (x86_64)."""
    if sys.platform != "darwin":
        return False
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out == "1"
    except Exception:
        return False


def worker_command(python: str) -> list:
    cmd = [python, "-m", "reelai.worker"]
    # Si Resolve tourne sous Rosetta, Python hériterait du mode Intel et ne pourrait
    # pas charger les paquets installés pour Apple Silicon : on force le mode natif.
    if _apple_silicon() and os.path.exists("/usr/bin/arch"):
        cmd = ["/usr/bin/arch", "-arm64"] + cmd
    return cmd


class SubprocessBackend:
    def __init__(self, python: str):
        self.python = python

    def run(self, task: str, payload: dict, settings: Settings, log: Callable[[str], None]) -> dict:
        tmp = tempfile.mkdtemp(prefix="reelai_")
        job, out = os.path.join(tmp, "job.json"), os.path.join(tmp, "out.json")
        with open(job, "w", encoding="utf-8") as fh:
            json.dump({"task": task, "payload": dict(payload, settings=asdict(settings))}, fh, ensure_ascii=False)

        env = dict(os.environ, PYTHONPATH=PACKAGE_ROOT, PYTHONIOENCODING="utf-8")
        for var in ("PYTHONHOME", "PYTHONSTARTUP"):  # Resolve peut les définir pour son propre Python
            env.pop(var, None)
        proc = subprocess.Popen(
            worker_command(self.python) + [job, out],
            cwd=PACKAGE_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("LOG:"):
                log(line[4:])
            elif line:
                tail = (tail + [line])[-15:]
                print(f"[ReelAI worker] {line}")
        proc.wait()

        if not os.path.exists(out):
            raise RuntimeError(f"Le traitement a échoué ({self.python}) :\n" + "\n".join(tail[-6:]))
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        shutil.rmtree(tmp, ignore_errors=True)
        if not data["ok"]:
            raise RuntimeError(data["error"])
        return data["result"]


def get_backend(settings: Settings, log: Callable[[str], None] = print):
    if deps_available():
        return LocalBackend()
    python = find_python(settings)
    if not python:
        raise RuntimeError(
            "Les outils de ReelAI ne sont pas installés. Dans le Terminal : "
            "cd ~/videoeditor && python3.12 install.py"
        )
    log(f"Traitement via {python}")
    return SubprocessBackend(python)
