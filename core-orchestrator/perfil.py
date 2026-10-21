"""
Perfil del asistente y de la persona: lo que en cada PC puede ser distinto.

  - Dónde viven las cosas:
      INSTALACION  entornos de Python, voces, modelos y scripts   (JARVIS_INSTALACION, por defecto ~/jarvis)
      DATOS        lo de la persona: memoria, calendario, notas…  (JARVIS_DATOS,       por defecto ~/jarvis)
      SECRETOS     claves y permisos                              (JARVIS_SECRETOS,    por defecto = DATOS)
  - Cómo es el asistente: nombre (y con qué se le despierta), color de la interfaz, voz, idioma y pantallas.

Los ajustes se guardan en DATOS/config.json, bajo la clave "perfil". Si no hay nada, todo vale como en el Jarvis
original, así que un PC ya instalado no nota el cambio.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import unicodedata
from pathlib import Path

MOTOR = Path(__file__).resolve().parent                     # el código (core-orchestrator)


def _ruta(variable: str, defecto: Path) -> Path:
    v = os.environ.get(variable, "").strip()
    return Path(v).expanduser() if v else defecto


INSTALACION = _ruta("JARVIS_INSTALACION", Path.home() / "jarvis")
DATOS = _ruta("JARVIS_DATOS", Path.home() / "jarvis")
SECRETOS = _ruta("JARVIS_SECRETOS", DATOS)
CONFIG = DATOS / "config.json"

DEFECTO: dict = {
    "nombre": "Jarvis",                 # cómo se llama el asistente
    "activacion": [],                   # palabras extra para despertarlo (además del nombre)
    "genero": "masculino",              # cómo habla de sí mismo
    "idioma": "es-ES",                  # es-ES, es-MX, en-US…
    "color": "#29d4ff",                 # color principal de la interfaz
    "voz": {"motor": "piper", "modelo": "", "hablante": None, "lentitud": None},
    "pantallas": {"interfaz": "auto"},  # "auto" o el nombre de la salida (HDMI-1, DP-2…) donde va la interfaz
    "usuario": {"nombre": "", "trato": ""},
}

_lock = threading.Lock()
_cache: dict = {"mtime": None, "perfil": None}


def _leer_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _mezclar(base: dict, encima: dict) -> dict:
    fuera = copy.deepcopy(base)
    for k, v in (encima or {}).items():
        if isinstance(v, dict) and isinstance(fuera.get(k), dict):
            fuera[k] = _mezclar(fuera[k], v)
        else:
            fuera[k] = v
    return fuera


def perfil() -> dict:
    """Los ajustes actuales (los de config.json encima de los de por defecto). Se relee si cambia el archivo."""
    try:
        mtime = CONFIG.stat().st_mtime
    except OSError:
        mtime = None
    with _lock:
        if _cache["perfil"] is None or _cache["mtime"] != mtime:
            _cache["perfil"] = _mezclar(DEFECTO, _leer_config().get("perfil") or {})
            _cache["mtime"] = mtime
        return copy.deepcopy(_cache["perfil"])


def guardar(**cambios) -> dict:
    """guardar(nombre="Viernes", color="#ff8800", voz={"modelo": "es_ES-davefx-medium"})"""
    with _lock:
        c = _leer_config()
        c["perfil"] = _mezclar(c.get("perfil") or {}, cambios)
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG)
        _cache["perfil"] = None
    return perfil()


def nombre() -> str:
    n = str(perfil().get("nombre") or "Jarvis").strip()
    return n or "Jarvis"


def idioma() -> str:
    return str(perfil().get("idioma") or "es-ES")


# ---------------------------------------------------------------- activación por el nombre
def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


# Cómo suele equivocarse el reconocimiento de voz con un nombre: letras que suenan igual en español.
_PARECIDOS = [("v", "b"), ("b", "v"), ("j", "y"), ("j", "h"), ("j", "ch"), ("j", "g"), ("y", "ll"), ("ll", "y"),
              ("z", "s"), ("s", "z"), ("ce", "se"), ("ci", "si"), ("qu", "k"), ("k", "qu"), ("x", "s"), ("h", ""),
              ("a", "e"), ("e", "a")]
_JARVIS = ["jarvis", "yarvis", "jarbis", "yarbis", "harvis", "charvis", "jervis", "yervis", "garvis"]


def variantes(nombre_: str | None = None) -> list[str]:
    """Palabras que cuentan como el nombre (sin tildes, en minúsculas). Para «Jarvis» son las de siempre."""
    n = _sin_tildes(nombre_ or nombre())
    n = re.sub(r"[^a-zñ]", "", n)
    if not n:
        return list(_JARVIS)
    fuera = {n}
    for a, b in _PARECIDOS:
        for v in list(fuera):
            if a in v:
                fuera.add(v.replace(a, b, 1))
        if len(fuera) > 40:
            break
    if n == "jarvis":
        fuera.update(_JARVIS)
    for extra in perfil().get("activacion") or []:
        e = re.sub(r"[^a-zñ]", "", _sin_tildes(str(extra)))
        if e:
            fuera.add(e)
    return sorted(fuera)


def con_nombre(texto: str) -> str:
    """Cambia «Jarvis» por el nombre del asistente en un texto fijo (frases, avisos, instrucciones)."""
    n = nombre()
    if n == "Jarvis" or "Jarvis" not in texto:
        return texto
    return re.sub(r"\bJarvis\b", n, texto)
