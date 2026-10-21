#!/usr/bin/env python3
"""
Jarvis v2 — siempre escuchando, con interfaz holográfica y saludo al arrancar.

Cómo se usa: di "Jarvis, ¿qué hora es?" o solo "Jarvis" y espera el "¿Sí?".
Después de responder, durante unos segundos puedes seguir hablando sin repetir el nombre.

    python jarvis.py              # modo normal: escucha continua + voz + interfaz
    python jarvis.py --texto      # escribir por teclado (para probar sin micrófono)
    python jarvis.py --calibrar   # muestra el nivel del micrófono para ajustar la sensibilidad

La interfaz se ve en http://127.0.0.1:8765 (arrancar_jarvis.sh la abre a pantalla completa).

Variables de entorno opcionales:
    JARVIS_LLM           modelo de Ollama           (qwen2.5:1.5b)
    JARVIS_WHISPER       modelo de whisper          (base)
    JARVIS_BEAM          precisión de whisper       (1 = rápido)
    JARVIS_VOZ           ruta a una voz .onnx de Piper
    JARVIS_USUARIO       tu nombre, para el saludo  (vacío)
    JARVIS_SENSIBILIDAD  1.0 normal; más alto = hace falta hablar más fuerte
    JARVIS_SEGUIMIENTO   segundos para seguir hablando sin decir "Jarvis" (6; 0 = desactivado)
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

import perfil
from perfil import DATOS, INSTALACION, con_nombre
from sistema import Sistema, VOLUMEN_SUSURRO
from extras import Extras, memoria_para_ia, leer_memoria, guardar_memoria
from telegram_bot import Telegram
from camara import Camara
from frases import frase, variar
from mantenimiento import Mantenimiento
from archivos import Archivos
from calendario import Calendario, registrar_recordatorio
from cerebro import Cerebro, SinConexion
from saber import Saber
from nex import Nex
from ultimos import Ultimos, apuntar
from instalar import Instalar
from medios import Medios
from molestar import NoMolestar
from estudio import Estudio, guardar_clave as guardar_clave_estudio, comprobar_clave
from google_cuenta import CuentaGoogle, extraer_cliente
from google_calendario import SincronizadorCalendario
from correo import Correo
from vision import Vision
from oficina import Oficina
from creativo import Creativo
from aprendizaje import Aprendizaje, limpiar as limpiar_orden
from herramientas import Herramientas, guardar_config, leer_config, normalizar

BASE = DATOS
LOGS = BASE / "logs"
NOTAS = BASE / "notas" / "notas.md"
TMP = Path(tempfile.gettempdir()) / "jarvis"
UI_DIR = Path(__file__).resolve().parent / "ui"
PUERTO_UI = 8765

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODELO_LLM = os.environ.get("JARVIS_LLM", "qwen2.5:1.5b")
MODELO_WHISPER = os.environ.get("JARVIS_WHISPER", "base")
BEAM_WHISPER = int(os.environ.get("JARVIS_BEAM", "1"))
USUARIO = os.environ.get("JARVIS_USUARIO", "").strip()
SENSIBILIDAD = float(os.environ.get("JARVIS_SENSIBILIDAD", "1.0"))
SEGUIMIENTO = float(os.environ.get("JARVIS_SEGUIMIENTO", "6"))

RATE = 16000
FRAME = 480                 # 30 ms de audio por bloque
MAX_TURNOS = 4
OLVIDAR_CHARLA = 300        # tras 5 minutos sin charlar, empieza conversación nueva (no arrastra temas)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

TIPOS_CEREBRO = {"evento", "recordatorio", "temporizador", "consultar", "borrar_evento", "dato", "ver", "orden"}

ORDENES_CONOCIDAS = (
    "PC: abre/cierra <programa, web o ventana>; abre la carpeta <x>; busca el archivo <x>; sube/baja el volumen; "
    "pon el volumen al <n>; habla en voz baja; hazme una foto; haz una captura; qué tiempo hace; dime las noticias; "
    "busca en internet <tema>; cómo va el ordenador; limpia el ordenador; vacía la papelera; actualiza el sistema; "
    "haz un chequeo; qué ocupa más espacio; toma nota <texto>; activa/desactiva la vigilancia; apaga/reinicia el ordenador. "
    "VÍDEO Y MÚSICA: busca en youtube <x>; pon en youtube <x> [en vlc]; pon el vídeo de <x>; abre tiktok; busca en "
    "tiktok <x>; pon tiktoks de <x>; abre el tiktok de <usuario>; pon música [de <artista o estilo>]; pon la canción "
    "<x>; pausa; sigue; para la música; siguiente; anterior. "
    "ARCHIVOS: crea una carpeta <x>; crea un word/pdf sobre <tema>; mándame el archivo <x>; borra el archivo <x>; "
    "mueve el archivo <x> a <carpeta>; renombra el archivo <x> a <y>; convierte <archivo> a pdf/word/csv; "
    "abre el excel/word/pdf/plano/presentación <x>; abre el último archivo descargado; cuáles son mis últimos documentos. "
    "OFICINA: crea un excel de <tema> con <columnas o datos>; añade al excel <x>: <datos>; <pregunta> del excel <x>; "
    "haz un gráfico del excel <x>; crea una presentación sobre <tema>; describe el plano <x>; dibuja un plano de "
    "<descripción con medidas>; une los pdf <a> y <b>; escanea este documento; extrae el texto del pdf <x>; "
    "añade al word <x>: <texto>; resume este excel. "
    "CALENDARIO Y CORREO: abre el calendario; mándame el calendario; sincroniza el calendario; conecta mi cuenta de "
    "Google; avísame/no me avises de los correos; marca los correos como leídos; pon el resumen de la mañana a las "
    "<hora>; activa/desactiva el resumen de la mañana; dame el resumen de la mañana. "
    "CREAR: crea una imagen de <x>; hazme un logo/fondo de pantalla de <x>; hazla <cambio>; ponla de fondo de "
    "pantalla; crea un vídeo sobre <tema> [sin voz] [con Kling/Pika/Luma/Runway o en CapCut/Clipchamp si lo nombra]; "
    "compón una canción <estilo> sobre <tema> [con voz de mujer/hombre] [con Suno/Udio/AI Make Song/Musicful/Treblo "
    "si lo nombra]; diseña <x> en Canva/Photopea; qué herramientas de creación tienes; con esa foto crea un vídeo; "
    "reproduce/abre/enséñame/mándame la canción/el vídeo/la foto/la imagen/el documento que has creado; "
    "cuando tengas la canción, reprodúcela. "
    "PROGRAMAS: instala <programa> (o el AppImage/deb que está en Descargas); qué programas me has instalado; "
    "desinstala <programa>. MODO: no me molestes [hasta las <hora>]; ya puedes hablar. "
    "SABER: investiga [a fondo] sobre <tema>; qué has investigado; olvida lo que investigaste de <tema>; aprende mis "
    "documentos; qué dicen mis documentos sobre <tema>; mantenme informado sobre <tema>; deja de seguir <tema>; "
    "qué hay de nuevo de mis temas; qué sabes de mí; olvida que <dato>. "
    "NEX: encarga a Nex <tarea de varios pasos>; cuánto llevo gastado en Nex."
)

SISTEMA = (
    "Eres Jarvis, el asistente personal del usuario, con el estilo del mayordomo digital de Iron Man: educado, "
    "cercano, resolutivo y con un punto de humor. Funcionas en local en un portátil con Ubuntu. "
    "Respondes SIEMPRE en español de España, con frases cortas y naturales, porque tu respuesta se lee en voz alta. "
    "Máximo tres frases salvo que te pidan detalle. No uses listas, emojis, markdown ni símbolos. "
    "Varía tu forma de hablar: no empieces siempre igual, no repitas frases que ya has dicho y no empieces con '¡No!'. "
    "No saques temas de mensajes anteriores si el usuario no los menciona. "
    "Para charla, ideas, planes, recomendaciones, chistes o dudas generales, responde tú directamente y con "
    "creatividad. Solo para datos de actualidad (noticias, precios, resultados, horarios) sugiere decir "
    "'busca en internet' y el tema; nunca te inventes datos actuales. "
    "Las acciones en el ordenador las ejecuta otro módulo, y estas son las órdenes que existen: "
    + ORDENES_CONOCIDAS + ". "
    "El texto del usuario viene de un reconocedor de voz y a veces llega mal transcrito. Si el mensaje es en "
    "realidad una de esas órdenes mal oída (por ejemplo 'apme un a foto' es 'hazme una foto', y 'baja boca al "
    "internet dietas' es 'busca en internet dietas'), responde ÚNICAMENTE con la palabra ORDEN, dos puntos y "
    "la orden corregida, por ejemplo: ORDEN: hazme una foto. Si te piden una acción que no está en la lista, di con naturalidad que eso todavía no lo sabes hacer "
    "y que te lo pueden enseñar diciendo: aprende que cuando diga tal cosa, haz tal otra. "
    "NUNCA digas que has hecho algo en el ordenador. Si no estás seguro de un dato, dilo."
)


def sistema_con_fecha() -> str:
    ahora = dt.datetime.now()
    return (f"{SISTEMA} Ahora mismo es {DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]} "
            f"de {ahora.year}, a las {ahora.hour}:{ahora.minute:02d}. {memoria_para_ia()}").strip()


# =============================================================== auditoría

def auditar(tipo: str, detalle: str, **extra) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    evento = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "tipo": tipo, "detalle": detalle, **extra}
    with open(LOGS / "auditoria.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# =============================================================== interfaz (servidor local)

class Interfaz:
    """Sirve ui/index.html y le manda eventos en directo (Server-Sent Events). Solo escucha en 127.0.0.1."""

    def __init__(self, activa: bool = True):
        self.clientes: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.estado = {"tipo": "estado", "estado": "arrancando"}
        self.textos: dict = {"tipo": "texto"}
        self.panel: dict | None = None
        self.camara: dict | None = None
        self.cerebro: dict | None = None
        self.google_ev: dict | None = None
        self.saber_ev: dict | None = None
        self.google = None                              # la cuenta de Google (para /google/conectar y /google)
        self.calendario = None                          # lo conecta Jarvis: la página /calendario lo usa
        if not activa:
            return
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PUERTO_UI), self._handler())
        except OSError as e:
            log(f"interfaz no disponible (¿otro Jarvis en marcha?): {e}")
            return
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"interfaz en http://127.0.0.1:{PUERTO_UI}")

    def enviar(self, **ev) -> None:
        ev["t"] = time.time()
        if ev.get("tipo") == "estado":
            self.estado = ev
        elif ev.get("tipo") == "texto":
            self.textos = {**self.textos, **ev}
        elif ev.get("tipo") == "panel":
            self.panel = ev
        elif ev.get("tipo") == "camara":
            self.camara = ev
        elif ev.get("tipo") == "cerebro":
            self.cerebro = ev
        elif ev.get("tipo") == "google":
            self.google_ev = ev
        elif ev.get("tipo") == "saber":
            self.saber_ev = {k: v for k, v in ev.items() if k != "ultimo"}
        with self.lock:
            for q in self.clientes:
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    pass

    def poner_estado(self, estado: str, detalle: str = "") -> None:
        self.enviar(tipo="estado", estado=estado, detalle=detalle)

    def _handler(self):
        ui = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    datos = interfaz_personalizada((UI_DIR / "index.html").read_text(encoding="utf-8")).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(datos)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(datos)
                elif re.fullmatch(r"/fuentes/[a-z0-9-]+\.woff2", self.path):
                    f = UI_DIR / self.path.lstrip("/")
                    if f.is_file():
                        self.send_response(200)
                        self.send_header("Content-Type", "font/woff2")
                        self.send_header("Content-Length", str(f.stat().st_size))
                        self.send_header("Cache-Control", "max-age=86400")
                        self.end_headers()
                        self.wfile.write(f.read_bytes())
                    else:
                        self.send_error(404)
                elif self.path == "/calendario":
                    self._enviar(200, (UI_DIR / "calendario.html").read_bytes(), "text/html; charset=utf-8")
                elif self.path.startswith("/calendario.json"):
                    datos = ui.calendario.datos_web() if ui.calendario else {"eventos": []}
                    self._enviar(200, json.dumps(datos, ensure_ascii=False).encode(), "application/json")
                elif self.path == "/google/conectar" and ui.google:
                    try:
                        destino = ui.google.url_permiso()
                    except Exception as e:
                        self._enviar(200, _pagina_google(False, f"No puedo conectar todavía: {e}."),
                                     "text/html; charset=utf-8")
                        return
                    self.send_response(302)
                    self.send_header("Location", destino)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                elif (self.path == "/google" or self.path.startswith("/google?")) and ui.google:
                    import urllib.parse as up
                    params = {k: v[0] for k, v in up.parse_qs(up.urlsplit(self.path).query).items()}
                    ok, mensaje = ui.google.recibir_codigo(params)
                    self._enviar(200, _pagina_google(ok, mensaje), "text/html; charset=utf-8")
                elif self.path == "/eventos":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    q: queue.Queue = queue.Queue(maxsize=500)
                    with ui.lock:
                        ui.clientes.append(q)
                    q.put(ui.estado)
                    q.put(ui.textos)
                    if ui.panel:
                        q.put(ui.panel)
                    if ui.camara:
                        q.put(ui.camara)
                    if ui.cerebro:
                        q.put(ui.cerebro)
                    if ui.google_ev:
                        q.put(ui.google_ev)
                    if ui.saber_ev:
                        q.put(ui.saber_ev)
                    try:
                        while True:
                            try:
                                ev = q.get(timeout=15)
                                linea = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                            except queue.Empty:
                                linea = ": ping\n\n"
                            self.wfile.write(linea.encode())
                            self.wfile.flush()
                    except OSError:
                        pass
                    finally:
                        with ui.lock:
                            ui.clientes.remove(q)
                else:
                    self.send_error(404)

            def _enviar(self, codigo: int, datos: bytes, tipo: str) -> None:
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(datos)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(datos)

            def do_POST(self):
                # La cabecera X-Jarvis obliga al navegador a pedir permiso (CORS) si la petición viene de otra web,
                # y este servidor nunca lo da: solo la propia página del calendario puede cambiarlo.
                if self.path not in ("/calendario/nuevo", "/calendario/borrar") or not ui.calendario \
                        or self.headers.get("X-Jarvis") != "1":
                    self.send_error(403)
                    return
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    datos = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
                except ValueError:
                    datos = {}
                r = ui.calendario.desde_web(self.path.rsplit("/", 1)[1], datos if isinstance(datos, dict) else {})
                self._enviar(200, json.dumps(r, ensure_ascii=False).encode(), "application/json")

        return Manejador


def _pagina_google(ok: bool, mensaje: str) -> bytes:
    import html as h
    color = "#3fd2ff" if ok else "#ff6b6b"
    return (f"<!doctype html><meta charset='utf-8'><title>Cuenta de Google</title>"
            f"<body style='background:#05121c;color:#cfe;font:20px sans-serif;display:grid;place-items:center;"
            f"height:90vh'><div style='max-width:640px;text-align:center'><h1 style='color:{color}'>"
            f"{'Conectado' if ok else 'No se ha conectado'}</h1><p>{h.escape(mensaje)}</p>"
            f"<p style='opacity:.6'>Ya puedes cerrar esta pestaña.</p></div>").encode()


# =============================================================== micrófono continuo

class Microfono:
    """Un único proceso grabando todo el rato vía PipeWire; entrega bloques de 30 ms."""

    def __init__(self):
        if shutil.which("parec"):
            self.cmd = ["parec", "--format=s16le", f"--rate={RATE}", "--channels=1", "--latency-msec=30"]
        elif shutil.which("pw-record"):
            self.cmd = ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
        else:
            sys.exit("No encuentro parec ni pw-record. Instala: sudo apt install pulseaudio-utils")
        self.cola: queue.Queue = queue.Queue(maxsize=400)   # ~12 s de margen
        self.mudo = threading.Event()
        threading.Thread(target=self._bucle, daemon=True).start()
        log(f"micrófono continuo vía {self.cmd[0]}")

    def _bucle(self) -> None:
        n = FRAME * 2
        while True:
            p = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            buf = bytearray()
            while True:
                datos = p.stdout.read(n)
                if not datos:
                    break
                buf += datos
                while len(buf) >= n:
                    bloque, buf = bytes(buf[:n]), buf[n:]
                    if self.mudo.is_set():
                        continue
                    if self.cola.full():
                        try:
                            self.cola.get_nowait()
                        except queue.Empty:
                            pass
                    self.cola.put_nowait(np.frombuffer(bloque, dtype=np.int16).astype(np.float32) / 32768.0)
            p.wait()
            log("el micrófono se cortó; reintentando en 2 s")
            time.sleep(2)

    def leer(self, timeout: float = 1.0):
        try:
            return self.cola.get(timeout=timeout)
        except queue.Empty:
            return None

    def vaciar(self) -> None:
        while not self.cola.empty():
            try:
                self.cola.get_nowait()
            except queue.Empty:
                break


class Oyente:
    """Detecta cuándo empieza y acaba una frase por el nivel de sonido (sin pulsar nada)."""

    def __init__(self, mic: Microfono, ui: Interfaz):
        self.mic, self.ui = mic, ui
        self.ruido = 0.004
        self._calibrar()

    def _calibrar(self) -> None:
        niveles = []
        fin = time.time() + 1.5
        while time.time() < fin:
            f = self.mic.leer(0.5)
            if f is not None:
                niveles.append(float(np.sqrt(np.mean(f ** 2))))
        if niveles:
            self.ruido = float(np.percentile(niveles, 50))
        log(f"ruido de fondo: {self.ruido:.4f}")

    def umbral(self) -> float:
        return max(self.ruido * 3.0, 0.008) * SENSIBILIDAD

    def frase(self, max_espera: float | None = None) -> np.ndarray | None:
        """Espera a que alguien hable y devuelve la frase completa. None si pasa max_espera sin voz."""
        previo = collections.deque(maxlen=12)          # 360 ms antes de empezar, para no cortar la primera sílaba
        trozos: list[np.ndarray] = []
        activo, seguidos, silencio, contador, con_voz = False, 0, 0, 0, 0
        inicio = time.time()
        while True:
            if max_espera is not None and not activo and time.time() - inicio > max_espera:
                return None
            f = self.mic.leer(0.5)
            if f is None:
                continue
            nivel = float(np.sqrt(np.mean(f ** 2)))
            contador += 1
            if contador % 3 == 0:
                self.ui.enviar(tipo="nivel", v=round(min(1.0, nivel / (self.umbral() * 4)), 3))
            u = self.umbral()
            if not activo:
                previo.append(f)
                if nivel > u:
                    seguidos += 1
                else:
                    seguidos = 0
                    self.ruido = 0.98 * self.ruido + 0.02 * nivel   # se adapta despacio al ruido de la sala
                if seguidos >= 3:
                    activo, trozos, silencio, con_voz = True, list(previo), 0, seguidos
            else:
                trozos.append(f)
                if nivel < u * 0.8:
                    silencio += 1
                else:
                    silencio, con_voz = 0, con_voz + 1
                if silencio >= 30 or len(trozos) >= 500:      # 0,9 s de silencio o 15 s de frase
                    if con_voz >= 12:                          # al menos ~0,35 s hablando: ignora golpes y toses
                        return np.concatenate(trozos)
                    activo, seguidos, previo = False, 0, collections.deque(maxlen=12)


# =============================================================== oído (whisper)

class Oido:
    def __init__(self):
        from faster_whisper import WhisperModel
        log(f"cargando whisper '{MODELO_WHISPER}' (int8, CPU)…")
        self.modelo = WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8", cpu_threads=2)

    def transcribir(self, audio: np.ndarray, silencioso: bool = False) -> str:
        t0 = time.time()
        segmentos, _ = self.modelo.transcribe(
            audio, language="es", beam_size=BEAM_WHISPER, vad_filter=True,
            initial_prompt=con_nombre("Conversación en español de España con Jarvis, un asistente personal. Hola, Jarvis."),
        )
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        if not silencioso:
            log(f"oído ({time.time() - t0:.1f}s): {texto}")
        return texto


NO_LETRAS = re.compile(r"[^a-záéíóúüñ]")
VOCATIVOS = {"oye", "hola", "eh", "ey", "hey", "buenas", "bueno", "venga", "vale", "ok", "okey", "perdona", "oiga",
             "buenos", "dias", "tardes", "noches", "días", "porfa", "por", "favor", "y", "a", "ver"}


def interfaz_personalizada(html: str) -> str:
    """La interfaz con el nombre y el color del perfil. El <title> se queda en «Jarvis»: los scripts de pantallas
    reconocen la ventana por él."""
    p = perfil.perfil()
    nombre = perfil.nombre()
    color = str(p.get("color") or "#38e8ff").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", color)
    if m and m.group(1).lower() != "38e8ff":
        h = m.group(1).lower()
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        html = (html.replace("#38e8ff", f"#{h}").replace("%2338e8ff", f"%23{h}")
                .replace("56, 232, 255", f"{r}, {g}, {b}").replace("56,232,255", f"{r},{g},{b}"))
    if nombre != "Jarvis":
        siglas = ".".join(NO_LETRAS.sub("", nombre.upper().replace(" ", "")) or nombre.upper())
        cuerpo, cierre = html.split("<title>", 1) if "<title>" in html else (html, "")
        resto = cierre.split("</title>", 1)[1] if cierre else ""
        titulo = "<title>" + cierre.split("</title>", 1)[0] + "</title>" if cierre else ""
        resto = (resto.replace("J.A.R.V.I.S · JUST A RATHER VERY INTELLIGENT SYSTEM", f"{siglas} · ASISTENTE PERSONAL")
                 .replace("J.A.R.V.I.S", siglas).replace("«Jarvis»", f"«{nombre}»").replace("de Jarvis", f"de {nombre}"))
        html = cuerpo + titulo + resto
    return html


def separar_nombre(texto: str) -> tuple[bool, str]:
    """¿Empieza la frase llamando al asistente por su nombre? Devuelve (llamado, resto de la frase)."""
    palabras = texto.split()
    variantes = perfil.variantes()
    largo = len(perfil.nombre())
    corte = 0.72 if largo >= 6 else 0.8 if largo >= 5 else 0.9   # nombres cortos: más exigente
    # «Jarvis» no es una palabra normal y vale en cualquiera de las 4 primeras. Otro nombre («Viernes», «Luna»)
    # puede salir en una frase normal («el viernes tengo cita»): tiene que ir al principio o tras un saludo.
    estricto = perfil.nombre().lower() != "jarvis"
    for i, p in enumerate(palabras[:4]):                 # admite "Oye, Jarvis…" o "Bueno Jarvis…"
        limpia = NO_LETRAS.sub("", p.lower())
        if estricto and i > 0 and not all(NO_LETRAS.sub("", q.lower()) in VOCATIVOS for q in palabras[:i]):
            break
        if len(limpia) >= 3 and difflib.get_close_matches(limpia, variantes, n=1, cutoff=corte):
            return True, " ".join(palabras[i + 1:]).strip(" ,.;:¿?¡!")
    return False, ""


# =============================================================== voz (piper)

def reproductor() -> list[str]:
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    sys.exit("No encuentro pw-play, paplay ni aplay.")


def buscar_voz() -> Path:
    if os.environ.get("JARVIS_VOZ"):
        return Path(os.environ["JARVIS_VOZ"]).expanduser()
    voces = sorted(p for p in INSTALACION.rglob("*.onnx") if "venv" not in p.parts and Path(str(p) + ".json").exists())
    elegida = str((perfil.perfil().get("voz") or {}).get("modelo") or "").strip()
    if elegida:                                                  # la del perfil (nombre del modelo o ruta)
        if Path(elegida).expanduser().exists():
            return Path(elegida).expanduser()
        coinciden = [v for v in voces if v.name.startswith(elegida.removesuffix(".onnx"))]
        if coinciden:
            return coinciden[0]
    preferida = [v for v in voces if "sharvard" in v.name]      # la del Jarvis original
    if preferida:
        return preferida[0]
    medias = [v for v in voces if "medium" in v.name]
    if not (medias or voces):
        sys.exit(f"No encuentro ninguna voz de Piper (.onnx + .onnx.json) dentro de {INSTALACION}.")
    return (medias or voces)[0]


def envolvente(ruta: Path, paso: float = 0.04) -> list[float]:
    """Volumen de la voz cada 40 ms (0-1): la interfaz lo usa para moverse al ritmo del habla."""
    with wave.open(str(ruta), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    n = max(1, int(sr * paso))
    k = len(x) // n
    if k == 0:
        return []
    rms = np.sqrt((x[: k * n].reshape(k, n) ** 2).mean(axis=1))
    rms = rms / max(float(rms.max()), 1e-4)
    return [round(float(v), 3) for v in rms]


class Voz:
    def __init__(self, ruta: Path):
        from piper import PiperVoice
        self.voz = PiperVoice.load(str(ruta))
        self.player = reproductor()
        try:
            hablantes = int(json.loads(Path(str(ruta) + ".json").read_text()).get("num_speakers", 1))
        except (OSError, ValueError):
            hablantes = 1
        # sharvard tiene 2 hablantes: el 1 es el que suena a mayordomo. Algo más pausado que el normal.
        ajustes = perfil.perfil().get("voz") or {}
        hablante = os.environ.get("JARVIS_VOZ_HABLANTE") or ajustes.get("hablante")
        self.hablante = int(hablante if hablante is not None else 1) if hablantes > 1 else None
        self.lentitud = float(os.environ.get("JARVIS_VOZ_LENTITUD") or ajustes.get("lentitud") or 1.05)
        self.config = None
        try:
            from piper import SynthesisConfig
            self.config = SynthesisConfig(speaker_id=self.hablante, length_scale=self.lentitud)
        except ImportError:
            pass
        log(f"voz: {ruta.name} (hablante {self.hablante}) · reproductor: {self.player[0]}")

    def sintetizar(self, texto: str, destino: Path) -> None:
        with wave.open(str(destino), "wb") as w:
            if hasattr(self.voz, "synthesize_wav"):
                if self.config is not None:
                    self.voz.synthesize_wav(texto, w, syn_config=self.config)
                else:
                    self.voz.synthesize_wav(texto, w)
            else:
                self.voz.synthesize(texto, w, speaker_id=self.hablante, length_scale=self.lentitud)


# =============================================================== LLM (ollama)

def ollama(ruta: str, cuerpo: dict | None = None, timeout: int = 10) -> dict:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(OLLAMA_URL + ruta, data=datos, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def esperar_ollama(ui: Interfaz) -> None:
    """Al arrancar el ordenador Ollama tarda en estar listo: esperamos en vez de fallar."""
    for intento in range(60):
        try:
            modelos = {m["name"] for m in ollama("/api/tags")["models"]}
            break
        except (urllib.error.URLError, OSError):
            if intento == 0:
                log("esperando a Ollama…")
                ui.poner_estado("arrancando", "Esperando al motor de IA")
            time.sleep(2)
    else:
        ui.poner_estado("error", "Ollama no responde")
        sys.exit("Ollama no responde. Arráncalo con: sudo systemctl start ollama")
    if MODELO_LLM not in modelos and f"{MODELO_LLM}:latest" not in modelos:
        ui.poner_estado("error", f"Falta el modelo {MODELO_LLM}")
        sys.exit(f"Falta el modelo {MODELO_LLM}. Descárgalo con: ollama pull {MODELO_LLM}")


def limpiar_respuesta(texto: str, max_frases: int = 4) -> str:
    """El modelo pequeño a veces ignora las instrucciones y suelta listas o markdown: lo dejamos hablable."""
    lineas = []
    for linea in texto.splitlines():
        linea = re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", linea)          # viñetas y numeraciones
        linea = re.sub(r"[*_#`>]+", "", linea).strip()
        if linea:
            lineas.append(linea if re.search(r"[.!?:;]$", linea) else linea + ".")
    limpio = re.sub(r"\s+", " ", " ".join(lineas)).strip()
    frases = re.split(r"(?<=[.!?])\s+", limpio)
    return " ".join(frases[:max_frases]).strip()


def preguntar_llm(historial: list[dict], max_tokens: int = 140, extra: str = "", temperatura: float = 0.7) -> str:
    sistema = sistema_con_fecha() + (" " + extra if extra else "")
    cuerpo = {
        "model": MODELO_LLM,
        "messages": [{"role": "system", "content": sistema}] + historial[-MAX_TURNOS * 2:],
        "stream": False,
        "keep_alive": "30m",          # la IA local es solo de reserva: libera 1,3 GB de RAM si no se usa
        "options": {"num_ctx": 2048, "temperature": temperatura, "top_p": 0.9, "repeat_penalty": 1.15,
                    "num_predict": max_tokens},
    }
    texto = ollama("/api/chat", cuerpo, timeout=300)["message"]["content"]
    if re.search(r"ORDEN\s*:", texto):
        return texto.strip()
    texto = limpiar_respuesta(texto)
    sin_no = re.sub(r"^¡?No!\s+", "", texto)                   # la muletilla "¡No!" del modelo pequeño
    return sin_no[:1].upper() + sin_no[1:] if sin_no else texto


# =============================================================== acciones locales

RE_HORA = re.compile(r"\bqu[eé] hora\b")
RE_FECHA = re.compile(r"\bqu[eé] d[ií]a|\bfecha\b")
RE_CAPACIDADES = re.compile(
    r"\bqu[eé] (puedes|sabes) hacer\b|\ba qu[eé] tienes acceso\b|\bqu[eé] (acceso|permisos) tienes\b"
    r"|\bqu[eé] (archivos|carpetas|rutas?) (tienes|ves|puedes)\b|\bpara qu[eé] sirves\b"
)
CAPACIDADES = (
    "Puedo abrir y cerrar aplicaciones, carpetas y archivos, buscar archivos y resumirlos, buscar en internet, "
    "decirte el tiempo, las noticias, la hora y la fecha, guardar notas, recordatorios y temporizadores, recordar "
    "datos sobre ti, hacerte fotos con la cámara, saludarte cuando vuelves, vigilar la habitación, hacer cuentas y conversiones, escribir lo que me dictes, hacer capturas de pantalla, decirte "
    "cómo va el ordenador, subir o bajar el volumen, hablar en voz baja, y apagar o reiniciar si me lo confirmas. "
    "También hago mantenimiento: limpio la caché y los temporales, reviso el sistema y lo actualizo. "
    "Y aprendo: enséñame atajos diciendo aprende que cuando diga tal cosa, haz tal otra, o corrígeme diciendo "
    "no, me refería a. Gestiono tus archivos: creo carpetas, documentos de texto, Word y PDF, que puedo redactar "
    "yo, los muevo, renombro, convierto a PDF y te los mando al móvil, y los borro solo si me lo confirmas, "
    "mandándolos a la papelera. Llevo tu calendario: apunto citas y cumpleaños, guardo ahí los recordatorios, "
    "te digo qué tienes cada día y te lo enseño en la pantalla, sincronizado con tu Google Calendar. Con tu cuenta "
    "de Google conectada, te leo y resumo el correo, contesto o escribo correos con tu permiso y te aviso de los "
    "importantes. Puedo mirar tu pantalla y leerte un error, o ver por la cámara qué tienes en la mano. Cada mañana te doy un resumen del día. "
    "En la oficina: abro cualquier archivo por su nombre, también planos DWG y DXF con LibreCAD; creo hojas de "
    "cálculo con totales, les añado filas, respondo preguntas sobre ellas y hago gráficos; preparo presentaciones; "
    "describo planos y dibujo planos sencillos; uno PDF, escaneo documentos con la cámara y saco el texto de un PDF "
    "escaneado o de una foto. "
    "Y soy creativo: pinto imágenes, logos y fondos de pantalla, monto vídeos narrados con imágenes, subtítulos y "
    "música, y compongo canciones con letra, acordes y arreglo musical. "
    "Y me informo por mi cuenta: investigo a fondo cualquier tema leyendo varias webs y lo guardo para responderte "
    "después, leo tus documentos para contestarte qué dicen, sigo los temas que me pidas y cada mañana te mando "
    "las novedades, y voy recordando lo que me cuentas de ti. "
    "Para tareas largas de varios pasos puedo encargárselas a Nex, una IA más potente que trabaja como agente: "
    "busca, lee, compara y me da órdenes, y te deja el resultado en un Word. "
    "Para crear uso herramientas de fuera yo solo: canciones cantadas con ACE-Step, Musicful o Treblo, vídeos con "
    "movimiento real con Wan, LTX, Kling, Pika, Luma o Runway, y te preparo y abro Suno, Udio, CapCut o Canva. También me puedes escribir por Telegram."
)


def accion_local(texto: str, confirmar) -> str | None:
    t = texto.lower().strip(" ¿?¡!.,")
    ahora = dt.datetime.now()

    m = re.match(r"^(toma nota|apunta|anota)(?: que)?[:,]?\s+(.+)$", t)
    if m:
        nota = m.group(2).strip()
        if not confirmar(f"guardar la nota: {nota}"):
            return "Vale, no la guardo."
        NOTAS.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTAS, "a", encoding="utf-8") as f:
            f.write(f"- {ahora:%Y-%m-%d %H:%M} — {nota}\n")
        auditar("accion", "nota_guardada", nota=nota)
        return "Anotado."

    if RE_CAPACIDADES.search(t):
        return CAPACIDADES

    partes = []
    if RE_FECHA.search(t):
        partes.append(f"Hoy es {DIAS[ahora.weekday()]}, {ahora.day} de {MESES[ahora.month - 1]}.")
    if RE_HORA.search(t):
        partes.append(f"Son las {ahora.hour} y {ahora.minute:02d}.")
    return " ".join(partes) or None


def bajar_volumen_wav(ruta: Path, factor: float) -> None:
    """Modo susurro: la misma voz, más flojita (sin depender del volumen general)."""
    import array
    with wave.open(str(ruta), "rb") as w:
        params = w.getparams()
        datos = w.readframes(w.getnframes())
    if params.sampwidth != 2:
        return
    muestras = array.array("h")
    muestras.frombytes(datos)
    muestras = array.array("h", (int(m * factor) for m in muestras))
    with wave.open(str(ruta), "wb") as w:
        w.setparams(params)
        w.writeframes(muestras.tobytes())


# =============================================================== Jarvis

class Jarvis:
    def __init__(self, modo_texto: bool, mudo: bool):
        TMP.mkdir(parents=True, exist_ok=True)
        self.modo_texto = modo_texto
        self.ui = Interfaz()
        self.ui.poner_estado("arrancando", "Iniciando sistemas")
        esperar_ollama(self.ui)
        self.mic = None if modo_texto else Microfono()
        self.oido = None if modo_texto else Oido()
        self.voz = None if mudo else Voz(buscar_voz())
        self.oyente = None if modo_texto else Oyente(self.mic, self.ui)
        self.historial: list[dict] = []
        self.cerebro = Cerebro(log)                     # Groq: oído y cerebro grandes (si hay clave e internet)
        self.cerebro.al_cambiar = lambda: self.ui.enviar(tipo="cerebro", estado=self.cerebro.estado())
        self.dialogo: list[dict] = []                   # lo último hablado, para que entienda "también", "ese"…
        self._ultimo_dialogo = 0.0
        self.herr = Herramientas(self.resumir, self.confirmar)
        self._voz_lock = threading.RLock()            # que un recordatorio no hable encima de otra frase
        self.molestar = NoMolestar()                     # «no me molestes»: sin hablar por su cuenta
        self.sist = Sistema(self.decir, self.confirmar, self.ui, log)
        self._cerebro = threading.RLock()             # voz y Telegram no procesan órdenes a la vez
        self._canal = threading.local()               # ¿la orden viene de Telegram?
        self.tg = Telegram(self._procesar_telegram, self.decir,
                           self._transcribir_archivo if self.oido else None, log)
        self.sist.avisar = self.tg.enviar             # los recordatorios llegan también al móvil
        self.tg.al_recibir_archivo = self._archivo_recibido
        self.extras = Extras(self.decir, self.ui, log, self.herr, avisar=self.tg.enviar, sist=self.sist)
        self.cam = Camara(self.decir, self.ui, log, avisar=self.tg.enviar, avisar_foto=self.tg.enviar_foto,
                          bienvenida=self._bienvenida)
        self.mant = Mantenimiento(self.decir, self.confirmar, log, avisar=self.tg.enviar,
                                  es_telegram=lambda: getattr(self._canal, "tg", False),
                                  modelo_llm=MODELO_LLM, ollama_url=OLLAMA_URL, ui=self.ui)
        self.aprende = Aprendizaje(log)
        self.cal = Calendario(self.decir, self.confirmar, log, ui=self.ui, programar=self.sist.programar,
                              desprogramar=self.sist.desprogramar, enviar_documento=self.tg.enviar_documento,
                              es_telegram=lambda: getattr(self._canal, "tg", False))
        self.sist.al_crear = registrar_recordatorio
        self.ui.calendario = self.cal
        self.google = CuentaGoogle(log)                 # Gmail y Google Calendar (si está conectada)
        self.sync = SincronizadorCalendario(self.google, log, programar=self.sist.programar,
                                            desprogramar=self.sist.desprogramar)
        self.google.al_cambiar = self._google_cambia
        self.ui.google = self.google
        self.correo = Correo(self.google, self.decir, self.confirmar, log, ui=self.ui, cerebro=self.cerebro,
                             resumir=self.resumir, avisar=self.tg.enviar,
                             es_telegram=lambda: getattr(self._canal, "tg", False))
        self.correo.sync = self.sync
        self.extras.correo = self.correo
        self.vision = Vision(self.cerebro, self.cam, log, ui=self.ui,
                             es_telegram=lambda: getattr(self._canal, "tg", False))
        self.arch = Archivos(self.decir, self.confirmar, log, ui=self.ui, enviar_documento=self.tg.enviar_documento,
                             es_telegram=lambda: getattr(self._canal, "tg", False), redactar=self.redactar,
                             avisar=self.tg.enviar)
        self.oficina = Oficina(self.cerebro, self.decir, self.confirmar, log, ui=self.ui,
                               enviar_documento=self.tg.enviar_documento,
                               es_telegram=lambda: getattr(self._canal, "tg", False), avisar=self.tg.enviar,
                               camara=self.cam, vision=self.vision, redactar=self.redactar)
        self.estudio = Estudio(log, ui=self.ui, avisar=self.tg.enviar,
                               es_telegram=lambda: getattr(self._canal, "tg", False))
        self.creativo = Creativo(self.cerebro, self.decir, log, ui=self.ui, enviar_documento=self.tg.enviar_documento,
                                 enviar_foto=self.tg.enviar_foto, es_telegram=lambda: getattr(self._canal, "tg", False),
                                 avisar=self.tg.enviar, sintetizar=self.voz.sintetizar if self.voz else None)
        self.saber = Saber(self.cerebro, self.decir, log, ui=self.ui, preguntar=self.preguntar,
                           es_telegram=lambda: getattr(self._canal, "tg", False), avisar=self.tg.enviar,
                           enviar_documento=self.tg.enviar_documento)
        self.creativo.estudio = self.estudio            # canciones cantadas y vídeo con movimiento, solo
        self.ultimos = Ultimos(self.decir, log, es_telegram=lambda: getattr(self._canal, "tg", False),
                               enviar_documento=self.tg.enviar_documento, enviar_foto=self.tg.enviar_foto,
                               avisar=self.tg.enviar, trabajando=lambda: self.creativo._trabajando)
        self.instalar = Instalar(self.decir, self.confirmar, log, es_telegram=lambda: getattr(self._canal, "tg", False),
                                 avisar=self.tg.enviar)
        self.medios = Medios(log, es_telegram=lambda: getattr(self._canal, "tg", False), avisar=self.tg.enviar)
        self.nex = Nex(log, ui=self.ui, decir=self.decir, avisar=self.tg.enviar,
                       es_telegram=lambda: getattr(self._canal, "tg", False), preguntar=self.preguntar,
                       enviar_documento=self.tg.enviar_documento)
        self.nex.ejecutar_orden = self._orden_de_nex
        self.nex.ordenes = ORDENES_CONOCIDAS
        self.cerebro.respaldo = self.nex                # si Groq se queda sin cupo, piensa Nex
        self.saber.nex = self.nex                       # las investigaciones a fondo las redacta Nex
        self._ultima_entrada: str | None = None
        self._ultima_charla = 0.0
        self._recientes: collections.deque = collections.deque(maxlen=5)   # para no repetirse
        self.sist.arrancar_vigilante()
        self.extras.arrancar_vigilante()
        self.mant.arrancar_vigilante()
        self.cam.arrancar()
        self.sync.arrancar()
        self.correo.arrancar_vigilante()
        threading.Thread(target=self._agente_manana, daemon=True).start()
        self.saber.arrancar()

    def _google_cambia(self) -> None:
        self.ui.enviar(tipo="google", estado=self.google.estado())
        self.sync.pedir()
        if self.google.tiene_cliente and not self.google.conectada and self.google.cfg.get("permisos"):
            self.tg.enviar("⚠️ Google ha retirado el permiso de Jarvis. Di «conecta mi cuenta de Google» delante "
                           "del portátil para volver a conectarlo.")

    # ---------- resumen de la mañana (agente programado)
    @staticmethod
    def _es_hora_resumen() -> bool:
        cfg = leer_config()
        ahora = dt.datetime.now()
        return bool(cfg.get("resumen_activo", True)) and f"{ahora:%H:%M}" >= cfg.get("resumen_hora", "08:00") \
            and ahora.hour < 13

    def _resumen_pendiente(self) -> bool:
        """¿Falta dar hoy el resumen en voz?"""
        return self._es_hora_resumen() and leer_config().get("ultimo_resumen") != dt.date.today().isoformat()

    def _resumen_telegram(self) -> None:
        hoy = dt.date.today().isoformat()
        if leer_config().get("ultimo_resumen_tg") == hoy or not self.tg.activo:
            return
        guardar_config(ultimo_resumen_tg=hoy)
        try:
            self.tg.enviar(self.extras.resumen_dia(para_telegram=True))
        except Exception as e:
            log(f"resumen de la mañana (Telegram): {e!r}")

    def _dar_resumen_manana(self, saludo: bool = True) -> None:
        guardar_config(ultimo_resumen=dt.date.today().isoformat())
        try:
            self.decir(("Buenos días. " if saludo else "") + self.extras.resumen_dia())
        except Exception as e:
            log(f"resumen de la mañana: {e!r}")

    def _agente_manana(self) -> None:
        """A la hora del resumen: por Telegram siempre; en voz cuando la cámara te ve (o a la hora, sin cámara)."""
        time.sleep(90)
        while True:
            try:
                if self._es_hora_resumen():
                    self._resumen_telegram()
                    camara_mira = self.cam.activa and self.cam.disponible
                    if self._resumen_pendiente() and (not camara_mira or self.cam._presente):
                        with self._cerebro:
                            self._dar_resumen_manana()
            except Exception as e:
                log(f"resumen de la mañana: {e!r}")
            time.sleep(30)

    def _bienvenida(self, minutos: float) -> str:
        """Al volver delante de la cámara tras un rato fuera."""
        from sistema import leer_recordatorios
        if self._resumen_pendiente():
            guardar_config(ultimo_resumen=dt.date.today().isoformat())
            try:
                return "Buenos días. " + self.extras.resumen_dia()
            except Exception as e:
                log(f"resumen de la mañana: {e!r}")
        ahora = dt.datetime.now()
        texto = frase("hola_de_nuevo") if minutos < 90 else \
            f"{frase('hola_de_nuevo')} Has estado fuera unas {round(minutos / 60)} horas."
        proximos = [r for r in leer_recordatorios()
                    if dt.datetime.fromisoformat(r["cuando"]) - ahora < dt.timedelta(hours=3)]
        if proximos:
            r = proximos[0]
            texto += f" Te recuerdo que a las {dt.datetime.fromisoformat(r['cuando']):%H:%M} tienes: {r['texto'] or 'un recordatorio'}."
        return texto

    def _archivo_recibido(self, ruta: Path, es_foto: bool) -> str:
        """Lo que llega por Telegram se abre en la pantalla del portátil (salvo las credenciales de Google)."""
        from herramientas import lanzar
        if ruta.suffix.lower() == ".json" and ruta.stat().st_size < 20000:
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                datos = None
            if isinstance(datos, dict) and extraer_cliente(datos):
                ok, mensaje = self.google.guardar_cliente(datos)
                try:
                    ruta.unlink()                       # que no quede una copia suelta en Descargas
                except OSError:
                    pass
                log("telegram: recibidas las credenciales de Google (no se guardan en el registro)")
                return mensaje
        if es_foto:
            self.vision.recibida_por_telegram(ruta)
        self.ui.enviar(tipo="resultados", titulo="Recibido por Telegram", items=[ruta.name])
        if es_foto:
            self.oficina.ultimo = ruta
            apuntar(ruta, "foto", abierto=True)          # "con esta foto crea un vídeo", "anímala"
            lanzar(["xdg-open", str(ruta)])
            if self.vision.disponible:
                return ("Abierto en el portátil. Si quieres que la mire, pregúntame, por ejemplo: «¿qué es esto?», "
                        "o dime «escanéala» para guardarla como PDF con su texto.")
            return "Abierto en el portátil."
        return self.oficina.recibido(ruta)

    def _transcribir_archivo(self, ruta: str) -> str:
        """Notas de voz de Telegram: ffmpeg las pasa a 16 kHz mono y se transcriben como el micrófono."""
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", ruta, "-f", "s16le",
                            "-ac", "1", "-ar", str(RATE), "-"], capture_output=True, timeout=120)
        if r.returncode != 0 or not r.stdout:
            log(f"telegram: ffmpeg no pudo leer la nota de voz: {r.stderr[-200:]!r}")
            return ""
        audio = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        with self._cerebro:
            return self.escuchar(audio)

    def _vocabulario(self) -> str:
        """Nombres propios que el usuario usa (de su memoria y su calendario): así whisper escribe «Serveo» y no
        «Cerveo», o el nombre de su pueblo bien escrito. Se recalcula cada 5 minutos."""
        cache = getattr(self, "_vocab", None)
        if cache and time.time() - cache[0] < 300:
            return cache[1]
        textos = [d.get("dato", "") for d in leer_memoria()]
        try:
            import calendario
            textos += [e.get("texto", "") for e in calendario.proximos(15)]
        except Exception:
            pass
        vistos: dict[str, None] = {}
        for tx in textos:
            for i, w in enumerate(re.findall(r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü]{2,}", tx)):
                if (i > 0 or not tx.startswith(w)) and w.lower() not in (perfil.nombre().lower(), "seat", "mi", "el", "la"):
                    vistos.setdefault(w, None)
        pista = ("Nombres que pueden salir: " + ", ".join(list(vistos)[:30]) + ".") if vistos else ""
        self._vocab = (time.time(), pista)
        return pista

    def escuchar(self, audio: np.ndarray, silencioso: bool = False) -> str:
        """Transcribe una frase: con whisper-large-v3 en Groq si se puede; si no, con el whisper local."""
        if self.cerebro.oido_activo:
            t0 = time.time()
            try:
                texto = self.cerebro.transcribir(audio, pista=self._vocabulario())
                if not silencioso:
                    log(f"oído nube ({time.time() - t0:.1f}s): {texto}")
                return texto
            except Exception as e:
                log(f"oído nube no disponible ({e}); uso el local")
        return self.oido.transcribir(audio, silencioso=silencioso)

    def _procesar_telegram(self, texto: str) -> dict:
        if re.search(r"GOCSPX-[A-Za-z0-9_\-]{10,}", texto):      # secreto de Google: ni al registro ni a la IA
            log("telegram: recibido un secreto de Google como texto; no se procesa")
            return {"texto": ("Eso es el secreto de tu cuenta de Google: no hace falta mandarlo como texto, ya lo "
                              "tengo del archivo. Borra ese mensaje del chat, por seguridad."),
                    "susurro": None, "despues": None, "archivo": None}
        m = re.search(r"(?i)\bpollinations\b\W*(?:token|clave|key)?\W*([A-Za-z0-9_\-\.]{12,})\s*$", texto.strip())
        if m:                                           # clave de Pollinations (imágenes): ni al registro ni a la IA
            guardar_config(pollinations_token=m.group(1))
            log("telegram: recibida una clave de Pollinations (no se guarda en el registro)")
            return {"texto": "Guardada la clave de Pollinations: las imágenes saldrán sin marca de agua y más deprisa. "
                             "Borra ese mensaje del chat, por seguridad.", "susurro": None, "despues": None,
                    "archivo": None}
        m = re.search(r"(?i)\b(?:clave|key|token|api)\s+(?:de\s+)?(musicful|fal(?:\.ai)?|runway|hugging\s*face|hf)\b"
                      r"\W*([A-Za-z0-9_\-:.]{16,})", texto) or re.search(r"\b()(hf_[A-Za-z0-9]{30,})\b", texto)
        if m:                                           # claves del estudio: ni al registro ni a la IA
            servicio = normalizar(m.group(1) or "hf").replace(" ", "").replace(".ai", "")
            servicio = "hf" if servicio in ("huggingface", "hf") else servicio
            guardar_clave_estudio(servicio, m.group(2))
            log(f"telegram: recibida una clave de {servicio} (no se guarda en el registro)")
            return {"texto": comprobar_clave(servicio, m.group(2)) + " Borra tu mensaje con la clave, por seguridad.",
                    "susurro": None, "despues": None, "archivo": None}
        m = re.search(r"\b(sk-or-v1-[A-Za-z0-9]{20,})\b", texto)
        if m:                                           # la clave de OpenRouter (Nex): ni al registro ni a la IA
            log("telegram: recibida una clave de OpenRouter (no se guarda en el registro)")
            ok, mensaje = self.nex.guardar_clave(m.group(1))
            self.cerebro.al_cambiar()
            return {"texto": mensaje, "susurro": None, "despues": None, "archivo": None}
        m = re.search(r"\b(gsk_[A-Za-z0-9]{20,})\b", texto)
        if m:                                           # la clave de Groq: ni al registro ni a la pantalla
            log("telegram: recibida una clave de Groq (no se guarda en el registro)")
            ok, mensaje = self.cerebro.guardar_clave(m.group(1))
            self.cerebro.al_cambiar()
            return {"texto": mensaje, "susurro": None, "despues": None, "archivo": None}
        with self._cerebro:
            self._canal.tg = True
            try:
                auditar("entrada", texto, canal="telegram")
                self.ui.enviar(tipo="texto", usuario="📱 " + texto, jarvis="")
                r = self.procesar(texto)
                self.ui.enviar(tipo="texto", jarvis=r["texto"])
                log(f"Telegram › {texto}  ⇒  {r['texto']}")
                return r
            finally:
                self._canal.tg = False

    def _orden_de_nex(self, orden: str, tg: bool) -> str:
        """Nex (modo agente) le da una orden a Jarvis: pasa solo por las reglas, como las del cerebro."""
        previo = getattr(self._canal, "tg", False)
        self._canal.tg = tg
        try:
            with self._cerebro:
                auditar("entrada", orden, canal="nex")
                r = self.procesar(orden, profundidad=2)
            if r.get("archivo") and tg:
                self.tg.enviar_documento(str(r["archivo"]), Path(str(r["archivo"])).name)
            return r["texto"]
        finally:
            self._canal.tg = previo

    def resumir(self, instruccion: str, texto: str) -> str:
        """La IA solo se usa para resumir lo que las herramientas encuentran."""
        if self.cerebro.activo:
            try:
                return limpiar_respuesta(self.cerebro.chat([
                    {"role": "system", "content": "Eres Jarvis. Respondes en español de España, breve y exacto, "
                                                  "sin listas ni símbolos, para leerse en voz alta."},
                    {"role": "user", "content": f"{instruccion}\n\n---\n{texto[:7000]}"}], max_tokens=500,
                    ligero=True), 4)
            except SinConexion:
                pass
        cuerpo = {
            "model": MODELO_LLM, "stream": False, "keep_alive": "30m",
            "messages": [{"role": "system", "content": "Eres Jarvis. Respondes en español de España, breve, "
                                                       "sin listas ni símbolos, para leerse en voz alta."},
                         {"role": "user", "content": f"{instruccion}\n\n---\n{texto[:5000]}"}],
            "options": {"num_ctx": 2048, "temperature": 0.3, "num_predict": 160},
        }
        try:
            return limpiar_respuesta(ollama("/api/chat", cuerpo, timeout=300)["message"]["content"], 3)
        except (urllib.error.URLError, OSError, KeyError):
            return "no he podido resumirlo"

    def redactar(self, encargo: str) -> str:
        """Redacta un documento completo (para los Word y PDF que se piden por voz)."""
        instrucciones = ("Eres Jarvis y redactas documentos en español de España, bien escritos y útiles. "
                         "Devuelve SOLO el documento: en la primera línea un título corto (sin almohadillas); "
                         "después párrafos separados por una línea en blanco. Para los apartados usa una línea que "
                         "empiece por «## ». Para enumeraciones, líneas que empiecen por guion. Si hace falta una "
                         "tabla, una fila por línea con las columnas separadas por « | » (la primera, la cabecera). "
                         "Puedes resaltar alguna palabra clave con **negrita**. Sin comentarios tuyos antes o después.")
        if re.search(r"(?i)im[aá]gen|foto|ilustr|dibujo|gr[aá]fic", encargo):
            instrucciones += (" El usuario quiere imágenes: añade entre 2 y 3 líneas sueltas, cada una en su sitio, con "
                              "el formato [IMAGEN: descripción visual EN INGLÉS, fotográfica y concreta]. Jarvis las "
                              "pintará y las pondrá en el documento.")
        if self.cerebro.activo:
            try:
                texto = self.cerebro.chat([{"role": "system", "content": instrucciones},
                                           {"role": "user", "content": f"Redacta: {encargo}"}],
                                          max_tokens=3000, temperatura=0.6, timeout=90)
                if texto:
                    texto = re.sub(r"`+", "", texto).strip()
                    lineas = texto.splitlines()
                    if lineas:
                        lineas[0] = lineas[0].strip(" #*")         # el título, limpio
                    return "\n".join(lineas).strip()
            except SinConexion:
                pass
        cuerpo = {
            "model": MODELO_LLM, "stream": False, "keep_alive": "30m",
            "messages": [{"role": "system", "content":
                          "Eres Jarvis y redactas documentos en español de España, bien escritos y útiles. "
                          "Devuelve SOLO el documento: en la primera línea un título corto; después párrafos "
                          "separados por una línea en blanco. Para enumeraciones usa líneas que empiecen por guion. "
                          "Sin markdown, sin asteriscos, sin almohadillas y sin comentarios tuyos antes o después."},
                         {"role": "user", "content": f"Redacta: {encargo}"}],
            "options": {"num_ctx": 2048, "temperature": 0.6, "repeat_penalty": 1.1, "num_predict": 900},
        }
        texto = ollama("/api/chat", cuerpo, timeout=900)["message"]["content"]
        return re.sub(r"[*#`]+", "", texto).strip()

    # ---------- salida
    def decir(self, texto: str, susurro: bool | None = None) -> None:
        texto = con_nombre(texto)                         # el asistente puede llamarse de otra forma
        if not getattr(self._canal, "respondiendo", False) and not self.molestar.permite(texto):
            log(f"Jarvis (no molestar) › {texto}")       # por su cuenta y en silencio: a la pantalla y al móvil
            self.ui.enviar(tipo="texto", jarvis=texto)
            try:
                if self.tg.activo:
                    self.tg.enviar("🔕 " + texto)
            except Exception:
                pass
            return
        with self._voz_lock:
            self._decir(texto, self.sist.susurro if susurro is None else susurro)

    def _decir(self, texto: str, susurro: bool) -> None:
        log(f"Jarvis › {texto}" + (" (susurro)" if susurro else ""))
        self.ui.enviar(tipo="texto", jarvis=texto)
        self.ui.poner_estado("hablando")
        if not self.voz:
            return
        if self.mic:
            self.mic.mudo.set()                       # que no se escuche a sí mismo
        try:
            frases = [f for f in re.split(r"(?<=[.!?;:])\s+", texto) if f.strip()]
            sonando = None
            for i, frase in enumerate(frases):
                wav = TMP / f"frase_{i % 2}.wav"
                self.voz.sintetizar(frase, wav)
                if susurro:
                    bajar_volumen_wav(wav, VOLUMEN_SUSURRO)
                env = envolvente(wav)
                if sonando:
                    sonando.wait()
                self.ui.enviar(tipo="voz", env=env, paso=0.04)
                sonando = subprocess.Popen(self.voz.player + [str(wav)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if sonando:
                sonando.wait()
        finally:
            if self.mic:
                time.sleep(0.25)                      # el eco de la sala
                self.mic.vaciar()
                self.mic.mudo.clear()

    # ---------- permisos
    def confirmar(self, accion: str) -> bool:
        return self._si_o_no(accion, f"Voy a {accion}. ¿Lo confirmas?")

    def preguntar(self, pregunta: str) -> bool:
        """Una pregunta de sí o no (por voz o por Telegram)."""
        return self._si_o_no(pregunta, pregunta)

    def _si_o_no(self, accion: str, pregunta: str) -> bool:
        if getattr(self._canal, "tg", False):
            ok = self.tg.preguntar_si(accion, pregunta=pregunta)
            auditar("permiso", accion, aprobado=ok, canal="telegram")
            return ok
        if self.modo_texto:
            resp = input(f"   ⚠ {pregunta} (s/N): ").strip().lower()
            ok = resp in {"s", "si", "sí", "y", "yes"}
        else:
            self.decir(pregunta)
            self.ui.poner_estado("escuchando", "Esperando confirmación")
            audio = self.oyente.frase(max_espera=8)
            resp = self.escuchar(audio).lower() if audio is not None else ""
            ok = bool(re.search(r"\b(s[ií]|confirmo|adelante|vale|hazlo|correcto)\b", resp)) \
                and not re.search(r"\bno\b", resp)
        auditar("permiso", accion, aprobado=ok, respuesta=resp)
        return ok

    # ---------- cerebro
    def procesar(self, entrada: str, profundidad: int = 0) -> dict:
        """Decide la respuesta a una orden (de voz o de Telegram) sin hablar. Devuelve un diccionario."""
        llamado, resto = separar_nombre(entrada)
        if llamado and resto:                          # por Telegram también se escribe "Jarvis, …"
            entrada = resto
        if profundidad < 2:
            try:
                reescrito = self.aprende.reescribir(entrada, self._ultima_entrada)
            except Exception as e:
                log(f"error en aprendizaje: {e!r}")
                reescrito = None
            if reescrito:
                ordenes, motivo = reescrito
                log(f"aprendizaje: {motivo} → {ordenes}")
                auditar("aprendizaje", motivo, entrada=entrada, ordenes=ordenes)
                if not motivo.startswith("corrección") and profundidad == 0:
                    self._ultima_entrada = entrada
                return self._varias(ordenes, profundidad + 1)
        if profundidad == 0:
            self._ultima_entrada = entrada
            try:
                self.saber.observar(entrada)            # ¿cuenta algo de sí mismo que convenga recordar?
            except Exception as e:
                log(f"error en saber: {e!r}")
        if profundidad < 2 and self.cerebro.activo:
            r = self._con_cerebro(entrada)
            if r is not None:
                r["texto"] = variar(r["texto"])
                return r
        r = self._procesar_una(entrada, profundidad)
        r["texto"] = variar(r["texto"])
        return r

    # ---------- cerebro en la nube
    def _con_cerebro(self, entrada: str) -> dict | None:
        t0 = time.time()
        if time.time() - self._ultimo_dialogo > 600:
            self.dialogo = []                             # conversación nueva tras 10 minutos
        tg = getattr(self._canal, "tg", False)
        contexto = {"ordenes": ORDENES_CONOCIDAS, "memoria": memoria_para_ia(), "calendario": self.cal.contexto_ia(),
                    "telegram": tg}
        try:
            contexto["saber"] = self.saber.contexto(entrada)
        except Exception as e:
            log(f"error en saber: {e!r}")
        reciente = entrada + " " + " ".join(d["content"] for d in self.dialogo[-2:])
        if re.search(r"(?i)correo|e-?mail|\bmail|gmail|bandeja|contest|respond|escrib|l[eé]eme|mensaje", reciente):
            contexto["correo"] = self.correo.contexto_ia()
        try:
            plan = self.cerebro.interpretar(entrada, contexto, self.dialogo)
        except (SinConexion, ValueError, KeyError, TypeError) as e:
            log(f"cerebro nube: {e}; sigo en local")
            self.cerebro.al_cambiar()
            return None
        log(f"cerebro ({time.time() - t0:.1f}s): {json.dumps(plan, ensure_ascii=False)[:400]}")
        auditar("cerebro", entrada, plan=plan)
        textos, eventos, despues, archivo, susurro = [], [], [], None, None
        for a in plan.get("acciones", [])[:10]:
            if not isinstance(a, dict):
                continue
            tipo = a.get("tipo")
            if tipo not in TIPOS_CEREBRO and not str(tipo).startswith("correo_"):
                # el modelo a veces inventa tipos ("buscar en internet"): se convierte en una orden normal
                extra = a.get("texto") or a.get("consulta") or a.get("tema") or ""
                a = {"tipo": "orden", "texto": f"{str(tipo or '').replace('_', ' ')} {extra}".strip()}
                tipo = "orden"
                log(f"cerebro: tipo desconocido convertido en orden: {a['texto']}")
            try:
                if tipo == "evento":
                    eventos.append(self.cal.anadir_evento(a["fecha"], a.get("hora"), a.get("texto", "")))
                elif tipo == "recordatorio":
                    cuando = dt.datetime.fromisoformat(f"{a['fecha']}T{a.get('hora') or '09:00'}")
                    que = (a.get("texto") or "lo que me pediste").strip()
                    if cuando <= dt.datetime.now():
                        textos.append(f"La hora para «{que}» ya ha pasado. Dime otra.")
                        continue
                    self.sist.programar(cuando, que)
                    self.sist.al_crear(cuando, que)
                    textos.append(f"Te lo recuerdo {self._cuando_hablado(cuando)}: {que}.")
                elif tipo == "temporizador":
                    seg = int(a.get("segundos") or 0)
                    if seg > 0:
                        self.sist.programar(dt.datetime.now() + dt.timedelta(seconds=seg), "temporizador terminado")
                        textos.append(f"Temporizador de {self._duracion(seg)} en marcha.")
                elif tipo == "consultar":
                    textos.append(self.cal.consultar(a["desde"], a.get("hasta") or a["desde"]).texto)
                elif tipo == "borrar_evento":
                    textos.append(self.cal.borrar_id(str(a.get("id", ""))))
                elif tipo == "ver":
                    rv = self.vision.ver(str(a.get("fuente") or "pantalla"), entrada)   # la pregunta tal cual la dijiste
                    textos.append(rv.texto)
                    archivo = archivo or rv.archivo
                elif isinstance(tipo, str) and tipo.startswith("correo_"):
                    textos.append(self.correo.accion(a))
                elif tipo == "dato":
                    textos.append(self._guardar_dato(str(a.get("texto", ""))))
                elif tipo == "orden" and a.get("texto"):
                    r = self.procesar(str(a["texto"]), profundidad=2)
                    textos.append(r["texto"])
                    if r.get("despues"):
                        despues.append(r["despues"])
                    archivo = archivo or r.get("archivo")
                    if r.get("susurro") is not None:
                        susurro = r["susurro"]
            except (KeyError, ValueError, TypeError) as e:
                log(f"cerebro: acción mal formada {a}: {e!r}")
        if eventos:
            textos.insert(0, ("Apuntado en el calendario: " if len(eventos) == 1 else
                              f"Apuntadas {len(eventos)} cosas en el calendario: ") + "; ".join(eventos) + ".")
        respuesta = (plan.get("respuesta") or "").strip()
        if respuesta and any(textos) and "?" not in respuesta and len(respuesta) < 140 and re.match(
                r"(?i)^(voy a|ahora mismo|enseguida|en seguida|vale|perfecto|de acuerdo|hecho|listo|claro|entendido|"
                r"datos? guardados?|he guardado|informaci[oó]n (actualizada|guardada)|apuntado|anotado|buscando|"
                r"me pongo|ahora te|ya est[aá])", respuesta):
            respuesta = ""                                  # el módulo ya lo ha dicho: no repetirlo
        if respuesta:
            textos.append(respuesta if tg else limpiar_respuesta(respuesta, 5))
        texto = " ".join(dict.fromkeys(t for t in textos if t)).strip() or frase("no_entiendo")
        self.dialogo = (self.dialogo + [{"role": "user", "content": entrada},
                                        {"role": "assistant", "content": texto}])[-12:]
        self._ultimo_dialogo = time.time()
        auditar("respuesta", texto, origen="cerebro", segundos=round(time.time() - t0, 1))

        def todo():
            for d in despues:
                d()
        return {"texto": texto, "susurro": susurro, "despues": todo if despues else None, "archivo": archivo,
                "origen": "cerebro"}

    @staticmethod
    def _cuando_hablado(cuando: dt.datetime) -> str:
        from calendario import fecha_hablada, hora_hablada
        falta = cuando - dt.datetime.now()
        if falta < dt.timedelta(hours=1):
            minutos = max(1, round(falta.total_seconds() / 60))
            return f"dentro de {minutos} minuto{'s' if minutos != 1 else ''}"
        return f"{fecha_hablada(cuando.date())}{hora_hablada(f'{cuando:%H:%M}')}"

    @staticmethod
    def _duracion(seg: int) -> str:
        if seg < 60:
            return f"{seg} segundos"
        m, s = divmod(seg, 60)
        if m < 60:
            return f"{m} minuto{'s' if m != 1 else ''}" + (f" y {s} segundos" if s else "")
        h, m = divmod(m, 60)
        return f"{h} hora{'s' if h != 1 else ''}" + (f" y {m} minutos" if m else "")

    def _guardar_dato(self, dato: str) -> str:
        dato = dato.strip(" .")
        if not dato:
            return ""
        clave = normalizar(dato)
        previos = leer_memoria()
        igual = next((d for d in previos if normalizar(d["dato"]) == clave or
                      difflib.SequenceMatcher(None, normalizar(d["dato"]), clave).ratio() > 0.9), None)
        if igual:
            if time.time() - getattr(self, "_ultimo_dato_dicho", 0) < 120 or igual.get("fecha") == dt.date.today().isoformat() \
                    and igual.get("origen") == "observado":
                self._ultimo_dato_dicho = time.time()
                return f"Lo recordaré: {dato}."            # recién apuntado por el aprendizaje automático
            return "Eso ya lo tenía apuntado."
        previos.append({"dato": dato, "fecha": dt.date.today().isoformat()})
        guardar_memoria(previos)
        self.saber.consolidar_pronto()               # junta duplicados y actualiza lo que haya cambiado
        self.saber.avisar_panel(dato)
        self._ultimo_dato_dicho = time.time()
        return f"Lo recordaré: {dato}."

    def _varias(self, ordenes: list[str], profundidad: int) -> dict:
        textos, despues, archivo, susurro, origen = [], [], None, None, "aprendizaje"
        for o in ordenes:
            r = self.procesar(o, profundidad)
            textos.append(r["texto"])
            if r.get("despues"):
                despues.append(r["despues"])
            archivo = archivo or r.get("archivo")
            susurro = r["susurro"] if r.get("susurro") is not None else susurro
            if len(ordenes) == 1:
                origen = r.get("origen", origen)

        def todo():
            for d in despues:
                d()
        return {"texto": " ".join(t for t in textos if t), "susurro": susurro,
                "despues": todo if despues else None, "archivo": archivo, "origen": origen}

    def _procesar_una(self, entrada: str, profundidad: int) -> dict:
        t0 = time.time()
        for modulo, nombre in ((self.aprende, "aprendizaje"), (self.molestar, "molestar"), (self.ultimos, "ultimos"), (self.instalar, "instalar"), (self.medios, "medios"), (self.nex, "nex"), (self.saber, "saber"), (self.estudio, "estudio"), (self.oficina, "oficina"),
                               (self.creativo, "creativo"), (self.vision, "vision"),
                               (self.correo, "correo"),
                               (self.cal, "calendario"),
                               (self.sist, "sistema"),
                               (self.arch, "archivos"),
                               (self.cam, "camara"),
                               (self.mant, "mantenimiento"), (self.extras, "extras")):
            try:
                rs = modulo.manejar(entrada)
            except Exception as e:                   # un módulo nunca debe tumbar a Jarvis
                log(f"error en {nombre}: {e!r}")
                rs = None
            if rs is not None:
                auditar("respuesta", rs.texto, origen=nombre, segundos=round(time.time() - t0, 1))
                return {"texto": rs.texto, "susurro": rs.susurro, "despues": rs.despues, "archivo": rs.archivo,
                        "origen": nombre}
        respuesta, origen = None, "herramienta"
        try:
            r = self.herr.manejar(entrada)
        except Exception as e:
            log(f"error en herramienta: {e!r}")
            auditar("error", f"herramienta: {e!r}")
            r = None
        if r is not None:
            respuesta = r.texto
            if r.lista:
                self.ui.enviar(tipo="resultados", titulo=r.titulo, items=r.lista)
                if getattr(self._canal, "tg", False):          # en el móvil, la lista también
                    respuesta += "\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(r.lista[:8]))
            auditar("accion", r.titulo or "herramienta", entrada=entrada, lista=r.lista)
        if respuesta is None:
            respuesta = accion_local(entrada, self.confirmar)
            origen = "local"
        if respuesta is None and profundidad >= 2 and self.cerebro.activo:
            return {"texto": "Eso todavía no lo sé hacer.", "susurro": None, "despues": None, "archivo": None,
                    "origen": "llm"}
        if respuesta is None:
            origen = "llm"
            try:
                respuesta = self._charlar(entrada)
            except (urllib.error.URLError, OSError, KeyError) as e:
                respuesta = "No he podido hablar con el modelo."
                auditar("error", str(e))
            m = re.search(r"ORDEN\s*:\s*(.+)", respuesta)
            if m:
                canon = re.split(r"[.!?]\s", m.group(1).splitlines()[0] + " ")[0].strip(" .\"'«»<>")
                if re.match(r"^(y )?la orden", canon.lower()):
                    canon = ""
                if canon and profundidad < 2 and limpiar_orden(canon) != limpiar_orden(entrada):
                    log(f"IA: «{entrada}» parece la orden «{canon}»")
                    parecido = difflib.SequenceMatcher(None, limpiar_orden(canon), limpiar_orden(entrada)).ratio()
                    # la IA local adivina: si no se parece mucho a lo dicho, se pregunta antes de hacer nada
                    if parecido >= 0.75 or self.preguntar(f"No estoy seguro de haberte entendido. "
                                                         f"¿Quieres que haga esto: {canon}?"):
                        r2 = self.procesar(canon, profundidad + 1)
                        if r2.get("origen") != "llm":
                            return r2
                    else:
                        log(f"IA: no confirmado «{canon}» (parecido {parecido:.2f})")
                        auditar("respuesta", "no confirmado", origen="local")
                        return {"texto": "Vale, no hago nada. Dímelo con otras palabras.", "susurro": None,
                                "despues": None, "archivo": None, "origen": "local"}
                respuesta = frase("no_entiendo")
            else:
                self.historial += [{"role": "user", "content": entrada}, {"role": "assistant", "content": respuesta}]
        auditar("respuesta", respuesta, origen=origen, segundos=round(time.time() - t0, 1))
        return {"texto": respuesta, "susurro": None, "despues": None, "archivo": None, "origen": origen}

    def _charlar(self, entrada: str) -> str:
        ahora = time.time()
        if ahora - self._ultima_charla > OLVIDAR_CHARLA:
            self.historial = []                       # conversación nueva: no arrastra la anterior
        self._ultima_charla = ahora
        mensajes = self.historial + [{"role": "user", "content": entrada}]
        respuesta = preguntar_llm(mensajes)
        if "ORDEN" not in respuesta and any(
                difflib.SequenceMatcher(None, respuesta.lower(), r.lower()).ratio() > 0.72 for r in self._recientes):
            log("IA: respuesta repetida, pido otra")
            respuesta = preguntar_llm(mensajes, temperatura=1.0,
                                      extra=f"Hace poco ya dijiste: «{self._recientes[-1]}». Responde de forma "
                                            "distinta, con otras palabras y otro enfoque.")
        if "ORDEN" not in respuesta:
            self._recientes.append(respuesta)
        return respuesta

    def responder(self, entrada: str) -> None:
        auditar("entrada", entrada)
        self.ui.enviar(tipo="texto", usuario=entrada, jarvis="")
        self.ui.poner_estado("pensando")
        previo = getattr(self._canal, "respondiendo", False)
        self._canal.respondiendo = True                  # lo que se diga ahora es la respuesta: siempre suena
        try:
            with self._cerebro:
                r = self.procesar(entrada)
                if r.get("archivo") and str(r["archivo"]).endswith(".jpg"):   # la foto de la cámara se ve en el portátil
                    from herramientas import lanzar
                    lanzar(["xdg-open", r["archivo"]])
                self.decir(r["texto"], susurro=r["susurro"])
                if r["despues"]:
                    r["despues"]()
        finally:
            self._canal.respondiendo = previo

    # ---------- arranque
    def saludar(self) -> None:
        h = dt.datetime.now().hour
        saludo = "Buenos días" if 6 <= h < 14 else "Buenas tardes" if 14 <= h < 21 else "Buenas noches"
        nombre = f", {USUARIO}" if USUARIO else ""
        aviso = frase("aviso_voz") if not self.modo_texto else "Escríbeme cuando quieras."
        # Mientras saluda, cargamos el modelo de IA en memoria para que la primera respuesta sea rápida.
        threading.Thread(target=lambda: preguntar_llm([{"role": "user", "content": "hola"}], 1), daemon=True).start()
        self.tg.arrancar()
        self.cerebro.al_cambiar()
        self.ui.enviar(tipo="google", estado=self.google.estado())
        self.extras.actualizar_panel()
        self.sist.esperar_musica()                    # si suena la música de arranque, saluda al terminar
        self.decir(f"{saludo}{nombre}. {frase('en_linea')} {aviso}")
        # Primer saludo de la mañana: el resumen del día (si ya es la hora y no se ha dado)
        if self._resumen_pendiente():
            self._dar_resumen_manana(saludo=False)
        self.tg.anunciar_codigo()
        auditar("inicio", "sesion", llm=MODELO_LLM, modo="texto" if self.modo_texto else "voz")

    # ---------- bucles
    def bucle_voz(self) -> None:
        self._canal.respondiendo = True      # todo lo que se dice desde este hilo es contestar al usuario
        en_conversacion_hasta = 0.0
        while True:
            conversando = time.time() < en_conversacion_hasta
            self.ui.poner_estado("escuchando" if conversando else "reposo")
            espera = max(0.5, en_conversacion_hasta - time.time()) if conversando else None
            audio = self.oyente.frase(max_espera=espera)
            if audio is None:
                en_conversacion_hasta = 0.0
                continue
            if not conversando:
                # Filtro barato: solo miramos los 2,5 primeros segundos buscando "Jarvis".
                # La tele o una conversación larga se descartan en ~1 s en vez de transcribirse enteras.
                cabeza = self.oido.transcribir(audio[: int(RATE * 2.5)], silencioso=True)
                if not separar_nombre(cabeza)[0]:
                    continue
            self.ui.poner_estado("analizando")
            texto = self.escuchar(audio)
            if not texto:
                continue
            llamado, resto = separar_nombre(texto)
            if not llamado and not conversando:
                continue                              # no iba con Jarvis: ni se responde ni se guarda
            if llamado and not resto:
                self.decir(frase("si"))
                self.ui.poner_estado("escuchando")
                audio = self.oyente.frase(max_espera=8)
                if audio is None:
                    continue
                self.ui.poner_estado("analizando")
                resto = self.escuchar(audio)
                otra_vez, sin_nombre = separar_nombre(resto or "")
                if otra_vez:                          # "Jarvis, abre la terminal" después del "¿Sí?"
                    resto = sin_nombre
                if not resto:
                    continue
            peticion = resto if llamado else texto
            if re.fullmatch(r"(gracias|nada|eso es todo|ya est[aá]|olv[ií]dalo)[.!]*", peticion.lower().strip()):
                self.decir(frase("de_nada"))
                en_conversacion_hasta = 0.0
                continue
            self.responder(peticion)
            en_conversacion_hasta = time.time() + SEGUIMIENTO if SEGUIMIENTO > 0 else 0.0

    def bucle_texto(self) -> None:
        self._canal.respondiendo = True
        while True:
            self.ui.poner_estado("reposo")
            try:
                entrada = input("Tú › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if entrada.lower() in {"salir", "exit", "quit"}:
                break
            if entrada:
                self.responder(entrada)


def calibrar() -> None:
    mic = Microfono()
    print("Habla y calla para ver los niveles. Ctrl+C para salir.\n")
    try:
        while True:
            f = mic.leer(1)
            if f is not None:
                n = float(np.sqrt(np.mean(f ** 2)))
                print(f"{n:.4f} " + "█" * int(min(60, n * 600)), flush=True)
    except KeyboardInterrupt:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Jarvis v2")
    ap.add_argument("--texto", action="store_true", help="escribir por teclado en vez de escuchar")
    ap.add_argument("--mudo", action="store_true", help="sin voz")
    ap.add_argument("--calibrar", action="store_true", help="ver el nivel del micrófono")
    args = ap.parse_args()
    try:                                                  # las claves, solo legibles por la persona
        from secretos import asegurar_permisos
        corregidas = asegurar_permisos()
        if corregidas:
            log("claves protegidas (600): " + ", ".join(corregidas))
    except Exception as e:
        log(f"no he podido revisar los permisos de las claves: {e}")
    if args.calibrar:
        return calibrar()
    j = Jarvis(modo_texto=args.texto, mudo=args.mudo)
    j.saludar()
    try:
        j.bucle_texto() if args.texto else j.bucle_voz()
    except KeyboardInterrupt:
        pass
    auditar("fin", "sesion")


if __name__ == "__main__":
    main()
