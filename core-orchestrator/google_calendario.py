"""
Sincronización del calendario de Jarvis con Google Calendar (calendario principal), en los dos sentidos.

- Lo que se apunta en Jarvis (voz, Telegram, página) sube a Google al momento y lleva el id de Google ("gid").
- Lo que se borra en Jarvis se borra en Google.
- Lo que apuntas, cambias o borras en el móvil (Google Calendar) baja a Jarvis cada pocos minutos, y si tiene hora
  Jarvis te avisa a esa hora como con sus propios eventos. Los eventos que se repiten (cumpleaños anuales…) llegan
  como días sueltos.
- Solo se mira la ventana de una semana atrás a un año vista. Lo de antes no se toca.
- Los recordatorios cortos ("en 10 minutos…") no suben a Google: solo eventos y recordatorios a más de 2 horas.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Callable

import calendario as cal
from google_cuenta import CuentaGoogle, ErrorGoogle

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CADA = 300                     # segundos entre sincronizaciones completas
ATRAS, ADELANTE = 7, 400       # días de la ventana sincronizada


def _hora_local(texto: str) -> dt.datetime:
    """'2026-10-29T15:10:00+01:00' (o con Z) → hora local sin zona."""
    return dt.datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def _a_google(e: dict) -> dict:
    cuerpo = {"summary": e["texto"], "description": "Apuntado por Jarvis",
              "extendedProperties": {"private": {"jarvis_id": e["id"]}}}
    if e.get("hora"):
        inicio = dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}").astimezone()
        cuerpo["start"] = {"dateTime": inicio.isoformat()}
        cuerpo["end"] = {"dateTime": (inicio + dt.timedelta(minutes=30)).isoformat()}
    else:
        f = dt.date.fromisoformat(e["fecha"])
        cuerpo["start"] = {"date": f.isoformat()}
        cuerpo["end"] = {"date": (f + dt.timedelta(days=1)).isoformat()}
    return cuerpo


def _de_google(g: dict) -> tuple[str, str | None, str] | None:
    """Evento de Google → (fecha, hora o None, texto)."""
    inicio = g.get("start") or {}
    texto = (g.get("summary") or "").strip() or "Evento"
    if inicio.get("dateTime"):
        local = _hora_local(inicio["dateTime"])
        return local.date().isoformat(), f"{local:%H:%M}", texto
    if inicio.get("date"):
        return inicio["date"], None, texto
    return None


class SincronizadorCalendario:
    def __init__(self, cuenta: CuentaGoogle, log=print,
                 programar: Callable[[dt.datetime, str], None] | None = None,
                 desprogramar: Callable[[dt.datetime, str], None] | None = None):
        self.cuenta = cuenta
        self.log = log
        self.programar = programar or (lambda cuando, texto: None)
        self.desprogramar = desprogramar or (lambda cuando, texto: None)
        self._despertar = threading.Event()
        self._lock = threading.Lock()
        self.ultima: float = 0.0
        self.ultimo_error = ""
        cal.AL_CAMBIAR.append(self.pedir)                 # un cambio local se sube enseguida

    def arrancar(self) -> None:
        threading.Thread(target=self._bucle, daemon=True).start()

    def pedir(self) -> None:
        self._despertar.set()

    def _bucle(self) -> None:
        time.sleep(15)
        while True:
            if self.cuenta.conectada:
                try:
                    self.sincronizar()
                except Exception as e:                    # nunca tumbar a Jarvis
                    self.log(f"google calendario: error inesperado {e!r}")
            self._despertar.wait(CADA)
            self._despertar.clear()
            time.sleep(2)                                 # junta varios cambios seguidos en una sola pasada

    # ---------- una pasada completa
    def sincronizar(self) -> dict:
        with self._lock:
            resumen = {"subidos": 0, "borrados_google": 0, "nuevos": 0, "cambiados": 0, "borrados": 0}
            try:
                self._subir_borrados(resumen)
                self._subir_nuevos(resumen)
                self._bajar(resumen)
            except ErrorGoogle as e:
                if str(e) != self.ultimo_error:
                    self.log(f"google calendario: {e}")
                self.ultimo_error = str(e)
                resumen["error"] = str(e)
                return resumen
            self.ultimo_error = ""
            self.ultima = time.time()
            if any(v for k, v in resumen.items()):
                self.log("google calendario: " + ", ".join(f"{k} {v}" for k, v in resumen.items() if v))
            return resumen

    def _subir_borrados(self, resumen: dict) -> None:
        pendientes = cal.leer_borrados()
        if not pendientes:
            return
        quedan = []
        for gid in pendientes:
            try:
                self.cuenta.api("DELETE", f"{API}/{urllib.parse.quote(gid, safe='')}")
                resumen["borrados_google"] += 1
            except ErrorGoogle as e:
                if e.codigo in (404, 410):                # ya no estaba
                    continue
                quedan.append(gid)
                if not e.codigo:
                    raise                                 # sin red: se reintenta en la próxima pasada
        cal.guardar_borrados(quedan)

    def _se_sube(self, e: dict) -> bool:
        if e.get("gid") or e.get("origen") == "google":
            return False
        hoy = dt.date.today().isoformat()
        if e["fecha"] < hoy:
            return False
        if e.get("origen") == "recordatorio":           # solo los que son para más adelante
            if not e.get("hora"):
                return False
            cuando = dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}")
            creado = dt.datetime.fromisoformat(e.get("creado") or dt.datetime.now().isoformat())
            return cuando - creado >= dt.timedelta(hours=2) and cuando > dt.datetime.now()
        return True

    def _subir_nuevos(self, resumen: dict) -> None:
        for e in [x for x in cal.leer() if self._se_sube(x)]:
            g = self.cuenta.api("POST", API, _a_google(e))
            with cal._lock:                                # se apunta el gid sin disparar otra sincronización
                eventos = cal.leer()
                for x in eventos:
                    if x["id"] == e["id"]:
                        x["gid"] = g["id"]
                cal.guardar(eventos)
            resumen["subidos"] += 1

    def _bajar(self, resumen: dict) -> None:
        hoy = dt.date.today()
        desde = dt.datetime.combine(hoy - dt.timedelta(days=ATRAS), dt.time()).astimezone()
        hasta = dt.datetime.combine(hoy + dt.timedelta(days=ADELANTE), dt.time()).astimezone()
        de_google: dict[str, dict] = {}
        token = None
        for _ in range(20):                               # hasta 5.000 eventos
            params = {"timeMin": desde.isoformat(), "timeMax": hasta.isoformat(), "singleEvents": "true",
                      "orderBy": "startTime", "maxResults": 250, "showDeleted": "false"}
            if token:
                params["pageToken"] = token
            r = self.cuenta.api("GET", API, params=params)
            for g in r.get("items", []):
                if g.get("status") != "cancelled" and g.get("id"):
                    de_google[g["id"]] = g
            token = r.get("nextPageToken")
            if not token:
                break
        else:
            return                                        # lista incompleta: mejor no borrar nada
        ahora = dt.datetime.now()
        desde_txt = (hoy - dt.timedelta(days=ATRAS)).isoformat()
        hasta_txt = (hoy + dt.timedelta(days=ADELANTE)).isoformat()
        avisos_quitar, avisos_poner = [], []
        with cal._lock:
            eventos = cal.leer()
            por_gid = {e["gid"]: e for e in eventos if e.get("gid")}
            # Los que Jarvis subió pero aún no tienen gid (subida a medias): se reconocen por jarvis_id.
            por_jid = {(g.get("extendedProperties") or {}).get("private", {}).get("jarvis_id"): gid
                       for gid, g in de_google.items()}
            recuperados = 0
            for e in eventos:
                if not e.get("gid") and e["id"] in por_jid:
                    e["gid"] = por_jid[e["id"]]
                    por_gid[e["gid"]] = e
                    recuperados += 1
            quitar = set()
            for gid, e in por_gid.items():
                if gid in de_google:
                    datos = _de_google(de_google[gid])
                    if not datos or (e["fecha"], e.get("hora"), e["texto"]) == datos:
                        continue
                    if e.get("aviso") and e.get("hora"):
                        avisos_quitar.append((dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}"), e["texto"]))
                    e["fecha"], e["hora"], e["texto"] = datos
                    e["aviso"] = bool(e["hora"]) and dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}") > ahora
                    if e["aviso"]:
                        avisos_poner.append((dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}"), e["texto"]))
                    resumen["cambiados"] += 1
                elif desde_txt <= e["fecha"] <= hasta_txt:
                    quitar.add(e["id"])                   # borrado en el móvil
                    if e.get("aviso") and e.get("hora"):
                        avisos_quitar.append((dt.datetime.fromisoformat(f"{e['fecha']}T{e['hora']}"), e["texto"]))
                    resumen["borrados"] += 1
            eventos = [e for e in eventos if e["id"] not in quitar]
            for gid, g in de_google.items():
                if gid in por_gid:
                    continue
                datos = _de_google(g)
                if not datos:
                    continue
                fecha, hora, texto = datos
                aviso = bool(hora) and dt.datetime.fromisoformat(f"{fecha}T{hora}") > ahora
                eventos.append({"id": uuid.uuid4().hex[:12], "fecha": fecha, "hora": hora, "texto": texto,
                                "origen": "google", "aviso": aviso, "gid": gid,
                                "creado": ahora.isoformat(timespec="seconds")})
                if aviso:
                    avisos_poner.append((dt.datetime.fromisoformat(f"{fecha}T{hora}"), texto))
                resumen["nuevos"] += 1
            if resumen["cambiados"] or resumen["borrados"] or resumen["nuevos"] or recuperados:
                cal.guardar(eventos)
        for cuando, texto in avisos_quitar:
            self.desprogramar(cuando, texto)
        for cuando, texto in avisos_poner:
            self.programar(cuando, texto)

    def estado_hablado(self) -> str:
        if not self.cuenta.conectada:
            return "El calendario no está conectado con Google."
        if self.ultimo_error:
            return f"No he podido sincronizar con Google: {self.ultimo_error[:120]}."
        if not self.ultima:
            return "Todavía no he sincronizado con Google."
        minutos = round((time.time() - self.ultima) / 60)
        return ("Sincronizado con Google Calendar hace un momento." if minutos < 1
                else f"Sincronizado con Google Calendar hace {minutos} minuto{'s' if minutos != 1 else ''}.")
