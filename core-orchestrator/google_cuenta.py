"""
Cuenta de Google para Jarvis: Gmail y Google Calendar con OAuth (sin librerías extra).

Cómo se conecta (una sola vez):
  1. En console.cloud.google.com se crea un proyecto con las API de Gmail y Calendar y un "ID de cliente OAuth"
     de tipo "App de escritorio". Se descarga su JSON (client_secret_….json).
  2. Ese JSON llega a Jarvis por Telegram (como documento) o se copia a ~/jarvis/google_cliente.json.
  3. "Jarvis, conecta mi cuenta de Google": abre en el portátil http://127.0.0.1:8765/google/conectar, que lleva
     a la página de permisos de Google; al aceptar, Google vuelve a http://127.0.0.1:8765/google y Jarvis guarda
     el permiso (refresh token) en ~/jarvis/google.json con permisos 600.
La contraseña de Google nunca pasa por Jarvis. El permiso se retira en myaccount.google.com → Seguridad →
Aplicaciones de terceros, o diciendo "desconecta mi cuenta de Google".
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
from pathlib import Path
from perfil import DATOS, SECRETOS

BASE = DATOS
CONFIG = SECRETOS / "google.json"
CLIENTE = SECRETOS / "google_cliente.json"
REDIRECCION = "http://127.0.0.1:8765/google"
URL_CONECTAR = "http://127.0.0.1:8765/google/conectar"
PERMISOS = ["https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.modify"]


class ErrorGoogle(Exception):
    def __init__(self, mensaje: str, codigo: int = 0):
        super().__init__(mensaje)
        self.codigo = codigo


def _leer(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_privado(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(ruta)


def extraer_cliente(datos: dict) -> dict | None:
    """Del JSON que descarga Google (o uno ya simplificado) saca client_id y client_secret."""
    for clave in ("installed", "web"):
        if isinstance(datos.get(clave), dict):
            datos = datos[clave]
            break
    cid, secreto = datos.get("client_id"), datos.get("client_secret")
    if isinstance(cid, str) and cid.endswith(".apps.googleusercontent.com") and isinstance(secreto, str):
        return {"client_id": cid, "client_secret": secreto}
    return None


class CuentaGoogle:
    def __init__(self, log=print):
        self.log = log
        self._lock = threading.Lock()
        self._token: tuple[str, float] | None = None       # (access token, caduca)
        self._pendiente: dict[str, str] = {}                 # state → verificador PKCE
        self.al_cambiar = lambda: None                       # para el panel y para arrancar la sincronización
        self.cfg = _leer(CONFIG)
        if not self.cfg.get("client_id"):
            cliente = extraer_cliente(_leer(CLIENTE))
            if cliente:
                self.cfg.update(cliente)

    # ---------- estado
    @property
    def tiene_cliente(self) -> bool:
        return bool(self.cfg.get("client_id") and self.cfg.get("client_secret"))

    @property
    def conectada(self) -> bool:
        return self.tiene_cliente and bool(self.cfg.get("refresh_token"))

    @property
    def email(self) -> str:
        return self.cfg.get("email", "")

    def estado(self) -> str:
        if self.conectada:
            return "conectada · " + (self.email.split("@")[0] or "Google")
        return "sin conectar"

    # ---------- credenciales de la app (el JSON de Google Cloud)
    def guardar_cliente(self, datos: dict) -> tuple[bool, str]:
        cliente = extraer_cliente(datos)
        if not cliente:
            return False, "Ese archivo no parece el de credenciales de Google (falta client_id o client_secret)."
        with self._lock:
            if cliente["client_id"] != self.cfg.get("client_id"):
                self.cfg.pop("refresh_token", None)          # otro cliente: hay que volver a dar permiso
            self.cfg.update(cliente)
            _guardar_privado(CONFIG, self.cfg)
        try:
            CLIENTE.unlink()
        except OSError:
            pass
        self.log("google: credenciales de la app guardadas")
        return True, ("Credenciales de Google guardadas. Ahora di «Jarvis, conecta mi cuenta de Google» delante del "
                      "portátil, o abre en él " + URL_CONECTAR + " y acepta los permisos.")

    # ---------- permiso del usuario (OAuth con PKCE y redirección a 127.0.0.1)
    def url_permiso(self) -> str:
        if not self.tiene_cliente:
            raise ErrorGoogle("faltan las credenciales de la app")
        estado = secrets.token_urlsafe(24)
        verificador = secrets.token_urlsafe(64)
        reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        self._pendiente = {estado: verificador}              # solo vale el último enlace generado
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": self.cfg["client_id"], "redirect_uri": REDIRECCION, "response_type": "code",
            "scope": " ".join(PERMISOS), "access_type": "offline", "prompt": "consent",
            "state": estado, "code_challenge": reto, "code_challenge_method": "S256"})

    def recibir_codigo(self, parametros: dict[str, str]) -> tuple[bool, str]:
        if parametros.get("error"):
            return False, f"Google no ha dado permiso ({parametros['error']})."
        verificador = self._pendiente.pop(parametros.get("state", ""), None)
        if not verificador or not parametros.get("code"):
            return False, "El enlace de permiso ha caducado o no es válido. Vuelve a pedir «conecta mi cuenta de Google»."
        try:
            r = self._post_token({"grant_type": "authorization_code", "code": parametros["code"],
                                  "redirect_uri": REDIRECCION, "code_verifier": verificador})
        except ErrorGoogle as e:
            return False, f"Google no ha aceptado el permiso: {e}"
        if not r.get("refresh_token"):
            return False, "Google no ha dado un permiso permanente. Quita el acceso de Jarvis en tu cuenta y repite."
        concedidos = set((r.get("scope") or "").split())
        faltan = [p.rsplit("/", 1)[-1] for p in PERMISOS if p not in concedidos]
        with self._lock:
            self.cfg["refresh_token"] = r["refresh_token"]
            self.cfg["permisos"] = sorted(concedidos)
            self._token = (r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 60)
            _guardar_privado(CONFIG, self.cfg)
        try:
            self.cfg["email"] = self.api("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")["emailAddress"]
            _guardar_privado(CONFIG, self.cfg)
        except ErrorGoogle:
            pass
        self.log(f"google: cuenta conectada ({self.email or 'sin correo'})" + (f"; faltan permisos {faltan}" if faltan else ""))
        self.al_cambiar()
        if faltan:
            return True, ("Cuenta conectada, pero no marcaste todos los permisos (" + ", ".join(faltan) +
                          "). Repite la conexión y marca todas las casillas.")
        return True, f"Cuenta de Google conectada ({self.email}). Ya tengo tu correo y tu calendario."

    def desconectar(self) -> None:
        token = self.cfg.get("refresh_token")
        if token:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    "https://oauth2.googleapis.com/revoke?" + urllib.parse.urlencode({"token": token}),
                    data=b"", headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=10).close()
            except (urllib.error.URLError, OSError):
                pass
        with self._lock:
            for k in ("refresh_token", "email", "permisos"):
                self.cfg.pop(k, None)
            self._token = None
            _guardar_privado(CONFIG, self.cfg)
        self.log("google: cuenta desconectada")
        self.al_cambiar()

    # ---------- tokens
    def _post_token(self, campos: dict) -> dict:
        datos = urllib.parse.urlencode({"client_id": self.cfg["client_id"],
                                        "client_secret": self.cfg["client_secret"], **campos}).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=datos,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            cuerpo = e.read()[:300].decode("utf-8", "ignore")
            raise ErrorGoogle(cuerpo or f"HTTP {e.code}", e.code) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErrorGoogle(f"sin conexión ({e})") from e

    def token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token[1]:
                return self._token[0]
            if not self.conectada:
                raise ErrorGoogle("la cuenta de Google no está conectada", 401)
            try:
                r = self._post_token({"grant_type": "refresh_token", "refresh_token": self.cfg["refresh_token"]})
            except ErrorGoogle as e:
                if "invalid_grant" in str(e):              # permiso retirado o caducado
                    self.cfg.pop("refresh_token", None)
                    _guardar_privado(CONFIG, self.cfg)
                    self.log("google: el permiso ya no vale (retirado o caducado); hay que volver a conectar")
                    threading.Thread(target=self.al_cambiar, daemon=True).start()
                raise
            self._token = (r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 60)
            return self._token[0]

    # ---------- llamadas a las API
    def api(self, metodo: str, url: str, cuerpo: dict | None = None, params: dict | None = None,
            timeout: float = 20) -> dict:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        for intento in range(2):
            req = urllib.request.Request(url, data=datos, method=metodo, headers={
                "Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                "User-Agent": "Jarvis/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    bruto = r.read()
                    return json.loads(bruto) if bruto else {}
            except urllib.error.HTTPError as e:
                detalle = e.read()[:300].decode("utf-8", "ignore")
                if e.code == 401 and intento == 0:
                    self._token = None                     # token caducado: se pide otro y se repite
                    continue
                raise ErrorGoogle(f"HTTP {e.code}: {detalle}", e.code) from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise ErrorGoogle(f"sin conexión ({e})") from e
        raise ErrorGoogle("no autorizado", 401)
