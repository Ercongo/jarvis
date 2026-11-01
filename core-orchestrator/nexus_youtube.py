"""
YouTube del personaje de Nexus con la API oficial (gratis): subir Shorts, poner descripción, palabras clave y banner
del canal, y leer y contestar comentarios.

Usa la misma app de Google Cloud que Jarvis (las credenciales de ~/jarvis/google.json), pero con un permiso aparte,
dado con la cuenta de Google DEL PERSONAJE y guardado en youtube_nexus.json (600). La contraseña nunca pasa por aquí.

Una sola vez, en console.cloud.google.com (con TU cuenta, la dueña del proyecto):
  1. APIs y servicios → Biblioteca → «YouTube Data API v3» → Habilitar.
  2. Pantalla de consentimiento de OAuth → Usuarios de prueba → añadir el Gmail del personaje.
Luego, en el portátil: «nexus, conecta YouTube» (abre http://127.0.0.1:8765/nexus/youtube/conectar) y se entra con
la cuenta del personaje y se pulsa «Permitir».

Límite de Google: los proyectos sin revisar suben los vídeos como PRIVADOS (Google lo levanta gratis tras su
auditoría). Banner, descripción y comentarios funcionan desde el primer día.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from google_cuenta import CONFIG as CONFIG_JARVIS, REDIRECCION, ErrorGoogle, _guardar_privado, _leer
from perfil import SECRETOS

CONFIG = SECRETOS / "youtube_nexus.json"
# la misma vuelta que Jarvis (la que ya admite su app de Google): jarvis.py la reparte según el «state»
URL_CONECTAR = "http://127.0.0.1:8765/nexus/youtube/conectar"
PERMISOS = ["https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl"]
API = "https://www.googleapis.com/youtube/v3"


class YouTube:
    def __init__(self, log=print):
        self.log = log
        self._lock = threading.Lock()
        self._token: tuple[str, float] | None = None
        self._pendiente: dict[str, str] = {}
        self.cfg = _leer(CONFIG)

    def _cliente(self) -> dict:
        c = _leer(CONFIG_JARVIS)
        if not (c.get("client_id") and c.get("client_secret")):
            raise ErrorGoogle("faltan las credenciales de la app de Google de Jarvis")
        return c

    def es_mio(self, estado: str) -> bool:
        return estado in self._pendiente

    @property
    def conectado(self) -> bool:
        return bool(self.cfg.get("refresh_token"))

    def estado(self) -> dict:
        return {"conectado": self.conectado, "canal": self.cfg.get("canal", {}), "url": URL_CONECTAR}

    # ---------- permiso
    def url_permiso(self) -> str:
        c = self._cliente()
        estado, verificador = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
        reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        self._pendiente = {estado: verificador}
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": c["client_id"], "redirect_uri": REDIRECCION, "response_type": "code",
            "scope": " ".join(PERMISOS), "access_type": "offline", "prompt": "consent select_account",
            "state": estado, "code_challenge": reto, "code_challenge_method": "S256"})

    def recibir_codigo(self, p: dict[str, str]) -> tuple[bool, str]:
        if p.get("error"):
            return False, (f"Google no ha dado permiso ({p['error']}). Si pone access_denied, falta añadir el Gmail "
                           "del personaje como «usuario de prueba» en la pantalla de consentimiento de Google Cloud.")
        verificador = self._pendiente.pop(p.get("state", ""), None)
        if not verificador or not p.get("code"):
            return False, "El enlace ha caducado. Vuelve a decir «nexus, conecta YouTube»."
        try:
            r = self._post_token({"grant_type": "authorization_code", "code": p["code"], "redirect_uri": REDIRECCION,
                                  "code_verifier": verificador})
        except ErrorGoogle as e:
            return False, f"Google no ha aceptado el permiso: {e}"
        if not r.get("refresh_token"):
            return False, "Google no ha dado un permiso permanente; repite la conexión."
        with self._lock:
            self.cfg["refresh_token"] = r["refresh_token"]
            self._token = (r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 60)
            _guardar_privado(CONFIG, self.cfg)
        try:
            canal = self.canal()
        except ErrorGoogle as e:
            if "youtube.googleapis.com" in str(e) or "accessNotConfigured" in str(e) or "SERVICE_DISABLED" in str(e):
                return True, ("Permiso guardado, pero falta habilitar «YouTube Data API v3» en tu proyecto de Google "
                              "Cloud (APIs y servicios → Biblioteca).")
            return True, f"Permiso guardado, pero no veo el canal todavía ({e})."
        return True, f"YouTube conectado: canal «{canal.get('titulo', '?')}». Ya puedo personalizarlo y subir vídeos."

    def _post_token(self, campos: dict) -> dict:
        c = self._cliente()
        datos = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                        **campos}).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=datos,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise ErrorGoogle(e.read()[:300].decode("utf-8", "ignore") or f"HTTP {e.code}", e.code) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErrorGoogle(f"sin conexión ({e})") from e

    def token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token[1]:
                return self._token[0]
            if not self.conectado:
                raise ErrorGoogle("YouTube del personaje sin conectar", 401)
            try:
                r = self._post_token({"grant_type": "refresh_token", "refresh_token": self.cfg["refresh_token"]})
            except ErrorGoogle as e:
                if "invalid_grant" in str(e):
                    self.cfg.pop("refresh_token", None)
                    _guardar_privado(CONFIG, self.cfg)
                raise
            self._token = (r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 60)
            return self._token[0]

    def _llamar(self, metodo: str, url: str, cuerpo: bytes | None = None, tipo: str = "application/json",
                timeout: float = 60) -> dict:
        for intento in range(2):
            req = urllib.request.Request(url, data=cuerpo, method=metodo, headers={
                "Authorization": f"Bearer {self.token()}", "Content-Type": tipo})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    b = r.read()
                    return json.loads(b) if b else {}
            except urllib.error.HTTPError as e:
                detalle = e.read()[:400].decode("utf-8", "ignore")
                if e.code == 401 and intento == 0:
                    self._token = None
                    continue
                raise ErrorGoogle(f"HTTP {e.code}: {detalle}", e.code) from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise ErrorGoogle(f"sin conexión ({e})") from e
        raise ErrorGoogle("no autorizado", 401)

    def _json(self, metodo: str, ruta: str, params: dict, cuerpo: dict | None = None) -> dict:
        url = f"{API}/{ruta}?" + urllib.parse.urlencode(params)
        return self._llamar(metodo, url, json.dumps(cuerpo).encode() if cuerpo is not None else None)

    # ---------- canal
    def canal(self) -> dict:
        r = self._json("GET", "channels", {"part": "snippet,brandingSettings,statistics", "mine": "true"})
        it = (r.get("items") or [{}])[0]
        if not it:
            raise ErrorGoogle("esa cuenta no tiene canal de YouTube todavía")
        c = {"id": it["id"], "titulo": it["snippet"]["title"], "url": f"https://www.youtube.com/channel/{it['id']}",
             "suscriptores": it.get("statistics", {}).get("subscriberCount"),
             "videos": it.get("statistics", {}).get("videoCount"),
             "vistas": it.get("statistics", {}).get("viewCount")}
        self.cfg["canal"] = c
        self.cfg["_branding"] = it.get("brandingSettings", {})
        _guardar_privado(CONFIG, self.cfg)
        return c

    def personalizar(self, descripcion: str, palabras: list[str], banner: Path | None = None) -> list[str]:
        """Descripción, palabras clave e idioma del canal; y el banner si se da. Devuelve lo que ha cambiado."""
        c = self.canal()
        hecho = []
        url_banner = None
        if banner and banner.exists():
            r = self._llamar("POST", "https://www.googleapis.com/upload/youtube/v3/channelBanners/insert",
                             banner.read_bytes(), "image/jpeg", timeout=120)
            url_banner = r.get("url")
        b = self.cfg.get("_branding", {})
        canal = dict(b.get("channel", {}))
        canal.update(description=descripcion[:1000], defaultLanguage="es", country="ES",
                     keywords=" ".join(f'"{p}"' if " " in p else p for p in palabras)[:500])
        cuerpo = {"id": c["id"], "brandingSettings": {"channel": canal}}
        if url_banner:
            cuerpo["brandingSettings"]["image"] = {"bannerExternalUrl": url_banner}
        self._json("PUT", "channels", {"part": "brandingSettings"}, cuerpo)
        hecho += ["descripción", "palabras clave", "idioma y país"] + (["banner"] if url_banner else [])
        return hecho

    # ---------- vídeos
    def subir(self, video: Path, titulo: str, descripcion: str, etiquetas: list[str], publico: bool = True) -> dict:
        """Sube un Short. Marca «contenido alterado o sintético» (lo exige YouTube a los vídeos hechos con IA)."""
        meta = {"snippet": {"title": titulo[:100], "description": descripcion[:4900], "tags": etiquetas[:15],
                            "categoryId": "20", "defaultLanguage": "es", "defaultAudioLanguage": "es"},
                "status": {"privacyStatus": "public" if publico else "private", "selfDeclaredMadeForKids": False,
                           "containsSyntheticMedia": True}}
        frontera = uuid.uuid4().hex
        cuerpo = (f"--{frontera}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                  + json.dumps(meta).encode() + f"\r\n--{frontera}\r\nContent-Type: video/mp4\r\n\r\n".encode()
                  + video.read_bytes() + f"\r\n--{frontera}--\r\n".encode())
        r = self._llamar("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part="
                                 "snippet,status", cuerpo, f"multipart/related; boundary={frontera}", timeout=600)
        estado = r.get("status", {}).get("privacyStatus", "")
        return {"id": r.get("id"), "url": f"https://youtube.com/shorts/{r.get('id')}", "privacidad": estado}

    # ---------- comentarios
    def comentarios(self, n: int = 30) -> list[dict]:
        c = self.cfg.get("canal") or self.canal()
        r = self._json("GET", "commentThreads", {"part": "snippet", "allThreadsRelatedToChannelId": c["id"],
                                                  "maxResults": n, "order": "time", "textFormat": "plainText"})
        out = []
        for it in r.get("items", []):
            s = it["snippet"]["topLevelComment"]["snippet"]
            out.append({"id": it["snippet"]["topLevelComment"]["id"], "video": it["snippet"].get("videoId", ""),
                        "autor": s.get("authorDisplayName", ""), "texto": s.get("textDisplay", ""),
                        "fecha": s.get("publishedAt", "")[:16].replace("T", " "), "red": "youtube",
                        "respuestas": it["snippet"].get("totalReplyCount", 0)})
        return out

    def responder(self, id_comentario: str, texto: str) -> dict:
        return self._json("POST", "comments", {"part": "snippet"},
                          {"snippet": {"parentId": id_comentario, "textOriginal": texto[:9000]}})
