"""El panel de Nexus en el móvil: una puerta aparte (puerto 8766, toda la red de casa) que solo deja pasar el panel.

La interfaz de Athena (8765) sigue escuchando solo en el propio portátil: desde ella se pueden dar órdenes de todo tipo
(apagar el equipo, abrir programas…) y eso no debe quedar a un paso de cualquiera de la red. Esta pasarela:

- pide una llave: se entra una vez con el enlace que Athena manda por Telegram («nexus en el móvil») y el móvil
  guarda una cookie (HttpOnly, SameSite=Strict, 1 año). Sin llave no se ve nada;
- solo reenvía el panel de Nexus, sus archivos y miniaturas, el correo de Asuka y las acciones del panel; las órdenes
  libres (/orden) solo si empiezan por «nexus»;
- reenvía a 127.0.0.1:8765, así que el panel del móvil y el del portátil son el mismo, con los mismos datos.

Fuera de casa: con Tailscale (VPN gratuita) en el portátil y en el móvil, el mismo enlace con la IP de Tailscale.
La llave se cambia con «nexus, cambia la llave del móvil» (los móviles ya entrados tendrán que volver a entrar).
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUERTO = 8766
INTERNO = "http://127.0.0.1:8765"
CONF = Path.home() / ".config/athena-nexus/movil.json"
COOKIE = "nexus_llave"
GET_PERMITIDOS = re.compile(r"^/(nexus|nexus/(datos|archivo/.+|mini/.+|correo.*|zip.*|manifest\.json|icono\.png)"
                            r"|fuentes/[a-z0-9-]+\.woff2)(\?.*)?$")
POST_PERMITIDOS = {"/nexus/accion", "/nexus/cuenta", "/orden"}


def llave() -> str:
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))["llave"]
    except (OSError, ValueError, KeyError):
        return rotar()


def rotar() -> str:
    CONF.parent.mkdir(parents=True, exist_ok=True)
    nueva = secrets.token_urlsafe(24)
    CONF.write_text(json.dumps({"llave": nueva, "creada": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
    CONF.chmod(0o600)
    return nueva


def ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.1.1", 9))                 # no envía nada: solo elige la interfaz de la red de casa
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def ip_tailscale() -> str:
    """La IP 100.x de Tailscale, si está instalado y conectado."""
    try:
        import subprocess
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        ip = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
        return ip if ip.startswith("100.") else ""
    except Exception:
        return ""


def enlaces() -> dict:
    k = llave()
    d = {"casa": f"http://{ip_local()}:{PUERTO}/entrar?llave={k}"}
    ts = ip_tailscale()
    if ts:
        d["fuera"] = f"http://{ts}:{PUERTO}/entrar?llave={k}"
    return d


PAGINA_FUERA = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Nexus</title><body style="background:#04070d;color:#dcecf5;font:17px system-ui;padding:28px">
<h2 style="color:#38e8ff">Nexus · Asuka</h2><p>{msg}</p><p style="color:#7d93ad">Pídele el enlace a Athena por
Telegram: <b>nexus en el móvil</b>.</p></body>"""


class _Pasarela(BaseHTTPRequestHandler):
    log = staticmethod(print)
    fallos: dict = {}

    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------------- llave
    def _con_llave(self) -> bool:
        c = self.headers.get("Cookie", "")
        m = re.search(rf"(?:^|;\s*){COOKIE}=([A-Za-z0-9_\-]+)", c)
        return bool(m) and hmac.compare_digest(m.group(1), llave())

    def _pagina(self, codigo: int, msg: str) -> None:
        datos = PAGINA_FUERA.format(msg=msg).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _entrar(self) -> None:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        ip = self.client_address[0]
        if sum(1 for t in self.fallos.get(ip, []) if time.time() - t < 600) >= 8:
            return self._pagina(429, "Demasiados intentos. Espera unos minutos.")
        if hmac.compare_digest(q.get("llave", [""])[0], llave()):
            self.send_response(302)
            self.send_header("Set-Cookie", f"{COOKIE}={llave()}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/nexus")
            self.end_headers()
            _Pasarela.log(f"móvil: entrada al panel desde {ip}")
            return
        self.fallos.setdefault(ip, []).append(time.time())
        time.sleep(1)
        self._pagina(403, "Ese enlace no vale (o la llave se ha cambiado).")

    # ---------------- reenvío
    def _reenviar(self, metodo: str, cuerpo: bytes | None = None) -> None:
        cab = {"X-Jarvis": "1"}
        for h in ("Content-Type", "Range"):
            if self.headers.get(h):
                cab[h] = self.headers[h]
        req = urllib.request.Request(INTERNO + self.path, data=cuerpo, method=metodo, headers=cab)
        try:
            r = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            r = e
        except (urllib.error.URLError, OSError):
            return self._pagina(503, "Athena se está reiniciando. Prueba en un minuto.")
        self.send_response(r.status if hasattr(r, "status") else r.code)
        for h in ("Content-Type", "Content-Length", "Content-Disposition", "Cache-Control", "Content-Range",
                  "Accept-Ranges", "Location"):
            v = r.headers.get(h)
            if v:
                self.send_header(h, v)
        self.end_headers()
        try:
            while trozo := r.read(1 << 16):
                self.wfile.write(trozo)
        finally:
            r.close()

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta == "/entrar":
            return self._entrar()
        if not self._con_llave():
            return self._pagina(401, "Para ver el panel de Asuka hace falta entrar con tu enlace.")
        if ruta in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/nexus")
            self.end_headers()
            return
        if not GET_PERMITIDOS.match(self.path):
            return self._pagina(404, "Eso no está en el panel.")
        self._reenviar("GET")

    def do_POST(self):
        ruta = self.path.split("?")[0]
        if not self._con_llave() or ruta not in POST_PERMITIDOS:
            return self._pagina(403, "No permitido.")
        n = min(int(self.headers.get("Content-Length") or 0), 64_000)
        cuerpo = self.rfile.read(n)
        if ruta == "/orden":                              # desde el móvil, solo órdenes del proyecto Nexus
            try:
                texto = str(json.loads(cuerpo or b"{}").get("texto", ""))
            except ValueError:
                texto = ""
            if not re.match(r"(?i)^\s*nexus\b", texto):
                return self._pagina(403, "Desde el móvil solo órdenes de Nexus.")
        self._reenviar("POST", cuerpo)


def arrancar(log=print) -> bool:
    _Pasarela.log = staticmethod(log)
    llave()                                               # la crea la primera vez
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PUERTO), _Pasarela)
    except OSError as e:
        log(f"móvil: la pasarela del panel no arranca ({e})")
        return False
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="pasarela-movil").start()
    log(f"móvil: panel de Nexus en http://{ip_local()}:{PUERTO}/nexus (con llave)")
    return True
