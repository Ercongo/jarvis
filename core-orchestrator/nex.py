"""
Nex-N2-Pro (Nex AGI) a través de OpenRouter: el «cerebro profundo» de Jarvis.

Groq sigue siendo el cerebro de cada día (gratis y rápido). Nex se usa para lo que pide pensar y trabajar
en varios pasos, porque es un modelo hecho para agentes (herramientas, investigación, código) y lee
hasta 262.000 tokens de una vez:

  · Modo agente: "encarga a Nex que compare tres seguros de hogar y me haga un Word",
                 "piensa a fondo cómo organizo la mudanza", "usa Nex para …", "modo agente: …"
                 → planifica y usa herramientas: buscar en internet, leer webs y archivos, dar órdenes a
                   Jarvis (crear excel, mandar archivos, calendario…), crear un Word y guardar lo aprendido
                   en la memoria de Jarvis. Trabaja en segundo plano y avisa al terminar.
  · Respaldo: si Groq se queda sin cupo o falla, el cerebro de cada día pasa a Nex.
  · Investigación a fondo ("investiga a fondo sobre …") la redacta Nex, que lee más páginas.
  · Control de gasto: límite diario (por defecto 0,50 $), "cuánto llevo gastado en Nex",
    "pon el límite de Nex a 1 dólar", "desactiva Nex" / "activa Nex", "estado de Nex".

Clave: por Telegram ("sk-or-v1-…"; no va al registro) o en ~/jarvis/openrouter.json (permisos 600).
Es de pago (céntimos): hace falta saldo en https://openrouter.ai/settings/credits.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from perfil import DATOS, SECRETOS, con_nombre
from herramientas import buscar_archivos, buscar_web, leer_config, guardar_config, leer_texto, normalizar
from sistema import Respuesta, con_tildes

HOME = Path.home()
CONFIG = SECRETOS / "openrouter.json"
GASTO = DATOS / "logs" / "openrouter_gasto.json"
API = "https://openrouter.ai/api/v1"
MODELO = "nex-agi/nex-n2-pro"
# Por orden: el que pidió el usuario y, si OpenRouter no lo sirve (el 20 oct no tenía proveedores),
# su sucesor N2.5-Pro (mismo fabricante, 0,075 $/M de entrada y 0,25 $/M de salida) y el N2.5-Mini.
PREFERENCIA = ["nex-agi/nex-n2-pro", "nex-agi/nex-n2.5-pro", "nex-agi/nex-n2.5-mini"]
LIMITE_DIA = 0.50                     # dólares al día, salvo que el usuario diga otra cosa
MAX_PASOS = 12
SALIDA = HOME / "Documentos" / "Jarvis"


def usd(v: float, dec: int = 2) -> str:
    """0.5 → '0,50 dólares' (para leerlo en voz alta)."""
    return f"{v:.{dec}f}".replace(".", ",") + " dólares"


class SinNex(Exception):
    pass


def leer_clave() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# =============================================================== herramientas del agente

HERRAMIENTAS = [
    {"type": "function", "function": {
        "name": "buscar_web", "description": "Busca en internet (DuckDuckGo, España). Devuelve títulos, enlaces y resúmenes.",
        "parameters": {"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]}}},
    {"type": "function", "function": {
        "name": "leer_web", "description": "Lee el texto de una página web (hasta ~12.000 caracteres).",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "buscar_archivo", "description": "Busca archivos del usuario por nombre en su ordenador. Devuelve rutas.",
        "parameters": {"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]}}},
    {"type": "function", "function": {
        "name": "leer_archivo", "description": "Lee el texto de un archivo del usuario (pdf, word, excel, presentación, "
                                              "plano, texto). Pasa la ruta completa que dio buscar_archivo.",
        "parameters": {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": ["ruta"]}}},
    {"type": "function", "function": {
        "name": "orden_jarvis", "description": "Da una orden a Jarvis, en español, como la diría el usuario: abrir o "
                                              "crear archivos, excel, presentaciones, planos, imágenes, calendario, "
                                              "recordatorios, correo, mandar archivos al móvil, volumen, etc. Una orden "
                                              "por llamada. Devuelve lo que Jarvis contesta. Las acciones delicadas "
                                              "(borrar, enviar correos, apagar) piden confirmación al usuario.",
        "parameters": {"type": "object", "properties": {"orden": {"type": "string"}}, "required": ["orden"]}}},
    {"type": "function", "function": {
        "name": "crear_word", "description": "Crea un documento Word con el contenido que redactes (markdown ligero: "
                                            "'## apartado', '- lista', '**negrita**', tablas con '|'). Lo guarda en "
                                            "Documentos/Jarvis y devuelve la ruta.",
        "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "contenido": {"type": "string"}},
                       "required": ["titulo", "contenido"]}}},
    {"type": "function", "function": {
        "name": "guardar_en_memoria", "description": "Guarda en la memoria de Jarvis lo que has aprendido sobre un tema, "
                                                    "para que pueda responder después sin buscar otra vez.",
        "parameters": {"type": "object", "properties": {"tema": {"type": "string"}, "nota": {"type": "string"}},
                       "required": ["tema", "nota"]}}},
    {"type": "function", "function": {
        "name": "preguntar_usuario", "description": "Hace al usuario una pregunta de sí o no cuando de verdad no puedes "
                                                   "seguir sin su decisión. Devuelve 'sí' o 'no'.",
        "parameters": {"type": "object", "properties": {"pregunta": {"type": "string"}}, "required": ["pregunta"]}}},
]

SISTEMA_AGENTE = """Eres Jarvis trabajando en modo agente con el modelo Nex: el mayordomo digital del usuario \
(España, trato de tú, cercano y resolutivo). Ahora es {ahora}. Te encargan una tarea que puede necesitar varios pasos.
Planifica en silencio y usa las herramientas una a una: busca y lee fuentes antes de afirmar datos, lee los archivos \
del usuario si hacen falta, y para actuar en su ordenador usa orden_jarvis con frases como estas: {ordenes}.
Reglas: no inventes datos ni archivos; si algo falla, prueba otra vía; no repitas la misma llamada; no borres ni \
envíes nada que no te hayan pedido. Si el resultado es largo (informe, comparativa, plan), créalo con crear_word. \
Si aprendes algo útil para el futuro, guárdalo con guardar_en_memoria. Cuando termines, responde SOLO con el resumen \
final para el usuario en español de España: {formato}."""


# =============================================================== el módulo

class Nex:
    def __init__(self, log=print, ui=None, decir: Callable[..., None] | None = None,
                 avisar: Callable[[str], None] | None = None, es_telegram: Callable[[], bool] | None = None,
                 preguntar: Callable[[str], bool] | None = None, enviar_documento=None):
        self.log = log
        self.ui = ui
        self.decir = decir or (lambda t, **k: None)
        self.avisar = avisar or (lambda t: None)
        self.es_telegram = es_telegram or (lambda: False)
        self.preguntar = preguntar or (lambda p: False)
        self.enviar_documento = enviar_documento or (lambda r, p: False)
        self.ejecutar_orden: Callable[[str, bool], str] | None = None     # lo pone Jarvis
        self.ordenes = ""                                                   # ORDENES_CONOCIDAS de Jarvis
        cfg = leer_clave()
        self.clave = str(cfg.get("api_key", "")).strip()
        self.forzado = str(cfg.get("modelo_forzado") or "")      # si el usuario quiere uno concreto
        self.modelo = self.forzado or MODELO
        self._comprobado = 0.0
        self.disponible = False
        self.motivo = "sin clave" if not self.clave else "comprobando"
        self._pausa_hasta = 0.0
        self._lock = threading.Lock()
        self._trabajando = 0
        if self.clave:
            threading.Thread(target=self.detectar, daemon=True).start()

    # ---------- estado y gasto
    @staticmethod
    def limite() -> float:
        try:
            return float(leer_config().get("nex_limite_dia", LIMITE_DIA))
        except (TypeError, ValueError):
            return LIMITE_DIA

    @staticmethod
    def gasto_hoy() -> float:
        try:
            g = json.loads(GASTO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0.0
        return float(g.get(dt.date.today().isoformat(), {}).get("usd", 0.0))

    def _anotar(self, uso: dict) -> None:
        coste = float(uso.get("cost") or 0.0)
        with self._lock:
            try:
                g = json.loads(GASTO.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                g = {}
            dia = g.setdefault(dt.date.today().isoformat(), {"usd": 0.0, "peticiones": 0, "tokens": 0})
            dia["usd"] = round(dia["usd"] + coste, 6)
            dia["peticiones"] += 1
            dia["tokens"] += int(uso.get("total_tokens") or 0)
            g = dict(sorted(g.items())[-60:])                  # dos meses de historial
            GASTO.parent.mkdir(parents=True, exist_ok=True)
            GASTO.write_text(json.dumps(g, indent=1), encoding="utf-8")

    @property
    def activo(self) -> bool:
        if self.clave and not self.disponible and time.time() - self._comprobado > 3600:
            self._comprobado = time.time()                     # cada hora vuelve a mirar si hay proveedor
            threading.Thread(target=self.detectar, daemon=True).start()
        return bool(self.clave and self.disponible and time.time() > self._pausa_hasta
                    and leer_config().get("nex_activo", True) and self.gasto_hoy() < self.limite())

    def estado(self) -> str:
        if not self.clave:
            return "sin clave"
        if not leer_config().get("nex_activo", True):
            return "desactivado"
        if self.gasto_hoy() >= self.limite():
            return "límite del día"
        return "listo" if self.activo else self.motivo

    # ---------- HTTP
    def _peticion(self, ruta: str, cuerpo: dict | None = None, timeout: float = 20) -> dict:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(API + ruta, data=datos, headers={
            "Authorization": f"Bearer {self.clave}", "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Ercongo/jarvis", "X-Title": "Jarvis"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def detectar(self) -> bool:
        self._comprobado = time.time()
        try:
            k = self._peticion("/key").get("data", {})
        except urllib.error.HTTPError as e:
            self.disponible, self.motivo = False, f"clave rechazada ({e.code})"
            self.log(f"nex: OpenRouter rechaza la clave ({e.code})")
            return False
        except (urllib.error.URLError, OSError) as e:
            self.disponible, self.motivo = False, "sin conexión"
            self.log(f"nex: no llego a OpenRouter ({e})")
            return False
        proveedores = []
        for modelo in ([self.forzado] if self.forzado else PREFERENCIA):
            try:
                ep = self._peticion(f"/models/{modelo}/endpoints").get("data", {}) or {}
                proveedores = [e.get("provider_name") or e.get("name") for e in ep.get("endpoints") or []]
            except Exception as e:
                proveedores = []
                self.log(f"nex: no puedo consultar {modelo} ({e!r})")
            if proveedores:
                if modelo != self.modelo:
                    self.log(f"nex: {self.modelo} no está disponible en OpenRouter; uso {modelo}")
                self.modelo = modelo
                break
        self.disponible = bool(proveedores)
        self.motivo = "listo" if proveedores else "el modelo no tiene proveedores ahora"
        resto = k.get("limit_remaining")
        self.log(f"nex: {self.modelo} · proveedores {', '.join(map(str, proveedores)) or 'ninguno'} · "
                 f"saldo de la clave {'sin límite' if resto is None else f'{resto:.2f} $'}")
        return self.disponible

    def guardar_clave(self, clave: str) -> tuple[bool, str]:
        anterior, self.clave = self.clave, clave.strip()
        ok = self.detectar()
        if not ok and self.motivo.startswith("clave rechazada"):
            self.clave = anterior
            return False, "OpenRouter rechaza esa clave. Revísala y vuelve a mandarla."
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"api_key": self.clave, "modelo_forzado": self.forzado}), encoding="utf-8")
        CONFIG.chmod(0o600)
        if not ok:
            return True, (f"Clave de OpenRouter guardada, pero ahora mismo {self.motivo}. Lo vuelvo a intentar más "
                          f"tarde. Borra tu mensaje con la clave, por seguridad.")
        return True, (f"Clave de OpenRouter guardada: ya puedo trabajar con Nex ({self.modelo.split('/')[-1]}). Gasto máximo {usd(self.limite())} "
                      f"al día. Borra tu mensaje con la clave, por seguridad.")

    # ---------- conversación
    def chat(self, mensajes: list[dict], herramientas: list | None = None, json_: bool = False,
             max_tokens: int = 2000, esfuerzo: str = "low", timeout: float = 120) -> dict:
        if not self.activo:
            raise SinNex(self.estado())
        cuerpo = {"model": self.modelo, "messages": mensajes, "max_tokens": max_tokens, "temperature": 0.3,
                  "reasoning": {"effort": esfuerzo, "exclude": True}, "usage": {"include": True}}
        if herramientas:
            cuerpo.update(tools=herramientas, tool_choice="auto")
        if json_:
            cuerpo["response_format"] = {"type": "json_object"}
        for intento in range(2):
            try:
                r = self._peticion("/chat/completions", cuerpo, timeout=timeout)
                break
            except urllib.error.HTTPError as e:
                detalle = e.read()[:300].decode("utf-8", "ignore")
                if e.code == 400 and "response_format" in cuerpo and intento == 0:
                    cuerpo.pop("response_format")                 # si no admite JSON estricto, sin él
                    continue
                if e.code == 402:
                    self._pausa_hasta = time.time() + 1800
                    self.motivo = "sin saldo en OpenRouter"
                    raise SinNex("no queda saldo en OpenRouter") from e
                if e.code in (429, 502, 503):
                    self._pausa_hasta = time.time() + 60
                    self.motivo = "ocupado"
                if e.code == 404:
                    self.disponible, self.motivo = False, "modelo no disponible"
                raise SinNex(f"HTTP {e.code} {detalle[:120]}") from e
            except (urllib.error.URLError, OSError) as e:
                self._pausa_hasta = time.time() + 60
                raise SinNex(f"sin conexión ({e})") from e
        if r.get("error"):
            raise SinNex(str(r["error"])[:150])
        self._anotar(r.get("usage") or {})
        return r["choices"][0]["message"]

    def texto(self, sistema: str, usuario: str, max_tokens: int = 2000, json_: bool = False,
              esfuerzo: str = "low", timeout: float = 120) -> str:
        m = self.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                      json_=json_, max_tokens=max_tokens, esfuerzo=esfuerzo, timeout=timeout)
        return re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or "").strip()

    # ---------- agente
    def _herramienta(self, nombre: str, args: dict, tg: bool) -> str:
        if nombre == "buscar_web":
            res = buscar_web(str(args.get("consulta", "")), 6)
            return "\n".join(f"- {r['titulo']} | {r['url']}\n  {r['texto']}" for r in res) or "sin resultados"
        if nombre == "leer_web":
            from saber import leer_pagina
            return leer_pagina(str(args.get("url", "")), limite=12000) or "página vacía o no legible"
        if nombre == "buscar_archivo":
            rutas = buscar_archivos(str(args.get("nombre", "")), maximo=10)
            return "\n".join(str(r) for r in rutas) or "no encuentro archivos con ese nombre"
        if nombre == "leer_archivo":
            ruta = Path(str(args.get("ruta", ""))).expanduser()
            if not ruta.is_file() or not str(ruta.resolve()).startswith(str(HOME)):
                return "no existe ese archivo dentro de la carpeta del usuario"
            return leer_texto(ruta, limite=30000) or "no he podido sacar texto"
        if nombre == "orden_jarvis":
            if not self.ejecutar_orden:
                return "no puedo dar órdenes ahora"
            return self.ejecutar_orden(str(args.get("orden", "")), tg) or "hecho"
        if nombre == "crear_word":
            from archivos import crear_docx
            titulo = str(args.get("titulo") or "Informe").strip()[:80]
            SALIDA.mkdir(parents=True, exist_ok=True)
            nombre_f = re.sub(r"[^\w\s\-áéíóúñÁÉÍÓÚÑ]", "", titulo).strip() or "Informe"
            ruta = SALIDA / f"{nombre_f}.docx"
            n = 2
            while ruta.exists():
                ruta = SALIDA / f"{nombre_f} ({n}).docx"
                n += 1
            crear_docx(ruta, titulo, str(args.get("contenido", "")))
            self._archivos.append(ruta)
            return f"creado {ruta}"
        if nombre == "guardar_en_memoria":
            from saber import NOTAS, slug
            tema = str(args.get("tema") or "Nota").strip()[:80]
            NOTAS.mkdir(parents=True, exist_ok=True)
            ruta = NOTAS / f"{slug(tema)}.md"
            previo = ruta.read_text(encoding="utf-8") if ruta.exists() else f"# {tema}\n"
            hoy = dt.date.today()
            ruta.write_text(previo + f"\n\n_Aprendido con Nex el {hoy.day}/{hoy.month}/{hoy.year}_\n\n"
                            + str(args.get("nota", "")).strip() + "\n", encoding="utf-8")
            return "guardado en la memoria"
        if nombre == "preguntar_usuario":
            return "sí" if self.preguntar(str(args.get("pregunta", ""))) else "no"
        return f"herramienta desconocida: {nombre}"

    def agente(self, tarea: str, tg: bool = False) -> tuple[str, list[Path]]:
        ahora = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        formato = ("puede ser detallado y con viñetas, para leer en el móvil" if tg else
                   "máximo cuatro frases, sin listas ni símbolos, porque se lee en voz alta")
        mensajes = [{"role": "system", "content": con_nombre(SISTEMA_AGENTE).format(ahora=ahora, ordenes=self.ordenes[:2500],
                                                                         formato=formato)},
                    {"role": "user", "content": tarea}]
        self._archivos: list[Path] = []
        final = ""
        for paso in range(MAX_PASOS):
            m = self.chat(mensajes, herramientas=HERRAMIENTAS, esfuerzo="medium", max_tokens=4000, timeout=180)
            llamadas = m.get("tool_calls") or []
            texto = re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or "").strip()
            if not llamadas:
                final = texto
                break
            mensajes.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": llamadas})
            for c in llamadas:
                nombre = c.get("function", {}).get("name", "")
                try:
                    args = json.loads(c.get("function", {}).get("arguments") or "{}")
                except ValueError:
                    args = {}
                resumen = re.sub(r"\s+", " ", ", ".join(f"{v}" for v in args.values()))[:70]
                self._actividad(f"Nex · {nombre.replace('_', ' ')}: {resumen}")
                self.log(f"nex: paso {paso + 1} {nombre} {json.dumps(args, ensure_ascii=False)[:160]}")
                try:
                    resultado = self._herramienta(nombre, args, tg)
                except Exception as e:
                    resultado = f"error: {type(e).__name__}: {e}"
                mensajes.append({"role": "tool", "tool_call_id": c.get("id", nombre), "content": str(resultado)[:12000]})
        else:
            mensajes.append({"role": "user", "content": "Se acabaron los pasos: resume ya lo que hayas conseguido."})
            final = self.texto_de(mensajes)
        return final or "He terminado, pero no me ha quedado nada que contarte.", self._archivos

    def texto_de(self, mensajes: list[dict]) -> str:
        try:
            return (self.chat(mensajes, max_tokens=1200).get("content") or "").strip()
        except SinNex:
            return ""

    def _actividad(self, texto: str) -> None:
        if self.ui:
            self.ui.enviar(tipo="actividad", texto=texto)

    def encargar(self, tarea: str) -> Respuesta:
        if not self.clave:
            return Respuesta("Para usar Nex necesito una clave de OpenRouter. Créala en openrouter.ai, añade unos "
                             "dólares de saldo y mándamela por Telegram.")
        if not self.activo:
            return Respuesta(f"Ahora mismo no puedo usar Nex: {self.estado()}.")
        if self._trabajando >= 2:
            return Respuesta("Nex ya tiene dos encargos en marcha. Espera a que termine alguno.")
        tg = self.es_telegram()

        def hilo():
            self._trabajando += 1
            t0 = time.time()
            gasto0 = self.gasto_hoy()
            try:
                texto, archivos = self.agente(tarea, tg)
            except SinNex as e:
                texto, archivos = f"Nex no ha podido terminar: {e}.", []
            except Exception as e:
                self.log(f"nex: error {e!r}")
                texto, archivos = f"Nex ha fallado ({type(e).__name__}). Prueba otra vez.", []
            finally:
                self._trabajando -= 1
            coste = self.gasto_hoy() - gasto0
            self.log(f"nex: encargo terminado en {time.time() - t0:.0f} s, {coste:.4f} $")
            if tg:
                self.avisar(texto + (f"\n\n(Nex · {time.time() - t0:.0f} s · {coste:.3f} $)"))
                for a in archivos:
                    self.enviar_documento(str(a), a.name)
            else:
                self.decir(texto)
                if archivos:
                    try:
                        import subprocess
                        subprocess.Popen(["xdg-open", str(archivos[-1])], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
                    except OSError:
                        pass
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta("Se lo encargo a Nex. Trabajará en varios pasos; te aviso al terminar.")

    # ---------- entrada
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)

        if re.search(r"\b(cuanto|que) (llevo gastado|he gastado|gasto|has gastado)\b.*\b(nex|openrouter)\b", t) or \
                re.search(r"\b(gasto|consumo) de (nex|openrouter)\b", t):
            try:
                g = json.loads(GASTO.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                g = {}
            hoy = g.get(dt.date.today().isoformat(), {"usd": 0, "peticiones": 0})
            mes = sum(v["usd"] for k, v in g.items() if k.startswith(dt.date.today().strftime("%Y-%m")))
            return Respuesta(f"Hoy Nex lleva {hoy['peticiones']} peticiones y {usd(hoy['usd'], 3)}; este mes, "
                             f"{usd(mes)}. El límite diario es {usd(self.limite())}.")
        m = re.search(r"\b(?:pon|cambia|sube|baja) el limite de (?:nex|openrouter) a (\d+(?:[.,]\d+)?)", t)
        if m:
            v = float(m.group(1).replace(",", "."))
            guardar_config(nex_limite_dia=v)
            return Respuesta(f"Hecho: Nex podrá gastar como mucho {usd(v)} al día.")
        if re.match(r"^(desactiva|apaga|no uses) (a )?nex\b", t):
            guardar_config(nex_activo=False)
            return Respuesta("Nex desactivado. Sigo solo con Groq y lo local.")
        if re.match(r"^(activa|enciende|usa) (a )?nex$", t):
            guardar_config(nex_activo=True)
            threading.Thread(target=self.detectar, daemon=True).start()
            return Respuesta("Nex activado." if self.clave else "Lo activo, pero falta la clave de OpenRouter.")
        if re.search(r"\b(estado|como esta|funciona) (de )?nex\b", t):
            return Respuesta(f"Nex ({self.modelo}): {self.estado()}. Hoy lleva {usd(self.gasto_hoy(), 3)} de "
                             f"{usd(self.limite())}.")

        m = re.match(r"^(?:encarga(?:le)? a nex(?: que)?|encargale a nex(?: que)?|usa nex para|usa a nex para|"
                     r"pidele a nex(?: que)?|preguntale a nex|nex[,:]|modo agente[,:]?|piensa a fondo(?: sobre| en| como)?|"
                     r"pensando a fondo[,:]?)\s+(.+)$", t)
        if m:
            tarea = con_tildes(peticion, m.group(1)) or m.group(1)
            return self.encargar(tarea)
        return None
