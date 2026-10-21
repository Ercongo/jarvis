"""
Control de Jarvis desde el móvil con un bot de Telegram.

- El token se guarda en ~/jarvis/telegram.json (nunca en el código).
- Solo obedece a UNA persona: el dueño. Para vincularse, Jarvis dice en voz alta un código de 4 cifras
  y hay que mandárselo al bot. Los mensajes de cualquier otra persona se ignoran.
- Acepta texto y notas de voz (se transcriben con el mismo whisper).
- Las órdenes que piden confirmación (apagar, reiniciar…) se confirman respondiendo "sí" en el chat.
"""

from __future__ import annotations

import json
import subprocess
import queue
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable
from perfil import SECRETOS

CONFIG = SECRETOS / "telegram.json"
TMP = Path("/tmp/jarvis")


def leer_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_config(c: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(c, indent=2), encoding="utf-8")
    CONFIG.chmod(0o600)                          # el token es como una contraseña


class Telegram:
    def __init__(self, procesar: Callable[[str], dict], decir: Callable[..., None],
                 transcribir: Callable[[str], str] | None = None, log=print):
        self.procesar = procesar           # texto -> {"texto":…, "archivo":…, "despues":…}
        self.decir = decir
        self.transcribir = transcribir
        self.log = log
        self.cfg = leer_config()
        self.token = self.cfg.get("token", "").strip()
        self.dueno = self.cfg.get("dueno")
        self.codigo = None
        self.offset = 0
        self.ordenes: queue.Queue = queue.Queue()
        self.respuestas: queue.Queue | None = None     # mientras esperamos un "sí/no"
        self.al_recibir_archivo: Callable[[Path, bool], str] | None = None   # Jarvis lo abre en el portátil

    @property
    def activo(self) -> bool:
        return bool(self.token)

    # ---------- API
    def _api(self, metodo: str, datos: dict | None = None, timeout: int = 20) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{metodo}"
        cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
        with urllib.request.urlopen(urllib.request.Request(url, data=cuerpo), timeout=timeout) as r:
            return json.load(r)

    def enviar(self, texto: str, chat: int | None = None) -> None:
        chat = chat or self.dueno
        if not (self.activo and chat):
            return
        try:
            self._api("sendMessage", {"chat_id": chat, "text": texto[:4000]})
        except Exception as e:
            self.log(f"telegram: no se pudo enviar ({type(e).__name__})")

    def enviar_foto(self, ruta: str, pie: str = "") -> None:
        if not (self.activo and self.dueno):
            return
        frontera = uuid.uuid4().hex
        datos = Path(ruta).read_bytes()
        partes = []
        for nombre, valor in (("chat_id", str(self.dueno)), ("caption", pie)):
            partes.append(f'--{frontera}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n{valor}\r\n'.encode())
        partes.append(f'--{frontera}\r\nContent-Disposition: form-data; name="photo"; filename="{Path(ruta).name}"\r\n'
                      f'Content-Type: image/{"png" if ruta.endswith(".png") else "jpeg"}\r\n\r\n'.encode() + datos + b"\r\n")
        partes.append(f"--{frontera}--\r\n".encode())
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendPhoto", data=b"".join(partes),
                                     headers={"Content-Type": f"multipart/form-data; boundary={frontera}"})
        try:
            urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            self.log(f"telegram: no se pudo enviar la foto ({type(e).__name__})")

    def enviar_documento(self, ruta: str, pie: str = "") -> bool:
        """Manda cualquier archivo (PDF, Word, zip…) al móvil. Telegram admite hasta 50 MB."""
        if not (self.activo and self.dueno):
            return False
        frontera = uuid.uuid4().hex
        partes = []
        for nombre, valor in (("chat_id", str(self.dueno)), ("caption", pie[:1000])):
            partes.append(f'--{frontera}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n{valor}\r\n'.encode())
        nombre_arch = Path(ruta).name.replace('"', "")
        partes.append(f'--{frontera}\r\nContent-Disposition: form-data; name="document"; filename="{nombre_arch}"\r\n'
                      f'Content-Type: application/octet-stream\r\n\r\n'.encode() + Path(ruta).read_bytes() + b"\r\n")
        partes.append(f"--{frontera}--\r\n".encode())
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendDocument", data=b"".join(partes),
                                     headers={"Content-Type": f"multipart/form-data; boundary={frontera}"})
        try:
            urllib.request.urlopen(req, timeout=180).read()
            return True
        except Exception as e:
            self.log(f"telegram: no se pudo enviar el archivo ({type(e).__name__})")
            return False

    def _descargar(self, file_id: str, carpeta: Path | None = None, nombre: str | None = None) -> Path:
        info = self._api("getFile", {"file_id": file_id})["result"]
        carpeta = carpeta or TMP
        carpeta.mkdir(parents=True, exist_ok=True)
        sufijo = Path(info["file_path"]).suffix or ".oga"
        destino = carpeta / (nombre or f"tg_{file_id[-12:]}{sufijo}")
        if destino.exists() and nombre:                 # no machacar un archivo con el mismo nombre
            destino = carpeta / f"{destino.stem}_{int(time.time())}{destino.suffix}"
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=60) as r:
            destino.write_bytes(r.read())
        return destino

    # ---------- confirmaciones ("¿apago el ordenador?")
    def preguntar_si(self, accion: str, espera: float = 90, pregunta: str | None = None) -> bool:
        self.respuestas = queue.Queue()
        self.enviar((pregunta or f"Voy a {accion}. ¿Lo confirmas?") + " Responde «sí» o «no».")
        try:
            resp = self.respuestas.get(timeout=espera).strip().lower()
        except queue.Empty:
            self.enviar("Sin respuesta: no hago nada.")
            return False
        finally:
            self.respuestas = None
        return resp.strip(" .!¡") in ("sí", "si", "s", "vale", "confirmo", "adelante", "hazlo", "ok", "yes", "👍")

    # ---------- bucles
    def arrancar(self) -> None:
        if not self.activo:
            return
        threading.Thread(target=self._sondear, daemon=True).start()
        threading.Thread(target=self._trabajar, daemon=True).start()
        if self.dueno:
            self.enviar("🟢 Jarvis en línea.")
        else:
            self.codigo = f"{random.randint(1000, 9999)}"
            self.log(f"telegram: sin vincular. Código de vinculación: {self.codigo}")

    def anunciar_codigo(self) -> None:
        """Se llama después del saludo: dice el código en voz alta (solo hasta que se vincula)."""
        if self.activo and not self.dueno and self.codigo:
            cifras = " ".join(self.codigo)
            self.decir(f"Telegram está listo para vincularse. Envía a tu bot el código {cifras}.")

    def _sondear(self) -> None:
        espera = 5
        while True:
            try:
                r = self._api("getUpdates", {"offset": self.offset, "timeout": 50,
                                             "allowed_updates": json.dumps(["message"])}, timeout=65)
                espera = 5
                for upd in r.get("result", []):
                    self.offset = upd["update_id"] + 1
                    self._recibir(upd.get("message") or {})
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.log("telegram: el token no es válido. Revisa ~/jarvis/telegram.json")
                    return
                time.sleep(espera)
                espera = min(espera * 2, 60)     # tras un corte, como mucho 1 minuto
            except Exception:
                time.sleep(espera)                       # sin internet: reintenta con calma
                espera = min(espera * 2, 60)     # tras un corte, como mucho 1 minuto

    def _recibir(self, msg: dict) -> None:
        chat = (msg.get("chat") or {}).get("id")
        texto = (msg.get("text") or "").strip()
        if not chat:
            return
        if not self.dueno:                            # vinculación
            if self.codigo and texto == self.codigo:
                self.dueno = chat
                self.cfg["dueno"] = chat
                guardar_config(self.cfg)
                self.log(f"telegram: vinculado con el chat {chat}")
                self.enviar("✅ Vinculado. Ya puedes darme órdenes por aquí: escribe o manda una nota de voz.\n"
                            "Ejemplos: «qué recordatorios tengo», «cómo va el ordenador», «haz una captura», "
                            "«recuérdame en 20 minutos sacar la ropa», «apaga el ordenador».")
                self.decir("Telegram vinculado.", susurro=False)
            return
        if chat != self.dueno:
            return                                    # desconocidos: ni respuesta
        if "photo" in msg:                             # Telegram manda varios tamaños: el último es el mayor
            self.ordenes.put(("foto", (msg["photo"][-1]["file_id"], msg.get("caption", ""), None)))
            return
        if "document" in msg:
            d = msg["document"]
            self.ordenes.put(("documento", (d["file_id"], msg.get("caption", ""), d.get("file_name"))))
            return
        if "voice" in msg or "audio" in msg:
            self.ordenes.put(("voz", (msg.get("voice") or msg.get("audio"))["file_id"]))
            return
        if not texto:
            return
        if self.respuestas is not None:               # estamos esperando un "sí/no"
            self.respuestas.put(texto)
            return
        self.ordenes.put(("texto", texto))

    def _trabajar(self) -> None:
        while True:
            tipo, valor = self.ordenes.get()
            try:
                if tipo in ("foto", "documento"):
                    file_id, pie, nombre = valor
                    es_foto = tipo == "foto" or (nombre or "").lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                    sub = "PICTURES" if es_foto else "DOWNLOAD"
                    carpeta = Path(subprocess.run(["xdg-user-dir", sub], capture_output=True, text=True).stdout.strip()
                                   or Path.home()) / "Telegram"
                    if tipo == "foto":
                        nombre = f"Foto_{time.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
                    ruta = self._descargar(file_id, carpeta, nombre)
                    self.log(f"telegram: recibido {ruta}")
                    aviso = self.al_recibir_archivo(ruta, es_foto) if self.al_recibir_archivo else ""
                    self.enviar(f"📥 Guardado en {carpeta.parent.name}/Telegram/{ruta.name}. {aviso}".strip())
                    if pie.strip():                   # si la foto lleva texto, se trata como una orden
                        r = self.procesar(pie.strip())
                        self.enviar(r.get("texto") or "Hecho.")
                    continue
                if tipo == "voz":
                    if not self.transcribir:
                        self.enviar("No puedo escuchar notas de voz ahora mismo.")
                        continue
                    ruta = self._descargar(valor)
                    texto = self.transcribir(str(ruta)).strip()
                    self.log(f"telegram: nota de voz → {texto!r}")
                    ruta.unlink(missing_ok=True)
                    if not texto:
                        self.enviar("No he entendido la nota de voz.")
                        continue
                    self.enviar(f"🎤 «{texto}»")
                else:
                    texto = valor
                if texto in ("/start", "/ayuda", "ayuda"):
                    self.enviar("Soy Jarvis. Escríbeme lo mismo que me dirías en voz alta (sin decir «Jarvis»).")
                    continue
                r = self.procesar(texto)
                if r.get("archivo") and str(r["archivo"]).lower().endswith((".png", ".jpg", ".jpeg")):
                    self.enviar_foto(r["archivo"], r.get("texto", ""))
                elif r.get("archivo") and Path(r["archivo"]).is_file():
                    if not self.enviar_documento(r["archivo"], r.get("texto", "")):
                        self.enviar(r.get("texto") or "Hecho.")
                else:
                    self.enviar(r.get("texto") or "Hecho.")
                if r.get("despues"):
                    time.sleep(1)
                    r["despues"]()
            except Exception as e:
                self.log(f"telegram: error procesando orden: {e!r}")
                self.enviar("Ha habido un error con esa orden.")
