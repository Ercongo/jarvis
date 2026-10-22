"""
El móvil, con KDE Connect (Android: todo; iPhone: lo que permite su app, sobre todo mandar archivos y el portapapeles).

  "dónde está mi móvil", "haz sonar el móvil"            → suena aunque esté en silencio
  "cuánta batería tiene el móvil"
  "manda la foto / el archivo / la canción al móvil"     → lo último que ha hecho el asistente (o el que nombres)
  "manda un sms a Ana: llego en 10 minutos"              → con el número de la memoria («el móvil de Ana es…»)
  "qué avisos tengo en el móvil", "léeme los whatsapps"  → los avisos del móvil (WhatsApp, Telegram, llamadas…)
  "contesta a Ana: vale, ahí estaré"                     → responde al aviso (si la app lo permite, como WhatsApp)
  "escribe a Ana por whatsapp: …"                        → WhatsApp Web con el mensaje puesto (tú pulsas enviar)
  Avisos nuevos del móvil → los dice (respeta «no me molestes»)

Para emparejarlo: instalar KDE Connect en el PC (sudo apt install kdeconnect) y en el móvil (Play Store / App Store),
misma wifi, y aceptar en los dos. La configuración del asistente lo guía.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable

from herramientas import abrir_web, normalizar
from sistema import Respuesta

DBUS = "org.kde.kdeconnect"
RAIZ = "/modules/kdeconnect"


def _gdbus(objeto: str, metodo: str, *args: str, timeout: int = 6) -> str:
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", DBUS, "--object-path", objeto,
                            "--method", metodo, *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _propiedad(objeto: str, interfaz: str, nombre: str) -> str:
    return _gdbus(objeto, "org.freedesktop.DBus.Properties.Get", interfaz, nombre)


def _valor(salida: str):
    """'(<85>,)' → 85; "(<'Pixel 7'>,)" → 'Pixel 7'; '(<true>,)' → True."""
    m = re.match(r"^\(<(.*)>,\)$", salida.strip())
    if not m:
        return None
    v = m.group(1).strip()
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    m2 = re.fullmatch(r"'(.*)'", v, re.S)
    return m2.group(1) if m2 else v


def disponible() -> bool:
    return bool(shutil.which("kdeconnect-cli"))


def dispositivos() -> list[dict]:
    """Móviles emparejados y alcanzables: [{id, nombre}]."""
    if not disponible():
        return []
    try:
        r = subprocess.run(["kdeconnect-cli", "-a", "--id-name-only"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return []
    fuera = []
    for linea in r.stdout.splitlines():
        partes = linea.strip().split(" ", 1)
        if len(partes) == 2 and re.fullmatch(r"[\w-]{6,}", partes[0]):
            fuera.append({"id": partes[0], "nombre": partes[1]})
    return fuera


def _cli(dispositivo: str, *args: str) -> bool:
    try:
        return subprocess.run(["kdeconnect-cli", "-d", dispositivo, *args], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def bateria(dispositivo: str) -> tuple[int | None, bool | None]:
    obj = f"{RAIZ}/devices/{dispositivo}/battery"
    carga = _valor(_propiedad(obj, f"{DBUS}.device.battery", "charge"))
    cargando = _valor(_propiedad(obj, f"{DBUS}.device.battery", "isCharging"))
    return (carga if isinstance(carga, int) else None), (cargando if isinstance(cargando, bool) else None)


def avisos(dispositivo: str) -> list[dict]:
    """Avisos que hay ahora en el móvil: [{id, app, titulo, texto, contestable}]."""
    base = f"{RAIZ}/devices/{dispositivo}/notifications"
    ids = re.findall(r"'([^']+)'", _gdbus(base, f"{DBUS}.device.notifications.activeNotifications"))
    fuera = []
    for nid in ids[:30]:
        obj = f"{base}/{nid}"
        interfaz = f"{DBUS}.device.notifications.notification"
        app = _valor(_propiedad(obj, interfaz, "appName")) or ""
        titulo = _valor(_propiedad(obj, interfaz, "title")) or ""
        texto = _valor(_propiedad(obj, interfaz, "text")) or ""
        resp = _valor(_propiedad(obj, interfaz, "replyId")) or ""
        fuera.append({"id": nid, "app": str(app), "titulo": str(titulo), "texto": str(texto), "contestable": bool(resp)})
    return fuera


def contestar(dispositivo: str, aviso_id: str, mensaje: str) -> bool:
    obj = f"{RAIZ}/devices/{dispositivo}/notifications/{aviso_id}"
    return bool(_gdbus(obj, f"{DBUS}.device.notifications.notification.sendReply", mensaje))


def numero_de(nombre: str, memoria: list[dict]) -> str | None:
    """«el móvil de Ana es 612 34 56 78» en la memoria → +34612345678."""
    n = normalizar(nombre)
    for d in memoria:
        t = str(d.get("dato", ""))
        if n and n in normalizar(t):
            m = re.search(r"(\+?\d[\d \-.]{7,}\d)", t)
            if m:
                num = re.sub(r"[ \-.]", "", m.group(1))
                if not num.startswith("+") and len(num) == 9:
                    num = "+34" + num
                return num
    return None


def _hablable(a: dict) -> str:
    app = {"com.whatsapp": "WhatsApp", "org.telegram.messenger": "Telegram"}.get(a["app"], a["app"])
    quien = a["titulo"].strip()
    texto = a["texto"].strip()
    return f"{app}: {quien}" + (f", «{texto[:160]}»" if texto else "")


class Movil:
    def __init__(self, decir: Callable[..., None], log=print, memoria: Callable[[], list[dict]] | None = None,
                 ultimo_archivo: Callable[[], Path | None] | None = None, puede_hablar: Callable[[str], bool] | None = None,
                 es_telegram: Callable[[], bool] | None = None, confirmar: Callable[[str], bool] | None = None):
        self.decir = decir
        self.confirmar = confirmar or (lambda pregunta: True)
        self.log = log
        self.memoria = memoria or (lambda: [])
        self.ultimo_archivo = ultimo_archivo or (lambda: None)
        self.puede_hablar = puede_hablar or (lambda t: True)
        self.es_telegram = es_telegram or (lambda: False)
        self._vistos: set[str] = set()
        self._ultimos: list[dict] = []
        self._parar = threading.Event()
        if disponible():
            threading.Thread(target=self._vigilar, daemon=True).start()

    # ---------------------------------------------------------------- avisos nuevos
    def _vigilar(self) -> None:
        primera = True
        while not self._parar.wait(20):
            try:
                for d in dispositivos():
                    lista = avisos(d["id"])
                    nuevos = [a for a in lista if a["id"] not in self._vistos]
                    self._vistos.update(a["id"] for a in lista)
                    if primera:                          # lo que ya estaba al arrancar no se anuncia
                        continue
                    for a in nuevos[:3]:
                        if not (a["titulo"] or a["texto"]):
                            continue
                        self._ultimos = ([a] + self._ultimos)[:20]
                        texto = "En el móvil, " + _hablable(a)
                        if self.puede_hablar(texto):
                            self.decir(texto)
                primera = False
            except Exception as e:
                self.log(f"móvil: {e!r}")

    def _uno(self) -> dict | None:
        ds = dispositivos()
        return ds[0] if ds else None

    # ---------------------------------------------------------------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|y)[ ,]+", "", t)
        menciona = re.search(r"\b(movil|telefono|celular|iphone|android)\b", t)
        whatsapp = re.search(r"\bwh?ats?app?s?\b|\bwasaps?\b|\bguasaps?\b", t)

        # WhatsApp asistido (no hace falta KDE Connect)
        m = re.match(r"(?:escribe|escribele|manda(?:le)?|envia(?:le)?)(?: un mensaje)? a (.+?) (?:por|en) "
                     r"(?:wh?ats?app?|wasap|guasap)[,:]? (.+)$", t)
        quien = lambda g: " ".join(w.capitalize() for w in g.split())
        if m:
            num = numero_de(m.group(1), self.memoria())
            texto = re.split(r"(?i)[,:]\s*", peticion, maxsplit=1)[-1] if ":" in peticion else m.group(2)
            if not num:
                return Respuesta(f"No tengo el número de {quien(m.group(1))}. Dime, por ejemplo: «el móvil de "
                                 f"{quien(m.group(1))} es 612 345 678» y lo apunto.")
            url = "https://web.whatsapp.com/send?phone=" + num.lstrip("+") + "&text=" + urllib.parse.quote(texto)
            abrir_web(url)
            return Respuesta(f"Te dejo el mensaje a {quien(m.group(1))} escrito en WhatsApp. Revísalo y pulsa enviar.")

        if not (menciona or whatsapp or re.search(r"\bsms\b", t) or re.match(r"(?:contesta|responde)(?:le)? a ", t)):
            return None
        quien = lambda g: " ".join(w.capitalize() for w in g.split())
        if not disponible():
            return Respuesta("Para eso tengo que estar conectado a tu móvil con KDE Connect. Ábreme la configuración "
                             "y te guío: son dos minutos.")
        d = self._uno()
        if not d:
            return Respuesta("No veo tu móvil: comprueba que tiene KDE Connect abierto y está en la misma wifi.")

        if re.search(r"\b(donde esta|busca|encuentra|haz sonar|suena|que suene|llama a)\b.*\b(movil|telefono|iphone)\b", t):
            ok = _cli(d["id"], "--ring")
            return Respuesta(f"Haciendo sonar {d['nombre']}." if ok else "No he podido hacerlo sonar.")
        if re.search(r"\bbateria\b", t):
            carga, cargando = bateria(d["id"])
            if carga is None:
                return Respuesta("Tu móvil no me dice la batería.")
            return Respuesta(f"{d['nombre']} tiene un {carga} por ciento" + (", y está cargando." if cargando else "."))
        m = re.match(r"(?:manda|envia|pasa)(?:me)? (?:la |el |esta |este |esa |ese )?(.+?) al (?:movil|telefono|iphone)$", t)
        if m:
            ruta = self.ultimo_archivo()
            pedido = m.group(1)
            if pedido not in ("foto", "imagen", "archivo", "documento", "cancion", "video", "ultimo", "ultima") and ruta \
                    and normalizar(pedido) not in normalizar(ruta.name):
                ruta = None
            if not ruta or not ruta.exists():
                return Respuesta("¿Qué archivo te mando? Dime, por ejemplo, «manda la foto que has hecho al móvil».")
            ok = _cli(d["id"], "--share", str(ruta))
            return Respuesta(f"Mandado {ruta.name} a {d['nombre']}." if ok else "No he podido mandarlo.")
        m = re.match(r"(?:manda|envia)(?:le)? un (?:sms|mensaje de texto) a (.+?)[,:] (.+)$", t)
        if m:
            num = numero_de(m.group(1), self.memoria())
            if not num:
                return Respuesta(f"No tengo el número de {quien(m.group(1))}.")
            texto = peticion.split(":", 1)[-1].strip() if ":" in peticion else m.group(2)
            if not self.confirmar(f"Mando a {quien(m.group(1))} este SMS: «{texto}». ¿Lo confirmas?"):
                return Respuesta("Vale, no lo mando.")
            ok = _cli(d["id"], "--send-sms", texto, "--destination", num)
            return Respuesta(f"SMS enviado a {quien(m.group(1))}." if ok else "No he podido mandar el SMS (en iPhone no se puede).")
        if re.search(r"\b(avisos|notificaciones|mensajes|whatsapps?|wasaps?)\b", t) and \
                re.search(r"\b(que|lee|leeme|dime|tengo|hay)\b", t):
            lista = [a for a in avisos(d["id"]) if a["titulo"] or a["texto"]]
            if whatsapp:
                lista = [a for a in lista if "whatsapp" in a["app"].lower()]
            if not lista:
                return Respuesta("No tienes avisos " + ("de WhatsApp " if whatsapp else "") + "en el móvil.")
            self._ultimos = lista
            return Respuesta(f"Tienes {len(lista)}: " + "; ".join(_hablable(a) for a in lista[:5]) + ".")
        m = re.match(r"(?:contesta|responde)(?:le)? a (.+?)[,:] (.+)$", t)
        if m:
            quien = normalizar(m.group(1))
            candidatos = [a for a in (self._ultimos or avisos(d["id"])) if a["contestable"] and quien in normalizar(a["titulo"])]
            if not candidatos:
                return Respuesta(f"No tengo ningún mensaje de {quien(m.group(1))} al que pueda contestar.")
            texto = peticion.split(":", 1)[-1].strip() if ":" in peticion else m.group(2)
            if not self.confirmar(f"Contesto a {candidatos[0]['titulo']}: «{texto}». ¿Lo confirmas?"):
                return Respuesta("Vale, no contesto.")
            ok = contestar(d["id"], candidatos[0]["id"], texto)
            return Respuesta(f"Contestado a {candidatos[0]['titulo']}." if ok else "No he podido contestar.")
        return None
