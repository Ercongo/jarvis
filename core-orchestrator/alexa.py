"""
Alexa de Amazon: lo que tienes conectado a Alexa (luces, enchufes, ventiladores… de cualquier marca) lo maneja también
el asistente, a través del puente scripts/alexa/puente.js (127.0.0.1:3457, alexa-remote2).

  «enciende la luz del salón», «apaga el enchufe de la tele», «apaga todas las luces»
  «pon la luz del dormitorio al 40 por ciento», «baja la luz del salón»
  «qué dispositivos tiene alexa», «qué luces tengo»
  «dile a alexa que ponga una alarma a las ocho»   → se lo dice al Echo como si hablaras tú
  «di por el echo que la cena está lista»           → el Echo lo dice en voz alta
  «conecta alexa»                                   → abre la página para entrar con tu cuenta de Amazon
  «desconecta alexa»                                → olvida la sesión

Se instala con ~/jarvis/instalar_alexa.sh (sin sudo). La contraseña de Amazon la escribes tú en la página de
Amazon; el asistente solo guarda la sesión que da Amazon, en ~/jarvis/alexa.json.
"""

from __future__ import annotations

import difflib
import json
import datetime as dt
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from herramientas import abrir_web, normalizar
from sistema import Respuesta, a_numero

PUENTE = "http://127.0.0.1:3457"
SERVICIO = Path.home() / ".config/systemd/user/alexa-puente.service"

# lo que es del propio portátil o de otros módulos: no se le manda a Alexa salvo que coincida con un aparato suyo
DEL_PC = re.compile(r"\b(pc|ordenador|portatil|equipo|pantalla|monitor|camara|microfono|musica|radio|wifi|bluetooth|"
                    r"sonido|volumen|video|chat web|navegador|telegram|modo|alarma|temporizador|ia)\b")
APARATO = re.compile(r"\b(luz|luces|lampara|lamparas|bombilla|bombillas|foco|focos|led|leds|tira|enchufe|enchufes|"
                     r"regleta|ventilador|calefactor|estufa|radiador|aire acondicionado|purificador|humidificador|"
                     r"persiana|persianas|cafetera|interruptor|plafon|aplique|termostato|tele|television|tv|termo)\b")
ENCENDER = r"enciende|enciendeme|prende|prendeme|conecta|activa"
APAGAR = r"apaga|apagame|desconecta|desactiva"
ARTICULO = r"(?:el |la |los |las |mi |mis )?"


def _pedir(ruta: str, datos: dict | None = None, timeout: float = 20) -> dict | list:
    req = urllib.request.Request(PUENTE + ruta, json.dumps(datos).encode() if datos is not None else None,
                                 {"Content-Type": "application/json"}, method="POST" if datos is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {"error": f"HTTP {e.code}"}


class Alexa:
    def __init__(self, log: Callable[[str], None], es_telegram: Callable[[], bool] = lambda: False, ui=None):
        self.log = log
        self.es_telegram = es_telegram
        self.ui = ui
        self._refrescar = threading.Event()
        self._disp: list[dict] = []
        self._disp_t = 0.0
        self._abierta = 0.0

    # ---------------------------------------------------------------- estado
    @property
    def instalada(self) -> bool:
        return SERVICIO.exists()

    def _estado(self) -> dict:
        try:
            return _pedir("/estado", timeout=5)          # type: ignore[return-value]
        except Exception:
            return {}

    def _dispositivos(self) -> list[dict]:
        if self._disp and time.time() - self._disp_t < 300:
            return self._disp
        try:
            r = _pedir("/dispositivos", timeout=40)
        except Exception:
            return self._disp
        if isinstance(r, list):
            # solo lo que se enciende y apaga: fuera los propios Echo y las cámaras; nombres sin espacios sobrantes
            r = [{**d, "nombre": " ".join(str(d.get("nombre", "")).split())} for d in r
                 if not re.search(r"ALEXA_VOICE_ENABLED|CAMERA|SPEAKER", d.get("tipo", ""), re.I)]
            self._disp, self._disp_t = [d for d in r if d["nombre"]], time.time()
        return self._disp

    def _no_lista(self, est: dict) -> Respuesta:
        if not self.instalada:
            return Respuesta("Todavía no tengo Alexa instalada. Se instala con bash ~/jarvis/instalar_alexa.sh y "
                             "luego me dices «conecta alexa».")
        if not est:
            return Respuesta("El puente con Alexa no responde. Dime «conecta alexa» para arrancarlo.")
        if est.get("login"):
            return self._conectar(est)
        return Respuesta("Estoy conectando con Alexa; prueba en un minuto." if not est.get("error") else
                         "No consigo conectar con Alexa ahora mismo; puede que no haya internet.")

    def _conectar(self, est: dict | None = None) -> Respuesta:
        if not self.instalada:
            return self._no_lista({})
        est = est if est is not None else self._estado()
        if not est:
            import subprocess
            subprocess.run(["systemctl", "--user", "restart", "alexa-puente.service"], capture_output=True, timeout=30)
            for _ in range(15):
                time.sleep(2)
                est = self._estado()
                if est.get("listo") or est.get("login"):
                    break
        if est.get("listo"):
            nombres = [e["nombre"] for e in est.get("echos", [])]
            return Respuesta("Alexa ya está conectada" + (f": tengo {', '.join(nombres)}." if nombres else "."))
        url = est.get("login")
        if not url:
            return Respuesta("No consigo arrancar el puente con Alexa. Detalles en el registro de alexa-puente.")
        if self.es_telegram():
            return Respuesta(f"Para conectar Alexa, abre {url} en un ordenador de casa (mejor que en el móvil) y entra "
                             "con tu cuenta de Amazon. La contraseña la escribes tú en la página de Amazon; yo solo "
                             "guardo la sesión.")
        if time.time() - self._abierta > 600:          # una vez basta: no abrir la página en cada orden
            self._abierta = time.time()
            try:
                abrir_web(url)
            except Exception:
                pass
        return Respuesta("Te he abierto la página de Amazon. Entra con tu cuenta de Amazon (la contraseña la escribes "
                         f"tú; yo no la veo). También puedes abrirla desde otro ordenador de casa: {url}")

    # ---------------------------------------------------------------- la pantalla
    def vigilar(self, cada: int = 60) -> None:
        """Cada minuto (y justo después de encender o apagar algo) manda a la pantalla los aparatos con su estado
        y las alarmas, temporizadores y recordatorios de los Echo."""
        if not self.ui or not self.instalada:
            return

        def bucle():
            time.sleep(20)
            while True:
                try:
                    self.refrescar_pantalla()
                except Exception as e:
                    self.log(f"alexa: pantalla {e!r}")
                self._refrescar.wait(cada)
                self._refrescar.clear()
        threading.Thread(target=bucle, daemon=True, name="alexa-pantalla").start()

    def pedir_refresco(self, tras: float = 3) -> None:
        threading.Timer(tras, self._refrescar.set).start()

    def refrescar_pantalla(self) -> None:
        est = self._estado()
        if not est.get("listo"):
            self.ui.enviar(tipo="casa", conectada=False,
                           aviso="Di «conecta alexa»" if est.get("login") else "Conectando…")
            return
        r = _pedir("/estados", timeout=60)
        if isinstance(r, list):
            aparatos = [{"id": d["id"], "nombre": " ".join(str(d.get("nombre", "")).split()), "tipo": d.get("tipo", ""),
                         "encendido": d.get("encendido"), "brillo": d.get("brillo"),
                         "conectado": d.get("conectado", True)}
                        for d in r if d.get("nombre")]
            aparatos.sort(key=lambda d: normalizar(d["nombre"]))
        else:
            aparatos = (self.ui.casa_ev or {}).get("aparatos") or []
        a = _pedir("/avisos", timeout=40)
        avisos = [self._aviso(x) for x in a] if isinstance(a, list) else []
        self.ui.enviar(tipo="casa", conectada=True, aparatos=aparatos,
                       avisos=[x for x in avisos if x["activa"]][:8],
                       apagadas=sum(1 for x in avisos if not x["activa"] and x["tipo"] != "temporizador"),
                       echos=[e["nombre"] for e in est.get("echos", [])])

    @staticmethod
    def _aviso(x: dict) -> dict:
        tipo = x.get("tipo") or "aviso"
        cuando = ""
        try:
            if x.get("cuando"):
                d = dt.datetime.fromtimestamp(x["cuando"] / 1000)
                hoy = dt.date.today()
                dia = ("hoy" if d.date() == hoy else "mañana" if d.date() == hoy + dt.timedelta(days=1)
                       else d.strftime("%d/%m"))
                cuando = f"{dia} {d:%H:%M}" if tipo != "temporizador" else f"a las {d:%H:%M}"
            elif x.get("hora"):
                cuando = x["hora"]
        except (OverflowError, OSError, ValueError):
            cuando = x.get("hora") or ""
        if x.get("repite") and tipo == "alarma":
            cuando = (x.get("hora") or cuando) + " · se repite"
        texto = x.get("texto") or ("luz que se enciende" if x.get("luz") else tipo)
        return {"tipo": tipo, "cuando": cuando, "texto": texto, "echo": x.get("echo") or "", "activa": bool(x.get("activa"))}

    def desde_pantalla(self, ident: str, encender: bool) -> dict:
        """Tocar un aparato en la pantalla."""
        if not ident:
            return {"ok": False}
        r = _pedir("/accion", {"id": ident, "accion": "turnOn" if encender else "turnOff"}, timeout=30)
        ok = isinstance(r, dict) and bool(r.get("ok"))
        self.log(f"alexa: pantalla {'enciende' if encender else 'apaga'} {r.get('nombre', ident) if isinstance(r, dict) else ident}"
                 f"{'' if ok else ' (falla)'}")
        self.pedir_refresco(2)
        return {"ok": ok, "motivo": (r or {}).get("motivo") or (r or {}).get("error") if not ok else ""}

    # ---------------------------------------------------------------- buscar el aparato
    def _buscar(self, nombre: str) -> tuple[list[dict], float]:
        """Los aparatos que encajan con lo dicho («la luz del salón» → «Luz salón»), y lo seguro que es."""
        n = normalizar(nombre).strip(" .")
        n = re.sub(r"^(el|la|los|las|mi|mis) ", "", n)
        n = re.sub(r"\b(tele|tv)\b", "television", n)
        lista = self._dispositivos()
        if not lista:
            return [], 0.0
        todas = re.match(r"^(todas? (las |los )?|todo )(.*)$", n)
        if todas:
            resto = todas.group(3).strip()
            if resto in ("", "luces", "luz", "lamparas", "bombillas") or resto.startswith("luces"):
                lugar = re.sub(r"^luces( (de|del|de la))? ?", "", resto)
                luces = [d for d in lista if re.search(r"LIGHT", d.get("tipo", ""), re.I)
                         or APARATO.search(normalizar(d["nombre"]) or "") and re.search(r"luz|lampara|bombilla|led|foco",
                                                                                         normalizar(d["nombre"]))]
                if lugar:
                    luces = [d for d in luces if lugar in normalizar(d["nombre"])] or luces
                return luces, 1.0 if luces else 0.0
            if resto in ("enchufes",):
                return [d for d in lista if re.search(r"PLUG|SWITCH", d.get("tipo", ""), re.I)], 1.0
        vacias = {"de", "del", "la", "el", "en", "los", "las", "y"}
        palabras = {w for w in n.split() if w not in vacias}
        mejor, puntos = [], 0.0
        for d in lista:
            dn = normalizar(d["nombre"])
            dp = {w for w in dn.split() if w not in vacias}
            comunes = len(palabras & dp) / max(1, len(dp | palabras))
            parecido = difflib.SequenceMatcher(None, n, dn).ratio()
            p = max(parecido, comunes + (0.2 if palabras and dp <= palabras else 0))
            # «la luz de la cocina» no es «Luz salón»: las palabras que no son de aparato (el sitio) tienen que estar
            clave = {w for w in palabras if not APARATO.search(w)}
            dclave = {w for w in dp if not APARATO.search(w)}
            if clave and not any(difflib.SequenceMatcher(None, a, b).ratio() > 0.8 for a in clave for b in dp):
                p = min(p, 0.4)
            elif dclave and not clave and len(dclave) > 0 and palabras and not (dclave & palabras):
                p = min(p, 0.5)                          # «la luz» a secas y hay varias luces: no adivinar
            if dn == n:
                p = 1.5
            if p > puntos + 0.02:
                mejor, puntos = [d], p
            elif abs(p - puntos) <= 0.02:
                mejor.append(d)
        return (mejor[:1] if puntos >= 1.0 else mejor), puntos

    # ---------------------------------------------------------------- órdenes
    def manejar(self, texto: str) -> Respuesta | None:
        t = normalizar(texto).strip(" .?¿!¡")
        t = re.sub(r"^(athena|atenea|jarvis)[, ]+", "", t)

        if re.search(r"^(conecta|configura|vincula|enlaza|activa|instala)\w* (con )?(a )?(la )?alexa\b", t):
            return self._conectar()
        if re.search(r"^(desconecta|desvincula|olvida)\w* (la cuenta de |la sesion de )?(a )?alexa\b", t):
            if not self.instalada:
                return self._no_lista({})
            _pedir("/salir", {})
            self._disp = []
            return Respuesta("Hecho: he olvidado la sesión de Amazon. Para volver, dime «conecta alexa».")
        if re.search(r"\b(que|cuales|lista\w*|dime)\b.*\b(dispositivos|aparatos|luces|enchufes|cosas)\b.*\balexa\b"
                     r"|\b(que|cuales) (luces|enchufes|dispositivos de casa) (tengo|hay)\b"
                     r"|\balexa\b.*\b(que|cuales) (dispositivos|aparatos)\b", t):
            est = self._estado()
            if not est.get("listo"):
                return self._no_lista(est)
            lista = self._dispositivos()
            if not lista:
                return Respuesta("Alexa no me da ningún dispositivo de casa todavía.")
            nombres = sorted(d["nombre"] for d in lista)
            return Respuesta(f"Alexa tiene {len(nombres)} dispositivos: " + ", ".join(nombres[:25])
                             + (" y más." if len(nombres) > 25 else "."))

        if re.search(r"\b(que|cuales|cuantas|cuantos|tengo|hay|dime|lista\w*)\b", t) and \
                re.search(r"\b(alarmas?|temporizador\w*|recordatorios?|despertador)\b", t) and \
                re.search(r"\b(alexa|echos?|despertador)\b", t):
            return self._decir_avisos()
        m = re.search(r"^(?:dile|pidele|pregunta(?:le)?|manda(?:le)?|ordena(?:le)?) a alexa (?:que )?(.+)$", t)
        if m:
            return self._texto(con_original(texto, m.group(1)))
        # «pon música relajante en el echo del despacho», «para la música de alexa», «sube el volumen del echo»
        m = re.search(r"^((?:pon|ponme|reproduce|toca|para|pausa|deten|quita|sube|baja|continua|siguiente)\w*"
                      r"(?: .+?)?) (?:en|de|del) (?:el |la )?(?:echo|alexa)(?: (?:de |del |de la )?([\w ]+?))?$", t)
        if m:
            return self._texto(con_original(texto, m.group(1)), (m.group(2) or "").strip() or None)
        m = re.search(r"^(?:di|anuncia|avisa|habla)\w* (?:por|en) (?:el |la )?(?:echo|alexa)(?: de (\w+))? (?:que )?(.+)$", t)
        if m:
            return self._decir(con_original(texto, m.group(2)), m.group(1))

        # encender / apagar
        m = re.search(rf"^(?:{ENCENDER}|{APAGAR})\w*(?: me)? {ARTICULO}(.+?)(?: por favor)?$", t)
        if m:
            encender = bool(re.match(rf"^(?:{ENCENDER})", t))
            return self._encender(m.group(1), encender, con_original(texto, t))
        # brillo
        m = re.search(rf"^(?:pon|ponme|deja|ajusta)\w* {ARTICULO}(.+?) (?:al?|en el?) (\w+)(?: ?%| por ?ciento)?$", t)
        if m and (APARATO.search(m.group(1)) or self._buscar(m.group(1))[1] >= 0.75 and self.instalada):
            valor = a_numero(m.group(2)) if not m.group(2).isdigit() else int(m.group(2))
            if valor is not None and 0 <= valor <= 100:
                return self._brillo(m.group(1), valor, con_original(texto, t))
        m = re.search(rf"^(sube|baja)\w* {ARTICULO}(.+)$", t)
        if m and APARATO.search(m.group(2)) and not DEL_PC.search(m.group(2)):
            return self._texto(con_original(texto, t))
        return None

    def _encender(self, objeto: str, encender: bool, original: str) -> Respuesta | None:
        objeto = objeto.strip()
        es_aparato = bool(APARATO.search(objeto))
        if not self.instalada:
            return self._no_lista({}) if es_aparato or "alexa" in objeto else None
        if DEL_PC.search(objeto) and not es_aparato:
            # «apaga la pantalla», «enciende la cámara»…: solo si Alexa tiene un aparato que se llame justo así
            candidatos, p = self._buscar(objeto) if self._disp else ([], 0.0)
            if p < 1.4:
                return None
        else:
            est = self._estado()
            if not est.get("listo"):
                return self._no_lista(est) if es_aparato else None
            candidatos, p = self._buscar(objeto)
        if not candidatos or p < (0.55 if es_aparato else 0.8):
            if not es_aparato:
                return None
            # no sé cómo lo llama Alexa: que lo resuelva ella con la frase tal cual
            return self._texto(original)
        accion = "turnOn" if encender else "turnOff"
        hechos, fallos = [], []
        for d in candidatos[:20]:
            r = _pedir("/accion", {"id": d["id"], "accion": accion}, timeout=30)
            (hechos if isinstance(r, dict) and r.get("ok") else fallos).append(d["nombre"])
        self.log(f"alexa: {accion} {hechos} {('fallan ' + str(fallos)) if fallos else ''}")
        self.pedir_refresco()
        if hechos and not fallos:
            que = hechos[0] if len(hechos) == 1 else f"{len(hechos)} dispositivos"
            return Respuesta(f"{'Encendido' if encender else 'Apagado'}: {que}.")
        if hechos:
            return Respuesta(f"He {'encendido' if encender else 'apagado'} {', '.join(hechos)}, pero no responde "
                             f"{', '.join(fallos)}.")
        return Respuesta(f"{fallos[0]} no responde. Mira si está enchufado y con wifi.")

    def _brillo(self, objeto: str, valor: int, original: str) -> Respuesta:
        est = self._estado()
        if not est.get("listo"):
            return self._no_lista(est)
        candidatos, p = self._buscar(objeto)
        if not candidatos or p < 0.55:
            return self._texto(original)
        hechos = []
        for d in candidatos[:20]:
            r = _pedir("/accion", {"id": d["id"], "accion": "setBrightness" if valor else "turnOff", "valor": valor},
                       timeout=30)
            if isinstance(r, dict) and r.get("ok"):
                hechos.append(d["nombre"])
        self.pedir_refresco()
        if not hechos:
            return Respuesta(f"{candidatos[0]['nombre']} no responde ahora mismo.")
        return Respuesta(f"Puesto al {valor} por ciento: {', '.join(hechos) if len(hechos) < 4 else str(len(hechos)) + ' luces'}.")

    def _decir_avisos(self) -> Respuesta:
        est = self._estado()
        if not est.get("listo"):
            return self._no_lista(est)
        a = _pedir("/avisos", timeout=40)
        if not isinstance(a, list):
            return Respuesta("No consigo ver las alarmas de los Echo ahora mismo.")
        avisos = [self._aviso(x) for x in a]
        activas = [x for x in avisos if x["activa"]]
        self.pedir_refresco(0.5)
        if not activas:
            n = sum(1 for x in avisos if x["tipo"] != "temporizador")
            return Respuesta("Los Echo no tienen ninguna alarma ni recordatorio activo"
                             + (f" (hay {n} desactivados)." if n else "."))
        partes = []
        for x in activas[:6]:
            donde = f" en {x['echo']}" if x["echo"] else ""
            que = "" if x["texto"] in ("alarma", "temporizador", "recordatorio") else f": {x['texto']}"
            partes.append(f"{x['tipo']} {x['cuando']}{donde}{que}".strip())
        return Respuesta(f"Tienes {len(activas)} activos. " + "; ".join(partes) + ".")

    def _texto(self, frase: str, echo: str | None = None) -> Respuesta:
        est = self._estado()
        if not est.get("listo"):
            return self._no_lista(est)
        r = _pedir("/texto", {"texto": frase, "echo": echo}, timeout=30)
        if isinstance(r, dict) and r.get("ok"):
            self.pedir_refresco(6)
            return Respuesta("Hecho, se lo he dicho a Alexa.")
        return Respuesta(f"No he podido hablar con Alexa: {(r or {}).get('error', 'sin respuesta')}.")

    def _decir(self, frase: str, echo: str | None = None) -> Respuesta:
        est = self._estado()
        if not est.get("listo"):
            return self._no_lista(est)
        r = _pedir("/decir", {"texto": frase, "echo": echo}, timeout=30)
        if isinstance(r, dict) and r.get("ok"):
            return Respuesta("Dicho por el Echo.")
        return Respuesta(f"El Echo no lo ha dicho: {(r or {}).get('error', 'sin respuesta')}.")


def con_original(original: str, fragmento: str) -> str:
    """El trozo de la frase con sus tildes originales (Alexa entiende mejor «salón» que «salon»)."""
    import unicodedata
    plano = "".join("".join(c for c in unicodedata.normalize("NFD", ch.lower()) if unicodedata.category(c) != "Mn")[:1]
                    or " " for ch in original)
    i = plano.find(fragmento)
    return original[i:i + len(fragmento)].strip(" .") if i >= 0 else fragmento
