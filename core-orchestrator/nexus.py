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
import time
from pathlib import Path
from typing import Callable

from herramientas import abrir_web, normalizar
from perfil import DATOS
from sistema import Respuesta

NX = DATOS / "nexus"
ESTADO = NX / "estado.json"
REF, CLIPS = NX / "referencias", NX / "clips"
DESCARGAS = [Path.home() / "Descargas", Path.home() / "Downloads"]
WEBS_CLIP = {"deevid": ("DeeVid", "https://deevid.ai/es/model/h3"), "opengen": ("OpenGen", "https://opengen.ai/video"),
             "viggle": ("Viggle", "https://viggle.ai")}
VOZ_DESC = ["Young adult woman from Spain, about 24, warm slightly husky mid-low voice, confident and playful, dry "
            "sarcastic humor, natural Castilian Spanish accent, relaxed pace, like a gamer streamer talking to her chat",
            "Young adult woman from Madrid, clear bright voice with a teasing tone, energetic but not shouting, quick "
            "witty delivery, Castilian Spanish accent, sounds like a popular tech and gaming creator",
            "Young adult woman from Spain, low smooth calm voice, deadpan and ironic, slightly raspy, confident, "
            "Castilian Spanish accent, unhurried like a late-night streamer"]
MEZCLA = {"publica": 60, "revisar": 35, "no": 5}
VOZ_TEXTO = "Hola, soy {n}. Soy un personaje creado con inteligencia artificial, y no, no vengo a caerte bien."
REDES = {
    "tiktok": {"nombre": "TikTok", "alta": "https://www.tiktok.com/signup", "bio": 80},
    "instagram": {"nombre": "Instagram", "alta": "https://www.instagram.com/accounts/emailsignup/", "bio": 150},
    "youtube": {"nombre": "YouTube", "alta": "https://www.youtube.com/create_channel", "bio": 1000},
    "x": {"nombre": "X", "alta": "https://x.com/i/flow/signup", "bio": 160},
    "twitch": {"nombre": "Twitch", "alta": "https://www.twitch.tv/signup", "bio": 300},
    "pinterest": {"nombre": "Pinterest", "alta": "https://www.pinterest.es/business/create/", "bio": 500},
}
GUIA_ALTA = {
    "tiktok": "Regístrate con el correo del personaje y el usuario. Luego: Perfil → menú → Herramientas para creadores → "
              "cambia a cuenta de empresa o creador. Pon la foto y la bio del panel.",
    "instagram": "Regístrate con el correo del personaje. Luego: Configuración → Tipo de cuenta → Cuenta profesional → Creador. "
                 "Pon foto y bio. (Para publicar sola necesitaré una página de Facebook enlazada: lo vemos en las conexiones.)",
    "youtube": "Entra con el Gmail del personaje y crea el canal con el nombre del personaje. Pon foto, banner y descripción "
               "del panel. En Configuración del canal → Opciones avanzadas, marca que el contenido está alterado o es sintético cuando toque.",
    "x": "Regístrate con el correo del personaje y el usuario. Pon foto, banner y bio. En la bio ya va el aviso de IA.",
    "twitch": "Regístrate con el usuario del personaje. Pon foto y bio. (Twitch es en directo: lo usaremos más adelante.)",
    "pinterest": "Crea una cuenta de empresa con el correo del personaje. Categoría: Entretenimiento. Pon foto y bio.",
}
ORDEN = ["nombre", "biblia", "retrato", "bios", "correo", "cuentas", "voz", "primer_video", "conexiones", "rutina"]
TITULOS = {"nombre": "Nombre y usuario", "biblia": "Biblia del personaje", "retrato": "Retrato y foto de perfil",
           "bios": "Biografías por red", "correo": "Correo del personaje", "cuentas": "Cuentas en las redes",
           "voz": "Voz del personaje", "primer_video": "Primer vídeo", "conexiones": "Publicación automática",
           "rutina": "Calendario y rutina"}
BASE = ("Influencer virtual creada con IA (y lo dice abiertamente). Mujer joven pelirroja, gamer y friki: anime "
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


class Nexus:
    def __init__(self, cerebro, decir: Callable[[str], None], log: Callable[[str], None], ui=None, estudio=None,
                 voz=None, avisar: Callable[[str], None] | None = None,
                 enviar_foto: Callable[[str, str], None] | None = None,
                 enviar_documento: Callable[[str, str], bool] | None = None,
                 es_telegram: Callable[[], bool] = lambda: False):
        self.cerebro, self.decir, self.log, self.ui = cerebro, decir, log, ui
        self.estudio, self.voz = estudio, voz
        self.avisar = avisar or (lambda t: None)
        self.enviar_foto = enviar_foto or (lambda r, p="": None)
        self.enviar_documento = enviar_documento or (lambda r, p="": False)
        self.es_telegram = es_telegram
        self.ocupado = ""
        NX.mkdir(parents=True, exist_ok=True)
        self.e = self._leer()

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
        if q.get("texto") and time.time() - q.get("t", 0) < 86400:
            q["t"] = time.time()                         # vuelve a contar el plazo para contestar
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

    # ---------------------------------------------------------------- órdenes
    def manejar(self, texto: str) -> Respuesta | None:
        t = normalizar(texto).strip(" .?¿!¡")
        if not re.search(r"\bnexus\b|\bnexo\b", t):
            return None
        self._diario("tu", texto)
        if re.search(r"\b(panel|pagina)\b", t):
            abrir_web("http://127.0.0.1:8765/nexus")
            return Respuesta("Te abro el panel de Nexus.")
        r = self._ordenes_material(t)
        if r:
            return r
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

    def _recoger_descargas(self) -> list[str]:
        """Los clips que la persona ha bajado de DeeVid, OpenGen o Viggle desde que se los pedí pasan a clips/."""
        p = self.e.get("clip_pedido") or {}
        if not p:
            return []
        nuevos, ind = [], self._indice(CLIPS)
        for d in DESCARGAS:
            for f in sorted(d.glob("*.mp4")) if d.exists() else []:
                if f.stat().st_mtime < p.get("t", 0) - 60 or f.stat().st_size < 50_000:
                    continue
                CLIPS.mkdir(parents=True, exist_ok=True)
                nombre = f"clip{len(ind) + 1:02d}.mp4"
                import shutil
                shutil.move(str(f), CLIPS / nombre)
                ind.append({"archivo": nombre, "escena": p.get("escena", ""), "apta": "publica",
                            "origen": p.get("web", ""), "fecha": time.strftime("%Y-%m-%d")})
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
            v = set(re.findall(r"[a-z]+", visual.lower()))
            return len(v & set(x.get("escena", "").split()))

        def elegir(visual_en: str, i: int):
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
                return "clip", mejor_c["ruta"]
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
        m = re.search(r"\b(prepara|haz|pide)\w* (?:un |otro )?clip(?: (?:en|con) (deevid|opengen|open gen|viggle))?", t)
        if m:
            web = (m.group(2) or "deevid").replace(" ", "")
            fotos, _ = self._material()
            if not fotos:
                return Respuesta("No tengo fotos aprobadas del personaje para animar.")
            usadas = {c.get("foto") for c in self._indice(CLIPS)}
            f = next((x for x in fotos if x["archivo"] not in usadas), random.choice(fotos))
            b = self.e["id"].get("biblia", {})
            idea = self._ia("Eres director de vídeos cortos con IA. Devuelve SOLO JSON.",
                            f"Escribe la instrucción (en inglés, máx. 60 palabras) para animar 5 segundos esta foto del "
                            f"personaje {self.e['id'].get('nombre', '')} ({b.get('resumen', BASE)}). La foto: "
                            f"{f['escena']}. Movimiento natural, cámara cinematográfica, nada sexual. JSON: "
                            "{\"prompt\": \"…\"}")
            nombre, url = WEBS_CLIP[web]
            self.e["clip_pedido"] = {"t": time.time(), "web": nombre, "escena": f["escena"], "foto": f["archivo"]}
            self._guardar()
            self.enviar_foto(str(f["ruta"]), f"Para {nombre}: sube esta foto y pega esto:\n\n{idea.get('prompt', '')}")
            if not self.es_telegram():
                abrir_web(url)
            return Respuesta(f"Te abro {nombre} y te mando por Telegram la foto y la instrucción para pegar. Usa tu "
                             "cuenta gratis; cuando lo tengas, descárgalo (se guarda en Descargas) y dime «nexus, ya "
                             "tengo el clip»: lo cojo yo de ahí.")
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
        if re.search(r"\bmaterial\b", t):
            self._recoger_descargas()
            ind = self._indice(REF)
            cuenta = {a: sum(1 for r in ind if r.get("apta") == a) for a in ("publica", "revisar", "no")}
            return Respuesta(f"Material de {self.e['id'].get('nombre', 'Nexus')}: {len(ind)} fotos ({cuenta['publica']} "
                             f"para usar sola, {cuenta['revisar']} solo si me las apruebas, {cuenta['no']} que no subo) "
                             f"y {len(self._indice(CLIPS))} clips. Están en el panel de Nexus.")
        return None

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
                     "no fingir ser humana, no contenido sexual, no política), \"publico\" (a quién se dirige), "
                     "\"aviso_ia\" (frase corta en español para declarar que es IA, en su tono).", max_tokens=1800)
        self.e["id"]["biblia"] = d
        self.e["id"]["apariencia_en"] = d.get("apariencia_en", "")
        self.e["id"]["aviso_ia"] = d.get("aviso_ia", "Personaje creado con IA")
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
                     + "OBLIGATORIO: cada bio dice claramente que es un personaje creado con IA (por ejemplo «IA» o "
                     "«creada con IA») y respeta el máximo de caracteres: "
                     + ", ".join(f"{k} {v['bio']}" for k, v in REDES.items())
                     + ". Para youtube, una descripción de canal de 3-4 frases. Añade \"email_firma\" (firma de correo "
                     "profesional para marcas, 3 líneas). JSON: {\"tiktok\": \"…\", \"instagram\": \"…\", \"youtube\": "
                     "\"…\", \"x\": \"…\", \"twitch\": \"…\", \"pinterest\": \"…\", \"email_firma\": \"…\"}",
                     max_tokens=1500)
        for k, v in REDES.items():
            if k in d and len(d[k]) > v["bio"]:
                d[k] = d[k][: v["bio"] - 1].rsplit(" ", 1)[0] + "…"
        self.e["id"]["bios"] = d
        self._guardar()
        ej = d.get("instagram", "")
        return self._preguntar("bios", f"Bios listas para las 6 redes y la firma de correo, todas con el aviso de IA. "
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
            g = self._ia("Eres guionista de vídeos cortos virales. Devuelve SOLO JSON.",
                         f"Guion de un vídeo vertical de 30-45 segundos para {self.e['id']['nombre']} ({b.get('tono', '')}). "
                         f"Idea: {idea['titulo']}. Gancho: {idea.get('gancho', '')}. 4-6 escenas; cada escena: \"texto\" "
                         "(lo que dice, frases cortas en español de España, 1-2 frases) y \"visual_en\" (qué se ve, EN "
                         "INGLÉS, con el personaje en un lugar concreto"
                         + (f", eligiendo entre estos lugares de los que hay fotos suyas: {lugares}" if lugares else "")
                         + "). Termina con una llamada a seguir. Además "
                         "\"titulo\", \"caption\" (español, con el aviso de IA al final), \"hashtags\" (8, incluye #IA "
                         "y #AIinfluencer), \"titulo_youtube\" (máx 90 car.). JSON: {\"titulo\": …, \"escenas\": [{\"texto\": "
                         "…, \"visual_en\": …}], \"caption\": …, \"hashtags\": […], \"titulo_youtube\": …}", max_tokens=2000)
            carpeta = NX / "videos" / time.strftime("%Y%m%d-%H%M%S")
            reserva = (lambda tx, ruta: voz_piper(self.voz.voz, tx, ruta)) if self.voz is not None else None
            self._recoger_descargas()
            ref = NX / "voz_ref.wav"
            voz_ref = (ref, self.e["id"]["voz_ref_texto"]) if ref.exists() and self.e["id"].get("voz_ref_texto") else None
            ruta = crear_corto(g, self.e["id"], carpeta, self.estudio.imagen, voz_reserva=reserva, log=self.log,
                               fuente=self._fuente(set()), voz_ref=voz_ref)
            (carpeta / "publicacion.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
            v = {"titulo": g.get("titulo", idea["titulo"]), "ruta": str(ruta), "carpeta": str(carpeta),
                 "fecha": time.strftime("%Y-%m-%d %H:%M"), "publicado": {}}
            self.e.setdefault("videos", []).append(v)
            self._diario("video", f"Vídeo creado: {v['titulo']}", ruta=v["ruta"], caption=g.get("caption", ""))
            self.e["pregunta"] = {"clave": "video_ok", "t": time.time(), "video": len(self.e["videos"]) - 1,
                                  "texto": "¿Te gusta el vídeo? Si me dices que sí, queda listo para publicar."}
            self._guardar()
            self.enviar_documento(str(ruta), f"{v['titulo']}\n\n{g.get('caption', '')}\n{' '.join(g.get('hashtags', []))}")
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
        self.e["videos"][i]["aprobado"] = True
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
    def datos_panel(self) -> dict:
        e = dict(self.e)
        e["titulos"] = TITULOS
        e["orden"] = ORDEN
        e["redes"] = {k: v["nombre"] for k, v in REDES.items()}
        e["retratos"] = sorted(p.name for p in (NX / "retratos").glob("*.jpg")) if (NX / "retratos").exists() else []
        e["perfil"] = (NX / "perfil.jpg").exists()
        e["referencias"] = self._indice(REF)
        e["clips"] = self._indice(CLIPS)
        e["mezcla"] = self.e.get("mezcla") or MEZCLA
        e["diario"] = self._leer_diario()
        e["comentarios"] = self.e.get("comentarios", [])
        tipos = {".jpg", ".jpeg", ".png", ".mp4", ".wav"}
        e["archivos"] = sorted((str(f.relative_to(NX)) for f in NX.rglob("*") if f.suffix.lower() in tipos
                                and f.is_file() and not f.name.startswith(("esc", "junto", "voz", "img"))),
                               reverse=True)[:500]
        e["ocupado"] = self.ocupado
        return e
