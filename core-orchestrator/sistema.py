"""
Órdenes del sistema para Jarvis: volumen, modo susurro, recordatorios y apagar / reiniciar.

Igual que en herramientas.py, las órdenes se reconocen con reglas (no las decide la IA).
Apagar y reiniciar SIEMPRE piden confirmación de voz.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from perfil import DATOS, INSTALACION
from herramientas import guardar_config, leer_config, normalizar

HOME = Path.home()
RECORDATORIOS = DATOS / "recordatorios.json"
VOLUMEN_SUSURRO = 0.3          # la voz al 30 % cuando susurra


@dataclass
class Respuesta:
    texto: str
    susurro: bool | None = None            # None = lo que diga el modo actual
    despues: Callable[[], None] | None = None   # algo que hacer DESPUÉS de hablar (apagar…)
    archivo: str | None = None                 # un archivo para mandar por Telegram (capturas…)


# =============================================================== números dichos con palabras

UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
           "noventa": 90, "cien": 100, "ciento": 100}
NUM = (r"(\d+|(?:treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)(?: y \w+)?|cien|ciento|"
       + "|".join(sorted(UNIDADES, key=len, reverse=True)) + ")")


def a_numero(texto: str) -> int | None:
    texto = texto.strip()
    if texto.isdigit():
        return int(texto)
    partes = texto.split(" y ")
    if partes[0] in DECENAS:
        return DECENAS[partes[0]] + (UNIDADES.get(partes[1], 0) if len(partes) > 1 else 0)
    return UNIDADES.get(texto)


# =============================================================== volumen (PipeWire / PulseAudio / ALSA)

def _ejecutar(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def volumen_actual() -> int | None:
    if shutil.which("wpctl"):
        try:
            r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=5)
            m = re.search(r"([\d.]+)", r.stdout)
            if m:
                return round(float(m.group(1)) * 100)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("pactl"):
        try:
            r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=5)
            m = re.search(r"(\d+)%", r.stdout)
            if m:
                return int(m.group(1))
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def poner_volumen(cambio: str) -> bool:
    """cambio: '10%+', '10%-' o '50%'."""
    if shutil.which("wpctl"):
        return _ejecutar(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", cambio])
    if shutil.which("pactl"):
        valor = ("+" + cambio[:-1]) if cambio.endswith("+") else ("-" + cambio[:-1]) if cambio.endswith("-") else cambio
        return _ejecutar(["pactl", "set-sink-volume", "@DEFAULT_SINK@", valor])
    return _ejecutar(["amixer", "-q", "sset", "Master", cambio])


def silenciar(si: bool) -> bool:
    if shutil.which("wpctl"):
        return _ejecutar(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if si else "0"])
    if shutil.which("pactl"):
        return _ejecutar(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if si else "0"])
    return _ejecutar(["amixer", "-q", "sset", "Master", "mute" if si else "unmute"])


# =============================================================== música de arranque

PID_MUSICA = HOME / ".cache" / "jarvis_musica.pid"
SCRIPT_MUSICA = INSTALACION / "musica_arranque.sh"


def musica_sonando() -> int | None:
    try:
        pid = int(PID_MUSICA.read_text().strip())
        Path(f"/proc/{pid}").stat()
        return pid
    except (OSError, ValueError):
        return None


def parar_musica() -> bool:
    pid = musica_sonando()
    if not pid:
        return False
    try:
        import os
        import signal
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def hay_musica_arranque() -> bool:
    return any((INSTALACION / "musica").glob("arranque.*"))


# =============================================================== apagar / reiniciar

OBJETOS_ORDENADOR = ["ordenador", "portatil", "equipo", "pc", "computadora", "computador", "sistema",
                     "maquina", "ordenata"]

def apagar_o_reiniciar(reiniciar: bool) -> None:
    """Primero por la sesión de Xfce (no pide contraseña); si no, por systemd."""
    if shutil.which("xfce4-session-logout") and _ejecutar(
            ["xfce4-session-logout", "--reboot" if reiniciar else "--halt", "--fast"]):
        return
    _ejecutar(["systemctl", "reboot" if reiniciar else "poweroff"])


# =============================================================== recordatorios

def leer_recordatorios() -> list[dict]:
    try:
        return json.loads(RECORDATORIOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def guardar_recordatorios(lista: list[dict]) -> None:
    RECORDATORIOS.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECORDATORIOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RECORDATORIOS)


def hora_hablada(cuando: dt.datetime, ahora: dt.datetime | None = None) -> str:
    ahora = ahora or dt.datetime.now()
    dia = "" if cuando.date() == ahora.date() else \
        "mañana " if cuando.date() == ahora.date() + dt.timedelta(days=1) else f"el día {cuando.day} "
    return f"{dia}a las {cuando.hour}:{cuando.minute:02d}"


RE_EN = re.compile(r"\ben\s+(?:unos?\s+|unas?\s+)?(" + NUM[1:-1] + r"|media|un cuarto de)\s*"
                   r"(segundos?|minutos?|min|horas?|hora)\b")
RE_A_LAS = re.compile(r"\b(?:a las?|para las?)\s+(\d{1,2}|" + "|".join(sorted(UNIDADES, key=len, reverse=True)) + r")"
                      r"(?:(?::|\.|\s+y\s+|\s+)(\d{1,2}|media|cuarto|" + NUM[1:-1] + r"))?"
                      r"(?:\s+menos\s+(cuarto|\d{1,2}|" + NUM[1:-1] + r"))?"
                      r"(?:\s+(?:de la|por la)\s+(manana|tarde|noche|madrugada))?"
                      r"(?:\s+(?:en punto|horas))?")
RE_PEDIR = re.compile(r"^(?:recuerdame|recuerda me|recordarme|avisame|avisarme|pon(?:me)? un recordatorio"
                      r"(?: para| de)?|crea un recordatorio(?: para| de)?)\s+(.*)$")
RE_TEMPORIZADOR = re.compile(r"^(?:pon(?:me)?|crea|activa)\s+(?:un\s+)?(?:temporizador|alarma|cuenta atras)"
                             r"\s+(?:de|para dentro de|en)\s+(.+)$")


def interpretar_recordatorio(resto: str, ahora: dt.datetime) -> tuple[dt.datetime | None, str]:
    """Devuelve (cuándo, qué). resto = texto normalizado sin el 'recuérdame'."""
    cuando = None
    m = RE_EN.search(resto)
    if m:
        cant, unidad = m.group(1), m.group(2)
        if cant == "media":
            seg = 1800
        elif cant == "un cuarto de":
            seg = 900
        else:
            n = a_numero(cant) or 0
            seg = n * (1 if unidad.startswith("segundo") else 3600 if unidad.startswith("hora") else 60)
        if seg:
            cuando = ahora + dt.timedelta(seconds=seg)
            resto = (resto[:m.start()] + " " + resto[m.end():]).strip()
    else:
        sin_periodo = re.sub(r"\b(de|por) la manana\b", "", resto)
        manana = bool(re.search(r"\bmanana\b", sin_periodo))
        m = RE_A_LAS.search(resto)
        if m:
            h = a_numero(m.group(1))
            minuto = 0
            if m.group(2):
                minuto = 30 if m.group(2) == "media" else 15 if m.group(2) == "cuarto" else (a_numero(m.group(2)) or 0)
            if m.group(3):
                menos = 15 if m.group(3) == "cuarto" else (a_numero(m.group(3)) or 0)
                h, minuto = (h - 1) % 24, 60 - menos
            periodo = m.group(4)
            if h is not None and 0 <= h <= 23 and 0 <= minuto <= 59:
                if periodo in ("tarde", "noche") and h < 12:
                    h += 12
                base = ahora.replace(hour=h, minute=minuto, second=0, microsecond=0)
                if manana:
                    cuando = base + dt.timedelta(days=1)
                elif base > ahora:
                    cuando = base
                elif periodo is None and h < 12 and base + dt.timedelta(hours=12) > ahora:
                    cuando = base + dt.timedelta(hours=12)       # "a las 6" ya pasado → las 18
                else:
                    cuando = base + dt.timedelta(days=1)
                resto = (resto[:m.start()] + " " + resto[m.end():]).strip()
        resto = re.sub(r"\bmanana\b", "", resto).strip() if cuando else resto
    que = re.sub(r"^(que|de que|de|para|el|la)\s+", "", re.sub(r"\s+", " ", resto)).strip(" ,.")
    que = re.sub(r"\s+(que|de)$", "", que)
    return cuando, que


def con_tildes(original: str, fragmento: str) -> str:
    """Recupera del texto original (con tildes y mayúsculas) el trozo que encontramos ya normalizado."""
    if not fragmento:
        return fragmento
    orig = unicodedata.normalize("NFC", original)
    plano, pos = [], []
    for i, c in enumerate(orig):
        for d in unicodedata.normalize("NFD", c.lower()):
            if unicodedata.category(d) != "Mn":
                plano.append(d)
                pos.append(i)
    k = "".join(plano).find(fragmento)
    if k < 0:
        return fragmento
    return orig[pos[k]:pos[k + len(fragmento) - 1] + 1]


# =============================================================== el módulo

class Sistema:
    def __init__(self, decir: Callable[..., None], confirmar: Callable[[str], bool], ui=None, log=print):
        self.decir = decir
        self.confirmar = confirmar
        self.ui = ui
        self.log = log
        self.susurro = bool(leer_config().get("susurro", False))
        self.avisar: Callable[[str], None] = lambda texto: None   # Telegram lo sustituye si está activo
        self.al_crear: Callable[[dt.datetime, str], None] = lambda cuando, texto: None   # el calendario
        self._lock = threading.Lock()

    # ---------- recordatorios en segundo plano
    def arrancar_vigilante(self) -> None:
        threading.Thread(target=self._vigilar, daemon=True).start()

    def _vigilar(self) -> None:
        # Los que vencieron con el ordenador apagado se avisan al arrancar.
        time.sleep(20)
        while True:
            try:
                self._comprobar()
            except Exception as e:                       # nunca tumbar a Jarvis por un recordatorio
                self.log(f"error en recordatorios: {e!r}")
            time.sleep(5)

    def _comprobar(self) -> None:
        ahora = dt.datetime.now()
        with self._lock:
            lista = leer_recordatorios()
            vencidos = [r for r in lista if dt.datetime.fromisoformat(r["cuando"]) <= ahora]
            if not vencidos:
                return
            guardar_recordatorios([r for r in lista if r not in vencidos])
        for r in vencidos:
            retraso = (ahora - dt.datetime.fromisoformat(r["cuando"])).total_seconds()
            texto = r["texto"] or "lo que me pediste"
            aviso = (f"Mientras estaba apagado tenías un recordatorio: {texto}." if retraso > 300
                     else f"Te recuerdo: {texto}.")
            self.log(f"recordatorio: {texto}")
            if self.ui:
                self.ui.enviar(tipo="resultados", titulo="Recordatorio", items=[texto])
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", "-u", "critical", "Jarvis — Recordatorio", texto],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.avisar("⏰ " + aviso)
            self.decir(aviso, susurro=False)

    def programar(self, cuando: dt.datetime, que: str) -> None:
        with self._lock:
            lista = leer_recordatorios()
            lista.append({"cuando": cuando.isoformat(timespec="seconds"), "texto": que,
                          "creado": dt.datetime.now().isoformat(timespec="seconds")})
            lista.sort(key=lambda r: r["cuando"])
            guardar_recordatorios(lista)

    def desprogramar(self, cuando: dt.datetime, que: str) -> None:
        with self._lock:
            lista = leer_recordatorios()
            clave = cuando.isoformat(timespec="minutes")
            guardar_recordatorios([r for r in lista if not (r["cuando"][:16] == clave and
                                                            normalizar(r.get("texto", "")) == normalizar(que))])

    def _nuevo_recordatorio(self, resto: str, original: str = "") -> Respuesta:
        ahora = dt.datetime.now()
        cuando = None
        if not RE_EN.search(resto):                      # "el viernes a las 10", "el 3 de diciembre"…
            from calendario import interpretar_fecha, interpretar_hora
            fecha, sin_fecha = interpretar_fecha(resto, ahora.date())
            if fecha is not None:
                hora, sin_hora = interpretar_hora(sin_fecha)
                propuesta = dt.datetime.fromisoformat(f"{fecha}T{hora or '09:00'}")
                if propuesta > ahora:
                    cuando = propuesta
                    _, que = interpretar_recordatorio(sin_hora, ahora)
        if cuando is None:
            cuando, que = interpretar_recordatorio(resto, ahora)
        que = con_tildes(original, que) if original else que
        if cuando is None:
            return Respuesta("¿Cuándo te lo recuerdo? Dime, por ejemplo: recuérdame en diez minutos sacar la ropa, "
                             "o recuérdame el viernes a las seis llamar a mamá.")
        self.programar(cuando, que)
        try:
            self.al_crear(cuando, que)
        except Exception as e:
            self.log(f"calendario: no se pudo apuntar el recordatorio ({e!r})")
        falta = cuando - ahora
        if falta < dt.timedelta(hours=1):
            minutos = round(falta.total_seconds() / 60)
            plazo = f"dentro de {round(falta.total_seconds())} segundos" if minutos < 1 else \
                f"dentro de {minutos} minuto{'s' if minutos != 1 else ''}"
        else:
            plazo = hora_hablada(cuando, ahora)
            if (cuando.date() - ahora.date()).days > 1:
                from calendario import fecha_hablada
                plazo = f"{fecha_hablada(cuando.date(), ahora.date())} a las {cuando.hour}:{cuando.minute:02d}"
        return Respuesta(f"Hecho. Te lo recuerdo {plazo}" + (f": {que}." if que else "."))

    def _listar(self) -> Respuesta:
        lista = leer_recordatorios()
        if not lista:
            return Respuesta("No tienes recordatorios pendientes.")
        items = [f"{hora_hablada(dt.datetime.fromisoformat(r['cuando']))} — {r['texto'] or 'recordatorio'}" for r in lista]
        if self.ui:
            self.ui.enviar(tipo="resultados", titulo="Recordatorios", items=items)
        n = len(lista)
        return Respuesta(f"Tienes {n} recordatorio{'s' if n > 1 else ''}. " + ". ".join(items[:3]) + ".")

    def _cuanto_falta(self) -> Respuesta:
        lista = leer_recordatorios()
        if not lista:
            return Respuesta("No hay ningún temporizador ni recordatorio en marcha.")
        r = lista[0]                                    # están ordenados: el más próximo primero
        falta = dt.datetime.fromisoformat(r["cuando"]) - dt.datetime.now()
        seg = max(0, round(falta.total_seconds()))
        if seg < 60:
            plazo = f"{seg} segundos"
        elif seg < 3600:
            m, s = divmod(seg, 60)
            plazo = f"{m} minuto{'s' if m != 1 else ''}" + (f" y {s} segundos" if s and m < 5 else "")
        else:
            h, m = divmod(seg // 60, 60)
            plazo = f"{h} hora{'s' if h != 1 else ''}" + (f" y {m} minutos" if m else "")
        que = r["texto"] or "el recordatorio"
        que = "el temporizador" if que == "temporizador terminado" else que
        return Respuesta(f"Faltan {plazo} para {que}.")

    def esperar_musica(self, maximo: float = 400) -> None:
        """Al arrancar, espera a que acabe la música (empieza un poco antes que Jarvis)."""
        fin = time.time() + maximo
        while time.time() < fin and musica_sonando():
            time.sleep(0.5)

    # ---------- entrada
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        t = re.sub(r"^(por favor|oye|venga)\s+", "", t)

        # --- recordatorios
        if re.search(r"\b(que|cuales) recordatorios\b|\bmis recordatorios\b|\btengo (algun|algo) recordatorio", t):
            return self._listar()
        if re.search(r"\b(cuanto|cuantos minutos|cuanto tiempo)\b.*\b(falta|queda|va|lleva)\w*|\bpor cuanto va\b"
                     r"|\b(falta|queda)\w* (mucho|poco)\b", t) and re.search(r"temporizador|alarma|recordatorio|falta|queda", t):
            return self._cuanto_falta()
        if re.search(r"\b(borra|cancela|elimina|quita)\w*\s+(todos )?(los |mis |el |ese )?recordatorios?\b", t):
            n = len(leer_recordatorios())
            if n and not self.confirmar(f"borrar {'tu recordatorio pendiente' if n == 1 else f'tus {n} recordatorios pendientes'}"):
                return Respuesta("Vale, no borro nada.")
            with self._lock:
                guardar_recordatorios([])
            return Respuesta("Recordatorios borrados." if n else "No había ningún recordatorio.")
        m = RE_TEMPORIZADOR.match(t)
        if m:
            return self._nuevo_recordatorio("en " + m.group(1) + " temporizador terminado")
        m = RE_PEDIR.match(t)
        if m:
            return self._nuevo_recordatorio(m.group(1), peticion)

        # --- susurro
        m = re.match(r"^susurr\w*\s+(?:que\s+)?(.+)$", t)
        if m and not re.match(r"^(modo|un poco|mas|siempre)\b", m.group(1)):
            original = re.sub(r"^\W*\w+\s+(que\s+)?", "", peticion.strip(), count=1)
            return Respuesta(original.strip(" .") + ".", susurro=True)
        if re.search(r"^susurr\w*$|\bmodo susurro\b(?!.*\b(quita|desactiva|apaga))|\bhabla(me)? (mas )?(bajo|bajito|flojo|flojito)"
                     r"|\bhabla(me)? en voz baja|\bsusurra(me)? (siempre|un poco)", t) \
                and not re.search(r"\b(quita|desactiva|apaga|deja)\w*\b", t):
            self.susurro = True
            guardar_config(susurro=True)
            return Respuesta("Vale, hablaré en voz baja.", susurro=True)
        if re.search(r"\bhabla(me)? (normal|mas alto|en voz alta|fuerte)|\bdeja de susurrar|\b(quita|desactiva|apaga)\w* "
                     r"(el )?modo susurro|\bno susurres", t):
            self.susurro = False
            guardar_config(susurro=False)
            return Respuesta("De acuerdo, vuelvo a hablar normal.", susurro=False)

        # --- música de arranque
        if re.search(r"\b(para|quita|apaga|deten|detén|corta|stop)\w*\b.*\b(musica|cancion|thunderstruck)\b"
                     r"|^(para|basta|silencio|stop)$", t) and musica_sonando():
            parar_musica()
            return Respuesta("Música parada.")
        if re.search(r"\b(pon|ponme|toca|reproduce|suena)\w*\b.*\b(musica de arranque|cancion de arranque|thunderstruck"
                     r"|thunder struck|tander\w*|ac ?dc|acdc)\b", t):
            if not hay_musica_arranque():
                return Respuesta("No tengo la música de arranque. Copia la canción en la carpeta jarvis, musica, "
                                 "con el nombre arranque.")
            if not musica_sonando():
                subprocess.Popen(["bash", str(SCRIPT_MUSICA)], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return Respuesta("Ahí va.")

        # --- volumen
        if re.search(r"\b(silencia\w*|mutea\w*)\b|\bquita\w* el (sonido|volumen)\b|\bsin sonido\b", t):
            silenciar(True)
            return Respuesta("Silenciado.")
        if re.search(r"\bquita\w* (el )?silencio\b|\bdesilencia\w*|\bactiva\w* el sonido\b|\bpon(me)? sonido\b", t):
            silenciar(False)
            return Respuesta(f"Sonido activado. Volumen al {volumen_actual() or '?'} por ciento.")
        if (re.search(r"\b(volumen|sonido|musica)\b", t) or re.search(r"\b(sube|subele|baja|bajale)\b", t)) \
                and not re.search(r"\b(internet|pagina|web|google|busca\w*|busqu\w*|persiana|archivo|descarga\w*)\b", t):
            m = re.search(r"\b(?:al?|en)\s+" + NUM + r"(?:\s*(?:%|por ?ciento))?\b", t)
            n = a_numero(m.group(1)) if m else None
            if re.search(r"\b(maximo|a tope|al 100)\b", t):
                n = 100
            if n is not None and 0 <= n <= 100 and re.search(r"\b(pon|ponme|deja|cambia|sube|baja|volumen)\w*\b", t):
                silenciar(False)
                poner_volumen(f"{n}%")
                return Respuesta(f"Volumen al {n} por ciento.")
            paso = "20%" if re.search(r"\b(mucho|bastante)\b", t) else "10%"
            if re.search(r"\b(sube\w*|subir|mas alto|aumenta\w*|mas volumen|mas fuerte)\b", t):
                silenciar(False)
                poner_volumen(paso + "+")
                return Respuesta(f"Volumen al {volumen_actual() or '?'} por ciento.")
            if re.search(r"\b(baja\w*|bajar|mas bajo|disminuye\w*|menos volumen|reduce\w*)\b", t):
                poner_volumen(paso + "-")
                return Respuesta(f"Volumen al {volumen_actual() or '?'} por ciento.", susurro=None)
            if re.search(r"\b(que|cual|como)\b.*\bvolumen\b|\bvolumen (tengo|hay|esta)\b", t):
                return Respuesta(f"El volumen está al {volumen_actual() or '?'} por ciento.")

        # --- apagar / reiniciar
        # Tolerante a lo que whisper oye mal: "reinicial portadil", "reinici el portátil", "apagal ordenador"…
        palabras = t.split()
        reiniciar = any(w.startswith("reinic") or w.startswith("reinisi") for w in palabras)
        apagar = any(w.startswith("apag") for w in palabras)
        objeto = re.search(r"^(apagate|reiniciate|apagat|reiniciat)", t) or any(
            difflib.get_close_matches(w, OBJETOS_ORDENADOR, n=1, cutoff=0.72) for w in palabras if len(w) >= 2)
        if (reiniciar or apagar) and objeto:
            accion = "reiniciar el ordenador" if reiniciar else "apagar el ordenador"
            if not self.confirmar(accion):
                return Respuesta("Vale, no hago nada.")
            es_reinicio = bool(reiniciar)
            return Respuesta("Reiniciando. Ahora vuelvo." if es_reinicio else "Apagando. Hasta luego.",
                             despues=lambda: apagar_o_reiniciar(es_reinicio))
        if re.search(r"\b(suspende\w*|hiberna\w*)\b", t) and objeto:
            if not self.confirmar("suspender el ordenador"):
                return Respuesta("Vale, no hago nada.")
            return Respuesta("Suspendiendo.", despues=lambda: (
                _ejecutar(["xfce4-session-logout", "--suspend"]) or _ejecutar(["systemctl", "suspend"])))
        return None
