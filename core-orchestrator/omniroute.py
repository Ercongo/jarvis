"""OmniRoute: puerta de enlace de IA en el propio equipo (http://127.0.0.1:20128/v1, compatible con OpenAI).

Reparte las peticiones entre los proveedores que tenga conectados (Groq, Gemini, Cerebras, OpenRouter, Mistral,
NVIDIA, Hugging Face…) y, cuando uno agota su cupo, pasa al siguiente. Para el asistente es el segundo cerebro:
si Groq (el de siempre) se queda sin cupo por minuto, se piensa con OmniRoute antes de caer en la IA local.

- Lo instala `instalar_omniroute.sh` como servicio del usuario (systemd --user), solo escuchando en 127.0.0.1,
  con clave obligatoria y la memoria limitada. Su clave y su contraseña van en SECRETOS/omniroute.json (600).
- Órdenes: «estado de OmniRoute», «qué proveedores tiene OmniRoute», «prueba OmniRoute», «usa OmniRoute para
  pensar» / «usa Groq para pensar», «arranca / para OmniRoute», «conecta Gemini a OmniRoute» (explica cómo).
- Las claves de proveedores llegan por Telegram («clave de gemini AIza…») y no se escriben en el registro.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from herramientas import guardar_config, leer_config, normalizar
from perfil import SECRETOS
from sistema import Respuesta

CONFIG = SECRETOS / "omniroute.json"
URL_DEFECTO = "http://127.0.0.1:20128/v1"
SERVICIO = "omniroute.service"

# proveedores con plan gratuito que merece la pena conectar (id de OmniRoute → nombre, web para sacar la clave,
# forma de la clave). Solo los que se reconocen sin dudar en un mensaje.
PROVEEDORES = {
    "groq": ("Groq", "https://console.groq.com/keys", r"gsk_[A-Za-z0-9]{20,}"),
    "gemini": ("Google Gemini", "https://aistudio.google.com/apikey", r"AIza[0-9A-Za-z_\-]{30,}|AQ\.[0-9A-Za-z_\-]{30,}"),
    "cerebras": ("Cerebras", "https://cloud.cerebras.ai", r"csk-[A-Za-z0-9]{20,}"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/keys", r"sk-or-v1-[A-Za-z0-9]{20,}"),
    "mistral": ("Mistral", "https://console.mistral.ai/api-keys", r"[A-Za-z0-9]{32}"),
    "nvidia": ("NVIDIA NIM", "https://build.nvidia.com", r"nvapi-[A-Za-z0-9_\-]{20,}"),
    "huggingface": ("Hugging Face", "https://huggingface.co/settings/tokens", r"hf_[A-Za-z0-9]{20,}"),
    "sambanova": ("SambaNova", "https://cloud.sambanova.ai/apis", r"[A-Za-z0-9\-]{30,}"),
    "cohere": ("Cohere", "https://dashboard.cohere.com/api-keys", r"[A-Za-z0-9]{40}"),
}
ALIAS_PROVEEDOR = {"google": "gemini", "gemini": "gemini", "groq": "groq", "cerebras": "cerebras",
                   "openrouter": "openrouter", "open router": "openrouter", "mistral": "mistral",
                   "nvidia": "nvidia", "nim": "nvidia", "hugging face": "huggingface", "huggingface": "huggingface",
                   "sambanova": "sambanova", "samba nova": "sambanova", "cohere": "cohere"}


# prefijo de sus modelos en OmniRoute (el «alias» del catálogo) y, por preferencia, los modelos que mejor van para
# entender órdenes en español; si ninguno está, se usan los dos primeros que ofrezca
ALIAS_MODELOS = {"groq": "groq", "gemini": "gemini", "cerebras": "cerebras", "openrouter": "openrouter",
                 "mistral": "mistral", "nvidia": "nvidia", "huggingface": "hf", "sambanova": "samba",
                 "cohere": "cohere"}
PREFERIDOS = {
    "groq": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b"],
    "cerebras": ["gpt-oss-120b", "llama-3.3-70b", "qwen-3-235b"],
    "gemini": ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"],
    "openrouter": ["gpt-oss-120b:free", "deepseek-chat-v3.1:free", "llama-3.3-70b-instruct:free"],
    "mistral": ["mistral-small-latest", "mistral-medium-latest"],
    "nvidia": ["gpt-oss-120b", "llama-3.3-70b-instruct"],
    "sambanova": ["gpt-oss-120b", "Llama-3.3-70B"],
    "huggingface": ["gpt-oss-120b", "Llama-3.3-70B"],
    "cohere": ["command-a", "command-r-plus"],
}
# sin cuenta: el chat de IA de DuckDuckGo (probado el 23 oct 2026; uso no oficial de su web, puede dejar de ir)
SIN_CUENTA = ["ddgw/tinfoil/gpt-oss-120b", "ddgw/gpt-5.4-mini", "ddgw/mistral-small-2603"]
COMBO = "asistente"


class SinOmni(Exception):
    pass


def leer() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _node_y_cli() -> tuple[str, str] | None:
    """El node y el omniroute.mjs instalados (en ~/.local/node o en /opt/omniroute del disco portátil)."""
    for base in (Path.home() / ".local" / "node", Path("/opt/omniroute")):
        node = base / "bin" / "node"
        cli = base / "lib" / "node_modules" / "omniroute" / "bin" / "omniroute.mjs"
        if node.exists() and cli.exists():
            return str(node), str(cli)
    return None


class OmniRoute:
    def __init__(self, log: Callable[[str], None] = print, es_telegram: Callable[[], bool] | None = None):
        self.log = log
        self.es_telegram = es_telegram or (lambda: False)
        self._vivo = (0.0, False)                 # (cuándo se comprobó, si responde)
        self._pausa = 0.0                          # tras un fallo, no se insiste durante un rato
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ estado
    @property
    def configurado(self) -> bool:
        c = leer()
        return bool(c.get("clave"))

    @property
    def preferido(self) -> bool:
        """«usa OmniRoute para pensar»: va antes que Groq."""
        return bool(leer_config().get("omniroute_primero"))

    @property
    def activo(self) -> bool:
        if not self.configurado or time.time() < self._pausa:
            return False
        t, ok = self._vivo
        if time.time() - t > 60:
            ok = self._comprobar()
        return ok

    def _comprobar(self) -> bool:
        try:
            self._peticion("/models", timeout=4)
            ok = True
        except (urllib.error.URLError, OSError, ValueError):
            ok = False
        self._vivo = (time.time(), ok)
        return ok

    def _peticion(self, ruta: str, cuerpo: dict | None = None, timeout: float = 60) -> dict:
        c = leer()
        url = (c.get("url") or URL_DEFECTO).rstrip("/") + ruta
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(url, datos, {"Authorization": f"Bearer {c.get('clave', '')}",
                                                  "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    # ------------------------------------------------------------------ pensar
    def chat(self, mensajes: list[dict], formato_json: bool = False, max_tokens: int = 900,
             temperatura: float = 0.3, timeout: float = 60) -> str:
        """Respuesta de OmniRoute (modelo «auto» o el elegido). Lanza SinOmni si no puede."""
        if not self.configurado:
            raise SinOmni("OmniRoute no está instalado")
        cuerpo = {"model": leer().get("modelo") or COMBO, "messages": mensajes, "temperature": temperatura,
                  "max_tokens": max_tokens, "stream": False,
                  "reasoning_effort": "low"}       # gpt-oss razona antes de contestar: poco, para no gastar el margen
        # sin «response_format»: DuckDuckGo devuelve vacío con él; las instrucciones ya piden JSON y el cerebro
        # lo lee aunque venga con algo alrededor
        for intento in range(2):
            try:
                r = self._peticion("/chat/completions", cuerpo, timeout=timeout)
                texto = (r["choices"][0]["message"].get("content") or "").strip()
                self._vivo = (time.time(), True)
                self.ultimo_modelo = r.get("model") or cuerpo["model"]
                return re.sub(r"(?s)<think>.*?</think>", "", texto).strip()
            except urllib.error.HTTPError as e:
                detalle = e.read()[:300].decode("utf-8", "ignore")
                if e.code == 502 and "empty content" in detalle and intento == 0:
                    time.sleep(1.5)                            # DuckDuckGo a veces contesta vacío: otra vez
                    continue
                if e.code in (401, 403):
                    raise SinOmni("OmniRoute rechaza la clave") from e
                self._pausa = time.time() + 30
                raise SinOmni(f"OmniRoute: HTTP {e.code} {detalle[:160]}") from e
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
                self._vivo = (time.time(), False)
                self._pausa = time.time() + 30
                raise SinOmni(f"OmniRoute no responde ({e})") from e
        raise SinOmni("OmniRoute no ha contestado")

    # ------------------------------------------------------------------ la consola de OmniRoute
    def _cli(self, *args: str, entrada: str | None = None, timeout: float = 60) -> subprocess.CompletedProcess | None:
        nc = _node_y_cli()
        if not nc:
            return None
        c = leer()
        entorno = {**os.environ, "OMNIROUTE_API_KEY": c.get("clave", ""),
                   "OMNIROUTE_BASE_URL": (c.get("url") or URL_DEFECTO).removesuffix("/v1"),
                   "DATA_DIR": c.get("datos") or str(Path.home() / ".local" / "share" / "omniroute"),
                   "PATH": str(Path(nc[0]).parent) + ":" + os.environ.get("PATH", "")}
        try:
            return subprocess.run([nc[0], nc[1], *args], input=entrada, capture_output=True, text=True,
                                  timeout=timeout, env=entorno)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def proveedores(self) -> list[dict]:
        r = self._cli("providers", "list", "--json")
        if not r or r.returncode != 0:
            return []
        m = re.search(r"\{.*\}", r.stdout, re.S)
        try:
            return (json.loads(m.group(0)) if m else {}).get("providers") or []
        except ValueError:
            return []

    def anadir(self, proveedor: str, clave: str, rehacer: bool = True) -> tuple[bool, str]:
        """Conecta un proveedor con su clave (por la entrada estándar: no sale en la lista de procesos)."""
        if not self.activo:
            return False, "OmniRoute no está en marcha."
        nombre = PROVEEDORES.get(proveedor, (proveedor,))[0]
        ya = [p for p in self.proveedores() if p.get("provider") == proveedor]
        for p in ya:                                            # si ya estaba, se sustituye la clave
            self._cli("providers", "remove", p.get("id", ""), "--yes")
        r = self._cli("providers", "add", proveedor, "--credential-stdin", "--name", nombre, entrada=clave)
        if not r:
            return False, "No encuentro OmniRoute instalado."
        salida = (r.stdout + r.stderr).replace(clave, "…")
        if r.returncode != 0 or "✖" in salida:
            return False, re.sub(r"\x1b\[[0-9;]*m", "", salida).strip().splitlines()[-1][:200]
        estado = next((p for p in self.proveedores() if p.get("provider") == proveedor), {})
        if estado.get("testStatus") == "error":
            self._cli("providers", "remove", estado.get("id", ""), "--yes")     # no dejar una conexión rota
            return False, f"{nombre} rechaza esa clave ({estado.get('lastError') or 'error'})."
        if rehacer:
            self.rehacer_combo()
        return True, f"{nombre} conectado a OmniRoute."

    def rehacer_combo(self) -> list[str]:
        """La combinación «asistente»: primero los proveedores conectados (con sus mejores modelos) y al final los
        que no necesitan cuenta. Se rehace cada vez que se conecta uno."""
        try:
            ids = [m["id"] for m in self._peticion("/models", timeout=15).get("data", [])]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return []
        conectados = [p.get("provider") for p in self.proveedores() if p.get("testStatus") != "error"]
        modelos: list[str] = []
        for prov in [p for p in PROVEEDORES if p in conectados]:
            pref = ALIAS_MODELOS.get(prov, prov) + "/"
            suyos = [i for i in ids if i.startswith(pref)]
            elegidos = [i for nombre in PREFERIDOS.get(prov, []) for i in suyos if i.endswith(nombre)][:2]
            if not elegidos:                                   # aún sin catálogo de modelos: el nombre de siempre
                elegidos = [pref + n for n in PREFERIDOS.get(prov, [])[:1]] if not suyos else suyos[:2]
            modelos += [m for m in dict.fromkeys(elegidos) if m not in modelos]
        modelos += [m for m in SIN_CUENTA if m in ids or not ids]
        self._cli("combo", "delete", COMBO, "--yes")
        r = self._cli("combo", "create", COMBO, "--strategy", "priority", "--models", ",".join(modelos))
        if r and r.returncode == 0:
            self.log(f"omniroute: combinación «{COMBO}»: {', '.join(modelos)}")
        return modelos

    def sincronizar_claves(self) -> None:
        """Las claves que el asistente ya tiene (Groq, Hugging Face, OpenRouter) también en OmniRoute."""
        if not self.activo:
            return
        tiene = {p.get("provider") for p in self.proveedores()}
        claves = {}
        for archivo, campo, prov in (("groq.json", "api_key", "groq"), ("estudio.json", "hf", "huggingface"),
                                     ("openrouter.json", "api_key", "openrouter")):
            try:
                valor = json.loads((SECRETOS / archivo).read_text(encoding="utf-8")).get(campo)
            except (OSError, ValueError):
                valor = None
            if valor and prov not in tiene:
                claves[prov] = valor
        for prov, valor in claves.items():
            ok, texto = self.anadir(prov, valor, rehacer=False)
            self.log(f"omniroute: {texto}")
        if claves or not self._combo_existe():
            self.rehacer_combo()

    def _combo_existe(self) -> bool:
        r = self._cli("combo", "list", "--json")
        return bool(r and f'"name": "{COMBO}"' in r.stdout)

    def servicio(self, accion: str) -> bool:
        if not shutil.which("systemctl"):
            return False
        r = subprocess.run(["systemctl", "--user", accion, SERVICIO], capture_output=True, timeout=30)
        self._vivo = (0.0, False)
        return r.returncode == 0

    # ------------------------------------------------------------------ órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        if re.search(r"\busa (a )?groq\b|\bpiensa con groq\b", t) and self.configurado:
            guardar_config(omniroute_primero=False)
            return Respuesta("Hecho: pienso primero con Groq y OmniRoute queda de reserva.")
        if not re.search(r"\bomni ?rout|\bomni ?ruta?\b|\bomniru\w*", t) or re.search(r"\bactualiz", t):
            return None                     # «actualiza OmniRoute» lo lleva actualizar.py
        if not self.configurado:
            return Respuesta("OmniRoute no está instalado todavía. En el portátil se instala con: bash "
                             "~/jarvis/instalar_omniroute.sh (unos 2 GB). Luego te reparto el trabajo entre "
                             "varias IA gratuitas.")
        if re.search(r"\busa\b.*\b(para pensar|primero|como cerebro|siempre)|\bpiensa con\b", t):
            guardar_config(omniroute_primero=True)
            return Respuesta("Hecho: pienso primero con OmniRoute y, si falla, con Groq.")
        if re.search(r"^(para|paralo)\b|\b(parar|deten\w*|apaga\w*|desactiva\w*)\b", t):
            ok = self.servicio("stop")
            return Respuesta("OmniRoute parado: vuelvo a pensar solo con Groq." if ok else
                             "No he podido pararlo.")
        if re.search(r"\b(arranca|enciende|inicia|activa|reinicia)\w*\b", t):
            ok = self.servicio("restart")
            return Respuesta("Arrancando OmniRoute; en unos segundos está listo." if ok else
                             "No he podido arrancarlo. Mira: systemctl --user status omniroute")
        if re.search(r"\b(conecta|anade|agrega|mete)\b", t):
            nombre = next((v for k, v in ALIAS_PROVEEDOR.items() if re.search(rf"\b{k}\b", t)), None)
            if nombre:
                n, web, _ = PROVEEDORES[nombre]
                return Respuesta(f"Para conectar {n}: saca una clave gratis en {web} y mándamela por Telegram "
                                 f"así: clave de {nombre} y la clave. La guardo cifrada en OmniRoute y no la "
                                 "escribo en ningún registro.")
            return Respuesta("Puedo conectar a OmniRoute: " + ", ".join(v[0] for v in PROVEEDORES.values()) +
                             ". Mándame por Telegram: clave de gemini y la clave (o del que quieras).")
        if re.search(r"\b(prueba|test|comprueba)\b", t):
            t0 = time.time()
            try:
                texto = self.chat([{"role": "user", "content": "Responde solo: funciono"}], max_tokens=300,
                                  timeout=40)
            except SinOmni as e:
                return Respuesta(f"OmniRoute no ha contestado: {e}")
            return Respuesta(f"OmniRoute contesta en {time.time() - t0:.1f} segundos con "
                             f"{getattr(self, 'ultimo_modelo', 'auto')}: «{texto[:60]}».")
        # estado / proveedores
        vivo = self.activo
        provs = self.proveedores() if vivo else []
        activos = [p for p in provs if p.get("isActive") or p.get("testStatus") in ("ok", "success", "active")]
        nombres = ", ".join(sorted({PROVEEDORES.get(p.get("provider"), (p.get("name") or p.get("provider"),))[0]
                                    for p in (activos or provs)}) + ["DuckDuckGo (sin cuenta)"])
        if not vivo:
            return Respuesta("OmniRoute está instalado pero no responde. Dime «arranca OmniRoute».")
        orden = "antes que Groq" if self.preferido else "cuando Groq se queda sin cupo"
        faltan = [v[0] for k, v in PROVEEDORES.items() if k not in {p.get('provider') for p in provs}][:3]
        return Respuesta(f"OmniRoute está en marcha y lo uso {orden}. Proveedores conectados: {nombres}." +
                         (f" Para tener más cupo gratis puedes conectar {', '.join(faltan)}." if faltan else ""))

    def recibir_clave(self, texto: str) -> str | None:
        """Por Telegram: «clave de gemini AIza…». Devuelve la respuesta, o None si no es una clave para OmniRoute.
        La clave no se escribe en el registro."""
        m = re.match(r"(?is)\s*(?:clave|key|token)\s+(?:de|del|para)\s+([a-z ]{3,20}?)\s*[:=]?\s+(\S{16,})\s*$",
                     texto)
        if not m:
            # también vale pegar el ejemplo de Google AI Studio (curl … generativelanguage … X-goog-api-key: …)
            mm = re.search(r"generativelanguage\.googleapis\.com", texto or "") and \
                re.search(r"(AIza[0-9A-Za-z_\-]{30,}|AQ\.[0-9A-Za-z_\-]{30,})", texto)
            if not mm:
                return None
            m = re.match(r"(.*)", "gemini")
            nombre, clave_pegada = "gemini", mm.group(1)
        else:
            clave_pegada = None
        nombre = "gemini" if clave_pegada else ALIAS_PROVEEDOR.get(normalizar(m.group(1)).strip())
        if not nombre or nombre in ("groq", "openrouter", "huggingface"):
            return None                     # esas ya tienen su propio camino (y luego se sincronizan aquí)
        clave = clave_pegada or m.group(2).strip()
        if not re.fullmatch(PROVEEDORES[nombre][2], clave):
            return f"Eso no parece una clave de {PROVEEDORES[nombre][0]}. Cópiala entera."
        self.log(f"omniroute: recibida una clave de {nombre} (no se guarda en el registro)")
        ok, aviso = self.anadir(nombre, clave)
        return (aviso + " Borra ese mensaje del chat, por seguridad.") if ok else f"No la he podido conectar: {aviso}"
