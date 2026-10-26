"""
Herramientas de Jarvis: abrir aplicaciones y carpetas, buscar y resumir archivos,
buscar en internet y dar el tiempo real.

Diseño: las órdenes se reconocen con reglas (no las decide la IA), porque un modelo
de 1,5B no es fiable eligiendo acciones sobre el ordenador. La IA solo resume textos.
Nada de lo que hay aquí borra, mueve ni modifica archivos.
"""

from __future__ import annotations

import configparser
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from perfil import CONFIG as PERFIL_CONFIG, DATOS

HOME = Path.home()
CONFIG = PERFIL_CONFIG


# =============================================================== utilidades

def normalizar(t: str) -> str:
    """minúsculas y sin tildes, para comparar lo que dice whisper con nombres reales."""
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip(" .,;:¿?¡!\"'")


def leer_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_config(**cambios) -> None:
    c = leer_config()
    c.update(cambios)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


LOG_ABRIR = DATOS / "logs" / "abrir.log"


def _anotar(texto: str) -> None:
    try:
        LOG_ABRIR.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_ABRIR, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {texto}\n")
    except OSError:
        pass


def pantalla_portatil() -> tuple[int, int, int, int] | None:
    """(ancho, alto, x, y) de la pantalla de trabajo, si la interfaz tiene otra para ella sola (pantallas.py).
    Con una sola pantalla devuelve None y las ventanas se quedan donde las ponga el escritorio."""
    from pantallas import trabajo_geo
    return trabajo_geo()


def _id_jarvis() -> int | None:
    try:
        return int((HOME / ".cache/jarvis_ventana").read_text().strip(), 16)
    except (OSError, ValueError):
        return None


def ventanas_geo() -> list[tuple[str, int, int, int, int, int, str]]:
    """(id, escritorio, x, y, ancho, alto, título) de todas las ventanas."""
    try:
        r = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return []
    lista = []
    for linea in r.stdout.splitlines():
        p = linea.split(None, 7)
        if len(p) >= 6:
            try:
                lista.append((p[0], int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), p[7] if len(p) > 7 else ""))
            except ValueError:
                pass
    return lista


def _colocar_en_portatil(antes: set[int], segundos: float = 25) -> None:
    """Vigila las ventanas nuevas un rato y las lleva al portátil, maximizadas.
    Se repite unas veces porque Firefox y otros se recolocan solos al terminar de abrir."""
    g = pantalla_portatil()
    if not g:
        return
    ancho, alto, px, py = g
    jarvis = _id_jarvis()
    movidas: dict[int, int] = {}
    fin = time.time() + segundos
    while time.time() < fin:
        time.sleep(0.5)
        for wid, esc, x, y, w, h, titulo in ventanas_geo():
            n = int(wid, 16)
            if n in antes or esc == -1 or n == jarvis or "Jarvis — " in titulo or "Jarvis - " in titulo:
                continue
            cx, cy = x + w // 2, y + h // 2
            if px <= cx < px + ancho and py <= cy < py + alto:
                continue                                    # ya está en el portátil
            if movidas.get(n, 0) >= 4:
                continue
            movidas[n] = movidas.get(n, 0) + 1
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "remove,fullscreen"], timeout=3)
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "remove,maximized_vert,maximized_horz"], timeout=3)
            time.sleep(0.3)
            subprocess.run(["wmctrl", "-i", "-r", wid, "-e",
                            f"0,{px + 30},{py + 30},{min(w, ancho - 60)},{min(h, alto - 80)}"], timeout=3)
            time.sleep(0.2)
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,maximized_vert,maximized_horz"], timeout=3)
            subprocess.run(["wmctrl", "-i", "-a", wid], timeout=3)
            _anotar(f"  movida al portátil: {wid} '{titulo}' (estaba en {x},{y})")


def lanzar(cmd: list[str]) -> None:
    """Abre algo en segundo plano, desligado de Jarvis (si Jarvis se reinicia, la app sigue),
    y se asegura de que la ventana nueva aparezca en la pantalla del portátil."""
    con_wm = shutil.which("wmctrl") is not None
    antes = {int(v[0], 16) for v in ventanas_geo()} if con_wm else set()
    _anotar("abrir: " + " ".join(cmd))
    try:
        LOG_ABRIR.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_ABRIR, "a", encoding="utf-8") as salida:
            subprocess.Popen(cmd, stdout=salida, stderr=salida, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        _anotar(f"  error: {e!r}")
        raise
    if con_wm:
        threading.Thread(target=_colocar_en_portatil, args=(antes,), daemon=True).start()


def abrir_web(url: str) -> None:
    """Las páginas van al Firefox normal (nunca a la pantalla de Jarvis), en una pestaña nueva si ya está abierto:
    una ventana por búsqueda llenaba la memoria del portátil."""
    if shutil.which("firefox"):
        lanzar(["firefox", "--new-tab", url])
    else:
        lanzar(["xdg-open", url])


MEDIOS = {".mp3", ".ogg", ".flac", ".wav", ".m4a", ".opus", ".aac", ".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v",
          ".mpg", ".mpeg", ".wmv"}


def abrir_archivo(ruta) -> None:
    """Abre un archivo con su programa; la música y los vídeos, con VLC si está instalado."""
    ruta = str(ruta)
    if Path(ruta).suffix.lower() in MEDIOS and shutil.which("vlc"):
        lanzar(["vlc", "--one-instance", "--no-playlist-enqueue", ruta])
    else:
        lanzar(["xdg-open", ruta])


def http_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-local/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


NUMEROS = {"primero": 1, "primera": 1, "uno": 1, "1": 1, "segundo": 2, "segunda": 2, "dos": 2, "2": 2,
           "tercero": 3, "tercera": 3, "tres": 3, "3": 3, "cuarto": 4, "cuarta": 4, "cuatro": 4, "4": 4,
           "quinto": 5, "quinta": 5, "cinco": 5, "5": 5, "ultimo": -1, "ultima": -1}


@dataclass
class Resultado:
    texto: str                                   # lo que Jarvis dice
    lista: list[str] = field(default_factory=list)   # lo que se muestra numerado en pantalla
    titulo: str = ""


# =============================================================== aplicaciones

ALIAS_APPS = {
    "navegador": ["firefox", "chromium", "google chrome"], "internet": ["firefox", "chromium"],
    "explorador": ["thunar", "archivos", "files"], "archivos": ["thunar", "archivos", "files"],
    "gestor de archivos": ["thunar"], "terminal": ["terminal", "xfce4-terminal", "ptyxis"], "consola": ["terminal", "ptyxis"],
    "editor": ["mousepad", "geany", "gedit"], "bloc de notas": ["mousepad", "gedit"],
    "editor de texto": ["mousepad", "gedit"], "codigo": ["visual studio code", "code", "geany"],
    "visual studio": ["visual studio code", "code"], "vs code": ["visual studio code"],
    "calculadora": ["calculadora", "calculator", "galculator", "gnome-calculator"],
    "ajustes": ["configuracion", "settings manager", "xfce4-settings-manager"],
    "configuracion": ["configuracion", "settings manager"], "musica": ["rhythmbox", "spotify", "vlc"],
    "videos": ["vlc", "totem", "celluloid"],
}


class Aplicaciones:
    CARPETAS = [Path("/usr/share/applications"), Path("/usr/local/share/applications"),
                HOME / ".local/share/applications", Path("/var/lib/snapd/desktop/applications"),
                Path("/var/lib/flatpak/exports/share/applications"),
                HOME / ".local/share/flatpak/exports/share/applications"]

    def __init__(self, carpetas: list[Path] | None = None):
        self.carpetas = carpetas or self.CARPETAS
        self.apps: list[dict] = []
        self.recargar()

    def recargar(self) -> None:
        """Lee los .desktop: así cualquier programa que instales aparece solo, sin tocar Jarvis."""
        vistas, apps = set(), []
        for carpeta in self.carpetas:
            for f in sorted(carpeta.glob("*.desktop")) if carpeta.is_dir() else []:
                if f.name in vistas:
                    continue
                cp = configparser.RawConfigParser(strict=False, interpolation=None)
                cp.optionxform = str
                try:
                    cp.read(f, encoding="utf-8")
                    e = cp["Desktop Entry"]
                except (KeyError, configparser.Error, UnicodeDecodeError):
                    continue
                if e.get("Type", "Application") != "Application" or e.get("NoDisplay") == "true" \
                        or e.get("Hidden") == "true" or not e.get("Exec"):
                    continue
                vistas.add(f.name)
                nombres = {e.get("Name", ""), e.get("Name[es]", ""), e.get("GenericName", ""),
                           e.get("GenericName[es]", ""), f.stem.split(".")[-1], f.stem,
                           f.stem.split(".")[-1].split("_")[-1]}
                # cada palabra suelta del nombre también vale ("firefox", "thunar"…)
                nombres |= {w for n in list(nombres) for w in re.split(r"[\s_\-.]+", n) if len(w) >= 4}
                claves = (e.get("Keywords[es]", "") + ";" + e.get("Keywords", "")).split(";")
                apps.append({"id": f.stem, "ruta": str(f), "nombre": e.get("Name[es]") or e.get("Name", f.stem),
                             "exec": e["Exec"], "terminal": e.get("Terminal") == "true",
                             "busqueda": {normalizar(n) for n in nombres | set(claves) if n.strip()}})
        self.apps = apps

    def buscar(self, consulta: str) -> dict | None:
        q = normalizar(re.sub(r"^(el|la|los|las|programa|aplicacion|app)\s+", "", normalizar(consulta)))
        q = re.sub(r"^(programa|aplicacion|app|de)\s+", "", q)
        if q not in ALIAS_APPS:                                 # "terminada" -> "terminal"
            parecido = difflib.get_close_matches(q, list(ALIAS_APPS), n=1, cutoff=0.8)
            q = parecido[0] if parecido else q
        candidatos = [q] + ALIAS_APPS.get(q, [])
        for c in candidatos:                                    # 1) nombre exacto
            for a in self.apps:
                if c in a["busqueda"]:
                    return a
        for c in candidatos:                                    # 2) contiene la palabra
            for a in self.apps:
                # «s in c» solo con nombres largos: si no, «calculadora» contiene «calc» y abría LibreOffice Calc
                if any(len(c) >= 4 and (c in s or (len(s) >= 6 and s in c)) for s in a["busqueda"] if len(s) >= 4):
                    return a
        todos = {s: a for a in self.apps for s in a["busqueda"]}   # 3) parecido (whisper se equivoca)
        cerca = difflib.get_close_matches(q, list(todos), n=1, cutoff=0.7)
        return todos[cerca[0]] if cerca else None

    @staticmethod
    def abrir(app: dict) -> None:
        if shutil.which("gtk-launch"):
            lanzar(["gtk-launch", Path(app["ruta"]).name])
            return
        exe = re.sub(r"\s%[a-zA-Z]", "", app["exec"]).replace('"', "")
        cmd = exe.split()
        if app["terminal"]:
            cmd = ["xfce4-terminal", "-x"] + cmd
        lanzar(cmd)


# =============================================================== archivos y carpetas

def carpeta_usuario(clave: str) -> Path:
    try:
        r = subprocess.run(["xdg-user-dir", clave], capture_output=True, text=True, timeout=3)
        if r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return HOME


CARPETAS_CONOCIDAS = {
    "descargas": "DOWNLOAD", "documentos": "DOCUMENTS", "imagenes": "PICTURES", "fotos": "PICTURES",
    "musica": "MUSIC", "videos": "VIDEOS", "escritorio": "DESKTOP", "plantillas": "TEMPLATES",
}


def buscar_archivos(texto: str, solo_carpetas: bool = False, maximo: int = 8) -> list[Path]:
    """Busca por nombre en todo el disco (plocate) y, si no hay índice, dentro de tu carpeta personal."""
    palabras = [p for p in re.split(r"[\s_\-.]+", normalizar(texto)) if len(p) >= 2]
    if not palabras:
        return []
    rutas: list[str] = []
    if shutil.which("locate") or shutil.which("plocate"):
        loc = shutil.which("plocate") or shutil.which("locate")
        try:
            r = subprocess.run([loc, "-i", "-b", "-l", "400", palabras[0]], capture_output=True,
                               text=True, timeout=6)
            rutas = r.stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not rutas:
        try:
            r = subprocess.run(["find", str(HOME), "-maxdepth", "7", "-not", "-path", "*/.*",
                                "-iname", f"*{palabras[0]}*"], capture_output=True, text=True, timeout=8)
            rutas = r.stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            pass
    ignorar = ("/proc/", "/sys/", "/snap/", "/usr/", "/var/", "/.cache/", "/venv/", "/site-packages/",
               "/node_modules/", "/.local/share/Trash/", "/.git/")
    puntuadas = []
    for r in rutas:
        if any(i in r for i in ignorar):
            continue
        p = Path(r)
        nombre = normalizar(p.name)
        if not all(w in nombre or difflib.get_close_matches(w, re.split(r"[\s_\-.]+", nombre), cutoff=0.8)
                   for w in palabras):
            continue
        try:
            if solo_carpetas != p.is_dir():
                continue
        except OSError:
            continue
        en_casa = str(p).startswith(str(HOME))
        puntuadas.append((difflib.SequenceMatcher(None, " ".join(palabras), nombre).ratio() + en_casa * 0.3, p))
    puntuadas.sort(key=lambda x: -x[0])
    return [p for _, p in puntuadas[:maximo]]


EXT_ANYDOC = {".doc", ".docx", ".docm", ".ppt", ".pps", ".pptx", ".pptm", ".ppsx", ".xls", ".xlsx", ".xlsm", ".xlsb",
              ".odt", ".ods", ".odp", ".rtf", ".epub", ".pdf"}


def leer_texto(ruta: Path, limite: int = 6000) -> str:
    suf = ruta.suffix.lower()
    if suf in EXT_ANYDOC:                              # anydoc (Firecrawl, MIT): Word, PowerPoint, Excel, PDF… a Markdown
        try:                                           # limpio, con tablas y títulos. Si no está o falla, lo de siempre.
            import anydoc
            texto = anydoc.to_markdown(str(ruta))
            if texto and texto.strip():
                return texto[:limite]
        except Exception:
            pass
    try:
        if suf == ".pdf" and shutil.which("pdftotext"):
            r = subprocess.run(["pdftotext", "-l", "8", str(ruta), "-"], capture_output=True, text=True, timeout=20)
            return r.stdout[:limite]
        if suf in (".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".pptx", ".dxf", ".dwg"):
            import oficina                            # hojas de cálculo, presentaciones y planos
            if suf == ".pptx":
                return oficina.leer_pptx(ruta)[:limite]
            if suf in (".dxf", ".dwg"):
                dxf = ruta if suf == ".dxf" else oficina.dwg_a_dxf(ruta)
                return oficina.resumen_dxf(dxf)[0][:limite] if dxf else ""
            return oficina.tabla_como_texto(oficina.leer_tabla(ruta), limite)
        if suf in (".docx", ".odt"):
            with zipfile.ZipFile(ruta) as z:
                xml = z.read("word/document.xml" if suf == ".docx" else "content.xml").decode("utf-8", "ignore")
            return re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>|</text:p>", "\n", xml))[:limite]
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            return f.read(limite)
    except (OSError, zipfile.BadZipFile, subprocess.TimeoutExpired, KeyError):
        return ""
    except Exception:                                 # un archivo raro nunca debe tumbar la orden
        return ""


def corto(p: Path) -> str:
    s = str(p)
    return "~" + s[len(str(HOME)):] if s.startswith(str(HOME)) else s


# =============================================================== internet

SEARXNG = "http://127.0.0.1:8888"


def _buscar_searxng(consulta: str, maximo: int) -> list[dict]:
    """SearXNG en este equipo (si está instalado): pregunta a varios buscadores a la vez, sin cuentas ni rastreo."""
    url = f"{SEARXNG}/search?" + urllib.parse.urlencode({"q": consulta, "format": "json", "language": "es-ES",
                                                          "safesearch": 0})
    req = urllib.request.Request(url, headers={"X-Real-IP": "127.0.0.1", "User-Agent": "Athena"})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.loads(r.read())
    vistos, res = set(), []
    for x in d.get("results") or []:
        u = x.get("url") or ""
        if not u or u in vistos:
            continue
        vistos.add(u)
        res.append({"titulo": x.get("title", ""), "url": u, "texto": x.get("content", "")})
        if len(res) >= maximo:
            break
    return res


def buscar_web(consulta: str, maximo: int = 4) -> list[dict]:
    if (Path.home() / ".config/systemd/user/searxng.service").exists():
        try:
            res = _buscar_searxng(consulta, maximo)
            if res:
                return res
        except Exception:
            pass                                    # apagado o sin respuesta: DuckDuckGo como siempre
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise RuntimeError("falta el paquete ddgs (pip install ddgs)")
    res = DDGS().text(consulta, region="es-es", max_results=maximo)
    return [{"titulo": r.get("title", ""), "url": r.get("href", ""), "texto": r.get("body", "")} for r in res or []]


CODIGOS_TIEMPO = {
    0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado", 45: "con niebla",
    48: "con niebla", 51: "con llovizna débil", 53: "con llovizna", 55: "con llovizna intensa",
    61: "con lluvia débil", 63: "con lluvia", 65: "con lluvia fuerte", 66: "con lluvia helada",
    67: "con lluvia helada", 71: "con nevada débil", 73: "con nieve", 75: "con nevada fuerte",
    77: "con granizo fino", 80: "con chubascos débiles", 81: "con chubascos", 82: "con chubascos fuertes",
    85: "con chubascos de nieve", 86: "con chubascos de nieve", 95: "con tormenta",
    96: "con tormenta y granizo", 99: "con tormenta y granizo",
}


def tiempo(ciudad: str, manana: bool = False) -> str:
    geo = http_json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": ciudad, "count": 1, "language": "es", "format": "json"}))
    if not geo.get("results"):
        return f"No encuentro la ciudad {ciudad}."
    g = geo["results"][0]
    d = http_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "forecast_days": 2,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"}))
    dia = d["daily"]
    i = 1 if manana else 0
    lluvia = dia["precipitation_probability_max"][i]
    prevision = (f"máxima de {round(dia['temperature_2m_max'][i])} y mínima de "
                 f"{round(dia['temperature_2m_min'][i])} grados")
    prob = f", con un {lluvia} por ciento de probabilidad de lluvia" if lluvia is not None and lluvia >= 20 else ""
    if manana:
        cielo = CODIGOS_TIEMPO.get(dia["weather_code"][1], "variable")
        return f"Mañana en {g['name']} estará {cielo}, {prevision}{prob}."
    c = d["current"]
    cielo = CODIGOS_TIEMPO.get(c["weather_code"], "variable")
    return f"Ahora en {g['name']} hace {round(c['temperature_2m'])} grados y está {cielo}. Hoy, {prevision}{prob}."


# =============================================================== órdenes

RE_ABRIR_N = re.compile(r"^(abre|abrir|abreme|abrelo|abrela|muestrame|ensename|pon)\s*(lo|la|el|me)?\s*"
                        r"(el |la |numero |resultado )?(primero|primera|segundo|segunda|tercero|tercera|cuarto|"
                        r"cuarta|quinto|quinta|ultimo|ultima|uno|dos|tres|cuatro|cinco|\d)?\s*$")
RE_CARPETA = re.compile(r"^(abre|abrir|abreme|abro|abra|muestrame|ensename|ve a|vete a)\s+(la |mi |mis )?carpet\w*"
                        r"( de| del)?\s+(.+)$")
RE_BUSCAR_ARCHIVO = re.compile(r"^(busca|buscame|buscar|encuentra|encuentrame|localiza|donde esta|donde estan)"
                               r"\s+(el |la |los |las |un |una |mis |mi )?(archivo|archivos|fichero|ficheros|"
                               r"documento|documentos|carpeta|carpetas)\s+(que se llama |llamado |llamada |de |con )?"
                               r"(.+)$")
RE_RESUMIR = re.compile(r"^(resume|resumeme|leeme|lee|de que va|que dice)\s+(el |la |mi )?(archivo|documento|"
                        r"fichero|pdf|word|texto)\s+(que se llama |llamado |llamada |de )?(.+)$")
RE_WEB = re.compile(r"^(busca|buscame|buscar|investiga|mira|consulta)\s+(en )?(internet|google|la web|online|"
                    r"en internet)\s*(sobre|acerca de|que|informacion de|informacion sobre)?\s*(.+)$"
                    r"|^(busca|buscame) informacion (sobre|de|acerca de)\s+(.+)$")
RE_ABRIR_APP = re.compile(r"^(abre|abrir|abreme|abro|abra|lanza|ejecuta|inicia|arranca)\s+(el |la |los |las )?"
                          r"(programa |aplicacion |app )?(.+)$")
RE_CERRAR = re.compile(r"^(cierra\w*|cierre\w*|cerrar\w*|cierro|quita\w*)\s+(.+)$")
RE_TIEMPO = re.compile(r"\bque tiempo (hace|va a hacer|hara|tendremos|hay)|\bclima\b|\bllov(er|era|iendo|io)\b"
                       r"|\btemperatura|\bhace (frio|calor)\b|\bel tiempo\b")
RE_CIUDAD = re.compile(r"^(mi ciudad es|vivo en|estoy en)\s+(.+)$")
RE_TIEMPO_EN = re.compile(r"\ben\s+([a-zñ ]{3,30})$")


PALABRAS_WEB = ["internet", "google", "online", "web"]
CONECTORES = {"sobre", "acerca", "de", "del", "en", "por", "a"}


def detectar_web(t: str) -> str | None:
    """'busca en internet X', 'buscan de interne X', 'oye, búscame en google X' → X."""
    t = re.sub(r"[,;:]", " ", t)
    m = re.search(r"(?:^|\s)(busca\w*|busqu\w*|buscar|busco|investiga\w*|mira|consulta\w*|averigua\w*|que dice)\s+(.+)$", t)
    if not m or len(t[:m.start()].split()) > 3:
        return None
    palabras = m.group(2).split()
    for i, w in enumerate(palabras[:4]):
        if w.startswith("informacion") or (len(w) >= 3 and difflib.get_close_matches(w, PALABRAS_WEB, n=1, cutoff=0.75)):
            resto = palabras[i + 1:]
            while resto and resto[0] in CONECTORES:
                resto = resto[1:]
            consulta = " ".join(resto)
            # "...y muéstramelo en pantalla", "...y ábremelo": eso ya lo hace siempre
            consulta = re.sub(r"\s+y\s+(muestra|ensena|abre|pon|ense)\w*\b.*$", "", consulta)
            return consulta.strip()
    return None


# Si no hay un programa instalado con ese nombre, se abre la web equivalente.
WEBS = {
    "calendario": "https://calendar.google.com", "agenda": "https://calendar.google.com",
    "correo": "https://mail.google.com", "gmail": "https://mail.google.com", "email": "https://mail.google.com",
    "youtube": "https://www.youtube.com", "mapas": "https://maps.google.com", "maps": "https://maps.google.com",
    "traductor": "https://translate.google.es", "whatsapp": "https://web.whatsapp.com",
    "netflix": "https://www.netflix.com", "spotify": "https://open.spotify.com", "drive": "https://drive.google.com",
    "fotos de google": "https://photos.google.com", "amazon": "https://www.amazon.es",
    "google": "https://www.google.es", "wikipedia": "https://es.wikipedia.org", "el tiempo": "https://www.aemet.es",
    "noticias": "https://news.google.com/?hl=es&gl=ES&ceid=ES:es", "chat gpt": "https://chatgpt.com",
    "chatgpt": "https://chatgpt.com", "twitter": "https://x.com", "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "outlook": "https://outlook.live.com",
}


def web_conocida(nombre: str) -> tuple[str, str] | None:
    nombre = re.sub(r"^(el|la|los|las|mi|un|una)\s+", "", nombre.strip())
    nombre = re.sub(r"\s+(de|en) (internet|google|la web)$", "", nombre)
    if nombre in WEBS:
        return nombre, WEBS[nombre]
    cerca = difflib.get_close_matches(nombre, list(WEBS), n=1, cutoff=0.8)
    return (cerca[0], WEBS[cerca[0]]) if cerca else None


def nombre_carpeta_conocida(nombre: str) -> str | None:
    """'descargas', 'de cargas', 'escargas' → 'descargas'."""
    candidatos = [nombre, nombre.replace(" ", ""), "de" + nombre.replace(" ", ""), "des" + nombre.replace(" ", "")]
    for c in candidatos:
        cerca = difflib.get_close_matches(c, list(CARPETAS_CONOCIDAS), n=1, cutoff=0.8)
        if cerca:
            return cerca[0]
    return None


# =============================================================== ventanas

DESTINOS_CERRAR = {
    # Ubuntu 26.04 trae Ptyxis: su ventana no lleva la palabra «terminal»
    "terminal": ["terminal", "ptyxis", "kgx", "konsole", "xterm"], "consola": ["terminal", "ptyxis", "kgx", "konsole"],
    "carpeta": ["thunar"], "carpetas": ["thunar"], "explorador": ["thunar"], "archivos": ["thunar"],
    "navegador": ["firefox", "chromium", "chrome"], "firefox": ["firefox"], "internet": ["firefox", "chromium"],
    "pagina": ["firefox", "chromium"], "paginas": ["firefox", "chromium"], "busqueda": ["firefox", "chromium"],
    "editor": ["mousepad", "geany", "code", "gedit"], "codigo": ["code", "geany"],
    "archivo": ["mousepad", "geany", "evince", "atril", "papers", "libreoffice", "ristretto", "eog", "code"],
    "documento": ["mousepad", "evince", "atril", "papers", "libreoffice"], "pdf": ["evince", "atril", "papers"],
    "foto": ["ristretto", "eog"], "imagen": ["ristretto", "eog"],
}
ARTICULOS = {"el", "la", "los", "las", "lo", "le", "un", "una", "mi", "mis", "esa", "ese", "eso", "esta", "este", "esto",
             "ventana", "ventanas", "de", "del"}


def ventanas() -> list[dict]:
    """Ventanas normales abiertas, sin la de Jarvis."""
    try:
        r = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return []
    try:
        jarvis = int((HOME / ".cache/jarvis_ventana").read_text().strip(), 16)
    except (OSError, ValueError):
        jarvis = None
    lista = []
    for linea in r.stdout.splitlines():
        partes = linea.split(None, 4)
        if len(partes) < 4 or partes[1] == "-1":
            continue
        titulo = partes[4] if len(partes) > 4 else ""
        if int(partes[0], 16) == jarvis or "Jarvis — " in titulo or "Jarvis - " in titulo:
            continue
        lista.append({"id": partes[0], "clase": partes[2].lower(), "titulo": titulo})
    return lista


def cerrar_ventanas(objetivo: str) -> tuple[int, str]:
    """Cierra (como pulsar la X) las ventanas que encajan. Si hay algo sin guardar, la propia app lo pregunta."""
    abiertas = ventanas()
    palabras = [w for w in objetivo.split() if w not in ARTICULOS]
    clave = " ".join(palabras)
    if clave in ("todo", "todas", "todos") or objetivo.strip() in ("todo", "todas las ventanas"):
        elegidas = abiertas
    elif not palabras:                                          # "ciérralo", "cierra esa ventana"
        try:
            r = subprocess.run(["wmctrl", "-c", ":ACTIVE:"], timeout=3)
            return (1 if r.returncode == 0 else 0), "la ventana activa"
        except (OSError, subprocess.TimeoutExpired):
            return 0, "la ventana activa"
    else:
        grupos = []                                             # cada palabra, con sus equivalentes
        for w in palabras:
            cerca = difflib.get_close_matches(w, list(DESTINOS_CERRAR), n=1, cutoff=0.8)
            grupos.append(DESTINOS_CERRAR[cerca[0]] if cerca else [w])

        def encaja(v: dict, claves: list[str]) -> bool:
            return any(k in v["clase"] or k in normalizar(v["titulo"]) for k in claves)
        # tienen que encajar TODAS las palabras: «cierra LibreOffice Calc» no cierra también el Impress
        elegidas = [v for v in abiertas if all(encaja(v, g) for g in grupos)]
        if not elegidas and len(grupos) > 1:                    # si con todas no hay ninguna, la más concreta
            elegidas = [v for v in abiertas if encaja(v, grupos[-1])]
    for v in elegidas:
        subprocess.run(["wmctrl", "-i", "-c", v["id"]], timeout=3)
    return len(elegidas), clave or "todo"


class Herramientas:
    def __init__(self, resumir_fn, confirmar_fn=None):
        """resumir_fn(instruccion, texto) -> str : usa la IA solo para resumir."""
        self.resumir = resumir_fn
        self.confirmar = confirmar_fn
        self.apps = Aplicaciones()
        self.ultimos: list[str] = []          # rutas o URLs de la última lista mostrada

    def _lista(self, elementos: list[str], titulo: str, texto: str) -> Resultado:
        self.ultimos = elementos
        visibles = [corto(Path(e)) if not e.startswith("http") else e for e in elementos]
        return Resultado(texto, visibles, titulo)

    def manejar(self, peticion: str) -> Resultado | None:
        t = normalizar(peticion)

        m = RE_CIUDAD.match(t)
        if m:
            ciudad = peticion.strip(" .¿?¡!")[len(m.group(1)):].strip(" .,") or m.group(2)
            ciudad = re.split(r"[.,;:¿?¡!]", ciudad)[0].strip() or m.group(2)
            guardar_config(ciudad=ciudad)
            return Resultado(f"Apuntado: tu ciudad es {ciudad}.")

        consulta = detectar_web(t)
        if consulta is not None:
            consulta = consulta.strip()
            if not consulta:
                return Resultado("¿Qué quieres que busque en internet?")
            try:
                res = buscar_web(consulta, 6)
            except Exception as e:                       # sin red, paquete ausente, bloqueo del buscador…
                return Resultado(f"No he podido buscar en internet. ({type(e).__name__})")
            if not res:
                return Resultado("No he encontrado nada en internet sobre eso.")
            contexto = "\n\n".join(f"[{i + 1}] {r['titulo']}\n{r['texto']}" for i, r in enumerate(res))
            respuesta = self.resumir(
                f"Responde en dos o tres frases, en español de España, a: {consulta}. Usa solo estos resultados de "
                "búsqueda. Si hablan de otra cosa con un nombre parecido (otra empresa, otra persona, otro "
                "producto), dilo claramente en una frase y no la describas como si fuera lo que busca. Si no "
                "contienen la respuesta, dilo. Euros, no dólares, salvo que los resultados digan otra cosa.", contexto)
            # Además del resumen hablado, abre la página de resultados en el navegador del portátil.
            abrir_web("https://www.google.com/search?hl=es&q=" + urllib.parse.quote_plus(consulta))
            r = self._lista([x["url"] for x in res], f"Internet: {consulta}",
                            respuesta + " Te he abierto los resultados en el portátil.")
            r.lista = [f"{x['titulo']} — {urllib.parse.urlparse(x['url']).netloc}" for x in res]
            return r

        if RE_TIEMPO.search(t):
            ciudad_en = RE_TIEMPO_EN.search(t)
            ciudad = ciudad_en.group(1).strip() if ciudad_en and ciudad_en.group(1) not in ("casa",) \
                else leer_config().get("ciudad")
            if not ciudad:
                return Resultado("Para darte el tiempo necesito tu ciudad. Dime: Jarvis, mi ciudad es, y el nombre.")
            try:
                return Resultado(tiempo(ciudad, manana="manana" in t))
            except (OSError, ValueError, KeyError) as e:
                return Resultado(f"No he podido consultar el tiempo. Puede que no haya internet. ({type(e).__name__})")

        m = RE_ABRIR_N.match(t)
        if m and self.ultimos and (m.group(4) or m.group(2) in ("lo", "la") or m.group(1) in ("abrelo", "abrela")):
            n = NUMEROS.get(m.group(4) or "primero", 1)
            idx = len(self.ultimos) - 1 if n == -1 else n - 1
            if 0 <= idx < len(self.ultimos):
                destino = self.ultimos[idx]
                abrir_web(destino) if destino.startswith("http") else lanzar(["xdg-open", destino])
                return Resultado("Abriendo.")
            return Resultado(f"Solo hay {len(self.ultimos)} resultados.")

        m = RE_CARPETA.match(t)
        if m:
            nombre = m.group(4).strip()
            if nombre in ("personal", "inicio", "usuario", "casa"):
                destino = HOME
            elif nombre_carpeta_conocida(nombre):
                destino = carpeta_usuario(CARPETAS_CONOCIDAS[nombre_carpeta_conocida(nombre)])
            else:
                encontradas = buscar_archivos(nombre, solo_carpetas=True)
                if not encontradas:
                    return Resultado(f"No encuentro ninguna carpeta que se llame {nombre}.")
                if len(encontradas) > 1:
                    return self._lista([str(p) for p in encontradas], f"Carpetas: {nombre}",
                                       f"Hay {len(encontradas)} carpetas parecidas. Te las enseño; dime cuál abro.")
                destino = encontradas[0]
            lanzar(["xdg-open", str(destino)])
            return Resultado(f"Abriendo {corto(destino)}.")

        m = RE_RESUMIR.match(t)
        if m:
            encontrados = [p for p in buscar_archivos(m.group(5)) if p.is_file()]
            if not encontrados:                                  # lo recién creado aún no está en el índice
                from archivos import buscar_en_casa
                encontrados = [p for p in buscar_en_casa(m.group(5), carpetas=False) if p.is_file()]
            if not encontrados:
                return Resultado(f"No encuentro ningún archivo llamado {m.group(5)}.")
            ruta = encontrados[0]
            contenido = leer_texto(ruta)
            if not contenido.strip():
                return Resultado(f"Encontré {ruta.name}, pero no puedo leer su contenido.")
            resumen = self.resumir("Resume en tres frases, en español, de qué trata este documento.", contenido)
            self.ultimos = [str(ruta)]
            return Resultado(f"{ruta.name}: {resumen}", [corto(ruta)], "Documento")

        m = RE_BUSCAR_ARCHIVO.match(t)
        if m:
            carpetas = m.group(3).startswith("carpeta")
            encontrados = buscar_archivos(m.group(5), solo_carpetas=carpetas)
            if not encontrados:
                return Resultado(f"No encuentro nada que se llame {m.group(5)}.")
            n = len(encontrados)
            texto = (f"He encontrado {n} {'resultados' if n > 1 else 'resultado'}. "
                     f"{'El primero es' if n > 1 else 'Es'} {encontrados[0].name}. Dime abre el primero, o el número que quieras.")
            return self._lista([str(p) for p in encontrados], f"Búsqueda: {m.group(5)}", texto)

        if re.fullmatch(r"(cierr\w*|cerrar\w*)( (eso|esto|esa ventana|la ventana|esta ventana))?", t):
            n, _ = cerrar_ventanas("")                   # "ciérralo": la ventana activa
            return Resultado("Hecho." if n else "No veo ninguna ventana que cerrar.")

        m = RE_CERRAR.match(t)
        if m:
            total, nombres = 0, []
            for parte in re.split(r"\s+y\s+(?:cierr\w*\s+)?", m.group(2)):   # "cierra el archivo y la carpeta"
                n, que = cerrar_ventanas(parte)
                total += n
                nombres.append(que)
            if total == 0:
                return Resultado(f"No veo ninguna ventana de {' ni '.join(nombres)} abierta.")
            if total == 1:                                # que diga qué ha cerrado («Hecho» a secas no lo confirma)
                return Resultado(f"He cerrado {re.sub(r'^(el|la|los|las) (ventana|programa) (de )?', '', m.group(2))}.")
            return Resultado(f"He cerrado {total} ventanas.")

        m = RE_ABRIR_APP.match(t)
        if m:
            objetivo = m.group(4).strip()
            app = self.apps.buscar(objetivo)
            if not app:
                self.apps.recargar()                     # por si la has instalado hace un momento
                app = self.apps.buscar(objetivo)
            if not app:
                web = web_conocida(objetivo)
                if web:
                    abrir_web(web[1])
                    return Resultado(f"Abriendo {web[0]} en el navegador.")
                return Resultado(f"No encuentro ninguna aplicación que se llame {objetivo}.")
            self.apps.abrir(app)
            return Resultado(f"Abriendo {app['nombre']}.")

        return None
