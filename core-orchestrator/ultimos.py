"""
Lo último que ha hecho Jarvis (canciones, vídeos, imágenes, fotos, documentos…), para poder decir:

  "reproduce la canción que acabas de crear", "pon el vídeo que has hecho", "enséñame la foto que has sacado",
  "abre el word que has redactado", "mándame la última canción", "ábrelo", "reprodúcela"

Si lo pides mientras todavía lo está haciendo ("cuando tengas la canción, reprodúcela"), lo abre en cuanto termina.
Los módulos que crean cosas llaman a apuntar(ruta, tipo). Se guarda en ~/jarvis/creados.json (los 30 últimos).
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

from perfil import DATOS
from herramientas import abrir_archivo, normalizar
from sistema import Respuesta

HOME = Path.home()
CREADOS = DATOS / "creados.json"
_lock = threading.Lock()
_oyentes: list[Callable[[Path, str, bool], None]] = []

TIPOS = {   # palabra dicha → tipo guardado
    "cancion": "cancion", "musica": "cancion", "tema": "cancion", "audio": "cancion",
    "video": "video", "videoclip": "video", "clip": "video",
    "imagen": "imagen", "dibujo": "imagen", "ilustracion": "imagen", "logo": "imagen", "fondo": "imagen",
    "cartel": "imagen", "poster": "imagen",
    "foto": "foto", "fotografia": "foto", "captura": "foto",
    "word": "documento", "documento": "documento", "informe": "documento", "pdf": "documento",
    "carta": "documento", "texto": "documento",
    "excel": "hoja", "hoja": "hoja", "tabla": "hoja",
    "presentacion": "presentacion", "plano": "plano",
}
RE_TIPO = r"(" + "|".join(sorted(TIPOS, key=len, reverse=True)) + r")"
VERBO = (r"(?:reproduce|reproducela|reproducelo|ponla|ponlo|pon|abre|abrela|abrelo|ensename|ensenamela|ensenamelo|"
         r"muestrame|muestramela|muestramelo|mandame|mandamela|mandamelo|enviame|enviamela|enviamelo|pasame|"
         r"dejame (?:ver|oir|escuchar)|quiero (?:ver|oir|escuchar)|escuchemos|veamos)")
HECHO = (r"(?:que (?:has|acabas de|me has|habias|hayas) (?:crea|hech|hace|compu|compon|grab|sac|hic|redact|"
         r"dibuj|pint|mont|prepar|escrib|genera)\w*|que (?:he|acabo de) (?:sac|hech|hac|tom)\w*|"
         r"(?:recien|ultim[oa]) (?:cread|hech)[oa]|ultim[oa]|nuev[oa]|de antes)")


def tipo_por_ruta(ruta: Path) -> str:
    suf = ruta.suffix.lower()
    if suf in (".mp3", ".wav", ".ogg", ".flac", ".m4a"):
        return "cancion"
    if suf in (".mp4", ".mkv", ".webm", ".mov"):
        return "video"
    if suf in (".jpg", ".jpeg", ".png", ".webp"):
        return "foto" if "cam" in normalizar(str(ruta.parent)) else "imagen"
    if suf in (".xlsx", ".ods", ".csv"):
        return "hoja"
    if suf in (".pptx", ".odp"):
        return "presentacion"
    if suf in (".dxf", ".dwg"):
        return "plano"
    return "documento"


def apuntar(ruta: Path | str, tipo: str | None = None, abierto: bool = False) -> None:
    """Lo llaman los módulos al terminar algo. abierto=True si ya se ha abierto en la pantalla."""
    ruta = Path(ruta)
    tipo = tipo or tipo_por_ruta(ruta)
    with _lock:
        try:
            datos = json.loads(CREADOS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = []
        datos = [d for d in datos if d.get("ruta") != str(ruta)]
        datos.append({"ruta": str(ruta), "tipo": tipo, "t": time.time()})
        CREADOS.parent.mkdir(parents=True, exist_ok=True)
        CREADOS.write_text(json.dumps(datos[-30:], ensure_ascii=False, indent=1), encoding="utf-8")
    for f in list(_oyentes):
        try:
            f(ruta, tipo, abierto)
        except Exception:
            pass


def ultimo(tipo: str | None = None) -> Path | None:
    try:
        datos = json.loads(CREADOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for d in reversed(datos):
        if (tipo is None or d.get("tipo") == tipo) and Path(d["ruta"]).exists():
            return Path(d["ruta"])
    return None


def contexto_ia(cuantos: int = 6) -> str:
    """Los últimos archivos que ha hecho el asistente, con su nombre exacto: para que el cerebro no se lo invente
    («prueba.xlsx» cuando se llama «Gastos prueba.xlsx»)."""
    try:
        datos = json.loads(CREADOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    vistos = [d for d in reversed(datos) if Path(d.get("ruta", "")).exists()][:cuantos]
    return "; ".join(f"{d.get('tipo')}: {Path(d['ruta']).name}" for d in vistos)


class Ultimos:
    def __init__(self, decir: Callable[..., None], log=print, es_telegram: Callable[[], bool] | None = None,
                 enviar_documento=None, enviar_foto=None, avisar=None, trabajando: Callable[[], int] | None = None):
        self.decir = decir
        self.log = log
        self.es_telegram = es_telegram or (lambda: False)
        self.enviar_documento = enviar_documento or (lambda r, p: False)
        self.enviar_foto = enviar_foto or (lambda r, p: None)
        self.avisar = avisar or (lambda t: None)
        self.trabajando = trabajando or (lambda: 0)          # ¿hay algo creándose ahora mismo?
        self._esperando: dict | None = None
        self._ultimo_tipo: str | None = None
        _oyentes.append(self._recien_creado)

    def _recien_creado(self, ruta: Path, tipo: str, abierto: bool) -> None:
        self._ultimo_tipo = tipo
        e = self._esperando
        if e and (e["tipo"] in (None, tipo)) and time.time() - e["t"] < 1800:
            self._esperando = None
            if abierto and not e["tg"]:
                return                                  # ya se ha abierto solo en el portátil
            threading.Timer(1, self._entregar, args=(ruta, tipo, e["tg"], True)).start()

    def _entregar(self, ruta: Path, tipo: str, tg: bool, avisando: bool = False) -> str:
        if tg:
            if ruta.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                self.enviar_foto(str(ruta), ruta.stem)
            else:
                self.enviar_documento(str(ruta), ruta.name)
            texto = f"Ahí tienes {ruta.name}."
        else:
            abrir_archivo(ruta)
            verbo = {"cancion": "Reproduciendo", "video": "Poniendo"}.get(tipo, "Abriendo")
            texto = f"{verbo} {ruta.stem}."
        if avisando:
            (self.avisar if tg else self.decir)(texto)
        return texto

    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis|y)[ ,]+", "", t)
        tg = self.es_telegram()
        tipo, a_secas = None, False
        m = re.search(r"\b" + VERBO + r"\s+(?:la |el |lo |esa |ese |esta |este |tu |mi )?(?:ultim[oa] )?" + RE_TIPO +
                      r"\b(.*)$", t)
        if m and (re.search(HECHO, m.group(2)) or re.search(r"\bultim[oa]\b", t[:m.end(1) + 8]) or
                  m.group(2).strip() == ""):
            tipo = TIPOS[m.group(1)]
            a_secas = m.group(2).strip() == "" and not re.search(r"\bultim", t)
            if m.group(2).strip() == "" and not re.search(r"\b(la|el|esa|ese|esta|este|ultim)\b", t):
                return None                               # "pon música" a secas no es esto
            if m.group(2).strip() == "" and m.group(1) in ("musica", "tema", "audio"):
                return None
        elif re.fullmatch(r"(?:cuando (?:la |lo )?(?:tengas|este lista|este listo|acabes|termines)[ ,]*)?"
                          r"(reproducela|reproducelo|ponla|ponlo|abrela|abrelo|ensenamela|ensenamelo|mandamela|"
                          r"mandamelo)", t):
            tipo = self._ultimo_tipo                       # "reprodúcela", "ábrelo": lo último que se hizo
        else:
            m2 = re.search(r"\bcuando (?:tengas|este lista|este listo|acabes|termines)\b.*\b(" +
                           "|".join(TIPOS) + r")\b", t)
            if m2 and re.search(r"\b(reproduc|pon|abre|ensen|muestr|mand)", t):
                tipo = TIPOS[m2.group(1)]
                self._esperando = {"tipo": tipo, "t": time.time(), "tg": tg}
                return Respuesta("De acuerdo, en cuanto esté te la pongo." if tipo in ("cancion", "foto", "imagen")
                                 else "De acuerdo, en cuanto esté te lo pongo.")
            return None
        # ¿se está haciendo todavía? entonces se abre al terminar
        reciente = ultimo(tipo)
        if self.trabajando() and (reciente is None or time.time() - reciente.stat().st_mtime > 120):
            self._esperando = {"tipo": tipo, "t": time.time(), "tg": tg}
            return Respuesta("Todavía la estoy terminando; en cuanto esté, te la pongo." if tipo in
                             ("cancion", "foto", "imagen") else "Todavía lo estoy terminando; en cuanto esté, te lo pongo.")
        if reciente is None and a_secas:
            return None                                   # "abre la presentación" sin nada hecho: que mire otro
        if reciente is None:
            nombre = {"cancion": "ninguna canción", "video": "ningún vídeo", "imagen": "ninguna imagen",
                      "foto": "ninguna foto", "documento": "ningún documento", "hoja": "ninguna hoja de cálculo",
                      "presentacion": "ninguna presentación", "plano": "ningún plano"}.get(tipo, "nada")
            return Respuesta(f"No tengo {nombre} hecha todavía." if nombre.startswith("ninguna")
                             else f"No tengo {nombre} hecho todavía.")
        return Respuesta(self._entregar(reciente, tipo or "", tg))
