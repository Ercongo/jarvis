"""
Proyecto NEXUS: un personaje de IA declarado (influencer virtual) en TikTok, Instagram, YouTube, X, Twitch,
Pinterest y correo, llevado por el asistente paso a paso y preguntando lo que necesita.

  «proyecto nexus», «sigue con nexus», «en qué paso va nexus»   → dice el paso y hace la pregunta que toque
  (la respuesta se dice normal: «la tercera», «Vexara», «sí», «cámbiale el pelo a más corto»…)
  «nexus: vuelve al paso de las bios», «nexus: haz otro vídeo», «nexus: ideas de vídeos», «abre el panel de nexus»
  «nexus: prepara un clip en deevid / opengen / viggle», «nexus: ya tengo el clip», «nexus: material»,
  «nexus: aprueba la foto 12», «nexus: quita la foto 12»

Material propio del personaje (lo usa antes que generar nada):
  ~/jarvis/nexus/referencias/  fotos del personaje + indice.json (escena y si es «publica», «revisar» o «no»)
  ~/jarvis/nexus/clips/        clips hechos en DeeVid, OpenGen, Viggle… + indice.json
En los vídeos, cada escena sale de una categoría al azar según la mezcla elegida por la persona (por defecto 60 %
verdes «publica», 35 % ámbar «revisar», 5 % rojas «no»): «nexus: mezcla 60 35 5». La foto de perfil, solo verdes.
Diario: todo lo que pasa con el personaje (preguntas, respuestas, vídeos, material, publicaciones y comentarios)
se apunta en ~/jarvis/nexus/diario.jsonl y se ve en el panel, que se abre solo al arrancar.

Lo que hace el asistente: nombre, biblia del personaje, retratos (FLUX), biografías por red con el aviso de IA,
guiones, voz, vídeos verticales y el calendario. Lo que hace la persona (las redes lo exigen): crear cuentas,
verificarlas con su móvil y dar permiso a las conexiones oficiales de publicación.

Todo se guarda en ~/jarvis/nexus/ y se ve en http://127.0.0.1:8765/nexus.
"""

from __future__ import annotations

import json
import random
import re
import threading
import sys
import time
from pathlib import Path
from typing import Callable

from shutil import copy as shutil_copy

from herramientas import abrir_web, normalizar
from perfil import DATOS
from sistema import Respuesta

NX = DATOS / "nexus"
ESTADO = NX / "estado.json"
REF, CLIPS = NX / "referencias", NX / "clips"
ENTORNO = NX / "entorno"   # su mundo sin ella: su cuarto, su colección, sus perras (fotos de la persona)
SUBIR = {   # dónde se publica a mano en cada red (mientras no haya conexión oficial)
    "tiktok": {"subir": "https://www.tiktok.com/tiktokstudio/upload"},
    "instagram": {"subir": "https://www.instagram.com/"},
    "youtube": {"subir": "https://studio.youtube.com/"},
    "x": {"subir": "https://x.com/compose/post"},
    "twitch": {"subir": "https://dashboard.twitch.tv/"},
    "pinterest": {"subir": "https://www.pinterest.es/pin-creation-tool/"},
    "facebook": {"subir": "https://www.facebook.com/"},
}
DESCARGAS = [Path.home() / "Descargas", Path.home() / "Downloads"]
# Webs de vídeo con crédito gratis que usa la persona con SU cuenta (Athena prepara la foto y la instrucción, ella pulsa
# «generar» y se lo manda). (nombre, dirección, cuándo vuelve el crédito: dia | mes | nunca). En orden de preferencia.
WEBS_CLIP = {
    "flow": ("Google Flow (Veo)", "https://labs.google/fx/tools/flow", "dia"),          # 50 créditos al día; vídeo con sonido
    "kling": ("Kling", "https://app.klingai.com/global/image-to-video", "mes"),
    "dreamina": ("Dreamina", "https://dreamina.capcut.com/ai-tool/video/generate", "dia"),
    "capcut": ("CapCut", "https://www.capcut.com/es-es/tools/ai-video-generator", "dia"),
    "vidu": ("Vidu", "https://www.vidu.com/create/img2video", "mes"),
    "firefly": ("Adobe Firefly", "https://firefly.adobe.com/generate/video", "dia"),   # sin marca de agua, según Adobe
    "pixverse": ("PixVerse", "https://app.pixverse.ai/", "dia"),                       # 30 créditos al día, 540p
    "krea": ("Krea", "https://www.krea.ai/video", "dia"),
    "vheer": ("Vheer", "https://vheer.com/image-to-video", "dia"),                     # sin registro
    "pippit": ("Pippit", "https://www.pippit.ai/", "dia"),
    "apob": ("Apob", "https://www.apob.ai/", "dia"),
    "invideo": ("InVideo AI", "https://invideo.io/", "semana"),
    "deevid": ("DeeVid", "https://deevid.ai/es/model/h3", "dia"),
    "opengen": ("OpenGen", "https://opengen.ai/video", "dia"),
    "viggle": ("Viggle", "https://viggle.ai", "dia"),
    "hailuo": ("Hailuo (MiniMax)", "https://hailuoai.video/", "nunca"),               # solo créditos de bienvenida
    "sjinn": ("SJinn", "https://sjinn.ai/", "nunca"),
    "pika": ("Pika", "https://pika.art/", "nunca"),                                    # ya sin créditos gratis al mes
    "metaai": ("Meta AI", "https://www.meta.ai/", "dia"),                      # «Imagine» y «animar», con su cuenta de Meta
    "wanweb": ("Wan (web oficial)", "https://create.wan.video/", "dia"),       # Wan 2.5+ con créditos diarios
    "hedra": ("Hedra", "https://www.hedra.com/app/video", "mes"),             # ella hablando con SU voz (300 créditos/mes)
    "heygen": ("HeyGen", "https://app.heygen.com/", "mes"),                   # foto que habla con su audio (pocos al mes)
    "vidnoz": ("Vidnoz", "https://www.vidnoz.com/talking-photo.html", "dia"), # foto que habla, crédito diario
    "nanobanana": ("Nano Banana (Gemini)", "https://gemini.google.com/app", "dia"),   # fotos nuevas con su misma cara
}
TIPO_WEB = {"hedra": "habla", "heygen": "habla", "vidnoz": "habla", "nanobanana": "foto"}                       # las demás: clip con movimiento
ALIAS_WEB = {"cap cut": "capcut", "capcut": "capcut", "dreamina": "dreamina", "pixverse": "pixverse", "pix verse": "pixverse",
             "krea": "krea", "pika": "pika", "kling": "kling", "clin": "kling", "hailuo": "hailuo",
             "minimax": "hailuo", "deevid": "deevid", "opengen": "opengen", "open gen": "opengen", "viggle": "viggle",
             "sjinn": "sjinn", "hedra": "hedra", "nano banana": "nanobanana", "nanobanana": "nanobanana",
             "gemini": "nanobanana", "google flow": "flow", "flow": "flow", "vidu": "vidu",
             "firefly": "firefly", "adobe": "firefly", "vheer": "vheer", "pippit": "pippit", "apob": "apob",
             "invideo": "invideo", "in video": "invideo", "heygen": "heygen", "hey gen": "heygen", "vidnoz": "vidnoz",
             "gidnoz": "vidnoz", "vidnos": "vidnoz", "dreamina": "dreamina", "meta ai": "metaai", "meta": "metaai",
             "wan video": "wanweb", "wan web": "wanweb", "vigier": "viggle", "vigle": "viggle"}
VOZ_DESC = ["Young adult woman from Spain, about 24, warm slightly husky mid-low voice, confident and playful, dry "
            "sarcastic humor, natural Castilian Spanish accent, relaxed pace, like a gamer streamer talking to her chat",
            "Young adult woman from Madrid, clear bright voice with a teasing tone, energetic but not shouting, quick "
            "witty delivery, Castilian Spanish accent, sounds like a popular tech and gaming creator",
            "Young adult woman from Spain, low smooth calm voice, deadpan and ironic, slightly raspy, confident, "
            "Castilian Spanish accent, unhurried like a late-night streamer"]
MEZCLA = {"publica": 60, "revisar": 35, "no": 5}
VOZ_TEXTO = "Hola, soy {n}. Gamer, friki del anime y del gimnasio. Y no, no vengo a caerte bien."
def _apaisado(video: Path) -> bool:
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(video)], capture_output=True, text=True, timeout=30)
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
        return w > h
    except Exception:
        return False


HORA_MOV = {"tiktok": "20:00", "instagram": "20:30", "facebook": "21:00", "youtube": "21:15"}   # las 20 es su mejor hora
REDES = {
    "tiktok": {"nombre": "TikTok", "alta": "https://www.tiktok.com/signup", "bio": 80,
               "perfil": "https://www.tiktok.com/@{u}"},
    "instagram": {"nombre": "Instagram", "alta": "https://www.instagram.com/accounts/emailsignup/", "bio": 150,
                  "perfil": "https://www.instagram.com/{u}/"},
    "youtube": {"nombre": "YouTube", "alta": "https://www.youtube.com/create_channel", "bio": 1000,
                "perfil": "https://www.youtube.com/@{u}"},
    "x": {"nombre": "X", "alta": "https://x.com/i/flow/signup", "bio": 160, "perfil": "https://x.com/{u}"},
    "twitch": {"nombre": "Twitch", "alta": "https://www.twitch.tv/signup", "bio": 300, "perfil": "https://www.twitch.tv/{u}"},
    "pinterest": {"nombre": "Pinterest", "alta": "https://www.pinterest.es/business/create/", "bio": 500,
                  "perfil": "https://www.pinterest.es/{u}/"},
    "facebook": {"nombre": "Facebook (página)", "alta": "https://www.facebook.com/pages/create", "bio": 255,
                 "perfil": "https://www.facebook.com/{u}"},
}
GUIA_ALTA = {
    "tiktok": "Regístrate con el correo del personaje y el usuario. Luego: Perfil → menú → Herramientas para creadores → "
              "cambia a cuenta de empresa o creador. Pon la foto y la bio del panel.",
    "instagram": "Regístrate con el correo del personaje. Luego: Configuración → Tipo de cuenta → Cuenta profesional → Creador. "
                 "Pon foto y bio. (Para publicar sola necesitaré una página de Facebook enlazada: lo vemos en las conexiones.)",
    "youtube": "Entra con el Gmail del personaje y crea el canal con el nombre del personaje. Pon foto, banner y descripción "
               "del panel. En Configuración del canal → Opciones avanzadas, marca que el contenido está alterado o es sintético cuando toque.",
    "x": "Regístrate con el correo del personaje y el usuario. Pon foto, banner y bio. En Configuración → Privacidad → "
         "Contenido, marca la cuenta como automatizada/IA si te lo pide.",
    "twitch": "Regístrate con el usuario del personaje. Pon foto y bio. (Twitch es en directo: lo usaremos más adelante.)",
    "pinterest": "Crea una cuenta de empresa con el correo del personaje. Categoría: Entretenimiento. Pon foto y bio.",
    "facebook": "En Facebook el personaje va como PÁGINA, no como perfil de persona (Meta cierra los perfiles que no son "
                "de una persona real). Entra con tu propio Facebook → Páginas → Crear página: nombre del personaje, "
                "categoría «Creador digital», foto y bio del panel. Luego, en la página: Configuración → Cuentas "
                "vinculadas → Instagram, y enlaza su Instagram (hace falta para que yo publique en Instagram). Como "
                "usuario, apúntame el nombre de la página que sale en su dirección (facebook.com/…).",
}
ORDEN = ["nombre", "biblia", "retrato", "bios", "correo", "cuentas", "voz", "primer_video", "conexiones", "rutina"]
PANEL = ("id", "hechos", "orden", "titulos", "pregunta", "ocupado", "refrescado", "cola", "videos", "portadas",
         "perfil", "cuentas", "redes", "enlaces", "subida", "conectadas", "youtube", "comentarios", "referencias",
         "clips", "mezcla", "estadisticas", "mejores", "diario", "archivos", "prompts_lista", "prompts_pendientes",
         "todo_hecho")                     # claves que usa ui/nexus.html
TITULOS = {"nombre": "Nombre y usuario", "biblia": "Biblia del personaje", "retrato": "Retrato y foto de perfil",
           "bios": "Biografías por red", "correo": "Correo del personaje", "cuentas": "Cuentas en las redes",
           "voz": "Voz del personaje", "primer_video": "Primer vídeo", "conexiones": "Publicación automática",
           "rutina": "Calendario y rutina"}
# Transparencia mínima (lo que exigen las redes y la ley europea, nada más): una marca corta en la bio y la etiqueta
# oficial «contenido generado con IA» de cada red al publicar. No lo repite en vídeos, textos ni comentarios; pero si
# alguien pregunta en serio si es real o una IA, NUNCA lo niega: lo reconoce en una frase, en su tono, y sigue.
TRANSPARENCIA = ("No menciona que es una IA ni que la gestiona una IA en vídeos, textos ni comentarios. Si alguien le "
                 "pregunta en serio si es real, una persona o una IA, no lo niega nunca: lo reconoce en una frase corta, "
                 "con humor y en su tono, y vuelve al tema.")
BASE = ("Influencer virtual (personaje digital). Mujer joven pelirroja, gamer y friki: anime "
        "(Solo Leveling), videojuegos, gimnasio y tecnología. Aspecto fijo (el de sus fotos de referencia): pelo rojo intenso, "
        "largo y ondulado, gafas finas de montura metálica, piel clara, gargantilla negra; setup gamer con neones morados. "
        "Estética oscura y cinematográfica. Personalidad directa, "
        "ruda pero inteligente, con humor seco; nunca ofensiva ni sexualizada. Habla español de España.")
NUMEROS = {"uno": 1, "una": 1, "primero": 1, "primera": 1, "dos": 2, "segundo": 2, "segunda": 2, "tres": 3,
           "tercero": 3, "tercera": 3, "cuatro": 4, "cuarto": 4, "cuarta": 4, "cinco": 5, "quinto": 5, "quinta": 5,
           "seis": 6, "sexto": 6, "sexta": 6, "siete": 7, "septimo": 7, "septima": 7, "ocho": 8, "octavo": 8, "octava": 8}


def _json_de(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        raise ValueError("la IA no ha devuelto JSON")
    return json.loads(m.group(0))


def numero(texto: str) -> int | None:
    t = normalizar(texto)
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    for w in t.split():
        if w in NUMEROS:
            return NUMEROS[w]
    return None


def si_no(texto: str) -> str | None:
    t = normalizar(texto).strip(" .!¡?¿")
    if re.fullmatch(r"(si|vale|venga|ok|perfecto|me vale|me gusta|esta bien|adelante|dale|genial|correcto|"
                    r"si,? (me vale|esta bien|perfecto|adelante|hazlo|sigue)|sigue|siguiente)( por favor)?", t):
        return "si"
    if re.fullmatch(r"(no|no me gusta|otra vez|otros?|otras?|repite|cambialo|cambiala|no me vale)( por favor)?", t):
        return "no"
    return None


def es_entrada_directa(t: str) -> bool:
    """Lo que Nexus coge sin decir «nexus» (para que no pase antes por el cerebro y se desvíe): prompts de fotos de
    Asuka, Hedra («Edra»), «mándame las fotos rojas», «esa no es Asuka». `t` ya normalizado."""
    t = re.sub(r"\b(azuka|azucar|azuca|asuca|azzuka|askua|asuk|azuk|asucka|asuko)\b", "asuka", t)
    return bool(re.match(r"^(nexus,? )?(fotos?|imagen(es)?|prompts?) (de|para) asuka\b", t)
                or (len(t) > 90 and Nexus.RE_PROMPT_FOTO.search(t) and Nexus.RE_ESCENA_FOTO.search(t))
                or re.search(r"\b(esa|esta|eso) no es asuka\b", t)
                or (re.search(r"\b(edra|hedra|hedda)\b", t) and re.search(r"\b(video|crea\w*|haz|abre|usa|utiliza\w*)\b", t))
                or (re.search(r"\b(rojas?|rojo|verdes?|ambar)\b", t) and re.search(r"\bfotos?\b", t)
                    and re.search(r"\b(manda|envia|pasa)\w*\b", t) and "asuka" in t))


class Nexus:
    def __init__(self, cerebro, decir: Callable[[str], None], log: Callable[[str], None], ui=None, estudio=None,
                 voz=None, avisar: Callable[[str], None] | None = None,
                 enviar_foto: Callable[[str, str], None] | None = None,
                 enviar_documento: Callable[[str, str], bool] | None = None,
                 es_telegram: Callable[[], bool] = lambda: False):
        self.cerebro, self.decir, self.log, self.ui = cerebro, decir, log, ui
        self._cerrojo_pub = threading.Lock()
        self.estudio, self.voz = estudio, voz
        self.avisar = avisar or (lambda t: None)
        self.enviar_foto = enviar_foto or (lambda r, p="": None)
        self.enviar_documento = enviar_documento or (lambda r, p="": False)
        self.es_telegram = es_telegram
        self.ocupado = ""
        NX.mkdir(parents=True, exist_ok=True)
        self.e = self._leer()
        try:
            from nexus_youtube import YouTube
            self.youtube = YouTube(log)
        except Exception as ex:                            # sin módulo o sin Google: Nexus sigue igual
            self.youtube = None
            log(f"nexus: YouTube no disponible ({ex})")
        threading.Thread(target=self._rutina_diaria, daemon=True, name="nexus-dia").start()
        threading.Thread(target=self._vigilar_buzon, daemon=True, name="nexus-buzon").start()

    # ---------------------------------------------------------------- estado
    def _leer(self) -> dict:
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"paso": "nombre", "hechos": [], "id": {}, "cuentas": {}, "videos": [], "pregunta": None}

    def _diario(self, tipo: str, texto: str, **extra) -> None:
        """Todo lo que pasa con el personaje, en orden: se ve en la página de Nexus."""
        try:
            with open(NX / "diario.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tipo": tipo, "texto": texto[:2000],
                                    **extra}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _leer_diario(self, n: int = 400) -> list[dict]:
        try:
            lineas = (NX / "diario.jsonl").read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
        out = []
        for l in lineas:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
        return out

    def _guardar(self) -> None:
        tmp = ESTADO.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.e, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ESTADO)
        if self.ui:
            self.ui.enviar(tipo="nexus", paso=TITULOS.get(self.e["paso"], ""), hechos=len(self.e["hechos"]),
                           total=len(ORDEN))

    def _preguntar(self, clave: str, texto: str, **datos) -> Respuesta:
        self.e["pregunta"] = {"clave": clave, "t": time.time(), "texto": texto, **datos}
        self._guardar()
        self._diario("athena", texto)
        if not self.es_telegram():                      # que llegue también al móvil, aunque no esté delante
            try:
                self.avisar("Nexus pregunta: " + texto)
            except Exception:
                pass
        return Respuesta(texto)

    def recordar(self) -> None:
        """Al arrancar el asistente: si hay una pregunta sin contestar (de menos de un día), la repite en voz alta."""
        q = self.e.get("pregunta") or {}
        if q.get("texto") and time.time() - q.get("t", 0) < 86400 and not q.get("recordada"):
            q["t"], q["recordada"] = time.time(), True   # una vez: si no contestas, no se repite en cada arranque
            self._guardar()
            self.decir("Del proyecto Nexus tengo una pregunta para ti. " + q["texto"])

    def preguntar_ahora(self) -> None:
        """Lanza (en voz y por Telegram) la pregunta del paso en que va el proyecto."""
        r = self.continuar()
        if r and r.texto:
            self.decir(r.texto)

    def espera_respuesta(self) -> bool:
        p = self.e.get("pregunta")
        return bool(p) and time.time() - p["t"] < 30 * 60 and not self.ocupado

    def _hecho(self, paso: str) -> None:
        if paso not in self.e["hechos"]:
            self.e["hechos"].append(paso)
        siguiente = next((p for p in ORDEN if p not in self.e["hechos"]), "rutina")
        self.e["paso"] = siguiente
        self.e["pregunta"] = None
        self._guardar()

    def _ia(self, sistema: str, usuario: str, json_: bool = True, max_tokens: int = 1500):
        t = self.cerebro.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                              formato_json=json_, max_tokens=max_tokens, temperatura=0.8, timeout=90)
        return _json_de(t) if json_ else t.strip()

    def _en_hilo(self, nombre: str, trabajo: Callable[[], str]) -> None:
        def h():
            self.ocupado = nombre
            try:
                txt = trabajo()
            except Exception as ex:
                self.log(f"nexus: {nombre}: {ex!r}")
                txt = f"No he podido terminar ({nombre}): {ex}. Dime «sigue con nexus» para reintentarlo."
            finally:
                self.ocupado = ""
            if txt:
                self._diario("athena", txt)
                (self.avisar if self.es_telegram() else self.decir)(txt)
        threading.Thread(target=h, daemon=True, name=f"nexus-{nombre}").start()

    # ---------------------------------------------------------------- atajos sobre Asuka (sin decir «nexus»)
    def sobre_asuka(self, t: str) -> Respuesta | None:
        """«abre el instagram de asuka», «cuál es su usuario de twitch», «abre nexus», «pon el último vídeo»."""
        web = next((v for k, v in ALIAS_WEB.items() if re.search(rf"\b{k}\b", t)), None)
        if web and re.search(r"\bcredit\w*", t) and re.search(r"\b(sin|no|acab|agot|gast|queda)\w*", t):
            return Respuesta(self.sin_credito(web))        # «sin crédito en capcut», también sin decir «nexus»
        alias_red = {"tiktok": "tiktok", "tik tok": "tiktok", "instagram": "instagram", "insta": "instagram",
                     "youtube": "youtube", "x": "x", "twitter": "x", "twitch": "twitch", "pinterest": "pinterest",
                     "facebook": "facebook", "face": "facebook"}
        red = next((v for k, v in alias_red.items() if re.search(rf"\b{k}\b", t)), None)
        cuentas = self.e.get("cuentas", {})
        abrir = re.search(r"\b(abre\w*|abrir|ensena\w*|muestra\w*|pon\w*|ve a|entra\w*|llevame)\b", t)
        if "asuka" in t and red and (abrir or re.match(r"(?:el |la )?(?:pagina|perfil|cuenta|web)\b", t)):
            c = cuentas.get(red) or {}
            if not c.get("usuario"):
                return Respuesta(f"Aún no tengo apuntado el usuario de {REDES[red]['nombre']} de Asuka.")
            abrir_web(REDES[red]["perfil"].format(u=c["usuario"]))
            return Respuesta(f"Te abro el {REDES[red]['nombre']} de Asuka.")
        if ("asuka" in t or "nexus" in t) and re.search(r"\b(cual|dime|como se llama|que)\b.*\b(usuario|cuenta|perfil|nombre|arroba|correo|"
                                      r"gmail|email|enlace|link)\b", t):
            if re.search(r"\b(correo|gmail|email)\b", t):
                correo = self.e["id"].get("correo") or "(sin apuntar)"
                return Respuesta(f"Su correo es {correo}.")
            if red:
                c = cuentas.get(red) or {}
                if not c.get("usuario"):
                    return Respuesta(f"Aún no tengo apuntado su usuario de {REDES[red]['nombre']}.")
                return Respuesta(f"En {REDES[red]['nombre']} es {c['usuario']}: "
                                 f"{REDES[red]['perfil'].format(u=c['usuario'])}")
            lista = [f"{REDES[k]['nombre']}: {v['usuario']}" for k, v in cuentas.items() if v.get("usuario") and k in REDES]
            return Respuesta("Sus cuentas: " + "; ".join(lista) + "." if lista else "Aún no tengo sus cuentas apuntadas.")
        if abrir and re.search(r"\b(nexus|panel de asuka|pagina de asuka|asuka)\b", t) and not red and \
                re.fullmatch(r"(?:\w+ ){0,3}(?:el |la )?(?:panel|pagina|web)?\s*(?:de |del )?(?:proyecto )?(?:nexus|asuka)"
                             r"(?: de asuka)?", t):
            abrir_web("http://127.0.0.1:8765/nexus")
            return Respuesta("Te abro la página de Asuka.")
        if "asuka" in t and abrir and re.search(r"\b(todas|todos)\b.*\b(redes|perfiles|cuentas)\b", t):
            urls = self.urls_perfiles()
            for u in urls:
                abrir_web(u)
            return Respuesta(f"Te abro sus {len(urls)} perfiles." if urls else "Aún no tengo sus cuentas apuntadas.")
        if "asuka" in t and abrir and re.search(r"\b(gmail|correo|email)\b", t):
            abrir_web("https://mail.google.com/mail/u/?authuser=" + (self.e["id"].get("correo") or
                                                                     "(sin apuntar)"))
            return Respuesta("Te abro el Gmail de Asuka.")
        # sus vídeos: reproducirlos en la pantalla o mandarlos por Telegram
        mandar = re.search(r"\b(manda\w*|envia\w*|pasa\w*)\b", t)
        poner = re.search(r"\b(reproduce\w*|pon\w*|ensena\w*|muestra\w*|abre\w*|ver|veamos)\b", t)
        if (mandar or poner) and re.search(r"\bvideos?\b", t) and self.e.get("videos") and \
                re.search(r"\b(ultimo|ultimos|creado|creados|hecho|has hecho|de asuka|que has)\b|\bvideo (de|del|sobre) ", t):
            vids = [v for v in self.e["videos"] if Path(v.get("ruta", "")).exists()]
            m = re.search(r"\bvideo (?:de|del|sobre) (?:la |el |los |las )?(.+)$", t)
            if m and not re.match(r"(asuka|ultimo|hoy)\b", m.group(1)):
                palabras = [w for w in m.group(1).split() if len(w) > 2 and w not in ("asuka", "telegram", "pantalla")]
                vids = [v for v in vids if all(w in normalizar(v["titulo"]) for w in palabras)] or []
                if not vids:
                    return Respuesta(f"No encuentro ningún vídeo suyo de «{m.group(1)}».")
            if not vids:
                return Respuesta("No tengo vídeos hechos todavía.")
            n = 3 if re.search(r"\bultimos\b", t) else 1
            elegidos = vids[-n:]
            if mandar:
                enviados = [v["titulo"] for v in elegidos if self.enviar_documento(v["ruta"], v["titulo"]) is not False]
                return Respuesta(("Te mando por Telegram: " + ", ".join(f"«{x}»" for x in enviados) + ".") if enviados
                                 else "No he podido mandártelo por Telegram (¿pesa más de 50 MB?).")
            from herramientas import lanzar
            lanzar(["xdg-open", elegidos[-1]["ruta"]])
            return Respuesta(f"Te pongo «{elegidos[-1]['titulo']}» en la pantalla.")
        return None

    # ---------------------------------------------------------------- órdenes
    def manejar(self, texto: str) -> Respuesta | None:
        t = normalizar(texto).strip(" .?¿!¡")
        t = re.sub(r"\b(azuka|azucar|azuca|asuca|azzuka|askua|asuk|asuka|azuk|asucka|asuko)\b", "asuka", t)   # cómo lo oye el reconocedor
        t = re.sub(r"\b(nexo|next|nexos|necsus|nexuz)\b", "nexus", t)
        t = re.sub(r"\b(edra|hedra|hedda|edra video|hedra video)\b", "hedra", t)
        r = self._entrada_directa(texto, t)
        if r:
            self._diario("tu", texto[:500])
            return r
        r = self.sobre_asuka(t)
        if r:
            self._diario("tu", texto)
            return r
        if not re.search(r"\bnexus\b", t):
            return None
        self._diario("tu", texto)
        if re.search(r"\b(movil|telefono|celular|fuera de casa)\b", t) and not re.search(r"\b(video|foto)\b", t):
            import pasarela_movil
            if re.search(r"\b(cambia|nueva|rota|renueva)\w*\b.*\bllave\b", t):
                pasarela_movil.rotar()
            en = pasarela_movil.enlaces()
            msg = ("Panel de Asuka en el móvil. Ábrelo con este enlace (es tu llave: no lo compartas; luego "
                   "«Añadir a pantalla de inicio» y queda como una app):\n" + en["casa"]
                   + (f"\n\nFuera de casa (Tailscale): {en['fuera']}" if en.get("fuera") else
                      "\n\nFunciona con el móvil en el wifi de casa. Para usarlo fuera, instala Tailscale "
                      "(te digo cómo con «nexus, tailscale»)."))
            if self.es_telegram():
                return Respuesta(msg)
            self.avisar(msg)
            return Respuesta("Te he mandado por Telegram el enlace del panel para el móvil.")
        if re.search(r"\btailscale\b", t):
            return Respuesta("Para ver el panel fuera de casa: 1) en el portátil, en una terminal: "
                             "curl -fsSL https://tailscale.com/install.sh | sh  y luego  sudo tailscale up  (te da un "
                             "enlace para entrar con tu cuenta de Google); 2) en el móvil, la app Tailscale con la misma "
                             "cuenta; 3) dime «nexus en el móvil» y te mando también el enlace de fuera.")
        if re.search(r"\b(abre\w*|abrir|ensena\w*|muestra\w*|pon\w*)\b.*\b(panel|pagina|web)\b", t):
            abrir_web("http://127.0.0.1:8765/nexus")
            return Respuesta("Te abro la página de Asuka.")
        r = self._ordenes_material(t)
        if r:
            return r
        if re.search(r"\b(crea\w*|haz|hacer|abre)\b.*\b(cuentas|perfiles)\b", t):
            for k, c in list(self.e["cuentas"].items()):    # las «pendiente» se vuelven a ofrecer
                if c.get("estado") != "creada":
                    del self.e["cuentas"][k]
            return self._paso_cuentas()
        if re.search(r"\b(ideas?|otro video|nuevo video|haz (un|otro) video)\b", t):
            if "primer_video" not in self.e["hechos"] and self.e["paso"] != "primer_video":
                return Respuesta("Antes de los vídeos tenemos que terminar el personaje. " + self.continuar().texto)
            self.e["paso"] = "primer_video"
            self.e["pregunta"] = None
            return self._paso_video()
        m = re.search(r"\bya tengo (?:la )?(?:cuenta )?(?:de |del |en )?(tiktok|instagram|youtube|x|twitter|twitch|pinterest)"
                      r"(?:.*?@?([a-z0-9_.]{3,30}))?$", t)
        if m:
            k = "x" if m.group(1) == "twitter" else m.group(1)
            u = m.group(2) if m.group(2) and m.group(2) not in ("usuario", "es", "con") else self.e["id"].get("usuario", "")
            self.e["cuentas"][k] = {"estado": "creada", "usuario": u, "fecha": time.strftime("%Y-%m-%d")}
            self._guardar()
            return Respuesta(f"Apuntada la cuenta de {REDES[k]['nombre']} (@{u}).")
        m = re.search(r"\b(vuelve|volver|ir|ve)\b.*\bpaso (?:de |del |de la |de las )?(\w+)", t)
        if m:
            destino = next((p for p in ORDEN if m.group(2)[:4] in normalizar(TITULOS[p]) or m.group(2)[:4] in p), None)
            if destino:
                self.e["hechos"] = [h for h in self.e["hechos"] if h != destino]
                self.e["paso"], self.e["pregunta"] = destino, None
                self._guardar()
                return self.continuar()
        if re.search(r"\b(como va|en que paso|estado|progreso|que falta)\b", t):
            return Respuesta(self._resumen())
        return self.continuar()

    # ---------------------------------------------------------------- lo que entra sin decir «nexus»
    RE_PROMPT_FOTO = re.compile(r"\b(llevo|estoy (sentada|de pie|tumbada|apoyada|caminando|paseando|en)|mi (cabello|pelo)|"
                                r"mis gafas|voy vestida|posando|aparezco)\b")
    RE_ESCENA_FOTO = re.compile(r"\b(foto\w*|luz|escena|fondo|plano|hiperrealista|realista|iluminacion|camara|atardecer|"
                                r"amanecer|calidad|estilo|retrato|colores?)\b")

    @staticmethod
    def _partir_prompts(texto: str) -> list[str]:
        """Una lista numerada («1. … 2. …») o separada por líneas en blanco → un prompt por foto."""
        cuerpo = re.sub(r"(?is)^\s*(nexus[,:]?\s*)?(fotos?|imagen(es)?|prompts?)\s+(de|para)\s+(asuka|azuka)\w*\s*[:,.-]?\s*", "", texto)
        partes = re.split(r"(?m)^\s*(?:\d{1,2}\s*[.)\-:]?\s*(?=[A-ZÁÉÍÓÚÑ¿¡])|[-•*]\s+)", cuerpo)   # «2 Crea…», «3Foto…»
        partes = [x.strip() for x in partes if len(x.strip()) > 25]
        if len(partes) <= 1 and re.search(r"(^|\s)2[.)]\s", cuerpo):           # «1. … 2. …» en la misma línea
            partes = [x.strip() for x in re.split(r"(?:^|\s)\d{1,2}[.)]\s+", cuerpo) if len(x.strip()) > 25]
        if len(partes) <= 1:
            bloques = [x.strip() for x in re.split(r"\n\s*\n", cuerpo) if len(x.strip()) > 25]
            # varias escenas separadas solo si cada bloque es una escena entera (lleva ropa o lugar)
            if len(bloques) > 2 and all(re.search(r"(?i)\b(llevo|estoy|vestid|en (la|el|una|un))\b", b) for b in bloques):
                partes = bloques
            else:
                partes = [cuerpo.strip()]
        return [x[:1500] for x in partes][:20]

    def _limpiar_prompts(self) -> int:
        """Fuera los repetidos y los trozos de otro (Telegram parte los mensajes largos en varios)."""
        cola = self.e.get("prompts_fotos", [])
        norm = [re.sub(r"\W+", " ", normalizar(p["es"])).strip() for p in cola]
        quedan = [p for i, p in enumerate(cola)
                  if not any(j != i and norm[i] in norm[j] and (len(norm[i]) < len(norm[j]) or j < i) for j in range(len(cola)))]
        quitados = len(cola) - len(quedan)
        self.e["prompts_fotos"] = quedan
        return quitados

    def _entrada_directa(self, texto: str, t: str) -> Respuesta | None:
        # prompts de fotos de Asuka: «fotos de asuka: 1. … 2. …» o una escena descrita en primera persona
        explicito = re.match(r"^(nexus,? )?(fotos?|imagen(es)?|prompts?) (de|para) asuka\b", t)
        if explicito or (len(t) > 90 and self.RE_PROMPT_FOTO.search(t) and self.RE_ESCENA_FOTO.search(t)
                         and not re.search(r"\b(correo|email|whatsapp|mensaje para)\b", t)):
            prompts = self._partir_prompts(texto)
            cola = self.e.setdefault("prompts_fotos", [])
            for x in prompts:
                cola.append({"es": x, "t": time.strftime("%Y-%m-%d %H:%M")})
            self._limpiar_prompts()
            self._guardar()
            self._en_hilo("fotos", lambda: self.crear_fotos(min(3, len(prompts))))
            return Respuesta(f"Apuntada{'s' if len(prompts) > 1 else ''} {len(prompts)} foto{'s' if len(prompts) > 1 else ''} "
                             f"de Asuka (con su cara, a partir de sus fotos). Empiezo ya; con el cupo gratis salen unas 3-4 "
                             f"al día, así que {'van saliendo en los próximos días' if len(prompts) > 3 else 'en un rato las tienes'}"
                             ". Te las mando por Telegram y entran en las publicaciones.")
        if re.search(r"\b(gemini|nano ?banana)\b", t) and re.search(r"\b(pedidas|cola|prompts?|las fotos)\b", t):
            return Respuesta(self.pedidas_a_gemini(3))
        if re.search(r"\b(esa|esta|eso) no es asuka\b", t):
            return Respuesta("Tienes razón: esa la pintó el estudio genérico, sin su cara. Para fotos de Asuka mándame la "
                             "descripción así: «fotos de asuka:» y los prompts numerados (1., 2., …), o descríbela en "
                             "primera persona («llevo…, estoy en…»): la hago a partir de sus fotos y compruebo que es ella.")
        # Hedra (el reconocedor oye «Edra»): el vídeo hablando con su voz, flujo asistido
        if re.search(r"\bhedra\b", t) and re.search(r"\b(video|crea\w*|haz|hacer|abre|usa|utiliza\w*|empieza|comienza)\b", t):
            self._en_hilo("hedra", lambda: self.pedir_habla_web("hedra"))
            return Respuesta("Preparo el vídeo de Asuka hablando en Hedra: te mando por Telegram su foto y el audio con su "
                             "voz y te abro Hedra. Allí: sube la foto, sube el audio, pulsa Generar y me reenvías el vídeo "
                             "con la palabra «clip».")
        # «mándame las fotos rojas / verdes / ámbar de asuka»
        m = re.search(r"\b(rojas?|rojo|verdes?|ambar|amarillas?|naranjas?)\b", t)
        if m and re.search(r"\b(manda|envia|pasa|ensena)\w*\b", t) and re.search(r"\b(fotos?|imagenes?)\b", t) \
                and ("asuka" in t or "nexus" in t):
            apta = {"r": "no", "v": "publica"}.get(m.group(1)[0], "revisar")
            fotos = [r for r in self._indice(REF) if r.get("apta") == apta and (REF / r["archivo"]).exists()]
            if not fotos:
                return Respuesta("No hay fotos de ese color.")
            def _mandar():
                for r in fotos[-12:]:
                    self.enviar_foto(str(REF / r["archivo"]), f"{r['archivo']} · {r.get('escena', '')}")
            threading.Thread(target=_mandar, daemon=True, name="nexus-fotos-tg").start()
            nombre = {"no": "rojas", "publica": "verdes", "revisar": "ámbar"}[apta]
            return Respuesta(f"Te mando por Telegram las {min(12, len(fotos))} fotos {nombre}"
                             + (f" más recientes (hay {len(fotos)})" if len(fotos) > 12 else "") + ".")
        return None

    # ---------------------------------------------------------------- material propio (fotos y clips)
    @staticmethod
    def _indice(carpeta: Path) -> list[dict]:
        try:
            return json.loads((carpeta / "indice.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    @staticmethod
    def _guardar_indice(carpeta: Path, ind: list[dict]) -> None:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "indice.json").write_text(json.dumps(ind, ensure_ascii=False, indent=1), encoding="utf-8")

    def _material(self, apta: tuple[str, ...] = ("publica",)) -> tuple[list[dict], list[dict]]:
        fotos = [dict(x, ruta=REF / x["archivo"]) for x in self._indice(REF) if x.get("apta") in apta
                 and (REF / x["archivo"]).exists()]
        clips = [dict(x, ruta=CLIPS / x["archivo"]) for x in self._indice(CLIPS) if x.get("apta") in apta
                 and (CLIPS / x["archivo"]).exists()]
        return fotos, clips

    # ---------------------------------------------------------------- webs con crédito (CapCut, PixVerse, Kling…)
    def _web_con_credito(self, preferida: str | None = None, tipo: str = "video") -> str | None:
        import datetime
        hoy = datetime.date.today().isoformat()
        estado = self.e.get("creditos_webs", {})
        orden = ([preferida] if preferida else []) + [w for w in WEBS_CLIP if w != preferida
                                                       and TIPO_WEB.get(w, "video") == tipo]
        return next((w for w in orden if estado.get(w, {}).get("hasta", "") <= hoy
                     and not estado.get(w, {}).get("nunca")), None)

    def sin_credito(self, web: str) -> str:
        """«nexus, sin crédito en capcut»: no se vuelve a pedir hasta que se recargue (mañana, el mes que viene o nunca)."""
        import datetime
        nombre, _, recarga = WEBS_CLIP[web]
        d = datetime.date.today()
        hasta = (d + datetime.timedelta(days=1) if recarga == "dia" else
                 d + datetime.timedelta(days=7 - d.weekday()) if recarga == "semana" else
                 (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) if recarga == "mes" else d)
        self.e.setdefault("creditos_webs", {})[web] = {"hasta": hasta.isoformat(), "nunca": recarga == "nunca"}
        if (self.e.get("clip_pedido") or {}).get("web") == nombre:
            self.e["clip_pedido"] = None
        self._guardar()
        cuando = {"dia": "mañana", "semana": "el lunes", "mes": "el mes que viene",
                  "nunca": "no vuelve (eran créditos de bienvenida)"}[recarga]
        otra = self._web_con_credito(tipo=TIPO_WEB.get(web, "video"))
        if TIPO_WEB.get(web) == "habla":
            return f"Apuntado: {nombre} sin crédito; vuelvo a usarla {cuando}."
        return (f"Apuntado: {nombre} sin crédito; {('vuelvo a usarla ' + cuando) if recarga != 'nunca' else cuando}. "
                + (f"Seguimos con {WEBS_CLIP[otra][0]}: " + self.pedir_clip_web(otra) if otra else
                   "No queda ninguna web con crédito hoy; mañana se recargan las diarias."))

    def resumen_creditos(self) -> str:
        import datetime
        hoy = datetime.date.today().isoformat()
        est = self.e.get("creditos_webs", {})
        con = [WEBS_CLIP[w][0] for w in WEBS_CLIP if est.get(w, {}).get("hasta", "") <= hoy and not est.get(w, {}).get("nunca")]
        sin = [f"{WEBS_CLIP[w][0]} (hasta {est[w]['hasta'][8:]}/{est[w]['hasta'][5:7]})" if not est[w].get("nunca")
               else f"{WEBS_CLIP[w][0]} (gastada)" for w in WEBS_CLIP if w in est and w not in
               [k for k in WEBS_CLIP if WEBS_CLIP[k][0] in con]]
        return ("Con crédito: " + (", ".join(con) or "ninguna") + ". " + ("Sin crédito: " + ", ".join(sin) + "." if sin else "")
                + " Cuando una se gaste, dime «nexus, sin crédito en <web>» y paso a la siguiente.")

    def pedir_clip_web(self, web: str | None = None) -> str:
        """Prepara un clip para una web con crédito: elige una foto suya buena, escribe la instrucción en inglés, abre la
        web y le manda a la persona por Telegram la foto y el texto para pegar. Lo que descargue lo recoge Athena."""
        if web and TIPO_WEB.get(web) == "habla":
            return self.pedir_habla_web(web)
        if web and TIPO_WEB.get(web) == "foto":
            return self.pedir_foto_web(web)
        web = self._web_con_credito(web)
        if not web:
            return "Hoy no queda crédito en ninguna web de vídeo; mañana se recargan las diarias."
        nombre, url, _ = WEBS_CLIP[web]
        fotos, _ = self._material()
        if not fotos:
            return "No tengo fotos aprobadas del personaje para animar."
        usadas = {c.get("foto") for c in self._indice(CLIPS)} | set(self.e.get("fotos_animadas", []))
        buenas = [x for x in fotos if x["archivo"] not in usadas and self._luz(x["ruta"]) >= 90] or fotos
        f = random.choice(buenas)
        b = self.e["id"].get("biblia", {})
        estilo = random.choice(self.ESTILOS_CLIP)
        idea = self._ia("Eres director de vídeos cortos con IA. Devuelve SOLO JSON.",
                        f"Escribe la instrucción (en inglés, máx. 60 palabras) para animar 5 segundos esta foto del "
                        f"personaje {self.e['id'].get('nombre', '')} ({b.get('resumen', BASE)}). La foto: {f['escena']}. "
                        f"Movimiento natural en esta línea: «{estilo}»; cámara cinematográfica, misma cara, nada sexual. "
                        "JSON: {\"prompt\": \"…\"}")
        self.e["clip_pedido"] = {"t": time.time(), "web": nombre, "clave": web, "escena": f["escena"], "foto": f["archivo"]}
        self._guardar()
        self.enviar_foto(str(f["ruta"]), f"Para {nombre} ({url}):\n1. Sube esta foto (imagen a vídeo).\n2. Pega esto:\n\n"
                         f"{idea.get('prompt', estilo)}\n\n3. Genera y descarga. Mándamelo por aquí con la palabra «clip», "
                         "o déjalo en Descargas del portátil.\nSi no te queda crédito: «nexus, sin crédito en " + web + "».")
        if not self.es_telegram():
            abrir_web(url)
        return (f"Te abro {nombre} y te mando por Telegram la foto y la instrucción para pegar. Cuando lo tengas, "
                "mándamelo con la palabra «clip» (o déjalo en Descargas y dime «nexus, ya tengo el clip»).")

    def _foto_de_cara(self) -> dict | None:
        fotos, _ = self._material()
        caras = [f for f in fotos if re.search(r"face|portrait|selfie|closeup|smil", f.get("escena", ""))
                 and self._luz(f["ruta"]) >= 90]
        return random.choice(caras or fotos) if fotos else None

    @staticmethod
    def _sin_peques(texto: str) -> str:
        """Quita las frases que hablan de sus perras (para vídeos en los que no salen)."""
        frases = re.split(r"(?<=[.!?…])\s+", texto)
        quedan = [f for f in frases if not re.search(r"(?i)\b(peques|perr[ao]s?|jazm[ií]n|leia)\b", f)]
        return " ".join(quedan) or texto

    def pedir_habla_web(self, web: str = "hedra") -> str:
        """Hedra / HeyGen / Vidnoz: ella hablando a cámara con SU voz. Athena manda la foto y su voz (mp3) por Telegram."""
        web = self._web_con_credito(web, "habla")
        if not web:
            return "Ninguna web de «foto que habla» tiene crédito ahora; en cuanto se recarguen te lo vuelvo a preparar."
        voz, f = self._voz_asuka(), self._foto_de_cara()
        if not (voz and f):
            return "Me falta su voz o una foto suya de cara."
        b = self.e["id"].get("biblia", {})
        d = self._ia("Devuelve SOLO JSON.", f"{self.e['id'].get('nombre')} ({b.get('resumen', BASE)}) habla a cámara 6-8 "
                     "segundos a sus seguidores (un saludo, una pregunta, algo de su día). No hables de sus perras ni de juegos o "
                     "cosas concretas que no se ven. JSON: {\"frase\": \"15-22 palabras, español de España coloquial, sin "
                     "mencionar la IA\"}", max_tokens=200)
        frase = self._humano(d.get("frase", ""), "guion") or "¡Hola, peña! ¿Qué tal vuestro día? El mío, entre partidas y café. Contadme algo."
        frase = self._sin_peques(frase)                    # en la foto no salen sus perras: no se nombran
        corta = ""                                         # 6-8 s: como mucho ~24 palabras, sin cortar frases
        for trozo in re.split(r"(?<=[.!?…])\s+", frase):
            if corta and len((corta + " " + trozo).split()) > 24:
                break
            corta = (corta + " " + trozo).strip()
        frase = corta or " ".join(frase.split()[:22])
        carpeta = NX / "videos" / f"{time.strftime('%Y%m%d-%H%M%S')}-hedra"
        carpeta.mkdir(parents=True, exist_ok=True)
        voz(frase, carpeta / "voz.wav")
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(carpeta / "voz.wav"), "-b:a", "160k",
                        str(carpeta / "voz_asuka.mp3")], check=True)
        nombre, url, _ = WEBS_CLIP[web]
        self.e["clip_pedido"] = {"t": time.time(), "web": nombre, "clave": web, "escena": f"ella hablando a cámara: «{frase}»",
                                 "foto": f["archivo"], "frase": frase}
        self._guardar()
        paso1 = {"hedra": "Crea un vídeo (Character-3) y sube esta foto como personaje.",
                 "heygen": "Crea un «Photo Avatar» con esta foto (o «Avatar IV»).",
                 "vidnoz": "Abre «Talking Photo» y sube esta foto."}.get(web, "Sube esta foto como personaje.")
        self.enviar_foto(str(f["ruta"]), f"Para {nombre} ({url}) · vídeo de ella HABLANDO con su voz:\n1. {paso1}\n"
                         "2. En audio, elige «subir audio» y sube el mp3 que te mando ahora (no uses sus voces).\n"
                         "3. Formato vertical 9:16. Genera y descarga.\n4. Mándamelo por aquí con la palabra «clip».\n"
                         f"Si no te queda crédito: «sin crédito en {web}».")
        self.enviar_documento(str(carpeta / "voz_asuka.mp3"), f"Su voz: «{frase}»")
        if not self.es_telegram():
            abrir_web(url)
        return f"Te mando por Telegram su foto y su voz («{frase}») para hacerla hablar en Hedra."

    def pedir_foto_web(self, web: str = "nanobanana") -> str:
        """Nano Banana (Gemini): una foto nueva suya con la misma cara. Athena manda la foto base y el texto."""
        f = self._foto_de_cara()
        if not f:
            return "No tengo fotos suyas de las que partir."
        b = self.e["id"].get("biblia", {})
        d = self._ia("Devuelve SOLO JSON.", f"Idea de foto nueva para {self.e['id'].get('nombre')} ({b.get('resumen', BASE)}), "
                     "en Sevilla o en su vida de gamer/otaku/gym, con buena luz de día. Escribe la instrucción para un editor "
                     "de fotos con IA, en español, empezando por «Mantén exactamente a la misma mujer de la foto (misma cara, "
                     "gafas y pelo rojo rizado)». JSON: {\"instruccion\": \"…\", \"escena\": \"5-8 palabras en inglés\"}",
                     max_tokens=300)
        nombre, url, _ = WEBS_CLIP[web]
        self.e["foto_pedida"] = {"t": time.time(), "web": nombre, "base": f["archivo"], "escena": d.get("escena", "new photo")}
        self._guardar()
        self.enviar_foto(str(f["ruta"]), f"Para {nombre} ({url}): sube esta foto y escribe:\n\n{d.get('instruccion', '')}"
                         "\n\nDescarga la foto y mándamela por aquí con la palabra «foto nueva».")
        if not self.es_telegram():
            abrir_web(url)
        return f"Te mando por Telegram la foto y el texto para {nombre}."

    def pedidas_a_gemini(self, n: int = 3) -> str:
        """Cuando el cupo gratis no da para más: las fotos que pediste, listas para hacerlas en el móvil con Gemini
        (Nano Banana), con su foto de cara y el texto. Me las reenvías con «foto nueva» y entran como las demás."""
        cola = self.e.get("prompts_fotos", [])
        if not cola:
            return "No hay fotos pedidas en cola."
        f = self._foto_de_cara()
        if not f:
            return "No tengo fotos suyas de las que partir."
        enviadas = cola[:n]
        self.e["prompts_fotos"] = cola[n:]
        self.e["foto_pedida"] = {"t": time.time(), "web": "Gemini", "base": f["archivo"], "escena": "requested photo"}
        self._guardar()
        self.enviar_foto(str(f["ruta"]), "Foto de referencia de Asuka para Gemini (Nano Banana). Ábrela en la app "
                         "Gemini, adjunta esta foto y pega cada texto de los siguientes mensajes; luego me reenvías aquí "
                         "cada resultado con «foto nueva».")
        for i, p in enumerate(enviadas, 1):
            self.avisar(f"Foto {i}/{len(enviadas)} para Gemini:\n\nMantén exactamente a la misma mujer de la foto adjunta "
                        f"(misma cara, gafas y pelo rojo largo). {p['es'][:3200]}")
        return (f"Te he mandado a Telegram {len(enviadas)} de las fotos pedidas, con su foto de referencia, para hacerlas "
                f"en Gemini desde el móvil. Quedan {len(self.e['prompts_fotos'])} en cola para el cupo gratis.")

    def guardar_foto_recibida(self, ruta: Path, pie: str) -> str:
        """«foto nueva» por Telegram: si se la reconoce y tiene luz, a sus fotos (verde)."""
        from nexus_telegram import guardar_foto
        p = self.e.get("foto_pedida") or {}
        ind = self._indice(REF)
        n = max([int(m.group(1)) for x in ind for m in [re.match(r"ref(\d+)", x["archivo"])] if m] + [0]) + 1
        destino = REF / f"ref{n}.jpg"
        guardar_foto(ruta, destino)
        base = REF / p["base"] if p.get("base") and (REF / p["base"]).exists() else None
        motivo = self._foto_mala(base, destino) if base else ""
        if motivo:
            destino.unlink(missing_ok=True)
            return f"Esa foto no la guardo: {motivo}."
        ind.append({"archivo": destino.name, "escena": p.get("escena", "new photo"), "apta": "publica",
                    "origen": f"foto {p.get('web', 'IA')}", "fecha": time.strftime("%Y-%m-%d")})
        self._guardar_indice(REF, ind)
        self.e["foto_pedida"] = None
        self._guardar()
        self._diario("material", f"Foto nueva de {p.get('web', 'IA')}", ruta=str(destino))
        return f"Foto nueva guardada en sus fotos ({destino.name}); la usaré en las publicaciones y los clips."

    def guardar_clip_recibido(self, ruta: Path, pie: str) -> str:
        """Un vídeo que llega por Telegram o el buzón con «clip»: a sus clips (no se publica tal cual)."""
        import shutil
        p = self.e.get("clip_pedido") or {}
        t = normalizar(pie or "")
        web = next((v for k, v in ALIAS_WEB.items() if re.search(rf"\b{k}\b", t)), p.get("clave"))
        nombre = WEBS_CLIP.get(web, (p.get("web") or "web",))[0]
        CLIPS.mkdir(parents=True, exist_ok=True)
        ind = self._indice(CLIPS)
        destino = CLIPS / f"web-{web or 'clip'}-{time.strftime('%Y%m%d-%H%M%S')}{ruta.suffix.lower()}"
        shutil.copy(ruta, destino)
        sin_marca = bool(re.search(r"\bsin marca\b", t))
        ind.insert(0, dict({"archivo": destino.name, "escena": p.get("escena") or "clip de ella con movimiento",
                            "apta": "publica", "origen": f"movimiento {nombre}" + (" (sin marca)" if sin_marca else ""),
                            "foto": p.get("foto", ""), "fecha": time.strftime("%Y-%m-%d")},
                           **({"frase": p["frase"]} if p.get("frase") else {})))
        self._guardar_indice(CLIPS, ind)
        self.e["clip_pedido"] = None
        self._guardar()
        self._diario("material", f"Clip de {nombre} recibido", ruta=str(destino))
        threading.Thread(target=lambda: self.avisar(self.videos_movimiento(maximo=1) or "Clip guardado."),
                         daemon=True, name="nexus-clip-web").start()
        return (f"Clip de {nombre} guardado. Le pongo su frase y su voz y lo meto en la cola de la próxima noche libre"
                + ("" if sin_marca else " (si trae marca de agua, va entero sobre fondo difuminado)") + ".")

    def _recoger_descargas(self) -> list[str]:
        """Los clips que la persona ha bajado de DeeVid, OpenGen o Viggle desde que se los pedí pasan a clips/."""
        p = self.e.get("clip_pedido") or {}
        if not p:
            return []
        nuevos, ind = [], self._indice(CLIPS)
        for d in DESCARGAS:
            for f in sorted(d.glob("*.mp4")) if d.exists() else []:
                from nexus_xbox import PATRON as XBOX
                if f.stat().st_mtime < p.get("t", 0) - 60 or f.stat().st_size < 50_000 or XBOX.search(f.name):
                    continue                                   # (los de Xbox son tuyos, no de DeeVid)
                CLIPS.mkdir(parents=True, exist_ok=True)
                nombre = f"clip{len(ind) + 1:02d}.mp4"
                import shutil
                shutil.move(str(f), CLIPS / nombre)
                ind.insert(0, {"archivo": nombre, "escena": p.get("escena", ""), "apta": "publica",
                               "origen": f"movimiento {p.get('web', '')}", "foto": p.get("foto", ""),
                               "fecha": time.strftime("%Y-%m-%d")})
                nuevos.append(nombre)
                self._diario("material", f"Clip nuevo de {p.get('web', '')}", ruta=str(CLIPS / nombre))
        if nuevos:
            self._guardar_indice(CLIPS, ind)
            self.e["clip_pedido"] = None
            self._guardar()
        return nuevos

    def _fuente(self, usadas: set, animar: bool = True):
        """Para cada escena del guion: el clip o la foto propia que mejor encaje con lo que se ve. La categoría de la
        foto (verde, ámbar, roja) se sortea con la mezcla elegida; si en esa no hay nada libre, se prueba en las otras."""
        _, clips = self._material()
        todas, _ = self._material(("publica", "revisar", "no"))
        mezcla = self.e.get("mezcla") or MEZCLA

        def puntos(x: dict, visual: str) -> int:
            v = set(re.findall(r"[a-z]+", normalizar(visual)))
            return len(v & set(normalizar(x.get("escena", "")).split()))

        PERRAS = {"dog", "dogs", "jazmin", "leia", "perras", "perra", "pets", "pet"}

        entorno = [dict(x, ruta=ENTORNO / x["archivo"]) for x in self._indice(ENTORNO)
                   if x.get("apta") in ("publica", "revisar") and (ENTORNO / x["archivo"]).exists()]

        def elegir(visual_en: str, i: int):
            if i > 0 and entorno:                             # «sus perras», «su cuarto»: la foto de verdad
                libres_e = [x for x in entorno if x["archivo"] not in usadas]
                mejor_e = max(libres_e, key=lambda x: puntos(x, visual_en), default=None)
                pide_perras = bool(PERRAS & set(re.findall(r"[a-z]+", normalizar(visual_en))))
                if pide_perras:                               # si salen las perras, la foto de verdad de ellas
                    con = [x for x in libres_e if PERRAS & set(normalizar(x["escena"]).split())]
                    mejor_e = max(con, key=lambda x: puntos(x, visual_en), default=mejor_e)
                if mejor_e and (puntos(mejor_e, visual_en) >= 2 or (pide_perras and PERRAS & set(
                        normalizar(mejor_e["escena"]).split()))):
                    usadas.add(mejor_e["archivo"])
                    return "imagen", mejor_e["ruta"]
            libres_c = [c for c in clips if c["archivo"] not in usadas]
            cats = [k for k in mezcla if mezcla[k] > 0]
            primera = random.choices(cats, weights=[mezcla[k] for k in cats])[0] if cats else "publica"
            libres_f = []
            for cat in [primera] + [k for k in cats if k != primera]:
                libres_f = [f for f in todas if f.get("apta") == cat and f["archivo"] not in usadas]
                if libres_f:
                    break
            mejor_c = max(libres_c, key=lambda c: puntos(c, visual_en), default=None)
            mejor_f = max(libres_f, key=lambda f: puntos(f, visual_en), default=None)
            if mejor_c and (i == 0 or puntos(mejor_c, visual_en) >= max(1, puntos(mejor_f, visual_en) if mejor_f else 0)):
                usadas.add(mejor_c["archivo"])
                origen = normalizar(mejor_c.get("origen", ""))
                marca = "sin marca" not in origen and any(w in origen for w in ("deevid", "opengen", "viggle", "kling", "marca"))
                return "clip", mejor_c["ruta"], marca
            if not mejor_f:
                return None                                   # sin material: imagen nueva con FLUX
            usadas.add(mejor_f["archivo"])
            if animar and i == 0 and self.estudio:            # el gancho con movimiento: Wan en Hugging Face, gratis
                try:
                    destino = NX / "clips" / f"wan-{mejor_f['archivo'].rsplit('.', 1)[0]}.mp4"
                    if not destino.exists():
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        self.estudio.clip(f"the woman in the photo, {visual_en}, subtle natural movement, smiles at "
                                          "camera", mejor_f["ruta"], destino, forzar="wan")
                    return "clip", destino
                except Exception as ex:
                    self.log(f"nexus: Wan no ha animado la foto ({ex}); va quieta")
            return "imagen", mejor_f["ruta"]
        return elegir

    def _ordenes_material(self, t: str) -> Respuesta | None:
        m = re.search(r"\b(tengo|ya tengo|he cogido|activad\w*|quita\w*|ya no tengo|cancelad\w*)\b.*\b(hugging ?face )?pro\b", t)
        if m and re.search(r"\bhugging|\bhf\b|\bpro\b", t):
            si = not re.search(r"\b(quita\w*|ya no|cancelad\w*)\b", t)
            self.e["hf_pro"] = si
            self._guardar()
            return Respuesta("Apuntado: con Hugging Face PRO hago más clips al día, vídeos hablando y sonido real en los "
                             "clips mudos." if si else "Apuntado: sin PRO, gasto lo justo del cupo gratis.")
        for w in ("hedra", "heygen", "hey gen", "vidnoz", "gidnoz"):   # webs de «foto que habla»: por su web, no por LTX
            if re.search(rf"\b{w}\b", t):
                return Respuesta(self.pedir_habla_web(ALIAS_WEB.get(w, w)))
        if re.search(r"\b(video|clip)\w* (de ella |de asuka )?(hablando|que hable|hablandome|hablando a camara)\b|\bque hable a camara\b", t):
            self._en_hilo("vídeo hablando", self.hablar_a_camara)
            return Respuesta("Hago un vídeo de Asuka hablando a cámara con su voz. Tarda unos minutos; te aviso.")
        if re.search(r"\b(video|clip)\w* (de |en )?(alta calidad|calidad alta|hd)\b", t):
            self._en_hilo("clip alta calidad", lambda: self.clip_wan(1) or "Hoy no queda cupo de vídeo; mañana más.")
            return Respuesta("Hago un clip de Asuka en alta calidad (LTX 2.3) con su voz. Tarda unos minutos; te aviso.")
        m = re.search(r"\bborra\w* (?:de|en) instagram (?:la (?:publicacion |foto |del? |que )?|el (?:reel |video )?(?:de |del )?)?(.+)", t)
        if m:
            return Respuesta(self.borrar_de_instagram(m.group(1)))
        if re.search(r"\b(que|cual\w*|como) (?:me |le )?(funciona|va) mejor\b|\bestadisticas de (?:las )?publicaciones\b", t):
            return Respuesta(self.actualizar_rendimiento())
        web_dicha = next((v for k, v in ALIAS_WEB.items() if re.search(rf"\b{k}\b", t)), None)
        if web_dicha and re.search(r"\b(sin|no (me )?queda\w*|se (me )?ha acabado|agotad\w*|gastad\w*)\b.*\bcredit\w*|"
                                   r"\bcredit\w*\b.*\b(acabad|agotad|gastad)\w*", t):
            return Respuesta(self.sin_credito(web_dicha))
        if re.search(r"\b(que|cuales?) webs?\b.*\bcredit\w*|\bcreditos\b.*\b(quedan|tengo|hay)\b", t):
            return Respuesta(self.resumen_creditos())
        if re.search(r"\b(haz|prepara|pide|crea)\w* (?:una |otra )?foto\b", t) and (web_dicha == "nanobanana" or
                                                                                re.search(r"\bnueva\b", t)):
            return Respuesta(self.pedir_foto_web("nanobanana"))
        if web_dicha in ("hedra", "heygen", "vidnoz") or re.search(r"\b(que hable|hablando)\b.*\bweb\b", t):
            return Respuesta(self.pedir_habla_web(web_dicha or "hedra"))
        m = re.search(r"\b(prepara|haz|pide|crea)\w* (?:un |otro )?(?:clip|video)\b(?! con movimiento)", t)
        if m and (web_dicha or re.search(r"\b(web|credito)\w*\b", t) or re.search(r"\bclip\b", t)):
            return Respuesta(self.pedir_clip_web(web_dicha))
        if re.search(r"\bya tengo (el |los )?clips?\b", t):
            n = self._recoger_descargas()
            return Respuesta(f"Guardado{'s' if len(n) > 1 else ''} {len(n)} clip{'s' if len(n) > 1 else ''} del "
                             "personaje; los usaré en los próximos vídeos." if n else
                             "No veo ningún vídeo nuevo en Descargas desde que lo pedí. ¿Lo has descargado ya?")
        m = re.search(r"\b(aprueba|vale|quita|retira|bloquea)\w* (?:la )?(?:foto|referencia|imagen) (\d{1,3})\b", t)
        if m:
            ind = self._indice(REF)
            nombre = f"ref{int(m.group(2)):02d}.jpg"
            x = next((r for r in ind if r["archivo"] == nombre), None)
            if not x:
                return Respuesta(f"No tengo la foto {m.group(2)}.")
            x["apta"] = "publica" if m.group(1).startswith(("aprueba", "vale")) else "no"
            self._guardar_indice(REF, ind)
            return Respuesta(f"Foto {m.group(2)}: " + ("la puedo usar en los vídeos." if x["apta"] == "publica"
                                                      else "no la usaré en las redes."))
        m = re.search(r"\bmezcla\D*(\d{1,3})\D+(\d{1,3})\D+(\d{1,3})", t)
        if m:
            v = [int(x) for x in m.groups()]
            if sum(v) == 0:
                return Respuesta("La mezcla no puede ser todo cero.")
            self.e["mezcla"] = dict(zip(("publica", "revisar", "no"), v))
            self._guardar()
            self._diario("ajuste", f"Mezcla de fotos: {v[0]} % verdes, {v[1]} % ámbar, {v[2]} % rojas")
            return Respuesta(f"Hecho: en los vídeos, {v[0]} % fotos verdes, {v[1]} % ámbar y {v[2]} % rojas.")
        m = re.search(r"\busa (?:la )?voz (\d)\b", t)
        if m:
            import shutil
            ref, txt = NX / "voces" / f"voz{m.group(1)}_ref.wav", NX / "voces" / f"voz{m.group(1)}_ref.txt"
            if not (ref.exists() and txt.exists()):
                return Respuesta(f"No tengo la voz {m.group(1)}.")
            shutil.copy(ref, NX / "voz_ref.wav")
            self.e["id"]["voz_ref_texto"] = txt.read_text(encoding="utf-8").strip()
            self._guardar()
            self._diario("ajuste", f"Voz del personaje: la {m.group(1)}", ruta=str(NX / "voces" / f"voz{m.group(1)}_muestra.wav"))
            return Respuesta(f"Hecho: desde ahora {self.e['id'].get('nombre', 'el personaje')} habla con la voz "
                             f"{m.group(1)} en los vídeos.")
        m = re.search(r"\b(?:crea|haz|hazle|genera)\w* (\w+ )?fotos? nuevas?\b", t)
        if m:
            n = numero(m.group(1) or "") or 3
            self._en_hilo("fotos nuevas", lambda: self.crear_fotos(min(n, 6)))
            return Respuesta(f"Hago {min(n, 6)} fotos nuevas de Asuka a partir de las suyas; tardo unos minutos.")
        if re.search(r"\banima\w* (una |sus )?fotos?\b", t):
            self._en_hilo("animar foto", lambda: self.clip_wan() or "Hoy no queda cupo gratis para animar fotos; "
                                                                     "lo intento más tarde.")
            return Respuesta("Animo una de sus fotos con movimiento real (unos 2 minutos) y la preparo con su voz.")
        m = re.search(r"\b(?:video|clip) con sjinn(?: sobre| de)? (.+)$", t)
        if m:
            self._en_hilo("vídeo con SJinn", lambda: self.video_sjinn(m.group(1)))
            return Respuesta("Encargo el vídeo a SJinn (gasta créditos de tu cuenta); te aviso cuando esté.")
        if re.search(r"\b(publica|sube)\w* (ya|ahora|lo de hoy|las de hoy)\b", t):
            hechas = self.publicar_pendientes() if self.redes_conectadas() else []
            return Respuesta(("Publicado: " + "; ".join(hechas)) if hechas else
                             ("No hay nada pendiente cuya hora haya llegado en las redes conectadas." if
                              self.redes_conectadas() else "Aún no hay redes conectadas para publicar sola: "
                              "bash ~/jarvis/configurar_redes_nexus.sh y «nexus, conecta YouTube»."))
        if re.search(r"\b(no publiques sola|para de publicar|publicacion manual)\b", t):
            self.e["auto_publicar"] = False
            self._guardar()
            return Respuesta("Vale: preparo las publicaciones pero no las subo yo; las subes tú o me dices «publica ya».")
        if re.search(r"\b(publica sola|publicacion automatica)\b", t):
            self.e["auto_publicar"] = True
            self._guardar()
            return Respuesta("Hecho: publico sola a su hora en las redes conectadas.")
        if re.search(r"\bconecta\w* (el |su )?youtube\b", t):
            if not self.youtube:
                return Respuesta("No tengo el módulo de YouTube.")
            abrir_web("http://127.0.0.1:8765/nexus/youtube/conectar")
            return Respuesta("Te abro Google: entra con la cuenta de Asuka y pulsa «Permitir». Si sale «acceso "
                             "bloqueado», antes hay que añadir su Gmail como usuario de prueba en Google Cloud.")
        if re.search(r"\bpersonaliza\w*\b|\bactualiza\w* (los |sus )?perfiles\b", t):
            return Respuesta(self.personalizar())
        if re.search(r"\b(que publico|plan (de|del) (hoy|dia)|que toca hoy|publicaciones de hoy)\b", t):
            return Respuesta(self.plan_del_dia(forzar="otra vez" in t or "nuevo" in t))
        if re.search(r"\b(video narrado|videos narrados|money ?printer|asuka cuenta|cuenta (algo|una historia))\b", t):
            m = re.search(r"\bsobre\s+(.{4,80})$", t) or re.search(r"\bde\s+(?!prueba\b)(.{4,80})$", t)
            tema = m.group(1).strip() if m and "narrado" not in m.group(1) else ""
            tema = re.sub(r"\bde prueba\b|\bprueba\b", "", tema).strip(" ,")
            self._en_hilo("narrado", lambda: self.video_narrado(tema, publicar="prueba" not in t))
            return Respuesta("Preparo un vídeo narrado con su voz" + (f" sobre {tema}" if tema else "") + ": guion, su "
                             "voz, metraje con MoneyPrinterTurbo y subtítulos. En el portátil tarda unos 10-20 minutos; "
                             "te aviso.")
        if re.search(r"\bkaggle\b", t):
            ka = self.e.get("kaggle") or {}
            if re.search(r"\b(como va|estado|que tal|ha terminado|que ha fallado)\b", t):
                if not ka:
                    return Respuesta("Todavía no he lanzado nada en Kaggle.")
                txt = {"lanzado": "Está en marcha", "running": "Está generando los clips",
                       "queued": "Está en cola esperando GPU", "hecho": f"Terminó: {ka.get('clips', 0)} clips",
                       "fallido": "El último lote falló"}.get(ka.get("estado"), ka.get("estado", "?"))
                if ka.get("estado") == "fallido" and ka.get("registro"):
                    txt += ". Lo último del registro: " + ka["registro"][-300:]
                return Respuesta(txt + ".")
            if re.search(r"\bno\b.*\b(solo|sola|automatic)", t):
                self.e["kaggle_auto"] = False
                self._guardar()
                return Respuesta("Vale, no lanzo lotes en Kaggle yo sola; solo cuando me lo pidas.")
            self._en_hilo("kaggle", self.clips_kaggle)
            return Respuesta("Preparo el lote de clips para la GPU de Kaggle; te aviso.")
        if re.search(r"\b(contest|respond)\w* (tu |ella )?sola\b|\b(contestar|responder) sola\b", t):
            self.e["auto_respuestas"] = not re.search(r"\bno (contest|respond)", t)
            self._guardar()
            return Respuesta("Vale, los comentarios sencillos (emojis, piropos, saludos) los contesto yo sola, máximo 12 "
                             "al día; las preguntas y lo delicado te las paso a ti." if self.e["auto_respuestas"] else
                             "Vale, no contesto nada sola: todas las respuestas te las propongo y las envías tú.")
        if re.search(r"\bcomentarios\b", t):
            n = self.leer_comentarios()
            pend = [c for c in self.e.get("comentarios", []) if c.get("propuesta") and not c.get("respondido")
                    and not c.get("ignorado")]
            return Respuesta((f"{n} comentarios nuevos. " if n else "") + (f"Hay {len(pend)} con respuesta propuesta en "
                             "la página de Asuka." if pend else "No hay comentarios por contestar.")
                             + ("" if self.youtube and self.youtube.conectado else " (Solo leo YouTube cuando esté "
                                                                                   "conectado.)"))
        if re.search(r"\b(anima|animame|dale movimiento)\b.*\bfoto\b|\bclip (con|de) movimiento\b", t):
            self._en_hilo("movimiento", lambda: self.clip_wan() or "Hoy no queda cupo gratis para animar fotos; "
                                                                   "lo intento más tarde.")
            return Respuesta("Animo una de tus fotos con movimiento real (tardo unos 2 minutos) y la preparo con tu "
                             "voz para esta noche.")
        if re.search(r"\bvideos? (con|de) movimiento\b", t):
            self._en_hilo("movimiento", lambda: self.videos_movimiento() or "No hay clips con movimiento nuevos.")
            return Respuesta("Preparo tus clips con movimiento con tu voz para esta noche; te aviso.")
        if re.search(r"\b(entregas?|publicaciones|plan)\b.*\b(hoy|del dia)\b", t) and re.search(r"\b(prepara|haz|rehaz)", t):
            self._en_hilo("entregas", self.entregas_hoy)
            return Respuesta("Preparo lo de hoy en todas las redes: fotos en las que sales tú, sola o con tus peques, y "
                             "tus clips con movimiento con tu voz. Te aviso en unos minutos.")
        m = re.search(r"\bmonta(?:r|me)? (?:el )?(?:video )?(?:de )?(.+)$", t)
        if m and not re.search(r"\bxbox\b", t):
            clave = next((k for k in self.MONTAJES if normalizar(k) in m.group(1)), m.group(1).strip())
            self._en_hilo("montaje", lambda: self.montar_historia(clave))
            return Respuesta(f"Monto «{clave}» con las tomas que tengo y mi voz; te aviso.")
        m = re.search(r"\bvoz (?:de |del |de los )?videos? (?:con |de )?(asuka|qwen|la de asuka|la de qwen)\b", t)
        if m:
            self.e["id"]["voz_video"] = "qwen" if "qwen" in m.group(1) else "asuka"
            self._guardar()
            return Respuesta("Hecho: en los vídeos de Asuka uso " + ("la voz de Qwen3 (copia de la voz 2, con cupo diario)."
                             if "qwen" in m.group(1) else "su voz entrenada, la misma que tengo yo."))
        if re.search(r"\b(clips?|capturas?|videos?|partidas?)\b.*\bxbox\b|\bxbox\b.*\b(clips?|capturas?|sube\w*)\b", t):
            if self.ocupado == "xbox":
                return Respuesta("Ya estoy preparando clips de Xbox; te aviso al terminar.")
            self._en_hilo("xbox", lambda: self.clips_xbox(avisar_vacio=True))
            return Respuesta("Busco tus clips de Xbox nuevos y los preparo para YouTube, TikTok y Twitch; tardo unos "
                             "minutos por clip y te aviso.")
        m = re.search(r"\bfoto (?:de perfil )?(?:de |para |en )(?:la cuenta de |el canal de )?(twitch|youtube|tiktok|"
                      r"instagram|x|twitter|pinterest|facebook)\b.*?\b(?:la |es la |pon la |numero )?(\d)\b", t)
        if m:
            red = "x" if m.group(1) == "twitter" else m.group(1)
            arch = f"candidata{m.group(2)}.jpg"
            if not (NX / "retratos" / arch).exists():
                return Respuesta(f"No tengo la foto {m.group(2)} entre las candidatas de perfil.")
            self.e.setdefault("perfil_red", {})[red] = arch
            self._guardar()
            self.hacer_portadas()
            return Respuesta(f"Hecho: en {REDES[red]['nombre']} su foto de perfil será la {m.group(2)}. La tienes en la "
                             "página de Asuka, con las portadas.")
        if re.search(r"\b(portadas?|banners?|cabeceras?|fotos? de perfil)\b", t):
            return Respuesta(self.hacer_portadas())
        if re.search(r"\bmaterial\b", t):
            self._recoger_descargas()
            ind = self._indice(REF)
            cuenta = {a: sum(1 for r in ind if r.get("apta") == a) for a in ("publica", "revisar", "no")}
            return Respuesta(f"Material de {self.e['id'].get('nombre', 'Nexus')}: {len(ind)} fotos ({cuenta['publica']} "
                             f"para usar sola, {cuenta['revisar']} solo si me las apruebas, {cuenta['no']} que no subo) "
                             f"y {len(self._indice(CLIPS))} clips. Están en el panel de Nexus.")
        return None

    # ================================================================ usar los perfiles
    def _guion_humano(self, g: dict, tono: str) -> None:
        """El guion se humaniza entero, de una vez, para que fluya de una escena a otra; y las perras solo se nombran
        en las escenas en las que salen."""
        escenas = g.get("escenas", [])
        perro = re.compile(r"\b(dogs?|jazmin|leia|pets?|perr[oa]s?)\b")
        for e in escenas:
            e["_perras"] = bool(perro.search(normalizar(e.get("visual_en", ""))))
        marcado = "\n".join(f"[{i + 1}] {e.get('texto', '')}" + ("" if e["_perras"] else " (aquí no salen las perras)")
                             for i, e in enumerate(escenas))
        nuevo = self._humano(marcado + "\n\nDevuelve las mismas escenas numeradas [1], [2]… una por línea. En las "
                             "marcadas «aquí no salen las perras» no las nombres. Que se lea como una sola charla "
                             "seguida, fluida.", "guion", tono)
        trozos = re.findall(r"\[(\d+)\]\s*(.+?)(?=\s*\[\d+\]|\Z)", nuevo, re.S)
        if len(trozos) == len(escenas):
            for (_, t), e in zip(trozos, escenas):
                e["texto"] = re.sub(r"\s*\(aquí no salen las perras\)", "", t.strip())
        else:                                                 # si no ha respetado el formato, escena a escena
            for e in escenas:
                e["texto"] = self._humano(e.get("texto", ""), "guion", tono)
        nombra = re.compile(r"(?i)\b(jazm[ií]n|leia|mis peques|mis perras|las perras)\b")
        for e in escenas:                                     # red de seguridad: sin perras en pantalla, sin nombrarlas
            if not e.pop("_perras") and nombra.search(e["texto"]):
                frases = [f for f in re.split(r"(?<=[.!?…])\s+", e["texto"]) if not nombra.search(f)]
                e["texto"] = " ".join(frases) or e["texto"]
        if not any(perro.search(normalizar(e.get("visual_en", ""))) for e in escenas):
            g["caption"] = " ".join(f for f in re.split(r"(?<=[.!?…])\s+", g.get("caption", ""))
                                    if not nombra.search(f)) or g.get("caption", "")

    def _humano(self, texto: str, tipo: str, tono: str = "", limite: int | None = None) -> str:
        from nexus_humano import humanizar
        return humanizar(texto, self.cerebro, tono or self.e["id"].get("biblia", {}).get("tono", ""), tipo, limite)

    def _foto_mezcla(self, usadas: set) -> dict | None:
        """Una foto según la mezcla (verde/ámbar/roja), sin repetir las de los últimos días."""
        mezcla = self.e.get("mezcla") or MEZCLA
        recientes = set(self.e.get("fotos_usadas", [])[-25:]) | usadas
        todas, _ = self._material(("publica", "revisar", "no"))
        cats = [k for k in mezcla if mezcla[k] > 0]
        if not cats or not todas:
            return None
        import datetime as _dt
        hace10 = (_dt.date.today() - _dt.timedelta(days=10)).isoformat()
        frescas = [f for f in todas if f.get("apta") == "publica" and f.get("nueva", "") >= hace10
                   and f["archivo"] not in recientes and f["archivo"] not in set(self.e.get("fotos_usadas", []))]
        if frescas:                                         # recién hechas (o pedidas por ti): primero
            f = sorted(frescas, key=lambda x: (not x.get("pedida"), x.get("nueva", "")))[0]
            usadas.add(f["archivo"])
            self.e["fotos_usadas"] = (self.e.get("fotos_usadas", []) + [f["archivo"]])[-200:]
            return f
        primera = random.choices(cats, weights=[mezcla[k] for k in cats])[0]
        for cat in [primera] + [k for k in cats if k != primera]:
            libres = [f for f in todas if f.get("apta") == cat and f["archivo"] not in recientes]
            if libres:
                f = random.choice(libres)
                usadas.add(f["archivo"])
                self.e["fotos_usadas"] = (self.e.get("fotos_usadas", []) + [f["archivo"]])[-200:]
                return f
        return random.choice(todas)

    def plan_del_dia(self, forzar: bool = False, solo_ella: bool = False) -> str:
        """Lo que se publica hoy en cada red: textos ya humanizados, foto o vídeo, y la hora buena."""
        hoy = time.strftime("%Y-%m-%d")
        if not forzar and any(c.get("dia") == hoy and c.get("estado") in ("pendiente", "publicado")
                              and c.get("tipo") in ("foto", "historia", "carrusel") for c in self.e.get("cola", [])):
            return "El plan de hoy ya está hecho; lo tienes en la página de Asuka."
        b = self.e["id"].get("biblia", {})
        usadas: set = set()
        fotos = {k: self._foto_mezcla(usadas) for k in ("x", "instagram", "facebook", "pinterest")}
        for f in fotos.values():
            if f:
                f["rel"] = f"referencias/{f['archivo']}"
        ent = [x for x in self._indice(ENTORNO) if x.get("apta") == "publica" and (ENTORNO / x["archivo"]).exists()
               and x["archivo"] not in self.e.get("entorno_usadas", [])[-6:]]
        if ent and not solo_ella and random.random() < 0.35:                 # algunos días, su mundo: las perras, el cuarto, la colección
            x = random.choice(ent)
            red = random.choice(["instagram", "facebook", "x"])
            fotos[red] = dict(x, rel=f"entorno/{x['archivo']}",
                              escena=f"{x.get('descripcion', x['escena'])} (ella no sale en la foto; habla de ello)")
            self.e.setdefault("entorno_usadas", []).append(x["archivo"])
        desc = {k: (f["escena"] if f else "") for k, f in fotos.items()}
        d = self._ia("Eres community manager de una creadora de contenido española. Devuelve SOLO JSON.",
                     f"Creadora: {self.e['id'].get('nombre')}. {b.get('resumen', BASE)} Tono: {b.get('tono', '')}. "
                     f"Regla: {TRANSPARENCIA} {self.resumen_rendimiento(para_ia=True)} "
                     f"Hoy es {time.strftime('%A %d de %B')}. Escribe las publicaciones de hoy, "
                     f"cada una sobre su foto: x (foto: {desc['x']}; post de máx 260 caracteres), instagram (foto: "
                     f"{desc['instagram']}; caption 1-3 frases + 5 hashtags), facebook (foto: {desc['facebook']}; post "
                     f"corto), pinterest (foto: {desc['pinterest']}; titulo máx 90 y descripcion máx 400 con palabras "
                     "que se buscan). Solo habla de sus perras («mis peques», Jazmín y Leia) en la publicación cuya foto es de "
                     "ellas; en las demás, ni las nombres. Habla solo de lo que se ve en cada foto: no inventes juegos, "
                     "mascotas (no tiene gato) ni cosas que no salen. Nada de anuncios ni frases hechas. Cada texto distinto en arranque y ritmo; sus muletillas, "
                     "como mucho una por texto y nunca la misma en dos publicaciones. JSON: {\"x\": \"…\", \"instagram\": \"…\", "
                     "\"facebook\": \"…\", \"pinterest_titulo\": \"…\", \"pinterest\": \"…\", "
                     "\"horas\": {\"x\": \"HH:MM\", \"instagram\": \"HH:MM\", \"facebook\": \"HH:MM\", \"pinterest\": \"HH:MM\"}}",
                     max_tokens=1200)
        tono = b.get("tono", "")
        ya = {c["red"] for c in self.e.get("cola", []) if c.get("dia") == hoy and c.get("estado") == "publicado"}
        cola = [c for c in self.e.get("cola", []) if (c.get("estado") == "pendiente"
                and (c.get("dia") != hoy or c.get("origen") in ("xbox", "telegram", "movimiento")))
                or (c.get("dia") == hoy and c.get("estado") == "publicado")][-40:]
        minimo = time.strftime("%H:%M", time.localtime(time.time() + 20 * 60))
        lim = {"x": 270, "instagram": 600, "facebook": 600, "pinterest": 450}
        for k, f in fotos.items():
            if not f or not d.get(k) or k in ya:
                continue
            hora = (d.get("horas") or {}).get(k, "") or minimo
            if forzar and hora < minimo:                  # rehecho a media tarde: nada con la hora ya pasada
                hora = minimo
                minimo = time.strftime("%H:%M", time.localtime(time.time() + (20 + 35 * (len(cola) % 4)) * 60))
            item = {"id": f"{hoy}-{k}-{int(time.time()) % 100000}", "dia": hoy, "red": k, "tipo": "foto",
                    "plan_auto": int(time.strftime("%H")) >= 10, "archivo": f.get("rel") or f"referencias/{f['archivo']}",
                    "texto": self._humano(d[k], "post" if k in ("x", "facebook") else "caption", tono, lim[k]),
                    "hora": hora, "estado": "pendiente"}
            if k == "pinterest":
                item["titulo"] = self._humano(d.get("pinterest_titulo", ""), "post", tono, 90)
            cola.append(item)
        if "instagram" not in ya and not any(c.get("tipo") == "historia" and c.get("dia") == hoy for c in cola):
            h = self._foto_mezcla(usadas)                      # y una historia de Instagram con otra foto suya
            import datetime as _dt                             # (algunos días, el vídeo con movimiento de ayer)
            ayer = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
            mov = [c for c in self.e.get("cola", []) if c.get("origen") == "movimiento" and c.get("estado") == "publicado"
                   and c.get("dia", "") >= ayer and (NX / c.get("archivo", "")).exists()]
            if mov and random.random() < 0.5:
                h = {"archivo": "", "rel": mov[-1]["archivo"]}
            if h:
                hora_h = max("13:30", minimo) if forzar else "13:30"
                cola.append({"id": f"{hoy}-historia-{int(time.time()) % 100000}", "dia": hoy, "red": "instagram",
                             "tipo": "historia", "plan_auto": int(time.strftime("%H")) >= 10,
                             "archivo": h.get("rel") or f"referencias/{h['archivo']}", "texto": "(historia: sin texto)",
                             "hora": hora_h, "estado": "pendiente"})
        car = self._carrusel_semanal(cola, hoy, minimo if forzar else "12:30")
        if car:
            cola.append(car)
        for i, v in enumerate(self.e.get("videos", [])):          # vídeos aprobados aún sin publicar
            if not v.get("aprobado"):
                continue
            meta = {}
            try:
                meta = json.loads((Path(v["carpeta"]) / "publicacion.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                pass
            texto = (meta.get("caption", "") + "\n" + " ".join(meta.get("hashtags", [])[:5])).strip()
            for red in ("tiktok", "instagram", "youtube"):
                if red in v.get("publicado", {}) or any(c["id"] == f"v{i}-{red}" for c in cola):
                    continue
                cola.append({"id": f"v{i}-{red}", "dia": hoy, "red": red, "tipo": "video",
                             "archivo": v["ruta"].split("/nexus/", 1)[-1], "texto": texto,
                             "titulo": meta.get("titulo_youtube", v["titulo"]), "video": i, "estado": "pendiente",
                             "hora": "19:00" if red != "youtube" else "17:00"})
        self.e["cola"] = cola
        self._guardar()
        n = sum(1 for c in cola if c["dia"] == hoy)
        self._diario("ajuste", f"Plan de hoy: {n} publicaciones preparadas")
        return (f"Plan de hoy listo: {n} publicaciones con su foto o vídeo, el texto y la hora. Están en la página de "
                "Asuka, en «Hoy toca»: copias el texto, abres la red y lo subes; luego pulsas «Hecho».")

    def accion(self, j: dict) -> dict:
        """Botones de la página: publicado / descartar / publicar en YouTube / responder un comentario."""
        tipo = j.get("tipo")
        if tipo == "publicar":
            c = next((x for x in self.e.get("cola", []) if x["id"] == j.get("id")), None)
            if not c:
                return {"ok": False, "error": "no está en la cola"}
            if j.get("texto"):
                c["texto"] = str(j["texto"])[:2200]
            try:
                self._publicar(c)
            except Exception as ex:
                return {"ok": False, "error": str(ex)[:200]}
            return {"ok": True, "url": c.get("url", "")}
        if tipo == "deshacer":
            c = next((x for x in self.e.get("cola", []) if x["id"] == j.get("id")), None)
            if c and (c.get("estado") == "descartado" or (c.get("estado") == "publicado" and c.get("marcado"))):
                c["estado"] = "pendiente"
                c.pop("url", None)
                self._guardar()
            return {"ok": True}
        if tipo == "apta":
            nombre, apta = str(j.get("archivo", "")), j.get("apta")
            if apta not in ("publica", "revisar", "no"):
                return {"ok": False, "error": "color no válido"}
            ind = self._indice(REF)
            r = next((x for x in ind if x["archivo"] == nombre), None)
            if not r:
                return {"ok": False, "error": "foto no encontrada"}
            r["apta"] = apta
            r.pop("nueva_sin_ver", None)
            self._guardar_indice(REF, ind)
            self._diario("ajuste", f"{nombre} → {apta}")
            return {"ok": True}
        if tipo == "quitar_prompt":
            cola = self.e.get("prompts_fotos", [])
            i = int(j.get("i", -1))
            if 0 <= i < len(cola):
                cola.pop(i)
                self._guardar()
                return {"ok": True}
            return {"ok": False, "error": "no está"}
        if tipo == "limpiar_prompts":
            n = self._limpiar_prompts()
            self._guardar()
            return {"ok": True, "quitados": n}
        if tipo == "contestar":
            if not self.e.get("pregunta"):
                return {"ok": False, "error": "no hay pregunta pendiente"}
            texto = str(j.get("texto", "")).strip()[:500]
            self._diario("tu", texto + " (desde el panel)")
            self._en_hilo("respuesta", lambda: self.responder(texto).texto)
            return {"ok": True}
        if tipo == "rapida":
            que = j.get("que")
            trabajos = {"fotos": ("fotos", lambda: self.crear_fotos(3)),
                        "clip": ("clip", lambda: self.clip_wan(1)),
                        "narrado": ("narrado", lambda: self.video_narrado()),
                        "plan": ("plan", lambda: self.plan_del_dia(forzar=True)),
                        "comentarios": ("comentarios", lambda: f"{self.leer_comentarios()} comentarios nuevos."),
                        "estadisticas": ("estadísticas", self.actualizar_rendimiento),
                        "hedra": ("hedra", lambda: self.pedir_habla_web("hedra")),
                        "gemini": ("gemini", lambda: self.pedidas_a_gemini(3)),
                        "refrescar": ("refrescar", self._refrescar_todo)}
            if que not in trabajos:
                return {"ok": False, "error": "acción desconocida"}
            if self.ocupado and que != "refrescar":
                return {"ok": False, "error": f"estoy con {self.ocupado}; en cuanto acabe"}
            nombre, fn = trabajos[que]
            if que == "refrescar":
                threading.Thread(target=fn, daemon=True, name="nexus-refrescar").start()
            else:
                self._en_hilo(nombre, fn)
            return {"ok": True}
        if tipo in ("hecho", "descartar", "youtube"):
            c = next((x for x in self.e.get("cola", []) if x["id"] == j.get("id")), None)
            if not c:
                return {"ok": False, "error": "no está en la cola"}
            if tipo == "descartar":
                c["estado"] = "descartado"
                self._diario("ajuste", f"Descartada la publicación de {REDES[c['red']]['nombre']}: {c['texto'][:80]}")
            elif tipo == "youtube":
                if not (self.youtube and self.youtube.conectado):
                    return {"ok": False, "error": "YouTube sin conectar"}
                r = self.youtube.subir(NX / c["archivo"], c.get("titulo", "")[:100], c["texto"],
                                       [h.lstrip("#") for h in re.findall(r"#\w+", c["texto"])])
                c.update(estado="publicado", url=r["url"], privacidad=r["privacidad"])
            else:
                c.update(estado="publicado", url=str(j.get("url") or "")[:300], marcado=True)
            if c["estado"] == "publicado":
                c["publicado_t"] = time.strftime("%Y-%m-%d %H:%M")
                if c.get("tipo") == "video" and isinstance(c.get("video"), int) \
                        and 0 <= c["video"] < len(self.e.get("videos", [])):     # los de movimiento/narrados no tienen
                    self.e["videos"][c["video"]].setdefault("publicado", {})[c["red"]] = c.get("url", "") or "sí"
                self._diario("publicado", f"Publicado en {REDES[c['red']]['nombre']}: {c['texto'][:120]}",
                             ruta=str(NX / c["archivo"]), url=c.get("url", ""))
            self._guardar()
            return {"ok": True, "url": c.get("url", "")}
        if tipo in ("responder", "ignorar"):
            com = next((x for x in self.e.get("comentarios", []) if x["id"] == j.get("id")), None)
            if not com:
                return {"ok": False, "error": "comentario no encontrado"}
            if tipo == "responder":
                texto = str(j.get("texto") or com.get("propuesta") or "").strip()
                if not texto:
                    return {"ok": False, "error": "respuesta vacía"}
                self._enviar_respuesta(com, texto)
            else:
                com["ignorado"] = True
            self._guardar()
            return {"ok": True}
        return {"ok": False, "error": "acción desconocida"}

    def _enviar_respuesta(self, com: dict, texto: str, sola: bool = False) -> None:
        if com.get("red") == "instagram":
            from nexus_publicar import instagram_responder
            instagram_responder(com["id"], texto)
        elif com.get("red") == "facebook":
            from nexus_publicar import facebook_responder
            facebook_responder(com["id"], texto)
        else:
            self.youtube.responder(com["id"], texto)
        com.update(respondido=texto, **({"sola": True} if sola else {}))
        self._diario("comentario", f"Respondido{' sola' if sola else ''} a {com['autor']}: {texto}")

    def _puede_responder_sola(self, c: dict, clase: str) -> bool:
        """Solo lo que no tiene riesgo: emojis, piropos, saludos y ánimos, con un tope diario. Preguntas, críticas,
        enlaces, menciones o cualquier cosa sobre si es real/IA siguen pasando por ti."""
        if not self.e.get("auto_respuestas", True) or clase != "simple":
            return False
        crudo = c.get("texto", "")
        t = normalizar(crudo)
        if len(crudo) > 140 or "?" in crudo or "http" in t or "www." in t or "@" in crudo:
            return False
        if re.search(r"\b(ia|ai|bot|real|fake|falsa?|artificial|robot|generad|precio|cuanto|colab|dm|privado|"
                     r"whats|telegram|onlyfans|sigue(me)?|follow)\b", t):
            return False
        hoy = time.strftime("%Y-%m-%d")
        cuenta = self.e.get("auto_resp_dia") or {}
        if cuenta.get("dia") != hoy:
            cuenta = {"dia": hoy, "n": 0}
        if cuenta["n"] >= 12:
            return False
        cuenta["n"] += 1
        self.e["auto_resp_dia"] = cuenta
        return True

    def leer_comentarios(self) -> int:
        """Comentarios nuevos de YouTube, Instagram y Facebook, con una respuesta propuesta en su voz. Los sencillos
        (emojis, piropos, saludos) los contesta ella sola con tope diario; el resto se envía con un clic."""
        vistos = {c["id"] for c in self.e.get("comentarios", [])}
        todos = []
        if self.youtube and self.youtube.conectado:
            try:
                todos += self.youtube.comentarios()
            except Exception as ex:
                self.log(f"nexus: comentarios de YouTube: {ex!r}"[:200])
        for red, nombre in (("instagram", "instagram_comentarios"), ("facebook", "facebook_comentarios")):
            try:
                import nexus_publicar
                todos += getattr(nexus_publicar, nombre)()
            except Exception as ex:
                self.log(f"nexus: comentarios de {red}: {ex!r}"[:200])
        nuevos = [c for c in todos if c["id"] not in vistos and not c.get("respuestas")]
        b = self.e["id"].get("biblia", {})
        for c in nuevos:
            r = self._ia("Contestas comentarios como la creadora. Devuelve SOLO JSON.",
                         f"Creadora: {self.e['id'].get('nombre')}. {b.get('resumen', '')} Tono: {b.get('tono', '')}. "
                         f"Reglas: {b.get('reglas_conversacion', TRANSPARENCIA)} No respondas a insultos ni spam "
                         f"(responder=false). Comentario de {c['autor']}: «{c['texto'][:500]}». "
                         "clase: \"simple\" si es solo emojis, un piropo, un saludo o ánimo (sin preguntas ni "
                         "peticiones); \"pregunta\" si pregunta algo; \"otro\" para todo lo demás. La respuesta, "
                         "corta y natural (máximo 15 palabras para las simples). JSON: {\"responder\": true/false, "
                         "\"clase\": \"simple|pregunta|otro\", \"respuesta\": \"…\"}", max_tokens=300)
            c["propuesta"] = self._humano(r.get("respuesta", ""), "respuesta") if r.get("responder") else ""
            c["red"] = c.get("red", "youtube")
            self._diario("comentario", f"{c['autor']} en {c['red'].capitalize()}: {c['texto'][:300]}")
            if c["propuesta"] and (c["red"] != "youtube" or (self.youtube and self.youtube.conectado)) \
                    and self._puede_responder_sola(c, str(r.get("clase", ""))):
                try:
                    self._enviar_respuesta(c, c["propuesta"], sola=True)
                except Exception as ex:
                    self.log(f"nexus: respuesta automática: {ex!r}"[:200])
        if nuevos:
            self.e["comentarios"] = (self.e.get("comentarios", []) + nuevos)[-300:]
            self._guardar()
        return len(nuevos)

    def youtube_conectado(self) -> None:
        self._diario("ajuste", "YouTube del personaje conectado")
        threading.Thread(target=lambda: self.avisar(self.personalizar()), daemon=True).start()

    def personalizar(self) -> str:
        """Deja los perfiles al día: portadas, bios y, donde hay conexión oficial, lo cambia ella misma."""
        partes = [self.hacer_portadas()]
        bios = self.e["id"].get("bios")
        if self.youtube and self.youtube.conectado:
            try:
                b = self.e["id"].get("biblia", {})
                desc = (bios or {}).get("youtube") or b.get("resumen", "")
                pil = [p.get("tema", str(p)) if isinstance(p, dict) else str(p) for p in b.get("pilares", [])]
                hecho = self.youtube.personalizar(desc, pil + ["gaming", "anime", "gym", "tecnología", "shorts"],
                                                  NX / "portadas" / "youtube_2560x1440.jpg")
                partes.append("En YouTube he cambiado yo misma: " + ", ".join(hecho) + ".")
                self._diario("ajuste", "YouTube personalizado: " + ", ".join(hecho))
            except Exception as ex:
                partes.append(f"YouTube no me ha dejado cambiarlo ahora ({str(ex)[:120]}).")
        else:
            partes.append("Para que YouTube lo cambie yo sola, dime «nexus, conecta YouTube».")
        if not bios:
            partes.append("Las bios las escribo cuando apruebes la biblia (contesta «sí» a su pregunta).")
        partes.append("Foto, portada y bio del resto de redes: en la página de Asuka, con botón de descargar y copiar.")
        return " ".join(partes)

    def redes_conectadas(self) -> list[str]:
        try:
            from nexus_publicar import conectadas
            red = conectadas()
        except Exception:
            red = []
        if self.youtube and self.youtube.conectado:
            red.append("youtube")
        return red

    def _publicar(self, c: dict) -> None:
        """Publica un elemento de la cola por la API oficial de su red y lo apunta. Nunca dos veces lo mismo: el botón
        «Publicar ya» y la publicación automática pueden cruzarse mientras Instagram procesa un vídeo (≈1 min)."""
        with self._cerrojo_pub:
            if c.get("estado") == "publicado" or c.get("publicando"):
                raise RuntimeError("ya se está publicando o ya está publicado")
            if any(x is not c and x.get("estado") == "publicado" and x.get("red") == c["red"]
                   and x.get("archivo") == c.get("archivo")
                   and (x.get("tipo") == "historia") == (c.get("tipo") == "historia")   # un Reel puede ir también a historia
                   for x in self.e.get("cola", [])):
                c["estado"] = "publicado"
                self._guardar()
                raise RuntimeError("ese mismo archivo ya está publicado en esa red")
            c["publicando"] = time.time()
        try:
            self._publicar_de_verdad(c)
        finally:
            c.pop("publicando", None)
            self._guardar()

    def _publicar_de_verdad(self, c: dict) -> None:
        ruta = NX / c["archivo"]
        if c["red"] == "youtube":
            r = self.youtube.subir(ruta, c.get("titulo", "")[:100], c["texto"],
                                   [h.lstrip("#") for h in re.findall(r"#\w+", c["texto"])])
        else:
            from nexus_publicar import publicar
            r = publicar(c["red"], c.get("tipo", "foto"), ruta, c["texto"], c.get("titulo", ""),
                         extra=[NX / x for x in c.get("extra", [])])
        c.update(estado="publicado", url=r.get("url", ""), publicado_t=time.strftime("%Y-%m-%d %H:%M"))
        if c.get("tipo") == "video" and "video" in c:
            self.e["videos"][c["video"]].setdefault("publicado", {})[c["red"]] = c["url"] or "sí"
        self._guardar()
        self._diario("publicado", f"Publicado en {REDES[c['red']]['nombre']}: {c['texto'][:120]}",
                     ruta=str(ruta), url=c.get("url", ""))

    def publicar_pendientes(self) -> list[str]:
        """Lo de hoy cuya hora ya ha llegado, en las redes conectadas (si la publicación automática está activa)."""
        if not self.e.get("auto_publicar", True):
            return []
        hechas, ahora = [], time.strftime("%H:%M")
        redes = self.redes_conectadas()
        import datetime as _dt                           # lo de subir a mano que lleva 3 días sin hacerse, caduca
        limite = (_dt.date.today() - _dt.timedelta(days=2)).isoformat()
        for c in self.e.get("cola", []):
            if c.get("estado") == "pendiente" and c.get("red") not in redes and c.get("dia", "9999") < limite:
                c["estado"], c["motivo"] = "descartado", "caducado (no se subió a mano)"
        for c in self.e.get("cola", []):
            if c.get("publicando") and time.time() - c["publicando"] > 900:
                c.pop("publicando", None)
            if (c.get("estado") == "pendiente" and c["red"] in redes and c.get("dia") == time.strftime("%Y-%m-%d")
                    and not c.get("publicando")
                    and (c.get("hora") or "00:00") <= ahora
                    and (not c.get("error_t") or (c.get("intentos", 1) < 4 and time.time() - c["error_t"] > 3600))):
                try:
                    self._publicar(c)
                    hechas.append(f"{REDES[c['red']]['nombre']}: {c.get('url', '')}")
                except Exception as ex:                     # (se reintenta cada hora, hasta 4 veces: p. ej. sin internet)
                    c["error"], c["error_t"] = str(ex)[:200], time.time()
                    c["intentos"] = c.get("intentos", 0) + 1
                    self._guardar()
                    self.log(f"nexus: no se ha podido publicar en {c['red']}: {ex}")
        return hechas

    def crear_fotos(self, n: int = 3) -> str:
        """Fotos nuevas de Asuka a partir de las suyas (FLUX Kontext / Qwen-Image-Edit, gratis con cupo diario)."""
        from nexus_crear import SinCupo, editar_foto
        fotos, _ = self._material()
        if not fotos:
            return "No tengo fotos aprobadas de Asuka de las que partir."
        b = self.e["id"].get("biblia", {})
        ideas = self.e.get("ideas_fotos") or []
        pedidas = self.e.setdefault("prompts_fotos", [])
        for p in pedidas[:n]:                              # lo que ha pedido la persona va antes que las ideas propias
            if not p.get("instruccion_en"):
                d = self._ia("Traduces descripciones de fotos a instrucciones de edición de imagen. Devuelve SOLO JSON.",
                             f"Descripción (escrita por ella en primera persona): «{p['es']}». Escribe en INGLÉS una "
                             "instrucción para editar una foto suya y convertirla en esa escena: lugar, ropa, pose, luz y "
                             "encuadre, empezando por «Keep the same woman (same face, long curly red hair, thin "
                             "glasses)». Sin nada sexual. Y \"escena\": 3-5 palabras en inglés. JSON: {\"instruccion_en\": "
                             "\"…\", \"escena\": \"…\"}", max_tokens=500)
                if d.get("instruccion_en"):
                    p.update(instruccion_en=d["instruccion_en"], escena=d.get("escena", ""))
        lista = [dict(p, pedida=True) for p in pedidas[:n] if p.get("instruccion_en")]
        if len(ideas) + len(lista) < n:
            d = self._ia("Eres directora de fotografía de una creadora de contenido. Devuelve SOLO JSON.",
                         f"Creadora: {b.get('resumen', BASE)} Temas: {b.get('pilares', '')}. Propón {n + 2} fotos nuevas "
                         "para sus redes, distintas entre sí (lugar, ropa, momento del día, acción), que pegarían en "
                         "Instagram ahora. Nada sexual ni de marcas. SIEMPRE con buena luz (de día, luz natural o un "
                         "interior bien iluminado; nada de noche ni sitios oscuros) y plano medio con la cara bien "
                         "visible mirando a cámara. Para cada una: \"instruccion_en\" (en inglés, qué "
                         "cambiar de la foto: lugar, ropa, pose, luz) y \"escena\" (3-5 palabras en inglés para "
                         "clasificarla, ej. 'cafe coffee winter street'). JSON: {\"fotos\": [{\"instruccion_en\": "
                         "\"…\", \"escena\": \"…\"}]}", max_tokens=1200)
            ideas += d.get("fotos", [])
        ind = self._indice(REF)
        hechas = []
        for idea in (lista + list(ideas))[:n]:
            base = random.choice([f for f in fotos if self._luz(f["ruta"]) >= 90] or fotos)
            quitar = (lambda i=idea: pedidas.remove(next(x for x in pedidas if x.get("es") == i.get("es")))) \
                if idea.get("pedida") else (lambda i=idea: ideas.remove(i) if i in ideas else None)
            numeros = [int(re.sub(r"\D", "", r["archivo"]) or 0) for r in ind]
            nombre = f"ref{max(numeros + [0]) + 1:02d}.jpg"
            try:
                motor = editar_foto(base["ruta"], idea["instruccion_en"], REF / nombre, self.log,
                                    orden=self._orden_motores())
            except SinCupo:
                break                                       # mañana se sigue con las ideas que quedan
            except Exception as ex:
                self.log(f"nexus: foto nueva: {ex}")
                quitar()
                continue
            motivo = self._foto_mala(base["ruta"], REF / nombre)
            cuenta = self.e.setdefault("motores_foto", {}).setdefault(motor, {"ok": 0, "mal": 0})
            cuenta["mal" if motivo else "ok"] += 1           # el que más fotos buenas da, se prueba primero
            if motivo:                                      # oscura o no se la reconoce: fuera, y no se manda
                self.log(f"nexus: foto nueva descartada ({motivo})")
                (REF / nombre).unlink(missing_ok=True)
                if idea.get("pedida"):                      # lo pedido se reintenta una vez más (otra foto de base)
                    p = next((x for x in pedidas if x.get("es") == idea.get("es")), None)
                    if p is not None:
                        p["fallos"] = p.get("fallos", 0) + 1
                        if p["fallos"] >= 2:
                            pedidas.remove(p)
                            self.avisar(f"Asuka: la foto «{idea['es'][:70]}…» no ha salido bien dos veces; la dejo.")
                else:
                    quitar()
                continue
            quitar()
            ind.append({"archivo": nombre, "escena": idea.get("escena", base["escena"]), "apta": "publica",
                        "origen": motor, "de": base["archivo"], "nueva": time.strftime("%Y-%m-%d"),
                        **({"pedida": idea["es"][:300]} if idea.get("pedida") else {})})
            self._guardar_indice(REF, ind)
            hechas.append(nombre)
            self._diario("material", f"Foto nueva ({motor}): {idea.get('escena', '')}", ruta=str(REF / nombre))
            self.enviar_foto(str(REF / nombre), f"Foto nueva de Asuka: {idea.get('escena', '')}")
        self.e["ideas_fotos"] = ideas
        self._guardar()
        if pedidas and not hechas:
            return (f"Hoy ya no queda cupo gratis en los editores de imagen; me quedan {len(pedidas)} fotos tuyas por "
                    "hacer y sigo en unas horas o mañana.")
        if not hechas:
            return ("Hoy ya no queda cupo gratis en los editores de imagen de Hugging Face; me guardo las ideas y las "
                    "hago mañana.")
        return (f"He hecho {len(hechas)} fotos nuevas de Asuka a partir de las suyas (en su página y en Telegram). Si "
                "alguna no te gusta: «nexus, quita la foto N».")

    @staticmethod
    def _luz(ruta: Path) -> float:
        try:
            from PIL import Image, ImageStat
            with Image.open(ruta) as im:
                return ImageStat.Stat(im.convert("L").resize((128, 128))).mean[0]
        except Exception:
            return 128.0

    def _orden_motores(self) -> list[str]:
        """Motores de edición de mejor a peor tasa de fotos aprobadas (con suavizado: uno nuevo empieza al 50 %)."""
        from nexus_crear import ESPACIOS
        m = self.e.get("motores_foto", {})
        todos = list(dict.fromkeys([e[0].split("/")[-1] for e in ESPACIOS] + list(m)))
        tasa = lambda k: (m.get(k, {}).get("ok", 0) + 1) / (sum(m.get(k, {}).values() or [0]) + 2)
        return sorted(todos, key=lambda k: -tasa(k))

    @staticmethod
    def _aclarar(ruta: Path) -> float:
        """Rescata una foto oscura (escena de noche o interior) en vez de tirarla: estira niveles y sube medios tonos
        hasta una luz media de ~105. Devuelve la luz nueva."""
        from PIL import Image, ImageOps, ImageStat
        with Image.open(ruta) as im:
            im = ImageOps.autocontrast(im.convert("RGB"), cutoff=0.5)
            luz = ImageStat.Stat(im.convert("L").resize((128, 128))).mean[0]
            if luz < 100:
                g = max(0.45, min(1.0, __import__("math").log(105 / 255) / __import__("math").log(max(luz, 1) / 255)))
                im = im.point([round(255 * (i / 255) ** g) for i in range(256)] * 3)
            im.save(ruta, "JPEG", quality=93)
        return Nexus._luz(ruta)

    def _foto_mala(self, base: Path, nueva: Path) -> str:
        """'' si vale; si no, por qué: demasiado oscura, o en la nueva no se reconoce a la misma mujer."""
        luz = self._luz(nueva)
        if 20 <= luz < 70:                               # antes se tiraba (y se perdía el cupo): ahora se aclara
            try:
                antes, luz = luz, self._aclarar(nueva)
                self.log(f"nexus: foto oscura aclarada ({antes:.0f} → {luz:.0f}/255)")
            except Exception as ex:
                self.log(f"nexus: no he podido aclararla ({ex})")
        if luz < 70:
            return f"demasiado oscura ({luz:.0f}/255)"
        try:
            import base64, io
            from PIL import Image
            with Image.open(base) as a, Image.open(nueva) as b:
                a, b = a.convert("RGB"), b.convert("RGB")
                a.thumbnail((512, 512)); b.thumbnail((512, 512))
                lienzo = Image.new("RGB", (a.width + b.width + 10, max(a.height, b.height)), "white")
                lienzo.paste(a, (0, 0)); lienzo.paste(b, (a.width + 10, 0))
                buf = io.BytesIO(); lienzo.save(buf, "JPEG", quality=85)
            r = self.cerebro.ver("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                                 "Comparas caras para una agencia. Responde solo SI o NO y una razón corta.",
                                 "¿La mujer de la derecha es claramente la misma que la de la izquierda (misma cara, pelo "
                                 "rojo largo y rizado, gafas finas) y se le ve bien la cara?", max_tokens=60)
            if re.match(r"\s*NO\b", r or "", re.I):
                return "no se la reconoce: " + r[:80]
        except Exception as ex:
            self.log(f"nexus: no he podido comparar la foto nueva ({ex}); me quedo con la luz")
        return ""

    def animar_foto(self) -> str:
        """Un clip de 5 s con movimiento a partir de una de sus fotos (Wan en Hugging Face, gratis)."""
        fotos, _ = self._material()
        if not (fotos and self.estudio):
            return "No tengo fotos o el estudio de vídeo."
        f = random.choice(fotos)
        destino = CLIPS / f"wan-{int(time.time())}.mp4"
        CLIPS.mkdir(parents=True, exist_ok=True)
        self.estudio.clip(f"the woman in the photo, {f['escena']}, natural movement, smiles at camera, cinematic",
                          f["ruta"], destino, forzar="wan")
        ind = self._indice(CLIPS)
        ind.append({"archivo": destino.name, "escena": f["escena"], "apta": "publica", "origen": "Wan (sin marca)",
                    "foto": f["archivo"], "fecha": time.strftime("%Y-%m-%d")})
        self._guardar_indice(CLIPS, ind)
        self._diario("material", f"Clip nuevo con Wan a partir de {f['archivo']}", ruta=str(destino))
        return "Clip nuevo hecho a partir de una de sus fotos; entra en los próximos vídeos."

    def video_sjinn(self, tema: str) -> str:
        from nexus_crear import sjinn_video
        b = self.e["id"].get("biblia", {})
        destino = CLIPS / f"sjinn-{int(time.time())}.mp4"
        CLIPS.mkdir(parents=True, exist_ok=True)
        sjinn_video(f"Vertical 9:16 short video for TikTok/Reels, Spanish from Spain. Character: "
                    f"{self.e['id'].get('apariencia_en') or b.get('apariencia_en', '')}. Topic: {tema}. Natural, no "
                    "text overlays, no logos.", destino, log=self.log)
        ind = self._indice(CLIPS)
        ind.append({"archivo": destino.name, "escena": tema[:60], "apta": "publica", "origen": "SJinn",
                    "fecha": time.strftime("%Y-%m-%d")})
        self._guardar_indice(CLIPS, ind)
        self._diario("material", f"Vídeo de SJinn: {tema}", ruta=str(destino))
        return f"Vídeo de SJinn hecho («{tema}»); está en su página y entra en los próximos vídeos."

    def _rutina_diaria(self) -> None:
        """Cada día a partir de las 10:00 prepara el plan; cada media hora mira comentarios de YouTube."""
        time.sleep(180)
        while True:
            try:
                hoy = time.strftime("%Y-%m-%d")
                if (int(time.strftime("%H")) >= 10 and self.e.get("id", {}).get("biblia")
                        and not any(c.get("dia") == hoy and c.get("plan_auto") for c in self.e.get("cola", []))
                        and not any(c.get("dia") == hoy and c.get("estado") == "pendiente" and c.get("tipo") in ("foto", "historia", "carrusel")
                                    for c in self.e.get("cola", []))):   # un vídeo pendiente de hoy no frena el plan
                    txt = self.plan_del_dia()
                    self.avisar("Asuka: " + txt)
                hechas = self.publicar_pendientes()
                if hechas:
                    self.avisar("Asuka ha publicado: " + " · ".join(hechas))
                if (int(time.strftime("%H")) >= 9 and (self.e.get("fotos_dia") != hoy or self.e.get("prompts_fotos"))
                        and self.e.get("id", {}).get("biblia")
                        and time.time() - self.e.get("fotos_intento", 0) > 3 * 3600):
                    self.e["fotos_intento"] = time.time()   # 4 fotos al día (antes lo que pidas); sin cupo, en 3 h
                    self._guardar()
                    txt = self.crear_fotos(4 if self.e.get("fotos_dia") != hoy else 2)
                    if "He hecho" in txt:
                        self.e["fotos_dia"] = hoy
                        self._guardar()
                if self.ocupado != "xbox":
                    txt = self.clips_xbox()
                    if txt:
                        self.avisar(txt)
                if (int(time.strftime("%H")) >= 12 and self.e.get("clip_wan_dia") != hoy
                        and self.e.get("id", {}).get("biblia")
                        and time.time() - self.e.get("clip_wan_intento", 0) > 3 * 3600):
                    self.e["clip_wan_intento"] = time.time()   # un clip con movimiento al día; sin cupo, en 3 h
                    self._guardar()
                    txt = self.clip_wan()
                    if txt:
                        self.avisar("Asuka: " + txt)
                self._musica_de_madrugada()
                self._kaggle_rutina()
                self._narrado_rutina()
                if int(time.strftime("%H")) >= 22 and self.e.get("boveda_dia") != time.strftime("%Y-%m-%d"):
                    self.e["boveda_dia"] = time.strftime("%Y-%m-%d")      # la bóveda de Obsidian, cada noche
                    try:
                        import boveda
                        self.log("nexus: " + boveda.exportar())
                    except Exception as ex:
                        self.log(f"nexus: bóveda de Obsidian: {ex!r}"[:200])
                # webs con crédito gratis: una petición al día (de 17 a 21 h) mientras quede crédito en alguna
                hora = int(time.strftime("%H"))
                if 17 <= hora < 21 and self.e.get("clip_web_dia") != hoy and self.e.get("id", {}).get("biblia") \
                        and not ((self.e.get("clip_pedido") or {}).get("t", 0) > time.time() - 20 * 3600):
                    self.e["clip_web_dia"] = hoy
                    self._guardar()
                    if int(time.strftime("%j")) % 3 == 0 and self._web_con_credito(None, "habla"):
                        self.avisar("Asuka: " + self.pedir_habla_web("hedra"))
                    elif self._web_con_credito():
                        self.avisar("Asuka: " + self.pedir_clip_web())
                if int(time.strftime("%H")) >= 9 and self.e.get("rendimiento_dia") != hoy:
                    self.e["rendimiento_dia"] = hoy
                    self.actualizar_rendimiento()
                n = self.leer_comentarios()
                if n:
                    ult = self.e.get("comentarios", [])[-n:]
                    lineas = [f"· {c['autor']} ({c.get('red', 'youtube')}): «{c['texto'][:120]}»"
                              + (f"\n  ✓ contestado sola: {c['respondido']}" if c.get("sola") else
                                 f"\n  → {c['propuesta']}" if c.get("propuesta") else "") for c in ult[-5:]]
                    falta = any(c.get("propuesta") and not c.get("respondido") for c in ult)
                    self.avisar(f"Asuka tiene {n} comentario{'s' if n > 1 else ''} nuevo{'s' if n > 1 else ''}"
                                + (" (los que tienen respuesta propuesta se envían desde su página, botón «Enviar»)"
                                   if falta else "") + ":\n" + "\n".join(lineas))
            except Exception as ex:
                self.log(f"nexus: rutina diaria: {ex!r}")
            for _ in range(6):                    # lo demás cada media hora; publicar, cada 5 minutos (puntual)
                time.sleep(300)
                try:
                    hechas = self.publicar_pendientes()
                    if hechas:
                        self.avisar("Asuka ha publicado: " + " · ".join(hechas))
                except Exception as ex:
                    self.log(f"nexus: publicar: {ex!r}")

    SESIONES = {"cosplay": "cosplay", "gamer room": "su cuarto gamer", "riverside": "paseo por el río",
                "terrace": "terraceo", "plaza": "Plaza de España", "night": "de noche", "dress": "vestidos"}

    def _carrusel_semanal(self, cola: list, hoy: str, hora: str) -> dict | None:
        """Una vez por semana, un carrusel de Instagram con 3-5 fotos de una misma «sesión» (cosplays, el río…)."""
        import datetime
        hace7 = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()
        if any(c.get("tipo") == "carrusel" and c.get("dia", "") >= hace7 for c in cola + self.e.get("cola", [])):
            return None
        fotos, _ = self._material()
        usadas = set(self.e.get("carrusel_usadas", []))
        grupos = []
        for clave, nombre in self.SESIONES.items():
            g = [f for f in fotos if clave in f.get("escena", "") and f["archivo"] not in usadas
                 and self._luz(f["ruta"]) >= 80]
            if len(g) >= 3:
                grupos.append((nombre, g))
        if not grupos:
            return None
        nombre, g = random.choice(grupos)
        random.shuffle(g)
        g = g[:5]
        b = self.e["id"].get("biblia", {})
        d = self._ia("Devuelve SOLO JSON.", f"{self.e['id'].get('nombre')} ({b.get('resumen', BASE)}) sube a Instagram un "
                     f"carrusel de {len(g)} fotos suyas: {nombre} ({'; '.join(f.get('escena', '') for f in g)}). Caption "
                     "de 1-3 frases que invite a pasar las fotos («¿con cuál os quedáis?»…) + 6 hashtags. Habla solo de lo "
                     "que se ve. JSON: {\"caption\": \"…\"}", max_tokens=300)
        texto = self._humano(d.get("caption", ""), "caption", b.get("tono", ""), 600)
        if not texto:
            return None
        self.e.setdefault("carrusel_usadas", []).extend(f["archivo"] for f in g)
        return {"id": f"{hoy}-carrusel-{int(time.time()) % 100000}", "dia": hoy, "red": "instagram", "tipo": "carrusel",
                "plan_auto": True, "archivo": f"referencias/{g[0]['archivo']}",
                "extra": [f"referencias/{f['archivo']}" for f in g[1:]], "texto": texto, "hora": hora,
                "estado": "pendiente", "titulo": f"Carrusel: {nombre}"}

    def actualizar_rendimiento(self) -> str:
        """Alcance, vistas, guardados y compartidos de cada publicación de Instagram → qué le funciona y a qué hora."""
        import datetime
        from nexus_publicar import rendimiento
        try:
            filas = rendimiento()
        except Exception as ex:
            self.log(f"nexus: estadísticas de publicaciones: {ex!r}"[:200])
            return "No he podido leer las estadísticas de Instagram ahora."
        for f in filas:                                   # la hora de Instagram viene en UTC: a la de España
            try:
                t = datetime.datetime.strptime(f["fecha"], "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
                f["hora"] = t.astimezone().strftime("%H")
            except ValueError:
                pass
            f["puntos"] = (f.get("reach") or 0) + 3 * (f.get("saved") or 0) + 3 * (f.get("shares") or 0) \
                + 2 * (f.get("comentarios") or 0) + (f.get("me_gusta") or 0)
        self.e["rendimiento"] = filas
        self._guardar()
        return self.resumen_rendimiento()

    def resumen_rendimiento(self, para_ia: bool = False) -> str:
        filas = [f for f in self.e.get("rendimiento", []) if f.get("reach") is not None]
        if len(filas) < 3:
            return "" if para_ia else ("Aún hay pocas publicaciones para sacar conclusiones; en unos días te digo "
                                       "qué funciona mejor.")
        mejores = sorted(filas, key=lambda f: -f["puntos"])[:3]
        peores = sorted(filas, key=lambda f: f["puntos"])[:2]
        horas: dict = {}
        for f in filas:
            horas.setdefault(f.get("hora", "?"), []).append(f["puntos"])
        hora = max(horas, key=lambda h: sum(horas[h]) / len(horas[h]))
        if para_ia:
            return ("Lo que mejor le ha funcionado en Instagram: " + " | ".join(f"«{f['texto'][:70]}» ({f['tipo']})"
                    for f in mejores) + ". Lo que menos: " + " | ".join(f"«{f['texto'][:50]}»" for f in peores)
                    + f". Mejor hora hasta ahora: las {hora}. Tenlo en cuenta (más de lo que funciona), sin copiar.")
        return ("En Instagram lo que mejor va: " + "; ".join(
            f"«{f['texto'][:50]}» ({f.get('reach', 0)} de alcance, {f.get('saved', 0)} guardados)" for f in mejores)
            + f". La mejor hora hasta ahora, las {hora}.")

    def borrar_de_instagram(self, pista: str) -> str:
        """«nexus, borra de instagram la de akatsuki» → solo si hay una única publicación que encaje."""
        from nexus_publicar import instagram_borrar, instagram_publicaciones
        palabras = [w for w in normalizar(pista).split() if len(w) > 2 and w not in ("del", "las", "los", "que", "una")]
        if not palabras:
            return "Dime qué publicación: una palabra de su texto (por ejemplo «nexus, borra de instagram la de akatsuki»)."
        pubs = instagram_publicaciones(30)
        encajan = [p for p in pubs if all(w in normalizar(p.get("caption") or "") for w in palabras)]
        if not encajan:
            return f"No encuentro ninguna publicación de Instagram con «{pista}»."
        if len(encajan) > 1:
            return ("Hay varias que encajan, dime una palabra más: " + " · ".join(
                f"«{(p.get('caption') or '')[:40]}» ({(p.get('timestamp') or '')[:10]})" for p in encajan[:5]))
        p = encajan[0]
        instagram_borrar(p["id"])
        self._diario("ajuste", f"Borrada de Instagram: {(p.get('caption') or '')[:80]}", url=p.get("permalink", ""))
        return f"Borrada de Instagram: «{(p.get('caption') or '')[:60]}» ({(p.get('timestamp') or '')[:10]})."

    def _musica_de_madrugada(self) -> None:
        """Si a la biblioteca de música le faltan pistas, de 3 a 6 de la mañana se hacen (MusicGen, con prioridad
        mínima). Así sobrevive a un reinicio del portátil."""
        import subprocess
        from nexus_video import ESTILOS, MUSICA
        hoy = time.strftime("%Y-%m-%d")
        if not (3 <= int(time.strftime("%H")) < 6) or self.e.get("musica_intento") == hoy:
            return
        if len(list(MUSICA.glob("*.wav"))) >= 2 * len(ESTILOS):
            return
        guion = next((p for p in (Path.home() / "jarvis/scripts/musica_asuka.py",
                                  Path(__file__).resolve().parent.parent / "scripts/musica_asuka.py") if p.exists()), None)
        if not guion:
            return
        self.e["musica_intento"] = hoy
        self._guardar()
        with open(NX / "musica.log", "a") as log:
            subprocess.Popen(["nice", "-n", "19", sys.executable, str(guion), "--ya"], stdout=log, stderr=log,
                             start_new_session=True)
        self.log("nexus: haciendo la música de fondo que falta (de madrugada)")

    def clips_xbox(self, avisar_vacio: bool = False) -> str:
        """Los clips de Xbox nuevos → vertical para TikTok y Shorts, horizontal para Twitch, con sus textos, a la cola
        (un clip por día). YouTube se publica solo si está conectado; TikTok y Twitch quedan para subir con un clic."""
        import datetime
        from nexus_xbox import buscar, clave, juego, preparar
        vistos = set(self.e.get("xbox_vistos", []))
        nuevos = buscar(NX, vistos)[:6]
        if not nuevos:
            return ("No encuentro clips de Xbox nuevos. Déjalos en Descargas, en un USB enchufado al portátil o "
                    "mándamelos por Telegram con la palabra «xbox».") if avisar_vacio else ""
        b = self.e["id"].get("biblia", {})
        tono = b.get("tono", "")
        dias_ocupados = {c["dia"] for c in self.e.get("cola", []) if c.get("origen") == "xbox"
                         and c.get("estado") == "pendiente"}
        hechos = []
        for p in nuevos:
            self.e.setdefault("xbox_vistos", []).append(clave(p))
            self._guardar()
            nombre_juego = juego(p)
            d = self._ia("Eres community manager de una creadora gamer española. Devuelve SOLO JSON.",
                         f"Creadora: {self.e['id'].get('nombre')}. {b.get('resumen', BASE)} Va a subir un clip suyo "
                         f"jugando a {nombre_juego} (Xbox). Escribe: \"rotulo\" (máx 40 caracteres, lo que pasa o una "
                         "reacción, va encima del vídeo), \"titulo_youtube\" (máx 90, con el nombre del juego), "
                         "\"caption\" (1-2 frases, como lo contaría ella), \"hashtags\" (6: el juego, xbox, gaming y "
                         "otros que se buscan). JSON: {\"rotulo\": …, \"titulo_youtube\": …, \"caption\": …, "
                         "\"hashtags\": […]}", max_tokens=600)
            rotulo = self._humano(d.get("rotulo", nombre_juego), "post", tono, 40)
            caption = self._humano(d.get("caption", ""), "caption", tono, 300)
            tags = " ".join("#" + re.sub(r"\W", "", h.lstrip("#")) for h in (d.get("hashtags") or [])[:6] if h)
            carpeta = NX / "xbox" / f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^a-z0-9]+', '-', nombre_juego.lower())[:30]}"
            try:
                info = preparar(p, carpeta, rotulo)
            except Exception as ex:
                self.log(f"nexus: clip de xbox {p.name}: {ex}")
                continue
            dia = datetime.date.today()
            while dia.isoformat() in dias_ocupados:
                dia += datetime.timedelta(days=1)
            dias_ocupados.add(dia.isoformat())
            texto = f"{caption}\n{tags}".strip()
            rel = carpeta.relative_to(NX)
            base_id = f"xb{int(time.time()) % 1000000}"
            for red, archivo, hora in (("youtube", "vertical.mp4", "18:00"), ("tiktok", "vertical.mp4", "20:00"),
                                       ("twitch", "horizontal.mp4", "21:00")):
                self.e.setdefault("cola", []).append(
                    {"id": f"{base_id}-{red}", "dia": dia.isoformat(), "red": red, "tipo": "video", "origen": "xbox",
                     "archivo": f"{rel}/{archivo}", "texto": texto, "estado": "pendiente", "hora": hora,
                     "titulo": self._humano(d.get("titulo_youtube", nombre_juego), "post", tono, 90)})
            self._guardar()
            self._diario("material", f"Clip de Xbox ({nombre_juego}, {info['duracion']} s) preparado para el "
                                     f"{dia.strftime('%d/%m')}: «{rotulo}»", ruta=str(carpeta / "vertical.mp4"))
            hechos.append(f"{nombre_juego} ({dia.strftime('%d/%m')})")
        if not hechos:
            return "He encontrado clips de Xbox pero no he podido prepararlos; mira el registro." if avisar_vacio else ""
        return (f"Clips de Xbox listos: {', '.join(hechos)}. Uno por día, en vertical para TikTok y Shorts y en "
                "horizontal para Twitch. Están en la página de Asuka, en «Hoy toca», el día que les toca.")

    # ---------------------------------------------------------------- lo que llega por Telegram
    def desde_telegram(self, ruta: Path, pie: str) -> str | None:
        """Una foto o un vídeo con «instagram», «todas», «xbox»… en el texto: se publica. Si no, None (lo de siempre)."""
        from nexus_telegram import EXT_FOTO, EXT_VIDEO, entender
        suf = ruta.suffix.lower()
        es_video = suf in EXT_VIDEO
        if es_video and re.search(r"\bmontaje\b", normalizar(pie or "")):
            return self._toma_montaje(ruta, pie)
        if es_video and re.search(r"\bclip\b", normalizar(pie or "")) and not re.search(r"\bxbox\b", normalizar(pie or "")):
            return self.guardar_clip_recibido(ruta, pie)
        if suf in EXT_FOTO and re.search(r"\bfoto nueva\b|\bnano ?banana\b", normalizar(pie or "")):
            return self.guardar_foto_recibida(ruta, pie)
        if not (es_video or suf in EXT_FOTO):
            return None
        q = entender(pie, es_video)
        if not q:
            return None
        if not q["redes"]:
            return f"Eso no se puede publicar en {', '.join(q['sobran'])}. Dime otra red o «todas»."

        def trabajo():
            try:
                txt = self._publicar_recibido(ruta, q, es_video)
            except Exception as ex:
                self.log(f"nexus: lo de Telegram: {ex!r}")
                txt = f"No he podido prepararlo: {ex}"
            self._diario("athena", txt)
            self.avisar(txt)
        threading.Thread(target=trabajo, daemon=True, name="nexus-telegram").start()
        que = "el clip de Xbox" if q["xbox"] else ("el vídeo" if es_video else "la foto")
        aviso = (f" ({', '.join(q['sobran'])} no admite{'n' if len(q['sobran']) > 1 else ''} este tipo)"
                 if q["sobran"] else "")
        return (f"Recibido {que} para {', '.join(REDES[r]['nombre'] for r in q['redes'])}{aviso}. Lo preparo con su "
                "texto y lo publico; " + ("con vídeo tardo unos minutos. " if es_video else "") + "Te aviso.")

    def _publicar_recibido(self, ruta: Path, q: dict, es_video: bool) -> str:
        from nexus_telegram import LIMITE, copiar, foto_dataurl, fotograma, guardar_foto, marca_tiempo
        b = self.e["id"].get("biblia", {})
        tono = b.get("tono", "")
        carpeta = NX / "subidas" / f"{marca_tiempo()}{'-xbox' if q['xbox'] else ''}"
        carpeta.mkdir(parents=True, exist_ok=True)
        if es_video:
            original = copiar(ruta, carpeta)
            muestra = fotograma(original, carpeta / "muestra.jpg")
        else:
            original = muestra = guardar_foto(ruta, carpeta / "foto.jpg")
        visto = ""
        try:                                          # que el texto hable de lo que se ve
            visto = self.cerebro.ver(foto_dataurl(muestra), "Describe imágenes para una community manager. En español, "
                                     "2 frases, concreto.",
                                     ((f"Es un fotograma de una partida de {q['pista']}. " if q["pista"] else
                                       "Es un fotograma de una partida de videojuego: ¿qué juego parece? ")
                                      + "¿Qué está pasando en la partida? Describe solo lo que se ve; no inventes nombres."
                                      if q["xbox"] else "¿Qué se ve: lugar, ropa, momento, ambiente? Si salen perras, di "
                                      "cuántas y de qué color (la negra y fuego es Jazmín, la blanca con manchas negras es Leia); "
                                      "no nombres a la que no salga. Al final "
                                      "escribe ASUKA:SI si sale una mujer joven pelirroja, o ASUKA:NO si no sale."),
                                     max_tokens=220)
        except Exception as ex:
            self.log(f"nexus: no he podido mirar la imagen: {ex}")
        sale = not re.search(r"ASUKA\s*:\s*NO", visto, re.I)
        visto = re.sub(r"ASUKA\s*:\s*(SI|SÍ|NO)\W*", "", visto, flags=re.I).strip()
        if not visto and not es_video and re.search(r"\b(perr[oa]s?|cuarto|habitacion|coleccion|espada)", q["pista"]):
            sale = False
        redes = q["redes"]
        d = self._ia("Eres community manager de una creadora de contenido española. Devuelve SOLO JSON.",
                     f"Creadora: {self.e['id'].get('nombre')}. {b.get('resumen', BASE)} Regla: {TRANSPARENCIA} "
                     + (("Va a subir un clip suyo jugando a la Xbox"
                         + (f" (el juego y lo que dice ella: «{q['pista']}»; ese es el juego, aunque la descripción "
                            "diga otro)" if q["pista"] else "") + ". Es solo la partida: no salen ni ella ni sus perras, "
                         "así que no las nombres; no inventes nombres de personajes ni de nada que no sepas. ")
                        if q["xbox"] else
                        f"Va a subir {'un vídeo' if es_video else 'una foto'} suya. ")
                     + (f"Se ve: {visto} " if visto else "")
                     + ("Ella NO sale en la foto: es de su mundo (sus perras, su cuarto, sus cosas); habla de eso. "
                        if not (es_video or sale) else "") + (f"Lo que ha dicho ella: {q['pista']}. " if q["pista"] else "")
                     + "Escribe el texto de cada red, distinto en cada una, como lo contaría ella (nada de anuncio ni "
                     "frases hechas, sin muletillas): "
                     + ", ".join(f"{r} (máx {LIMITE[r]} caracteres" + (", con 4-6 hashtags" if r in ("instagram", "tiktok")
                                 else "") + ")" for r in redes)
                     + (". Además \"rotulo\" (máx 38 caracteres, va encima del vídeo: lo que pasa o su reacción)"
                        if es_video else "")
                     + (". Además \"titulo\" (máx 90, título de YouTube/Twitch/Pinterest" + (", con el nombre del juego"
                                                                                           if q["xbox"] else "") + ")")
                     + ". JSON con esas claves.", max_tokens=1500)
        if es_video or sale:                          # sin perras en la imagen, sin nombrarlas
            nombra = re.compile(r"(?i)\b(jazm[ií]n|leia|mis peques|mis perras|las perras)\b")
            if not nombra.search(visto) and not nombra.search(q["pista"]):
                for k, v in list(d.items()):
                    if isinstance(v, str) and nombra.search(v):
                        d[k] = " ".join(f for f in re.split(r"(?<=[.!?…])\s+", v) if not nombra.search(f)) or v
        rotulo = self._humano(d.get("rotulo", ""), "post", tono, 38) if es_video else ""
        titulo = self._humano(d.get("titulo", "") or q["pista"] or "Nuevo", "post", tono, 90)
        archivos = {}
        if es_video:
            from nexus_xbox import preparar
            preparar(original, carpeta, rotulo, xbox=q["xbox"], maximo=59 if q["xbox"] else 90)
            archivos = {r: f"{carpeta.relative_to(NX)}/{'horizontal' if r == 'twitch' else 'vertical'}.mp4" for r in redes}
        else:
            archivos = {r: f"{carpeta.relative_to(NX)}/foto.jpg" for r in redes}
            carpeta_m = REF if sale else ENTORNO          # y queda como material: suyo o de su mundo
            carpeta_m.mkdir(parents=True, exist_ok=True)
            ind = self._indice(carpeta_m)
            nombre = f"tg{marca_tiempo()}.jpg"
            shutil_copy(original, carpeta_m / nombre)
            ind.append({"archivo": nombre, "apta": "publica", "escena": (q["pista"] or visto)[:80], "origen": "telegram",
                        "descripcion": visto[:200]})
            self._guardar_indice(carpeta_m, ind)
        hoy, ahora = time.strftime("%Y-%m-%d"), time.strftime("%H:%M")
        conectadas = self.redes_conectadas()
        hechas, a_mano, fallos = [], [], []
        for r in redes:
            texto = self._humano(d.get(r, "") or titulo, "post" if r in ("x", "facebook") else "caption", tono, LIMITE[r])
            c = {"id": f"tg{int(time.time() * 1000) % 10**9}-{r}", "dia": hoy, "red": r,
                 "tipo": "video" if es_video else "foto", "origen": "xbox" if q["xbox"] else "telegram",
                 "archivo": archivos[r], "texto": texto, "titulo": titulo, "hora": ahora, "estado": "pendiente"}
            self.e.setdefault("cola", []).append(c)
            self._guardar()
            if r in conectadas:
                try:
                    self._publicar(c)
                    hechas.append(f"{REDES[r]['nombre']}: {c.get('url', '')}")
                except Exception as ex:
                    c["error"], c["error_t"] = str(ex)[:200], time.time()
                    self._guardar()
                    fallos.append(f"{REDES[r]['nombre']} ({str(ex)[:80]})")
            else:
                a_mano.append(REDES[r]["nombre"])
        self._diario("material", f"Recibido por Telegram para {', '.join(redes)}" + (f": «{rotulo}»" if rotulo else ""),
                     ruta=str(carpeta / ("vertical.mp4" if es_video else "foto.jpg")))
        partes = []
        if hechas:
            partes.append("Publicado → " + " · ".join(hechas))
        if a_mano:
            partes.append(f"Listo para subir a mano en {', '.join(a_mano)}: en la página de Asuka, «Hoy toca», con "
                          "Descargar y Abrir red (esas redes no dejan publicar desde fuera sin conectarlas)")
        if fallos:
            partes.append("No ha podido publicar en " + ", ".join(fallos))
        return ". ".join(partes) + "."

    def _vigilar_buzon(self) -> None:
        """~/jarvis/nexus/buzon/: lo que manda el PC de Windows con «Enviar a Asuka» (sin límite de tamaño). Cada archivo
        llega con un .txt al lado (las redes y lo que quiera decir); el .txt se manda el último, así que cuando está,
        el archivo ya ha llegado entero."""
        buzon = NX / "buzon"
        hechos = buzon / "hechos"
        time.sleep(60)
        while True:
            try:
                buzon.mkdir(parents=True, exist_ok=True)
                for txt in sorted(buzon.glob("*.txt")):
                    archivo = buzon / txt.stem                 # «video.mp4.txt» → «video.mp4»
                    if not archivo.exists():
                        if time.time() - txt.stat().st_mtime > 3600:
                            txt.unlink(missing_ok=True)
                        continue
                    pie = txt.read_text(encoding="utf-8", errors="ignore").strip() or "todas"
                    hechos.mkdir(exist_ok=True)
                    destino = hechos / f"{time.strftime('%Y%m%d-%H%M%S')}-{archivo.name}"
                    archivo.rename(destino)
                    txt.unlink(missing_ok=True)
                    self.log(f"nexus: del PC llega {archivo.name} para «{pie}»")
                    r = self.desde_telegram(destino, pie if re.search(r"\w", pie) else "todas")
                    if r is None:                              # sin redes reconocibles: a todas las que admitan
                        r = self.desde_telegram(destino, "todas " + pie)
                    if r:
                        self.avisar("💻 " + r)
            except Exception as ex:
                self.log(f"nexus: buzón del PC: {ex!r}")
            time.sleep(20)

    # ---------------------------------------------------------------- vídeos de una sola historia (tomas de Kling…)
    MONTAJES = {   # guiones preparados: la voz de cada toma, en orden
        "paseando a mis peques": [
            "Tarde de parque con mis peques. Jazmín tira de la correa como si llegara tarde a algo.",
            "Leia, en cambio, tiene que oler cada brizna de hierba. Cada una, sin excepción.",
            "Las suelto un rato y desaparecen. Yo detrás, que hoy el gimnasio ya lo llevo hecho.",
            "Al final, banco, sol y dos perras agotadas. Plan perfecto. ¿Y el vuestro?"],
    }

    def _toma_montaje(self, ruta: Path, pie: str) -> str:
        t = normalizar(pie)
        titulo = re.sub(r"^.*?\bmontaje\b\s*(de|del)?\s*", "", t).strip(" .,:") or "sin titulo"
        clave = next((k for k in self.MONTAJES if normalizar(k) in t or t.endswith(normalizar(k))), titulo)
        carpeta = NX / "montajes" / re.sub(r"[^a-z0-9]+", "-", clave)[:40]
        carpeta.mkdir(parents=True, exist_ok=True)
        n = len(list(carpeta.glob("toma*.mp4"))) + 1
        shutil_copy(ruta, carpeta / f"toma{n:02d}.mp4")
        lineas = self.MONTAJES.get(clave) or self.e.get("montajes", {}).get(clave, [])
        self._diario("material", f"Toma {n} para el vídeo «{clave}»", ruta=str(carpeta / f"toma{n:02d}.mp4"))
        if lineas and n >= len(lineas):
            threading.Thread(target=lambda: self.avisar(self.montar_historia(clave)), daemon=True,
                             name="nexus-montaje").start()
            return f"Toma {n} de {len(lineas)} de «{clave}»: están todas. Monto el vídeo con mi voz y te lo mando."
        falta = f" (faltan {len(lineas) - n})" if lineas else ""
        return (f"Guardada la toma {n} de «{clave}»{falta}. Cuando estén todas lo monto sola; o dime "
                f"«nexus, monta {clave}».")

    def montar_historia(self, clave: str) -> str:
        from nexus_video import montar, voz_qwen
        carpeta = NX / "montajes" / re.sub(r"[^a-z0-9]+", "-", clave)[:40]
        tomas = sorted(carpeta.glob("toma*.mp4"))
        if not tomas:
            return f"No tengo tomas para «{clave}»."
        lineas = list(self.MONTAJES.get(clave) or self.e.get("montajes", {}).get(clave, []))
        if len(lineas) < len(tomas):                  # sin guion para alguna toma: lo escribe ella
            b = self.e["id"].get("biblia", {})
            d = self._ia("Eres guionista de vídeos cortos. Devuelve SOLO JSON.",
                         f"Vídeo «{clave}» de {self.e['id'].get('nombre')} ({b.get('tono', '')}), {len(tomas)} tomas de "
                         "5 s. Escribe lo que dice ella en cada una (1-2 frases que se enlacen, español de España, sin "
                         "mencionar la IA). JSON: {\"lineas\": [\"…\"]}", max_tokens=600)
            lineas += (d.get("lineas") or [])[len(lineas):len(tomas)]
        lineas = [self._humano(x, "guion") if i >= len(self.MONTAJES.get(clave, [])) else x
                  for i, x in enumerate(lineas[:len(tomas)])]
        salida_dir = NX / "videos" / time.strftime("%Y%m%d-%H%M%S")
        salida_dir.mkdir(parents=True, exist_ok=True)
        voz = self._voz_asuka()
        escenas = []
        for i, (toma, linea) in enumerate(zip(tomas, lineas)):
            audio = salida_dir / f"voz{i}.wav"
            if voz:
                voz(linea, audio)
            else:
                ref = NX / "voz_ref.wav"
                if not voz_qwen(linea, audio, ref, self.e["id"].get("voz_ref_texto", "")):
                    return "No tengo voz disponible para el montaje ahora mismo."
            escenas.append({"clip": toma, "audio": audio, "texto": linea, "seguido": True, "marca": True})
        nombre = re.sub(r"[^a-z0-9]+", "-", normalizar(clave)).strip("-")[:40] or "historia"
        ruta = montar(escenas, salida_dir, salida_dir / f"{nombre}.mp4", "", self.log)
        caption = self._humano(" ".join(lineas[:2]), "caption", "", 300)
        g = {"titulo": clave.capitalize(), "caption": caption, "hashtags": [], "titulo_youtube": clave.capitalize(),
             "escenas": [{"texto": x} for x in lineas]}
        (salida_dir / "publicacion.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        v = {"titulo": g["titulo"], "ruta": str(ruta), "carpeta": str(salida_dir),
             "fecha": time.strftime("%Y-%m-%d %H:%M"), "publicado": {}}
        self.e.setdefault("videos", []).append(v)
        self.e["pregunta"] = {"clave": "video_ok", "t": time.time(), "video": len(self.e["videos"]) - 1,
                              "texto": "¿Te gusta el vídeo? Si me dices que sí, queda listo para publicar."}
        self._guardar()
        self._diario("video", f"Vídeo de una historia montado: {v['titulo']}", ruta=v["ruta"], caption=caption)
        try:
            self.enviar_documento(str(ruta), f"{v['titulo']}\n\n{caption}")
        except Exception:
            pass
        return f"Vídeo «{v['titulo']}» montado con mi voz ({len(tomas)} tomas). ¿Te gusta? Si me dices que sí, queda listo para publicar."

    def entregas_hoy(self) -> str:
        """Lo de hoy en todas las redes: fotos en las que sale ella (sola o con sus peques) y sus clips con movimiento
        real (Kling…) convertidos en Reel/TikTok/Short con su voz, a horas repartidas de la tarde-noche."""
        txt = self.plan_del_dia(forzar=True, solo_ella=True)
        hechos = self.videos_movimiento()
        return txt + (" " + hechos if hechos else "")

    ESTILOS_CLIP = [
        "she turns her head to the camera and smiles, a playful wink",
        "she walks two steps towards the camera with confidence, hair moving, slight handheld camera",
        "she laughs naturally and tucks her hair behind her ear, the camera slowly pushes in",
        "she does a small happy dance move, swaying her hips to music",
        "she flips her long red hair and poses, slow orbit camera around her",
        "she waves hello at the camera, then looks away shyly",
        "she adjusts her glasses and gives a mischievous smile, the camera slowly pulls back",
        "she spins once on the spot, then stops facing the camera",
    ]

    def clip_wan(self, cuantos: int = 3) -> str:
        """Cada día, varios clips cortos con movimiento real (Wan 2.2, gratis, sin marca), cada uno de una foto suya
        distinta y con un movimiento distinto, para que cada red tenga su propio vídeo. Para cuando se acaba el cupo."""
        from nexus_crear import SinCupo, animar_foto
        fotos, _ = self._material()
        usadas = set(self.e.get("fotos_animadas", []))
        buenas = [f for f in fotos if f["archivo"] not in usadas and self._luz(f["ruta"]) >= 90]
        random.shuffle(buenas)
        con_peques = [f for f in buenas if re.search(r"\b(dog|dogs|jazmin|leia)\b", f.get("escena", ""))]
        if con_peques and random.random() < 0.4:            # algún día, una con las peques la primera
            buenas.remove(con_peques[0])
            buenas.insert(0, con_peques[0])
        estilos = random.sample(self.ESTILOS_CLIP, len(self.ESTILOS_CLIP))
        hechos = 0
        for i, f in enumerate(buenas[:cuantos]):
            d = self._ia("Eres directora de vídeo. Devuelve SOLO JSON.",
                         f"Foto de una creadora: {f.get('escena', '')}. Describe EN INGLÉS (máx. 40 palabras) un "
                         f"movimiento natural de 4 segundos para animar esa misma foto, en esta línea: «{estilos[i]}». "
                         "Adáptalo a lo que se ve (si está sentada, no camina; si hay perros, que se muevan). Nada que "
                         "cambie la escena ni añada gente. JSON: {\"movimiento_en\": \"…\"}", max_tokens=200)
            mov = d.get("movimiento_en") or estilos[i]
            CLIPS.mkdir(parents=True, exist_ok=True)
            destino = CLIPS / f"wan-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
            origen = "movimiento Wan 2.2 (sin marca)"
            try:
                if i == 0:                                 # el primero del día, en alta calidad (LTX 2.3, con sonido)
                    try:
                        from nexus_crear import video_alta_calidad
                        video_alta_calidad(f["ruta"], mov, destino, 5, self.log)
                        origen = "movimiento LTX 2.3 alta calidad (sin marca)"
                    except SinCupo:
                        raise
                    except Exception as ex:
                        self.log(f"nexus: LTX 2.3 no ha podido ({str(ex)[:120]}); con Wan")
                        animar_foto(f["ruta"], mov, destino, 4, self.log)
                else:
                    animar_foto(f["ruta"], mov, destino, 4, self.log)
            except SinCupo:
                break
            except Exception as ex:
                self.log(f"nexus: Wan no ha podido animar la foto: {ex}")
                break
            ind = self._indice(CLIPS)
            ind.append({"archivo": destino.name, "escena": f.get("escena", ""), "apta": f.get("apta", "publica"),
                        "origen": origen, "foto": f["archivo"], "movimiento": mov,
                        "fecha": time.strftime("%Y-%m-%d")})
            self._guardar_indice(CLIPS, ind)
            self.e.setdefault("fotos_animadas", []).append(f["archivo"])
            self.e["clip_wan_dia"] = time.strftime("%Y-%m-%d")
            self._guardar()
            self._diario("material", f"Clip con movimiento hecho por Athena a partir de {f['archivo']}", ruta=str(destino))
            hechos += 1
        return self.videos_movimiento(maximo=hechos) if hechos else ""

    # ------------------------------------------------------------ vídeos narrados (MoneyPrinterTurbo)
    HORA_NARR = {"tiktok": "14:00", "youtube": "14:15", "instagram": "18:30", "facebook": "18:45"}

    def video_narrado(self, tema: str = "", publicar: bool = True) -> str:
        """Formato largo (25-40 s): ella cuenta algo suyo con su voz. Empieza con un clip suyo (el gancho) y sigue con
        metraje real que encaja con lo que dice, buscado y cortado por MoneyPrinterTurbo; subtítulos karaoke y música."""
        import datetime
        import nexus_mpt
        from nexus_video import montar, duracion
        if not nexus_mpt.disponible():
            return "MoneyPrinterTurbo no está instalado en el portátil."
        voz = self._voz_asuka()
        if voz is None:
            return "No hago el vídeo narrado: no tengo su voz entrenada a mano."
        fuente = next(iter(nexus_mpt.fuentes_con_clave()), "")
        # material local: sus vídeos del entorno y sus clips SIN marca de agua (MoneyPrinterTurbo recorta a vertical, y
        # una marca de un servicio gratis no se recorta nunca)
        locales = sorted(ENTORNO.glob("*.mp4")) + [CLIPS / c["archivo"] for c in self._indice(CLIPS)
                                                   if "sin marca" in normalizar(c.get("origen", ""))
                                                   and (CLIPS / c["archivo"]).exists()
                                                   and c.get("apta", "publica") == "publica"]
        if not fuente and len(locales) < (3 if publicar else 2):     # la prueba vale con menos (no se publica)
            return ("Para los vídeos narrados con metraje real necesito una clave gratis de Pexels (pexels.com/api → "
                    "Your API Key). Mándamela por Telegram así: «clave de pexels» y la clave.")
        clips = [c for c in self._indice(CLIPS) if (CLIPS / c["archivo"]).exists() and not c.get("frase")
                 and c.get("apta", "publica") == "publica" and "sin marca" in normalizar(c.get("origen", ""))
                 and not _apaisado(CLIPS / c["archivo"])]
        if not clips:
            return "No tengo clips suyos sin marca para empezar el vídeo."
        usados = self.e.get("ganchos_usados", [])
        clips.sort(key=lambda c: usados.count(c["archivo"]) + random.random())
        gancho_clip = clips[0]
        b = self.e["id"].get("biblia", {})
        pilares = [p.get("tema", str(p)) if isinstance(p, dict) else str(p) for p in b.get("pilares", [])]
        recientes = [x.get("tema", "") for x in self.e.get("narrados", [])[-12:]]
        d = self._ia("Eres guionista de vídeos cortos narrados. Devuelve SOLO JSON.",
                     f"Creadora: {self.e['id'].get('nombre')} ({b.get('resumen', BASE)}). Temas suyos: "
                     f"{', '.join(pilares) or 'gaming, anime, gimnasio, Sevilla'}. "
                     + (f"Tema pedido: {tema}. " if tema else f"Elige un tema suyo distinto de estos: {recientes}. ")
                     + "Escribe un vídeo de 25 a 35 segundos que cuenta ELLA en primera persona, español de España, "
                     "coloquial y natural: \"gancho\" (la primera frase, de 6 a 11 palabras, que enganche), \"resto\" (60 a "
                     "85 palabras: su experiencia, sus trucos, su top o su opinión; nada de cifras ni datos que puedan ser "
                     "falsos; sin mencionar la IA; no nombres a sus perras), \"terminos\" (6 búsquedas EN INGLÉS de "
                     "metraje de stock en el orden del guion: objetos, lugares, ambientes; 2-3 palabras cada una), "
                     "\"tema\" (3-5 palabras), \"caption\" (1-2 frases) y \"hashtags\" (5). JSON.",
                     max_tokens=700) or {}
        def pulir(original: str) -> str:
            # el humanizador a veces contesta («Claro, te cuento…») o alarga: entonces se queda el original
            h = self._humano(original, "guion")
            n0, n1 = len(original.split()), len(h.split())
            return h if h and 0.6 * n0 <= n1 <= 1.4 * n0 + 2 and not re.match(r"(?i)\W*(claro|vale|aqu[ií] tienes)\b", h) \
                else original
        gancho = pulir(str(d.get("gancho", "")).strip())
        if len(gancho.split()) > 14:                     # el gancho cabe en su clip (≈4 s): la primera frase, corta
            gancho = re.split(r"(?<=[.!?…])\s+", gancho)[0]
            if len(gancho.split()) > 14:
                gancho = " ".join(gancho.split()[:12]).rstrip(",;:")
        resto = self._sin_peques(pulir(str(d.get("resto", "")).strip()))
        terminos = [str(t) for t in (d.get("terminos") or []) if str(t).strip()]
        if not gancho or len(resto.split()) < 25 or (fuente and len(terminos) < 3):
            return "La IA no me ha dado un guion decente para el vídeo narrado; lo intento más tarde."
        gancho = gancho.rstrip(" ,;") + ("" if gancho[-1:] in ".!?…" else ".")
        carpeta = NX / "videos" / f"{time.strftime('%Y%m%d-%H%M%S')}-narrado"
        carpeta.mkdir(parents=True, exist_ok=True)
        voz(gancho, carpeta / "voz0.wav")
        voz(resto, carpeta / "voz1.wav")
        del voz                                          # la voz cargada ocupa memoria: fuera antes del metraje
        import gc
        gc.collect()
        broll = carpeta / "metraje.mp4"
        try:
            nexus_mpt.metraje(resto, terminos, carpeta / "voz1.wav", broll, fuente or "local",
                              [p for p in locales if p.name != gancho_clip["archivo"]], log=self.log)
        except Exception as ex:
            self.log(f"nexus: MoneyPrinterTurbo: {str(ex)[:300]}")
            return f"MoneyPrinterTurbo no ha podido montar el metraje: {str(ex)[:160]}"
        ruta = montar([{"clip": CLIPS / gancho_clip["archivo"], "audio": carpeta / "voz0.wav", "texto": gancho,
                        "seguido": True},
                       {"clip": broll, "audio": carpeta / "voz1.wav", "texto": resto, "seguido": True, "propio": True}],
                      carpeta, carpeta / "narrado.mp4", "", self.log)
        texto = (self._humano(d.get("caption", ""), "caption", "", 280) + "\n"
                 + " ".join("#" + re.sub(r"\W", "", str(h).lstrip("#")) for h in (d.get("hashtags") or [])[:5])).strip()
        (carpeta / "metraje.mp4").unlink(missing_ok=True)
        if not publicar:                                 # de prueba: a Telegram para verlo, sin ponerlo en la cola
            self.enviar_documento(str(ruta), f"Prueba de vídeo narrado: «{gancho}»\n\n{texto}")
            return (f"Vídeo narrado de prueba listo ({duracion(ruta):.0f} s, metraje de "
                    f"{fuente.capitalize() if fuente else 'sus propios clips'}); te lo he mandado por Telegram. No lo "
                    "he puesto en la cola.")
        # cada narrado a dos redes (alternando TikTok+Shorts e Instagram+Facebook), uno por red y día como mucho
        giro = self.e.get("narr_giro", 0)
        destinos = [("tiktok", "youtube"), ("instagram", "facebook")][giro % 2]
        for red in destinos:
            hora = self.HORA_NARR[red]
            ya = {c2["dia"] for c2 in self.e.get("cola", []) if c2.get("origen") == "narrado"
                  and c2.get("red") == red and c2.get("estado") in ("pendiente", "publicado")}
            dia = datetime.date.today()
            while dia.isoformat() in ya or (dia == datetime.date.today() and time.strftime("%H:%M") > hora):
                dia += datetime.timedelta(days=1)
            self.e.setdefault("cola", []).append(
                {"id": f"nar{int(time.time()) % 100000}-{red}", "dia": dia.isoformat(), "red": red, "tipo": "video",
                 "origen": "narrado", "archivo": str(ruta.relative_to(NX)), "texto": self._texto_por_red(texto, red),
                 "titulo": gancho[:90], "hora": hora, "estado": "pendiente"})
        self.e["narr_giro"] = giro + 1
        self.e["narrado_dia"] = time.strftime("%Y-%m-%d")
        self.e["ganchos_usados"] = (usados + [gancho_clip["archivo"]])[-40:]
        self.e["narrados"] = (self.e.get("narrados", []) + [{"tema": d.get("tema", tema), "fecha": time.strftime(
            "%Y-%m-%d"), "fuente": fuente or "local", "archivo": str(ruta.relative_to(NX))}])[-60:]
        self._guardar()
        self._diario("video", f"Vídeo narrado ({fuente or 'sus clips'}): «{gancho}»", ruta=str(ruta), caption=texto)
        return (f"Vídeo narrado listo ({duracion(ruta):.0f} s, metraje de "
                f"{fuente.capitalize() if fuente else 'sus propios clips'}): «{gancho}». Va a "
                f"{' y '.join(REDES[r]['nombre'] for r in destinos)}.")

    # ------------------------------------------------------------ Kaggle (GPU gratis, 30 h a la semana)
    def clips_kaggle(self, cuantos: int = 8) -> str:
        """Lote semanal en Kaggle: varias fotos suyas, cada una con su movimiento, en Wan 2.2 5B sin marca."""
        import nexus_kaggle
        if not nexus_kaggle.disponible():
            return ("Para usar la GPU gratis de Kaggle mándame por Telegram el archivo kaggle.json (Kaggle → Settings → "
                    "API → «Legacy API Credentials» → «Create Legacy API Key»). Lo guardo yo sin enseñarlo. La cuenta tiene "
                    "que tener el móvil verificado para poder usar GPU.")
        ka = self.e.get("kaggle") or {}
        if ka.get("estado") in ("lanzado", "running", "queued"):
            return "Ya hay un lote corriendo en Kaggle; te aviso cuando termine."
        fotos, _ = self._material()
        usadas = set(self.e.get("fotos_animadas", []))
        buenas = [f for f in fotos if f["archivo"] not in usadas and self._luz(f["ruta"]) >= 90] or \
                 [f for f in fotos if self._luz(f["ruta"]) >= 90]
        random.shuffle(buenas)
        if not buenas:
            return "No tengo fotos buenas para animar."
        estilos = random.sample(self.ESTILOS_CLIP, len(self.ESTILOS_CLIP))
        trabajos = []
        for i, f in enumerate(buenas[:cuantos]):
            d = self._ia("Eres directora de vídeo. Devuelve SOLO JSON.",
                         f"Foto de una creadora: {f.get('escena', '')}. Describe EN INGLÉS (máx. 50 palabras) un "
                         f"movimiento natural de 5 segundos para animar esa misma foto, en esta línea: "
                         f"«{estilos[i % len(estilos)]}». Adáptalo a lo que se ve. Nada que cambie la escena ni añada "
                         "gente. JSON: {\"movimiento_en\": \"…\"}", max_tokens=200)
            trabajos.append({"nombre": f"k{i + 1}", "foto": f["ruta"], "archivo": f["archivo"],
                             "escena": f.get("escena", ""), "apta": f.get("apta", "publica"),
                             "prompt": d.get("movimiento_en") or estilos[i % len(estilos)]})
        try:
            nexus_kaggle.lanzar(trabajos)
        except Exception as ex:
            self.log(f"nexus: Kaggle no ha arrancado: {str(ex)[:300]}")
            return f"Kaggle no ha arrancado: {str(ex)[:200]}"
        self.e["kaggle"] = {"estado": "lanzado", "t": time.time(), "dia": time.strftime("%Y-%m-%d"),
                            "trabajos": [{k: (str(v) if k == "foto" else v) for k, v in t.items()} for t in trabajos]}
        self._guardar()
        self._diario("material", f"Lote de {len(trabajos)} clips lanzado en la GPU de Kaggle")
        return (f"Lanzado en Kaggle un lote de {len(trabajos)} clips con movimiento (Wan 2.2, sin marca). Tarda entre "
                "media hora y un par de horas; cuando acabe me los bajo y te aviso.")

    def _kaggle_rutina(self) -> None:
        """Una vez por semana lanza el lote; mientras corre, mira cada media hora y al acabar se baja los clips."""
        try:
            import nexus_kaggle
            if not nexus_kaggle.disponible() or not self.e.get("id", {}).get("biblia"):
                return
            ka = self.e.get("kaggle") or {}
            if ka.get("estado") in ("lanzado", "running", "queued"):
                st = nexus_kaggle.estado()
                if st in ("running", "queued"):
                    if st != ka["estado"]:
                        ka["estado"] = st
                        self._guardar()
                    if time.time() - ka.get("t", 0) < 11 * 3600:
                        return
                self.avisar("Asuka: " + self._kaggle_recoger(st))
            elif self.e.get("kaggle_auto", True) and time.time() - ka.get("t", 0) > 6.5 * 86400 \
                    and 1 <= int(time.strftime("%H")) < 7 and time.time() - self.e.get("kaggle_intento", 0) > 86400:
                self.e["kaggle_intento"] = time.time()
                self._guardar()
                self.avisar("Asuka: " + self.clips_kaggle())
        except Exception as ex:
            self.log(f"nexus: Kaggle: {ex!r}"[:300])

    def _narrado_rutina(self) -> None:
        import datetime
        try:
            import nexus_mpt
            if not nexus_mpt.disponible() or not self.e.get("id", {}).get("biblia") or self.ocupado:
                return
            ultimo = self.e.get("narrado_dia", "2000-01-01")
            if (datetime.date.today() - datetime.date.fromisoformat(ultimo)).days < (1 if nexus_mpt.GRANDE else 2):
                return                                  # con 16 GB, uno cada noche; con 6,5 GB, uno cada dos
            if not (1 <= int(time.strftime("%H")) < 3) or time.time() - self.e.get("narrado_intento", 0) < 20 * 3600:
                return
            self.e["narrado_intento"] = time.time()
            self._guardar()
            txt = self.video_narrado()
            if txt.startswith("Vídeo narrado listo") or "clave gratis de Pexels" in txt:
                if "clave" not in txt or not self.e.get("aviso_pexels"):
                    self.avisar("Asuka: " + txt)
                if "clave" in txt:
                    self.e["aviso_pexels"] = True
                    self._guardar()
            else:
                self.log(f"nexus: narrado: {txt[:200]}")
        except Exception as ex:
            self.log(f"nexus: narrado: {ex!r}"[:300])

    def _kaggle_recoger(self, st: str) -> str:
        import nexus_kaggle
        ka = self.e.get("kaggle") or {}
        try:
            vids, inf, registro = nexus_kaggle.recoger()
        except Exception as ex:
            vids, inf, registro = [], {}, str(ex)
        por_nombre = {t["nombre"]: t for t in ka.get("trabajos", [])}
        CLIPS.mkdir(parents=True, exist_ok=True)
        ind = self._indice(CLIPS)
        hechos = 0
        for v in vids:
            t = por_nombre.get(v.stem)
            if not t or v.stat().st_size < 50_000:
                continue
            destino = CLIPS / f"kaggle-{time.strftime('%Y%m%d')}-{v.stem}.mp4"
            shutil_copy(v, destino)
            ind.append({"archivo": destino.name, "escena": t.get("escena", ""), "apta": t.get("apta", "publica"),
                        "origen": "movimiento Wan 2.2 Kaggle (sin marca)", "foto": t.get("archivo", ""),
                        "movimiento": t.get("prompt", ""), "fecha": time.strftime("%Y-%m-%d")})
            self.e.setdefault("fotos_animadas", []).append(t.get("archivo", ""))
            hechos += 1
        if hechos:
            self._guardar_indice(CLIPS, ind)
        ka.update(estado="hecho" if hechos else "fallido", fin=time.time(), clips=hechos)
        if not hechos:
            ka["registro"] = registro[-1500:]
            self.log(f"nexus: Kaggle sin clips ({st}): {registro[-600:]!r}")
        self.e["kaggle"] = ka
        self._guardar()
        if hechos:
            self._diario("material", f"{hechos} clips con movimiento bajados de Kaggle")
            return (f"Kaggle ha terminado: {hechos} clips nuevos con movimiento y sin marca. Los voy usando en los "
                    "vídeos de los próximos días.")
        return ("El lote de Kaggle no ha sacado clips (estado: " + st + "). He guardado el registro; dime «nexus, "
                "cómo va kaggle» y te cuento qué ha fallado.")

    def hablar_a_camara(self, frase: str = "") -> str:
        """Ella hablando a cámara con su voz y los labios sincronizados (LTX 2.3: un clip de movimiento + lipsync).
        Gasta ~5 min de GPU: con la cuenta gratis de Hugging Face no da; con PRO, varias al día."""
        from nexus_crear import SinCupo, video_alta_calidad, video_hablando
        if not self.e.get("hf_pro") and self._web_con_credito(None, "habla"):
            # con la cuenta gratis de Hugging Face no llega (pide ~5 min de GPU): mejor Hedra/HeyGen/Vidnoz sin gastar nada
            return self.pedir_habla_web("hedra")
        voz = self._voz_asuka()
        fotos, _ = self._material()
        caras = [f for f in fotos if re.search(r"face|portrait|selfie|closeup|smil", f.get("escena", ""))
                 and self._luz(f["ruta"]) >= 90] or fotos
        if not (voz and caras):
            return "Me falta su voz o una foto suya de cara para hacerlo."
        f = random.choice(caras)
        b = self.e["id"].get("biblia", {})
        if not frase:
            d = self._ia("Devuelve SOLO JSON.", f"{self.e['id'].get('nombre')} ({b.get('resumen', BASE)}) habla a cámara "
                         "a sus seguidores 5 segundos. JSON: {\"frase\": \"lo que dice: 10-16 palabras, español de España "
                         "coloquial, sin mencionar la IA\"}", max_tokens=150)
            frase = self._humano(d.get("frase", ""), "guion") or "¡Hola, peña! ¿Qué tal el día? Contadme algo, que me aburro."
        carpeta = NX / "videos" / f"{time.strftime('%Y%m%d-%H%M%S')}-habla"
        carpeta.mkdir(parents=True, exist_ok=True)
        voz(frase, carpeta / "voz.wav")
        try:
            video_alta_calidad(f["ruta"], "she talks to the camera, friendly, natural head movements", carpeta / "base.mp4",
                               4, self.log)
            video_hablando(f["ruta"], carpeta / "voz.wav", carpeta / "habla.mp4", log=self.log)
        except SinCupo:
            if self._web_con_credito("hedra", "habla"):
                return ("Hoy no queda cupo de GPU para hacerlo yo sola, así que lo hacemos en Hedra: "
                        + self.pedir_habla_web("hedra"))
            return ("Hoy no queda cupo de GPU para el vídeo hablando (gasta unos 5 minutos de GPU y la cuenta gratis "
                    "da unos 3,5 al día). Con Hugging Face PRO saldrían varios al día.")
        CLIPS.mkdir(parents=True, exist_ok=True)
        destino = CLIPS / f"habla-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
        shutil_copy(carpeta / "habla.mp4", destino)
        ind = self._indice(CLIPS)
        ind.insert(0, {"archivo": destino.name, "escena": f"ella hablando a cámara: «{frase}»", "apta": "publica",
                       "origen": "movimiento LTX 2.3 hablando (sin marca)", "foto": f["archivo"],
                       "frase": frase, "fecha": time.strftime("%Y-%m-%d")})
        self._guardar_indice(CLIPS, ind)
        return f"Vídeo de ella hablando hecho: «{frase}». Lo tienes en la página de Asuka."

    def unir_fotos(self, inicio: Path, fin: Path, prompt_en: str = "") -> str:
        """Un clip que va de una foto suya a otra con movimiento real (Wan 2.2 con foto final)."""
        from nexus_crear import SinCupo, animar_foto
        destino = CLIPS / f"wan-{time.strftime('%Y%m%d-%H%M%S')}-union.mp4"
        try:
            animar_foto(inicio, prompt_en or "she moves naturally from the first pose to the second, smooth realistic "
                        "motion, same place, same clothes", destino, 4, self.log, final=fin)
        except SinCupo:
            return "Hoy ya no queda cupo gratis de vídeo; lo intento mañana."
        ind = self._indice(CLIPS)
        ind.append({"archivo": destino.name, "escena": "transición entre dos fotos", "apta": "publica",
                    "origen": "movimiento Wan 2.2 (sin marca)", "foto": inicio.name, "fecha": time.strftime("%Y-%m-%d")})
        self._guardar_indice(CLIPS, ind)
        return self.videos_movimiento(maximo=1) or "Clip hecho; lo tienes en la página de Asuka."

    def videos_movimiento(self, maximo: int = 2) -> str:
        from nexus_video import montar
        usados = set(self.e.get("clips_usados", []))
        clips = [c for c in self._indice(CLIPS) if c["archivo"] not in usados and (CLIPS / c["archivo"]).exists()
                 and re.search(r"kling|movimiento|wan", normalizar(c.get("origen", "")))][:maximo]
        if not clips:
            return ""
        voz = self._voz_asuka()
        if voz is None:
            return "No hago los clips con movimiento: no tengo su voz entrenada a mano."
        b = self.e["id"].get("biblia", {})
        import datetime
        hechos = []
        for n, c in enumerate(clips):
            if c.get("frase"):                             # ya habla ella en el clip (LTX 2.3 con su voz)
                d = self._ia("Devuelve SOLO JSON.", f"Vídeo corto de una creadora española que dice a cámara: "
                             f"«{c['frase']}». JSON: {{\"caption\": \"1-2 frases para Reels/TikTok\", \"hashtags\": [5]}}",
                             max_tokens=250) or {}
                d["frase"] = c["frase"]
            else:
                d = self._ia("Eres guionista de vídeos cortos. Devuelve SOLO JSON.",
                         f"{self.e['id'].get('nombre')} ({b.get('resumen', BASE)}) sube un clip de 4 segundos en el que "
                         f"sale ella: {c.get('escena', '')}. Escribe \"frase\" (lo que dice ella en voz alta: UNA frase de "
                         "6 a 11 palabras, que quepa en 4 segundos, español de España, natural, sin mencionar la IA; si "
                         "salen perros son sus peques Jazmín y Leia, y si no salen, no los nombres), \"caption\" (1-2 frases para Reels/TikTok) y \"hashtags\" (5). JSON.",
                         max_tokens=400)
            if not d.get("frase"):                          # la IA no ha contestado bien: otra vez, más corto
                d = self._ia("Devuelve SOLO JSON.", f"Clip de 5 s de una creadora española: {c.get('escena', '')}. "
                             "JSON: {\"frase\": \"lo que dice ella, 1 frase corta y natural\", \"caption\": \"…\", "
                             "\"hashtags\": [\"…\"]}", max_tokens=200) or {}
            frase = c["frase"] if c.get("frase") else self._humano(d.get("frase", ""), "guion")
            if not frase:
                self.log(f"nexus: sin frase para el clip {c['archivo']}")
                continue
            corta = frase if c.get("frase") else ""        # que quepa en el clip (4 s ≈ 80 letras dichas)
            for trozo in ([] if corta else re.split(r"(?<=[.!?…])\s+", frase)):
                if len(corta) + len(trozo) > 80:
                    break
                corta = (corta + " " + trozo).strip()
            if not corta:                                  # una sola frase larga: se corta en una coma, nunca a medias
                trozo = frase[:80]
                corta = trozo[:trozo.rfind(",")] if "," in trozo else ""
            if not corta:
                self.log(f"nexus: frase demasiado larga para el clip {c['archivo']}: {frase[:60]}…")
                continue
            frase = corta.rstrip(" ,;") + ("" if corta[-1:] in ".!?…" else ".")
            carpeta = NX / "videos" / f"{time.strftime('%Y%m%d-%H%M%S')}-mov{n}"
            carpeta.mkdir(parents=True, exist_ok=True)
            from nexus_video import duracion
            if c.get("frase"):                             # su voz ya va en el clip, con los labios sincronizados
                import subprocess
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(CLIPS / c["archivo"]), "-vn",
                                str(carpeta / "voz0.wav")], check=True)
            else:
                voz(frase, carpeta / "voz0.wav")
            if not c.get("frase") and duracion(carpeta / "voz0.wav") > 1.4 * (duracion(CLIPS / c["archivo"]) or 5):
                frase = re.split(r"(?<=[.!?…])\s+", frase)[0]
                voz(frase, carpeta / "voz0.wav")
            clip = CLIPS / c["archivo"]
            from nexus_video import tiene_audio
            # mudo (Wan, Hunyuan…): sonido real de la escena debajo. Gasta ~3 min de GPU: solo con Hugging Face PRO
            if self.e.get("hf_pro") and not c.get("frase") and not tiene_audio(clip):
                try:
                    from nexus_crear import poner_sonido
                    d_en = self._ia("Devuelve SOLO JSON.", f"Describe EN INGLÉS (máx. 20 palabras) los sonidos de ambiente "
                                    f"de esta escena, sin voces ni música: {c.get('escena', '')}. JSON: {{\"sonido\": \"…\"}}",
                                    max_tokens=80) or {}
                    sonoro = CLIPS / (clip.stem + "-sonido.mp4")
                    if not sonoro.exists():
                        poner_sonido(clip, d_en.get("sonido") or "ambient sounds of the scene, soft footsteps", sonoro, self.log)
                    clip = sonoro
                except Exception as ex:
                    self.log(f"nexus: sin sonido de ambiente para {clip.name} ({str(ex)[:80]})")
            ruta = montar([{"clip": clip, "audio": carpeta / "voz0.wav", "texto": frase, "seguido": True, "propio": bool(c.get("frase")),
                            # con marca de agua o apaisado: entero sobre fondo difuminado (no se recorta)
                            "marca": "sin marca" not in normalizar(c.get("origen", "")) or _apaisado(CLIPS / c["archivo"])}],
                          carpeta, carpeta / f"movimiento-{n}.mp4", "", self.log)
            texto = (self._humano(d.get("caption", ""), "caption", "", 280) + "\n"
                     + " ".join("#" + re.sub(r"\W", "", h.lstrip("#")) for h in (d.get("hashtags") or [])[:5])).strip()
            # cada red su propio vídeo: con 3 o más clips, uno por red; con menos, cada clip a dos redes (TikTok+Shorts o
            # Reels+Facebook, alternando). Cada red como mucho un vídeo con movimiento por noche, en el primer día libre.
            redes = ["tiktok", "instagram", "facebook", "youtube"]
            giro = self.e.get("mov_giro", 0)
            if len(clips) >= 3:
                destinos = [redes[(giro + n) % 4]] + ([redes[(giro + n + 3) % 4]] if len(clips) == 3 and n == 2 else [])
            else:
                destinos = [("tiktok", "youtube"), ("instagram", "facebook")][(giro + n) % 2]
            for red in destinos:
                hora = HORA_MOV[red]
                ya = {c2["dia"] for c2 in self.e.get("cola", []) if c2.get("origen") == "movimiento"
                      and c2.get("red") == red and c2.get("estado") in ("pendiente", "publicado")}
                dia = datetime.date.today()
                while dia.isoformat() in ya or (dia == datetime.date.today() and time.strftime("%H:%M") > hora):
                    dia += datetime.timedelta(days=1)
                self.e.setdefault("cola", []).append(
                    {"id": f"mov{int(time.time()) % 100000}{n}-{red}", "dia": dia.isoformat(), "red": red, "tipo": "video",
                     "origen": "movimiento", "archivo": str(ruta.relative_to(NX)),
                     "texto": self._texto_por_red(texto, red), "titulo": frase[:90], "hora": hora, "estado": "pendiente"})
            self.e.setdefault("clips_usados", []).append(c["archivo"])
            self._guardar()
            self._diario("video", f"Clip con movimiento listo para hoy: «{frase}»", ruta=str(ruta), caption=texto)
            hechos.append(frase)
        self.e["mov_giro"] = self.e.get("mov_giro", 0) + 1
        self._guardar()
        return (f"Y {len(hechos)} vídeo{'s' if len(hechos) > 1 else ''} con movimiento real y su voz, repartidos "
                "entre TikTok, Instagram, Facebook y YouTube (cada red el suyo).") if hechos else ""

    def _texto_por_red(self, texto: str, red: str) -> str:
        """El mismo vídeo no lleva el mismo texto en todas partes: en YouTube y Facebook sin muchos hashtags."""
        cuerpo, _, tags = texto.partition("\n")
        if red == "youtube":
            return (cuerpo + " #Shorts " + " ".join(tags.split()[:2])).strip()
        if red == "facebook":
            return (cuerpo + " " + " ".join(tags.split()[:2])).strip()
        return texto

    def _voz_asuka(self):
        """La voz entrenada en Kaggle (la misma de Athena) para los vídeos, si está elegida («voz_video»: asuka)."""
        if self.e["id"].get("voz_video", "asuka") != "asuka":
            return None
        modelo = Path.home() / "jarvis/voces/es_ES-asuka-medium.onnx"
        if not (modelo.exists() and Path(str(modelo) + ".json").exists()):
            return None
        from piper import PiperVoice
        from nexus_video import voz_piper
        voz = PiperVoice.load(str(modelo))
        try:
            import perfil
            ajustes = perfil.perfil().get("voz") or {}
        except Exception:
            ajustes = {}
        return lambda tx, ruta: voz_piper(voz, tx, ruta, ajustes=ajustes)

    def urls_perfiles(self) -> list[str]:
        """Las páginas de sus redes, para abrirlas al encender y ver lo que ha publicado."""
        out = []
        for red, c in self.e.get("cuentas", {}).items():
            if c.get("estado") == "creada" and c.get("usuario") and red in REDES:
                out.append(REDES[red]["perfil"].format(u=c["usuario"]))
        return out

    def hacer_portadas(self) -> str:
        """Foto de perfil y portadas de cada red con sus fotos verdes (gaming, gimnasio y calle, por ese orden)."""
        from nexus_portadas import generar
        fotos, _ = self._material()
        if not fotos:
            return "No tengo fotos aprobadas del personaje para las portadas."
        orden = {"gaming": 0, "gym": 1, "street": 2}
        fotos.sort(key=lambda f: orden.get(f["escena"].split()[0], 9))
        perfiles = {red: NX / "retratos" / arch for red, arch in (self.e.get("perfil_red") or {}).items()}
        hechas = generar(NX, fotos, self.e["id"].get("nombre", "Nexus"), perfiles_red=perfiles)
        self.e["portadas"] = hechas
        self._guardar()
        self._diario("material", f"Foto de perfil y {len(hechas) - 1} portadas hechas (YouTube, X, Facebook, Twitch, "
                                 "Pinterest)", ruta=str(NX / "portadas/youtube_2560x1440.jpg"))
        def mandar():                                   # a Telegram sin hacer esperar la respuesta
            for h in hechas:
                try:
                    self.enviar_foto(str(NX / h["archivo"]), f"{h['tipo']} {h['red']} ({h['medida']})")
                except Exception as ex:
                    self.log(f"nexus: portada a Telegram: {ex}")
        threading.Thread(target=mandar, daemon=True, name="nexus-portadas").start()
        return (f"Hechas la foto de perfil y las portadas de {len(hechas) - 1} redes con sus fotos. Están en la página "
                "de Asuka, con un botón para descargar cada una y dónde se cambia en cada red.")

    def apuntar_cuenta(self, red: str, usuario: str) -> dict:
        """Desde la página: la persona ha creado la cuenta y escribe el usuario que le ha quedado."""
        red = "x" if red == "twitter" else red
        m = re.search(r"profile\.php\?id=(\d+)|facebook\.com/(?:pages/[^/]+/)?(\d{8,})", usuario)
        if red == "facebook" and m:                     # páginas nuevas: la dirección es profile.php?id=…
            u = f"profile.php?id={m.group(1) or m.group(2)}"
            self.e["cuentas"][red] = {"estado": "creada", "usuario": u, "fecha": time.strftime("%Y-%m-%d")}
            self._guardar()
            self._diario("ajuste", f"Página de Facebook apuntada: {u}")
            return {"ok": True}
        u = usuario.strip().rstrip("/").split("?")[0]
        if "/" in u:                                    # han pegado la dirección entera: lo último es el usuario
            u = u.rsplit("/", 1)[-1]
        u = re.sub(r"[^a-z0-9_.]", "", u.lstrip("@").lower())[:30]
        if red not in REDES or not u:
            return {"ok": False, "error": "red o usuario no válidos"}
        self.e["cuentas"][red] = {"estado": "creada", "usuario": u, "fecha": time.strftime("%Y-%m-%d")}
        self._guardar()
        self._diario("ajuste", f"Cuenta de {REDES[red]['nombre']} creada: @{u}")
        return {"ok": True}

    def _resumen(self) -> str:
        hechos = [TITULOS[p] for p in ORDEN if p in self.e["hechos"]]
        return (f"Nexus va por «{TITULOS[self.e['paso']]}» ({len(hechos)} de {len(ORDEN)} pasos hechos"
                + (f": {', '.join(hechos)}" if hechos else "") + "). Dime «sigue con nexus» para continuar.")

    def continuar(self) -> Respuesta:
        if self.ocupado:
            return Respuesta(f"Estoy en ello ({self.ocupado}); te aviso al terminar.")
        p = self.e["paso"]
        return getattr(self, f"_paso_{p}")()

    # ---------------------------------------------------------------- respuestas
    ORDENES = re.compile(r"^(que|como|cuando|donde|quien|cuanto|cual es|pon|ponme|abre|busca|apaga|enciende|sube|baja|"
                         r"para|dime|cuentame|llama|manda|envia|recuerda|haz una foto|hazme|reproduce|cierra)\b")

    def parece_respuesta(self, texto: str) -> bool:
        """Para no tomar como respuesta lo que es otra orden («qué tiempo hace» mientras espera el nombre)."""
        q = self.e.get("pregunta") or {}
        clave, t = q.get("clave", ""), normalizar(texto).strip(" .?¿!¡")
        palabras = len(t.split())
        if si_no(texto) or (numero(texto) and palabras <= 4):
            return True
        if clave in ("voz", "video_ok", "conexiones", "retrato"):
            return bool(re.search(r"\b(otr[oa]s?|repite|cambia\w*)\b", t)) and palabras <= 5
        if clave == "correo":
            return "@" in texto or "arroba" in t or bool(re.search(r"\b(salta\w*|luego|despues)\b", t))
        if self.ORDENES.match(t) and clave not in ("biblia", "bios"):
            return False
        limite = {"nombre": 3, "cuentas": 3, "idea": 14}.get(clave, 30)
        return palabras <= limite and not re.match(r"^(que|como|cuando|donde|quien|cuanto)\b", t)

    def responder(self, texto: str) -> Respuesta:
        q = self.e.get("pregunta") or {}
        self._diario("tu", texto)
        clave = q.get("clave", "")
        f = getattr(self, f"_resp_{clave}", None)
        if not f:
            self.e["pregunta"] = None
            return self.continuar()
        return f(texto, q)

    # ================================================================ 1. nombre
    def _paso_nombre(self) -> Respuesta:
        d = self._ia("Eres experto en marcas personales para redes sociales. Devuelve SOLO JSON.",
                     f"Propón 8 nombres para este personaje: {BASE} Deben ser cortos, fáciles de decir en español e "
                     "inglés, memorables, sin marcas registradas conocidas. Para cada uno, un usuario (handle) en "
                     "minúsculas sin espacios de máximo 15 caracteres. JSON: {\"nombres\": [{\"nombre\": \"…\", "
                     "\"usuario\": \"…\", \"por_que\": \"…\"}]}")
        lista = d.get("nombres", [])[:8]
        lista_txt = "; ".join(f"{i + 1}, {n['nombre']}" for i, n in enumerate(lista))
        return self._preguntar("nombre", f"Empezamos por el nombre del personaje. Propongo: {lista_txt}. "
                                         "¿Cuál eliges? Dime el número o dime tú otro nombre.", opciones=lista)

    def _resp_nombre(self, texto: str, q: dict) -> Respuesta:
        ops = q.get("opciones") or []
        n = numero(texto)
        if n and 1 <= n <= len(ops):
            elegido = ops[n - 1]
        else:
            nombre = re.sub(r"^(se llama|llamala|ponle|el nombre es|quiero|me gusta)\s+", "", texto.strip(), flags=re.I)
            nombre = nombre.strip(" .\"'«»")[:30]
            if not nombre or si_no(texto) == "no":
                return self._paso_nombre()
            elegido = {"nombre": nombre.title() if nombre.islower() else nombre,
                       "usuario": re.sub(r"[^a-z0-9_.]", "", normalizar(nombre).replace(" ", ""))[:15]}
        u = elegido["usuario"]
        self.e["id"].update(nombre=elegido["nombre"], usuario=u,
                            alternativas=[f"{u}.ia", f"{u}_ia", f"soy{u}", f"{u}oficial"])
        self._hecho("nombre")
        return Respuesta(f"Hecho: se llamará {elegido['nombre']} y su usuario será @{u} (si alguna red lo tiene "
                         f"cogido, usaremos @{u}.ia o @{u}_ia). " + self.continuar().texto)

    # ================================================================ 2. biblia
    def _crear_biblia(self, cambios: str = "") -> dict:
        previa = self.e["id"].get("biblia")
        d = self._ia("Eres guionista y director de marca de influencers virtuales. Devuelve SOLO JSON.",
                     f"Crea la biblia del personaje «{self.e['id']['nombre']}» (@{self.e['id']['usuario']}). Base: {BASE}\n"
                     + (f"Versión anterior: {json.dumps(previa, ensure_ascii=False)}\nCambios pedidos: {cambios}\n" if cambios else "")
                     + "JSON con: \"resumen\" (2 frases en español), \"apariencia_en\" (descripción física detallada EN "
                     "INGLÉS para generar imágenes coherentes: edad aparente adulta, pelo, ojos, piel, ropa típica, estilo; "
                     "sin desnudez), \"personalidad\" (3 rasgos), \"tono\" (cómo habla, con 3 muletillas suyas), "
                     "\"pilares\" (4 temas de contenido con ejemplo cada uno), \"nunca\" (5 cosas que nunca hace: incluye "
                     f"no mentir sobre lo que es si se lo preguntan, no contenido sexual explícito, no política), \"publico\" (a quién se "
                     f"dirige), \"aviso_ia\" (marca muy corta para la bio, 2-4 palabras, p. ej. «✦ creadora digital IA»), "
                     f"\"reglas_conversacion\" (cómo contesta comentarios y mensajes; regla obligatoria: {TRANSPARENCIA})",
                     max_tokens=1800)
        self.e["id"]["biblia"] = d
        self.e["id"]["apariencia_en"] = d.get("apariencia_en", "")
        self.e["id"]["aviso_ia"] = d.get("aviso_ia", "✦ creadora digital IA")
        d.setdefault("reglas_conversacion", TRANSPARENCIA)
        self._guardar()
        return d

    def _paso_biblia(self) -> Respuesta:
        d = self._crear_biblia()
        pil = ", ".join(p.get("tema", str(p)) if isinstance(p, dict) else str(p) for p in d.get("pilares", []))
        return self._preguntar("biblia", f"He escrito la biblia de {self.e['id']['nombre']}: {d.get('resumen', '')} "
                                         f"Temas: {pil}. Está entera en el panel de Nexus. ¿Te vale, o qué le cambio?")

    def _resp_biblia(self, texto: str, q: dict) -> Respuesta:
        if si_no(texto) == "si":
            self._hecho("biblia")
            return Respuesta("Biblia aprobada. " + self.continuar().texto)
        d = self._crear_biblia(texto)
        return self._preguntar("biblia", f"Cambiada: {d.get('resumen', '')} ¿Ahora sí, o cambio algo más?")

    # ================================================================ 3. retrato
    def _paso_retrato(self) -> Respuesta:
        fotos, _ = self._material()
        orden_cara = ("portrait", "closeup", "chair", "street", "motorbike", "mall")   # mejor cuanto antes salga
        caras = sorted((f for f in fotos if any(w in f["escena"] for w in orden_cara)),
                       key=lambda f: min(i for i, w in enumerate(orden_cara) if w in f["escena"]))[:4]
        if caras:                                         # sus fotos de verdad: de ahí sale la foto de perfil
            from PIL import Image, ImageOps
            carpeta = NX / "retratos"
            carpeta.mkdir(exist_ok=True)
            for v in carpeta.glob("candidata*.jpg"):
                v.unlink()
            ops = []
            for i, f in enumerate(caras):
                ruta = carpeta / f"candidata{i + 1}.jpg"
                with Image.open(f["ruta"]) as im:
                    ImageOps.fit(im.convert("RGB"), (720, 720), Image.LANCZOS, centering=(0.5, 0.2)).save(ruta, quality=92)
                ops.append({"ruta": str(ruta), "semilla": 0, "ref": f["archivo"]})
                self.enviar_foto(str(ruta), f"Candidata {i + 1}")
            return self._preguntar("retrato", f"Para la foto de perfil he recortado {len(ops)} de sus fotos (las tienes "
                                              "en el panel y en Telegram). ¿Cuál pongo? Dime el número.", opciones=ops)
        if not self.estudio:
            return Respuesta("No tengo el estudio de imágenes disponible.")
        ap = self.e["id"].get("apariencia_en", "")

        def trabajo():
            carpeta = NX / "retratos"
            carpeta.mkdir(exist_ok=True)
            hechas = []
            for i in range(4):
                semilla = random.randint(1, 2 ** 31 - 1)
                ruta = carpeta / f"candidata{i + 1}.jpg"
                try:
                    self.estudio.imagen(f"Portrait photo of {ap}. Head and shoulders, looking at camera, dark "
                                        "cinematic background with soft red rim light, sharp focus, photorealistic, "
                                        "social media profile picture", 1024, 1024, ruta, semilla)
                    hechas.append({"ruta": str(ruta), "semilla": semilla})
                    self.enviar_foto(str(ruta), f"Candidata {i + 1}")
                except Exception as ex:
                    self.log(f"nexus: retrato {i + 1}: {ex}")
            if not hechas:
                return "No he podido generar retratos ahora (el servicio de imágenes falla o se acabó el cupo de hoy)."
            self.e["pregunta"] = {"clave": "retrato", "t": time.time(), "opciones": hechas,
                                  "texto": "¿Cuál de los retratos es el personaje? Dime el número u «otros»."}
            self._guardar()
            return (f"Tengo {len(hechas)} retratos en el panel de Nexus (y en Telegram). ¿Cuál es "
                    f"{self.e['id']['nombre']}? Dime el número, u «otros» para hacer más.")
        self._en_hilo("retratos", trabajo)
        return Respuesta(f"Hago 4 retratos de {self.e['id']['nombre']}; tardo un par de minutos y te pregunto cuál te gusta.")

    def _resp_retrato(self, texto: str, q: dict) -> Respuesta:
        ops = q.get("opciones") or []
        n = numero(texto)
        if not (n and 1 <= n <= len(ops)):
            self.e["pregunta"] = None
            return self._paso_retrato()
        o = ops[n - 1]
        import shutil
        shutil.copy(o["ruta"], NX / "perfil.jpg")
        self.e["id"]["semilla"] = o["semilla"]
        self._hecho("retrato")
        return Respuesta(f"Elegida la {n}: es la foto de perfil (en el panel, «perfil.jpg»). " + self.continuar().texto)

    # ================================================================ 4. bios
    def _paso_bios(self) -> Respuesta:
        b = self.e["id"].get("biblia", {})
        d = self._ia("Eres copywriter de redes sociales. Devuelve SOLO JSON.",
                     f"Escribe la biografía de {self.e['id']['nombre']} (@{self.e['id']['usuario']}) para cada red, en "
                     f"español de España, en su tono ({b.get('tono', '')}). Personaje: {b.get('resumen', BASE)}. "
                     + (f"Cambios pedidos por el usuario: {b.get('notas_bios')}. " if b.get("notas_bios") else "")
                     + "Escríbela como la escribiría ella, en primera persona o en frases sueltas: NO describas su "
                     "tono ni su forma de hablar (nada de «sarcástica», «frases cortas»), enséñalo. Que no empiece por "
                     "«Vale» ni repita su nombre completo si ya está en el perfil. Que no gire en torno a la IA: solo una marca corta y discreta al final de cada bio (por "
                     f"ejemplo «{self.e['id'].get('aviso_ia', '✦ creadora digital IA')}»), lo mínimo que piden las redes. "
                     "Respeta el máximo de caracteres: "
                     + ", ".join(f"{k} {v['bio']}" for k, v in REDES.items())
                     + ". Para youtube, una descripción de canal de 3-4 frases. Añade \"email_firma\" (firma de correo "
                     "profesional para marcas, 3 líneas). JSON: {\"tiktok\": \"…\", \"instagram\": \"…\", \"youtube\": "
                     "\"…\", \"x\": \"…\", \"twitch\": \"…\", \"pinterest\": \"…\", \"facebook\": \"…\", \"email_firma\": \"…\"}",
                     max_tokens=1500)
        for k, v in REDES.items():
            if k in d:
                d[k] = self._humano(d[k], "bio", b.get("tono", ""), v["bio"])
        self.e["id"]["bios"] = d
        self._guardar()
        ej = d.get("instagram", "")
        return self._preguntar("bios", f"Bios listas para las {len(REDES)} redes y la firma de correo, con la marca de IA mínima al final. "
                                       f"La de Instagram dice: «{ej}». Las tienes en el panel para copiarlas. ¿Te valen, "
                                       "o qué cambio?")

    def _resp_bios(self, texto: str, q: dict) -> Respuesta:
        if si_no(texto) == "si":
            self._hecho("bios")
            return Respuesta("Bios aprobadas. " + self.continuar().texto)
        self.e["id"].setdefault("notas_bios", []).append(texto)
        BASE_EXTRA = "; ".join(self.e["id"]["notas_bios"])
        self.e["id"]["biblia"]["notas_bios"] = BASE_EXTRA
        return self._paso_bios()

    # ================================================================ 5. correo
    def _paso_correo(self) -> Respuesta:
        if not self.es_telegram():
            abrir_web("https://accounts.google.com/signup")
        u = self.e["id"]["usuario"]
        return self._preguntar("correo", f"Ahora el correo del personaje: te abro la página para crear un Gmail. Pon "
                                         f"como nombre {self.e['id']['nombre']} y, si está libre, {u}@gmail.com o "
                                         f"{u}.ia@gmail.com. La verificación con tu móvil y la contraseña las haces tú. "
                                         "Cuando lo tengas, dime la dirección.")

    def _resp_correo(self, texto: str, q: dict) -> Respuesta:
        t = texto.strip().lower().replace(" arroba ", "@").replace(" punto ", ".").replace(" ", "")
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", t)
        if not m:
            if re.search(r"\b(salta|despues|luego)\b", normalizar(texto)):
                self._hecho("correo")
                return Respuesta("Vale, lo dejamos para luego. " + self.continuar().texto)
            return self._preguntar("correo", "No he entendido la dirección. Dímela así: «vexara punto ia arroba gmail "
                                             "punto com», o escríbemela por Telegram.")
        self.e["id"]["correo"] = m.group(0)
        self._hecho("correo")
        return Respuesta(f"Apuntado: {m.group(0)}. " + self.continuar().texto)

    # ================================================================ 6. cuentas
    def _paso_cuentas(self) -> Respuesta:
        falta = [k for k in REDES if k not in self.e["cuentas"]]
        if not falta:
            pend = [REDES[k]["nombre"] for k, v in self.e["cuentas"].items() if v.get("estado") != "creada"]
            self._hecho("cuentas")
            return Respuesta(("Cuentas repasadas" + (f"; quedan pendientes {', '.join(pend)} (cuando las tengas, dime "
                              "«nexus, ya tengo la cuenta de …»)" if pend else ": están todas") + ". ")
                             + self.continuar().texto)
        k = falta[0]
        if not self.es_telegram():
            abrir_web(REDES[k]["alta"])
        return self._preguntar("cuentas", f"Cuenta de {REDES[k]['nombre']} ({len(REDES) - len(falta) + 1} de "
                                          f"{len(REDES)}): te abro la página. Usuario: @{self.e['id']['usuario']}. "
                                          f"{GUIA_ALTA[k]} Cuando esté, dime el usuario que te ha quedado, o «saltar».",
                               red=k)

    def _resp_cuentas(self, texto: str, q: dict) -> Respuesta:
        k = q.get("red")
        t = normalizar(texto)
        if re.search(r"\b(salta\w*|despues|luego|no quiero)\b", t):
            self.e["cuentas"][k] = {"estado": "pendiente"}
        else:
            u = re.sub(r"^(es|el usuario es|me ha quedado|usuario)\s+", "", texto.strip(), flags=re.I)
            u = u.strip(" .@«»\"'").replace(" ", "").lower()
            if si_no(texto) == "si" or not u:
                u = self.e["id"]["usuario"]
            self.e["cuentas"][k] = {"estado": "creada", "usuario": u, "fecha": time.strftime("%Y-%m-%d")}
        self._guardar()
        return self._paso_cuentas()

    # ================================================================ 7. voz
    def _paso_voz(self, intento: int = 0) -> Respuesta:
        from nexus_video import voz_kokoro, voz_qwen_disenar

        def trabajo():
            ruta = NX / "muestra_voz.wav"
            texto = VOZ_TEXTO.format(n=self.e["id"].get("nombre", "Asuka").split()[0])
            if voz_qwen_disenar(texto, VOZ_DESC[intento % len(VOZ_DESC)], ruta):
                origen = "Qwen3-TTS (una voz propia, diseñada para ella)"
                self.e["voz_intento"] = intento
            elif voz_kokoro(texto, ruta):
                origen = "Kokoro"
            elif self.voz is not None:
                from nexus_video import voz_piper
                voz_piper(self.voz.voz, texto, ruta)
                origen = "Piper (provisional: instala Kokoro con bash ~/jarvis/instalar_voz_nexus.sh, suena mucho mejor)"
            else:
                return "No tengo ninguna voz disponible para el personaje."
            self.enviar_documento(str(ruta), "Voz del personaje")
            import subprocess
            subprocess.Popen(["pw-play", str(ruta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.e["pregunta"] = {"clave": "voz", "t": time.time(), "texto": "¿Te vale esta voz?"}
            self._guardar()
            return f"Así suena {self.e['id']['nombre']} con {origen}. ¿Te vale esta voz?"
        self._en_hilo("voz", trabajo)
        return Respuesta("Preparo una muestra de la voz del personaje.")

    def _resp_voz(self, texto: str, q: dict) -> Respuesta:
        if re.search(r"\b(otr[oa]s?|cambia\w*|repite)\b", normalizar(texto)) or si_no(texto) == "no" \
                and "voz_intento" in self.e and self.e["voz_intento"] < len(VOZ_DESC) - 1:
            self.e["pregunta"] = None
            return self._paso_voz(self.e.get("voz_intento", 0) + 1)
        if si_no(texto) == "si" and "voz_intento" in self.e and (NX / "muestra_voz.wav").exists():
            import shutil                                     # esta muestra es SU voz para siempre
            shutil.copy(NX / "muestra_voz.wav", NX / "voz_ref.wav")
            self.e["id"]["voz_ref_texto"] = VOZ_TEXTO.format(n=self.e["id"].get("nombre", "Asuka").split()[0])
        if si_no(texto) == "no":
            self.e["pregunta"] = None
            self._guardar()
            return Respuesta("De acuerdo. Hoy las voces gratis que funcionan en este portátil son Kokoro y Piper; "
                             "cuando aprenda otra mejor te la propongo. Por ahora sigo con esta. "
                             + (self._hecho("voz") or self.continuar().texto))
        self._hecho("voz")
        return Respuesta("Voz elegida. " + self.continuar().texto)

    # ================================================================ 8. vídeos
    def _paso_primer_video(self) -> Respuesta:
        return self._paso_video()

    def _paso_video(self) -> Respuesta:
        b = self.e["id"].get("biblia", {})
        hechos = [v["titulo"] for v in self.e.get("videos", [])][-15:]
        d = self._ia("Eres estratega de contenido viral en TikTok, Reels y Shorts en España. Devuelve SOLO JSON.",
                     f"Personaje: {self.e['id']['nombre']}. {b.get('resumen', BASE)} Temas: {b.get('pilares', '')}. "
                     f"Ya hechos: {hechos}. Propón 5 ideas de vídeo corto (30-45 s) con gancho fuerte en los primeros 3 "
                     "segundos, en su tono, aprovechando lo que se habla ahora en gaming/anime/gym. JSON: {\"ideas\": "
                     "[{\"titulo\": \"…\", \"gancho\": \"…\"}]}")
        ideas = d.get("ideas", [])[:5]
        txt = "; ".join(f"{i + 1}, {x['titulo']}" for i, x in enumerate(ideas))
        return self._preguntar("idea", f"Ideas para el vídeo: {txt}. ¿Cuál hago? Dime el número o tu propia idea.",
                               opciones=ideas)

    def _resp_idea(self, texto: str, q: dict) -> Respuesta:
        ops = q.get("opciones") or []
        n = numero(texto)
        idea = ops[n - 1] if n and 1 <= n <= len(ops) else {"titulo": texto.strip(), "gancho": ""}
        self.e["pregunta"] = None
        self._guardar()

        def trabajo():
            from nexus_video import crear_corto, voz_piper
            b = self.e["id"].get("biblia", {})
            fotos, clips = self._material(tuple(k for k, v in (self.e.get("mezcla") or MEZCLA).items() if v))
            lugares = ", ".join(sorted({x["escena"] for x in fotos + clips}))
            ent = self._indice(ENTORNO)
            if ent:
                lugares += ("; y fotos de su mundo sin ella (úsalas en alguna escena si encaja, con esas palabras en "
                            "visual_en): " + "; ".join(sorted({x["escena"] for x in ent})))
            perras = re.search(r"jazm|leia|perra|perro", normalizar(idea["titulo"] + " " + idea.get("gancho", "")))
            if perras:
                lugares += (". IMPORTANTE: es un vídeo con sus perras Jazmín y Leia: al menos 3 escenas son de ellas "
                            "(su visual_en debe decir «dogs Jazmin and Leia» y el sitio: river, lake, beach o car), y "
                            "el vídeo trata de la idea, no de otra cosa")
            g = self._ia("Eres guionista de vídeos cortos virales. Devuelve SOLO JSON.",
                         f"Guion de un vídeo vertical de 30-45 segundos para {self.e['id']['nombre']} ({b.get('tono', '')}). "
                         f"Idea: {idea['titulo']}. Gancho: {idea.get('gancho', '')}. 4-6 escenas; cada escena: \"texto\" "
                         "(lo que dice: 2-3 frases en español de España, como si hablara a cámara en una story, con frases que se "
                         "enlazan y siguen el hilo de la escena anterior, conectores naturales —pues, total, que, al final, "
                         "encima—, algún comentario de pasada; nada telegráfico ni de anuncio) y \"visual_en\" (qué se ve, EN "
                         "INGLÉS, con el personaje en un lugar concreto"
                         + (f", eligiendo entre estos lugares de los que hay fotos suyas: {lugares}" if lugares else "")
                         + "). A sus perras las llama «mis peques» (o por su nombre, Jazmín y Leia), con cariño. "
                         "REGLA: solo habla de ellas en las escenas en las que salen (su visual_en es de las perras); si "
                         "en el vídeo no salen, no las nombres. Termina con una llamada a seguir dicha con naturalidad. "
                         "Además "
                         "\"titulo\", \"caption\" (español, sin hablar de IA), \"hashtags\" (8, del tema del vídeo), "
                         f"\"titulo_youtube\" (máx 90 car.). Regla del personaje: {TRANSPARENCIA} "
                         "JSON: {\"titulo\": …, \"escenas\": [{\"texto\": "
                         "…, \"visual_en\": …}], \"caption\": …, \"hashtags\": […], \"titulo_youtube\": …}", max_tokens=2000)
            tono = b.get("tono", "")
            self._guion_humano(g, tono)                       # que suene a ella hablando, no a texto de IA
            g["caption"] = self._humano(g.get("caption", ""), "caption", tono, 300)
            carpeta = NX / "videos" / time.strftime("%Y%m%d-%H%M%S")
            reserva = (lambda tx, ruta: voz_piper(self.voz.voz, tx, ruta)) if self.voz is not None else None
            self._recoger_descargas()
            ref = NX / "voz_ref.wav"
            voz_ref = (ref, self.e["id"]["voz_ref_texto"]) if ref.exists() and self.e["id"].get("voz_ref_texto") else None
            ruta = crear_corto(g, self.e["id"], carpeta, self.estudio.imagen, voz_reserva=reserva, log=self.log,
                               fuente=self._fuente(set()), voz_ref=voz_ref, voz_propia=self._voz_asuka())
            (carpeta / "publicacion.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
            v = {"titulo": g.get("titulo", idea["titulo"]), "ruta": str(ruta), "carpeta": str(carpeta),
                 "fecha": time.strftime("%Y-%m-%d %H:%M"), "publicado": {}}
            self.e.setdefault("videos", []).append(v)
            self._diario("video", f"Vídeo creado: {v['titulo']}", ruta=v["ruta"], caption=g.get("caption", ""))
            self.e["pregunta"] = {"clave": "video_ok", "t": time.time(), "video": len(self.e["videos"]) - 1,
                                  "texto": "¿Te gusta el vídeo? Si me dices que sí, queda listo para publicar."}
            self._guardar()
            g["etiqueta_ia_red"] = True      # al publicar: casilla oficial «generado con IA» de cada red
            (carpeta / "publicacion.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
            self.enviar_documento(str(ruta), f"{v['titulo']}\n\n{g.get('caption', '')}\n{' '.join(g.get('hashtags', []))}"
                                             "\n\nAl subirlo, activa la casilla de la red «contenido generado con IA» "
                                             "(TikTok: Más opciones → Contenido generado por IA; YouTube: contenido "
                                             "alterado o sintético → Sí; Instagram: Etiqueta de IA).")
            return (f"Vídeo terminado: «{v['titulo']}». Lo tienes en el panel de Nexus y en Telegram con su texto y "
                    "etiquetas. ¿Te gusta? Si me dices que sí, queda listo para publicar.")
        self._en_hilo("vídeo", trabajo)
        return Respuesta(f"Hago el vídeo «{idea['titulo']}»: guion, voz, imágenes y montaje. En este portátil tarda unos "
                         "5-10 minutos; te aviso.")

    def _resp_video_ok(self, texto: str, q: dict) -> Respuesta:
        i = q.get("video", -1)
        if si_no(texto) == "no":
            self.e["pregunta"] = None
            self._guardar()
            return Respuesta("Vale, lo descarto. Dime «nexus: otro vídeo» y hago otro, o dime qué cambiarías.")
        try:
            self.e["videos"][int(i)]["aprobado"] = True
        except (IndexError, KeyError, TypeError, ValueError):
            self.e["pregunta"] = None                 # el vídeo de la pregunta ya no está: no se vuelve a preguntar
            self._guardar()
            return Respuesta("Ese vídeo ya no lo tengo; en el panel están los que quedan.")
        if "primer_video" not in self.e["hechos"]:
            self._hecho("primer_video")
        else:
            self.e["pregunta"] = None
            self._guardar()
        return Respuesta("Aprobado. " + self.continuar().texto)

    # ================================================================ 9. conexiones
    def _paso_conexiones(self) -> Respuesta:
        return self._preguntar("conexiones",
                               "Para que publique yo sola hacen falta las conexiones oficiales, gratis, que cada red da "
                               "a sus creadores: YouTube con tu permiso de Google; Instagram con una página de Facebook "
                               "enlazada; X con una clave de desarrollador gratuita; TikTok y Pinterest piden revisar la "
                               "aplicación (unas semanas; mientras, te dejo cada vídeo listo y lo subes tú en dos minutos). "
                               "Empezamos por YouTube, que es la más rápida. ¿Lo hacemos ahora?")

    def _resp_conexiones(self, texto: str, q: dict) -> Respuesta:
        if si_no(texto) == "si":
            self.e["conexiones_pedidas"] = True
            self._hecho("conexiones")
            return Respuesta("Apuntado: la conexión con YouTube es lo siguiente que preparo (la publicación automática "
                             "se activa red a red). " + self.continuar().texto)
        self._hecho("conexiones")
        return Respuesta("Lo dejamos para más adelante. " + self.continuar().texto)

    # ================================================================ 10. rutina
    def _paso_rutina(self) -> Respuesta:
        if self.e["id"].get("calendario"):
            return Respuesta(self._resumen() + " La rutina está en marcha: cada lunes te propongo el plan de la semana.")
        b = self.e["id"].get("biblia", {})
        d = self._ia("Eres estratega de redes sociales. Devuelve SOLO JSON.",
                     f"Plan semanal realista para {self.e['id']['nombre']} ({b.get('resumen', BASE)}) para una persona "
                     "que dedica 30 minutos al día, con vídeos hechos por IA: 4 vídeos cortos por semana (el mismo en "
                     "TikTok, Reels y Shorts), 3 posts en X, 3 pines en Pinterest, 1 correo a la lista cada 2 semanas. "
                     "Horas buenas en España. JSON: {\"semana\": [{\"dia\": \"lunes\", \"tareas\": [\"…\"]}]}")
        self.e["id"]["calendario"] = d.get("semana", [])
        self._hecho("rutina")
        return Respuesta("Plan semanal listo en el panel: 4 vídeos, 3 posts en X, 3 pines y un correo cada dos semanas. "
                         "Cuando quieras otro vídeo, dime «nexus: otro vídeo».")

    # ---------------------------------------------------------------- panel
    def _refrescar_todo(self) -> None:
        """El botón ⟳ del panel: comentarios, estadísticas, seguidores y la bóveda de Obsidian, de una vez."""
        for paso in (self.leer_comentarios, self.actualizar_rendimiento):
            try:
                paso()
            except Exception as ex:
                self.log(f"nexus: refrescar: {ex!r}"[:200])
        try:
            from nexus_publicar import estadisticas
            self._stats, self._stats_t = estadisticas(), time.time()
        except Exception:
            pass
        try:
            import boveda
            boveda.exportar()
        except Exception:
            pass
        self.e["refrescado"] = time.strftime("%H:%M")
        self._guardar()

    @staticmethod
    def miniatura(rel: str, ancho: int = 360) -> Path | None:
        """Miniatura JPEG (foto o fotograma de vídeo), en caché. Si el archivo se apartó a descartadas, la busca allí."""
        import hashlib, subprocess
        ancho = max(80, min(int(ancho), 1080))
        f = (NX / rel).resolve()
        if NX.resolve() not in f.parents:
            return None
        if not f.is_file():
            alt = NX / "descartadas" / Path(rel).name
            if not alt.is_file():
                return None
            f = alt
        cache = NX / ".mini" / (hashlib.md5(f"{f}:{f.stat().st_mtime}:{ancho}".encode()).hexdigest() + ".jpg")
        if cache.is_file():
            return cache
        cache.parent.mkdir(exist_ok=True)
        args = ["ffmpeg", "-v", "error", "-y"]
        if f.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
            args += ["-ss", "1"]
        args += ["-i", str(f), "-frames:v", "1", "-vf", f"scale='min({ancho},iw)':-2", "-q:v", "6", str(cache)]
        try:
            subprocess.run(args, capture_output=True, timeout=40)
        except (OSError, subprocess.SubprocessError):
            return None
        return cache if cache.is_file() else None

    def datos_panel(self) -> dict:
        e = dict(self.e)
        e["titulos"] = TITULOS
        e["orden"] = ORDEN
        e["redes"] = {k: v["nombre"] for k, v in REDES.items()}
        e["enlaces"] = {k: {"perfil": v["perfil"]} for k, v in REDES.items()}
        e["retratos"] = sorted(p.name for p in (NX / "retratos").glob("*.jpg")) if (NX / "retratos").exists() else []
        e["perfil"] = (NX / "perfil.jpg").exists()
        e["portadas"] = self.e.get("portadas", [])
        hoy = time.strftime("%Y-%m-%d")
        e["cola"] = [c for c in self.e.get("cola", []) if c.get("estado") == "pendiente"
                     or (c.get("dia") == hoy and c.get("estado") == "publicado")]
        e["prompts_pendientes"] = len(self.e.get("prompts_fotos", []))
        e["prompts_lista"] = [p["es"][:160] for p in self.e.get("prompts_fotos", [])]
        e["todo_hecho"] = all(p in self.e.get("hechos", []) for p in ORDEN)
        e["youtube"] = self.youtube.estado() if self.youtube else {"conectado": False}
        e["comentarios"] = [c for c in self.e.get("comentarios", []) if not c.get("ignorado")][-60:]
        e["subida"] = {k: v["subir"] for k, v in SUBIR.items()}
        e["conectadas"] = self.redes_conectadas()
        e["auto_publicar"] = self.e.get("auto_publicar", True)
        pp = NX / "portadas" / "perfil_1080.jpg"
        e["portadas_v"] = str(int(pp.stat().st_mtime)) if pp.exists() else ""
        e["referencias"] = self._indice(REF)
        e["clips"] = self._indice(CLIPS)
        if time.time() - getattr(self, "_stats_t", 0) > 3600:          # seguidores: una consulta por hora
            self._stats_t = time.time()

            def _stats():
                try:
                    from nexus_publicar import estadisticas
                    self._stats = estadisticas()
                except Exception:
                    pass
            threading.Thread(target=_stats, daemon=True, name="nexus-stats").start()
        e["estadisticas"] = getattr(self, "_stats", {})
        e["mezcla"] = self.e.get("mezcla") or MEZCLA
        e["diario"] = self._leer_diario()
        if time.time() - getattr(self, "_archivos_t", 0) > 300:   # recorrer todo el material cada 10 s pesaba
            tipos = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".wav"}
            self._archivos = sorted((str(f.relative_to(NX)) for f in NX.rglob("*") if f.suffix.lower() in tipos
                                     and f.is_file() and not f.name.startswith(("esc", "junto", "voz", "img", "metraje"))
                                     and ".mini" not in f.parts and "kaggle" not in f.parts), reverse=True)[:400]
            self._archivos_t = time.time()
        e["archivos"] = self._archivos
        filas = sorted(self.e.get("rendimiento", []), key=lambda r: -(r.get("puntos") or 0))[:5]
        e["mejores"] = [{k: r.get(k) for k in ("texto", "tipo", "hora", "reach", "puntos", "url")} for r in filas]
        e["ocupado"] = self.ocupado
        ident = self.e.get("id", {})
        e["id"] = {k: ident[k] for k in ("nombre", "usuario", "biblia", "calendario") if k in ident}
        return {k: e[k] for k in PANEL if k in e}          # solo lo que pinta el panel (lo interno no viaja al móvil)
