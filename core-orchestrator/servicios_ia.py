"""
Herramientas grandes que se encienden solo cuando hacen falta (para no gastar la memoria del portátil):

  Open WebUI (chat web tipo ChatGPT con las IA del asistente)
      «abre el chat web», «abre open webui»  → lo enciende y abre http://127.0.0.1:8080
      «cierra el chat web»                   → lo apaga
  ComfyUI (imágenes en este equipo, sin internet; con el procesador, ~1 minuto por imagen)
      «crea una imagen en local de …», «hazme sin internet una imagen de …»
      También es el último recurso de creativo.py si los servicios de imágenes en internet fallan.
      Se apaga solo a los 10 minutos sin usarlo.
  Linutil (caja de herramientas de Linux de Chris Titus, la versión para Linux de winutil)
      «abre la caja de herramientas de linux», «abre linutil» → en una terminal; lo que pide contraseña lo
      escribe usted allí.
  «qué herramientas de ia locales tienes» → qué está instalado.

Se instalan con ~/jarvis/instalar_open_webui.sh, ~/jarvis/instalar_comfyui.sh e ~/jarvis/instalar_linutil.sh.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from herramientas import abrir_web, carpeta_usuario, lanzar, normalizar
from sistema import Respuesta

HOME = Path.home()
WEBUI = "http://127.0.0.1:8080"
COMFY = "http://127.0.0.1:8188"
COMFY_DIR = HOME / ".local/share/comfyui/ComfyUI"
LINUTIL = HOME / ".local/bin/linutil"
APAGAR_COMFY_TRAS = 600


def _systemctl(*args: str) -> bool:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _instalado(servicio: str) -> bool:
    return (HOME / f".config/systemd/user/{servicio}.service").exists()


def _responde(url: str, timeout: float = 3) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _esperar(url: str, segundos: int) -> bool:
    fin = time.time() + segundos
    while time.time() < fin:
        if _responde(url):
            return True
        time.sleep(2)
    return False


# ================================================================ ComfyUI
_comfy_lock = threading.Lock()
_comfy_temporizador: list[threading.Timer | None] = [None]


def comfy_disponible() -> bool:
    return _instalado("comfyui") and (COMFY_DIR / "models/checkpoints/sd_turbo.safetensors").exists()


def _programar_apagado() -> None:
    if _comfy_temporizador[0]:
        _comfy_temporizador[0].cancel()
    t = threading.Timer(APAGAR_COMFY_TRAS, lambda: _systemctl("stop", "comfyui.service"))
    t.daemon = True
    t.start()
    _comfy_temporizador[0] = t


def _flujo(prompt: str, ancho: int, alto: int, semilla: int) -> dict:
    """SD-Turbo en un paso + decodificador TAESD: lo más rápido que hay para un procesador."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_turbo.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": ancho, "height": alto, "batch_size": 1}},
        "5": {"class_type": "SDTurboScheduler", "inputs": {"model": ["1", 0], "steps": 1, "denoise": 1.0}},
        "6": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "7": {"class_type": "SamplerCustom", "inputs": {
            "model": ["1", 0], "add_noise": True, "noise_seed": semilla, "cfg": 1.0, "positive": ["2", 0],
            "negative": ["3", 0], "sampler": ["6", 0], "sigmas": ["5", 0], "latent_image": ["4", 0]}},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": "taesd"}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["8", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "athena"}},
    }


def comfy_imagen(prompt: str, ancho: int, alto: int, destino: Path, semilla: int | None = None,
                 log=print) -> Path:
    """Genera la imagen con ComfyUI en este equipo. Ajusta el tamaño a lo que aguanta SD-Turbo (≤ 640 px)."""
    if not comfy_disponible():
        raise RuntimeError("ComfyUI no está instalado (bash ~/jarvis/instalar_comfyui.sh)")
    escala = min(1.0, 640 / max(ancho, alto))
    ancho, alto = (max(256, int(ancho * escala) // 64 * 64), max(256, int(alto * escala) // 64 * 64))
    with _comfy_lock:
        if not _responde(COMFY + "/system_stats"):
            _systemctl("start", "comfyui.service")
            if not _esperar(COMFY + "/system_stats", 240):
                raise RuntimeError("ComfyUI no arranca (mira: journalctl --user -u comfyui)")
        t0 = time.time()
        datos = json.dumps({"prompt": _flujo(prompt[:600], ancho, alto, semilla or random.randint(1, 2 ** 31)),
                            "client_id": "athena"}).encode()
        req = urllib.request.Request(COMFY + "/prompt", data=datos, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.load(r)["prompt_id"]
        salida = None
        while time.time() - t0 < 900:
            time.sleep(3)
            with urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=15) as r:
                h = json.load(r).get(pid)
            if not h:
                continue
            estado = (h.get("status") or {}).get("status_str")
            if estado == "error":
                raise RuntimeError("ComfyUI ha fallado al generar la imagen")
            for nodo in (h.get("outputs") or {}).values():
                if nodo.get("images"):
                    salida = nodo["images"][0]
                    break
            if salida:
                break
        if not salida:
            raise RuntimeError("ComfyUI tarda demasiado")
        q = urllib.parse.urlencode({"filename": salida["filename"], "subfolder": salida.get("subfolder", ""),
                                    "type": salida.get("type", "output")})
        with urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=60) as r:
            png = r.read()
        destino = destino.with_suffix(".png")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(png)
        log(f"comfyui: imagen {ancho}x{alto} en {time.time() - t0:.0f} s")
        _programar_apagado()
        return destino


# ================================================================ el módulo
class ServiciosIA:
    def __init__(self, log=print, decir: Callable[..., None] | None = None, traducir: Callable[[str], str] | None = None,
                 es_telegram: Callable[[], bool] | None = None, enviar_foto: Callable | None = None):
        self.log = log
        self.decir = decir or (lambda t: None)
        self.traducir = traducir or (lambda t: t)
        self.es_telegram = es_telegram or (lambda: False)
        self.enviar_foto = enviar_foto

    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)
        if re.search(r"\b(abre|arranca|enciende|pon|lanza)\w*\b.*\b(chat web|open ?web ?ui|openwebui|webui)\b", t):
            return self.abrir_webui()
        if re.search(r"\b(cierra|apaga|para|deten)\w*\b.*\b(chat web|open ?web ?ui|openwebui|webui)\b", t):
            _systemctl("stop", "open-webui.service")
            return Respuesta("Chat web apagado; así el portátil tiene más memoria libre.")
        m = re.match(r"^(?:crea|creame|haz|hazme|genera|generame|dibuja|dibujame|pinta|pintame)\s+(?:una |un )?"
                     r"(?:(?:imagen|foto|dibujo)\s+)?(?:en local|sin internet|con comfy ?ui|en el portatil|en este (?:equipo|ordenador))\s+"
                     r"(?:una |un )?(?:imagen |foto |dibujo )?(?:de |del |con |sobre )?(.+)$", t) or \
            re.match(r"^(?:crea|creame|haz|hazme|genera|generame|dibuja|dibujame|pinta|pintame)\s+(?:una |un )?"
                     r"(?:imagen|foto|dibujo)\s+(?:de |del |con |sobre )?(.+?)\s+(?:en local|sin internet|con comfy ?ui)$", t)
        if m:
            return self.imagen_local(m.group(1))
        if re.search(r"\b(apaga|cierra|para)\w*\b.*\bcomfy ?ui\b", t):
            _systemctl("stop", "comfyui.service")
            return Respuesta("ComfyUI apagado.")
        if re.search(r"\b(abre|lanza|arranca)\w*\b.*\b(linutil|caja de herramientas de linux|herramientas de chris titus|"
                     r"winutil)\b", t):
            return self.linutil("winutil" in t)
        if re.search(r"\bque (herramientas|programas) de ia (locales|en local|tienes instalad\w*)\b|\bque ia locales tienes\b", t):
            return self.estado()
        return None

    # ------------------------------------------------------------ Open WebUI
    def abrir_webui(self) -> Respuesta:
        if not _instalado("open-webui"):
            return Respuesta("El chat web (Open WebUI) no está instalado. Instálalo con: bash ~/jarvis/instalar_open_webui.sh")
        if _responde(WEBUI + "/health"):
            abrir_web(WEBUI)
            return Respuesta("Ahí tienes el chat web.")
        _systemctl("start", "open-webui.service")

        def hilo():
            if _esperar(WEBUI + "/health", 240):
                abrir_web(WEBUI)
                self.decir("Ya tienes el chat web abierto.")
            else:
                self.decir("El chat web no termina de arrancar. Mira el registro: journalctl --user -u open-webui.")
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta("Enciendo el chat web; tarda un minuto en arrancar y te lo abro.")

    # ------------------------------------------------------------ ComfyUI
    def imagen_local(self, que: str) -> Respuesta:
        if not comfy_disponible():
            return Respuesta("Para crear imágenes sin internet hace falta ComfyUI. Instálalo con: "
                             "bash ~/jarvis/instalar_comfyui.sh")
        tg = self.es_telegram()

        def hilo():
            try:
                prompt = self.traducir(que)
            except Exception:
                prompt = que
            nombre = re.sub(r"[^\w áéíóúñ-]", "", que)[:40].strip() or "Imagen local"
            destino = carpeta_usuario("PICTURES") / f"{nombre[:1].upper() + nombre[1:]} (local).png"
            try:
                ruta = comfy_imagen(prompt, 512, 512, destino, log=self.log)
            except Exception as e:
                self.log(f"servicios_ia: comfyui {e!r}")
                self.decir(f"No he podido hacer la imagen en local: {e}")
                return
            if tg and self.enviar_foto:
                self.enviar_foto(str(ruta), f"Hecha en el portátil, sin internet: {que}")
            else:
                try:
                    lanzar(["xdg-open", str(ruta)])
                except OSError:
                    pass
                self.decir("Ya tienes la imagen hecha en el portátil, sin internet.")
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta("La pinto aquí mismo, sin internet. Con el procesador tarda un minuto o dos.")

    # ------------------------------------------------------------ Linutil
    def linutil(self, pidio_winutil: bool) -> Respuesta:
        aviso = ("Winutil es solo para Windows; en Ubuntu uso su hermano Linutil, del mismo autor. " if pidio_winutil else "")
        if not LINUTIL.exists():
            return Respuesta(aviso + "Linutil no está instalado. Instálalo con: bash ~/jarvis/instalar_linutil.sh")
        terminal = shutil.which("ptyxis") or shutil.which("xfce4-terminal") or shutil.which("gnome-terminal") or shutil.which("xterm")
        if not terminal:
            return Respuesta(aviso + "No encuentro ninguna terminal para abrirlo.")
        if "ptyxis" in terminal:
            args = [terminal, "--new-window", "-x", str(LINUTIL)]
        elif "gnome-terminal" in terminal:
            args = [terminal, "--", str(LINUTIL)]
        else:
            args = [terminal, "-e", str(LINUTIL)]
        lanzar(args)
        return Respuesta(aviso + "Te abro Linutil en una terminal. Muévete con las flechas; lo que necesite contraseña "
                         "te la pedirá allí y la escribes tú.")

    def estado(self) -> Respuesta:
        partes = []
        partes.append("el chat web Open WebUI" + (" (encendido)" if _responde(WEBUI + "/health") else "")
                      if _instalado("open-webui") else "")
        partes.append("ComfyUI para imágenes sin internet" if comfy_disponible() else "")
        partes.append("Linutil" if LINUTIL.exists() else "")
        partes.append("OmniRoute" if _instalado("omniroute") else "")
        partes.append("Ollama con la IA local" if shutil.which("ollama") else "")
        hay = [p for p in partes if p]
        if not hay:
            return Respuesta("No tengo herramientas de IA locales instaladas todavía.")
        return Respuesta("Tengo instalado: " + ", ".join(hay) + ".")
