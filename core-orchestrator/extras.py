"""
Extras de Jarvis: estado del ordenador y avisos, cálculos y conversiones, dictado, capturas de pantalla,
noticias, memoria personal ("recuerda que…") y resumen de buenos días.

Como el resto: órdenes reconocidas con reglas. La IA no decide acciones.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import math
import operator
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from herramientas import (CODIGOS_TIEMPO, carpeta_usuario, guardar_config, http_json, leer_config, normalizar)
from sistema import Respuesta, a_numero, con_tildes, hora_hablada, interpretar_recordatorio, leer_recordatorios

HOME = Path.home()
MEMORIA = HOME / "jarvis" / "memoria.json"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def num_es(x: float, dec: int = 2) -> str:
    """12345.5 -> '12.345,5' (formato español, sin ceros de sobra)."""
    if abs(x - round(x)) < 1e-9:
        s = f"{int(round(x)):,}".replace(",", ".")
        return s
    s = f"{x:,.{dec}f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# =============================================================== estado del ordenador

def _leer(ruta: str) -> str:
    try:
        return Path(ruta).read_text().strip()
    except OSError:
        return ""


def _cpu_tiempos() -> tuple[int, int]:
    partes = [int(x) for x in _leer("/proc/stat").splitlines()[0].split()[1:]]
    inactivo = partes[3] + (partes[4] if len(partes) > 4 else 0)
    return sum(partes), inactivo


def uso_cpu(muestra: float = 0.4) -> int:
    try:
        t1, i1 = _cpu_tiempos()
        time.sleep(muestra)
        t2, i2 = _cpu_tiempos()
        return round(100 * (1 - (i2 - i1) / max(1, t2 - t1)))
    except (IndexError, ValueError):
        return 0


def uso_memoria() -> int:
    info = {}
    for linea in _leer("/proc/meminfo").splitlines():
        k, _, v = linea.partition(":")
        info[k] = int(v.split()[0]) if v.split() else 0
    total = info.get("MemTotal", 1)
    return round(100 * (1 - info.get("MemAvailable", total) / total))


def temperatura() -> int | None:
    """La más alta de los sensores de la CPU (k10temp en AMD) o, si no, de las zonas térmicas."""
    valores = []
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        nombre = _leer(str(hw / "name"))
        if nombre in ("k10temp", "coretemp", "zenpower", "acpitz", "cpu_thermal"):
            for f in hw.glob("temp*_input"):
                try:
                    valores.append(int(f.read_text()) / 1000)
                except (OSError, ValueError):
                    pass
    if not valores:
        for z in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                valores.append(int(z.read_text()) / 1000)
            except (OSError, ValueError):
                pass
    valores = [v for v in valores if 5 < v < 130]
    return round(max(valores)) if valores else None


def bateria() -> tuple[int, str] | None:
    for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        cap = _leer(str(b / "capacity"))
        if cap.isdigit():
            return int(cap), _leer(str(b / "status")).lower()      # charging / discharging / full / not charging
    return None


def disco_libre() -> tuple[float, int]:
    u = shutil.disk_usage(str(HOME))
    return u.free / 1e9, round(100 * u.used / u.total)


def estado_ordenador() -> dict:
    bat = bateria()
    libre, usado = disco_libre()
    return {"cpu": uso_cpu(), "ram": uso_memoria(), "temp": temperatura(),
            "bat": bat[0] if bat else None, "bat_estado": bat[1] if bat else "",
            "disco_libre": round(libre, 1), "disco_usado": usado}


def estado_hablado(e: dict) -> str:
    partes = [f"El procesador va al {e['cpu']} por ciento", f"la memoria al {e['ram']}"]
    if e["temp"] is not None:
        partes.append(f"la temperatura es de {e['temp']} grados")
    if e["bat"] is not None:
        estado = {"charging": ", cargando", "full": ", completa", "discharging": ", sin enchufar"}.get(e["bat_estado"], "")
        partes.append(f"la batería está al {e['bat']} por ciento{estado}")
    partes.append(f"quedan {num_es(e['disco_libre'], 0)} gigas libres en el disco")
    texto = ", ".join(partes[:-1]) + " y " + partes[-1] + "."
    if e["temp"] is not None and e["temp"] >= 85:
        texto += " Está bastante caliente: conviene que respire bien."
    if e["ram"] >= 90:
        texto += " La memoria va muy justa."
    return texto


# =============================================================== cálculos

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _evaluar(nodo):
    if isinstance(nodo, ast.Expression):
        return _evaluar(nodo.body)
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OPS:
        a, b = _evaluar(nodo.left), _evaluar(nodo.right)
        if isinstance(nodo.op, ast.Pow) and abs(b) > 100:
            raise ValueError("exponente demasiado grande")
        return _OPS[type(nodo.op)](a, b)
    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OPS:
        return _OPS[type(nodo.op)](_evaluar(nodo.operand))
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "sqrt" and len(nodo.args) == 1:
        return math.sqrt(_evaluar(nodo.args[0]))
    raise ValueError("expresión no permitida")


def _palabras_a_numeros(t: str) -> str:
    """'veinte y cinco' / 'tres' -> dígitos, sin tocar lo que ya son dígitos."""
    def sustituir(m):
        n = a_numero(m.group(0))
        return str(n) if n is not None else m.group(0)
    patron = (r"\b(?:treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)(?: y (?:uno|una|un|dos|tres|cuatro|"
              r"cinco|seis|siete|ocho|nueve))?\b|\b(?:cero|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|"
              r"once|doce|trece|catorce|quince|dieciseis|diecisiete|dieciocho|diecinueve|veinte|veintiuno|veintidos|"
              r"veintitres|veinticuatro|veinticinco|veintiseis|veintisiete|veintiocho|veintinueve|cien)\b")
    return re.sub(patron, sustituir, t)


def calcular(texto: str) -> float | None:
    t = _palabras_a_numeros(re.sub(r"^(la|el|lo)\s+", "", texto.strip()))
    t = re.sub(r"(\d)\.(\d{3})(?!\d)", r"\1\2", t)            # 1.500 -> 1500 (millares)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)                      # 3,5 -> 3.5
    m = re.fullmatch(r"\s*el\s+([\d.]+)\s*(?:%|por ?ciento)\s+de\s+([\d.]+)\s*", t) or \
        re.fullmatch(r"\s*([\d.]+)\s*(?:%|por ?ciento)\s+de\s+([\d.]+)\s*", t)
    if m:
        return float(m.group(1)) * float(m.group(2)) / 100
    reemplazos = [
        (r"raiz cuadrada de\s+([\d.]+)", r"sqrt(\1)"), (r"\bal cuadrado\b", "**2"), (r"\bal cubo\b", "**3"),
        (r"\belevado a( la)?\b", "**"), (r"\bmultiplicado por\b|\bpor\b|\bx\b|×", "*"),
        (r"\bdividido (entre|por)\b|\bentre\b|÷", "/"), (r"\bmas\b", "+"), (r"\bmenos\b", "-"),
        (r"\babre parentesis\b", "("), (r"\bcierra parentesis\b", ")"),
    ]
    for patron, sust in reemplazos:
        t = re.sub(patron, sust, t)
    t = t.replace("^", "**").strip(" ?=")
    if not re.fullmatch(r"[\d.\s+\-*/()%sqrt]+", t) or not re.search(r"\d", t):
        return None
    try:
        return float(_evaluar(ast.parse(t, mode="eval")))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


# =============================================================== conversiones

UNIDADES = {   # nombre: (magnitud, factor a la unidad base)
    "kilometro": ("long", 1000), "km": ("long", 1000), "metro": ("long", 1), "m": ("long", 1),
    "centimetro": ("long", 0.01), "cm": ("long", 0.01), "milimetro": ("long", 0.001), "mm": ("long", 0.001),
    "milla": ("long", 1609.344), "pie": ("long", 0.3048), "pulgada": ("long", 0.0254), "yarda": ("long", 0.9144),
    "kilo": ("masa", 1000), "kilogramo": ("masa", 1000), "kg": ("masa", 1000), "gramo": ("masa", 1),
    "g": ("masa", 1), "libra": ("masa", 453.59237), "onza": ("masa", 28.349523), "tonelada": ("masa", 1e6),
    "litro": ("vol", 1), "l": ("vol", 1), "mililitro": ("vol", 0.001), "ml": ("vol", 0.001),
    "galon": ("vol", 3.785411784), "centilitro": ("vol", 0.01), "cl": ("vol", 0.01),
    "segundo": ("tiempo", 1), "minuto": ("tiempo", 60), "hora": ("tiempo", 3600), "dia": ("tiempo", 86400),
    "semana": ("tiempo", 604800),
    "kilometro por hora": ("vel", 1 / 3.6), "km/h": ("vel", 1 / 3.6), "milla por hora": ("vel", 0.44704),
    "metro por segundo": ("vel", 1), "nudo": ("vel", 0.514444),
    "byte": ("datos", 1), "kilobyte": ("datos", 1e3), "megabyte": ("datos", 1e6), "mega": ("datos", 1e6),
    "gigabyte": ("datos", 1e9), "giga": ("datos", 1e9), "terabyte": ("datos", 1e12), "tera": ("datos", 1e12),
}
TEMP = {"celsius": "c", "centigrado": "c", "grados celsius": "c", "fahrenheit": "f", "grados fahrenheit": "f",
        "kelvin": "k"}


def _unidad(s: str) -> str | None:
    s = s.strip().removeprefix("grados ").strip()
    candidatos = [s, s.rstrip("s"), re.sub(r"es$", "", s), re.sub(r"(\w+)s (por \w+)", r"\1 \2", s)]
    for c in candidatos:
        if c in UNIDADES or c in TEMP or f"grados {c}" in TEMP:
            return c
    return None


def convertir(texto: str) -> str | None:
    m = re.search(r"([\d.,]+|" + "|".join(["un", "una", "dos", "tres", "cuatro", "cinco", "diez", "cien"]) + r")\s+"
                  r"(grados [a-z]+|[a-z/]+(?: por (?:hora|segundo))?)\s+(?:a|en)\s+(grados [a-z]+|[a-z/]+"
                  r"(?: por (?:hora|segundo))?)\s*$", texto)
    if not m:
        return None
    n = a_numero(m.group(1)) if not m.group(1)[0].isdigit() else None
    try:
        valor = float(n) if n is not None else float(m.group(1).replace(".", "").replace(",", ".")
                                                       if "," in m.group(1) else m.group(1))
    except ValueError:
        return None
    u1, u2 = _unidad(m.group(2)), _unidad(m.group(3))
    if not u1 or not u2:
        return None
    t1 = TEMP.get(u1) or TEMP.get(f"grados {u1}")
    t2 = TEMP.get(u2) or TEMP.get(f"grados {u2}")
    if t1 and t2:
        c = valor if t1 == "c" else (valor - 32) * 5 / 9 if t1 == "f" else valor - 273.15
        r = c if t2 == "c" else c * 9 / 5 + 32 if t2 == "f" else c + 273.15
        nombres = {"c": "grados centígrados", "f": "grados Fahrenheit", "k": "kelvin"}
        return f"{num_es(valor)} {nombres[t1]} son {num_es(r, 1)} {nombres[t2]}."
    if u1 not in UNIDADES or u2 not in UNIDADES or UNIDADES[u1][0] != UNIDADES[u2][0]:
        return None
    r = valor * UNIDADES[u1][1] / UNIDADES[u2][1]
    return f"{num_es(valor)} {m.group(2)} son {num_es(r, 3 if abs(r) < 10 else 2)} {m.group(3)}."


# =============================================================== noticias

FUENTES_NOTICIAS = [
    ("El País", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"),
    ("20minutos", "https://www.20minutos.es/rss/"),
    ("Europa Press", "https://www.europapress.es/rss/rss.aspx"),
]


def titulares(maximo: int = 6) -> tuple[str, list[tuple[str, str]]]:
    errores = []
    for nombre, url in FUENTES_NOTICIAS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis-local"})
            with urllib.request.urlopen(req, timeout=8) as r:
                raiz = ET.fromstring(r.read())
            items = []
            for it in raiz.iter("item"):
                titulo = (it.findtext("title") or "").strip()
                enlace = (it.findtext("link") or "").strip()
                if titulo:
                    items.append((titulo, enlace))
                if len(items) >= maximo:
                    break
            if items:
                return nombre, items
        except Exception as e:                       # red, formato…: probamos la siguiente fuente
            errores.append(f"{nombre}: {type(e).__name__}")
    raise RuntimeError("; ".join(errores))


# =============================================================== memoria personal

def leer_memoria() -> list[dict]:
    try:
        return json.loads(MEMORIA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def guardar_memoria(datos: list[dict]) -> None:
    MEMORIA.parent.mkdir(parents=True, exist_ok=True)
    MEMORIA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def memoria_para_ia() -> str:
    datos = leer_memoria()
    if not datos:
        return ""
    return ("Datos que el usuario te ha pedido que recuerdes (úsalos si vienen al caso): "
            + " | ".join(d["dato"] for d in datos[-40:]) + ".")


def _mayus(s: str) -> str:
    return s[:1].upper() + s[1:]


def _a_segunda_persona(dato: str) -> str:
    """'mi coche es un seat' -> 'tu coche es un seat' para leerlo en voz alta."""
    cambios = {"mi": "tu", "mis": "tus", "me": "te", "yo": "tú", "conmigo": "contigo", "mío": "tuyo", "mía": "tuya"}
    return " ".join(cambios.get(p.lower(), p) for p in dato.split())


# =============================================================== el módulo

class Extras:
    def __init__(self, decir: Callable[..., None], ui=None, log=print, herr=None,
                 avisar: Callable[[str], None] | None = None, sist=None):
        self.decir = decir
        self.sist = sist
        self.ui = ui
        self.log = log
        self.herr = herr
        self.avisar = avisar or (lambda texto: None)      # Telegram, si está configurado
        self._avisados: dict[str, float] = {}
        self._tiempo_cache: tuple[float, dict] | None = None
        self.correo = None                                 # el módulo de correo (para el resumen), lo pone Jarvis

    # ---------- avisos automáticos + panel
    def arrancar_vigilante(self) -> None:
        threading.Thread(target=self._vigilar, daemon=True).start()

    def _avisar_una_vez(self, clave: str, texto: str, cada: float) -> None:
        ahora = time.time()
        if ahora - self._avisados.get(clave, 0) < cada:
            return
        self._avisados[clave] = ahora
        self.log(f"aviso: {texto}")
        self.avisar("⚠️ " + texto)
        self.decir(texto, susurro=False)

    def _vigilar(self) -> None:
        time.sleep(30)
        ciclo = 0
        while True:
            try:
                e = estado_ordenador()
                if e["bat"] is not None and e["bat_estado"] == "discharging":
                    if e["bat"] <= 5:
                        self._avisar_una_vez("bat5", f"Batería al {e['bat']} por ciento. Enchúfame ya o me apagaré.", 300)
                    elif e["bat"] <= 15:
                        self._avisar_una_vez("bat15", f"Batería baja: {e['bat']} por ciento. Conviene enchufar el portátil.", 1800)
                elif e["bat_estado"] in ("charging", "full"):
                    self._avisados.pop("bat15", None)
                    self._avisados.pop("bat5", None)
                if e["temp"] is not None and e["temp"] >= 88:
                    self._avisar_una_vez("temp", f"El portátil está muy caliente: {e['temp']} grados.", 900)
                if e["disco_libre"] < 3 or e["disco_usado"] >= 95:
                    self._avisar_una_vez("disco", f"El disco está casi lleno: quedan {num_es(e['disco_libre'], 1)} gigas.",
                                         86400)
                if ciclo % 2 == 0:
                    self.actualizar_panel(e)
            except Exception as ex:
                self.log(f"error en vigilante: {ex!r}")
            ciclo += 1
            time.sleep(30)

    def tiempo_breve(self) -> dict | None:
        """Tiempo actual para el panel (se guarda 20 minutos)."""
        ciudad = leer_config().get("ciudad")
        if not ciudad:
            return None
        if self._tiempo_cache and time.time() - self._tiempo_cache[0] < 1200:
            return self._tiempo_cache[1]
        try:
            import urllib.parse
            geo = http_json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
                {"name": ciudad, "count": 1, "language": "es", "format": "json"}))
            g = geo["results"][0]
            d = http_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
                "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"}))
            t = {"ciudad": g["name"], "temp": round(d["current"]["temperature_2m"]),
                 "cielo": CODIGOS_TIEMPO.get(d["current"]["weather_code"], "variable").removeprefix("con "),
                 "max": round(d["daily"]["temperature_2m_max"][0]), "min": round(d["daily"]["temperature_2m_min"][0]),
                 "lluvia": d["daily"]["precipitation_probability_max"][0]}
            self._tiempo_cache = (time.time(), t)
            return t
        except Exception:
            return self._tiempo_cache[1] if self._tiempo_cache else None

    def actualizar_panel(self, e: dict | None = None) -> None:
        if not self.ui:
            return
        e = e or estado_ordenador()
        recs = []
        try:
            import calendario
            for ev in calendario.proximos(4):              # ev, no e: e es el estado del ordenador
                f = dt.date.fromisoformat(ev["fecha"])
                dia = "" if f == dt.date.today() else ("mañana " if f == dt.date.today() + dt.timedelta(days=1)
                                                       else f"{f.day}/{f.month} ")
                recs.append({"cuando": (dia + (ev.get("hora") or "todo el día")).strip(), "texto": ev["texto"]})
        except Exception:
            for r in leer_recordatorios()[:4]:
                cuando = dt.datetime.fromisoformat(r["cuando"])
                recs.append({"cuando": hora_hablada(cuando).removeprefix("a las "), "texto": r["texto"] or "recordatorio"})
        self.ui.enviar(tipo="panel", sistema=e, tiempo=self.tiempo_breve(), recordatorios=recs)

    # ---------- resumen de buenos días
    def resumen_dia(self, para_telegram: bool = False) -> str:
        """Tiempo, agenda de hoy y de mañana, correo y avisos. En voz, prosa; para Telegram, con viñetas."""
        voz, lineas = [], []
        hoy = dt.date.today()
        t = self.tiempo_breve()
        if t:
            lluvia = f", con un {t['lluvia']} por ciento de probabilidad de lluvia" if (t["lluvia"] or 0) >= 30 else ""
            voz.append(f"En {t['ciudad']} hace {t['temp']} grados y está {t['cielo']}; máxima de {t['max']}{lluvia}.")
            lineas.append(f"🌤 {t['ciudad']}: {t['temp']}°, {t['cielo']} (máx. {t['max']}°, mín. {t['min']}°"
                          + (f", lluvia {t['lluvia']}%" if (t["lluvia"] or 0) >= 30 else "") + ")")
        try:
            import calendario
            ahora = f"{dt.datetime.now():%H:%M}"
            de_hoy = [e for e in calendario.entre(hoy, hoy) if not e.get("hora") or e["hora"] >= ahora]
            manana = calendario.entre(hoy + dt.timedelta(days=1), hoy + dt.timedelta(days=1))
            if de_hoy:
                partes = [(calendario.hora_hablada(e["hora"]).strip() + ", " if e.get("hora") else "") + e["texto"]
                          for e in de_hoy[:5]]
                voz.append(f"Hoy tienes {len(de_hoy)} cosa{'s' if len(de_hoy) != 1 else ''} en el calendario: "
                           + "; ".join(partes) + ".")
            else:
                voz.append("No tienes nada en el calendario para hoy.")
            lineas.append("📅 Hoy: " + ("nada apuntado" if not de_hoy else ""))
            lineas += [f"   • {e.get('hora') or 'todo el día'} — {e['texto']}" for e in de_hoy[:8]]
            if manana:
                voz.append("Mañana: " + ", ".join(e["texto"] for e in manana[:3]) + ".")
                lineas.append("📅 Mañana: " + "; ".join(f"{e.get('hora') or 'todo el día'} {e['texto']}"
                                                       for e in manana[:5]))
        except Exception as e:
            self.log(f"resumen: calendario {e!r}")
        if self.correo is not None:
            try:
                frase_correo, lista = self.correo.resumen_breve()
                if frase_correo:
                    voz.append(frase_correo)
                    lineas.append("📧 " + frase_correo)
                    lineas += [f"   • {x}" for x in lista]
            except Exception as e:
                self.log(f"resumen: correo {e!r}")
        b = bateria()
        if b and b[1] == "discharging" and b[0] < 30:
            voz.append(f"Ojo, la batería está al {b[0]} por ciento.")
            lineas.append(f"🔋 Batería al {b[0]}%")
        if para_telegram:
            try:
                fuente, items = titulares(3)
                lineas.append(f"📰 {fuente}:")
                lineas += [f"   • {titulo}" for titulo, _ in items]
            except Exception:
                pass
            return f"☀️ Buenos días. Resumen del {DIAS[hoy.weekday()]} {hoy.day}/{hoy.month}\n" + "\n".join(lineas)
        return " ".join(voz)

    # ---------- entrada
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        t = re.sub(r"^(por favor|oye|venga)\s+", "", t)

        # --- estado del ordenador
        if re.search(r"\b(como|que tal) (va|esta|anda)\w* (el |mi )?(ordenador|portatil|equipo|pc|sistema)\b"
                     r"|\bestado del (ordenador|portatil|equipo|sistema)\b|\buso de (la )?(cpu|memoria|procesador)\b"
                     r"|\b(cuanta|que) (bateria|temperatura|memoria)\b|\bcuanto (espacio|disco)\b", t):
            e = estado_ordenador()
            self.actualizar_panel(e)
            return Respuesta(estado_hablado(e))

        # --- resumen de la mañana: hora y activar/desactivar
        if re.search(r"\bresumen (de la manana|diario|de cada manana)\b", t):
            if re.search(r"\b(desactiva|quita|apaga|no quiero|cancela)\w*\b", t):
                guardar_config(resumen_activo=False)
                return Respuesta("Vale, ya no te daré el resumen de la mañana. Puedes volver a activarlo cuando quieras.")
            m = re.search(r"\ba las (\d{1,2})(?:[: ](\d{2})| y (media|cuarto))?\b", t)
            if m:
                h = int(m.group(1))
                mi = int(m.group(2)) if m.group(2) else 30 if m.group(3) == "media" else 15 if m.group(3) else 0
                if 4 <= h <= 12 and mi < 60:
                    guardar_config(resumen_hora=f"{h:02d}:{mi:02d}", resumen_activo=True)
                    return Respuesta(f"Hecho: cada mañana a las {h}:{mi:02d} te mando el resumen por Telegram y te lo "
                                     "digo en cuanto te vea.")
                return Respuesta("El resumen de la mañana tiene que ser entre las 4 y las 12.")
            if re.search(r"\b(activa|pon|enciende|quiero)\w*\b", t) and not re.search(r"\b(dame|dime|lee)\b", t):
                guardar_config(resumen_activo=True)
                return Respuesta(f"Resumen de la mañana activado, a las {leer_config().get('resumen_hora', '08:00')}.")
            return Respuesta(self.resumen_dia())

        # --- resumen del día
        if re.search(r"^buenos dias\b|\bresumen del dia\b|\bque tengo (para )?hoy\b|\bcomo (viene|pinta) el dia\b", t):
            return Respuesta(("Buenos días. " if t.startswith("buenos dias") else "") + self.resumen_dia())

        # --- memoria personal
        m = re.match(r"^(?:recuerda|acuerdate de|apunta en tu memoria|memoriza|guarda en tu memoria)\s+(?:que\s+)?(.+)$", t)
        if m and not t.startswith("recuerdame"):
            cuando, _ = interpretar_recordatorio(m.group(1), dt.datetime.now())
            if cuando is not None and self.sist is not None:   # "recuerda que mañana a las 9…" es un recordatorio
                return self.sist._nuevo_recordatorio(m.group(1), peticion)
            if cuando is None:                                  # sin hora: es un dato, no un recordatorio
                dato = con_tildes(peticion, m.group(1)).strip(" .")
                datos = [d for d in leer_memoria() if normalizar(d["dato"]) != normalizar(dato)]
                datos.append({"dato": dato, "fecha": dt.date.today().isoformat()})
                guardar_memoria(datos)
                return Respuesta(f"Lo recordaré: {_a_segunda_persona(dato)}.")
        if re.search(r"\bque (sabes|recuerdas) de mi\b|\bque (cosas )?(tienes|guardas) en (tu|la) memoria\b", t):
            datos = leer_memoria()
            if not datos:
                return Respuesta("Todavía no me has pedido que recuerde nada. Dime, por ejemplo: recuerda que mi coche es un Seat León.")
            if self.ui:
                self.ui.enviar(tipo="resultados", titulo="Memoria", items=[d["dato"] for d in datos[-8:]])
            return Respuesta(f"Recuerdo {len(datos)} cosa{'s' if len(datos) > 1 else ''}. "
                             + ". ".join(_mayus(_a_segunda_persona(d["dato"])) for d in datos[-5:]) + ".")
        m = re.match(r"^olvida\w*\s+(?:que\s+|lo del?\s+|lo que\s+|el dato de\s+|lo de la\s+)?(.+)$", t)
        if m:
            clave = m.group(1)
            if clave in ("todo", "todo lo que sabes", "todo lo que recuerdas"):
                guardar_memoria([])
                return Respuesta("Hecho, he olvidado todo lo que me habías contado.")
            import difflib
            datos = leer_memoria()
            claves = {w for w in clave.split() if len(w) >= 4}
            puntos = [(difflib.SequenceMatcher(None, clave, normalizar(d["dato"])).ratio()
                       + (0.5 if clave in normalizar(d["dato"]) else 0)
                       + 0.6 * len(claves & set(normalizar(d["dato"]).split())), i) for i, d in enumerate(datos)]
            if puntos and max(puntos)[0] >= 0.55:
                quitado = datos.pop(max(puntos)[1])
                guardar_memoria(datos)
                return Respuesta(f"Olvidado: {_a_segunda_persona(quitado['dato'])}.")
            return Respuesta("No encuentro nada parecido en mi memoria.")

        # --- conversiones y cálculos
        m = re.match(r"^(?:convierte|pasa|cambia|cuanto es|cuantos son|cuantas son|cuanto son|a cuanto equivalen?)\s+(.+)$", t)
        if m:
            r = convertir(m.group(1))
            if r:
                for w in set(re.findall(r"[a-z]+", r)):          # devolver las tildes: kilometros -> kilómetros
                    if len(w) > 3:
                        r = re.sub(rf"\b{w}\b", con_tildes(peticion, w).lower(), r)
                return Respuesta(r)
        m = re.match(r"^(?:cuanto es|cuanto son|cuanto da|calcula(?:me)?|cuanto hace|resuelve)\s+(.+)$", t)
        if m:
            valor = calcular(m.group(1))
            if valor is not None:
                expr = peticion.strip(" ¿?¡!.")
                expr = re.sub(r"^\W*\w+\s+\w+\s+", "", expr, count=1) if re.match(r"^\W*cu", expr, re.I) else \
                    re.sub(r"^\W*\w+\s+", "", expr, count=1)
                return Respuesta(f"{expr[:1].upper() + expr[1:]} da {num_es(valor, 4)}.")
            return Respuesta("No he sabido hacer esa cuenta. Prueba, por ejemplo: cuánto es 21 por ciento de 340.")

        # --- dictado
        m = re.match(r"^(?:escribe|escribeme|teclea|dicta)\s+(?:esto\s*:?\s*)?(.+)$", t)
        if m and not re.match(r"^(un|una) (correo|email|mensaje)\b", m.group(1)):
            original = con_tildes(peticion, m.group(1)).strip()
            texto = original[:1].upper() + original[1:]
            if not shutil.which("xdotool"):
                return Respuesta("Para escribir necesito el programa xdotool, que no está instalado.")
            texto = re.sub(r"\s*\b(punto y aparte|nueva linea|nueva línea)\b\s*", "\n", texto, flags=re.I)
            for i, trozo in enumerate(texto.split("\n")):
                if i:
                    subprocess.run(["xdotool", "key", "Return"], timeout=5)
                if trozo:
                    subprocess.run(["xdotool", "type", "--delay", "15", "--", trozo], timeout=60)
            return Respuesta("Escrito.")

        # --- captura de pantalla
        if re.search(r"\b(haz|hazme|saca|sacame|toma)\w*\s+(una\s+)?(captura|foto de (la )?pantalla|pantallazo)"
                     r"|^captura\w*( la)? pantalla|^captura$", t):
            carpeta = carpeta_usuario("PICTURES")
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / f"Captura_{dt.datetime.now():%Y-%m-%d_%H-%M-%S}.png"
            ok = False
            for cmd in (["scrot", "-o", str(ruta)], ["xfce4-screenshooter", "-f", "-s", str(ruta)],
                        ["import", "-window", "root", str(ruta)]):
                if shutil.which(cmd[0]):
                    try:
                        ok = subprocess.run(cmd, timeout=20, capture_output=True).returncode == 0 and ruta.exists()
                    except (OSError, subprocess.TimeoutExpired):
                        ok = False
                    if ok:
                        break
            if not ok:
                return Respuesta("No he podido hacer la captura. Falta el programa scrot.")
            return Respuesta(f"Captura guardada en {carpeta.name}.", archivo=str(ruta))

        # --- noticias
        if re.search(r"\bnoticias\b|\btitulares\b|\bque (hay de nuevo|pasa en el mundo|ha pasado hoy)\b", t):
            try:
                fuente, items = titulares()
            except RuntimeError as e:
                self.log(f"noticias: {e}")
                return Respuesta("No he podido descargar las noticias. Puede que no haya internet.")
            if self.herr is not None:
                self.herr.ultimos = [u for _, u in items]
            if self.ui:
                self.ui.enviar(tipo="resultados", titulo=f"Noticias · {fuente}", items=[ti for ti, _ in items])
            lectura = ". ".join(ti.rstrip(".") for ti, _ in items[:5])
            return Respuesta(f"Titulares de {fuente}. {lectura}. Si quieres leer alguna, dime abre la primera, "
                             f"o el número que quieras.")
        return None
