"""
Visión de Jarvis: mira la pantalla, la cámara o una foto que le mandes por Telegram y te responde.

Órdenes (el cerebro en la nube también las entiende dichas de otras formas):
  "¿qué ves en la pantalla?" / "léeme el error" / "¿qué pone en la pantalla?"   → pantalla del portátil
  "¿qué hay en el monitor?" / "mira la otra pantalla"                          → monitor grande (ASUS)
  "¿qué tengo en la mano?" / "¿qué ves por la cámara?" / "¿cómo voy vestido?"  → webcam
  Por Telegram: manda una foto con el texto "¿qué es esto?" (o mándala y pregunta después).
La imagen solo sale del portátil cuando se lo pides, hacia el modelo con visión de Groq, y no se guarda en
Imágenes (va a una carpeta temporal y se borra).
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from herramientas import normalizar
from sistema import Respuesta

TMP = Path(tempfile.gettempdir()) / "jarvis"

INSTRUCCIONES = (
    "Eres los ojos de Jarvis, el asistente personal del usuario. Te pasan una imagen ({origen}) y una pregunta. "
    "Responde en español de España, directo y útil. Si hay un mensaje de error, léelo literalmente (lo importante) "
    "y explica en pocas frases la causa probable y cómo arreglarlo. Si te piden leer texto, transcríbelo. Si es un "
    "objeto, di qué es con seguridad razonable y, si dudas, dilo. No inventes detalles que no se vean. {formato}")
FORMATO_VOZ = "Tu respuesta se leerá en voz alta: máximo cuatro frases, sin listas, sin markdown ni símbolos."
FORMATO_TG = "Va por chat: puedes extenderte un poco y usar alguna lista corta si ayuda, sin markdown pesado."

RE_PANTALLA = re.compile(
    r"\b(que|cual) (ves|hay|pone|sale|aparece|tengo|estoy viendo|dice)\b.*\b(pantalla|monitor|escritorio)\b"
    r"|\b(mira|lee|leeme|revisa|analiza|describe|describeme|explicame)\w* (la |mi |el |esta |lo que hay en la |lo que "
    r"pone en la |lo que sale en la )?(pantalla|monitor|escritorio)\b"
    r"|\b(lee|leeme|explicame|que significa|que quiere decir|como arreglo|como soluciono)\w* (el |este |ese |lo del )?"
    r"(error|fallo|mensaje de error|aviso)\b|\bque (error|fallo) (me )?(sale|da|aparece|hay)\b"
    r"|\bque (estoy viendo|tengo abierto)\b")
RE_CAMARA = re.compile(
    r"\bque (tengo|llevo|sujeto|sostengo|te enseno|te muestro) en (la |las |mi |mis )?manos?\b"
    r"|\bque (ves|hay|estas viendo) (por|en|con) (la )?(camara|webcam)\b|\bque ves\b(?!.*\bpantalla)"
    r"|\bcomo (voy|estoy) (vestido|vestida|peinado|peinada)\b|\bque (llevo|tengo) puesto\b|\bcomo me ves\b"
    r"|\b(mira|lee|leeme) (esto|lo que te enseno|lo que tengo)\b|\bque es esto\b|\bque (pone|dice) (aqui|esto)\b"
    r"|\bcuantos dedos\b|\bde que color es (esto|lo que)\b|\bque te parece (como voy|mi )\b")
RE_MONITOR = re.compile(r"\b(monitor|otra pantalla|pantalla grande|pantalla de la izquierda|pantalla de jarvis)\b")
RE_TODAS = re.compile(r"\b(las dos pantallas|ambas pantallas|todas las pantallas)\b")


def _geometrias() -> dict[str, str]:
    """{'trabajo': 'WxH+X+Y', 'interfaz': …}: la pantalla donde se trabaja y la de la interfaz (pantallas.py)."""
    from pantallas import geometrias
    return geometrias()


def capturar_pantalla(cual: str = "portatil") -> Path | None:
    """cual: 'portatil', 'monitor' o 'todas'. Devuelve un JPG temporal."""
    if not shutil.which("scrot"):
        return None
    TMP.mkdir(parents=True, exist_ok=True)
    for viejo in TMP.glob("vision_*.jpg"):              # las que se mandaron al móvil, pasada una hora
        if time.time() - viejo.stat().st_mtime > 3600:
            viejo.unlink(missing_ok=True)
    ruta = TMP / f"vision_pantalla_{int(time.time())}.jpg"
    geo = _geometrias()
    clave = {"portatil": "trabajo", "monitor": "interfaz"}.get(cual)
    orden = ["scrot", "-o", "-q", "85"]
    if clave and geo.get(clave):
        w, h, x, y = map(int, re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", geo[clave]).groups())
        orden += ["-a", f"{x},{y},{w},{h}"]
    try:
        ok = subprocess.run(orden + [str(ruta)], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    return ruta if ok and ruta.exists() else None


class Vision:
    def __init__(self, cerebro, camara=None, log=print, ui=None, es_telegram: Callable[[], bool] | None = None):
        self.cerebro = cerebro
        self.camara = camara
        self.log = log
        self.ui = ui
        self.es_telegram = es_telegram or (lambda: False)
        self.foto_tg: tuple[Path, float] | None = None       # la última foto que mandaste por Telegram

    @property
    def disponible(self) -> bool:
        return bool(self.cerebro and self.cerebro.vision_activa)

    def recibida_por_telegram(self, ruta: Path) -> None:
        self.foto_tg = (ruta, time.time())

    def _foto_tg_reciente(self) -> Path | None:
        if self.foto_tg and time.time() - self.foto_tg[1] < 900 and self.foto_tg[0].exists():
            return self.foto_tg[0]
        return None

    # ---------- lo que hace
    def mirar(self, imagen: Path, pregunta: str, origen: str) -> str:
        tg = self.es_telegram()
        sistema = INSTRUCCIONES.format(origen=origen, formato=FORMATO_TG if tg else FORMATO_VOZ)
        datos = base64.b64encode(imagen.read_bytes()).decode()
        mime = "image/png" if imagen.suffix.lower() == ".png" else "image/jpeg"
        t0 = time.time()
        texto = self.cerebro.ver(f"data:{mime};base64,{datos}", sistema, pregunta, max_tokens=700 if tg else 350)
        self.log(f"visión ({origen}, {time.time() - t0:.1f}s): {texto[:160]}")
        return texto

    def ver(self, fuente: str, pregunta: str) -> Respuesta:
        """fuente: 'pantalla', 'monitor', 'pantallas', 'camara' o 'foto' (la de Telegram)."""
        from cerebro import SinConexion
        if not self.disponible:
            return Respuesta("Para mirar necesito el cerebro en la nube con visión, y ahora mismo no está disponible.")
        pregunta = pregunta.strip() or "¿Qué ves?"
        fuente = normalizar(str(fuente or "pantalla"))
        if fuente in ("mano", "manos", "yo", "persona", "cara", "usuario", "webcam", "camera", "objeto", "ropa"):
            fuente = "camara"
        elif fuente not in ("pantalla", "monitor", "pantallas", "camara", "foto"):
            fuente = "pantalla"
        if fuente == "monitor" and not re.search(r"monitor|pantalla grande|grande|asus|interfaz|panel|hud",
                                                 normalizar(pregunta)):
            fuente = "pantalla"     # en el monitor solo está la interfaz de Jarvis: las webs y programas, en el portátil
        borrar = True
        if fuente == "foto" or (fuente == "camara" and self.es_telegram() and self._foto_tg_reciente()):
            imagen, origen, borrar = self._foto_tg_reciente(), "una foto que te ha mandado el usuario desde el móvil", False
            if not imagen:
                return Respuesta("No tengo ninguna foto tuya reciente. Mándamela por aquí y pregúntame.")
        elif fuente == "camara":
            if not self.camara:
                return Respuesta("No tengo cámara.")
            imagen = self.camara.foto(destino=TMP)
            origen = "la webcam del portátil, apuntando al usuario"
            if not imagen:
                return Respuesta("No he podido usar la cámara. Puede que otro programa la esté usando.")
        else:
            cual = {"monitor": "monitor", "pantallas": "todas"}.get(fuente, "portatil")
            imagen = capturar_pantalla(cual)
            origen = {"monitor": "una captura del monitor grande, donde se ve la interfaz de Jarvis",
                      "todas": "una captura de las dos pantallas juntas"}.get(cual, "una captura de la pantalla del "
                                                                                "portátil, donde trabaja el usuario")
            if not imagen:
                return Respuesta("No he podido capturar la pantalla.")
        try:
            texto = self.mirar(imagen, pregunta, origen)
        except SinConexion as e:
            self.log(f"visión: {e}")
            texto = "No he podido mirarlo ahora mismo; el modelo con visión no responde. Inténtalo en un momento."
        archivo = None
        if self.es_telegram() and fuente != "foto" and imagen.exists() and len(texto) < 900:
            archivo = str(imagen)                         # en el móvil te llega también lo que he visto (pie ≤ 1024)
        elif borrar:
            imagen.unlink(missing_ok=True)
        if self.ui and not self.es_telegram():
            self.ui.enviar(tipo="resultados", titulo="Lo que veo", items=[texto[:300]])
        return Respuesta(texto or "No he sabido decir qué es.", archivo=archivo)

    # ---------- órdenes sin cerebro (o mandadas por él como "orden")
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        if re.search(r"\b(haz|hazme|saca|sacame|toma)\w*\s+(una\s+)?(captura|foto|pantallazo)\b", t):
            return None                                   # eso es una captura o una foto normal
        if RE_PANTALLA.search(t) or RE_TODAS.search(t):
            fuente = "pantallas" if RE_TODAS.search(t) else "monitor" if RE_MONITOR.search(t) else "pantalla"
            return self.ver(fuente, peticion)
        if self.es_telegram() and self._foto_tg_reciente() and (
                RE_CAMARA.search(t) or re.search(r"\b(la foto|esta foto|la imagen|esta imagen|que es|que ves|lee)\b", t)):
            return self.ver("foto", peticion)
        if RE_CAMARA.search(t):
            return self.ver("camara", peticion)
        return None
