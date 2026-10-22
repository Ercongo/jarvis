"""
Cerebro en la nube para Jarvis (Groq, gratis con una clave de console.groq.com).

- Oído: whisper-large-v3 en Groq. Solo se manda lo que dices DESPUÉS de "Jarvis" (la palabra clave se sigue
  detectando en el portátil, así que el sonido ambiente nunca sale de casa).
- Cerebro: un modelo grande (GPT-OSS 120B, con otros de reserva) que entiende la orden completa y devuelve
  acciones concretas en JSON: eventos con su fecha exacta, recordatorios, consultas, borrados, órdenes para
  los módulos de Jarvis o una respuesta hablada.
- Si no hay clave, no hay internet o se acaba el cupo del día, Jarvis vuelve solo a lo local (reglas + IA pequeña).

La clave se guarda en ~/jarvis/groq.json (permisos 600). Se puede dar por Telegram: "clave groq gsk_…".
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

import numpy as np
from perfil import SECRETOS, con_nombre, perfil

CONFIG = SECRETOS / "groq.json"
API = "https://api.groq.com/openai/v1"
PREFERENCIA_CHAT = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "llama-3.1-8b-instant",
                    "qwen/qwen3.8-27b"]
# Para trabajos secundarios (resúmenes, datos de fondo…): primero los pequeños, así el grande queda libre para
# entender órdenes. Con la clave gratuita cada modelo tiene su propio cupo de ~8000 tokens por minuto.
PREFERENCIA_LIGERA = ["openai/gpt-oss-20b", "llama-3.1-8b-instant", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
PREFERENCIA_VOZ = ["whisper-large-v3", "whisper-large-v3-turbo"]
# Modelos que ven imágenes (el primero que ofrezca la clave)
PREFERENCIA_VISION = ["qwen/qwen3.8-27b", "meta-llama/llama-4-maverick-17b-128e-instruct",
                      "meta-llama/llama-4-scout-17b-16e-instruct"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
# Frases que whisper "oye" en el silencio (vienen de subtítulos con los que se entrenó)
ALUCINACIONES = re.compile(r"amara\.org|subt[ií]tulos|gracias por ver|suscr[ií]bete|♪", re.I)


class SinConexion(Exception):
    pass


def leer_clave() -> str:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("api_key", "").strip()
    except (OSError, ValueError):
        return ""


def a_wav(audio: np.ndarray, rate: int = 16000) -> bytes:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Cerebro:
    def __init__(self, log=print):
        self.log = log
        self.clave = leer_clave()
        self.modelos_chat: list[str] = []
        self.modelo_voz: str | None = None
        self.modelo_vision: str | None = None
        self._pausa: dict[str, float] = {}               # modelo → hasta cuándo no usarlo (cupo agotado)
        self._cupo: dict[str, tuple[int, float]] = {}    # modelo → (tokens que quedan este minuto, cuándo se renueva)
        self._ultimas_cabeceras: dict = {}
        self._sin_red_hasta = 0.0
        self.al_cambiar = lambda: None                    # para el panel de la pantalla
        self.respaldo = None                              # Nex (OpenRouter): piensa si Groq no puede
        if self.clave:
            threading.Thread(target=self.detectar, daemon=True).start()

    # ---------- estado
    @property
    def groq_activo(self) -> bool:
        return bool(self.clave and self.modelos_chat) and time.time() > self._sin_red_hasta \
            and any(self._pausa.get(m, 0) < time.time() for m in self.modelos_chat)

    @property
    def activo(self) -> bool:
        return self.groq_activo or bool(self.respaldo and self.respaldo.activo)

    @property
    def oido_activo(self) -> bool:
        return bool(self.clave and self.modelo_voz) and time.time() > self._sin_red_hasta \
            and self._pausa.get(self.modelo_voz, 0) < time.time()

    @property
    def vision_activa(self) -> bool:
        return bool(self.clave and self.modelo_vision) and time.time() > self._sin_red_hasta \
            and self._pausa.get(self.modelo_vision, 0) < time.time()

    def estado(self) -> str:
        nex = bool(self.respaldo and self.respaldo.activo)
        if not self.groq_activo:
            if nex:
                return "nube · nex (respaldo)"
            if not self.clave:
                return "local"
            return "local (sin conexión con Groq)" if not self.modelos_chat else "local (cupo o red)"
        return "nube · " + self.modelos_chat[0].split("/")[-1] + (" + nex" if nex else "")

    # ---------- HTTP
    def _peticion(self, ruta: str, datos: bytes | None = None, cabeceras: dict | None = None, timeout: float = 15):
        req = urllib.request.Request(API + ruta, data=datos, headers={
            "Authorization": f"Bearer {self.clave}", "User-Agent": "Jarvis/1.0", **(cabeceras or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                self._ultimas_cabeceras = dict(r.headers)
                return json.load(r)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self._sin_red_hasta = time.time() + 60          # sin internet: un minuto en local antes de reintentar
            self.al_cambiar()
            raise SinConexion(str(e)) from e

    @staticmethod
    def _segundos(texto: str | None) -> float:
        """'20.15s', '1m5.2s', '585ms' (cabeceras de Groq) → segundos."""
        if not texto:
            return 0.0
        total = 0.0
        for num, unidad in re.findall(r"([\d.]+)(ms|h|m|s)", str(texto)):
            total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unidad]
        return total or (float(texto) if re.fullmatch(r"[\d.]+", str(texto)) else 0.0)

    def _anotar_cupo(self, modelo: str, cab: dict) -> None:
        cab = {k.lower(): v for k, v in (cab or {}).items()}
        try:
            quedan = int(cab.get("x-ratelimit-remaining-tokens"))
        except (TypeError, ValueError):
            return
        self._cupo[modelo] = (quedan, time.time() + self._segundos(cab.get("x-ratelimit-reset-tokens")))

    def _cabe(self, modelo: str, tokens: int) -> bool:
        quedan, renueva = self._cupo.get(modelo, (10 ** 6, 0))
        return quedan >= tokens or time.time() >= renueva

    def _pausar(self, modelo: str, e: urllib.error.HTTPError) -> None:
        cab = {k.lower(): v for k, v in dict(e.headers or {}).items()}
        espera = max(self._segundos(cab.get("retry-after")), self._segundos(cab.get("x-ratelimit-reset-tokens")))
        if not espera:
            espera = 20
        # si lo agotado es el cupo del DÍA (peticiones), la espera es larga y se respeta; si es el del minuto, corta
        espera = min(max(espera, 3), 3600)
        self._pausa[modelo] = time.time() + espera
        self.log(f"cerebro: cupo agotado en {modelo}, lo dejo descansar {round(espera)} s")
        self.al_cambiar()

    def detectar(self) -> bool:
        try:
            ids = {m["id"] for m in self._peticion("/models", timeout=10)["data"]}
        except urllib.error.HTTPError as e:
            self.log(f"cerebro: Groq rechaza la clave ({e.code})")
            return False
        except SinConexion as e:
            self.log(f"cerebro: no llego a Groq ({e}); sigo en local")
            return False
        self.modelos_chat = [m for m in PREFERENCIA_CHAT if m in ids]
        self.modelo_voz = next((m for m in PREFERENCIA_VOZ if m in ids), None)
        self.modelo_vision = next((m for m in PREFERENCIA_VISION if m in ids), None)
        self.log(f"cerebro: Groq listo · cerebro {', '.join(self.modelos_chat) or 'ninguno'} · oído {self.modelo_voz}"
                 f" · vista {self.modelo_vision or 'ninguna'}")
        self.al_cambiar()
        return bool(self.modelos_chat)

    def guardar_clave(self, clave: str) -> tuple[bool, str]:
        anterior, self.clave = self.clave, clave.strip()
        if not self.detectar():
            self.clave = anterior
            return False, "Esa clave no funciona (Groq la rechaza o no hay conexión). Revísala y vuelve a mandarla."
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"api_key": self.clave}), encoding="utf-8")
        CONFIG.chmod(0o600)
        return True, (f"Clave guardada. Ya pienso con {self.modelos_chat[0].split('/')[-1]} y escucho con "
                      f"{self.modelo_voz or 'el oído local'}. Borra tu mensaje con la clave del chat, por seguridad.")

    # ---------- oído
    def transcribir(self, audio: np.ndarray, pista: str = "") -> str:
        frontera = uuid.uuid4().hex
        campos = {"model": self.modelo_voz, "language": "es", "temperature": "0", "response_format": "json",
                  "prompt": (con_nombre("Conversación en español de España con Jarvis, un asistente personal. ")
                             + pista)[:800]}
        cuerpo = b"".join(f'--{frontera}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                          for k, v in campos.items())
        cuerpo += (f'--{frontera}\r\nContent-Disposition: form-data; name="file"; filename="frase.wav"\r\n'
                   f"Content-Type: audio/wav\r\n\r\n").encode() + a_wav(audio) + f"\r\n--{frontera}--\r\n".encode()
        try:
            r = self._peticion("/audio/transcriptions", cuerpo,
                               {"Content-Type": f"multipart/form-data; boundary={frontera}"}, timeout=12)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self._pausar(self.modelo_voz, e)
            raise SinConexion(f"HTTP {e.code}") from e
        texto = (r.get("text") or "").strip()
        return "" if ALUCINACIONES.search(texto) else texto

    # ---------- cerebro
    def chat(self, mensajes: list[dict], formato_json: bool = False, max_tokens: int = 900,
             temperatura: float = 0.3, timeout: float = 30, ligero: bool = False) -> str:
        # las instrucciones fijas de los módulos dicen «Eres Jarvis»: con el nombre que tenga el asistente
        mensajes = [dict(m, content=con_nombre(m["content"])) if m.get("role") == "system" and
                    isinstance(m.get("content"), str) else m for m in mensajes]
        try:
            return self._chat_groq(mensajes, formato_json, max_tokens, temperatura, timeout, ligero)
        except SinConexion as e:
            if not (self.respaldo and self.respaldo.activo):
                raise
            self.log(f"cerebro: Groq no puede ({e}); pienso con Nex")
            try:
                m = self.respaldo.chat(mensajes, json_=formato_json, max_tokens=max(max_tokens, 1500),
                                       timeout=max(timeout, 60))
            except Exception as e2:
                raise SinConexion(f"Groq y Nex no disponibles: {e2}") from e2
            return re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or "").strip()

    def _chat_groq(self, mensajes: list[dict], formato_json: bool, max_tokens: int, temperatura: float,
                   timeout: float, ligero: bool = False) -> str:
        if not self.clave or not self.modelos_chat or time.time() < self._sin_red_hasta:
            raise SinConexion("cerebro en la nube no disponible")
        ultimo = "sin modelos"
        estimados = sum(len(str(m.get("content", ""))) for m in mensajes) // 3 + max_tokens // 2
        orden = [m for m in (PREFERENCIA_LIGERA if ligero else PREFERENCIA_CHAT) if m in self.modelos_chat]
        libres = [m for m in orden if self._pausa.get(m, 0) < time.time()]
        candidatos = [m for m in libres if self._cabe(m, estimados)] or libres
        if not candidatos and orden:
            # todos cansados: si alguno se recupera en pocos segundos, mejor esperar que contestar mal en local
            m = min(orden, key=lambda x: self._pausa.get(x, 0))
            falta = self._pausa.get(m, 0) - time.time()
            if falta <= 20:          # la IA local de reserva contesta mucho peor: mejor unos segundos de espera
                self.log(f"cerebro: todos los modelos sin cupo; espero {falta:.0f} s a {m}")
                time.sleep(max(0.0, falta))
                candidatos = [m]
        for modelo in candidatos:
            cuerpo = {"model": modelo, "messages": mensajes, "temperature": temperatura,
                      "max_completion_tokens": max_tokens}
            if modelo.startswith("openai/gpt-oss"):
                cuerpo.update(reasoning_effort="low", include_reasoning=False)
            if formato_json:
                cuerpo["response_format"] = {"type": "json_object"}
            for _ in range(2):
                try:
                    r = self._peticion("/chat/completions", json.dumps(cuerpo).encode(),
                                       {"Content-Type": "application/json"}, timeout=timeout)
                    self._anotar_cupo(modelo, self._ultimas_cabeceras)
                    texto = (r["choices"][0]["message"].get("content") or "").strip()
                    return re.sub(r"(?s)<think>.*?</think>", "", texto).strip()
                except urllib.error.HTTPError as e:
                    detalle = e.read()[:400].decode("utf-8", "ignore")
                    if e.code == 429:
                        self._pausar(modelo, e)
                        ultimo = f"{modelo}: cupo agotado"
                        break
                    if e.code == 400 and ("response_format" in cuerpo or "include_reasoning" in cuerpo) and \
                            re.search(r"response_format|json|include_reasoning|reasoning", detalle):
                        cuerpo.pop("include_reasoning", None)           # si el modelo no admite algo, sin ello
                        if "response_format" in detalle or "json" in detalle:
                            cuerpo.pop("response_format", None)
                        continue
                    if e.code == 401:
                        raise SinConexion("clave rechazada") from e
                    ultimo = f"{modelo}: HTTP {e.code} {detalle[:120]}"
                    break
        raise SinConexion(ultimo)

    # ---------- vista
    def ver(self, imagen_url: str, sistema: str, pregunta: str, max_tokens: int = 400) -> str:
        """Pregunta sobre una imagen (data URL) al modelo con visión."""
        if not self.vision_activa:
            raise SinConexion("vista no disponible")
        cuerpo = {"model": self.modelo_vision, "temperature": 0.2, "max_completion_tokens": max_tokens,
                  "messages": [{"role": "system", "content": sistema},
                               {"role": "user", "content": [{"type": "text", "text": pregunta},
                                                            {"type": "image_url", "image_url": {"url": imagen_url}}]}]}
        try:
            r = self._peticion("/chat/completions", json.dumps(cuerpo).encode(), {"Content-Type": "application/json"},
                               timeout=45)
        except urllib.error.HTTPError as e:
            detalle = e.read()[:300].decode("utf-8", "ignore")
            if e.code == 429:
                self._pausar(self.modelo_vision, e)
            raise SinConexion(f"vista: HTTP {e.code} {detalle[:120]}") from e
        texto = (r["choices"][0]["message"].get("content") or "").strip()
        return re.sub(r"(?s)<think>.*?</think>", "", texto).strip()

    # ---------- entender una orden
    def interpretar(self, texto: str, contexto: dict, historial: list[dict]) -> dict:
        ahora = dt.datetime.now()
        tabla = ", ".join(f"{DIAS[(ahora + dt.timedelta(days=i)).weekday()]} {(ahora + dt.timedelta(days=i)):%d/%m}"
                          + (" (hoy)" if i == 0 else " (mañana)" if i == 1 else "") for i in range(15))
        sistema = (con_nombre(PROMPT) + identidad()).format(
            ahora=f"{DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]} de {ahora.year}, {ahora:%H:%M}",
            hoy=ahora.date().isoformat(), tabla=tabla, ordenes=contexto.get("ordenes", ""),
            memoria=contexto.get("memoria") or "nada", calendario=contexto.get("calendario") or "vacío",
            correo=contexto.get("correo") or "no consultado ahora (para algo del correo usa las acciones de correo)",
            canal="Telegram (escrito)" if contexto.get("telegram") else "voz (se leerá en voz alta)",
            saber=contexto.get("saber") or "nada relacionado")
        previos = [{"role": h["role"], "content": str(h.get("content", ""))[:400]} for h in historial[-8:]]
        mensajes = [{"role": "system", "content": sistema}] + previos + [{"role": "user", "content": texto}]
        bruto = self.chat(mensajes, formato_json=True, max_tokens=700, temperatura=0.2)   # el cupo por minuto cuenta lo reservado
        return leer_plan(bruto)


def identidad() -> str:
    """Cómo es el asistente según el perfil: su género y cómo trata a la persona (llaves dobladas: va a .format)."""
    p = perfil()
    partes = []
    if str(p.get("genero", "")).lower().startswith("f"):
        partes.append("Eres una asistente: habla de ti en femenino (\"estoy lista\", \"encantada\").")
    usuario = p.get("usuario") or {}
    if usuario.get("nombre"):
        partes.append(f"La persona se llama {usuario['nombre']}.")
    if usuario.get("trato"):
        partes.append(f"Trátala así: {usuario['trato']}.")
    texto = ("\n" + " ".join(partes)) if partes else ""
    return texto.replace("{", "{{").replace("}", "}}")


def leer_plan(bruto: str) -> dict:
    """El JSON del cerebro, tolerante: los modelos de reserva a veces contestan con texto normal o JSON imperfecto."""
    bruto = re.sub(r"(?s)<think>.*?</think>", "", bruto or "").strip()
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto)
    m = re.search(r"\{.*\}", bruto, re.S)
    if m:
        crudo = m.group(0)
        for intento in (crudo, re.sub(r",\s*([}\]])", r"\1", crudo),
                        re.sub(r"(?<![\\])'", '"', re.sub(r",\s*([}\]])", r"\1", crudo))):
            try:
                plan = json.loads(intento)
                break
            except ValueError:
                plan = None
        if isinstance(plan, dict):
            plan.setdefault("acciones", [])
            plan.setdefault("respuesta", "")
            if not isinstance(plan["acciones"], list):
                plan["acciones"] = [plan["acciones"]] if isinstance(plan["acciones"], dict) else []
            return plan
        if bruto.lstrip().startswith("{"):
            raise ValueError(f"JSON roto: {bruto[:120]}")
    if bruto and len(bruto) < 1500:
        return {"acciones": [], "respuesta": bruto}         # contestó en texto normal: vale como respuesta
    raise ValueError(f"respuesta vacía o rara: {bruto[:120]}")


PROMPT = """Eres el cerebro de Jarvis, el asistente personal de un usuario en España (estilo mayordomo de Iron Man: \
educado, cercano, resolutivo, con un punto de humor). Decides qué hacer con lo que dice o escribe.
Ahora: {ahora}. Hoy: {hoy}. Próximos días: {tabla}. Canal: {canal}.
Lo que sabes del usuario: {memoria}
Calendario (id|fecha|hora|texto): {calendario}
Correo (id|remitente|asunto|fecha): {correo}
Lo que has investigado o leído en sus documentos (úsalo si viene al caso y di de dónde sale): {saber}

Devuelve SOLO JSON: {{"acciones": [...], "respuesta": "..."}}. Tipos de acción (no inventes otros):
- {{"tipo":"evento","fecha":"AAAA-MM-DD","hora":"HH:MM"|null,"texto":"..."}} apuntar algo con fecha en el calendario.
- {{"tipo":"recordatorio","fecha":"AAAA-MM-DD","hora":"HH:MM","texto":"..."}} "recuérdame…" (en N minutos: calcula la \
hora; sin hora: 09:00).
- {{"tipo":"temporizador","segundos":N}}
- {{"tipo":"consultar","desde":"AAAA-MM-DD","hasta":"AAAA-MM-DD"}} "qué tengo…".
- {{"tipo":"borrar_evento","id":"..."}} borrar del calendario (id de la lista).
- {{"tipo":"dato","texto":"..."}} guardar un dato personal duradero ("recuerda que mi coche es un Seat León"). \
Si corrige o amplía algo que ya sabes, escribe el dato completo y actualizado; si deletrea, escribe la palabra junta.
- {{"tipo":"correo_lista"}} | {{"tipo":"correo_buscar","consulta":"búsqueda de Gmail, p. ej. from:amazon newer_than:7d"}} | \
{{"tipo":"correo_leer","id":"c2"}} | {{"tipo":"correo_resumir"}} | \
{{"tipo":"correo_responder","id":"c1","texto":"lo que quiere contestar"}} | \
{{"tipo":"correo_nuevo","para":"nombre o dirección tal cual","asunto":"","texto":"..."}} (nunca inventes direcciones).
- {{"tipo":"ver","fuente":"pantalla"|"monitor"|"camara"|"foto","pregunta":"..."}} mirar la pantalla del portátil \
(webs, programas y ventanas abiertas están SIEMPRE ahí), el monitor grande (solo muestra la interfaz de Jarvis: úsalo \
únicamente si lo nombra), la cámara ("¿qué tengo en la mano?", "¿cómo voy vestido?") o la foto recién mandada por \
Telegram. Para enseñar o abrir una foto/canción/vídeo/documento que ha hecho Jarvis NO es "ver": es una orden \
("enséñame la foto que has hecho", "reproduce la canción que has creado").
- {{"tipo":"orden","texto":"..."}} todo lo demás que hace el ordenador: archivos, Word, Excel, presentaciones, planos, \
PDF, escanear (no es "ver"), imágenes, vídeos, canciones, búsquedas en internet, etc. Escribe la orden en español \
claro con todos los datos, nombres de archivo tal cual, siguiendo estas formas: {ordenes}

Reglas:
1. Fechas: usa la lista de próximos días; "el jueves" es el próximo. Si día de la semana y número no coinciden, manda \
el número. Fecha pasada sin año = año que viene. No pongas hoy si dijo otro día.
2. Horas: "a las 3 y 10" de una cita es 15:10; de 1 a 7 sin "de la mañana", por la tarde.
3. Varias peticiones = varias acciones.
4. Textos cortos y bien escritos; corrige lo mal oído ("de entista" = "dentista") pero no cambies nombres propios ni \
números. Si deletrea letras ("S E R V E O"), júntalas en la palabra (Serveo) y usa esa ortografía.
5. Usa la conversación y lo que sabes del usuario para resolver referencias: "mi empresa", "mi pueblo", "ese no, el \
otro". En las órdenes escribe el nombre real (busca "Serveo mantenimiento", no "mi empresa").
6. Si falta algo imprescindible, no inventes: pregunta en "respuesta" con acciones vacías.
7. Lo que Jarvis no sabe hacer, dilo con naturalidad; no inventes acciones.
8. Con acciones, "respuesta" vacía o muy breve (Jarvis ya confirma); nunca digas que hiciste algo que no está en acciones.
9. Charla y dudas: contesta tú en "respuesta", en español de España, sin listas ni emojis, máximo tres frases por voz. \
Cálculos: hazlos tú con cuidado y da el resultado. Actualidad (noticias, precios, resultados): orden "busca en internet …".
10. "investiga / infórmate / aprende sobre X" → orden "investiga sobre X" ("a fondo" si lo pide); estar al día de un \
tema → "mantenme informado sobre X"; lo que dicen sus archivos → "qué dicen mis documentos sobre X".
11. "encarga a Nex <tarea completa>" (IA de pago que trabaja por pasos) SOLO si nombra a Nex, dice "piensa a fondo" o \
"modo agente", o la tarea encadena buscar, comparar y crear un documento o plan.
12. "dato" solo para lo que el usuario AFIRMA (no para preguntas: "¿tengo novia?" se contesta con lo que sabes) y que \
no esté ya en lo que sabes. También es dato cómo quiere que le trates o que te comportes ("llámame mi señor", "habla \
en femenino"); y aplícalo desde ese momento.
13. Si dice "apágate", "silencio", "no me molestes", "descansa" o "ya puedes hablar", es la orden "no me molestes" / \
"ya puedes hablar" (Jarvis deja de hablar por su cuenta), NO apagar el ordenador.
14. Nunca inventes citas, correos ni datos que no estén arriba.
15. YouTube, TikTok, música y vídeos de internet son órdenes: "busca en youtube X", "pon en youtube X", "busca en tiktok X", "pon tiktoks de X", "abre tiktok", "pon música de X", "pausa", "sigue", "siguiente". Para poner una canción o un vídeo conocido ("ponme Despacito") usa "pon en youtube Despacito" (si lo pide en VLC, añade "en vlc").
16. El móvil y WhatsApp son órdenes: "dónde está mi móvil", "qué avisos tengo en el móvil", "léeme los whatsapps", \
"contesta a <persona>: <texto>", "escribe a <persona> por whatsapp: <texto>", "manda un sms a <persona>: <texto>". El \
texto del mensaje, tal cual lo dice el usuario.
17. Si pide que le hagas preguntas para conocerle, hazle UNA pregunta cada vez sobre algo que aún no sepas y, cuando \
conteste, guarda la respuesta con "dato" y haz la siguiente.
"""
