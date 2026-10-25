"""
Fuentes de conocimiento para el asistente, además de la web: GitHub y YouTube.

  GitHub:  github_buscar("asistente de voz en español")  → repositorios (nombre, estrellas, descripción…)
           github_repo("open-webui/open-webui")           → datos del repositorio + su README
  YouTube: youtube_buscar("cómo injertar un olivo")        → vídeos (id, título, canal, duración)
           youtube_transcripcion("dQw4w9WgXcQ")            → lo que se dice en el vídeo (subtítulos)

Sin claves: la API de GitHub va sin cuenta (60 consultas/hora; con el token de GitHub del asistente, 5.000).
YouTube: la página de resultados trae los vídeos y los subtítulos salen de youtube-transcript-api.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from perfil import SECRETOS

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
API = "https://api.github.com"
RE_YT = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/))([\w-]{11})")


# ================================================================ GitHub
def _token() -> str:
    try:
        return json.loads((SECRETOS / "github.json").read_text(encoding="utf-8")).get("token", "")
    except (OSError, ValueError):
        return ""


def _gh(ruta: str, params: dict | None = None, crudo: bool = False, timeout: int = 15):
    url = API + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
    cab = {"User-Agent": "asistente-jarvis", "X-GitHub-Api-Version": "2022-11-28",
           "Accept": "application/vnd.github.raw+json" if crudo else "application/vnd.github+json"}
    tk = _token()
    if tk:
        cab["Authorization"] = f"Bearer {tk}"
    req = urllib.request.Request(url, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            datos = r.read(3_000_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError("GitHub me ha limitado las consultas; prueba dentro de un rato") from e
        if e.code == 401 and tk:                         # token caducado: se repite sin él
            cab.pop("Authorization")
            with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=timeout) as r:
                datos = r.read(3_000_000).decode("utf-8", "ignore")
        else:
            raise
    return datos if crudo else json.loads(datos)


def _ficha(r: dict) -> dict:
    return {"nombre": r.get("full_name", ""), "url": r.get("html_url", ""), "estrellas": r.get("stargazers_count", 0),
            "descripcion": (r.get("description") or "").strip(), "lenguaje": r.get("language") or "",
            "actualizado": (r.get("pushed_at") or "")[:10], "licencia": ((r.get("license") or {}).get("spdx_id") or ""),
            "temas": r.get("topics") or [], "archivado": bool(r.get("archived"))}


def github_buscar(consulta: str, n: int = 5) -> list[dict]:
    """Repositorios que vienen al caso, los más útiles primero (relevancia + estrellas, sin archivados)."""
    d = _gh("/search/repositories", {"q": f"{consulta} stars:>=15", "per_page": 15})   # sin proyectos de prueba
    if not d.get("items"):
        d = _gh("/search/repositories", {"q": consulta, "per_page": 15})
    repos = [_ficha(r) for r in d.get("items", []) if not r.get("fork")]
    vivos = [r for r in repos if not r["archivado"]] or repos
    # GitHub ordena por relevancia; entre los 8 primeros, sube los que tienen muchas estrellas
    cabeza = sorted(vivos[:8], key=lambda r: -r["estrellas"])
    return (cabeza + vivos[8:])[:n]


def repo_de_texto(texto: str) -> str | None:
    """«github.com/open-webui/open-webui», «open-webui/open-webui» → "open-webui/open-webui"."""
    texto = texto or ""
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", texto) or \
        re.search(r"(?<![\w./])((?=[\w-]*[A-Za-z])[A-Za-z0-9][\w-]{0,38})/((?=[\w.-]*[A-Za-z])[\w.-]{1,100})(?![\w/])", texto)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2).removesuffix('.git').rstrip('.')}"


def github_repo(nombre: str, limite: int = 20000) -> dict:
    """Ficha del repositorio + README (texto) + última versión publicada, si la hay."""
    r = _ficha(_gh(f"/repos/{nombre}"))
    try:
        r["readme"] = _gh(f"/repos/{nombre}/readme", crudo=True)[:limite]
    except Exception:
        r["readme"] = ""
    try:
        rel = _gh(f"/repos/{nombre}/releases/latest")
        r["version"] = rel.get("tag_name", "")
    except Exception:
        r["version"] = ""
    return r


def buscar_repo_por_nombre(nombre: str) -> str | None:
    """«open webui» → "open-webui/open-webui" (el repositorio más conocido con ese nombre)."""
    try:
        d = _gh("/search/repositories", {"q": f"{nombre} in:name", "per_page": 5})
    except Exception:
        return None
    items = d.get("items") or []
    if not items:
        return None
    clave = re.sub(r"[^a-z0-9]", "", nombre.lower())
    exactos = [i for i in items if re.sub(r"[^a-z0-9]", "", i["name"].lower()) == clave]
    return max(exactos or items[:2], key=lambda i: i.get("stargazers_count", 0))["full_name"]


# ================================================================ YouTube
def id_de_youtube(texto: str) -> str | None:
    m = RE_YT.search(texto or "")
    return m.group(1) if m else None


def _texto_yt(nodo) -> str:
    if not isinstance(nodo, dict):
        return ""
    if "simpleText" in nodo:
        return nodo["simpleText"]
    return "".join(r.get("text", "") for r in nodo.get("runs", []))


def youtube_buscar(consulta: str, n: int = 5) -> list[dict]:
    url = ("https://www.youtube.com/results?search_query=" + urllib.parse.quote(consulta) + "&sp=EgIQAQ%3D%3D")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=15) as r:
        pagina = r.read().decode("utf-8", "ignore")
    videos = []
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", pagina, re.S)
    if m:
        try:
            datos = json.loads(m.group(1))
            pila = [datos]
            while pila and len(videos) < n:                 # recorre el árbol buscando «videoRenderer»
                x = pila.pop(0)
                if isinstance(x, dict):
                    v = x.get("videoRenderer")
                    if isinstance(v, dict) and v.get("videoId"):
                        videos.append({"id": v["videoId"], "titulo": _texto_yt(v.get("title")),
                                       "canal": _texto_yt(v.get("ownerText")),
                                       "duracion": _texto_yt(v.get("lengthText")),
                                       "vistas": _texto_yt(v.get("viewCountText"))})
                        continue
                    pila.extend(x.values())
                elif isinstance(x, list):
                    pila.extend(x)
        except ValueError:
            pass
    if not videos:                                          # plan B: solo los ids
        for vid in dict.fromkeys(re.findall(r'"videoId":"([\w-]{11})"', pagina)):
            videos.append({"id": vid, "titulo": consulta, "canal": "", "duracion": "", "vistas": ""})
            if len(videos) >= n:
                break
    return videos


def _segundos(duracion: str) -> int:
    s = 0
    for p in (duracion or "").split(":"):
        s = s * 60 + (int(p) if p.isdigit() else 0)
    return s


def youtube_transcripcion(video_id: str, limite: int = 30000) -> str | None:
    """Lo que se dice en el vídeo (subtítulos en español o, si no hay, en inglés u otro idioma). None si no tiene."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        api = YouTubeTranscriptApi()
        lista = api.list(video_id)
        try:
            t = lista.find_transcript(["es", "es-ES", "es-419", "en", "en-US", "en-GB"])
        except Exception:
            t = next(iter(lista))                          # el idioma que haya
        trozos = t.fetch()
        texto = " ".join(getattr(s, "text", s.get("text", "") if isinstance(s, dict) else "") for s in trozos)
    except Exception:
        return None
    texto = re.sub(r"\[(música|music|aplausos|applause|risas)\]", " ", texto, flags=re.I)
    return re.sub(r"\s+", " ", texto).strip()[:limite] or None


def youtube_titulo(video_id: str) -> str:
    """Título y canal de un vídeo concreto (oEmbed, sin clave)."""
    try:
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=10) as r:
            d = json.load(r)
        return f"{d.get('title', '')} ({d.get('author_name', '')})"
    except Exception:
        return video_id
