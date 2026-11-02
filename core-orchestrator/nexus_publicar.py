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
def publicar(red: str, tipo: str, ruta: Path, texto: str, titulo: str = "") -> dict:
    if red not in conectadas():
        raise ErrorRed(f"{red} sin conectar")
    if red == "facebook":
        return facebook_video(ruta, texto, titulo) if tipo == "video" else facebook_foto(ruta, texto)
    if red == "instagram":
        return instagram_reel(ruta, texto) if tipo == "video" else instagram_foto(ruta, texto)
    if red == "x":
        if tipo == "video":
            raise ErrorRed("en X de momento solo publico texto y fotos")
        return x_post(texto, ruta)
    raise ErrorRed(f"no sé publicar en {red}")
