"""
Vídeo y música: YouTube, TikTok, la música del portátil con VLC y los mandos (pausa, sigue, siguiente…).

  "busca en youtube recetas de croquetas"          → página de resultados
  "pon en youtube despacito", "ponme el vídeo de X en youtube", "quiero ver X en youtube" → el primer vídeo
  "... en vlc"                                      → ese vídeo de YouTube en VLC
  "abre tiktok", "pon tiktok"                       → Para ti
  "busca en tiktok gatos", "pon tiktoks de cocina"  → búsqueda; "abre el tiktok de @usuario" → su perfil
  "pon música" (la carpeta Música, al azar), "pon música de Estopa" (sus archivos; si no hay, YouTube)
  "pausa", "para la música", "sigue", "continúa", "siguiente", "anterior", "pasa al siguiente tiktok"
Los vídeos y la música que hace Jarvis se abren con VLC (herramientas.abrir_archivo).
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from herramientas import abrir_web, carpeta_usuario, lanzar, normalizar
from sistema import Respuesta

HOME = Path.home()
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
EXT_AUDIO = {".mp3", ".ogg", ".flac", ".wav", ".m4a", ".opus", ".aac", ".wma"}
EXT_VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".wmv"}

VERBO_PONER = r"(?:pon|ponme|ponnos|reproduce|reproduceme|quiero ver|quiero escuchar|quiero oir|abre|abreme|ensename|muestrame)"
VERBO_BUSCAR = r"(?:busca|buscame|buscar|mira|encuentra|encuentrame)"


def _normalizar(t: str) -> str:
    t = normalizar(t).strip(" .¿?¡!")
    t = re.sub(r"\b(?:ti[ck]|tic)[ -]?to[ck]s?\b", lambda m: "tiktoks" if m.group(0).endswith("s") else "tiktok", t)
    t = re.sub(r"\byou ?tu(?:be|b|ve)\b|\byutub\w*\b", "youtube", t)
    t = re.sub(r"\b(?:v l c|uve ele ce)\b", "vlc", t)
    return re.sub(r"^(?:por favor|oye|venga|jarvis|y)[ ,]+", "", t).strip()


def youtube_primero(busqueda: str) -> tuple[str, str] | None:
    """(id, título) del primer vídeo de YouTube, sin clave: la página de resultados trae los ids."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(busqueda) + "&sp=EgIQAQ%3D%3D"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", "ignore")
    except OSError:
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,1500}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
                  html, re.S)
    if m:
        try:
            titulo = json.loads(f'"{m.group(2)}"')
        except ValueError:
            titulo = m.group(2)
        return m.group(1), titulo
    ids = re.findall(r'"videoId":"([\w-]{11})"', html)
    return (ids[0], busqueda) if ids else None


# ---------------------------------------------------------------- mandos (MPRIS por D-Bus)
def reproductores() -> list[str]:
    """Nombres D-Bus de los reproductores abiertos (VLC primero, luego Firefox…)."""
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path",
                            "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.ListNames"],
                           capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return []
    nombres = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", r.stdout)
    return sorted(nombres, key=lambda n: (0 if "vlc" in n else 1 if "firefox" in n else 2))


def _estado(nombre: str) -> str:
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", nombre, "--object-path", "/org/mpris/MediaPlayer2",
                            "--method", "org.freedesktop.DBus.Properties.Get", "org.mpris.MediaPlayer2.Player",
                            "PlaybackStatus"], capture_output=True, text=True, timeout=4)
        return "Playing" if "Playing" in r.stdout else "Paused" if "Paused" in r.stdout else "Stopped"
    except (OSError, subprocess.TimeoutExpired):
        return "Stopped"


def mando(metodo: str) -> str | None:
    """PlayPause / Pause / Play / Next / Previous / Stop al reproductor que esté sonando (o al primero)."""
    lista = reproductores()
    if not lista:
        return None
    if metodo in ("Pause", "Stop", "Next", "Previous"):
        sonando = [n for n in lista if _estado(n) == "Playing"]
        lista = sonando or lista
    elif metodo == "Play":
        parados = [n for n in lista if _estado(n) == "Paused"]
        lista = parados or lista
    nombre = lista[0]
    try:
        subprocess.run(["gdbus", "call", "--session", "--dest", nombre, "--object-path", "/org/mpris/MediaPlayer2",
                        "--method", f"org.mpris.MediaPlayer2.Player.{metodo}"], capture_output=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return "vlc" if "vlc" in nombre else "firefox" if "firefox" in nombre else nombre.rsplit(".", 1)[-1]


def _ventana_tiktok() -> str | None:
    try:
        r = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for linea in r.stdout.splitlines():
        if "tiktok" in linea.lower():
            return linea.split()[0]
    return None


def tecla_en_ventana(wid: str, tecla: str) -> bool:
    if not shutil.which("xdotool"):
        return False
    try:
        subprocess.run(["wmctrl", "-i", "-a", wid], timeout=3)
        subprocess.run(["xdotool", "sleep", "0.3", "key", tecla], timeout=5)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------- música del portátil
def carpeta_musica() -> Path:
    c = carpeta_usuario("MUSIC")
    return c if c != HOME else HOME / "Música"


def canciones(carpeta: Path | None = None) -> list[Path]:
    c = carpeta or carpeta_musica()
    if not c.exists():
        return []
    return [p for p in c.rglob("*") if p.suffix.lower() in EXT_AUDIO and p.is_file()][:5000]


def buscar_musica(que: str) -> list[Path]:
    palabras = [w for w in normalizar(que).split() if len(w) > 2 and w not in ("musica", "cancion", "canciones", "de", "del")]
    if not palabras:
        return []
    res = []
    for p in canciones():
        ruta = normalizar(str(p.relative_to(carpeta_musica())))
        if all(w in ruta for w in palabras):
            res.append(p)
    return sorted(res)


def vlc(*args: str) -> bool:
    if not shutil.which("vlc"):
        return False
    lanzar(["vlc", "--one-instance", "--no-playlist-enqueue", *args])
    return True


class Medios:
    def __init__(self, log=print, es_telegram: Callable[[], bool] | None = None, avisar=None):
        self.log = log
        self.es_telegram = es_telegram or (lambda: False)
        self.avisar = avisar or (lambda t: None)

    def _web(self, url: str, texto: str) -> Respuesta:
        if self.es_telegram():
            return Respuesta(f"{texto} en el portátil. Si lo quieres en el móvil: {url}") if self._abrir(url) else \
                Respuesta(url)
        self._abrir(url)
        return Respuesta(texto + ".")

    @staticmethod
    def _abrir(url: str) -> bool:
        try:
            abrir_web(url)
            return True
        except OSError:
            return False

    # ---------------------------------------------------------------- YouTube
    def youtube(self, que: str, reproducir: bool, en_vlc: bool = False) -> Respuesta:
        que = re.sub(r"^(?:el |un |los |unos )?(?:videos?|videoclips?|clips?|canciones?|temas?) (?:de |del |sobre )?", "", que).strip()
        que = re.sub(r"^(?:la |el )", "", que).strip()
        if not que:
            return self._web("https://www.youtube.com", "Abriendo YouTube")
        if not reproducir:
            return self._web("https://www.youtube.com/results?search_query=" + urllib.parse.quote(que),
                             f"Te busco «{que}» en YouTube")
        primero = youtube_primero(que)
        if not primero:
            return self._web("https://www.youtube.com/results?search_query=" + urllib.parse.quote(que),
                             f"No he podido sacar el primer vídeo; te dejo la búsqueda de «{que}» en YouTube")
        vid, titulo = primero
        url = f"https://www.youtube.com/watch?v={vid}"
        self.log(f"medios: youtube «{que}» → {vid} {titulo}")
        if en_vlc and not self.es_telegram() and vlc(url):
            return Respuesta(f"Poniendo en VLC: {titulo}.")
        return self._web(url, f"Poniendo {titulo}")

    # ---------------------------------------------------------------- TikTok
    def tiktok(self, que: str = "", perfil: str = "") -> Respuesta:
        if perfil:
            usuario = re.sub(r"[^\w.]", "", perfil.replace("arroba", "").replace(" ", "").lower())
            return self._web(f"https://www.tiktok.com/@{usuario}", f"Abriendo el TikTok de @{usuario}")
        que = re.sub(r"^(?:de |sobre |con )", "", que).strip()
        if not que:
            return self._web("https://www.tiktok.com/foryou", "Abriendo TikTok")
        return self._web("https://www.tiktok.com/search?q=" + urllib.parse.quote(que), f"Te busco «{que}» en TikTok")

    # ---------------------------------------------------------------- música local
    def musica(self, que: str, estilo: bool = False) -> Respuesta:
        """que = artista, canción o estilo. estilo=True ("música relajante") → en YouTube se busca "música <que>"."""
        if self.es_telegram():
            return Respuesta("La música suena en el portátil; dímelo cuando estés allí o pídeme el enlace de YouTube.")
        que = re.sub(r"^(?:de |del |la de |las de |algo de |un poco de )", "", que).strip()
        if not que:
            todas = canciones()
            if not todas:
                return self.youtube("musica variada", reproducir=True)
            if vlc("--random", "--loop", str(carpeta_musica())):
                return Respuesta(f"Poniendo tu música al azar ({len(todas)} canciones).")
            return Respuesta("No encuentro VLC para ponerla.")
        encontradas = buscar_musica(que)
        if encontradas:
            if len(encontradas) == 1:
                vlc(str(encontradas[0]))
                return Respuesta(f"Poniendo {encontradas[0].stem}.")
            random.shuffle(encontradas)
            vlc(*[str(p) for p in encontradas[:200]])
            return Respuesta(f"Poniendo {len(encontradas)} canciones de {que}.")
        return self.youtube(("música " + que) if estilo else que, reproducir=True)

    # ---------------------------------------------------------------- mandos
    def mandos(self, t: str) -> Respuesta | None:
        cosa = (r"(?: (?:la |el |los |las )?(?:musica|cancion|video|reproduccion|vlc|youtube|tiktok|reproductor|"
                r"peli\w*|serie|disco))?")
        m = re.fullmatch(r"(pausa|pausala|pausalo|pon(?:la|lo)? en pausa|para|parala|paralo|deten|detenla|quita|quitala)"
                         + cosa, t)
        if m and ("pausa" in t or t != m.group(1) or m.group(1) in ("parala", "paralo", "detenla")):
            quien = mando("Pause")
            if quien is None:
                return None
            return Respuesta("En pausa." if "pausa" in t else "Parado.")
        if re.fullmatch(r"(?:sigue|continua|reanuda|quita la pausa|dale al play|play|vuelve a ponerla|vuelve a ponerlo)" + cosa, t):
            quien = mando("Play")
            return None if quien is None else Respuesta("Sigo.")
        m = re.fullmatch(r"(?:(?:pasa|pon|salta)(?: a| al)? )?(?:la |el )?(siguiente|anterior|otra|otro)" + cosa +
                         r"(?: (?:cancion|video|tiktok))?", t)
        if m and not re.search(r"\b(evento|cita|correo|diapositiva|pagina|foto|imagen)\b", t):
            atras = m.group(1) == "anterior"
            wid = _ventana_tiktok()
            if wid and ("tiktok" in t or not reproductores()):
                if tecla_en_ventana(wid, "Up" if atras else "Down"):
                    return Respuesta("Anterior." if atras else "Siguiente.")
            quien = mando("Previous" if atras else "Next")
            if quien is None:
                return None
            return Respuesta("Anterior." if atras else "Siguiente.")
        return None

    # ---------------------------------------------------------------- entrada
    def manejar(self, peticion: str) -> Respuesta | None:
        t = _normalizar(peticion)
        if not t:
            return None
        r = self.mandos(t)
        if r:
            return r
        en_vlc = bool(re.search(r"\b(?:en|con) (?:el )?vlc\b", t))
        t2 = re.sub(r"\s*(?:en|con) (?:el )?vlc\b", "", t).strip()

        # ---- TikTok
        if "tiktok" in t2:
            m = re.search(r"\b(?:perfil|cuenta|tiktok) de (?:@|arroba )?([\w. ]+?)(?: en tiktok)?$", t2)
            if m and re.search(r"\b(perfil|cuenta|el tiktok de)\b", t2) and not re.search(r"\btiktoks de\b", t2):
                return self.tiktok(perfil=m.group(1))
            m = re.search(VERBO_BUSCAR + r"\s+(?:en tiktok\s+(.+)|(.+?)\s+en tiktok)$", t2)
            if m:
                return self.tiktok(m.group(1) or m.group(2))
            m = re.search(r"\btiktoks? (?:de|sobre|con) (.+)$", t2) or re.search(
                VERBO_PONER + r"\s+(?:videos? de )?(.+?) en tiktok$", t2)
            if m and re.match(r"(?:" + VERBO_PONER + "|" + VERBO_BUSCAR + r"|ver|quiero)\b", t2):
                return self.tiktok(m.group(1))
            if re.fullmatch(r"(?:" + VERBO_PONER + r"|ver|vamos a ver|entra en|entra a|ve a|ir a)\s+(?:el |un |unos )?tiktoks?"
                            r"(?: un rato)?", t2) or t2 == "tiktok":
                return self.tiktok()
            return None

        # ---- YouTube
        if "youtube" in t2 and re.search(r"\b(resum\w*|aprend\w*|que dice\w*|explica\w*|estudia\w*|investiga\w*|"
                                         r"informate)\b", t2):
            return None                                   # aprender de los vídeos: lo lleva saber.py
        if "youtube" in t2:
            m = re.search(VERBO_BUSCAR + r"\s+(?:en youtube\s+(.+)|(.+?)\s+en youtube)$", t2)
            if m:
                return self.youtube(m.group(1) or m.group(2), reproducir=False)
            m = re.search(VERBO_PONER + r"\s+(?:en youtube\s+(.+)|(.+?)\s+(?:en|de|por) youtube)$", t2)
            if m:
                return self.youtube(m.group(1) or m.group(2), reproducir=True, en_vlc=en_vlc)
            if re.fullmatch(r"(?:" + VERBO_PONER + r"|entra en|ve a)\s+(?:el )?youtube", t2):
                return self._web("https://www.youtube.com", "Abriendo YouTube")
            return None

        # ---- música
        m = re.fullmatch(r"(?:pon|ponme|ponnos|reproduce|quiero escuchar|quiero oir|toca)\s+(?:algo de |un poco de )?"
                         r"musica(?: (.+))?", t2)
        if m and not re.search(r"\b(arranque|thunderstruck|que has (?:creado|hecho|compuesto))\b", t2):
            resto = m.group(1) or ""
            return self.musica(resto, estilo=bool(resto) and not re.match(r"(?:de|del|la de|las de)\b", resto))
        m = re.fullmatch(r"(?:pon|ponme|reproduce|quiero escuchar)\s+(?:la cancion|el tema|canciones|temas)\s+(?:de |del )?(.+)", t2)
        if m and not re.search(r"\b(que has|que acabas|ultima|creado|hecho|compuesto|nueva)\b", t2):
            return self.musica(m.group(1))
        m = re.fullmatch(r"(?:pon|ponme|reproduce|quiero ver)\s+(?:el |un )?video (?:de |del |sobre )(.+)", t2)
        if m and not re.search(r"\b(que has|que acabas|ultimo|creado|hecho|montado)\b", t2):
            return self.youtube(m.group(1), reproducir=True, en_vlc=en_vlc)
        return None
