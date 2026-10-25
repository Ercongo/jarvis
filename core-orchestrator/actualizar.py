"""Actualizaciones de los componentes del propio asistente (lo del sistema, apt y snap, lo lleva mantenimiento.py).

- Paquetes de Python del entorno del asistente: se aplican solos los cambios menores (2.5.3 → 2.5.4); los de
  versión principal (opencv 4 → 5) solo se avisan, porque pueden romper cosas.
- OmniRoute (npm) y Ollama (GitHub): se compara la versión instalada con la última publicada.
- Antes de tocar el entorno de Python se copia entero y se prueba que todo carga (numpy, OpenCV, whisper, Piper…).
  Si algo falla, se vuelve a la copia. Se guardan las dos últimas copias.
- Cada semana lo comprueba solo y, si hay algo, te avisa por Telegram (no instala nada sin que lo pidas).

Órdenes: «busca actualizaciones del asistente», «actualiza el asistente» (con confirmación),
«qué versiones tienes».
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from herramientas import guardar_config, leer_config, normalizar
from perfil import INSTALACION
from sistema import Respuesta

VENV = INSTALACION / "venv"
COPIAS = INSTALACION / "copias"
NODO = Path.home() / ".local" / "node"
# no se tocan solos: fijados por otro paquete (kokoro-onnx pide phonemizer-fork==3.3.1) o delicados
FIJADOS = {"phonemizer-fork", "pip", "setuptools", "wheel"}
PRUEBA = """
import numpy, cv2, ctranslate2, av, onnxruntime, docx, openpyxl, pptx, ezdxf, pypdf, matplotlib, ddgs, bs4, piper
import gradio_client, huggingface_hub
from faster_whisper import WhisperModel
m = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=2)
segs, _ = m.transcribe(numpy.zeros(16000, dtype=numpy.float32), language="es")
list(segs)
print("ok")
"""


def _principal(v: str) -> str:
    return re.split(r"[.+]", v or "0")[0]


def _http_json(url: str, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "asistente", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Actualizador:
    def __init__(self, decir: Callable[..., None], confirmar: Callable[[str], bool], log=print,
                 avisar: Callable[[str], None] | None = None, es_telegram: Callable[[], bool] | None = None,
                 omni=None):
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.avisar = avisar or (lambda t: None)
        self.es_telegram = es_telegram or (lambda: False)
        self.omni = omni
        self._ocupado = threading.Lock()

    # ------------------------------------------------------------------ comprobar
    def _pip(self) -> tuple[list, list]:
        try:
            r = subprocess.run([str(VENV / "bin" / "pip"), "list", "--outdated", "--format=json"],
                               capture_output=True, text=True, timeout=180)
            datos = json.loads(r.stdout or "[]")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return [], []
        menores, mayores = [], []
        for d in datos:
            fila = (d["name"], d["version"], d["latest_version"])
            if d["name"].lower() in FIJADOS:
                continue
            (menores if _principal(d["version"]) == _principal(d["latest_version"]) else mayores).append(fila)
        return menores, mayores

    def _omniroute(self) -> tuple[str, str] | None:
        pkg = NODO / "lib" / "node_modules" / "omniroute" / "package.json"
        if not pkg.exists():
            return None
        try:
            actual = json.loads(pkg.read_text())["version"]
            ultima = _http_json("https://registry.npmjs.org/omniroute/latest")["version"]
        except (OSError, ValueError, KeyError):
            return None
        return (actual, ultima) if actual != ultima else None

    def _ollama(self) -> tuple[str, str] | None:
        if not shutil.which("ollama"):
            return None
        try:
            salida = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=15).stdout
            actual = re.findall(r"(\d+\.\d+\.\d+)", salida)[-1]
            ultima = _http_json("https://api.github.com/repos/ollama/ollama/releases/latest")["tag_name"].lstrip("v")
        except (OSError, IndexError, ValueError, KeyError, subprocess.TimeoutExpired):
            return None
        return (actual, ultima) if actual != ultima else None

    def comprobar(self) -> dict:
        menores, mayores = self._pip()
        info = {"pip_menores": menores, "pip_mayores": mayores, "omniroute": self._omniroute(),
                "ollama": self._ollama(), "cuando": dt.datetime.now().isoformat(timespec="minutes")}
        guardar_config(componentes_comprobados=info["cuando"])
        return info

    @staticmethod
    def resumen(info: dict) -> str:
        partes = []
        if info["pip_menores"]:
            partes.append(f"{len(info['pip_menores'])} paquetes de Python con mejoras menores")
        if info["omniroute"]:
            partes.append(f"OmniRoute {info['omniroute'][0]} → {info['omniroute'][1]}")
        if info["ollama"]:
            partes.append(f"Ollama {info['ollama'][0]} → {info['ollama'][1]}")
        texto = ("Hay actualizaciones del asistente: " + "; ".join(partes) + ". Dime «actualiza el asistente» y "
                 "las instalo con copia de seguridad.") if partes else "El asistente está al día."
        if info["pip_mayores"]:
            texto += (" Hay además versiones nuevas grandes que no instalo solas porque pueden romper cosas: " +
                      ", ".join(f"{n} {a} → {b}" for n, a, b in info["pip_mayores"][:4]) + ".")
        return texto

    # ------------------------------------------------------------------ aplicar
    def _probar_entorno(self) -> bool:
        try:
            r = subprocess.run([str(VENV / "bin" / "python"), "-c", PRUEBA], capture_output=True, text=True,
                               timeout=300, cwd=str(INSTALACION / "core-orchestrator"))
            return r.returncode == 0 and "ok" in r.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _actualizar_pip(self, menores: list) -> str:
        if not menores:
            return ""
        COPIAS.mkdir(parents=True, exist_ok=True)
        copia = COPIAS / f"venv_antes_{dt.datetime.now():%Y%m%d_%H%M}"
        self.log(f"actualizar: copia del entorno en {copia}")
        subprocess.run(["cp", "-a", str(VENV), str(copia)], check=True, timeout=1800)
        nombres = [n for n, _, _ in menores]
        r = subprocess.run([str(VENV / "bin" / "pip"), "install", "-q", "-U", *nombres], capture_output=True,
                           text=True, timeout=1800)
        conflicto = subprocess.run([str(VENV / "bin" / "pip"), "check"], capture_output=True, text=True,
                                   timeout=120).returncode != 0
        if r.returncode != 0 or conflicto or not self._probar_entorno():
            self.log(f"actualizar: fallo al actualizar Python ({r.stderr[-200:]!r}); vuelvo a la copia")
            shutil.rmtree(VENV)
            copia.rename(VENV)
            return "Los paquetes de Python no han pasado la prueba y he vuelto a la versión de antes."
        viejas = sorted(COPIAS.glob("venv_antes_*"))[:-2]          # solo las dos últimas copias
        for v in viejas:
            shutil.rmtree(v, ignore_errors=True)
        return f"{len(nombres)} paquetes de Python actualizados y probados."

    def _actualizar_omniroute(self, versiones: tuple[str, str] | None) -> str:
        if not versiones:
            return ""
        npm = NODO / "bin" / "npm"
        entorno = {"PATH": f"{NODO / 'bin'}:/usr/bin:/bin", "HOME": str(Path.home())}
        r = subprocess.run([str(npm), "install", "-g", "--no-audit", "--no-fund", f"omniroute@{versiones[1]}"],
                           capture_output=True, text=True, timeout=3600, env=entorno)
        subprocess.run(["systemctl", "--user", "restart", "omniroute"], capture_output=True, timeout=60)
        ok = False
        for _ in range(45):                                    # que vuelva a responder
            time.sleep(2)
            if self.omni and self.omni._comprobar():
                ok = True
                break
        if r.returncode == 0 and ok:
            return f"OmniRoute actualizado a la {versiones[1]}."
        self.log(f"actualizar: OmniRoute {versiones[1]} no arranca; vuelvo a la {versiones[0]}")
        subprocess.run([str(npm), "install", "-g", "--no-audit", "--no-fund", f"omniroute@{versiones[0]}"],
                       capture_output=True, timeout=3600, env=entorno)
        subprocess.run(["systemctl", "--user", "restart", "omniroute"], capture_output=True, timeout=60)
        return f"OmniRoute {versiones[1]} no funcionaba bien; he vuelto a la {versiones[0]}."

    def _actualizar_ollama(self, versiones: tuple[str, str] | None) -> str:
        if not versiones:
            return ""
        r = subprocess.run(["sudo", "-n", "/usr/local/sbin/jarvis-mantenimiento", "ollama"], capture_output=True,
                           text=True, timeout=1800)
        if r.returncode == 0:
            return f"Ollama actualizado a la {versiones[1]}."
        return (f"Ollama {versiones[1]} necesita permiso de administrador una vez: en el portátil, "
                "sudo bash ~/jarvis/configurar_mantenimiento.sh")

    def aplicar(self, info: dict) -> str:
        with self._ocupado:
            partes = [self._actualizar_pip(info["pip_menores"]), self._actualizar_omniroute(info["omniroute"]),
                      self._actualizar_ollama(info["ollama"])]
        texto = " ".join(p for p in partes if p) or "No había nada que actualizar."
        if info["pip_menores"]:
            texto += " Reinicio el asistente para usar lo nuevo cuando me digas «reinicia el asistente»."
        return texto

    # ------------------------------------------------------------------ cada semana
    def vigilar(self) -> None:
        def bucle():
            time.sleep(600)                                    # que el arranque termine tranquilo
            while True:
                try:
                    ultima = leer_config().get("componentes_comprobados")
                    if not ultima or dt.datetime.now() - dt.datetime.fromisoformat(ultima) > dt.timedelta(days=7):
                        info = self.comprobar()
                        if info["pip_menores"] or info["omniroute"] or info["ollama"]:
                            self.avisar("🔄 " + self.resumen(info))
                except Exception as e:
                    self.log(f"actualizar: no he podido comprobar: {e!r}")
                time.sleep(6 * 3600)
        threading.Thread(target=bucle, daemon=True).start()

    # ------------------------------------------------------------------ órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        de_asistente = r"(asistente|componentes|tus programas|tus paquetes|omni ?route|ollama|python)"
        if re.search(r"\b(que|cuales)\b.*\bversion\w*\b.*\b(tienes|usas)\b", t):
            pkg = NODO / "lib" / "node_modules" / "omniroute" / "package.json"
            omni = json.loads(pkg.read_text())["version"] if pkg.exists() else "no instalado"
            try:
                oll = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10).stdout
                oll = (re.findall(r"(\d+\.\d+\.\d+)", oll) or ["?"])[-1]
            except OSError:
                oll = "no instalado"
            return Respuesta(f"OmniRoute {omni}, Ollama {oll}. Última comprobación de actualizaciones: "
                             f"{leer_config().get('componentes_comprobados') or 'ninguna'}.")
        if re.search(rf"\b(busca|hay|comprueba|mira)\b.*\bactualizacion\w*\b.*\b{de_asistente}\b", t):
            if self._ocupado.locked():
                return Respuesta("Ya estoy actualizando; te aviso al terminar.")
            return Respuesta(self.resumen(self.comprobar()))
        if re.search(rf"\b(actualiza|actualizate|instala las actualizaciones)\b.*\b{de_asistente}\b", t):
            if self._ocupado.locked():
                return Respuesta("Ya estoy en ello; te aviso al terminar.")
            info = self.comprobar()
            if not (info["pip_menores"] or info["omniroute"] or info["ollama"]):
                return Respuesta(self.resumen(info))
            if not self.confirmar("actualizar mis componentes, con copia de seguridad (unos minutos)"):
                return Respuesta("Vale, lo dejo para otro momento.")
            tg = self.es_telegram()

            def trabajo():
                texto = self.aplicar(info)
                self.log(f"actualizar: {texto}")
                (self.avisar if tg else self.decir)(texto)
            threading.Thread(target=trabajo, daemon=True).start()
            return Respuesta("Me pongo con ello. Hago copia de todo y, si algo falla, vuelvo atrás. Te aviso al terminar.")
        return None
