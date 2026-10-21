"""
Creativo para Jarvis: imágenes, vídeos y canciones.

Órdenes (por voz o Telegram):
  Imágenes (las pinta Pollinations.ai, gratis y sin clave; la descripción sale a su servidor)
    "crea una imagen de un faro en una tormenta" / "dibújame un gato astronauta" / "hazme un logo para una panadería"
    "hazme un fondo de pantalla de montañas nevadas"     → apaisado 1920×1080
    "hazla más oscura" / "otra versión" / "ponle un sombrero"   → retoca la última (15 min)
    "ponla de fondo de pantalla"
  Vídeos
    "crea un vídeo sobre la historia de Sevilla"  → guion de la IA, una imagen por escena, narración con la voz
                                                     de Jarvis, zoom suave, subtítulos y música de fondo (MP4)
    "… sin voz" → solo imágenes y música
  Canciones
    "compón una canción de rock sobre mi perro"   → letra y acordes (PDF y TXT) + arreglo instrumental que sigue
                                                     esos acordes (MP3).
    "… con la IA de música" → además 20 s hechos por MusicGen en local (en este portátil tarda ~15-20 min)
    "… con voz" → además una versión con Jarvis recitando la letra (no sabe cantar)
Todo se guarda en Imágenes/Jarvis, Vídeos/Jarvis y Música/Jarvis; por Telegram te lo manda.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from perfil import INSTALACION
from archivos import crear_docx, a_pdf, limpiar_nombre, sin_pisar
from herramientas import HOME, abrir_archivo, carpeta_usuario, normalizar
from sistema import Respuesta, con_tildes
from estudio import SinHerramienta, WEBS, duracion, herramienta_pedida
from ultimos import apuntar

TMP = Path(tempfile.gettempdir()) / "jarvis"
VENV_MUSICA = INSTALACION / "venv_musica" / "bin" / "python"
MUSICA_IA = Path(__file__).with_name("musica_ia.py")
URL_IMAGEN = "https://image.pollinations.ai/prompt/{}?width={}&height={}&nologo=true&seed={}&model=flux"

FORMATOS = {"cuadrado": (1024, 1024), "horizontal": (1344, 768), "vertical": (768, 1344), "fondo": (1920, 1080),
            "video": (1280, 720)}

VERBOS = r"(?:crea|creame|haz|hazme|genera|generame|disena|disename|prepara|preparame|monta|montame|quiero)"
RE_IMAGEN = re.compile(r"\b" + VERBOS + r"\w*\s+(?:un |una |unos |unas )?(?:nuevo |nueva )?(imagen(?:es)?|dibujo|ilustracion|"
                       r"logo|logotipo|cuadro|pintura|poster|cartel|fondo de pantalla|fondo de escritorio|wallpaper|"
                       r"portada|avatar|icono|foto (?:artificial|generada|con ia|inventada))\b(.*)$")
RE_DIBUJA = re.compile(r"^(?:dibuja|dibujame|pinta|pintame|ilustra|ilustrame)\s+(.+)$")
RE_VIDEO = re.compile(r"\b" + VERBOS + r"\w*\s+(?:un |una )?(?:nuevo |nueva |pequeno |corto )?(video|videoclip|reel|"
                      r"cortometraje|corto|animacion|documental)\b(.*)$")
RE_CANCION = re.compile(r"\b(?:" + VERBOS[3:-1] + r"|compon|componme|escribe|escribeme|inventa|inventame)\w*\s+"
                        r"(?:un |una )?(?:nuevo |nueva |pequena )?(cancion|tema musical|melodia|musica|jingle|rap|himno|"
                        r"nana|villancico|base musical|instrumental|sintonia)\b(.*)$")
RE_RETOQUE = re.compile(r"^(?:hazla|hazlo|ponla|ponlo|ponle|cambiala|cambialo|cambiale|mejorala|quitale|anadele|"
                        r"que sea|que tenga|pero|ahora|otra version|otra vez|otra|repitela|repitelo)\b(.*)$")
RE_FONDO = re.compile(r"\b(?:pon|ponla|ponmela|ponlo|usa|usala|coloca)\w*\s+(?:esa |esta |la )?(?:imagen |foto )?"
                      r"(?:de|como)\s+fondo\b")

INSTR_IMAGEN = """Conviertes peticiones en español en prompts para un generador de imágenes (FLUX). Devuelve SOLO JSON:
{"prompt": "descripción detallada EN INGLÉS: sujeto, estilo, luz, encuadre, colores (si debe aparecer un texto, \
escríbelo entre comillas tal cual)", "titulo": "título corto en español (2-5 palabras)", "formato": \
"cuadrado" | "horizontal" | "vertical"}
Logos e iconos: cuadrado, fondo liso, diseño plano y limpio. Fondos de pantalla y paisajes: horizontal. Retratos y \
carteles: vertical. Respeta exactamente lo que pide el usuario."""

INSTR_RETOQUE = """Te doy el prompt (en inglés) de una imagen y lo que el usuario quiere cambiar. Devuelve SOLO JSON \
{"prompt": "el prompt nuevo completo en inglés", "titulo": "título corto en español"} conservando todo lo demás."""

INSTR_VIDEO = """Preparas vídeos cortos narrados en español de España. Devuelve SOLO JSON:
{"titulo": "...", "estilo_musica": "pop|balada|electronica|rock|epica|jazz|infantil|ambiental", \
"escenas": [{"narracion": "1 o 2 frases para leer en voz alta (máx. 30 palabras)", "imagen": "prompt EN INGLÉS \
para la imagen de esa escena, cinematográfica, mismo estilo visual en todas"}]}
Entre 5 y 8 escenas (o las que pida el usuario), con hilo narrativo y datos concretos. Sin emojis."""

INSTR_CANCION = """Compones canciones originales en español de España. Devuelve SOLO JSON:
{"titulo": "...", "estilo": "pop|rock|balada|reggaeton|rap|electronica|flamenco|rumba|jazz|infantil|cumbia", \
"bpm": 60-180, "acordes_estrofa": ["Am","F","C","G"], "acordes_estribillo": ["F","G","C","Am"], \
"prompt_ia": "descripción EN INGLÉS para un generador de música: género, instrumentos, ambiente, tempo", \
"letra": [{"seccion": "Estrofa 1", "lineas": ["..."]}, {"seccion": "Estribillo", "lineas": ["..."]}, ...]}
Acordes en notación inglesa (C, Dm, G7, F#m, Bb…), 4 por progresión. Estructura: estrofa, estribillo, estrofa, \
estribillo (puente opcional). Rima y métrica cuidadas, letra original (nunca copies canciones existentes)."""


# =============================================================== imágenes

_RITMO = threading.Lock()
_ULTIMA_PETICION = [0.0]
ESPACIO = 12          # segundos entre imágenes: el servicio gratuito sin cuenta corta si se le pide más deprisa


def clave_pollinations() -> str | None:
    """Clave gratuita de https://auth.pollinations.ai (quita la marca de agua y amplía el límite)."""
    try:
        from herramientas import leer_config
        return leer_config().get("pollinations_token") or os.environ.get("POLLINATIONS_TOKEN")
    except Exception:
        return None


ESTUDIO = [None]      # lo pone Creativo cuando Jarvis le da el estudio (FLUX gratis en Hugging Face)


def descargar_imagen(prompt: str, ancho: int, alto: int, destino: Path, semilla: int | None = None,
                     flux_primero: bool = True) -> Path:
    """Primero FLUX (gratis, sin marca de agua); si no está o se agota, Pollinations. En los vídeos se pasa
    flux_primero=False para guardar el cupo gratuito de GPU para dar movimiento a las escenas."""
    est = ESTUDIO[0]
    if est is not None and flux_primero:
        try:
            return est.imagen(prompt, ancho, alto, destino, semilla)
        except Exception:
            pass
    try:
        return _pollinations(prompt, ancho, alto, destino, semilla)
    except Exception:
        if est is not None and not flux_primero:
            try:
                return est.imagen(prompt, ancho, alto, destino, semilla)
            except Exception:
                pass
        raise


def _pollinations(prompt: str, ancho: int, alto: int, destino: Path, semilla: int | None = None) -> Path:
    url = URL_IMAGEN.format(urllib.parse.quote(prompt[:1500]), ancho, alto, semilla or random.randint(1, 10 ** 8))
    cabeceras = {"User-Agent": "Jarvis/1.0", "Referer": "jarvis-casa"}
    clave = clave_pollinations()
    if clave:
        cabeceras["Authorization"] = f"Bearer {clave}"
    ultimo = None
    for intento in range(6):
        with _RITMO:                                     # una petición cada vez, espaciadas
            espera = _ULTIMA_PETICION[0] + (3 if clave else ESPACIO) - time.time()
            if espera > 0:
                time.sleep(espera)
            try:
                req = urllib.request.Request(url, headers=cabeceras)
                with urllib.request.urlopen(req, timeout=100) as r:
                    datos = r.read()
                if datos[:3] == b"\xff\xd8\xff" or datos[:8] == b"\x89PNG\r\n\x1a\n":
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    destino.write_bytes(datos)
                    return destino
                ultimo = ValueError("no ha devuelto una imagen")
            except urllib.error.HTTPError as e:
                ultimo = e
            except OSError as e:
                ultimo = e
            finally:
                _ULTIMA_PETICION[0] = time.time()
        limite = isinstance(ultimo, urllib.error.HTTPError) and ultimo.code in (402, 429, 503)
        time.sleep((20, 30, 45, 60, 60, 60)[intento] if limite else 3 + 4 * intento)
    if isinstance(ultimo, urllib.error.HTTPError) and ultimo.code in (402, 429):
        raise RuntimeError("el servicio gratuito de imágenes me ha cortado por pedirle demasiadas seguidas; "
                           "prueba dentro de unos minutos")
    raise RuntimeError(f"el servicio de imágenes no responde ({ultimo})")


def poner_fondo(ruta: Path) -> bool:
    """Fondo de escritorio en Xfce (todas las pantallas); si no, GNOME."""
    if shutil.which("xfconf-query"):
        r = subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-l"], capture_output=True, text=True, timeout=10)
        claves = [c for c in r.stdout.split() if c.endswith("/last-image")]
        for c in claves:
            subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", c, "-s", str(ruta)], timeout=10)
        if claves:
            return True
    if shutil.which("gsettings"):
        for clave in ("picture-uri", "picture-uri-dark"):
            subprocess.run(["gsettings", "set", "org.gnome.desktop.background", clave, ruta.as_uri()], timeout=10)
        return True
    return False


# =============================================================== música (sintetizador propio)

SR = 32000
NOTAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
LATINAS = {"do": "C", "re": "D", "mi": "E", "fa": "F", "sol": "G", "la": "A", "si": "B"}


def acorde(nombre: str, octava: int = 4) -> list[int]:
    """'F#m7' → notas MIDI. Admite Do/Re/Mi…"""
    n = nombre.strip().split("/")[0]
    m = re.match(r"(?i)^(do|re|mi|fa|sol|la|si)(.*)$", n)
    if m and not re.match(r"^[A-G]", n):
        n = LATINAS[m.group(1).lower()] + m.group(2)
    m = re.match(r"^([A-G])([#b]?)(.*)$", n)
    if not m:
        return [60, 64, 67]
    raiz = 12 * (octava + 1) + NOTAS[m.group(1)] + {"#": 1, "b": -1}.get(m.group(2), 0)
    q = m.group(3)
    if q.startswith("dim"):
        tri = [0, 3, 6]
    elif q.startswith("aug") or q.startswith("+"):
        tri = [0, 4, 8]
    elif q.startswith("sus2"):
        tri = [0, 2, 7]
    elif q.startswith("sus"):
        tri = [0, 5, 7]
    elif q.startswith("m") and not q.startswith("maj"):
        tri = [0, 3, 7]
    else:
        tri = [0, 4, 7]
    if "maj7" in q:
        tri.append(11)
    elif "7" in q:
        tri.append(10)
    return [raiz + i for i in tri]


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _env(n: int, ataque: float, caida: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.minimum(1.0, t / max(ataque, 1e-4))
    return a * np.exp(-t / max(caida, 1e-3))


def _tono(midi: float, dur: float, armonicos=(1, 0.5, 0.25, 0.12), ataque=0.005, caida=0.6) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = hz(midi)
    x = sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(armonicos) if f * (k + 1) < SR / 2)
    fin = min(n, int(SR * 0.03))
    env = _env(n, ataque, caida)
    if fin:
        env[-fin:] *= np.linspace(1, 0, fin)
    return (x * env).astype(np.float32)


def _bombo(dur=0.35) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = 50 + 90 * np.exp(-t * 35)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)).astype(np.float32)


def _caja(dur=0.22, rng=np.random.default_rng(1)) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    ruido = rng.standard_normal(n) * np.exp(-t * 22)
    return (0.7 * ruido + 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)).astype(np.float32)


def _charles(dur=0.06, rng=np.random.default_rng(2)) -> np.ndarray:
    n = int(SR * dur)
    x = np.diff(rng.standard_normal(n + 1)) * np.exp(-np.arange(n) / SR * 70)
    return (x * 0.5).astype(np.float32)


RITMOS = {   # posiciones en corcheas (0-7) de un compás de 4/4: bombo, caja, charles, patrón de bajo y de acordes
    "pop":        ([0, 4], [2, 6], list(range(8)), [0, 3, 4, 6], [0, 4]),
    "rock":       ([0, 3, 4], [2, 6], list(range(8)), list(range(8)), [0, 2, 4, 6]),
    "balada":     ([0], [4], [0, 2, 4, 6], [0, 4], [0]),
    "reggaeton":  ([0, 4], [3, 6], [0, 2, 4, 6], [0, 3, 4, 7], [0, 3, 4, 7]),
    "rap":        ([0, 5], [2, 6], list(range(8)), [0, 5], [0]),
    "electronica": ([0, 2, 4, 6], [2, 6], [1, 3, 5, 7], [1, 3, 5, 7], [0, 3, 6]),
    "flamenco":   ([0, 3, 6], [2, 6], [0, 2, 4, 6], [0, 3, 6], [0, 1, 3, 4, 6]),
    "rumba":      ([0, 3, 6], [2, 6], list(range(8)), [0, 3, 6], [0, 1, 3, 4, 6]),
    "jazz":       ([0], [3, 7], [0, 3, 4, 7], [0, 2, 4, 6], [0, 3]),
    "infantil":   ([0, 4], [2, 6], [0, 2, 4, 6], [0, 4], [0, 2, 4, 6]),
    "cumbia":     ([0, 4], [2, 6], [1, 3, 5, 7], [0, 3, 4, 7], [1, 3, 5, 7]),
    "epica":      ([0, 3, 4], [4], [0, 2, 4, 6], [0, 2, 4, 6], [0]),
    "ambiental":  ([], [], [], [0], [0]),
}


def _estilo(nombre: str) -> str:
    n = normalizar(nombre or "")
    for k in RITMOS:
        if k in n:
            return k
    for k, v in (("trap", "rap"), ("hip", "rap"), ("techno", "electronica"), ("house", "electronica"),
                 ("lenta", "balada"), ("romant", "balada"), ("niño", "infantil"), ("nana", "balada"),
                 ("metal", "rock"), ("punk", "rock"), ("relaj", "ambiental"), ("cine", "epica"), ("salsa", "cumbia")):
        if k in n:
            return v
    return "pop"


def arreglo(spec: dict, destino_wav: Path, segundos: float | None = None, melodia: bool = True,
            semilla: int | None = None) -> float:
    """Arreglo instrumental (batería, bajo, acordes y melodía) que sigue los acordes de la canción. Devuelve la duración."""
    rng = np.random.default_rng(semilla if semilla is not None else random.randint(0, 10 ** 6))
    estilo = _estilo(spec.get("estilo") or spec.get("estilo_musica") or "pop")
    bpm = float(spec.get("bpm") or {"balada": 72, "rap": 90, "reggaeton": 95, "electronica": 124, "rock": 128,
                                     "ambiental": 70, "epica": 90}.get(estilo, 108))
    bpm = min(180, max(55, bpm))
    estrofa = [c for c in spec.get("acordes_estrofa") or [] if isinstance(c, str)][:8] or ["C", "G", "Am", "F"]
    estribillo = [c for c in spec.get("acordes_estribillo") or [] if isinstance(c, str)][:8] or estrofa
    corchea = 60 / bpm / 2
    compas = corchea * 8
    secciones = [("intro", estrofa[:2] * 1), ("estrofa", estrofa * 2), ("estribillo", estribillo * 2),
                 ("estrofa", estrofa * 2), ("estribillo", estribillo * 2), ("final", estribillo[:2] + estribillo[:1])]
    compases = [(sec, c) for sec, lista in secciones for c in lista]
    if segundos:                                         # música de fondo: lo que dure el vídeo
        n_comp = max(2, math.ceil(segundos / compas))
        compases = [("estrofa" if (i // 8) % 2 == 0 else "estribillo", (estrofa if (i // 8) % 2 == 0 else estribillo)
                     [i % len(estrofa if (i // 8) % 2 == 0 else estribillo)]) for i in range(n_comp)]
    total = int(SR * (len(compases) * compas + 2.5))
    L, R = np.zeros(total, np.float32), np.zeros(total, np.float32)

    def poner(x: np.ndarray, t: float, vol: float, pan: float = 0.0):
        i = int(t * SR)
        if i >= total:
            return
        x = x[: total - i] * vol
        L[i:i + len(x)] += x * (1 - max(0, pan))
        R[i:i + len(x)] += x * (1 + min(0, pan))

    bombo, caja, charles = _bombo(), _caja(), _charles()
    p_bombo, p_caja, p_charles, p_bajo, p_acorde = RITMOS[estilo]
    blando = estilo in ("balada", "ambiental", "jazz")
    arm_piano = (1, 0.45, 0.2, 0.1, 0.05)
    arm_pad = (1, 0.3, 0.15)
    ultima_nota = None
    for k, (sec, nombre) in enumerate(compases):
        t0 = k * compas
        notas = acorde(nombre, 4)
        es_final = sec == "final" and k == len(compases) - 1
        intensidad = {"intro": 0.6, "estrofa": 0.8, "estribillo": 1.0, "final": 0.7}.get(sec, 0.8)
        # batería
        if sec != "intro" or estilo in ("electronica", "reggaeton"):
            for c in p_bombo:
                poner(bombo, t0 + c * corchea, 0.9 * intensidad)
            for c in p_caja:
                poner(caja, t0 + c * corchea, (0.25 if blando else 0.45) * intensidad, 0.1)
            for c in p_charles:
                poner(charles, t0 + c * corchea, 0.22 * intensidad * (1.2 if c % 2 == 0 else 0.8), -0.4)
        # bajo
        raiz = notas[0] - 24
        for j, c in enumerate(p_bajo):
            dur = (p_bajo[j + 1] - c if j + 1 < len(p_bajo) else 8 - c) * corchea
            poner(_tono(raiz + (12 if estilo == "electronica" and c % 2 else 0), dur * 0.95,
                        (1, 0.6, 0.3, 0.15), 0.004, 0.5), t0 + c * corchea, 0.55 * intensidad)
        # acordes (piano en los golpes del patrón, colchón largo debajo)
        poner(sum(_tono(n, compas * (2.5 if es_final else 1.05), arm_pad, 0.08, 1.8) for n in notas) / 3,
              t0, 0.18 * intensidad, 0.3)
        for c in p_acorde:
            dur = (8 - c) * corchea if c == p_acorde[-1] else (p_acorde[p_acorde.index(c) + 1] - c) * corchea
            voz = notas + ([notas[0] + 12] if estilo != "rap" else [])
            poner(sum(_tono(n, max(0.25, dur), arm_piano, 0.003, 0.7) for n in voz) / len(voz), t0 + c * corchea,
                  0.30 * intensidad, 0.25)
        # melodía (estribillo y algo en la estrofa)
        if melodia and sec in ("estribillo", "estrofa") and estilo not in ("ambiental",):
            escala = sorted({n + 12 + o for n in notas for o in (0, 12)})
            ritmos = [[0, 2, 3, 4, 6], [0, 1, 2, 4, 6], [0, 2, 4, 5, 6], [0, 3, 4, 6]]
            ritmo = ritmos[int(rng.integers(len(ritmos)))]
            if sec == "estrofa":
                ritmo = ritmo[::2]
            for j, c in enumerate(ritmo):
                if ultima_nota is None:
                    nota = int(rng.choice(escala[:4]))
                else:
                    cercanas = sorted(escala, key=lambda x: abs(x - ultima_nota))[:3]
                    nota = int(rng.choice(cercanas))
                ultima_nota = nota
                dur = ((ritmo[j + 1] if j + 1 < len(ritmo) else 8) - c) * corchea
                poner(_tono(nota, dur * 0.9, (1, 0.35, 0.12), 0.01, 0.45), t0 + c * corchea,
                      (0.32 if sec == "estribillo" else 0.2), -0.3)
    # reverberación sencilla y mezcla
    for canal in (L, R):
        eco = canal.copy()
        for d, g in ((0.031, 0.25), (0.067, 0.18), (0.113, 0.12), (0.191, 0.08)):
            n = int(d * SR)
            canal[n:] += eco[:-n] * g
    pico = max(float(np.abs(L).max()), float(np.abs(R).max()), 1e-6)
    L, R = np.tanh(L / pico * 1.4) * 0.85, np.tanh(R / pico * 1.4) * 0.85
    fin = int(SR * 2.0)
    L[-fin:] *= np.linspace(1, 0, fin)
    R[-fin:] *= np.linspace(1, 0, fin)
    estereo = (np.stack([L, R], axis=1) * 32767).astype(np.int16)
    destino_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(estereo.tobytes())
    return total / SR


def a_mp3(wav: Path, mp3: Path, titulo: str = "", artista: str = "Jarvis") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "192k",
                    "-metadata", f"title={titulo}", "-metadata", f"artist={artista}", str(mp3)], check=True, timeout=300)
    return mp3


def duracion_wav(ruta: Path) -> float:
    with wave.open(str(ruta), "rb") as w:
        return w.getnframes() / w.getframerate()


# =============================================================== el módulo

class Creativo:
    def __init__(self, cerebro, decir: Callable[..., None], log=print, ui=None,
                 enviar_documento: Callable[[str, str], bool] | None = None,
                 enviar_foto: Callable[[str, str], None] | None = None,
                 es_telegram: Callable[[], bool] | None = None, avisar: Callable[[str], None] | None = None,
                 sintetizar: Callable[[str, Path], None] | None = None):
        self.cerebro = cerebro
        self.decir = decir
        self.log = log
        self.ui = ui
        self.enviar_documento = enviar_documento or (lambda r, p: False)
        self.enviar_foto = enviar_foto or (lambda r, p: None)
        self.es_telegram = es_telegram or (lambda: False)
        self.avisar = avisar or (lambda t: None)
        self.sintetizar = sintetizar
        self.ultima_imagen: dict | None = None
        self._estudio = None                                  # herramientas de fuera (estudio.py), lo pone Jarvis
        self._trabajando = 0

    # ---------- utilidades
    @property
    @property
    def estudio(self):
        return self._estudio

    @estudio.setter
    def estudio(self, valor):
        self._estudio = valor
        ESTUDIO[0] = valor

    def ia(self) -> bool:
        return bool(self.cerebro and getattr(self.cerebro, "activo", False))

    def _json(self, sistema: str, usuario: str, max_tokens: int = 3000, timeout: float = 90) -> dict:
        texto = self.cerebro.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                                  formato_json=True, max_tokens=max_tokens, temperatura=0.8, timeout=timeout)
        texto = re.sub(r"(?s)<think>.*?</think>|^```(?:json)?|```$", "", texto.strip()).strip()
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            m = re.search(r"(?s)\{.*\}", texto)
            if not m:
                raise ValueError("la IA no ha devuelto JSON")
            return json.loads(m.group(0))

    def _carpeta(self, clave: str) -> Path:
        c = carpeta_usuario(clave)
        c = (c if c != HOME else HOME / {"PICTURES": "Imágenes", "VIDEOS": "Vídeos", "MUSIC": "Música"}[clave]) / "Jarvis"
        c.mkdir(parents=True, exist_ok=True)
        return c

    def _entregar(self, texto: str, archivos: list[Path], tg: bool, abrir: Path | None = None) -> None:
        self.log(f"creativo: {texto}")
        if tg:
            if len(texto) > 900 or not archivos:
                self.avisar(texto)
            for i, a in enumerate(archivos):
                pie = (texto if len(texto) <= 900 and i == 0 else a.name)
                if a.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    self.enviar_foto(str(a), pie)
                elif a.stat().st_size > 48 * 1024 ** 2:
                    self.avisar(f"{a.name} ocupa demasiado para Telegram; está en el portátil.")
                else:
                    self.enviar_documento(str(a), pie)
            return
        if abrir:
            try:
                abrir_archivo(abrir)
            except OSError:
                pass
        self.decir(texto)

    def _segundo_plano(self, trabajo: Callable[[], tuple[str, list[Path], Path | None]], aviso: str) -> Respuesta:
        tg = self.es_telegram()

        def hilo():
            self._trabajando += 1
            try:
                texto, archivos, abrir = trabajo()
            except Exception as e:
                self.log(f"creativo: error {e!r}")
                texto, archivos, abrir = (f"No he podido terminarlo: {e}" if isinstance(e, RuntimeError) else
                                          f"No he podido terminarlo ({type(e).__name__}). Prueba otra vez."), [], None
            finally:
                self._trabajando -= 1
            self._entregar(texto, archivos, tg, abrir)
            if archivos:
                apuntar(archivos[0], abierto=bool(abrir) and not tg)
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta(aviso)

    # ---------- imágenes
    def imagen(self, peticion: str, formato_forzado: str | None = None) -> Respuesta:
        if not self.ia:
            return Respuesta("Para crear imágenes necesito la IA en la nube, y ahora mismo no está disponible.")

        def trabajo():
            spec = self._json(INSTR_IMAGEN, peticion, max_tokens=800, timeout=45)
            prompt = str(spec.get("prompt") or peticion)
            formato = formato_forzado or str(spec.get("formato") or "cuadrado")
            ancho, alto = FORMATOS.get(formato, FORMATOS["cuadrado"])
            titulo = limpiar_nombre(str(spec.get("titulo") or "Imagen"))
            ruta = sin_pisar(self._carpeta("PICTURES") / f"{titulo}.jpg")
            descargar_imagen(prompt, ancho, alto, ruta)
            self.ultima_imagen = {"prompt": prompt, "ancho": ancho, "alto": alto, "ruta": ruta, "t": time.time(),
                                  "titulo": titulo}
            return f"Aquí tienes: {titulo}. Si quieres cambiar algo, dime por ejemplo: hazla más luminosa.", [ruta], ruta
        return self._segundo_plano(trabajo, "La estoy pintando. Unos segundos.")

    def retocar(self, cambio: str) -> Respuesta:
        u = self.ultima_imagen

        def trabajo():
            if re.fullmatch(r"(otra( version| vez)?|repitela|repitelo)", normalizar(cambio).strip()):
                prompt, titulo = u["prompt"], u["titulo"]
            else:
                spec = self._json(INSTR_RETOQUE, f"Prompt: {u['prompt']}\nCambio pedido: {cambio}", 800, 45)
                prompt, titulo = str(spec.get("prompt") or u["prompt"]), limpiar_nombre(str(spec.get("titulo") or u["titulo"]))
            ruta = sin_pisar(self._carpeta("PICTURES") / f"{titulo}.jpg")
            descargar_imagen(prompt, u["ancho"], u["alto"], ruta)
            self.ultima_imagen = {**u, "prompt": prompt, "ruta": ruta, "t": time.time(), "titulo": titulo}
            return f"Nueva versión: {ruta.stem}.", [ruta], ruta
        return self._segundo_plano(trabajo, "Vale, la retoco.")

    # ---------- vídeos
    def video(self, peticion: str, con_voz: bool, forzar: str | None = None, web: str | None = None) -> Respuesta:
        if not self.ia:
            return Respuesta("Para hacer vídeos necesito la IA en la nube, y ahora mismo no está disponible.")
        if web and self.estudio:                         # web sin API: lo preparo y te la abro
            spec = self._json(INSTR_VIDEO, peticion, max_tokens=3500, timeout=90)
            escenas = [e for e in spec.get("escenas") or [] if isinstance(e, dict)]
            if WEBS[web][2] == "video":
                texto = "\n\n".join(f"Escena {i + 1}: {e.get('imagen', '')}" for i, e in enumerate(escenas))
            else:
                texto = f"{spec.get('titulo', '')}\n\n" + "\n\n".join(
                    f"ESCENA {i + 1}\nVoz: {e.get('narracion', '')}\nImagen: {e.get('imagen', '')}"
                    for i, e in enumerate(escenas))
            return Respuesta(self.estudio.asistir(web, texto))
        if con_voz and not self.sintetizar:
            con_voz = False

        def trabajo():
            spec = self._json(INSTR_VIDEO, peticion, max_tokens=3500, timeout=90)
            escenas = [e for e in spec.get("escenas") or [] if isinstance(e, dict) and e.get("imagen")][:10]
            if not escenas:
                raise RuntimeError("la IA no me ha dado escenas")
            titulo = limpiar_nombre(str(spec.get("titulo") or "Vídeo"))
            tmp = TMP / f"video_{int(time.time())}"
            tmp.mkdir(parents=True, exist_ok=True)
            # imágenes una a una (el servicio gratuito atiende mal varias peticiones a la vez)
            errores = []
            maximo = 10 if clave_pollinations() else 4        # sin clave: ~1 imagen cada 2 minutos
            n = len(escenas)
            pintar = set(range(n)) if n <= maximo else {round(k * (n - 1) / (maximo - 1)) for k in range(maximo)}
            for i, e in enumerate(escenas):
                if i not in pintar:
                    continue
                try:
                    descargar_imagen(str(e["imagen"]), 1280, 720, tmp / f"img{i}.jpg", semilla=1000 + i,
                                     flux_primero=False)
                except Exception as ex:
                    errores.append(ex)
                    self.log(f"creativo: escena {i} sin imagen: {ex}")
            buenas = [i for i in range(len(escenas)) if (tmp / f"img{i}.jpg").exists()]
            if not buenas:
                raise RuntimeError(f"no he podido pintar las imágenes ({errores[0] if errores else '¿sin internet?'})")
            for i in range(len(escenas)):                # escena sin imagen: usa la anterior (con otro movimiento)
                if not (tmp / f"img{i}.jpg").exists():
                    previa = max([k for k in buenas if k < i] or [buenas[0]])
                    shutil.copy(tmp / f"img{previa}.jpg", tmp / f"img{i}.jpg")
            validas = list(range(len(escenas)))
            # movimiento de verdad: cada imagen se convierte en un clip con la mejor herramienta disponible
            movidos, usadas = {}, set()
            if self.estudio:
                gratis_max = 6
                for n, i in enumerate(validas):
                    if not forzar and n >= gratis_max and not ({"runway", "kling", "pika", "luma"} & usadas):
                        break
                    try:
                        ruta, h = self.estudio.clip(str(escenas[i]["imagen"]), tmp / f"img{i}.jpg", tmp / f"mov{i}.mp4",
                                                    forzar)
                        movidos[i] = ruta
                        usadas.add(h)
                    except SinHerramienta as ex:
                        self.log(f"creativo: sin clip para la escena {i}: {ex}")
                        if not forzar:
                            break                          # ninguna responde: el resto, con zoom
            # narración y clips
            clips, subtitulos, t_acum = [], [], 0.0
            for n, i in enumerate(validas):
                texto = str(escenas[i].get("narracion") or "").strip()
                voz = tmp / f"voz{i}.wav"
                if con_voz and texto:
                    self.sintetizar(texto, voz)
                    dur = duracion_wav(voz) + 0.7
                else:
                    dur = 4.5
                frames = int(dur * 25)
                zoom = ("min(zoom+0.0007,1.15)" if n % 2 == 0 else "if(eq(on,0),1.15,max(zoom-0.0007,1.0))")
                x = ["iw/2-(iw/zoom/2)", "0", "iw-iw/zoom"][n % 3]
                filtro = (f"[0:v]scale=1920:1080,zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}"
                          f":s=1280x720:fps=25,format=yuv420p[v]")
                entrada_v = ["-i", str(tmp / f"img{i}.jpg")]
                if i in movidos:                            # clip animado: algo más lento y, si falta, último fotograma
                    d0 = max(0.5, duracion(movidos[i]))
                    f = min(1.6, max(1.0, dur / d0))
                    resto = max(0.0, dur - d0 * f) + 0.2
                    filtro = (f"[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
                              f"setpts={f:.3f}*PTS,fps=25,tpad=stop_mode=clone:stop_duration={resto:.2f},"
                              f"format=yuv420p[v]")
                    entrada_v = ["-an", "-i", str(movidos[i])]
                audio = (["-i", str(voz)] if con_voz and texto else
                         ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=44100:cl=stereo"])
                clip = tmp / f"clip{n:02d}.mp4"
                subprocess.run(["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error", *entrada_v,
                                *audio, "-filter_complex", filtro + ";[1:a]apad,aresample=44100[a]", "-map", "[v]",
                                "-map", "[a]", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                "-c:a", "aac", "-b:a", "128k", "-ac", "2", str(clip)], check=True, timeout=600)
                clips.append(clip)
                if texto and con_voz:
                    subtitulos.append((t_acum, t_acum + dur - 0.3, texto))
                t_acum += dur
            (tmp / "lista.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
                            "-c", "copy", "todo.mp4"], cwd=tmp, check=True, timeout=300)
            # música de fondo y subtítulos
            arreglo({"estilo": spec.get("estilo_musica") or "ambiental", "acordes_estrofa": ["Am", "F", "C", "G"],
                     "acordes_estribillo": ["F", "G", "Am", "Em"]}, tmp / "musica.wav", segundos=t_acum + 1,
                    melodia=not con_voz)

            def hms(s):
                return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(s * 1000 % 1000):03d}"
            (tmp / "sub.srt").write_text("".join(f"{k + 1}\n{hms(a)} --> {hms(b)}\n{t}\n\n"
                                                 for k, (a, b, t) in enumerate(subtitulos)), encoding="utf-8")
            vfil = ("[0:v]subtitles=sub.srt:force_style='FontName=DejaVu Sans,FontSize=18,Outline=2,Shadow=1,"
                    "MarginV=28'[v]" if subtitulos else "[0:v]null[v]")
            vol = 0.13 if con_voz else 0.9
            destino = sin_pisar(self._carpeta("VIDEOS") / f"{titulo}.mp4")
            subprocess.run(["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error", "-i", "todo.mp4", "-i", "musica.wav",
                            "-filter_complex", f"{vfil};[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:"
                            f"dropout_transition=0,volume=2[a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                            str(destino)], cwd=tmp, check=True, timeout=900)
            shutil.rmtree(tmp, ignore_errors=True)
            con_mov = (f" {len(movidos)} con movimiento real ({', '.join(sorted(usadas))})." if movidos else "")
            return (f"El vídeo {destino.stem} está listo: {len(clips)} escenas, {round(t_acum)} segundos, en Vídeos, "
                    f"carpeta Jarvis.{con_mov}", [destino], destino)
        aviso = ("Me pongo con el vídeo: guion, imágenes, movimiento, voz y montaje. " +
                 ("Tardaré unos minutos" if clave_pollinations() else
                  "Sin cuenta de Pollinations las imágenes van despacio: tardaré unos 10 minutos") + "; te aviso.")
        return self._segundo_plano(trabajo, aviso)

    # ---------- vídeo a partir de una foto ("con esa foto crea un vídeo", "anima esta imagen")
    def video_de_foto(self, foto: Path, peticion: str) -> Respuesta:
        def trabajo():
            tmp = TMP / f"anima_{int(time.time())}"
            tmp.mkdir(parents=True, exist_ok=True)
            deseo = ""
            if self.ia:
                try:
                    deseo = str(self._json(
                        'Convierte la petición en un prompt EN INGLÉS para animar una foto (movimiento de cámara y de '
                        'lo que aparece, sin cambiar a las personas). Devuelve SOLO JSON: {"prompt": "..."}',
                        peticion, max_tokens=300, timeout=30).get("prompt") or "")
                except Exception:
                    deseo = ""
            prompt = deseo or "gentle cinematic camera push in, natural subtle motion, soft light"
            clip, usada = None, None
            if self.estudio:
                try:
                    clip, usada = self.estudio.clip(prompt, foto, tmp / "mov.mp4")
                except SinHerramienta as e:
                    self.log(f"creativo: sin animación ({e}); hago movimiento de cámara")
            dur = 8.0
            if clip:
                d0 = max(0.5, duracion(clip))
                f = min(2.0, max(1.0, dur / d0))
                resto = max(0.0, dur - d0 * f) + 0.3
                vf = (f"scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
                      f"setpts={f:.3f}*PTS,fps=25,tpad=stop_mode=clone:stop_duration={resto:.2f},format=yuv420p")
                entrada = ["-an", "-i", str(clip)]
            else:
                frames = int(dur * 25)
                vf = (f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,zoompan=z='min(zoom+0.0009,1.2)'"
                      f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1280x720:fps=25,format=yuv420p")
                entrada = ["-loop", "1", "-i", str(foto)]
            arreglo({"estilo": "ambiental", "acordes_estrofa": ["C", "Am", "F", "G"], "acordes_estribillo": ["F", "G", "C", "Am"]},
                    tmp / "musica.wav", segundos=dur + 1, melodia=True)
            destino = sin_pisar(self._carpeta("VIDEOS") / f"Vídeo de {foto.stem}.mp4")
            subprocess.run(["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error", *entrada, "-i", str(tmp / "musica.wav"),
                            "-vf", vf, "-af", "afade=t=out:st=" + f"{dur - 1.5:.1f}" + ":d=1.5,volume=0.8",
                            "-t", f"{dur:.1f}", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "22", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(destino)],
                           check=True, timeout=600)
            shutil.rmtree(tmp, ignore_errors=True)
            como = f"con movimiento real ({usada})" if usada else "con movimiento de cámara (el animador gratuito no estaba disponible)"
            return f"Vídeo hecho a partir de la foto, {como}, en Vídeos, carpeta Jarvis.", [destino], destino
        return self._segundo_plano(trabajo, "Animo la foto y le pongo música. En un par de minutos lo tienes.")

    # ---------- canciones
    def cancion(self, peticion: str, con_voz: bool, con_ia: bool = False, forzar: str | None = None,
                web: str | None = None, voz: str = "") -> Respuesta:
        if not self.ia:
            return Respuesta("Para componer necesito la IA en la nube, y ahora mismo no está disponible.")
        tg = self.es_telegram()
        if web and self.estudio:                         # Suno, Udio, AI Make Song…: letra y estilo listos para pegar
            spec = self._json(INSTR_CANCION, peticion, max_tokens=3500, timeout=90)
            texto = (f"Título: {spec.get('titulo', '')}\n\nEstilo: {spec.get('prompt_ia', spec.get('estilo', ''))}"
                     f"\n\nLetra:\n{self.estudio.letra_etiquetada(spec)}")
            return Respuesta(self.estudio.asistir(web, texto))

        def trabajo():
            spec = self._json(INSTR_CANCION, peticion, max_tokens=3500, timeout=90)
            titulo = limpiar_nombre(str(spec.get("titulo") or "Canción"))
            carpeta = sin_pisar(self._carpeta("MUSIC") / titulo)
            carpeta.mkdir(parents=True)
            # letra con acordes
            partes = []
            for s in spec.get("letra") or []:
                if isinstance(s, dict):
                    lineas = [str(x) for x in s.get("lineas") or []]
                    acordes = spec.get("acordes_estribillo") if "estribillo" in normalizar(str(s.get("seccion"))) \
                        else spec.get("acordes_estrofa")
                    partes.append(f"## {s.get('seccion', '')}\n\n**[{' - '.join(acordes or [])}]**\n\n" + "\n".join(lineas))
            cabecera = (f"Estilo: {spec.get('estilo', '')} · {spec.get('bpm', '')} bpm · "
                        f"Estrofa: {' '.join(spec.get('acordes_estrofa') or [])} · "
                        f"Estribillo: {' '.join(spec.get('acordes_estribillo') or [])}")
            cuerpo = cabecera + "\n\n" + "\n\n".join(partes)
            (carpeta / "Letra y acordes.txt").write_text(f"{titulo}\n\n" + re.sub(r"[#*]+ ?", "", cuerpo) + "\n",
                                                          encoding="utf-8")
            archivos = []
            try:
                docx = carpeta / "Letra y acordes.docx"
                crear_docx(docx, titulo, cuerpo)
                pdf = a_pdf(docx, carpeta)
                if pdf:
                    docx.unlink(missing_ok=True)
                    archivos.append(pdf)
            except Exception as e:
                self.log(f"creativo: PDF de la letra: {e!r}")
            # versión CANTADA con la mejor herramienta disponible (ACE-Step gratis, Musicful, Sonauto…)
            if self.estudio:
                try:
                    cantada, h = self.estudio.cancion(spec, carpeta / f"{titulo}.mp3", forzar, voz)
                    archivos.insert(0, cantada)
                    letra_corta = " / ".join(str(x) for s in (spec.get("letra") or [])[:1] if isinstance(s, dict)
                                             for x in (s.get("lineas") or [])[:2])
                    nombre_h = {"ace": "ACE-Step", "musicful": "Musicful", "sonauto": "Sonauto, el motor de Treblo"}
                    return (f"Canción «{titulo}» lista y cantada, {round(duracion(cantada))} segundos, hecha con "
                            f"{nombre_h.get(h, h)}; la letra y los acordes van en PDF. Empieza así: {letra_corta}.",
                            archivos, cantada)
                except SinHerramienta as e:
                    self.log(f"creativo: sin versión cantada ({e}); hago el arreglo propio")
            # arreglo instrumental (rápido) que sigue los acordes
            wav = carpeta / "arreglo.wav"
            dur = arreglo(spec, wav)
            mp3 = a_mp3(wav, carpeta / f"{titulo}.mp3", titulo)
            archivos.insert(0, mp3)
            if con_voz and self.sintetizar:
                archivos.append(self._recitada(spec, wav, carpeta / f"{titulo} (recitada).mp3", titulo))
            wav.unlink(missing_ok=True)
            letra_corta = " / ".join(str(x) for s in (spec.get("letra") or [])[:2] if isinstance(s, dict)
                                     for x in (s.get("lineas") or [])[:2])
            texto = (f"Canción «{titulo}» compuesta: estilo {spec.get('estilo', 'pop')}, {round(dur)} segundos de "
                     f"arreglo, con la letra y los acordes en PDF. Empieza así: {letra_corta}.")
            if con_ia and VENV_MUSICA.exists() and MUSICA_IA.exists():
                threading.Thread(target=self._version_ia, args=(spec, carpeta, titulo, tg), daemon=True).start()
                texto += (" Además estoy haciendo 20 segundos con la IA de música; en este portátil tarda unos "
                          "15 o 20 minutos. Te aviso.")
            elif con_ia:
                texto += " La IA de música no está instalada; tienes el arreglo normal."
            return texto, archivos, mp3
        return self._segundo_plano(trabajo, "Me pongo a componer y a grabarla. En un par de minutos la tienes.")

    def _recitada(self, spec: dict, wav_musica: Path, destino: Path, titulo: str) -> Path:
        tmp = destino.parent / "_voz"
        tmp.mkdir(exist_ok=True)
        trozos = []
        for i, s in enumerate(spec.get("letra") or []):
            if isinstance(s, dict) and s.get("lineas"):
                v = tmp / f"{i:02d}.wav"
                self.sintetizar(". ".join(str(x) for x in s["lineas"]), v)
                trozos.append(v)
        lista = tmp / "lista.txt"
        lista.write_text("".join(f"file '{v.name}'\nfile 'silencio.wav'\n" for v in trozos), encoding="utf-8")
        with wave.open(str(trozos[0]), "rb") as w:
            params = w.getparams()
        with wave.open(str(tmp / "silencio.wav"), "wb") as w:
            w.setparams(params)
            w.writeframes(b"\x00" * int(params.framerate * 2.5) * params.sampwidth * params.nchannels)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
                        "voz.wav"], cwd=tmp, check=True, timeout=300)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_musica), "-i", str(tmp / "voz.wav"),
                        "-filter_complex", "[0:a]volume=0.35[m];[1:a]adelay=4000|4000,volume=1.6[v];"
                        "[m][v]amix=inputs=2:duration=longest,volume=1.8[a]", "-map", "[a]", "-codec:a", "libmp3lame",
                        "-b:a", "192k", "-metadata", f"title={titulo} (recitada)", str(destino)], check=True, timeout=300)
        shutil.rmtree(tmp, ignore_errors=True)
        return destino

    def _version_ia(self, spec: dict, carpeta: Path, titulo: str, tg: bool) -> None:
        """MusicGen en su propio entorno y proceso (así la memoria se libera al terminar)."""
        prompt = str(spec.get("prompt_ia") or f"{spec.get('estilo', 'pop')} song, {spec.get('bpm', 110)} bpm")
        wav = carpeta / "ia.wav"
        try:
            t0 = time.time()
            subprocess.run(["nice", "-n", "15", str(VENV_MUSICA), "-W", "ignore", str(MUSICA_IA), "--prompt", prompt,
                            "--segundos", "20", "--salida", str(wav)], capture_output=True, timeout=3600, check=True)
            mp3 = a_mp3(wav, carpeta / f"{titulo} (versión IA).mp3", f"{titulo} (versión IA)")
            wav.unlink(missing_ok=True)
            self._entregar(f"Ya está la versión hecha por la IA de música de «{titulo}» "
                           f"(20 segundos, {round((time.time() - t0) / 60)} minutos de trabajo).", [mp3], tg, mp3)
        except Exception as e:
            self.log(f"creativo: MusicGen falló: {e!r}")

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)
        reciente = self.ultima_imagen and time.time() - self.ultima_imagen["t"] < 900

        if RE_FONDO.search(t) and (reciente or self.ultima_imagen):
            ruta = self.ultima_imagen["ruta"]
            return Respuesta("Puesta de fondo de pantalla." if poner_fondo(ruta) else
                             "No sé cambiar el fondo en este escritorio.")

        if reciente:
            m = RE_RETOQUE.match(t)
            if m and not re.search(r"\b(cancion|video|musica|excel|word|pdf|plano|presentacion|carpeta)\b", t):
                return self.retocar(con_tildes(peticion, t) or peticion)

        forzar, web = herramienta_pedida(t)              # "con Kling", "en Suno", "con Canva"…
        if re.search(r"\b(video|animacion|clip)\b", t) and re.search(
                r"\b(con|de|a partir de|desde|usando|sobre) (esa|esta|la|mi|ultima|la ultima) (foto|imagen|fotografia|captura)\b"
                r"|\b(esa|esta) (foto|imagen) .*\b(video|animacion)\b", t) or re.match(
                r"^(anima|animame|dale vida a|da vida a|mueve) (esa|esta|la|mi|la ultima) (foto|imagen|fotografia)\b", t):
            from ultimos import ultimo
            candidatas = [p for p in (ultimo("foto"), ultimo("imagen")) if p]
            if not candidatas:
                return Respuesta("No tengo ninguna foto reciente. Hazte una o mándamela por Telegram y te la animo.")
            foto = max(candidatas, key=lambda p: p.stat().st_mtime)
            return self.video_de_foto(foto, con_tildes(peticion, t) or peticion)
        m = RE_VIDEO.search(t)
        if m and not re.search(r"\b(abre|pon|reproduce|busca|mandame|enviame)\b", t[:m.start()]):
            tema = m.group(2).strip(" ,.:")
            if not tema:
                return Respuesta("¿Sobre qué hago el vídeo? Dime por ejemplo: crea un vídeo sobre la Alhambra.")
            con_voz = not re.search(r"\bsin (voz|narracion|narrar|hablar)\b", t)
            if forzar in ("ace", "musicful", "sonauto"):
                forzar = None
            return self.video(peticion, con_voz, forzar, web if web and WEBS[web][2] != "musica" else None)

        m = RE_CANCION.search(t)
        if m and not re.search(r"\b(pon|reproduce|busca|para|quita|sube|baja)\b", t[:m.start()]):
            con_voz = bool(re.search(r"\b(con voz|cantada|que la cantes|cantala|recitada|con tu voz)\b", t))
            con_ia = bool(re.search(r"\b(con (la )?ia|ia de musica|inteligencia artificial|musicgen|version ia)\b", t))
            voz = ("female" if re.search(r"\b(voz (de )?mujer|voz femenina|cantante femenina|que la cante una chica|cantada por una mujer)\b", t)
                   else "male" if re.search(r"\b(voz (de )?hombre|voz masculina|cantante masculino|cantada por un hombre)\b", t) else "")
            if forzar not in (None, "ace", "musicful", "sonauto"):
                forzar = None
            return self.cancion(peticion, con_voz, con_ia, forzar, web if web and WEBS[web][2] == "musica" else None, voz)

        m = RE_IMAGEN.search(t) or RE_DIBUJA.match(t)
        if m and web and WEBS[web][2] == "diseno" and self.estudio:   # diseños en Canva, Photopea, Adobe Express
            texto = self._json(INSTR_IMAGEN, peticion, max_tokens=800, timeout=45).get("prompt") or peticion
            return Respuesta(self.estudio.asistir(web, f"{con_tildes(peticion, t) or peticion}\n\nIdea visual: {texto}"))
        m = RE_IMAGEN.search(t)
        if m and not re.search(r"\bplano|\bcroquis|\bexcel|\bword\b", t):
            if not m.group(2).strip(" ,.:"):
                return Respuesta("¿De qué? Dime por ejemplo: crea una imagen de un faro al atardecer.")
            fondo = "fondo" in m.group(1) or "wallpaper" in m.group(1)
            return self.imagen(peticion, "fondo" if fondo else None)
        m = RE_DIBUJA.match(t)
        if m and not re.search(r"\b(plano|planta|croquis|dxf|dwg)\b", t):
            return self.imagen(peticion)
        return None
