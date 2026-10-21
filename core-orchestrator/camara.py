"""
Cámara del portátil para Jarvis.

- Presencia: detecta tu cara (OpenCV, muy ligero: 1 imagen cada 1,5 s a 320x240). Cuando vuelves tras un rato
  fuera, Jarvis te da la bienvenida y te dice lo pendiente.
- Vigilancia: si la activas y hay movimiento, hace una foto y te la manda por Telegram.
- Fotos con la cámara por voz o desde Telegram ("hazme una foto", "foto de la cámara").
Nada se graba ni se envía salvo las fotos que pides y las de vigilancia.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from pathlib import Path
from typing import Callable

from frases import frase
from herramientas import carpeta_usuario, guardar_config, leer_config, normalizar
from sistema import Respuesta

AUSENTE_TRAS = 120          # segundos sin ver cara para darte por ausente
BIENVENIDA_TRAS = 300       # si estuviste fuera al menos esto, te saluda al volver


class Camara:
    def __init__(self, decir: Callable[..., None], ui=None, log=print,
                 avisar: Callable[[str], None] | None = None,
                 avisar_foto: Callable[[str, str], None] | None = None,
                 bienvenida: Callable[[float], str] | None = None):
        self.decir = decir
        self.ui = ui
        self.log = log
        self.avisar = avisar or (lambda t: None)
        self.avisar_foto = avisar_foto or (lambda ruta, pie: None)
        self.bienvenida = bienvenida or (lambda minutos: "")
        cfg = leer_config()
        self.activa = cfg.get("camara", True)
        self.vigilancia = cfg.get("vigilancia", False)
        self._lock = threading.Lock()
        self._ultimo_frame = None
        self._ultima_cara = 0.0
        self._presente = False
        self._ausente_desde = time.time()
        self._ultimo_movimiento = 0.0
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self.disponible = True
        self._foto_lock = threading.Lock()

    # ---------- bucle
    def arrancar(self) -> None:
        if self.activa or self.vigilancia:
            self._lanzar()

    def _lanzar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def _detener(self) -> None:
        self._parar.set()

    def _estado_ui(self) -> None:
        if not self.ui:
            return
        if not (self.activa or self.vigilancia):
            estado = "apagada"
        elif self.vigilancia:
            estado = "vigilando"
        else:
            estado = "te veo" if self._presente else "nadie"
        self.ui.enviar(tipo="camara", estado=estado)

    def _bucle(self) -> None:
        try:
            import cv2
        except ImportError:
            self.log("cámara: falta OpenCV (pip install opencv-python-headless)")
            self.disponible = False
            return
        for _ in range(10):                      # otro hilo puede estar importando OpenCV a la vez
            if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
                break
            time.sleep(1)
        try:
            caras = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception as e:
            self.log(f"cámara: sin detector de caras ({e}); solo movimiento")
            caras = None
        cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        if not cap.isOpened():
            self.log("cámara: no se puede abrir /dev/video0")
            self.disponible = False
            return
        self.log("cámara: encendida")
        anterior = None
        try:
            while not self._parar.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(2)
                    continue
                with self._lock:
                    self._ultimo_frame = frame
                gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                ahora = time.time()

                if self.activa:
                    encontradas = () if caras is None else caras.detectMultiScale(cv2.equalizeHist(gris), scaleFactor=1.2, minNeighbors=5,
                                                         minSize=(40, 40))
                    if len(encontradas):
                        self._ultima_cara = ahora
                        if not self._presente:
                            fuera = ahora - self._ausente_desde
                            self._presente = True
                            self._estado_ui()
                            if fuera >= BIENVENIDA_TRAS:
                                texto = self.bienvenida(fuera / 60)
                                if texto:
                                    self.decir(texto)
                    elif self._presente and ahora - self._ultima_cara > AUSENTE_TRAS:
                        self._presente = False
                        self._ausente_desde = self._ultima_cara
                        self._estado_ui()

                if self.vigilancia:
                    suave = cv2.GaussianBlur(gris, (21, 21), 0)
                    if anterior is not None:
                        diferencia = cv2.threshold(cv2.absdiff(anterior, suave), 25, 255, cv2.THRESH_BINARY)[1]
                        cambio = cv2.countNonZero(diferencia) / diferencia.size
                        if cambio > 0.03 and ahora - self._ultimo_movimiento > 60:
                            self._ultimo_movimiento = ahora
                            ruta = self._guardar(frame, "Vigilancia")
                            self.log(f"cámara: movimiento detectado ({cambio:.0%}) → {ruta}")
                            self.avisar_foto(str(ruta), f"🚨 Movimiento detectado a las {dt.datetime.now():%H:%M}")
                    anterior = suave
                else:
                    anterior = None

                if not (self.activa or self.vigilancia):
                    break
                self._parar.wait(1.5)
        finally:
            cap.release()
            with self._lock:
                self._ultimo_frame = None
            self.log("cámara: apagada")
            self._estado_ui()

    # ---------- fotos
    def _guardar(self, frame, prefijo: str = "Foto", destino: Path | None = None) -> Path:
        import cv2
        carpeta = destino or carpeta_usuario("PICTURES") / "Cámara"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / (f"vision_camara_{int(time.time())}.jpg" if destino else
                          f"{prefijo}_{dt.datetime.now():%Y-%m-%d_%H-%M-%S}.jpg")
        cv2.imwrite(str(ruta), frame)
        return ruta

    def foto(self, destino: Path | None = None) -> Path | None:
        """Foto a buena resolución (abre la cámara un momento; si el bucle la tiene, la suelta antes).
        Con destino, se guarda allí (las de la visión van a una carpeta temporal, no a Imágenes)."""
        try:
            import cv2
        except ImportError:
            return None
        with self._foto_lock:
            en_marcha = bool(self._hilo and self._hilo.is_alive())
            if en_marcha:
                self._detener()
                self._hilo.join(timeout=6)
            try:
                cap = None
                for _ in range(6):                     # el dispositivo tarda un instante en quedar libre
                    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
                    if cap.isOpened():
                        break
                    cap.release()
                    time.sleep(0.5)
                if not cap or not cap.isOpened():
                    self.log("cámara: no se pudo abrir para la foto")
                    return None
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                frame, fin = None, time.time() + 4
                leidas = 0
                while time.time() < fin:               # las primeras salen oscuras mientras ajusta la luz
                    ok, f = cap.read()
                    if ok:
                        frame, leidas = f, leidas + 1
                        if leidas >= 10 and float(f.mean()) > 25:
                            break
                cap.release()
                if frame is None:
                    self.log("cámara: abierta pero sin imagen")
                    return None
                ruta = self._guardar(frame, destino=destino)
                if not ruta.exists():
                    self.log(f"cámara: no se pudo guardar {ruta}")
                    return None
                self.log(f"cámara: foto {ruta.name} ({frame.shape[1]}x{frame.shape[0]})")
                if destino is None:
                    from ultimos import apuntar
                    apuntar(ruta, "foto")
                return ruta
            finally:
                if en_marcha:
                    self._lanzar()

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        if re.search(r"\b(pantalla|captura|pantallazo|internet|google|busca\w*|busqu\w*)\b", t):
            return None
        # Whisper oye "hace una foto", "realiza mi foto", "apme un a foto"... basta con que salga la palabra.
        if re.search(r"\b(foto|fotito|fotografia|selfie|autofoto|retrato)\b", t) \
                and not re.search(r"\b(abre|ensena|ensename|muestra|muestrame|ver|mira|borra|carpeta)\w*\b.*\bfotos?\b|\b(esta|esa) foto\b|\bla foto que\b", t):
            ruta = self.foto()
            if not ruta:
                return Respuesta("No he podido usar la cámara. Puede que otro programa la esté usando.")
            if re.search(r"\b(manda|mandame|envia|enviame|pasame)\w*\b|\b(movil|telefono|telegram)\b", t):
                self.avisar_foto(str(ruta), "📷 La foto que me has pedido")
            return Respuesta(f"{frase('foto')} La tienes en Imágenes, carpeta Cámara.", archivo=str(ruta))
        if re.search(r"\b(activa|enciende|pon|conecta)\w*\s+(la |el )?(modo )?vigilancia\b|\bvigila (la casa|esto|la habitacion)", t):
            self.vigilancia = True
            guardar_config(vigilancia=True)
            self._lanzar()
            self._estado_ui()
            return Respuesta("Vigilancia activada. Si veo movimiento te mando una foto por Telegram.")
        if re.search(r"\b(desactiva|apaga|quita|para|deten)\w*\s+(la |el )?(modo )?vigilancia\b", t):
            self.vigilancia = False
            guardar_config(vigilancia=False)
            if not self.activa:
                self._detener()
            self._estado_ui()
            return Respuesta("Vigilancia desactivada.")
        if re.search(r"\b(apaga|desactiva|desconecta|quita)\w*\s+(la )?(camara|webcam)\b|\bdeja de mirarme\b", t):
            self.activa = False
            guardar_config(camara=False)
            if not self.vigilancia:
                self._detener()
            self._estado_ui()
            return Respuesta("Cámara apagada. Ya no te veo.")
        if re.search(r"\b(enciende|activa|conecta|pon)\w*\s+(la )?(camara|webcam)\b", t):
            self.activa = True
            guardar_config(camara=True)
            self._lanzar()
            self._estado_ui()
            return Respuesta("Cámara encendida. Te saludaré cuando vuelvas.")
        if re.search(r"\b(me ves|estoy aqui|me estas viendo)\b", t):
            if not self.activa:
                return Respuesta("Tengo la cámara apagada. Dime: enciende la cámara.")
            return Respuesta(frase("te_veo") if self._presente else frase("no_te_veo"))
        return None
