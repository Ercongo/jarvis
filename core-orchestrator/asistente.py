"""
Asistente de instalación y configuración (fase 1).

Una página (ui/asistente.html) con pasos y voz: idioma, quién eres, nombre del asistente (con prueba de
activación por el micrófono), color, voz (con descarga de voces de Piper), pantallas, qué conviene a este
equipo, cuentas (Groq, Telegram, Google, GitHub), importar un perfil y terminar.

Dos formas de usarlo:
  - Dentro del asistente ya instalado: «Jarvis, abre la configuración» → http://127.0.0.1:8765/asistente
    (jarvis.py le pasa las peticiones /asistente*).
  - Solo, en una instalación nueva (sin asistente funcionando todavía):
        python3 asistente.py            → sirve en http://127.0.0.1:8765/asistente y lo abre en el navegador
    Usa el mismo puerto que luego usará el asistente para que el permiso de Google vuelva al sitio de siempre.
    Al terminar se cierra y arranca el asistente.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Callable

import equipo
import pantallas
import perfil
import secretos
from perfil import DATOS, INSTALACION, MOTOR, SECRETOS

UI = MOTOR / "ui"
VOCES = INSTALACION / "voces"
TMP = Path(tempfile.gettempdir()) / "jarvis" / "asistente"
PUERTO = 8765
UA = "Mozilla/5.0 (X11; Linux x86_64) Asistente/1.0"
HF_PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

# Voces de Piper que se ofrecen (oct 2026). El género solo se pone cuando es seguro; las demás se escuchan.
CATALOGO = [
    # id, idioma, descripción, megas aproximados
    ("es_ES-sharvard-medium", "es-ES", "Sharvard · 2 voces (la 1 es la del Jarvis original)", 77),
    ("es_ES-davefx-medium", "es-ES", "Davefx · hombre", 63),
    ("es_ES-carlfm-x_low", "es-ES", "Carlfm · hombre · ligera", 28),
    ("es_ES-mls_9972-low", "es-ES", "MLS 9972 · ligera", 63),
    ("es_ES-mls_10246-low", "es-ES", "MLS 10246 · ligera", 63),
    ("es_MX-ald-medium", "es-MX", "Ald · México", 63),
    ("es_MX-claude-high", "es-MX", "Claude · México · alta calidad", 114),
    ("es_AR-daniela-high", "es-AR", "Daniela · mujer · Argentina", 114),
    ("en_US-lessac-medium", "en-US", "Lessac · woman · US", 63),
    ("en_US-ryan-high", "en-US", "Ryan · man · US", 121),
    ("en_GB-alan-medium", "en-GB", "Alan · man · UK", 63),
    ("fr_FR-siwis-medium", "fr-FR", "Siwis · femme", 63),
    ("de_DE-thorsten-medium", "de-DE", "Thorsten · Mann", 63),
    ("it_IT-riccardo-x_low", "it-IT", "Riccardo · uomo", 28),
    ("pt_BR-faber-medium", "pt-BR", "Faber · homem", 63),
    ("ca_ES-upc_ona-medium", "ca-ES", "Ona · dona", 63),
]

FRASES_PASO = {     # lo que dice en voz alta al llegar a cada paso
    "bienvenida": "Hola. Voy a ayudarte a prepararme. Son unos pocos pasos y puedes cambiarlos cuando quieras.",
    "tu": "Primero, cuéntame cómo te llamas y cómo quieres que te trate.",
    "asistente": "Ahora elige cómo me llamo. Después lo probamos con tu voz.",
    "aspecto": "Elige el color de mi interfaz.",
    "voz": "Elige mi voz. Puedes escuchar cada una antes de decidir.",
    "pantallas": "Dime en qué pantalla quieres verme y en cuál trabajas.",
    "equipo": "He mirado este ordenador. Esto es lo que te recomiendo instalar.",
    "cuentas": "Ahora las cuentas. Todas son opcionales, y las claves se quedan solo en este equipo.",
    "perfil": "Si ya me tenías en otro ordenador, puedes traer aquí tu perfil.",
    "listo": "Todo listo. Cuando pulses terminar, me reinicio con lo que has elegido.",
}


def url_voz(modelo: str) -> str:
    idioma_region, nombre_, calidad = modelo.split("-", 2)
    idioma = idioma_region.split("_")[0]
    return f"{HF_PIPER}{idioma}/{idioma_region}/{nombre_}/{calidad}/{modelo}.onnx"


def voces_instaladas() -> list[dict]:
    fuera = []
    for p in sorted(INSTALACION.rglob("*.onnx")):
        if "venv" in p.parts or not Path(str(p) + ".json").exists():
            continue
        try:
            hablantes = int(json.loads(Path(str(p) + ".json").read_text()).get("num_speakers", 1))
        except (OSError, ValueError):
            hablantes = 1
        fuera.append({"modelo": p.stem, "ruta": str(p), "hablantes": hablantes})
    return fuera


def _reproductor() -> list[str] | None:
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def _http_json(url: str, cabeceras: dict | None = None, datos: dict | None = None, timeout: float = 15) -> dict:
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(url, data=cuerpo, headers={"User-Agent": UA, **({"Content-Type": "application/json"}
                                                                                  if cuerpo else {}), **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _guardar_secreto(nombre_: str, datos: dict) -> None:
    ruta = SECRETOS / nombre_
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(ruta)


def _leer_secreto(nombre_: str) -> dict:
    try:
        return json.loads((SECRETOS / nombre_).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Asistente:
    def __init__(self, log=print, embebido: bool = False, reiniciar: Callable[[], None] | None = None,
                 google=None, al_terminar: Callable[[], None] | None = None,
                 mientras_habla: Callable[[float], None] | None = None):
        self.log = log
        self.mientras_habla = mientras_habla     # dentro del asistente: que no se oiga a sí mismo (segundos)
        self.embebido = embebido           # True: lo sirve el asistente ya en marcha (jarvis.py)
        self.reiniciar = reiniciar
        self.al_terminar = al_terminar
        self.google = google
        self._voces: dict[str, object] = {}
        self._descargas: dict[str, dict] = {}
        self._whisper = None
        self._lock = threading.Lock()
        self._telegram: dict = {}
        TMP.mkdir(parents=True, exist_ok=True)

    # ================================================================ HTTP
    def responder(self, metodo: str, ruta: str, cuerpo: bytes = b"") -> tuple[int, bytes, str] | None:
        """(código, contenido, tipo) para /asistente*, o None si no es suyo."""
        camino = urllib.parse.urlsplit(ruta).path
        if not camino.startswith("/asistente"):
            return None
        try:
            if metodo == "GET" and camino in ("/asistente", "/asistente/"):
                html = (UI / "asistente.html").read_text(encoding="utf-8")
                return 200, html.encode(), "text/html; charset=utf-8"
            if metodo == "GET" and camino == "/asistente/estado":
                return self._json(self.estado())
            if metodo == "POST":
                try:
                    datos = json.loads(cuerpo or b"{}")
                except ValueError:
                    return self._json({"ok": False, "mensaje": "petición no válida"}, 400)
                accion = camino[len("/asistente/"):].replace("/", "_")
                funcion = getattr(self, f"p_{accion}", None)
                if funcion is None:
                    return self._json({"ok": False, "mensaje": "no existe"}, 404)
                return self._json(funcion(datos))
        except Exception as e:                      # nunca tumbar el servidor del asistente
            self.log(f"asistente: error en {camino}: {e!r}")
            return self._json({"ok": False, "mensaje": f"error: {e}"}, 500)
        return self._json({"ok": False, "mensaje": "no existe"}, 404)

    @staticmethod
    def _json(datos, codigo: int = 200) -> tuple[int, bytes, str]:
        return codigo, json.dumps(datos, ensure_ascii=False).encode(), "application/json; charset=utf-8"

    # ================================================================ estado
    def estado(self) -> dict:
        eq = equipo.detectar()
        salidas = pantallas.listar()
        plan = pantallas.plan(salidas)
        tg = _leer_secreto("telegram.json")
        gh = _leer_secreto("github.json")
        g = _leer_secreto("google.json")
        return {
            "perfil": perfil.perfil(),
            "embebido": self.embebido,
            "frases": {k: perfil.con_nombre(v) for k, v in FRASES_PASO.items()},
            "equipo": {"ram_gb": eq.ram_gb, "nucleos": eq.nucleos, "cpu": eq.cpu, "graficas": eq.graficas,
                       "portatil": eq.portatil, "disco_libre_gb": eq.disco_libre_gb},
            "recomendado": equipo.recomendar(eq),
            "pantallas": [{"nombre": s.nombre, "geo": s.geo, "interna": s.interna, "principal": s.principal}
                          for s in salidas],
            "plan": {"interfaz": plan.interfaz.nombre if plan.interfaz else "",
                     "trabajo": plan.trabajo.nombre if plan.trabajo else "", "dedicada": plan.dedicada},
            "voces": {"instaladas": voces_instaladas(),
                      "catalogo": [{"modelo": m, "idioma": i, "texto": t, "mb": mb} for m, i, t, mb in CATALOGO],
                      "descargas": self._descargas},
            "cuentas": {
                "groq": bool(_leer_secreto("groq.json").get("api_key")),
                "telegram": {"token": bool(tg.get("token")), "vinculado": bool(tg.get("dueno")),
                             "bot": tg.get("bot", ""), "codigo": self._telegram.get("codigo", "")},
                "google": {"cliente": bool(g.get("client_id")), "conectada": bool(g.get("refresh_token")),
                           "email": g.get("email", "")},
                "github": {"token": bool(gh.get("token")), "usuario": gh.get("usuario", "")},
                "movil": self._estado_movil(),
            },
            "microfono": bool(shutil.which("parec") or shutil.which("pw-record")),
        }

    @staticmethod
    def _estado_movil() -> dict:
        try:
            import movil
            return {"instalado": movil.disponible(), "dispositivos": [d["nombre"] for d in movil.dispositivos()]}
        except Exception:
            return {"instalado": False, "dispositivos": []}

    def p_movil_abrir(self, d: dict) -> dict:
        """Abre KDE Connect en el PC para aceptar el emparejamiento."""
        for cmd in (["kdeconnect-app"], ["kdeconnect-settings"], ["kdeconnect-indicator"]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return {"ok": True, "mensaje": "Abierto KDE Connect en el ordenador: busca ahí tu móvil y pulsa «Emparejar»."}
        return {"ok": False, "mensaje": "KDE Connect no está instalado en este ordenador. Abre una terminal y escribe: "
                                        "sudo apt install kdeconnect"}

    # ================================================================ perfil
    def p_perfil(self, d: dict) -> dict:
        permitidos = {"nombre", "genero", "idioma", "color", "usuario", "pantallas", "voz", "activacion", "equipo"}
        cambios = {k: v for k, v in d.items() if k in permitidos}
        if "nombre" in cambios:
            cambios["nombre"] = re.sub(r"\s+", " ", str(cambios["nombre"])).strip()[:24] or "Jarvis"
        aviso_extra = ""
        if "activacion" in cambios:
            limpias = []
            for x in cambios["activacion"] or []:
                x = re.sub(r"[\"'«»“”‘’]", "", str(x)).strip().lower()
                x = re.sub(r"\s+", " ", x)
                if x and x not in limpias:
                    limpias.append(x[:40])
            cambios["activacion"] = limpias[:10]
            comunes = [x for x in limpias if perfil._sin_tildes(x) in perfil.VOCATIVOS or
                       perfil._sin_tildes(x) in ("si", "no", "vale", "gracias", "adios", "jarvis")]
            if comunes:
                aviso_extra = ("Ojo: " + ", ".join(f"«{c}»" for c in comunes) + " se dice a menudo; me despertaré cada "
                               "vez que empieces una frase así.")
        if "color" in cambios and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(cambios["color"])):
            return {"ok": False, "mensaje": "el color tiene que ser #rrggbb"}
        p = perfil.guardar(**cambios)
        aviso = self._aviso_nombre(p["nombre"]) if "nombre" in cambios else aviso_extra
        return {"ok": True, "perfil": p, "aviso": aviso}

    @staticmethod
    def _aviso_nombre(n: str) -> str:
        bajo = perfil._sin_tildes(n)
        comunes = {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "casa", "luz", "sol",
                   "luna", "mar", "cielo", "musica", "hola", "vale", "bueno", "alexa", "siri", "google", "cortana"}
        if bajo in comunes:
            return (f"«{n}» es una palabra que se dice mucho: solo te haré caso si la dices al principio de la frase o "
                    "después de un saludo («oye», «hola»).")
        if len(bajo) <= 3:
            return "Los nombres muy cortos se confunden más; pruébalo varias veces con el micrófono."
        return ""

    # ================================================================ voz
    def _voz(self, modelo: str):
        from piper import PiperVoice
        with self._lock:
            if modelo not in self._voces:
                ruta = next((v["ruta"] for v in voces_instaladas() if v["modelo"] == modelo), None)
                if not ruta:
                    raise FileNotFoundError(f"la voz {modelo} no está instalada")
                self._voces[modelo] = PiperVoice.load(ruta)
            return self._voces[modelo]

    def decir(self, texto: str, modelo: str | None = None, hablante: int | None = None,
              lentitud: float | None = None) -> bool:
        ajustes = perfil.perfil().get("voz") or {}
        instaladas = voces_instaladas()
        if not instaladas:
            return False
        modelo = modelo or ajustes.get("modelo") or next((v["modelo"] for v in instaladas
                                                          if "sharvard" in v["modelo"]), instaladas[0]["modelo"])
        info = next((v for v in instaladas if v["modelo"] == modelo), instaladas[0])
        modelo = info["modelo"]
        if hablante is None:
            hablante = ajustes.get("hablante")
        hablante = (int(hablante) if hablante is not None else 1) if info["hablantes"] > 1 else None
        lentitud = float(lentitud or ajustes.get("lentitud") or 1.05)
        voz = self._voz(modelo)
        destino = TMP / f"voz_{int(time.time() * 1000)}.wav"
        with wave.open(str(destino), "wb") as w:
            if hasattr(voz, "synthesize_wav"):
                try:
                    from piper import SynthesisConfig
                    voz.synthesize_wav(texto, w, syn_config=SynthesisConfig(speaker_id=hablante, length_scale=lentitud))
                except ImportError:
                    voz.synthesize_wav(texto, w)
            else:
                voz.synthesize(texto, w, speaker_id=hablante, length_scale=lentitud)
        cmd = _reproductor()
        if cmd:
            if self.mientras_habla:
                try:
                    with wave.open(str(destino), "rb") as w:
                        self.mientras_habla(w.getnframes() / w.getframerate())
                except (OSError, wave.Error):
                    self.mientras_habla(8.0)
            subprocess.Popen(cmd + [str(destino)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Timer(60, lambda: destino.unlink(missing_ok=True)).start()
        return True

    def p_decir(self, d: dict) -> dict:
        texto = perfil.con_nombre(str(d.get("texto") or ""))[:400]
        if not texto:
            return {"ok": False}
        try:
            return {"ok": self.decir(texto, d.get("modelo"), d.get("hablante"))}
        except Exception as e:
            return {"ok": False, "mensaje": str(e)}

    def p_voz_probar(self, d: dict) -> dict:
        n = perfil.nombre()
        texto = d.get("texto") or (f"Hola, soy {n}. Así es como sonaré a partir de ahora."
                                   if str(d.get("modelo", "")).startswith(("es", "ca")) else
                                   f"Hello, I am {n}. This is how I will sound from now on.")
        return self.p_decir({"texto": texto, "modelo": d.get("modelo"), "hablante": d.get("hablante")})

    def p_voz_descargar(self, d: dict) -> dict:
        modelo = str(d.get("modelo") or "")
        if modelo not in {m for m, *_ in CATALOGO}:
            return {"ok": False, "mensaje": "voz desconocida"}
        if any(v["modelo"] == modelo for v in voces_instaladas()):
            return {"ok": True, "mensaje": "ya estaba instalada"}
        if self._descargas.get(modelo, {}).get("estado") == "bajando":
            return {"ok": True, "mensaje": "ya se está descargando"}
        self._descargas[modelo] = {"estado": "bajando", "hecho": 0}
        threading.Thread(target=self._descargar_voz, args=(modelo,), daemon=True).start()
        return {"ok": True}

    def _descargar_voz(self, modelo: str) -> None:
        estado = self._descargas[modelo]
        destino = VOCES / modelo
        try:
            destino.mkdir(parents=True, exist_ok=True)
            for sufijo in (".onnx.json", ".onnx"):
                url = url_voz(modelo) + sufijo[len(".onnx"):]
                tmp = destino / (modelo + sufijo + ".parte")
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    leido = 0
                    while True:
                        trozo = r.read(1 << 16)
                        if not trozo:
                            break
                        f.write(trozo)
                        leido += len(trozo)
                        if sufijo == ".onnx" and total:
                            estado["hecho"] = round(100 * leido / total)
                tmp.replace(destino / (modelo + sufijo))
            estado.update(estado="lista", hecho=100)
            self.log(f"asistente: voz {modelo} descargada")
        except Exception as e:
            estado.update(estado="error", mensaje=str(e)[:200])
            self.log(f"asistente: no se pudo bajar la voz {modelo}: {e}")

    # ================================================================ prueba de activación
    def p_activacion_probar(self, d: dict) -> dict:
        """Graba unos segundos, transcribe en local y dice si se le habría despertado."""
        segundos = max(2.0, min(6.0, float(d.get("segundos") or 4)))
        if shutil.which("parec"):
            cmd = ["parec", "--format=s16le", "--rate=16000", "--channels=1"]
        elif shutil.which("pw-record"):
            cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "-"]
        else:
            return {"ok": False, "mensaje": "no encuentro el micrófono (parec / pw-record)"}
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        bruto = b""
        fin = time.time() + segundos
        while time.time() < fin:
            bruto += p.stdout.read(3200) or b""
        p.kill()
        try:
            import numpy as np
            from faster_whisper import WhisperModel
        except ImportError:
            return {"ok": False, "mensaje": "falta el reconocimiento de voz local (faster-whisper)"}
        audio = np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0
        if float(np.sqrt((audio ** 2).mean() + 1e-12)) < 0.004:
            return {"ok": True, "oido": "", "despierta": False, "mensaje": "No te he oído. ¿El micrófono está encendido?"}
        with self._lock:
            if self._whisper is None:
                self._whisper = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=2)
        idioma = perfil.idioma().split("-")[0]
        segs, _ = self._whisper.transcribe(audio, language=idioma, beam_size=1, vad_filter=True,
                                           initial_prompt=perfil.con_nombre("Hola, Jarvis."))
        texto = " ".join(s.text.strip() for s in segs).strip()
        llamado, resto = perfil.separar_nombre(texto)
        n = perfil.nombre()
        return {"ok": True, "oido": texto, "despierta": llamado, "resto": resto,
                "mensaje": (f"Perfecto: con «{texto}» me habría despertado." if llamado else
                            f"He entendido «{texto or '…'}» y no me habría despertado. Prueba a decir «{n}» "
                            "más claro, o añade cómo te lo entiendo como palabra extra.")}

    # ================================================================ cuentas
    def p_groq(self, d: dict) -> dict:
        clave = str(d.get("clave") or "").strip()
        if not re.fullmatch(r"gsk_[A-Za-z0-9]{20,}", clave):
            return {"ok": False, "mensaje": "Las claves de Groq empiezan por gsk_. Cópiala entera."}
        try:
            modelos = _http_json("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {clave}"})
        except urllib.error.HTTPError as e:
            return {"ok": False, "mensaje": f"Groq no acepta esa clave ({e.code})."}
        except OSError as e:
            return {"ok": False, "mensaje": f"No llego a Groq: {e}"}
        _guardar_secreto("groq.json", {"api_key": clave})
        n = len(modelos.get("data") or [])
        return {"ok": True, "mensaje": f"Clave guardada. Groq ofrece {n} modelos con ella."}

    def p_telegram(self, d: dict) -> dict:
        token = str(d.get("token") or "").strip()
        if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", token):
            return {"ok": False, "mensaje": "El token de BotFather tiene la forma 123456789:AA… Cópialo entero."}
        try:
            yo = _http_json(f"https://api.telegram.org/bot{token}/getMe")["result"]
        except (urllib.error.HTTPError, OSError, KeyError) as e:
            return {"ok": False, "mensaje": f"Telegram no acepta ese token ({e})."}
        anterior = _leer_secreto("telegram.json")
        cfg = {"token": token, "bot": yo.get("username", "")}
        if anterior.get("token") == token and anterior.get("dueno"):
            cfg["dueno"] = anterior["dueno"]
        _guardar_secreto("telegram.json", cfg)
        if cfg.get("dueno"):
            return {"ok": True, "vinculado": True, "mensaje": f"Bot @{cfg['bot']} guardado y ya vinculado."}
        if self.embebido:
            return {"ok": True, "vinculado": False, "mensaje": (f"Bot @{cfg['bot']} guardado. Al terminar me reinicio y "
                                                                 "te diré un código para mandárselo.")}
        codigo = f"{int.from_bytes(os.urandom(2), 'big') % 9000 + 1000}"
        self._telegram = {"codigo": codigo, "token": token}
        threading.Thread(target=self._esperar_codigo, args=(token, codigo), daemon=True).start()
        return {"ok": True, "vinculado": False, "codigo": codigo,
                "mensaje": f"Bot @{cfg['bot']} guardado. Abre Telegram y mándale este código: {codigo}"}

    def _esperar_codigo(self, token: str, codigo: str) -> None:
        """Solo en una instalación nueva (no hay otro asistente leyendo el bot)."""
        offset = 0
        fin = time.time() + 900
        while time.time() < fin and self._telegram.get("codigo") == codigo:
            try:
                r = _http_json(f"https://api.telegram.org/bot{token}/getUpdates?timeout=25&offset={offset}",
                               timeout=35)
            except (OSError, ValueError):
                time.sleep(5)
                continue
            for u in r.get("result") or []:
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                if str(m.get("text", "")).strip() == codigo:
                    cfg = _leer_secreto("telegram.json")
                    cfg["dueno"] = m["chat"]["id"]
                    _guardar_secreto("telegram.json", cfg)
                    self._telegram = {}
                    try:
                        _http_json(f"https://api.telegram.org/bot{token}/sendMessage",
                                   datos={"chat_id": m["chat"]["id"],
                                          "text": perfil.con_nombre("Vinculado. Soy Jarvis; desde ahora te contesto aquí.")})
                    except OSError:
                        pass
                    self.log("asistente: Telegram vinculado")
                    return

    def p_google_cliente(self, d: dict) -> dict:
        texto = str(d.get("json") or "")
        try:
            datos = json.loads(texto)
        except ValueError:
            return {"ok": False, "mensaje": "Eso no es el archivo JSON que descarga Google Cloud."}
        if self.google is None:
            from google_cuenta import CuentaGoogle
            self.google = CuentaGoogle(self.log)
        ok, mensaje = self.google.guardar_cliente(datos)
        return {"ok": ok, "mensaje": "Credenciales guardadas. Ahora pulsa «Conectar con Google»." if ok else mensaje}

    def p_github(self, d: dict) -> dict:
        token = str(d.get("token") or "").strip()
        if not re.fullmatch(r"(github_pat_|ghp_)[A-Za-z0-9_]{20,}", token):
            return {"ok": False, "mensaje": "Los tokens de GitHub empiezan por github_pat_ (o ghp_)."}
        try:
            yo = _http_json("https://api.github.com/user", {"Authorization": f"Bearer {token}",
                                                            "Accept": "application/vnd.github+json"})
        except urllib.error.HTTPError as e:
            return {"ok": False, "mensaje": f"GitHub no acepta ese token ({e.code})."}
        except OSError as e:
            return {"ok": False, "mensaje": f"No llego a GitHub: {e}"}
        _guardar_secreto("github.json", {"token": token, "usuario": yo.get("login", "")})
        return {"ok": True, "mensaje": f"Conectado a GitHub como {yo.get('login')}."}

    def p_cuenta_quitar(self, d: dict) -> dict:
        archivo = {"groq": "groq.json", "telegram": "telegram.json", "github": "github.json"}.get(str(d.get("cuenta")))
        if not archivo:
            return {"ok": False}
        (SECRETOS / archivo).unlink(missing_ok=True)
        return {"ok": True}

    # ================================================================ perfil de otro PC
    def p_perfil_importar(self, d: dict) -> dict:
        try:
            datos = base64.b64decode(str(d.get("archivo") or ""), validate=True)
        except ValueError:
            return {"ok": False, "mensaje": "archivo no válido"}
        if len(datos) > 200 * 1024 ** 2:
            return {"ok": False, "mensaje": "el perfil es demasiado grande"}
        tmp = TMP / f"importar_{int(time.time())}.jarvisperfil"
        tmp.write_bytes(datos)
        try:
            m = secretos.importar(tmp, str(d.get("contrasena") or ""))
        except secretos.ErrorPerfil as e:
            return {"ok": False, "mensaje": str(e)}
        finally:
            tmp.unlink(missing_ok=True)
        aviso = ""
        if any(x.endswith("telegram.json") for x in m.get("puestos", [])):
            aviso = ("Si el otro ordenador sigue encendido con el mismo bot de Telegram, os pelearéis por los mensajes: "
                     "apágalo allí o crea un bot nuevo para este.")
        return {"ok": True, "perfil": perfil.perfil(), "aviso": aviso,
                "mensaje": f"Perfil de {m.get('asistente')} ({m.get('equipo')}) traído: {len(m.get('puestos', []))} archivos."}

    def p_perfil_exportar(self, d: dict) -> dict:
        destino = Path(str(d.get("destino") or Path.home() / "Escritorio" / "mi_asistente.jarvisperfil")).expanduser()
        try:
            p = secretos.exportar(destino, str(d.get("contrasena") or ""), con_claves=bool(d.get("claves", True)))
        except secretos.ErrorPerfil as e:
            return {"ok": False, "mensaje": str(e)}
        return {"ok": True, "mensaje": f"Guardado en {p}."}

    # ================================================================ terminar
    def p_terminar(self, d: dict) -> dict:
        perfil.guardar(instalado=True, configurado=time.strftime("%Y-%m-%d %H:%M"))
        secretos.asegurar_permisos()
        self.log("asistente: configuración terminada")
        if self.al_terminar:
            threading.Timer(1.5, self.al_terminar).start()
        elif self.reiniciar:
            threading.Timer(1.5, self.reiniciar).start()
        return {"ok": True, "mensaje": perfil.con_nombre("Hecho. Jarvis se reinicia con lo que has elegido.")}

    # ================================================================ orden por voz
    def manejar(self, peticion: str):
        """«abre la configuración», «configúrate», «quiero cambiarte el nombre / la voz / el color»."""
        from herramientas import abrir_web, normalizar
        from sistema import Respuesta
        t = normalizar(peticion).strip(" .¿?¡!")
        if re.search(r"\b(?:abre|abreme|ensename|lanza|ejecuta)\s+(?:el |la )?(?:asistente de |pagina de )?"
                     r"(?:configuracion|instalacion|ajustes)(?: del asistente| tuya| de jarvis)?$", t) or \
                re.fullmatch(r"(?:configurate|reconfigurate|quiero configurarte|vamos a configurarte|"
                             r"(?:quiero )?cambiar(?:te)? (?:el |tu )?(?:nombre|voz|color|aspecto))", t):
            abrir_web(f"http://127.0.0.1:{PUERTO}/asistente")
            return Respuesta("Te abro mi configuración en el portátil.")
        return None


# ==================================================================== servidor propio (instalación nueva)
def servir(abrir: bool = True) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from google_cuenta import CuentaGoogle

    google = CuentaGoogle(print)
    terminado = threading.Event()
    asis = Asistente(print, embebido=False, google=google, al_terminar=terminado.set)

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _enviar(self, codigo: int, datos: bytes, tipo: str) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):
            if self.path == "/":
                self.send_response(302)
                self.send_header("Location", "/asistente")
                self.end_headers()
                return
            if re.fullmatch(r"/fuentes/[a-z0-9-]+\.woff2", self.path):
                f = UI / self.path.lstrip("/")
                if f.exists():
                    return self._enviar(200, f.read_bytes(), "font/woff2")
            if self.path == "/google/conectar":
                try:
                    destino = google.url_permiso()
                except Exception as e:
                    return self._enviar(200, f"<p>No puedo conectar todavía: {e}</p>".encode(), "text/html; charset=utf-8")
                self.send_response(302)
                self.send_header("Location", destino)
                self.end_headers()
                return
            if self.path.startswith("/google?") or self.path == "/google":
                params = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
                ok, mensaje = google.recibir_codigo(params)
                pagina = (f"<meta charset=utf-8><body style='background:#01040a;color:#cdf7ff;font:20px sans-serif;"
                          f"padding:40px'><h2>{'✔' if ok else '✖'} {mensaje}</h2><p>Puedes cerrar esta pestaña y volver "
                          f"al asistente.</p>")
                return self._enviar(200, pagina.encode(), "text/html; charset=utf-8")
            r = asis.responder("GET", self.path)
            if r:
                return self._enviar(*r)
            self._enviar(404, b"no", "text/plain")

        def do_POST(self):
            largo = int(self.headers.get("Content-Length") or 0)
            if self.headers.get("X-Asistente") != "1" or largo > 300 * 1024 ** 2:
                return self._enviar(403, b"no", "text/plain")
            r = asis.responder("POST", self.path, self.rfile.read(largo))
            if r:
                return self._enviar(*r)
            self._enviar(404, b"no", "text/plain")

    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PUERTO}/asistente"
    print(f"Asistente de configuración en {url}")
    if abrir:
        for cmd in (["firefox", "--new-window", url], ["xdg-open", url]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                break
    try:
        terminado.wait()
        time.sleep(1)
    except KeyboardInterrupt:
        pass
    servidor.shutdown()
    servidor.server_close()
    arranque = INSTALACION / "arrancar_jarvis.sh"
    if terminado.is_set() and arranque.exists():
        print("Arrancando el asistente…")
        subprocess.Popen(["bash", str(arranque)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


if __name__ == "__main__":
    import sys
    servir(abrir="--sin-abrir" not in sys.argv)
