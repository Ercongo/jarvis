"""
Correo de Gmail para Jarvis (necesita la cuenta de Google conectada).

Órdenes (el cerebro en la nube las entiende dichas de cualquier forma; estas también funcionan sin él):
  "¿tengo correos nuevos?" / "lee mis correos"            → los no leídos de la bandeja principal
  "léeme el primero" / "léeme el correo de Amazon"        → lo lee (o lo resume si es largo) y lo marca leído
  "resume mis correos"                                    → resumen de los no leídos
  "contesta a Juan que el jueves me va bien"              → redacta la respuesta, te la lee y pide confirmación
  "manda un correo a Ana diciendo que llego tarde"        → busca su dirección en tus correos y pide confirmación
  "¿me ha escrito el banco?"                              → busca en todo el correo
  "marca los correos como leídos"                         → pide confirmación
  "avísame de los correos importantes" / "no me avises de los correos"
Nunca envía nada sin que digas que sí. No borra correos.
"""

from __future__ import annotations

import base64
import concurrent.futures
import datetime as dt
import email.utils
import html
import json
import re
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from google_cuenta import CuentaGoogle, ErrorGoogle
from herramientas import guardar_config, leer_config, normalizar
from sistema import Respuesta

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
AVISADOS = Path.home() / "jarvis" / "correo_avisados.json"
NO_LEIDOS = "is:unread in:inbox category:primary"
IMPORTANTES = "is:unread is:important in:inbox category:primary newer_than:2d"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
ORDINALES = {"primer": 1, "primero": 1, "primera": 1, "segundo": 2, "segunda": 2, "tercer": 3, "tercero": 3,
             "tercera": 3, "cuarto": 4, "cuarta": 4, "quinto": 5, "quinta": 5, "sexto": 6, "septimo": 7,
             "octavo": 8, "ultimo": -1, "ultima": -1}
NO_CONECTADO = ("Todavía no tengo acceso a tu correo. Primero hay que conectar tu cuenta de Google: "
                "di «conecta mi cuenta de Google».")


# =============================================================== utilidades

def _b64(datos: str) -> bytes:
    return base64.urlsafe_b64decode(datos + "=" * (-len(datos) % 4))


def _texto_de_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    return html.unescape(h)


def _cuerpo(payload: dict) -> str:
    """El texto de un mensaje: text/plain si lo hay; si no, el HTML sin etiquetas."""
    planos, htmls = [], []

    def recorrer(p: dict) -> None:
        tipo = p.get("mimeType", "")
        datos = (p.get("body") or {}).get("data")
        if datos and tipo == "text/plain":
            planos.append(_b64(datos).decode("utf-8", "replace"))
        elif datos and tipo == "text/html":
            htmls.append(_b64(datos).decode("utf-8", "replace"))
        for hijo in p.get("parts") or []:
            recorrer(hijo)
    recorrer(payload)
    texto = "\n".join(planos) if planos else _texto_de_html("\n".join(htmls))
    # Sin la parte citada de correos anteriores ni líneas vacías de más
    corte = re.search(r"(?m)^(>|El .{5,80} escribi[óo]:|On .{5,80} wrote:|-----Original Message-----|"
                      r"De: .{3,80}\n(Enviado|Fecha|Sent):)", texto)
    if corte:
        texto = texto[:corte.start()]
    texto = re.sub(r"[ \t ]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def _cabeceras(msg: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers", [])}


def _resumen_mensaje(msg: dict) -> dict:
    cab = _cabeceras(msg)
    nombre, direccion = email.utils.parseaddr(cab.get("from", ""))
    nombre = (nombre or direccion.split("@")[0] or "alguien").strip().strip('"')
    etiquetas = msg.get("labelIds") or []
    return {"id": msg["id"], "hilo": msg.get("threadId"), "nombre": nombre, "email": direccion.lower(),
            "asunto": (cab.get("subject") or "(sin asunto)").strip(), "snippet": html.unescape(msg.get("snippet", "")),
            "fecha": dt.datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000),
            "no_leido": "UNREAD" in etiquetas, "importante": "IMPORTANT" in etiquetas,
            "message_id": cab.get("message-id", ""), "references": cab.get("references", ""),
            "para": cab.get("to", "")}


def fecha_correo(f: dt.datetime) -> str:
    hoy = dt.date.today()
    if f.date() == hoy:
        return f"a las {f:%-H:%M}"
    if f.date() == hoy - dt.timedelta(days=1):
        return "ayer"
    return f"el {f.day} de {MESES[f.month - 1]}"


def direccion_dictada(texto: str) -> str | None:
    """'juan punto perez arroba gmail punto com' → 'juan.perez@gmail.com'."""
    t = normalizar(texto)
    t = re.sub(r"\s*\b(arroba)\b\s*", "@", t)
    t = re.sub(r"\s*\b(punto)\b\s*", ".", t)
    t = re.sub(r"\s*\b(guion bajo)\b\s*", "_", t)
    t = re.sub(r"\s*\b(guion)\b\s*", "-", t)
    m = re.search(r"[\w.+-]+(?: [\w.+-]+)*@[\w-]+(?:\.[\w-]+)+", t)
    if not m:
        return None
    d = m.group(0).replace(" ", "")
    return d if re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", d) else None


# =============================================================== el módulo

class Correo:
    def __init__(self, cuenta: CuentaGoogle, decir: Callable[..., None], confirmar: Callable[[str], bool],
                 log=print, ui=None, cerebro=None, resumir: Callable[[str, str], str] | None = None,
                 avisar: Callable[[str], None] | None = None, es_telegram: Callable[[], bool] | None = None):
        self.cuenta = cuenta
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.ui = ui
        self.cerebro = cerebro
        self.resumir = resumir or (lambda instruccion, texto: texto[:400])
        self.avisar = avisar or (lambda texto: None)
        self.es_telegram = es_telegram or (lambda: False)
        self.lista: list[dict] = []                      # lo último que se ha enseñado, para "léeme el segundo"
        self._lista_cuando = 0.0
        self._bandeja: tuple[float, list[dict]] | None = None
        self.sync = None                                 # el sincronizador del calendario (lo pone Jarvis)

    # ---------- Gmail
    def listar(self, consulta: str, maximo: int = 8) -> list[dict]:
        r = self.cuenta.api("GET", f"{GMAIL}/messages", params={"q": consulta, "maxResults": maximo})
        ids = [m["id"] for m in r.get("messages", [])]
        if not ids:
            return []

        def uno(i: str) -> dict:
            return _resumen_mensaje(self.cuenta.api("GET", f"{GMAIL}/messages/{i}", params={
                "format": "metadata", "metadataHeaders": ["From", "Subject", "To", "Message-ID", "References"]}))
        with concurrent.futures.ThreadPoolExecutor(4) as ex:
            mensajes = list(ex.map(uno, ids))
        return sorted(mensajes, key=lambda m: m["fecha"], reverse=True)

    def completo(self, ident: str) -> dict:
        msg = self.cuenta.api("GET", f"{GMAIL}/messages/{ident}", params={"format": "full"})
        datos = _resumen_mensaje(msg)
        datos["cuerpo"] = _cuerpo(msg.get("payload") or {})
        return datos

    def marcar_leidos(self, ids: list[str]) -> None:
        if ids:
            self.cuenta.api("POST", f"{GMAIL}/messages/batchModify", {"ids": ids, "removeLabelIds": ["UNREAD"]})
            self._bandeja = None

    def enviar(self, para: str, asunto: str, cuerpo: str, original: dict | None = None) -> None:
        m = EmailMessage()
        m["To"] = para
        if self.cuenta.email:
            m["From"] = self.cuenta.email
        m["Subject"] = asunto
        if original and original.get("message_id"):
            m["In-Reply-To"] = original["message_id"]
            m["References"] = (original.get("references", "") + " " + original["message_id"]).strip()
        m.set_content(cuerpo)
        cuerpo_api = {"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}
        if original and original.get("hilo"):
            cuerpo_api["threadId"] = original["hilo"]
        self.cuenta.api("POST", f"{GMAIL}/messages/send", cuerpo_api)
        self._bandeja = None

    def _recordar_lista(self, mensajes: list[dict]) -> None:
        self.lista = mensajes
        self._lista_cuando = time.time()

    def _de_lista(self, n: int) -> dict | None:
        if not self.lista or time.time() - self._lista_cuando > 1800:
            return None
        if n == -1:
            return self.lista[-1]
        return self.lista[n - 1] if 1 <= n <= len(self.lista) else None

    # ---------- para el cerebro en la nube
    def contexto_ia(self) -> str:
        if not self.cuenta.conectada:
            return "no conectado (si piden algo del correo, di que antes hay que decir «conecta mi cuenta de Google»)"
        try:
            if self.lista and time.time() - self._lista_cuando < 600:
                mensajes, origen = self.lista, "lo último que se ha enseñado al usuario"
            else:
                if not self._bandeja or time.time() - self._bandeja[0] > 90:
                    self._bandeja = (time.time(), self.listar("in:inbox category:primary newer_than:14d", 8))
                mensajes, origen = self._bandeja[1], "bandeja principal, lo más reciente"
                self._recordar_lista(mensajes)
        except ErrorGoogle as e:
            return f"no disponible ahora ({e})"
        if not mensajes:
            return "bandeja vacía"
        lineas = [f"c{i + 1} | {m['nombre']} <{m['email']}> | {m['asunto'][:80]} | {m['fecha']:%d/%m %H:%M}"
                  f"{' | NO LEÍDO' if m['no_leido'] else ''}" for i, m in enumerate(mensajes)]
        return f"({origen}) " + "; ".join(lineas)

    def _por_id(self, ident: str) -> dict | None:
        m = re.fullmatch(r"c?(\d+)", str(ident).strip().lower())
        return self._de_lista(int(m.group(1))) if m else None

    def accion(self, a: dict) -> str:
        """Ejecuta una acción de correo que ha decidido el cerebro. Devuelve lo que se dice."""
        if not self.cuenta.conectada:
            return NO_CONECTADO
        tipo = a.get("tipo")
        try:
            if tipo == "correo_lista":
                return self.leer_lista(NO_LEIDOS if a.get("solo_no_leidos", True) else "in:inbox category:primary")
            if tipo == "correo_buscar":
                return self.leer_lista(str(a.get("consulta") or ""), buscando=True)
            if tipo == "correo_leer":
                m = self._por_id(a.get("id", ""))
                return self.leer_uno(m) if m else "No sé qué correo quieres que te lea. Pídeme antes la lista."
            if tipo == "correo_resumir":
                return self.resumen_no_leidos()
            if tipo == "correo_responder":
                m = self._por_id(a.get("id", ""))
                if not m:
                    return "No sé a qué correo quieres contestar. Pídeme antes la lista."
                return self.responder(m, str(a.get("texto") or ""))
            if tipo == "correo_nuevo":
                return self.nuevo(str(a.get("para") or ""), str(a.get("asunto") or ""), str(a.get("texto") or ""))
        except ErrorGoogle as e:
            self.log(f"correo: {e}")
            return "No he podido hablar con Gmail ahora mismo. Inténtalo en un rato."
        return ""

    # ---------- lo que hace
    def leer_lista(self, consulta: str, buscando: bool = False) -> str:
        mensajes = self.listar(consulta, 8)
        self._recordar_lista(mensajes)
        if not mensajes:
            return "No he encontrado ningún correo así." if buscando else "No tienes correos nuevos. Bandeja al día."
        items = [f"{m['nombre']} — {m['asunto']} ({fecha_correo(m['fecha'])})" for m in mensajes]
        if self.ui:
            self.ui.enviar(tipo="resultados", titulo="Correo" + (" · búsqueda" if buscando else " · sin leer"),
                           items=items)
        n = len(mensajes)
        if buscando:
            cabeza = f"He encontrado {n} correo{'s' if n != 1 else ''}"
        else:
            cabeza = f"Tienes {n}{' o más' if n == 8 else ''} correo{'s' if n != 1 else ''} sin leer"
        if self.es_telegram():
            return cabeza + ":\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(items)) + \
                "\nDime «léeme el 2» o «contesta al 1 que…»."
        partes = [f"de {m['nombre']}, {m['asunto']}" for m in mensajes[:4]]
        texto = cabeza + ": " + "; ".join(partes) + "."
        if n > 4:
            texto += " Y más en la pantalla."
        return texto + " ¿Te leo alguno?"

    def leer_uno(self, m: dict) -> str:
        c = self.completo(m["id"])
        if c["no_leido"]:
            try:
                self.marcar_leidos([c["id"]])
            except ErrorGoogle:
                pass
        cuerpo = c["cuerpo"] or c["snippet"]
        cabeza = f"Correo de {c['nombre']}, {fecha_correo(c['fecha'])}. Asunto: {c['asunto']}."
        if self.es_telegram():
            if len(cuerpo) > 1500:
                resumen = self.resumir("Resume este correo en dos o tres frases y di si pide algo al usuario.", cuerpo)
                return f"{cabeza}\nResumen: {resumen}\n\n{cuerpo[:1500]}…"
            return f"{cabeza}\n\n{cuerpo}"
        if len(cuerpo) > 500:
            resumen = self.resumir("Resume este correo en dos o tres frases para leerlo en voz alta, y di si pide "
                                   "algo al usuario o tiene alguna fecha.", cuerpo)
            return f"{cabeza} En resumen: {resumen}"
        cuerpo = re.sub(r"https?://\S+", "un enlace", cuerpo)
        return f"{cabeza} Dice: {cuerpo}"

    def resumen_no_leidos(self) -> str:
        mensajes = self.listar(NO_LEIDOS, 10)
        self._recordar_lista(mensajes)
        if not mensajes:
            return "No tienes correos sin leer."
        texto = "\n".join(f"{i + 1}. De {m['nombre']} — {m['asunto']}: {m['snippet']}" for i, m in enumerate(mensajes))
        return self.resumir("Estos son los correos sin leer del usuario. Resúmelos en pocas frases: qué es importante, "
                            "qué pide algo o tiene fecha, y qué es publicidad. Nombra a los remitentes.", texto)

    def _redactar(self, encargo: str, original: dict | None, para: str = "") -> tuple[str, str]:
        """Devuelve (asunto, cuerpo). Con el cerebro, bien redactado; sin él, lo dictado tal cual."""
        if self.cerebro and self.cerebro.activo:
            from cerebro import SinConexion
            contexto = ""
            if original:
                contexto = (f"Correo al que se responde (de {original['nombre']}, asunto «{original['asunto']}»):\n"
                            f"{(original.get('cuerpo') or original.get('snippet', ''))[:3000]}\n\n")
            try:
                bruto = self.cerebro.chat([
                    {"role": "system", "content":
                        "Redactas correos en nombre del usuario, en español de España, con el tono que pida la "
                        "situación (cercano con conocidos, formal con empresas). Escribe solo lo que el usuario "
                        "quiere decir, sin inventar datos, compromisos ni citas que no haya dicho. Sin firma con "
                        "nombre; termina con un saludo breve. Devuelve JSON: {\"asunto\": \"...\", \"cuerpo\": \"...\"}."},
                    {"role": "user", "content": f"{contexto}Destinatario: {para or (original or {}).get('nombre', '')}\n"
                                                f"Lo que quiere decir el usuario: {encargo}"}],
                    formato_json=True, max_tokens=900, temperatura=0.4, timeout=40)
                datos = json.loads(re.search(r"\{.*\}", bruto, re.S).group(0))
                cuerpo = str(datos.get("cuerpo") or "").strip()
                if cuerpo:
                    return str(datos.get("asunto") or "").strip(), cuerpo
            except (SinConexion, AttributeError, ValueError, TypeError) as e:
                self.log(f"correo: no se pudo redactar con el cerebro ({e}); uso lo dictado")
        cuerpo = encargo.strip()
        cuerpo = (cuerpo[:1].upper() + cuerpo[1:]).rstrip(".") + ".\n\nUn saludo."
        return "", cuerpo

    def _confirmar_envio(self, nombre: str, direccion: str, asunto: str, cuerpo: str) -> bool:
        if self.es_telegram():
            return self.confirmar(f"enviar este correo a {nombre} <{direccion}>\nAsunto: {asunto}\n\n{cuerpo}\n\n")
        dicho = direccion.replace("@", " arroba ").replace(".", " punto ")
        return self.confirmar(f"enviar a {nombre}, {dicho}, este correo. Asunto: {asunto}. Dice: {cuerpo}")

    def responder(self, m: dict, encargo: str) -> str:
        if not encargo.strip():
            return f"¿Qué quieres que le conteste a {m['nombre']}?"
        original = self.completo(m["id"])
        _, cuerpo = self._redactar(encargo, original)
        asunto = original["asunto"] if original["asunto"].lower().startswith("re:") else "Re: " + original["asunto"]
        if not self._confirmar_envio(original["nombre"], original["email"], asunto, cuerpo):
            return "Vale, no lo envío."
        self.enviar(original["email"], asunto, cuerpo, original)
        self.log(f"correo: respuesta enviada a {original['email']}")
        return f"Enviada la respuesta a {original['nombre']}."

    def buscar_direccion(self, quien: str) -> tuple[str, str] | None:
        """Nombre → (nombre, dirección), buscando en los correos que te han mandado o has mandado."""
        directa = direccion_dictada(quien)
        if directa:
            return directa.split("@")[0], directa
        q = normalizar(quien).strip()
        if not q:
            return None
        recuentos: dict[str, list] = {}
        for m in self.listar(f"from:({q}) OR to:({q})", 10):
            candidatos = [(m["nombre"], m["email"])] + [email.utils.parseaddr(x) for x in m["para"].split(",")]
            for nombre, direccion in candidatos:
                direccion = direccion.lower()
                if direccion and direccion != self.cuenta.email.lower() and \
                        all(p in normalizar(f"{nombre} {direccion}") for p in q.split()):
                    recuentos.setdefault(direccion, [nombre or direccion.split("@")[0], 0])[1] += 1
        if not recuentos:
            return None
        direccion, (nombre, _) = max(recuentos.items(), key=lambda x: x[1][1])
        return nombre, direccion

    def nuevo(self, para: str, asunto: str, encargo: str) -> str:
        if not para.strip():
            return "¿A quién se lo mando?"
        if not encargo.strip():
            return "¿Qué quieres que diga el correo?"
        destino = self.buscar_direccion(para)
        if not destino:
            return (f"No encuentro la dirección de {para} en tus correos. Dímela, por ejemplo: "
                    "«manda un correo a juan punto perez arroba gmail punto com…», o escríbemela por Telegram.")
        nombre, direccion = destino
        asunto_ia, cuerpo = self._redactar(encargo, None, nombre)
        asunto = asunto.strip() or asunto_ia or "Mensaje"
        if not self._confirmar_envio(nombre, direccion, asunto, cuerpo):
            return "Vale, no lo envío."
        self.enviar(direccion, asunto, cuerpo)
        self.log(f"correo: enviado a {direccion}")
        return f"Correo enviado a {nombre}."

    # ---------- para el resumen de la mañana
    def resumen_breve(self) -> tuple[str, list[str]]:
        """(frase para decir, líneas para Telegram)."""
        if not self.cuenta.conectada:
            return "", []
        mensajes = self.listar(NO_LEIDOS + " newer_than:2d", 10)
        if not mensajes:
            return "No tienes correos nuevos.", []
        importantes = [m for m in mensajes if m["importante"]]
        n = len(mensajes)
        texto = f"Tienes {n}{' o más' if n == 10 else ''} correo{'s' if n != 1 else ''} sin leer"
        destacados = importantes[:3] or mensajes[:2]
        texto += (", entre ellos de " if importantes else ", por ejemplo de ") + \
            ", ".join(dict.fromkeys(m["nombre"] for m in destacados)) + "."
        self._recordar_lista(mensajes)
        return texto, [f"{'⭐ ' if m['importante'] else ''}{m['nombre']} — {m['asunto']}" for m in mensajes[:6]]

    # ---------- avisos de correos importantes
    def arrancar_vigilante(self) -> None:
        threading.Thread(target=self._vigilar, daemon=True).start()

    def _vigilar(self) -> None:
        time.sleep(60)
        fallos = 0
        while True:
            if self.cuenta.conectada and leer_config().get("avisar_correos", True):
                try:
                    self._comprobar_importantes()
                    fallos = 0
                except ErrorGoogle as e:
                    fallos += 1
                    if fallos == 3:
                        self.log(f"correo: el vigilante no llega a Gmail ({e})")
                except Exception as e:
                    self.log(f"correo: error en el vigilante {e!r}")
            time.sleep(180)

    def _comprobar_importantes(self) -> None:
        try:
            vistos = set(json.loads(AVISADOS.read_text(encoding="utf-8")))
            primera_vez = False
        except (OSError, ValueError):
            vistos, primera_vez = set(), True
        mensajes = self.listar(IMPORTANTES, 10)
        nuevos = [m for m in mensajes if m["id"] not in vistos]
        if nuevos or primera_vez:
            vistos |= {m["id"] for m in mensajes}
            AVISADOS.write_text(json.dumps(sorted(vistos)[-400:]), encoding="utf-8")
        if primera_vez or not nuevos:
            return                                       # la primera vez solo se apunta lo que ya había
        self._recordar_lista(nuevos)
        for m in nuevos[:3]:
            self.avisar(f"📧 Correo importante de {m['nombre']}\n{m['asunto']}\n{m['snippet'][:200]}")
        if len(nuevos) > 3:
            self.avisar(f"📧 Y {len(nuevos) - 3} correos importantes más.")
        if 8 <= dt.datetime.now().hour < 23:
            if len(nuevos) == 1:
                self.decir(f"Te ha llegado un correo importante de {nuevos[0]['nombre']}: {nuevos[0]['asunto']}. "
                           "Si quieres, te lo leo.")
            else:
                self.decir(f"Te han llegado {len(nuevos)} correos importantes, de " +
                           ", ".join(dict.fromkeys(m["nombre"] for m in nuevos[:3])) + ".")
        self.log(f"correo: avisados {len(nuevos)} importantes")

    # ---------- cuenta de Google y sincronización
    def _ordenes_google(self, t: str) -> Respuesta | None:
        if re.search(r"\bdesconecta\w* (mi |la )?(cuenta de )?(google|gmail)\b", t):
            if not self.cuenta.conectada:
                return Respuesta("Tu cuenta de Google no está conectada.")
            if not self.confirmar("desconectar tu cuenta de Google: dejaré de ver tu correo y tu calendario de Google"):
                return Respuesta("Vale, sigue conectada.")
            self.cuenta.desconectar()
            return Respuesta("Cuenta de Google desconectada. Tu calendario de Jarvis se queda como está.")
        if re.search(r"\b(conecta|conectate|vincula|enlaza|configura)(me|la|lo)? (con |a )?(mi |la )?(cuenta de )?"
                     r"(google|gmail)\b", t) and not re.search(r"\b(estas|esta|sigues) conectad", t):
            from google_cuenta import URL_CONECTAR
            from herramientas import abrir_web
            if not self.cuenta.tiene_cliente:
                return Respuesta("Antes necesito el archivo de credenciales de Google, el client_secret punto json. "
                                 "Mándamelo por Telegram como documento y luego repite «conecta mi cuenta de Google».")
            abrir_web(URL_CONECTAR)
            aviso = ("Te he abierto la página de permisos de Google en el portátil: entra con tu cuenta, pulsa "
                     "«Avanzado» e «Ir a Jarvis» si te avisa de que no está verificada, marca todas las casillas y acepta.")
            if self.es_telegram():
                aviso += " Tiene que ser en el propio portátil, porque Google me devuelve el permiso allí."
            return Respuesta(aviso)
        if re.search(r"\bsincroniza\w* (el |mi )?calendario\b|\bcomo va (la sincronizacion|google calendar)\b", t):
            if not self.cuenta.conectada:
                return Respuesta("El calendario no está conectado con Google. Di «conecta mi cuenta de Google».")
            if not self.sync:
                return None
            r = self.sync.sincronizar()
            if r.get("error"):
                return Respuesta(self.sync.estado_hablado())
            cambios = [f"{v} {k.replace('_', ' en ')}" for k, v in r.items() if v]
            return Respuesta("Calendario sincronizado con Google" + (": " + ", ".join(cambios) if cambios else
                                                                      "; no había nada nuevo") + ".")
        if re.search(r"\b(estas|esta) conectad\w* (a|con) (google|gmail)\b|\bestado de (la cuenta de )?google\b", t):
            if not self.cuenta.conectada:
                return Respuesta("No, tu cuenta de Google no está conectada.")
            return Respuesta(f"Sí, estoy conectado a {self.cuenta.email or 'tu cuenta de Google'}. "
                             + (self.sync.estado_hablado() if self.sync else ""))
        return None

    # ---------- órdenes sin cerebro (o mandadas por él como "orden")
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        t = re.sub(r"^(por favor|oye|venga)\s+", "", t)
        if re.search(r"\b(no|deja de) (me )?avis\w* (de|con) (los )?correos\b|\bdesactiva\w* (los )?avisos de correo", t):
            guardar_config(avisar_correos=False)
            return Respuesta("Vale, ya no te aviso de los correos importantes.")
        if re.search(r"\bavisa\w* (de|con|cuando lleguen) (los )?correos\b|\bactiva\w* (los )?avisos de correo", t):
            guardar_config(avisar_correos=True)
            return Respuesta("Hecho: te avisaré cuando te llegue un correo importante.")
        r = self._ordenes_google(t)
        if r is not None:
            return r
        habla_de_correo = re.search(r"\b(correos?|e-?mails?|mails?|gmail|bandeja de entrada)\b", t)
        if not habla_de_correo and not re.search(r"^leeme (el|la) (\w+)$", t):
            return None
        if not self.cuenta.conectada:
            return Respuesta(NO_CONECTADO)
        try:
            m = re.search(r"\bleeme (?:el|la) (?:correo |mensaje )?(?:numero )?(\d+|" + "|".join(ORDINALES) + r")\b", t)
            if m:
                n = int(m.group(1)) if m.group(1).isdigit() else ORDINALES[m.group(1)]
                correo = self._de_lista(n)
                return Respuesta(self.leer_uno(correo) if correo else "Pídeme antes la lista de correos.")
            if re.search(r"\bresum\w* (mis |los )?correos\b", t):
                return Respuesta(self.resumen_no_leidos())
            if re.search(r"\bmarca\w* .*\bleidos?\b", t):
                mensajes = self.listar(NO_LEIDOS, 50)
                if not mensajes:
                    return Respuesta("No tienes correos sin leer.")
                if not self.confirmar(f"marcar como leídos {len(mensajes)} correos"):
                    return Respuesta("Vale, los dejo como están.")
                self.marcar_leidos([x["id"] for x in mensajes])
                return Respuesta(f"Hecho: {len(mensajes)} correos marcados como leídos.")
            if re.search(r"\b(tengo|hay|me han llegado|ha llegado)\b.*\bcorreos?\b|\b(lee|leeme|mira|revisa|consulta)\w* "
                         r"(el |mi |los |mis )?(correos?|e-?mails?|mails?|gmail|bandeja)\b", t):
                return Respuesta(self.leer_lista(NO_LEIDOS))
        except ErrorGoogle as e:
            self.log(f"correo: {e}")
            return Respuesta("No he podido hablar con Gmail ahora mismo. Inténtalo en un rato.")
        if re.search(r"\b(contesta|responde|manda|envia|escribe)\w*\b", t):
            return Respuesta("Para escribir correos necesito el cerebro en la nube, y ahora mismo no está disponible.")
        return None
