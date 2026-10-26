"""
Copias de seguridad del asistente con restic (https://github.com/restic/restic, BSD-2): cifradas, incrementales y
deduplicadas. Guarda lo que no se puede volver a instalar: memoria, notas aprendidas, configuración, calendario,
claves de servicios… (no los programas ni los modelos, que se reinstalan).

  «haz una copia de seguridad»                → copia ahora en ~/CopiasAthena
  «haz una copia en el disco usb»             → además, en el disco USB conectado (carpeta CopiasAthena)
  «cuándo fue la última copia», «qué copias tienes»
Cada domingo a las 3:30 se hace sola (temporizador «athena-copia», lo crea instalar_copias.sh).
Para recuperar, en una terminal:  restic -r ~/CopiasAthena --password-file ~/.config/athena-copias/clave restore latest --target ~/recuperado
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from herramientas import normalizar
from perfil import DATOS
from sistema import Respuesta

HOME = Path.home()
RESTIC = next((str(p) for p in (HOME / ".local/bin/restic", Path("/opt/jarvis-herramientas/restic"))
               if p.exists()), shutil.which("restic") or "")
REPO = HOME / "CopiasAthena"
CLAVE = HOME / ".config/athena-copias/clave"
FUERA = ["venv*", "logs", "hf-cache", "__pycache__", "*.onnx", "*.gguf", "*.safetensors", "*.bin", "practicas/venv",
         "modelos", "voces", "cache", "*.tmp", "*.pyc"]


def _restic(repo: Path, *args: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    env = {**os.environ, "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD_FILE": str(CLAVE), "RESTIC_CACHE_DIR":
           str(HOME / ".cache/restic")}
    return subprocess.run([RESTIC, *args], capture_output=True, text=True, timeout=timeout, env=env)


def copia(repo: Path = REPO) -> dict:
    """Hace la copia y devuelve un resumen (para la voz y para el temporizador semanal)."""
    if not RESTIC or not CLAVE.exists():
        raise RuntimeError("faltan restic o la clave: bash ~/jarvis/instalar_copias.sh")
    if not (repo / "config").exists():
        r = _restic(repo, "init")
        if r.returncode:
            raise RuntimeError("no puedo crear el almacén de copias: " + r.stderr.strip()[-200:])
    args = ["backup", str(DATOS), "--json", "--tag", "athena", "--one-file-system"]
    for f in FUERA:
        args += ["--exclude", f]
    r = _restic(repo, *args)
    if r.returncode not in (0, 3):                         # 3 = algún archivo no se pudo leer, la copia vale
        raise RuntimeError(r.stderr.strip()[-300:] or "restic falló")
    resumen = {}
    for linea in r.stdout.splitlines():
        try:
            j = json.loads(linea)
        except ValueError:
            continue
        if j.get("message_type") == "summary":
            resumen = j
    _restic(repo, "forget", "--keep-daily", "7", "--keep-weekly", "8", "--keep-monthly", "12", "--prune", timeout=1800)
    return resumen


def disco_usb() -> Path | None:
    """Un disco USB montado y con sitio (el primero que haya)."""
    for base in (Path("/media") / os.environ.get("USER", ""), Path("/run/media") / os.environ.get("USER", "")):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            try:
                if d.is_dir() and os.access(d, os.W_OK) and shutil.disk_usage(d).free > 2 * 1024 ** 3:
                    return d
            except OSError:
                continue
    return None


class Copias:
    def __init__(self, log: Callable[[str], None], decir: Callable[[str], None] | None = None):
        self.log = log
        self.decir = decir
        self._ocupado = False

    def manejar(self, texto: str) -> Respuesta | None:
        t = normalizar(texto).strip(" .?¿!¡")
        if not re.search(r"\bcopias? de seguridad\b|\bbackup\b|\bcopia (de athena|del asistente|en el disco)"
                         r"|\b(ultima|cuantas|que) copias?\b", t):
            return None
        if re.search(r"\b(cuando|ultima|cuantas|que copias|lista)\b", t):
            return self._listar()
        if re.search(r"\b(haz|hazme|crea|guarda|saca|ejecuta)\w*\b", t):
            usb = bool(re.search(r"\b(usb|disco externo|pendrive|en el disco)\b", t))
            return self._hacer(usb)
        return None

    def _hacer(self, usb: bool) -> Respuesta:
        if not RESTIC or not CLAVE.exists():
            return Respuesta("Aún no tengo las copias de seguridad instaladas. Se instalan con "
                             "bash ~/jarvis/instalar_copias.sh.")
        if self._ocupado:
            return Respuesta("Ya estoy haciendo una copia; te aviso al terminar.")
        destino = disco_usb() if usb else None
        if usb and not destino:
            return Respuesta("No veo ningún disco USB conectado con sitio libre. Conéctalo y vuelve a pedírmelo.")

        def hilo():
            self._ocupado = True
            try:
                res = copia()
                txt = (f"Copia de seguridad hecha: {res.get('files_new', 0)} archivos nuevos y "
                       f"{res.get('files_changed', 0)} cambiados.")
                if destino:
                    copia(destino / "CopiasAthena")
                    txt += f" También está en el disco {destino.name}."
                self.log(f"copias: {txt}")
            except Exception as e:
                txt = f"No he podido hacer la copia: {e}"
                self.log(f"copias: {e!r}")
            finally:
                self._ocupado = False
            if self.decir:
                self.decir(txt)
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta("Hago la copia de seguridad ahora; tardo un par de minutos y te aviso." +
                         (f" Después la copio al disco {destino.name}." if destino else ""))

    def _listar(self) -> Respuesta:
        if not RESTIC or not (REPO / "config").exists():
            return Respuesta("Todavía no hay ninguna copia de seguridad. Dime «haz una copia de seguridad».")
        r = _restic(REPO, "snapshots", "--json", timeout=120)
        try:
            lista = json.loads(r.stdout or "[]")
        except ValueError:
            lista = []
        if not lista:
            return Respuesta("Todavía no hay ninguna copia de seguridad.")
        ultima = lista[-1]["time"][:16].replace("T", " a las ")
        dia, hora = ultima.split(" a las ")
        a, m, d = dia.split("-")
        return Respuesta(f"Tengo {len(lista)} copias guardadas; la última es del {int(d)}/{int(m)}/{a} a las {hora}.")
