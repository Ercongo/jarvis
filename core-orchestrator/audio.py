"""
Salida de sonido para el asistente: por dónde sale (monitor HDMI, jack de auriculares / altavoces auxiliares,
altavoces del portátil), cambiarla y revisar por qué no se oye.

  «pon el sonido por el monitor»            «saca el audio por los altavoces auxiliares»
  «pon el sonido por los altavoces del portátil»   «por dónde sale el sonido»
  «revisa el audio» / «no se oye nada»      (diagnóstico y arreglo de lo que se pueda: silencio, volumen, puerto)

Funciona con PipeWire o PulseAudio a través de pactl (y amixer para los interruptores de la tarjeta).
El volumen sigue en sistema.py: aquí no se toca salvo que esté casi a cero al revisar el audio.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from herramientas import normalizar


@dataclass
class Respuesta:
    texto: str
    susurro: bool | None = None
    despues: object = None
    archivo: str | None = None


ENTORNO = {**os.environ, "LC_ALL": "C", "LANG": "C"}
if "XDG_RUNTIME_DIR" not in ENTORNO:
    ENTORNO["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

# destino pedido → qué buscar en las salidas
DESTINOS = (
    ("hdmi", r"\b(monitor|hdmi|pantalla|tele|television|display ?port)\b", "el monitor (HDMI)"),
    ("jack", r"\b(auriculares|cascos|jack|minijack|auxiliar\w*|externos?|enchufados?)\b", "el jack (auriculares o altavoces auxiliares)"),
    ("interno", r"\b(altavo\w+ (del|de el|internos?|integrados?)( portatil| ordenador| pc)?|portatil|internos?)\b",
     "los altavoces del portátil"),
)
RE_CAMBIAR = re.compile(r"\b(pon|saca|cambia|manda|envia|pasa|quiero|haz que|que)\b.*\b(sonido|audio|salida|sonar|suene|oiga)\b"
                        r"|\b(sonido|audio|salida de sonido)\b.*\b(por|en) (el|los|la|las)\b")
RE_DONDE = re.compile(r"\b(por )?donde (sale|esta saliendo|suena)\b.*\b(sonido|audio)\b|\b(que|cual) (es la )?salida de (sonido|audio)\b"
                      r"|\bsalidas de (sonido|audio)\b")
RE_REVISAR = re.compile(r"\b(revisa|comprueba|arregla|mira|diagnostica)\w*\b.*\b(audio|sonido|altavo\w+)\b"
                        r"|\bno (se oye|suena|sale el (sonido|audio)|oigo|tengo sonido|hay sonido)\b"
                        r"|\b(audio|sonido)\b.*\bno (sale|funciona|va|se oye)\b")


def _pactl(*args: str, timeout: int = 6) -> str:
    try:
        r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout, env=ENTORNO)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def salidas() -> list[dict]:
    """Las salidas de sonido con sus puertos: [{nombre, descripcion, puertos:[{nombre, desc, disponible}], activo,
    silencio, volumen, tarjeta}]."""
    try:
        datos = json.loads(_pactl("--format=json", "list", "sinks") or "[]")
    except ValueError:
        datos = []
    defecto = _pactl("get-default-sink").strip()
    res = []
    for s in datos:
        vols = [int(str(v.get("value_percent", "0")).rstrip("%") or 0) for v in (s.get("volume") or {}).values()]
        res.append({
            "nombre": s.get("name", ""),
            "descripcion": s.get("description", ""),
            "puertos": [{"nombre": p.get("name", ""), "desc": p.get("description", ""),
                         "disponible": p.get("availability", "") != "not available"} for p in s.get("ports", [])],
            "activo": s.get("active_port") or "",
            "silencio": bool(s.get("mute")),
            "volumen": max(vols) if vols else None,
            "tarjeta": (s.get("properties") or {}).get("alsa.card"),
            "defecto": s.get("name") == defecto,
        })
    return res


def _tipo(salida: dict, puerto: str = "") -> str:
    n = (salida["nombre"] + " " + (puerto or salida["activo"])).lower()
    if "hdmi" in n or "displayport" in n:
        return "hdmi"
    if "headphone" in n or "line-out" in n or "lineout" in n:
        return "jack"
    if "speaker" in n:
        return "interno"
    if "bluez" in n:
        return "bluetooth"
    if "usb" in n:
        return "usb"
    return "otro"


def _nombre_humano(tipo: str, salida: dict) -> str:
    return {"hdmi": "el monitor por HDMI", "jack": "el jack (auriculares o altavoces auxiliares)",
            "interno": "los altavoces del portátil", "bluetooth": "el dispositivo Bluetooth",
            "usb": "el dispositivo USB"}.get(tipo, salida["descripcion"] or salida["nombre"])


def _mover_flujos(destino: str) -> None:
    for linea in _pactl("list", "short", "sink-inputs").splitlines():
        ident = linea.split("\t", 1)[0].strip()
        if ident.isdigit():
            _pactl("move-sink-input", ident, destino)


def _quitar_silencio_tarjeta(tarjeta, tipo: str = "") -> list[str]:
    """Los interruptores de la propia tarjeta (amixer): a veces Master o Headphone quedan silenciados aunque
    PipeWire diga que no. Solo los de la salida en uso: con algo en el jack, «Speaker» va apagado a propósito."""
    if tarjeta is None or not shutil.which("amixer"):
        return []
    arreglados = []
    propios = {"jack": ("Headphone", "Line Out", "Front"), "interno": ("Speaker",)}.get(tipo, ())
    for control in ("Master", "PCM", *propios):
        try:
            r = subprocess.run(["amixer", "-c", str(tarjeta), "sget", control], capture_output=True, text=True,
                               timeout=4, env=ENTORNO)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and "[off]" in r.stdout:
            subprocess.run(["amixer", "-q", "-c", str(tarjeta), "sset", control, "unmute"], capture_output=True,
                           timeout=4, env=ENTORNO)
            arreglados.append(control)
    return arreglados


class Audio:
    def __init__(self, log=print):
        self.log = log

    @property
    def disponible(self) -> bool:
        return bool(shutil.which("pactl"))

    # ------------------------------------------------------------------ órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .?¿!¡")
        if "volumen" in t and not re.search(r"\b(salida|por donde)\b", t):
            return None                                    # el volumen lo lleva sistema.py
        if RE_REVISAR.search(t):
            return self.revisar() if self.disponible else Respuesta("No encuentro pactl para revisar el sonido.")
        if RE_DONDE.search(t):
            return self.donde() if self.disponible else Respuesta("No encuentro pactl para ver el sonido.")
        if RE_CAMBIAR.search(t):
            for tipo, patron, _ in DESTINOS:
                if re.search(patron, t):
                    return self.cambiar(tipo) if self.disponible else Respuesta("No encuentro pactl para cambiar el sonido.")
        return None

    def donde(self) -> Respuesta:
        ss = salidas()
        if not ss:
            return Respuesta("No encuentro ninguna salida de sonido.")
        d = next((s for s in ss if s["defecto"]), ss[0])
        texto = f"El sonido sale por {_nombre_humano(_tipo(d), d)}, al {d['volumen']} %"
        texto += ", pero está silenciado." if d["silencio"] else "."
        otras = []
        for s in ss:
            for p in s["puertos"]:
                tp = _tipo(s, p["nombre"])
                if p["disponible"] and not (s is d and p["nombre"] == d["activo"]):
                    otras.append(_nombre_humano(tp, s))
        if otras:
            texto += " También puedo ponerlo por " + " o por ".join(dict.fromkeys(otras)) + "."
        return Respuesta(texto)

    def cambiar(self, tipo: str) -> Respuesta:
        ss = salidas()
        candidatos = []                       # (salida, puerto) del tipo pedido; los disponibles primero
        for s in ss:
            if s["puertos"]:
                for p in s["puertos"]:
                    if _tipo(s, p["nombre"]) == tipo:
                        candidatos.append((s, p))
            elif _tipo(s) == tipo:
                candidatos.append((s, None))
        if not candidatos:
            nombre = next(d[2] for d in DESTINOS if d[0] == tipo)
            hay = ", ".join(dict.fromkeys(_nombre_humano(_tipo(s, p["nombre"]), s) for s in ss for p in s["puertos"])) or "ninguna"
            return Respuesta(f"No encuentro {nombre} como salida de sonido. Las que hay: {hay}.")
        candidatos.sort(key=lambda c: not (c[1] is None or c[1]["disponible"]))
        s, p = candidatos[0]
        if p is not None and not p["disponible"]:
            if tipo == "interno":
                return Respuesta("Los altavoces del portátil están desactivados porque hay algo enchufado en el jack "
                                 "de auriculares. Desenchúfalo y sonarán por los altavoces del portátil.")
            if tipo == "jack":
                return Respuesta("No hay nada enchufado en el jack de auriculares. Conecta ahí los altavoces "
                                 "auxiliares o los cascos y dímelo otra vez.")
            if tipo == "hdmi":
                return Respuesta("El monitor por HDMI no aparece conectado ahora mismo, o no tiene altavoces.")
        _pactl("set-default-sink", s["nombre"])
        if p is not None and s["activo"] != p["nombre"]:
            _pactl("set-sink-port", s["nombre"], p["nombre"])
        _pactl("set-sink-mute", s["nombre"], "0")
        _mover_flujos(s["nombre"])
        self.log(f"audio: salida → {s['nombre']} {p['nombre'] if p else ''}")
        aviso = ""
        if s["volumen"] is not None and s["volumen"] < 15:
            _pactl("set-sink-volume", s["nombre"], "50%")
            aviso = " Estaba casi sin volumen; lo he puesto al 50 %."
        extra = " Si el monitor no tiene altavoces, no se oirá: dime «pon el sonido por los auriculares»." if tipo == "hdmi" else ""
        return Respuesta(f"Hecho, el sonido sale ahora por {_nombre_humano(tipo, s)}.{aviso}{extra}")

    def revisar(self) -> Respuesta:
        ss = salidas()
        if not ss:
            return Respuesta("No encuentro ninguna salida de sonido: puede que el servidor de sonido no esté en marcha. "
                             "Prueba a reiniciar el asistente o el portátil.")
        d = next((s for s in ss if s["defecto"]), ss[0])
        hecho, notas = [], []
        if d["silencio"]:
            _pactl("set-sink-mute", d["nombre"], "0")
            hecho.append("le he quitado el silencio")
        if d["volumen"] is not None and d["volumen"] < 15:
            _pactl("set-sink-volume", d["nombre"], "60%")
            hecho.append("he subido el volumen al 60 %")
        activo = next((p for p in d["puertos"] if p["nombre"] == d["activo"]), None)
        if activo is not None and not activo["disponible"]:
            otro = next((p for p in d["puertos"] if p["disponible"]), None)
            if otro:
                _pactl("set-sink-port", d["nombre"], otro["nombre"])
                hecho.append(f"he cambiado a {_nombre_humano(_tipo(d, otro['nombre']), d)}, porque la salida de antes no estaba conectada")
        tarjeta = _quitar_silencio_tarjeta(d["tarjeta"], _tipo(d))
        if tarjeta:
            hecho.append("he activado los interruptores de la tarjeta de sonido que estaban apagados (" + ", ".join(tarjeta) + ")")
        _mover_flujos(d["nombre"])
        tipo = _tipo(d)
        texto = f"El sonido sale por {_nombre_humano(tipo, d)}"
        texto += f" al {d['volumen'] if d['volumen'] is not None else '?'} %. "
        if hecho:
            texto += "Lo he revisado: " + "; ".join(hecho) + ". "
        else:
            texto += "No veo nada mal: no está silenciado y el volumen está bien. "
        if tipo == "jack":
            notas.append("Si son altavoces auxiliares, comprueba que estén encendidos, con su volumen subido y bien "
                         "metidos en el jack hasta el fondo")
            if any(p["nombre"].endswith("speaker") for p in d["puertos"]):
                notas.append("mientras haya algo enchufado en el jack, los altavoces del portátil no suenan")
        elif tipo == "hdmi":
            notas.append("ahora sale por el monitor; si el monitor no tiene altavoces, dime «pon el sonido por los "
                         "auriculares» o «por los altavoces del portátil»")
        if notas:
            texto += ". ".join(n[0].upper() + n[1:] for n in notas) + "."
        return Respuesta(texto.strip())


if __name__ == "__main__":                 # python audio.py  → diagnóstico sin cambiar nada
    for s in salidas():
        print(("* " if s["defecto"] else "  ") + f"{s['nombre']} ({s['descripcion']}) vol={s['volumen']} mute={s['silencio']} "
              f"tarjeta={s['tarjeta']} activo={s['activo']}")
        for p in s["puertos"]:
            print(f"      {_tipo(s, p['nombre']):9} {p['nombre']} {'disponible' if p['disponible'] else 'NO disponible'}")
