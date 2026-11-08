"""
Publicar fotos y vídeos del personaje con las API oficiales (gratis):

  Facebook (página)  fotos y vídeos                 Graph API, token de página
  Instagram          fotos y reels                   Graph API (cuenta profesional enlazada a la página)
  X                  textos y fotos                  API v2 con OAuth 1.0a (plan gratuito)
  YouTube            Shorts                          nexus_youtube.py

Las claves las pone la persona en el portátil con  bash ~/jarvis/configurar_redes_nexus.sh  y se guardan en
~/.config/athena-nexus/redes.json (600). Nunca van al registro ni a la IA.

La app de Meta puede quedarse en «modo desarrollo»: así solo publica en las cuentas de quien la administra, que es
justo lo que hace falta, y no necesita la revisión de Meta.
TikTok y Pinterest piden revisar la app antes de dejar publicar: siguen yendo a mano desde la cola.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CONF = Path.home() / ".config/athena-nexus/redes.json"
GRAPH = "https://graph.facebook.com/v21.0"


class ErrorRed(Exception):
    pass


def config() -> dict:
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def conectadas() -> list[str]:
    c = config()
    out = []
    if c.get("meta", {}).get("page_token"):
        out.append("facebook")
        if c["meta"].get("ig_id"):
            out.append("instagram")
    if all(c.get("x", {}).get(k) for k in ("api_key", "api_secret", "token", "token_secret")):
        out.append("x")
    return out


def _http(metodo: str, url: str, datos: bytes | None = None, cab: dict | None = None, timeout: float = 120) -> dict:
    req = urllib.request.Request(url, data=datos, method=metodo, headers=cab or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            return json.loads(b) if b else {}
    except urllib.error.HTTPError as e:
        detalle = e.read()[:500].decode("utf-8", "ignore")
        try:
            detalle = json.loads(detalle).get("error", {}).get("message", detalle) if detalle.startswith("{") else detalle
        except (ValueError, AttributeError):
            pass
        import re                                         # Meta repite el token en sus errores: no se muestra
        raise ErrorRed(f"HTTP {e.code}: {re.sub(r'EAA[0-9A-Za-z]+', '[token]', str(detalle))[:300]}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorRed(f"sin conexión ({e})") from e


def _multipart(campos: dict, archivo: tuple[str, Path, str] | None) -> tuple[bytes, str]:
    f = uuid.uuid4().hex
    partes = [f'--{f}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in campos.items()]
    if archivo:
        nombre, ruta, tipo = archivo
        partes.append(f'--{f}\r\nContent-Disposition: form-data; name="{nombre}"; filename="{ruta.name}"\r\n'
                      f"Content-Type: {tipo}\r\n\r\n".encode() + ruta.read_bytes() + b"\r\n")
    partes.append(f"--{f}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={f}"


# ================================================================ Facebook
def facebook_foto(ruta: Path, texto: str, publicada: bool = True) -> dict:
    m = config()["meta"]
    cuerpo, tipo = _multipart({"caption": texto, "published": "true" if publicada else "false",
                               "access_token": m["page_token"]}, ("source", ruta, "image/jpeg"))
    r = _http("POST", f"{GRAPH}/{m['page_id']}/photos", cuerpo, {"Content-Type": tipo})
    return {"id": r.get("id"), "url": f"https://www.facebook.com/{r.get('post_id') or r.get('id')}"}


def facebook_video(ruta: Path, texto: str, titulo: str = "") -> dict:
    m = config()["meta"]
    cuerpo, tipo = _multipart({"description": texto, "title": titulo[:250], "access_token": m["page_token"]},
                              ("source", ruta, "video/mp4"))
    r = _http("POST", f"https://graph-video.facebook.com/v21.0/{m['page_id']}/videos", cuerpo,
              {"Content-Type": tipo}, timeout=900)
    return {"id": r.get("id"), "url": f"https://www.facebook.com/{m['page_id']}/videos/{r.get('id')}"}


def _vale_para_reel(ruta: Path) -> bool:
    """Facebook solo acepta como reel vídeos verticales de 3 a 90 segundos."""
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:format=duration", "-of", "default=nw=1", str(ruta)],
                           capture_output=True, text=True, timeout=30)
        d = dict(x.split("=", 1) for x in r.stdout.split() if "=" in x)
        return int(d["height"]) > int(d["width"]) and 3 <= float(d["duration"]) <= 90
    except Exception:
        return False


def facebook_reel(ruta: Path, texto: str) -> dict:
    """Reel de la página en tres pasos (empezar, subir el archivo, publicar): sale en la pestaña Reels y se reparte
    mucho más que un vídeo normal."""
    m = config()["meta"]
    tok = m["page_token"]
    base = f"{GRAPH}/{m['page_id']}/video_reels"
    r = _http("POST", base, urllib.parse.urlencode({"upload_phase": "start", "access_token": tok}).encode())
    vid = r.get("video_id")
    if not vid:
        raise ErrorRed("Facebook no ha abierto la subida del reel")
    datos = ruta.read_bytes()
    _http("POST", f"https://rupload.facebook.com/video-upload/v21.0/{vid}", datos,
          {"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(datos)),
           "Content-Type": "application/octet-stream"}, timeout=900)
    _http("POST", base, urllib.parse.urlencode({"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                "description": texto, "access_token": tok}).encode())
    return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}"}


def facebook_movimiento(ruta: Path, texto: str, titulo: str = "") -> dict:
    """Reel si el vídeo cumple (vertical, 3-90 s); si no, o si Facebook lo rechaza, vídeo normal."""
    if _vale_para_reel(ruta):
        try:
            return facebook_reel(ruta, texto)
        except ErrorRed as e:
            if "sin conexión" in str(e):
                raise
    return facebook_video(ruta, texto, titulo)


# ================================================================ Instagram
def _ig_publicar(contenedor: str) -> dict:
    m = config()["meta"]
    tok = m["page_token"]
    for _ in range(60):                                  # hasta 10 min mientras Instagram procesa
        s = _http("GET", f"{GRAPH}/{contenedor}?fields=status_code,status&access_token={tok}")
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            raise ErrorRed(f"Instagram no ha aceptado el archivo: {s.get('status', '')}")
        time.sleep(10)
    r = _http("POST", f"{GRAPH}/{m['ig_id']}/media_publish?" + urllib.parse.urlencode(
        {"creation_id": contenedor, "access_token": tok}))
    p = _http("GET", f"{GRAPH}/{r['id']}?fields=permalink&access_token={tok}")
    return {"id": r["id"], "url": p.get("permalink", "")}


def instagram_foto(ruta: Path, texto: str) -> dict:
    """Instagram solo coge fotos desde una dirección pública: se sube antes a la página de Facebook SIN publicar
    (no se ve en la página) y se usa la dirección de esa copia."""
    m = config()["meta"]
    tok = m["page_token"]
    oculta = facebook_foto(ruta, "", publicada=False)
    img = _http("GET", f"{GRAPH}/{oculta['id']}?fields=images&access_token={tok}")
    url = max(img.get("images", []), key=lambda i: i.get("width", 0))["source"]
    c = _http("POST", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
        {"image_url": url, "caption": texto[:2200], "access_token": tok}))
    return _ig_publicar(c["id"])


def instagram_carrusel(rutas: list[Path], texto: str) -> dict:
    """Varias fotos (2-10) en una sola publicación de Instagram, que se pasan con el dedo."""
    m = config()["meta"]
    tok = m["page_token"]
    hijos = []
    for r in rutas[:10]:
        oculta = facebook_foto(r, "", publicada=False)
        img = _http("GET", f"{GRAPH}/{oculta['id']}?fields=images&access_token={tok}")
        url = max(img.get("images", []), key=lambda i: i.get("width", 0))["source"]
        h = _http("POST", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
            {"image_url": url, "is_carousel_item": "true", "access_token": tok}))
        hijos.append(h["id"])
    c = _http("POST", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
        {"media_type": "CAROUSEL", "children": ",".join(hijos), "caption": texto[:2200], "access_token": tok}))
    return _ig_publicar(c["id"])


def instagram_historia(ruta: Path) -> dict:
    """Una historia (24 h) con una foto o un vídeo vertical."""
    m = config()["meta"]
    tok = m["page_token"]
    if ruta.suffix.lower() == ".mp4":
        c = _http("POST", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
            {"media_type": "STORIES", "upload_type": "resumable", "access_token": tok}))
        datos = ruta.read_bytes()
        _http("POST", c["uri"], datos, {"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(datos))},
              timeout=900)
    else:
        oculta = facebook_foto(ruta, "", publicada=False)
        img = _http("GET", f"{GRAPH}/{oculta['id']}?fields=images&access_token={tok}")
        url = max(img.get("images", []), key=lambda i: i.get("width", 0))["source"]
        c = _http("POST", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
            {"image_url": url, "media_type": "STORIES", "access_token": tok}))
    r = _ig_publicar(c["id"])
    r["url"] = r.get("url") or "https://www.instagram.com/stories/"
    return r


def estadisticas() -> dict:
    """Seguidores y publicaciones de la página de Facebook y de Instagram (para el panel)."""
    c = config().get("meta", {})
    if not c.get("page_token"):
        return {}
    tok, out = c["page_token"], {}
    try:
        f = _http("GET", f"{GRAPH}/{c['page_id']}?fields=followers_count,fan_count&access_token={tok}", timeout=20)
        out["facebook"] = {"seguidores": f.get("followers_count", f.get("fan_count", 0))}
        if c.get("ig_id"):
            i = _http("GET", f"{GRAPH}/{c['ig_id']}?fields=followers_count,media_count&access_token={tok}", timeout=20)
            out["instagram"] = {"seguidores": i.get("followers_count", 0), "publicaciones": i.get("media_count", 0)}
    except ErrorRed:
        pass
    return out


def instagram_comentarios(publicaciones: int = 12) -> list[dict]:
    """Comentarios de sus últimas publicaciones de Instagram (leerlos va con el permiso que ya hay)."""
    m = config().get("meta", {})
    if not (m.get("page_token") and m.get("ig_id")):
        return []
    tok = m["page_token"]
    r = _http("GET", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
        {"fields": "id,caption,permalink,comments_count,comments.limit(25){id,text,username,timestamp,replies{id}}",
         "limit": publicaciones, "access_token": tok}), timeout=40)
    propio = (m.get("ig_usuario") or "").lower()
    out = []
    for p in r.get("data", []):
        for c in (p.get("comments") or {}).get("data", []):
            if propio and (c.get("username") or "").lower() == propio:
                continue
            out.append({"id": c["id"], "video": (p.get("caption") or "")[:60], "autor": "@" + (c.get("username") or "?"),
                        "texto": c.get("text", ""), "fecha": (c.get("timestamp") or "")[:16].replace("T", " "),
                        "red": "instagram", "url": p.get("permalink", ""),
                        "respuestas": len((c.get("replies") or {}).get("data", []))})
    return out


def instagram_responder(id_comentario: str, texto: str) -> dict:
    """Responder necesita el permiso «instagram_manage_comments» (se marca al volver a conectar Meta)."""
    tok = config()["meta"]["page_token"]
    try:
        return _http("POST", f"{GRAPH}/{id_comentario}/replies?" + urllib.parse.urlencode(
            {"message": texto[:2000], "access_token": tok}), timeout=40)
    except ErrorRed as e:
        if "permission" in str(e).lower() or "(#10)" in str(e) or "(#200)" in str(e):
            raise ErrorRed("a la conexión de Meta le falta el permiso de gestionar comentarios: copia la respuesta "
                           "y contéstalo tú en Instagram, o vuelve a conectar Meta marcando «instagram_manage_comments»"
                           ) from e
        raise


def facebook_comentarios(publicaciones: int = 10) -> list[dict]:
    """Comentarios de la gente en sus últimas publicaciones de la página (pages_read_user_content)."""
    m = config().get("meta", {})
    if not m.get("page_token"):
        return []
    tok = m["page_token"]
    r = _http("GET", f"{GRAPH}/{m['page_id']}/posts?" + urllib.parse.urlencode(
        {"fields": "id,message,permalink_url,comments.limit(25){id,message,from,created_time,comment_count}",
         "limit": publicaciones, "access_token": tok}), timeout=40)
    out = []
    for p in r.get("data", []):
        for c in (p.get("comments") or {}).get("data", []):
            if (c.get("from") or {}).get("id") == m["page_id"]:
                continue                                  # los suyos no
            out.append({"id": c["id"], "video": (p.get("message") or "")[:60],
                        "autor": (c.get("from") or {}).get("name") or "alguien", "texto": c.get("message", ""),
                        "fecha": (c.get("created_time") or "")[:16].replace("T", " "), "red": "facebook",
                        "url": p.get("permalink_url", ""), "respuestas": c.get("comment_count", 0)})
    return out


def facebook_responder(id_comentario: str, texto: str) -> dict:
    tok = config()["meta"]["page_token"]
    return _http("POST", f"{GRAPH}/{id_comentario}/comments?" + urllib.parse.urlencode(
        {"message": texto[:8000], "access_token": tok}), timeout=40)


def instagram_publicaciones(n: int = 25) -> list[dict]:
    m = config()["meta"]
    r = _http("GET", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
        {"fields": "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count",
         "limit": n, "access_token": m["page_token"]}), timeout=40)
    return r.get("data", [])


def instagram_borrar(id_publicacion: str) -> None:
    """Borra una publicación suya de Instagram (instagram_manage_contents). No se puede deshacer."""
    tok = config()["meta"]["page_token"]
    _http("DELETE", f"{GRAPH}/{id_publicacion}?access_token={tok}", timeout=40)


def rendimiento(n: int = 25) -> list[dict]:
    """Cómo le ha ido a cada publicación de Instagram: alcance, vistas, guardados, compartidos, me gusta."""
    tok = config()["meta"]["page_token"]
    out = []
    for p in instagram_publicaciones(n):
        fila = {"id": p["id"], "texto": (p.get("caption") or "")[:120], "tipo": p.get("media_product_type") or
                p.get("media_type"), "fecha": (p.get("timestamp") or "")[:16].replace("T", " "),
                "hora": (p.get("timestamp") or "")[11:13], "url": p.get("permalink", ""),
                "me_gusta": p.get("like_count", 0), "comentarios": p.get("comments_count", 0)}
        for metricas in ("reach,views,saved,shares,total_interactions", "reach,saved,shares,total_interactions",
                         "reach,saved"):
            try:
                r = _http("GET", f"{GRAPH}/{p['id']}/insights?metric={metricas}&access_token={tok}", timeout=30)
                for x in r.get("data", []):
                    fila[x["name"]] = (x.get("values") or [{}])[0].get("value", x.get("total_value", {}).get("value", 0))
                break
            except ErrorRed:
                continue
        out.append(fila)
    return out


def instagram_reel(ruta: Path, texto: str) -> dict:
    """Subida «reanudable» desde el propio portátil: no hace falta servidor público."""
    m = config()["meta"]
    tok = m["page_token"]
    c = _http("POST", f"{GRAPH}/{m['ig_id']}/media?" + urllib.parse.urlencode(
        {"media_type": "REELS", "upload_type": "resumable", "caption": texto[:2200], "share_to_feed": "true",
         "access_token": tok}))
    datos = ruta.read_bytes()
    _http("POST", c["uri"], datos, {"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(datos))},
          timeout=900)
    return _ig_publicar(c["id"])


# ================================================================ X
def _oauth1(metodo: str, url: str, x: dict, params: dict | None = None) -> str:
    o = {"oauth_consumer_key": x["api_key"], "oauth_nonce": secrets.token_hex(16),
         "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
         "oauth_token": x["token"], "oauth_version": "1.0"}
    todo = {**o, **(params or {})}
    q = lambda s: urllib.parse.quote(str(s), safe="~")
    base = "&".join([metodo.upper(), q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(todo.items())))])
    clave = f"{q(x['api_secret'])}&{q(x['token_secret'])}"
    o["oauth_signature"] = base64.b64encode(hmac.new(clave.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(o.items()))


def x_post(texto: str, foto: Path | None = None) -> dict:
    x = config()["x"]
    medios = []
    if foto:
        url = "https://api.x.com/2/media/upload"
        cuerpo, tipo = _multipart({"media_category": "tweet_image"}, ("media", foto, "image/jpeg"))
        r = _http("POST", url, cuerpo, {"Authorization": _oauth1("POST", url, x), "Content-Type": tipo})
        mid = (r.get("data") or {}).get("id") or r.get("media_id_string")
        if mid:
            medios.append(str(mid))
    url = "https://api.x.com/2/tweets"
    cuerpo = {"text": texto[:280]}
    if medios:
        cuerpo["media"] = {"media_ids": medios}
    r = _http("POST", url, json.dumps(cuerpo).encode(),
              {"Authorization": _oauth1("POST", url, x), "Content-Type": "application/json"})
    tid = (r.get("data") or {}).get("id", "")
    return {"id": tid, "url": f"https://x.com/i/web/status/{tid}"}


# ================================================================ una sola puerta
def publicar(red: str, tipo: str, ruta: Path, texto: str, titulo: str = "", extra: list[Path] | None = None) -> dict:
    if red not in conectadas():
        raise ErrorRed(f"{red} sin conectar")
    if tipo == "carrusel":
        if red == "instagram":
            return instagram_carrusel([ruta] + list(extra or []), texto)
        if red == "facebook":
            return facebook_foto(ruta, texto)            # en Facebook, la primera foto
        raise ErrorRed(f"en {red} no hay carrusel")
    if red == "facebook":
        return facebook_movimiento(ruta, texto, titulo) if tipo == "video" else facebook_foto(ruta, texto)
    if red == "instagram":
        if tipo == "historia":
            return instagram_historia(ruta)
        return instagram_reel(ruta, texto) if tipo == "video" else instagram_foto(ruta, texto)
    if red == "x":
        if tipo == "video":
            raise ErrorRed("en X de momento solo publico texto y fotos")
        return x_post(texto, ruta)
    raise ErrorRed(f"no sé publicar en {red}")
