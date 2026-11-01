"""
Correo del personaje de Nexus en la página de Asuka: solo lectura (no marca nada como leído, no envía ni borra).

Gmail por IMAP con una «contraseña de aplicación» de Google (la crea la persona con la verificación en dos pasos
activada y la escribe ella en bash ~/jarvis/configurar_correo_nexus.sh). Se guarda en
~/.config/athena-nexus/correo.json con permisos 600; nunca va al registro ni a la IA.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import re
import threading
import time
from html import unescape
from pathlib import Path

CONF = Path.home() / ".config/athena-nexus/correo.json"
_cache: dict = {"t": 0.0, "lista": None, "error": ""}
_cerrojo = threading.Lock()


def configurado() -> bool:
    return CONF.exists()


def _datos() -> dict:
    return json.loads(CONF.read_text(encoding="utf-8"))


def _conectar():
    d = _datos()
    m = imaplib.IMAP4_SSL(d.get("servidor", "imap.gmail.com"), 993, timeout=25)
    m.login(d["usuario"], d["clave"])
    m.select("INBOX", readonly=True)                 # solo mirar: no cambia «leído / no leído»
    return m


def _texto_cab(v: str | None) -> str:
    if not v:
        return ""
    partes = []
    for t, cod in email.header.decode_header(v):
        partes.append(t.decode(cod or "utf-8", "replace") if isinstance(t, bytes) else t)
    return re.sub(r"\s+", " ", "".join(partes)).strip()


def _cuerpo(msg) -> str:
    texto, html = "", ""
    for p in msg.walk() if msg.is_multipart() else [msg]:
        if p.get_content_maintype() == "multipart" or p.get_filename():
            continue
        try:
            datos = p.get_payload(decode=True) or b""
            s = datos.decode(p.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if p.get_content_type() == "text/plain" and not texto:
            texto = s
        elif p.get_content_type() == "text/html" and not html:
            html = s
    if not texto and html:                            # solo texto: nada de HTML del remitente en la página
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
        texto = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", texto)).strip()[:20000]


def lista(n: int = 40) -> dict:
    """Los últimos n correos de la bandeja de entrada (caché de 2 minutos)."""
    if not configurado():
        return {"configurado": False, "correos": []}
    with _cerrojo:
        if _cache["lista"] is not None and time.time() - _cache["t"] < 120:
            return {"configurado": True, "correos": _cache["lista"], "error": _cache["error"]}
        try:
            m = _conectar()
            _, d = m.uid("search", None, "ALL")
            uids = d[0].split()[-n:]
            correos = []
            if uids:
                _, datos = m.uid("fetch", b",".join(uids), "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                for parte in datos:
                    if not isinstance(parte, tuple):
                        continue
                    meta = parte[0].decode("ascii", "replace")
                    uid = re.search(r"UID (\d+)", meta)
                    cab = email.message_from_bytes(parte[1])
                    try:
                        fecha = email.utils.parsedate_to_datetime(cab["Date"]).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        fecha = ""
                    correos.append({"uid": uid.group(1) if uid else "", "de": _texto_cab(cab["From"]),
                                    "asunto": _texto_cab(cab["Subject"]) or "(sin asunto)", "fecha": fecha,
                                    "leido": "\\Seen" in meta})
            m.logout()
            correos.sort(key=lambda c: c["fecha"], reverse=True)
            _cache.update(t=time.time(), lista=correos, error="")
        except Exception as e:
            _cache.update(t=time.time(), lista=_cache["lista"] or [], error=f"{type(e).__name__}: {str(e)[:120]}")
        return {"configurado": True, "correos": _cache["lista"], "error": _cache["error"]}


def leer(uid: str) -> dict:
    if not (configurado() and re.fullmatch(r"\d{1,10}", uid or "")):
        return {"error": "correo no disponible"}
    try:
        m = _conectar()
        _, d = m.uid("fetch", uid, "(BODY.PEEK[])")
        m.logout()
        raw = next((p[1] for p in d if isinstance(p, tuple)), None)
        if not raw:
            return {"error": "no encontrado"}
        msg = email.message_from_bytes(raw)
        adjuntos = [_texto_cab(p.get_filename()) for p in msg.walk() if p.get_filename()]
        return {"de": _texto_cab(msg["From"]), "para": _texto_cab(msg["To"]), "asunto": _texto_cab(msg["Subject"]),
                "fecha": _texto_cab(msg["Date"]), "texto": _cuerpo(msg), "adjuntos": adjuntos}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}
