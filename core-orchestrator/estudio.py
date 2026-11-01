"""
Estudio de Jarvis: generadores de música y vídeo de fuera que usa como herramientas propias, sin que
haya que decírselo. Para cada encargo elige el mejor disponible y, si falla, pasa al siguiente.

Siempre se prueba PRIMERO lo gratuito; las de pago solo si lo gratis falla o se agota (o si se nombran).

Canciones CANTADAS (voz de verdad):
  1. Hugging Face: ACE-Step (GRATIS, sin clave)       → con "clave de huggingface hf_…" tienes más cupo
  2. Musicful (API, con clave)                       → "clave de musicful XXXX" por Telegram
  3. fal.ai: Sonauto V2 (el motor de Treblo)          → "clave de fal XXXX"
  4. Si nada responde: el arreglo propio de Jarvis (instrumental) como hasta ahora.

Clips de vídeo con MOVIMIENTO de verdad (para cada escena de los vídeos):
  1. Hugging Face: Wan 2.2 (anima la imagen) y LTX-Video (texto a vídeo) — GRATIS
  2. Runway Gen-4 Turbo (API, con clave y saldo)      → "clave de runway key_…"
  3. fal.ai: Kling 2.5 Turbo, Pika 2.2, Luma Ray 2    → con la clave de fal
  4. Si no: la imagen con zoom suave, como hasta ahora.

Imágenes: Hugging Face FLUX.1-schnell (GRATIS, sin marca de agua) y, si no, Pollinations (creativo.py).

Webs sin API (Suno, Udio, AI Make Song, Treblo, Kling, Luma, Pika, Runway, CapCut, Canva, Clipchamp,
Photopea, Adobe Express): modo asistido. Jarvis prepara la letra, el prompt o el guion, lo deja copiado
(y en un archivo, y por Telegram si vas por ahí) y abre la web en el navegador para que solo pegues.

Gasto: las de pago tienen un límite diario conjunto ("estudio_limite_dia", 1 $ por defecto).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from perfil import DATOS, SECRETOS
from herramientas import guardar_config, leer_config, normalizar

HOME = Path.home()
CLAVES = SECRETOS / "estudio.json"
GASTO = DATOS / "logs" / "estudio_gasto.json"
TMP = Path(tempfile.gettempdir()) / "jarvis" / "estudio"
UA = "Mozilla/5.0 (X11; Linux x86_64) Jarvis/1.0"

# Spaces gratuitos de Hugging Face (comprobados el 20 oct 2026)
HF_ACE = "ACE-Step/ACE-Step"
HF_WAN = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
HF_LTX = "Lightricks/ltx-video-distilled"
HF_FLUX = "black-forest-labs/FLUX.1-schnell"     # comprobado el 21 oct 2026 (/infer)

# fal.ai (una sola clave para todos). Precio aproximado por uso, en dólares.
FAL = {
    "sonauto": ("sonauto/v2/text-to-music", 0.075),
    "kling": ("fal-ai/kling-video/v2.5-turbo/pro/text-to-video", 0.35),
    "pika": ("fal-ai/pika/v2.2/text-to-video", 0.20),
    "luma": ("fal-ai/luma-dream-machine/ray-2", 0.50),
}
PRECIO = {"musicful": 0.10, "runway": 0.25}          # estimado por canción / por clip de 5 s

NOMBRES = {   # cómo lo dice el usuario → herramienta
    "musicful": "musicful", "treblo": "sonauto", "sonauto": "sonauto", "ace step": "ace", "acestep": "ace",
    "runway": "runway", "kling": "kling", "pika": "pika", "luma": "luma", "dream machine": "luma",
    "wan": "wan", "ltx": "ltx",
}
WEBS = {
    "suno": ("Suno", "https://suno.com/create", "musica"),
    "udio": ("Udio", "https://www.udio.com/create", "musica"),
    "ai make song": ("AI Make Song", "https://aimakesong.com/", "musica"),
    "aimakesong": ("AI Make Song", "https://aimakesong.com/", "musica"),
    "musicful": ("Musicful", "https://www.musicful.ai/", "musica"),
    "treblo": ("Treblo", "https://treblo.com/", "musica"),
    "kling": ("Kling AI", "https://app.klingai.com/global/text-to-video/new", "video"),
    "luma": ("Luma Dream Machine", "https://dream-machine.lumalabs.ai/", "video"),
    "pika": ("Pika", "https://pika.art/", "video"),
    "runway": ("Runway", "https://app.runwayml.com/", "video"),
    "capcut": ("CapCut", "https://www.capcut.com/editor", "guion"),
    "canva": ("Canva", "https://www.canva.com/", "diseno"),
    "clipchamp": ("Clipchamp", "https://app.clipchamp.com/", "guion"),
    "photopea": ("Photopea", "https://www.photopea.com/", "diseno"),
    "adobe express": ("Adobe Express", "https://new.express.adobe.com/", "diseno"),
}


def dolares(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + " dólares"


class SinHerramienta(Exception):
    pass


def leer_claves() -> dict:
    try:
        return json.loads(CLAVES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_clave(servicio: str, clave: str) -> None:
    c = leer_claves()
    c[servicio] = clave.strip()
    CLAVES.parent.mkdir(parents=True, exist_ok=True)
    CLAVES.write_text(json.dumps(c, indent=1), encoding="utf-8")
    CLAVES.chmod(0o600)


def _http(url: str, datos: dict | None = None, cabeceras: dict | None = None, metodo: str | None = None,
          timeout: float = 60) -> dict:
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers={
        "User-Agent": UA, **({"Content-Type": "application/json"} if cuerpo else {}), **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _bajar(url: str, destino: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)
    if destino.stat().st_size < 2000:
        raise SinHerramienta("archivo descargado vacío")
    return destino


def _urls(obj) -> list[str]:
    """Todas las URL de audio o vídeo que haya en una respuesta, por anidada que esté."""
    fuera = []
    if isinstance(obj, str):
        if obj.startswith("http") and re.search(r"\.(mp4|mov|webm|mp3|wav|flac|ogg|m4a)(\?|$)|/files/|storage", obj):
            fuera.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            fuera += _urls(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            fuera += _urls(v)
    return fuera


def _ruta_gradio(r) -> Path:
    """gradio_client devuelve rutas en formatos variados: str, dict(video=…), tuplas…"""
    for _ in range(4):
        if isinstance(r, (list, tuple)):
            r = r[0]
        elif isinstance(r, dict):
            r = r.get("video") or r.get("path") or r.get("value") or next(iter(r.values()))
        else:
            break
    p = Path(str(r))
    if not p.exists():
        raise SinHerramienta("el generador no devolvió archivo")
    return p


def duracion(ruta: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return 0.0


def copiar_al_portapapeles(texto: str) -> bool:
    for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["wl-copy"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=texto.encode(), timeout=5, env={"DISPLAY": ":0", **__import__("os").environ})
                return True
            except (OSError, subprocess.TimeoutExpired):
                pass
    # sin xclip: GTK del Python del sistema (el portapapeles se queda mientras viva el proceso, 10 min)
    codigo = ("import sys,gi;gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk,GLib;"
              "c=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);c.set_text(sys.stdin.read(),-1);c.store();"
              "GLib.timeout_add_seconds(600,Gtk.main_quit);Gtk.main()")
    try:
        p = subprocess.Popen(["/usr/bin/python3", "-c", codigo], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env={**__import__("os").environ, "DISPLAY": ":0"},
                             start_new_session=True)
        p.stdin.write(texto.encode())
        p.stdin.close()
        time.sleep(1.5)
        return p.poll() is None
    except OSError:
        return False


class Estudio:
    def __init__(self, log=print, ui=None, avisar: Callable[[str], None] | None = None,
                 es_telegram: Callable[[], bool] | None = None):
        self.log = log
        self.ui = ui
        self.avisar = avisar or (lambda t: None)
        self.es_telegram = es_telegram or (lambda: False)
        self._agotado: dict[str, float] = {}          # herramienta → hasta cuándo no probarla
        self._lock = threading.Lock()
        TMP.mkdir(parents=True, exist_ok=True)

    # ---------- gasto
    @staticmethod
    def limite() -> float:
        try:
            return float(leer_config().get("estudio_limite_dia", 1.0))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def gasto_hoy() -> float:
        try:
            return float(json.loads(GASTO.read_text(encoding="utf-8")).get(dt.date.today().isoformat(), 0.0))
        except (OSError, ValueError):
            return 0.0

    def _anotar(self, dolares: float, que: str) -> None:
        with self._lock:
            try:
                g = json.loads(GASTO.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                g = {}
            hoy = dt.date.today().isoformat()
            g[hoy] = round(float(g.get(hoy, 0.0)) + dolares, 4)
            GASTO.parent.mkdir(parents=True, exist_ok=True)
            GASTO.write_text(json.dumps(dict(sorted(g.items())[-60:]), indent=1), encoding="utf-8")
        self.log(f"estudio: {que} ≈ {dolares:.3f} $ (hoy {self.gasto_hoy():.2f} $)")

    def _puede_pagar(self, dolares: float) -> bool:
        return self.gasto_hoy() + dolares <= self.limite()

    def _disponible(self, h: str) -> bool:
        return self._agotado.get(h, 0) < time.time()

    def _apartar(self, h: str, segundos: float, motivo: str) -> None:
        self._agotado[h] = time.time() + segundos
        self.log(f"estudio: {h} apartado {int(segundos / 60)} min ({motivo})")

    def _actividad(self, texto: str) -> None:
        if self.ui:
            self.ui.enviar(tipo="actividad", texto=texto)

    # ---------- qué hay
    def herramientas(self, tipo: str) -> list[str]:
        c = leer_claves()
        # lo gratuito primero; lo de pago, de reserva
        if tipo == "cancion":
            orden = ["ace"] + (["musicful"] if c.get("musicful") else []) + (["sonauto"] if c.get("fal") else [])
        elif tipo == "imagen":
            orden = ["flux"]
        else:
            orden = (["wan", "ltx"] + (["runway"] if c.get("runway") else [])
                     + (["kling", "pika", "luma"] if c.get("fal") else []))
        preferida = leer_config().get(f"estudio_{tipo}")
        if preferida in orden:
            orden.remove(preferida)
            orden.insert(0, preferida)
        return [h for h in orden if self._disponible(h)]

    def resumen(self) -> str:
        c = leer_claves()
        nombres = {"musicful": "Musicful", "sonauto": "Sonauto (el motor de Treblo)", "ace": "ACE-Step gratis",
                   "runway": "Runway", "kling": "Kling", "pika": "Pika", "luma": "Luma", "wan": "Wan gratis",
                   "ltx": "LTX gratis", "flux": "FLUX gratis"}

        def lista(tipo: str) -> str:
            hs = self.herramientas(tipo)
            if hs:
                return ", ".join(nombres[h] for h in hs)
            vuelve = min((v for v in self._agotado.values() if v > time.time()), default=time.time())
            return f"ahora mismo ninguna (cupo gratuito agotado; vuelvo a probar en {max(1, int((vuelve - time.time()) / 60))} minutos)"
        partes = ["Primero lo gratuito. Para canciones cantadas uso " + lista("cancion"),
                  "para vídeo con movimiento " + lista("video"),
                  "para imágenes " + (lista("imagen") if self.herramientas("imagen") else "Pollinations") +
                  (" y, si se agota, Pollinations" if self.herramientas("imagen") else "")]
        faltan = [n for n, k in (("Musicful", "musicful"), ("fal.ai (Kling, Pika, Luma y Treblo)", "fal"),
                                 ("Runway", "runway")) if not c.get(k)]
        texto = "; ".join(partes) + "."
        if faltan:
            texto += " Sin clave todavía: " + ", ".join(faltan) + "."
        texto += (" Y en modo asistido te abro Suno, Udio, AI Make Song, CapCut, Canva y las demás webs con todo "
                  f"preparado. Gasto de hoy en las de pago: {dolares(self.gasto_hoy())} de {dolares(self.limite())}.")
        return texto

    # ---------- Hugging Face (gratis)
    def _hf(self, espacio: str, *args, api: str, intentos: int = 2):
        from gradio_client import Client
        token = leer_claves().get("hf") or None
        ultimo = None
        for intento in range(intentos):
            try:
                try:
                    c = Client(espacio, token=token, verbose=False) if token else Client(espacio, verbose=False)
                except TypeError:
                    c = Client(espacio, hf_token=token, verbose=False)
                return c.predict(*args, api_name=api)
            except Exception as e:
                ultimo = e
                texto = str(e).lower()
                if "quota" in texto or "exceeded" in texto or "gpu" in texto and "limit" in texto:
                    raise SinHerramienta("cupo gratuito de GPU agotado") from e
                time.sleep(5)
        raise SinHerramienta(f"{espacio}: {type(ultimo).__name__} {str(ultimo)[:120]}")

    # ---------- fal.ai
    def _fal(self, modelo: str, entrada: dict, timeout: float = 600) -> dict:
        clave = leer_claves().get("fal")
        if not clave:
            raise SinHerramienta("sin clave de fal")
        cab = {"Authorization": f"Key {clave}"}
        try:
            r = _http(f"https://queue.fal.run/{modelo}", entrada, cab, timeout=60)
        except urllib.error.HTTPError as e:
            detalle = e.read()[:200].decode("utf-8", "ignore")
            raise SinHerramienta(f"fal {e.code}: {detalle}") from e
        estado, resultado = r.get("status_url"), r.get("response_url")
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(5)
            s = _http(estado, cabeceras=cab, timeout=30)
            if s.get("status") == "COMPLETED":
                return _http(resultado, cabeceras=cab, timeout=60)
            if s.get("status") in ("FAILED", "ERROR"):
                raise SinHerramienta(f"fal: {str(s)[:150]}")
        raise SinHerramienta("fal: tarda demasiado")

    # ---------- canciones cantadas
    @staticmethod
    def letra_etiquetada(spec: dict) -> str:
        """[verse]/[chorus]/[bridge], que es como lo entienden ACE-Step, Sonauto y Musicful."""
        trozos = []
        for s in spec.get("letra") or []:
            if not isinstance(s, dict):
                continue
            sec = normalizar(str(s.get("seccion", "")))
            tag = "chorus" if "estribillo" in sec or "coro" in sec else "bridge" if "puente" in sec else \
                "intro" if "intro" in sec else "outro" if "final" in sec or "outro" in sec else "verse"
            trozos.append(f"[{tag}]\n" + "\n".join(str(x) for x in s.get("lineas") or []))
        return "\n\n".join(trozos)

    def cancion(self, spec: dict, destino_mp3: Path, forzar: str | None = None, voz: str = "") -> tuple[Path, str]:
        """Canción con voz cantada. Devuelve (mp3, herramienta) o lanza SinHerramienta."""
        letra = self.letra_etiquetada(spec)
        estilo = str(spec.get("prompt_ia") or spec.get("estilo") or "pop").strip()
        estilo_voz = estilo + (", " if estilo else "") + ("female vocal" if voz == "female" else "male vocal"
                                                          if voz == "male" else "") + ", spanish lyrics"
        lineas = sum(len(s.get("lineas") or []) for s in spec.get("letra") or [] if isinstance(s, dict))
        segundos = max(60, min(180, 12 + lineas * 4.2))
        orden = [forzar] if forzar else self.herramientas("cancion")
        errores = []
        for h in orden:
            try:
                self._actividad(f"Estudio · canción con {h}")
                t0 = time.time()
                if h == "ace":
                    r = self._hf(HF_ACE, segundos, estilo_voz.replace("spanish lyrics", "spanish, vocals"), letra, 27,
                                 15.0, "euler", "apg", 10.0, None, 0.5, 0.0, 3.0, True, False, True, None, 0.0, 0.0,
                                 False, 0.5, None, "none", api="/__call__")
                    origen = _ruta_gradio(r)
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(origen), "-codec:a", "libmp3lame",
                                    "-b:a", "192k", "-metadata", f"title={spec.get('titulo', '')}", str(destino_mp3)],
                                   check=True, timeout=300)
                elif h == "sonauto":
                    modelo, precio = FAL["sonauto"]
                    if not self._puede_pagar(precio):
                        raise SinHerramienta("límite diario de gasto")
                    r = self._fal(modelo, {"prompt": estilo, "lyrics": letra, "output_format": "mp3"})
                    self._anotar(precio, "Sonauto")
                    _bajar(_urls(r)[0], destino_mp3)
                elif h == "musicful":
                    if not self._puede_pagar(PRECIO["musicful"]):
                        raise SinHerramienta("límite diario de gasto")
                    self._musicful(spec, estilo, letra, voz, destino_mp3)
                    self._anotar(PRECIO["musicful"], "Musicful")
                else:
                    raise SinHerramienta(f"{h} no hace canciones")
                self.log(f"estudio: canción con {h} en {time.time() - t0:.0f} s")
                return destino_mp3, h
            except Exception as e:
                errores.append(f"{h}: {e}")
                self.log(f"estudio: {h} falló: {e}")
                if "cupo" in str(e) or "límite" in str(e):
                    self._apartar(h, 3600, str(e))
                else:
                    self._apartar(h, 600, "error")
        raise SinHerramienta("; ".join(errores) or "no hay herramientas de canción disponibles")

    def _musicful(self, spec: dict, estilo: str, letra: str, voz: str, destino: Path) -> Path:
        cab = {"x-api-key": leer_claves()["musicful"]}
        cuerpo = {"action": "custom", "mv": "MFV3.0", "style": estilo[:200], "lyrics": letra,
                  "title": str(spec.get("titulo", ""))[:80], "instrumental": 0, "gender": voz or ""}
        r = _http("https://api.musicful.ai/v1/music/generate", cuerpo, cab, timeout=60)
        ids = []

        def buscar(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ("ids", "task_ids") and isinstance(v, list):
                        ids.extend(str(x) for x in v)
                    elif k in ("id", "task_id") and isinstance(v, (str, int)):
                        ids.append(str(v))
                    else:
                        buscar(v)
            elif isinstance(o, list):
                for v in o:
                    buscar(v)
        buscar(r)
        if not ids:
            raise SinHerramienta(f"Musicful no devolvió tarea: {str(r)[:150]}")
        t0 = time.time()
        while time.time() - t0 < 600:
            time.sleep(8)
            canciones = _http(f"https://api.musicful.ai/v1/music/tasks?ids={','.join(ids[:2])}", cabeceras=cab)
            canciones = canciones.get("data", canciones) if isinstance(canciones, dict) else canciones
            for s in canciones or []:
                if s.get("fail_code") or s.get("fail_reason"):
                    raise SinHerramienta(f"Musicful: {s.get('fail_reason')}")
                if s.get("audio_url"):
                    return _bajar(s["audio_url"], destino)
        raise SinHerramienta("Musicful tarda demasiado")

    # ---------- imágenes (gratis)
    def imagen(self, prompt_en: str, ancho: int, alto: int, destino: Path, semilla: int | None = None) -> Path:
        """FLUX.1-schnell en Hugging Face. Lanza SinHerramienta si no está o se agota el cupo."""
        if not self._disponible("flux"):
            raise SinHerramienta("flux apartado")
        # FLUX trabaja en múltiplos de 32 y hasta 2048; se pide a esa medida y se ajusta después
        w, h = (max(256, min(1440, round(x / 32) * 32)) for x in (ancho, alto))
        try:
            self._actividad("Estudio · imagen con FLUX")
            t0 = time.time()
            # desde el 25 oct el espacio rechaza los decimales («AppError TypeError»): números enteros
            r = self._hf(HF_FLUX, prompt_en[:1500], int(semilla or 0), semilla is None, int(w), int(h), 4,
                         api="/infer", intentos=1)
            origen = _ruta_gradio(r)
            from PIL import Image
            with Image.open(origen) as im:
                im = im.convert("RGB")
                if im.size != (ancho, alto):
                    im = im.resize((ancho, alto), Image.LANCZOS)
                destino.parent.mkdir(parents=True, exist_ok=True)
                im.save(destino, "JPEG", quality=92)
            self.log(f"estudio: imagen con FLUX en {time.time() - t0:.0f} s")
            return destino
        except Exception as e:
            self.log(f"estudio: flux falló: {e}")
            self._apartar("flux", 3600 if "cupo" in str(e) else 600, str(e)[:60])
            raise SinHerramienta(str(e)) from e

    # ---------- clips de vídeo con movimiento
    def clip(self, prompt_en: str, imagen: Path | None, destino: Path, forzar: str | None = None) -> tuple[Path, str]:
        orden = [forzar] if forzar else self.herramientas("video")
        errores = []
        for h in orden:
            try:
                if h == "wan" and not (imagen and imagen.exists()):
                    continue
                self._actividad(f"Estudio · clip con {h}")
                t0 = time.time()
                if h == "wan":
                    from gradio_client import handle_file
                    r = self._hf(HF_WAN, handle_file(str(imagen)), prompt_en + ", smooth cinematic motion", 6,
                                 "static, blurred, low quality, watermark, text, subtitles", 3.5, 1, 1, 42, True,
                                 api="/generate_video")
                    shutil.copy(_ruta_gradio(r), destino)
                elif h == "ltx":
                    r = self._hf(HF_LTX, prompt_en, "worst quality, inconsistent motion, blurry, jittery, distorted",
                                 None, None, 512, 896, "text-to-video", 4, 9, 42, True, 1, True, api="/text_to_video")
                    shutil.copy(_ruta_gradio(r), destino)
                elif h == "runway":
                    if not self._puede_pagar(PRECIO["runway"]):
                        raise SinHerramienta("límite diario de gasto")
                    self._runway(prompt_en, imagen, destino)
                    self._anotar(PRECIO["runway"], "Runway clip")
                elif h in ("kling", "pika", "luma"):
                    modelo, precio = FAL[h]
                    if not self._puede_pagar(precio):
                        raise SinHerramienta("límite diario de gasto")
                    entrada = {"prompt": prompt_en, "aspect_ratio": "16:9"}
                    entrada.update({"kling": {"duration": "5"}, "pika": {"duration": 5, "resolution": "720p"},
                                    "luma": {"duration": "5s", "resolution": "720p"}}[h])
                    r = self._fal(modelo, entrada)
                    self._anotar(precio, f"{h} clip")
                    _bajar(_urls(r)[0], destino)
                else:
                    continue
                if duracion(destino) < 1:
                    raise SinHerramienta("clip vacío")
                self.log(f"estudio: clip con {h} en {time.time() - t0:.0f} s")
                return destino, h
            except Exception as e:
                errores.append(f"{h}: {e}")
                self.log(f"estudio: {h} falló: {e}")
                self._apartar(h, 3600 if "cupo" in str(e) or "límite" in str(e) else 600, str(e)[:60])
        raise SinHerramienta("; ".join(errores) or "no hay herramientas de vídeo disponibles")

    def _runway(self, prompt_en: str, imagen: Path | None, destino: Path) -> Path:
        if not (imagen and imagen.exists()):
            raise SinHerramienta("Runway necesita una imagen de partida")
        cab = {"Authorization": f"Bearer {leer_claves()['runway']}", "X-Runway-Version": "2024-11-06"}
        uri = "data:image/jpeg;base64," + base64.b64encode(imagen.read_bytes()).decode()
        try:
            r = _http("https://api.dev.runwayml.com/v1/image_to_video",
                      {"model": "gen4_turbo", "promptImage": uri, "promptText": prompt_en[:900],
                       "ratio": "1280:720", "duration": 5}, cab, timeout=60)
        except urllib.error.HTTPError as e:
            raise SinHerramienta(f"Runway {e.code}: {e.read()[:150].decode('utf-8', 'ignore')}") from e
        t0 = time.time()
        while time.time() - t0 < 600:
            time.sleep(6)
            s = _http(f"https://api.dev.runwayml.com/v1/tasks/{r['id']}", cabeceras=cab, timeout=30)
            if s.get("status") == "SUCCEEDED":
                return _bajar(s["output"][0], destino)
            if s.get("status") in ("FAILED", "CANCELLED"):
                raise SinHerramienta(f"Runway: {s.get('failure') or s.get('status')}")
        raise SinHerramienta("Runway tarda demasiado")

    # ---------- webs sin API: modo asistido
    def asistir(self, clave_web: str, texto: str) -> str:
        nombre, url, _ = WEBS[clave_web]
        carpeta = HOME / "Documentos" / "Jarvis"
        carpeta.mkdir(parents=True, exist_ok=True)
        archivo = carpeta / f"Para {nombre}.txt"
        archivo.write_text(texto + "\n", encoding="utf-8")
        if self.es_telegram():
            return (f"Esto es lo que tienes que pegar en {nombre} ({url}):\n\n{texto}\n\n"
                    f"Lo tienes también en el portátil: Documentos/Jarvis/{archivo.name}.")
        copiado = copiar_al_portapapeles(texto)
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass
        return (f"Te abro {nombre}. " + ("Ya lo tienes copiado: pega con control uve. " if copiado else
                                        f"Lo tienes en Documentos, Jarvis, «{archivo.name}». ")
                + "Si no has entrado nunca, tendrás que iniciar sesión.")

    # ---------- órdenes propias
    def manejar(self, peticion: str):
        from sistema import Respuesta
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)
        if re.search(r"\bque (herramientas|webs|programas) (de creacion |creativas |de musica |de video )?"
                     r"(tienes|usas|conoces)\b|\bestado del estudio\b", t):
            return Respuesta(self.resumen())
        if re.search(r"\b(cuanto|que) (llevo gastado|he gastado|gasto)\b.*\b(estudio|videos|canciones|runway|fal|musicful)\b", t):
            return Respuesta(f"Hoy llevo {dolares(self.gasto_hoy())} en las herramientas de pago, de un límite de "
                             f"{dolares(self.limite())}.")
        m = re.search(r"\bpon el limite (?:del estudio|de (?:videos|canciones|las herramientas)) a (\d+(?:[.,]\d+)?)", t)
        if m:
            guardar_config(estudio_limite_dia=float(m.group(1).replace(",", ".")))
            return Respuesta("Hecho, nuevo límite diario para las herramientas de pago.")
        m = re.search(r"\busa (?:siempre |preferiblemente )?(\w[\w ]*?) (?:para|en) (?:las |los )?(canciones|videos)\b", t)
        if m and NOMBRES.get(m.group(1).strip()):
            tipo = "cancion" if m.group(2) == "canciones" else "video"
            guardar_config(**{f"estudio_{tipo}": NOMBRES[m.group(1).strip()]})
            pref = NOMBRES[m.group(1).strip()]
            aviso = "" if pref in self.herramientas(tipo) else " En cuanto tenga su clave; mientras, sigo con lo gratuito."
            return Respuesta(f"De acuerdo, para {m.group(2)} probaré primero {m.group(1)}.{aviso}")
        return None


def herramienta_pedida(t: str) -> tuple[str | None, str | None]:
    """('kling', None) si se puede por API; (None, 'suno') si es una web sin API; (None, None) si no nombra ninguna."""
    m = re.search(r"\b(?:con|en|usando|mediante|desde)\s+(?:el |la )?(" + "|".join(
        sorted(set(NOMBRES) | set(WEBS), key=len, reverse=True)) + r")\b", t)
    if not m:
        return None, None
    nombre = m.group(1)
    c = leer_claves()
    api = NOMBRES.get(nombre)
    if api == "musicful" and c.get("musicful") or api in ("sonauto", "kling", "pika", "luma") and c.get("fal") \
            or api == "runway" and c.get("runway") or api in ("ace", "wan", "ltx"):
        return api, None
    return None, nombre if nombre in WEBS else None


def comprobar_clave(servicio: str, clave: str) -> str:
    """Prueba la clave sin gastar nada. Devuelve un texto para el usuario."""
    try:
        if servicio == "musicful":
            r = _http("https://api.musicful.ai/v1/get_api_key_info", cabeceras={"x-api-key": clave}, timeout=20)
            return f"Musicful acepta la clave; te quedan {r.get('key_music_counts', '?')} canciones."
        if servicio == "runway":
            r = _http("https://api.dev.runwayml.com/v1/organization", timeout=20,
                      cabeceras={"Authorization": f"Bearer {clave}", "X-Runway-Version": "2024-11-06"})
            return f"Runway acepta la clave; saldo: {r.get('creditBalance', '?')} créditos."
        if servicio == "elevenlabs":
            r = _http("https://api.elevenlabs.io/v1/user/subscription", cabeceras={"xi-api-key": clave}, timeout=20)
            return (f"ElevenLabs acepta la clave (plan {r.get('tier', '?')}, {r.get('character_count', 0)} de "
                    f"{r.get('character_limit', '?')} caracteres usados este mes). Ahora dime «voz de elevenlabs» y "
                    "el identificador de la voz.")
        if servicio == "hf":
            r = _http("https://huggingface.co/api/whoami-v2", cabeceras={"Authorization": f"Bearer {clave}"}, timeout=20)
            return f"Hugging Face acepta el token de {r.get('name', 'tu cuenta')}: tendrás más cupo gratis."
        if servicio == "fal":
            return "Clave de fal guardada; la probaré en el primer encargo (Kling, Pika, Luma y Sonauto)."
    except urllib.error.HTTPError as e:
        return f"Ojo: {servicio} responde {e.code} con esa clave. La guardo igualmente; revísala si falla."
    except Exception as e:
        return f"La guardo, pero no he podido comprobarla ({type(e).__name__})."
    return "Clave guardada."
