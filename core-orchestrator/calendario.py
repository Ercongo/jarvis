"""
Calendario de Jarvis (datos en ~/jarvis/calendario.json; copia en ~/jarvis/calendario.ics para el móvil).

Órdenes:
  "apunta en el calendario el cumpleaños de Ana el 20 de noviembre"      → evento de día completo
  "añade al calendario dentista el viernes a las 10"                     → con hora: además te avisa a esa hora
  "recuérdame el martes a las 6 llamar a mamá"                           → recordatorio (queda en el calendario)
  "abre el calendario" / "enséñame la agenda"                            → vista mensual en la pantalla del portátil
  "qué tengo hoy / mañana / el jueves / esta semana / este mes / el 3 de diciembre"
  "borra del calendario el dentista" / "cancela la cita del médico"      → pide confirmación
  "mándame el calendario"                                                → el .ics por Telegram (se importa en el móvil)
Los recordatorios ya avisados se quedan en el calendario como historial.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Callable

from herramientas import abrir_web, normalizar
from sistema import RE_A_LAS, Respuesta, a_numero, con_tildes, leer_recordatorios

CALENDARIO = Path.home() / "jarvis" / "calendario.json"
ICS = Path.home() / "jarvis" / "calendario.ics"
BORRADOS = Path.home() / "jarvis" / "calendario_borrados.json"   # ids de Google pendientes de borrar allí
AL_CAMBIAR: list[Callable[[], None]] = []                     # la sincronización con Google se apunta aquí
URL = "http://127.0.0.1:8765/calendario"

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
NUM_DIA = r"(\d{1,2}|uno|primero|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|" \
          r"dieciseis|diecisiete|dieciocho|diecinueve|veinte|veintiun|veintiuno|veintidos|veintitres|veinticuatro|" \
          r"veinticinco|veintiseis|veintisiete|veintiocho|veintinueve|treinta(?: y uno)?)"
RE_MES = "(" + "|".join(MESES) + ")"


# =============================================================== fechas y horas en español

def _dia_num(s: str) -> int | None:
    return 1 if s == "primero" else a_numero(s)


def interpretar_fecha(t: str, hoy: dt.date) -> tuple[dt.date | None, str]:
    """Busca una fecha en el texto normalizado. Devuelve (fecha, texto sin la fecha)."""
    def quitar(m):
        return (t[:m.start()] + " " + t[m.end():]).strip()

    def calcular(dia: int, mes: int | None, anio: int | None) -> dt.date | None:
        for intento in range(14):
            mm = mes or ((hoy.month - 1 + intento) % 12 + 1)
            aa = anio or (hoy.year + ((hoy.month - 1 + intento) // 12 if not mes else intento))
            try:
                f = dt.date(aa, mm, dia)
            except ValueError:
                continue
            if f >= hoy or anio:
                return f
        return None

    # Lo más concreto primero: "el jueves 29 de octubre", "29 de octubre", "29/10", "el día 29"
    sem = r"(?:(?:el |este |para el )?(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo),? )?"
    m = re.search(rf"\b{sem}(?:el (?:dia )?|dia |para el )?{NUM_DIA} de {RE_MES}(?: de(?:l)? (\d{{4}}))?\b", t)
    if m:
        f = calcular(_dia_num(m.group(1)) or 0, MESES.index(m.group(2)) + 1, int(m.group(3)) if m.group(3) else None)
        if f:
            return f, quitar(m)
    m = re.search(r"\b(?:el (?:dia )?)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m and 1 <= int(m.group(2)) <= 12:
        anio = int(m.group(3)) + (2000 if m.group(3) and len(m.group(3)) == 2 else 0) if m.group(3) else None
        f = calcular(int(m.group(1)), int(m.group(2)), anio)
        if f:
            return f, quitar(m)
    m = re.search(rf"\b(?:el |este |para el )?(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo),? (?:dia )?{NUM_DIA}\b"
                  rf"(?!\s*(?:minutos?|horas?|de la|y\b|:))", t)
    if m:
        f = calcular(_dia_num(m.group(1)) or 0, None, None)
        if f:
            return f, quitar(m)

    m = re.search(r"\bpasado manana\b", t)
    if m:
        return hoy + dt.timedelta(days=2), quitar(m)
    m = re.search(r"\b(?:para |de )?hoy\b", t)
    if m:
        return hoy, quitar(m)
    for m in re.finditer(r"\b(?:para )?manana\b", t):
        if not re.search(r"\b(?:de|por) la $", t[:m.start()]):      # "por la mañana" es la hora, no el día
            return hoy + dt.timedelta(days=1), quitar(m)
    m = re.search(r"\bdentro de (\w+(?: y \w+)?) (dias?|semanas?)\b", t)
    if m:
        n = 1 if m.group(1) in ("un", "una") else a_numero(m.group(1))
        if n:
            return hoy + dt.timedelta(days=n * (7 if m.group(2).startswith("semana") else 1)), quitar(m)
    m = re.search(r"\b(?:la semana que viene|la proxima semana)\b", t)
    if m:
        return hoy + dt.timedelta(days=7 - hoy.weekday()), quitar(m)
    m = re.search(r"\b(?:este )?fin de semana\b", t)
    if m:
        return hoy + dt.timedelta(days=(5 - hoy.weekday()) % 7), quitar(m)
    m = re.search(r"\b(?:el |este |para el )?(?:proximo |otro )?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)"
                  r"(?: que viene| proximo)?\b", t)
    if m:
        delta = (DIAS.index(m.group(1)) - hoy.weekday()) % 7 or 7
        return hoy + dt.timedelta(days=delta), quitar(m)
    m = re.search(rf"\b(?:el dia |el |dia ){NUM_DIA}\b(?!\s*(?:minutos?|horas?|dias?|semanas?|de la|y\b|:))", t)
    if m:
        dia = _dia_num(m.group(1))
        f = calcular(dia, None, None) if dia and 1 <= dia <= 31 else None
        if f:
            return f, quitar(m)
    return None, t


def interpretar_hora(t: str) -> tuple[str | None, str]:
    """'a las cinco y media de la tarde' → ('17:30', resto)."""
    m = re.search(r"\b(?:a |al |sobre el )?mediodia\b", t)
    if m:
        return "12:00", (t[:m.start()] + " " + t[m.end():]).strip()
    m = re.search(r"\b(?:a las |para las |sobre las )?(\d{1,2})[:.h](\d{2})\b(?:\s*(?:h|horas))?", t)
    if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
        h = int(m.group(1))
        resto = (t[:m.start()] + " " + t[m.end():]).strip()
        p = re.search(r"\b(?:de la|por la) (tarde|noche)\b", resto)
        if p and h < 12:
            h += 12
            resto = (resto[:p.start()] + " " + resto[p.end():]).strip()
        return f"{h:02d}:{int(m.group(2)):02d}", resto
    m = re.search(r"\b(?:a|para)\s+(?:las?\s+)?(\d{1,2})\s+y\s+(\d{1,2}|cuarto|media)\b"
                  r"(?:\s+(?:de la|por la)\s+(manana|tarde|noche))?", t)
    if m:
        h = int(m.group(1))
        minuto = 30 if m.group(2) == "media" else 15 if m.group(2) == "cuarto" else int(m.group(2))
        if h <= 23 and minuto <= 59:
            if (m.group(3) in ("tarde", "noche") and h < 12) or (m.group(3) is None and 1 <= h <= 7):
                h += 12
            return f"{h:02d}:{minuto:02d}", (t[:m.start()] + " " + t[m.end():]).strip()
    m = RE_A_LAS.search(t)
    if not m:
        m = re.search(r"\b(?:por|de|a) la (manana|tarde|noche)\b", t)
        if m:
            return {"manana": "09:00", "tarde": "17:00", "noche": "21:00"}[m.group(1)], \
                (t[:m.start()] + " " + t[m.end():]).strip()
        return None, t
    h = a_numero(m.group(1))
    minuto = 0
    if m.group(2):
        minuto = 30 if m.group(2) == "media" else 15 if m.group(2) == "cuarto" else (a_numero(m.group(2)) or 0)
    if m.group(3):
        menos = 15 if m.group(3) == "cuarto" else (a_numero(m.group(3)) or 0)
        h, minuto = ((h or 0) - 1) % 24, 60 - menos
    if h is None or not (0 <= h <= 23 and 0 <= minuto <= 59):
        return None, t
    periodo = m.group(4)
    if periodo in ("tarde", "noche") and h < 12:
        h += 12
    elif periodo is None and 1 <= h <= 7:
        h += 12                                       # "a las 5" casi siempre es por la tarde
    return f"{h:02d}:{minuto:02d}", (t[:m.start()] + " " + t[m.end():]).strip()


def limpiar_que(t: str) -> str:
    t = re.sub(r"\b(en (el|mi) calendario|en (la|mi) agenda|al calendario|a la agenda|del calendario|de la agenda)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.:;")
    for _ in range(3):
        t = re.sub(r"^(que|de que|de|para|el|la|un|una|tengo|hay|apunta|anota|es|son|sera|toca|tambien)\s+", "", t)
        t = re.sub(r"\s+(que|de|el|la|para|a|en)$", "", t)
    return t.strip(" ,.:;")


def tildes_por_palabra(original: str, texto: str) -> str:
    """Devuelve a cada palabra sus tildes y mayúsculas tal como venían en la frase original."""
    import unicodedata
    mapa = {}
    for w in re.findall(r"[\wÁÉÍÓÚÜÑáéíóúüñ]+", original):
        clave = "".join(c for c in unicodedata.normalize("NFD", w.lower()) if unicodedata.category(c) != "Mn")
        if clave not in mapa or (w[:1].isupper() and not w.isupper()):
            mapa[clave] = w if not w.isupper() or len(w) <= 4 else w.lower()
    return re.sub(r"[\w]+", lambda m: mapa.get(m.group(0), m.group(0)), texto)


def fecha_hablada(f: dt.date, hoy: dt.date | None = None) -> str:
    hoy = hoy or dt.date.today()
    if f == hoy:
        return "hoy"
    if f == hoy + dt.timedelta(days=1):
        return "mañana"
    if hoy < f < hoy + dt.timedelta(days=7):
        return f"el {DIAS_ES[f.weekday()]}"
    texto = f"el {DIAS_ES[f.weekday()]} {f.day} de {MESES[f.month - 1]}"
    return texto + (f" de {f.year}" if f.year != hoy.year else "")


def hora_hablada(h: str | None) -> str:
    if not h:
        return ""
    hh, mm = map(int, h.split(":"))
    h12 = hh % 12 or 12
    minutos = "" if mm == 0 else " y media" if mm == 30 else " y cuarto" if mm == 15 else f":{mm:02d}"
    parte = "de la madrugada" if hh < 6 else "de la mañana" if hh < 12 else "del mediodía" if hh < 14 else \
        "de la tarde" if hh < 21 else "de la noche"
    return f" a la{'s' if h12 != 1 else ''} {h12}{minutos} {parte}"


# =============================================================== almacenamiento

_lock = threading.RLock()


def leer() -> list[dict]:
    try:
        return json.loads(CALENDARIO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def guardar(eventos: list[dict]) -> None:
    eventos.sort(key=lambda e: (e["fecha"], e.get("hora") or "00:00"))
    CALENDARIO.parent.mkdir(parents=True, exist_ok=True)
    tmp = CALENDARIO.with_suffix(".tmp")
    tmp.write_text(json.dumps(eventos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CALENDARIO)
    escribir_ics(eventos)


def escribir_ics(eventos: list[dict]) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Jarvis//Calendario//ES", "CALSCALE:GREGORIAN",
              "X-WR-CALNAME:Jarvis"]
    sello = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in eventos:
        f = e["fecha"].replace("-", "")
        lineas += ["BEGIN:VEVENT", f"UID:{e['id']}@jarvis", f"DTSTAMP:{sello}", f"SUMMARY:{esc(e['texto'])}"]
        if e.get("hora"):
            inicio = f + "T" + e["hora"].replace(":", "") + "00"
            fin_dt = dt.datetime.strptime(inicio, "%Y%m%dT%H%M%S") + dt.timedelta(minutes=30)
            lineas += [f"DTSTART:{inicio}", f"DTEND:{fin_dt:%Y%m%dT%H%M%S}"]
            if e.get("aviso"):
                lineas += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(e['texto'])}", "TRIGGER:PT0M",
                           "END:VALARM"]
        else:
            siguiente = dt.date.fromisoformat(e["fecha"]) + dt.timedelta(days=1)
            lineas += [f"DTSTART;VALUE=DATE:{f}", f"DTEND;VALUE=DATE:{siguiente:%Y%m%d}"]
        lineas.append("END:VEVENT")
    lineas.append("END:VCALENDAR")
    try:
        ICS.write_text("\r\n".join(lineas) + "\r\n", encoding="utf-8")
    except OSError:
        pass


def nuevo(fecha: dt.date, hora: str | None, texto: str, origen: str = "evento", aviso: bool = False) -> dict:
    e = {"id": uuid.uuid4().hex[:12], "fecha": fecha.isoformat(), "hora": hora, "texto": texto.strip() or "Evento",
         "origen": origen, "aviso": aviso, "creado": dt.datetime.now().isoformat(timespec="seconds")}
    with _lock:
        eventos = leer()
        eventos.append(e)
        guardar(eventos)
    _avisar_cambio()
    return e


def borrar(ident: str) -> dict | None:
    with _lock:
        eventos = leer()
        quitado = next((e for e in eventos if e["id"] == ident), None)
        if quitado:
            guardar([e for e in eventos if e["id"] != ident])
            if quitado.get("gid"):
                guardar_borrados(leer_borrados() + [quitado["gid"]])
    if quitado:
        _avisar_cambio()
    return quitado


def _avisar_cambio() -> None:
    for f in AL_CAMBIAR:
        try:
            f()
        except Exception:
            pass


def leer_borrados() -> list[str]:
    try:
        return [str(x) for x in json.loads(BORRADOS.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def guardar_borrados(gids: list[str]) -> None:
    try:
        BORRADOS.write_text(json.dumps(sorted(set(gids))), encoding="utf-8")
    except OSError:
        pass


def entre(desde: dt.date, hasta: dt.date) -> list[dict]:
    return [e for e in leer() if desde.isoformat() <= e["fecha"] <= hasta.isoformat()]


def proximos(n: int = 4) -> list[dict]:
    ahora = dt.datetime.now()
    hoy = ahora.date().isoformat()
    futuros = [e for e in leer() if e["fecha"] > hoy or (e["fecha"] == hoy and (not e.get("hora") or
                                                                              e["hora"] >= f"{ahora:%H:%M}"))]
    return futuros[:n]


def registrar_recordatorio(cuando: dt.datetime, texto: str) -> None:
    """Lo llama el módulo de sistema cada vez que se crea un recordatorio."""
    if texto == "temporizador terminado":
        return
    nuevo(cuando.date(), f"{cuando:%H:%M}", texto or "Recordatorio", origen="recordatorio", aviso=True)


def sincronizar_recordatorios() -> None:
    """Al arrancar: los recordatorios pendientes que aún no estén en el calendario, se añaden."""
    with _lock:
        eventos = leer()
        claves = {(e["fecha"], e.get("hora"), normalizar(e["texto"])) for e in eventos}
        nuevos = 0
        for r in leer_recordatorios():
            if r.get("texto") == "temporizador terminado":
                continue
            c = dt.datetime.fromisoformat(r["cuando"])
            clave = (c.date().isoformat(), f"{c:%H:%M}", normalizar(r.get("texto") or "Recordatorio"))
            if clave not in claves:
                eventos.append({"id": uuid.uuid4().hex[:12], "fecha": clave[0], "hora": clave[1],
                                "texto": r.get("texto") or "Recordatorio", "origen": "recordatorio", "aviso": True,
                                "creado": r.get("creado", dt.datetime.now().isoformat(timespec="seconds"))})
                nuevos += 1
        if nuevos or not ICS.exists():
            guardar(eventos)


def abrir_calendario() -> None:
    """Abre la página y, cuando aparece la ventana, la maximiza en la pantalla del portátil."""
    abrir_web(URL)

    def maximizar():
        import shutil
        import subprocess
        import time
        if not shutil.which("wmctrl"):
            return
        for _ in range(10):
            time.sleep(2)
            r = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True)
            if "Calendario personal" in r.stdout:
                time.sleep(1.5)                       # que el guardián termine de moverla al portátil
                subprocess.run(["wmctrl", "-r", "Calendario personal", "-b", "add,maximized_vert,maximized_horz"])
                subprocess.run(["wmctrl", "-a", "Calendario personal"])
                return
    threading.Thread(target=maximizar, daemon=True).start()


# =============================================================== el módulo

class Calendario:
    def __init__(self, decir: Callable[..., None], confirmar: Callable[[str], bool], log=print, ui=None,
                 programar: Callable[[dt.datetime, str], None] | None = None,
                 desprogramar: Callable[[dt.datetime, str], None] | None = None,
                 enviar_documento: Callable[[str, str], bool] | None = None,
                 es_telegram: Callable[[], bool] | None = None):
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.ui = ui
        self.programar = programar or (lambda cuando, texto: None)
        self.desprogramar = desprogramar or (lambda cuando, texto: None)
        self.enviar_documento = enviar_documento or (lambda ruta, pie: False)
        self.es_telegram = es_telegram or (lambda: False)
        try:
            sincronizar_recordatorios()
        except Exception as e:
            log(f"calendario: no se pudo sincronizar ({e!r})")

    # ---------- para el cerebro en la nube (fechas ya resueltas)
    def contexto_ia(self, n: int = 25) -> str:
        hoy = dt.date.today()
        desde = (hoy - dt.timedelta(days=2)).isoformat()
        eventos = [e for e in leer() if e["fecha"] >= desde][:n]
        return "; ".join(f"{e['id']} | {e['fecha']} | {e.get('hora') or 'todo el día'} | {e['texto']}" for e in eventos)

    def anadir_evento(self, fecha: str, hora: str | None, texto: str) -> str:
        f = dt.date.fromisoformat(fecha)
        hora = hora if hora and re.fullmatch(r"\d{2}:\d{2}", hora) else None
        texto = (texto or "Evento").strip()
        texto = texto[:1].upper() + texto[1:]
        cuando = dt.datetime.fromisoformat(f"{fecha}T{hora}") if hora else None
        aviso = cuando is not None and cuando > dt.datetime.now()
        nuevo(f, hora, texto, "evento", aviso)
        if aviso:
            self.programar(cuando, texto)
        self.log(f"calendario (IA): {fecha} {hora or 'todo el día'} {texto}")
        return f"{fecha_hablada(f)}{hora_hablada(hora)}, {texto}"

    def consultar(self, desde: str, hasta: str) -> Respuesta:
        d, h = dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta)
        if h < d:
            d, h = h, d
        hoy = dt.date.today()
        cuando = fecha_hablada(d, hoy) if d == h else \
            ("esta semana" if d == hoy and h == hoy + dt.timedelta(days=6 - hoy.weekday()) else
             f"del {d.day} de {MESES[d.month - 1]} al {h.day} de {MESES[h.month - 1]}")
        eventos = entre(d, h)
        if d == hoy:
            ahora = f"{dt.datetime.now():%H:%M}"
            eventos = [e for e in eventos if e["fecha"] > d.isoformat() or not e.get("hora") or e["hora"] >= ahora]
        return self._contar(eventos, cuando)

    def borrar_id(self, ident: str) -> str:
        e = next((x for x in leer() if x["id"] == ident), None)
        if not e:
            return "No encuentro eso en el calendario."
        f = dt.date.fromisoformat(e["fecha"])
        if not self.confirmar(f"borrar del calendario {e['texto']}, {fecha_hablada(f)}{hora_hablada(e.get('hora'))}"):
            return "Vale, lo dejo como está."
        borrar(e["id"])
        if e.get("hora") and e.get("aviso"):
            self.desprogramar(dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}"), e["texto"])
        return f"Borrado del calendario: {e['texto']}."

    # ---------- para la página web
    def datos_web(self) -> dict:
        return {"hoy": dt.date.today().isoformat(), "ahora": f"{dt.datetime.now():%H:%M}", "eventos": leer()}

    def desde_web(self, accion: str, datos: dict) -> dict:
        if accion == "nuevo":
            try:
                fecha = dt.date.fromisoformat(datos["fecha"])
            except (KeyError, ValueError):
                return {"ok": False, "error": "fecha no válida"}
            hora = (datos.get("hora") or "").strip() or None
            if hora and not re.fullmatch(r"\d{2}:\d{2}", hora):
                return {"ok": False, "error": "hora no válida"}
            texto = (datos.get("texto") or "").strip()[:200]
            if not texto:
                return {"ok": False, "error": "falta el texto"}
            aviso = bool(hora) and dt.datetime.fromisoformat(f"{fecha}T{hora}") > dt.datetime.now()
            e = nuevo(fecha, hora, texto, "evento", aviso)
            if aviso:
                self.programar(dt.datetime.fromisoformat(f"{fecha}T{hora}"), texto)
            self.log(f"calendario (web): {fecha} {hora or ''} {texto}")
            return {"ok": True, "evento": e}
        if accion == "borrar":
            e = borrar(str(datos.get("id", "")))
            if e and e.get("hora") and e.get("aviso"):
                self.desprogramar(dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}"), e["texto"])
            return {"ok": bool(e)}
        return {"ok": False, "error": "acción desconocida"}

    # ---------- consultas
    def _rango(self, t: str) -> tuple[dt.date, dt.date, str] | None:
        hoy = dt.date.today()
        if re.search(r"\besta semana\b", t):
            return hoy, hoy + dt.timedelta(days=6 - hoy.weekday()), "esta semana"
        if re.search(r"\b(la semana que viene|la proxima semana)\b", t):
            ini = hoy + dt.timedelta(days=7 - hoy.weekday())
            return ini, ini + dt.timedelta(days=6), "la semana que viene"
        if re.search(r"\beste mes\b", t):
            fin = (hoy.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            return hoy, fin, "este mes"
        if re.search(r"\b(el mes que viene|el proximo mes)\b", t):
            ini = (hoy.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            fin = (ini.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            return ini, fin, "el mes que viene"
        fecha, _ = interpretar_fecha(t, hoy)
        if fecha:
            return fecha, fecha, fecha_hablada(fecha, hoy)
        return None

    def _contar(self, eventos: list[dict], cuando: str) -> Respuesta:
        hoy = dt.date.today()
        if not eventos:
            return Respuesta(f"No tienes nada en el calendario para {cuando}." if cuando not in ("hoy", "mañana")
                             else f"No tienes nada apuntado para {cuando}.")
        items = []
        for e in eventos:
            f = dt.date.fromisoformat(e["fecha"])
            items.append(f"{fecha_hablada(f, hoy).capitalize()}{hora_hablada(e.get('hora'))} — {e['texto']}")
        if self.ui:
            self.ui.enviar(tipo="resultados", titulo=f"Calendario · {cuando}", items=items[:12])
        n = len(eventos)
        un_dia = len({e["fecha"] for e in eventos}) == 1
        partes = []
        for e in eventos[:5]:
            f = dt.date.fromisoformat(e["fecha"])
            cuando_e = " ".join(x for x in ((None if un_dia else fecha_hablada(f, hoy)),
                                            hora_hablada(e.get("hora")).strip() or None) if x)
            partes.append(f"{cuando_e}, {e['texto']}" if cuando_e else e["texto"])
        inicio = cuando[:1].upper() + cuando[1:] if cuando.startswith("del ") else f"Para {cuando}"
        texto = f"{inicio} tienes {n} cosa{'s' if n != 1 else ''}: " + "; ".join(partes) + "."
        if n > 5:
            texto += f" Y {n - 5} más; te las enseño en la pantalla."
        if self.es_telegram():
            texto += "\n" + "\n".join(f"• {x}" for x in items[:15])
        return Respuesta(texto)

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).replace(",", " ")
        t = re.sub(r"\s+", " ", re.sub(r"^(por favor|oye|venga)\s+", "", t))
        hoy = dt.date.today()

        # Abrir la vista mensual
        if re.search(r"\b(abre|abreme|ensename|muestrame|ensena|muestra|ver|pon|ponme|saca)\w*\s+(el |la |mi )?"
                     r"(calendario|agenda)\b", t):
            abrir_calendario()
            if self.es_telegram():
                return Respuesta("Te lo he abierto en la pantalla del portátil. Si lo quieres en el móvil, "
                                 "dime: mándame el calendario.")
            return Respuesta("Abriendo el calendario.")

        # Mandar el .ics
        if re.search(r"\b(mandame|enviame|pasame|manda|envia)\w*\s+(el |mi |la )?(calendario|agenda)\b", t):
            escribir_ics(leer())
            if self.es_telegram():
                return Respuesta("Tu calendario. Ábrelo en el móvil para importarlo.", archivo=str(ICS))
            ok = self.enviar_documento(str(ICS), "📅 Tu calendario de Jarvis (ábrelo para importarlo)")
            return Respuesta("Te he mandado el calendario al móvil." if ok else "No he podido mandarlo por Telegram.")

        # Borrar un evento o un recordatorio concreto
        m = re.search(r"^(?:borra|quita|elimina|cancela|anula|suprime)\w*\s+(?:del calendario\s+|de la agenda\s+|de mi agenda\s+)?"
                      r"(?:el |la )?(?:evento|cita|recordatorio|reunion)?\s*(?:de |del |de la |con )?(.+?)"
                      r"(?:\s+(?:del calendario|de la agenda|de mi agenda))?$", t)
        if m and (re.search(r"\b(calendario|agenda|evento|cita|reunion)\b", t) or
                  re.search(r"\brecordatorio (de|del|para|con)\b", t)):
            return self._borrar(m.group(1), peticion)

        # Consultar
        if re.search(r"\bque (tengo|hay|me toca)\b|\bque planes\b|\bmi agenda\b|\b(hay|tengo) algo\b|\bque hay en el calendario\b"
                     r"|\beventos\b|\bmis citas\b", t) and not re.search(r"\b(tiempo|temperatura|noticias|recordatorios)\b", t):
            rango = self._rango(t)
            if rango is None and not re.search(r"\b(calendario|agenda|citas|eventos|planes|semana|mes)\b", t):
                return None
            if rango is None:
                rango = (hoy, hoy + dt.timedelta(days=7), "los próximos 7 días")
            desde, hasta, cuando = rango
            eventos = entre(desde, hasta)
            if desde == hoy:
                ahora = f"{dt.datetime.now():%H:%M}"
                eventos = [e for e in eventos if e["fecha"] > desde.isoformat() or not e.get("hora") or e["hora"] >= ahora]
            return self._contar(eventos, cuando)

        # Añadir
        # "recuerda que el 25 de octubre es el cambio de hora" (con fecha y sin hora) → evento de día completo
        m = re.match(r"^(?:recuerda(?:me)?|acuerdate de|ten en cuenta|apunta|anota)\w*\s+que\s+(.+)$", t)
        if m:
            fecha, resto = interpretar_fecha(m.group(1), hoy)
            hora, _ = interpretar_hora(resto)
            if fecha is not None and hora is None:
                return self._anadir(m.group(1), peticion)
        m = re.search(r"^(?:apunta|anota|anade|agrega|pon|guarda|mete|agenda|programa|crea|incluye)\w*\s+(?:tambien\s+)?"
                      r"(?:en (?:el|mi) calendario|en (?:la|mi) agenda|al calendario|a la agenda|el calendario|"
                      r"mi calendario|la agenda|un evento|una cita|una reunion)\s*(?:en el calendario\s*)?:?\s*(?:que\s+)?(.+)$", t) or \
            re.search(r"^(?:apunta|anota|anade|agrega|pon|guarda|mete)\w*\s+(.+?)\s+(?:en (?:el|mi) calendario|en (?:la|mi) "
                      r"agenda|al calendario|a la agenda)\b(.*)$", t)
        if m:
            resto = " ".join(g for g in m.groups() if g)
            return self._anadir(resto, peticion)
        return None

    def _anadir(self, resto: str, peticion: str) -> Respuesta:
        # Varias fechas en una sola orden ("17 de octubre trabajo. 21 de octubre ITV. 29 de octubre dentista")
        fechas = list(re.finditer(rf"\b(?:(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo),? )?"
                                  rf"(?:el (?:dia )?|dia )?{NUM_DIA} de {RE_MES}\b", resto))
        if len(fechas) >= 2:
            delante = resto[:fechas[0].start()].strip(" ,.:;") in ("", "que", "el", "para el")
            if delante:                                   # la fecha va delante de cada cosa
                limites = [f.start() for f in fechas] + [len(resto)]
                trozos = [resto[limites[i]:limites[i + 1]] for i in range(len(fechas))]
            else:                                         # la fecha va detrás: "dentista el 29 de octubre, ITV el 21…"
                finales = [f.end() for f in fechas]
                inicios = [0] + finales[:-1]
                trozos = [resto[inicios[i]:finales[i]] for i in range(len(fechas))]
                trozos[-1] += resto[finales[-1]:]
            respuestas = [self._anadir_uno(tr.strip(" ,.;:"), peticion) for tr in trozos if tr.strip(" ,.;:")]
            hechos = [r.texto.removeprefix("Apuntado en el calendario: ") for r in respuestas if r.texto.startswith("Apuntado")]
            if not hechos:
                return respuestas[0]
            return Respuesta(f"Apuntadas {len(hechos)} cosas en el calendario: " + " ".join(hechos))
        return self._anadir_uno(resto, peticion)

    def _anadir_uno(self, resto: str, peticion: str) -> Respuesta:
        hoy = dt.date.today()
        fecha, resto = interpretar_fecha(resto, hoy)
        hora, resto = interpretar_hora(resto)
        que = limpiar_que(resto)
        if not que:
            return Respuesta("¿Qué apunto? Dime por ejemplo: apunta en el calendario dentista el viernes a las diez.")
        que = tildes_por_palabra(peticion, que)
        que = que[:1].upper() + que[1:]
        if fecha is None and hora is None:
            return Respuesta(f"¿Para qué día apunto {que}?")
        if fecha is None:
            ahora = dt.datetime.now()
            fecha = hoy if f"{ahora:%H:%M}" < hora else hoy + dt.timedelta(days=1)
        cuando = dt.datetime.fromisoformat(f"{fecha}T{hora}") if hora else None
        aviso = cuando is not None and cuando > dt.datetime.now()
        nuevo(fecha, hora, que, "evento", aviso)
        if aviso:
            self.programar(cuando, que)
        self.log(f"calendario: {fecha} {hora or 'todo el día'} {que}")
        texto = f"Apuntado en el calendario: {fecha_hablada(fecha, hoy)}{hora_hablada(hora)}, {que}."
        if aviso:
            texto += " Te avisaré a esa hora."
        return Respuesta(texto)

    def _borrar(self, que: str, peticion: str) -> Respuesta:
        que = limpiar_que(que)
        hoy = dt.date.today()
        fecha, que_sin_fecha = interpretar_fecha(que, hoy)
        que = limpiar_que(que_sin_fecha) if fecha else que
        candidatos = [e for e in leer() if fecha is None or e["fecha"] == fecha.isoformat()]
        if fecha is not None and not que:                 # "quita la cita de mañana"
            if not candidatos:
                return Respuesta(f"No tienes nada apuntado {fecha_hablada(fecha, hoy)}.")
            if len(candidatos) > 1:
                lista = "; ".join(f"{e['texto']}{hora_hablada(e.get('hora'))}" for e in candidatos[:4])
                return Respuesta(f"{fecha_hablada(fecha, hoy).capitalize()} tienes {len(candidatos)} cosas: {lista}. "
                                 "Dime cuál borro.")
            que = normalizar(candidatos[0]["texto"])
        puntuados = []
        for e in candidatos:
            nombre = normalizar(e["texto"])
            p = difflib.SequenceMatcher(None, que, nombre).ratio() + (0.6 if que and que in nombre else 0)
            p += 0.3 * len({w for w in que.split() if len(w) > 3} & set(nombre.split()))
            p += 0.15 if e["fecha"] >= hoy.isoformat() else 0
            puntuados.append((p, e))
        puntuados.sort(key=lambda x: -x[0])
        if not puntuados or puntuados[0][0] < 0.55:
            return Respuesta(f"No encuentro nada parecido a {que} en el calendario.")
        e = puntuados[0][1]
        f = dt.date.fromisoformat(e["fecha"])
        if not self.confirmar(f"borrar del calendario {e['texto']}, {fecha_hablada(f, hoy)}{hora_hablada(e.get('hora'))}"):
            return Respuesta("Vale, lo dejo como está.")
        borrar(e["id"])
        if e.get("hora") and e.get("aviso"):
            self.desprogramar(dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}"), e["texto"])
        return Respuesta(f"Borrado del calendario: {e['texto']}.")
