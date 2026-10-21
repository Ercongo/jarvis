"""
Saber de Jarvis: lo que aprende por su cuenta y lo que se informa.

  · Investigar:   "investiga sobre la aerotermia", "infórmate a fondo de la ley de vivienda"
                  → busca en internet, lee varias páginas, contrasta y guarda una nota con fuentes
                    (~/jarvis/saber/notas). Después la usa para responder preguntas sobre el tema.
                  "qué sabes sobre la aerotermia", "qué has investigado", "olvida lo que investigaste de X"
  · Tus documentos: "aprende mis documentos" / "actualiza mis documentos" → lee Documentos y Escritorio
                  (pdf, word, excel, texto…) y los indexa. "qué dicen mis documentos sobre el seguro del coche"
                  → responde citando el archivo. Se reindexan solos cada noche.
  · Temas que sigue: "mantenme informado sobre la Fórmula 1", "sigue el tema de la vivienda",
                  "deja de seguir la Fórmula 1", "qué temas sigues", "qué hay de nuevo de mis temas"
                  → cada mañana manda por Telegram un resumen de novedades y lo guarda en la nota del tema.
  · Datos sobre usted: de lo que dice ("mi hija Lucía empieza el cole el lunes") apunta solo los datos
                  personales duraderos en la memoria (la misma de "recuerda que…"; "qué sabes de mí", "olvida…").

Todo el conocimiento se pasa al cerebro (Groq) como contexto cuando la pregunta tiene que ver con él.
"""

from __future__ import annotations

import datetime as dt
import difflib
import html
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Callable

from extras import MEMORIA as MEMORIA_JSON, leer_memoria, guardar_memoria
from herramientas import buscar_web, carpeta_usuario, guardar_config, leer_config, leer_texto, normalizar
from sistema import Respuesta, con_tildes

HOME = Path.home()
SABER = HOME / "jarvis" / "saber"
NOTAS = SABER / "notas"
INDICE = SABER / "documentos.json"
EXT_DOCS = {".txt", ".md", ".pdf", ".docx", ".odt", ".doc", ".rtf", ".xlsx", ".ods", ".csv", ".pptx", ".odp"}
MAX_ARCHIVOS = 1500
MAX_BYTES = 15 * 1024 ** 2
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"

VACIAS = set("""de la que el en y a los se del las un por con no una su para es al lo como mas pero sus le ha me si sin
sobre este ya entre cuando todo esta ser son dos tambien fue habia era muy hasta desde mi porque cual ese eso esa yo tu
ella hay donde quien cuanto cuantos cuanta les nos te ti algo otra otro otros otras cada puede pueden sea han hace
tiene tienen estan estos estas esos esas aqui alli asi bien dice dicen sabes saber dime cuentame jarvis oye favor
que quien cuales the and for are with this that from""".split())
PRIMERA_PERSONA = re.compile(r"\b(mi|mis|me llamo|soy|tengo|trabajo|vivo|estudio|me gusta|me gustan|odio|prefiero|"
                             r"mi mujer|mi marido|mi novia|mi novio|mi hijo|mi hija|mi madre|mi padre|nac[ií])\b", re.I)
SECRETOS = re.compile(r"contrase|password|clave|pin\b|tarjeta|iban|cuenta bancaria|\b\d{8,}\b|token", re.I)


# =============================================================== texto y búsqueda (BM25)

def fichas(texto: str) -> list[str]:
    salida = []
    for w in re.findall(r"[a-z0-9]{3,}", normalizar(texto)):
        if w in VACIAS:
            continue
        salida.append(w[:6])              # raíz aproximada: consumo/consume/consumir → consum
    return salida


def trocear(texto: str, tam: int = 900) -> list[str]:
    parrafos = [p.strip() for p in re.split(r"\n\s*\n|\n(?=#)", texto) if p.strip()]
    trozos, actual = [], ""
    for p in parrafos:
        while len(p) > tam * 1.5:                       # párrafos enormes (PDF sin saltos): a cachos
            corte = p.rfind(". ", 0, tam) + 1 or tam
            trozos.append((actual + "\n" + p[:corte]).strip())
            actual, p = "", p[corte:].strip()
        if len(actual) + len(p) > tam and actual:
            trozos.append(actual.strip())
            actual = ""
        actual += "\n" + p
    if actual.strip():
        trozos.append(actual.strip())
    return trozos


class Buscador:
    """BM25 sencillo, en memoria. Con unos miles de trozos va de sobra rápido en el portátil."""

    def __init__(self, trozos: list[dict]):
        self.trozos = trozos
        self.docs = [Counter(fichas(t["texto"] + " " + t.get("titulo", ""))) for t in trozos]
        self.largos = [sum(d.values()) for d in self.docs]
        self.medio = (sum(self.largos) / len(self.largos)) if self.largos else 1
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def buscar(self, consulta: str, n: int = 4) -> list[tuple[float, int, dict]]:
        q = set(fichas(consulta))
        if not q or not self.docs:
            return []
        res = []
        for i, d in enumerate(self.docs):
            s, aciertos = 0.0, 0
            for w in q:
                f = d.get(w)
                if f:
                    aciertos += 1
                    s += self.idf.get(w, 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * self.largos[i] / self.medio))
            if s > 0:
                res.append((s, aciertos, self.trozos[i]))
        res.sort(key=lambda x: -x[0])
        return res[:n]


def slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(t)).strip("-")[:60] or "tema"


# =============================================================== leer páginas web

def texto_de_html(crudo: str) -> str:
    try:
        from bs4 import BeautifulSoup
        sopa = BeautifulSoup(crudo, "html.parser")
        for x in sopa(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
            x.decompose()
        partes = []
        for el in sopa.find_all(["h1", "h2", "h3", "p", "li", "td"]):
            t = re.sub(r"\s+", " ", el.get_text(" ")).strip()
            if len(t) > 40 or (el.name.startswith("h") and len(t) > 3):
                partes.append(("## " if el.name in ("h2", "h3") else "") + t)
        return "\n".join(partes)
    except ImportError:
        crudo = re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", crudo)
        return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "\n", crudo)))


def leer_pagina(url: str, limite: int = 7000) -> str:
    url = urllib.parse.quote(url, safe=":/?&=%#+@,;~")      # direcciones con tildes (Wikipedia)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=12) as r:
        if "html" not in (r.headers.get("Content-Type") or "html"):
            return ""
        crudo = r.read(1_500_000).decode(r.headers.get_content_charset() or "utf-8", "ignore")
    return texto_de_html(crudo)[:limite]


def noticias_web(tema: str, maximo: int = 5) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    try:
        res = DDGS().news(tema, region="es-es", timelimit="d", max_results=maximo) or []
    except Exception:
        res = []
    return [{"titulo": r.get("title", ""), "url": r.get("url", "") or r.get("href", ""),
             "texto": r.get("body", ""), "fuente": r.get("source", ""), "fecha": r.get("date", "")} for r in res]


# =============================================================== instrucciones para la IA

INSTR_INVESTIGAR = """Eres Jarvis, investigador y mayordomo. Te paso el encargo del usuario y el texto de varias \
páginas web numeradas. Escribe en español de España, usando SOLO lo que dicen las fuentes; si se contradicen o algo \
no está claro, dilo. No inventes cifras ni fechas. Devuelve SOLO JSON:
{"titulo": "tema en 2-6 palabras", "voz": "resumen para decir en voz alta: 3 o 4 frases, sin listas, tuteando al \
usuario", "nota": "nota completa en markdown (350-700 palabras) con apartados ## y, si viene al caso, \
puntos clave, cifras, ventajas e inconvenientes y consejos prácticos; cita las fuentes con [1], [2]…", \
"preguntas": ["2 o 3 preguntas que podría querer investigar después"], \
"encontrado": true o false (false si las fuentes no hablan de lo que pide, p. ej. son de otra empresa con nombre \
parecido; entonces "voz" explica qué has encontrado en su lugar y "nota" queda vacía)}"""

INSTR_RESPONDER = """Eres Jarvis, mayordomo. Responde a la pregunta del usuario usando SOLO los extractos que te paso \
(de sus documentos o de lo que investigaste). Di de qué archivo o nota sale el dato. Si los extractos no lo dicen, \
dilo con franqueza. Español de España, tuteando, sin listas: máximo 4 frases si es por voz."""

INSTR_HECHOS = """Extrae de la frase del usuario SOLO datos personales duraderos sobre él o su entorno que un \
mayordomo debería recordar (nombres y relación de familiares o mascotas, dónde vive o trabaja, profesión, gustos y \
preferencias claras, alergias o dietas, su coche, fechas señaladas sin año concreto). NO apuntes: órdenes, planes \
puntuales, opiniones pasajeras, contraseñas, números de cuenta o tarjeta, ni nada que no haya dicho. Cada dato en \
una frase corta en primera persona del usuario ("mi hija se llama Lucía"). Si no hay nada, lista vacía. \
Devuelve SOLO JSON: {"datos": ["…"]}"""

INSTR_CONSOLIDAR = """Ordenas la memoria de un asistente personal: una lista numerada de datos (con la fecha en \
que se apuntó cada uno). Devuelve la MISMA lista con solo estos cambios:
- Une en uno los datos repetidos o casi iguales.
- Si dos datos se contradicen o uno corrige al otro (p. ej. dónde trabaja), quédate SOLO con el más reciente.
- Si alguno deletrea letras ("S E R V E O"), escribe la palabra junta (Serveo) y usa esa ortografía en todos.
Todo lo demás se queda tal cual, aunque parezca poco importante (instrucciones para el asistente, fechas, gustos, \
descripciones…). No inventes ni añadas nada. Devuelve SOLO JSON: {"datos": ["…", "…"]}"""

INSTR_NOVEDADES = """Eres Jarvis. Te paso noticias recientes sobre unos temas que el usuario sigue. Para cada tema \
con algo realmente nuevo, escribe 1 o 2 frases claras con lo esencial (español de España). Ignora noticias repetidas o \
irrelevantes. Devuelve SOLO JSON: {"temas": [{"tema": "…", "resumen": "…", "fuentes": [1, 3]}]} (fuentes = números \
de las noticias usadas). Si no hay nada nuevo de un tema, no lo incluyas."""


def json_de(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        raise ValueError("la IA no ha devuelto JSON")
    return json.loads(m.group(0))


# =============================================================== el módulo

class Saber:
    def __init__(self, cerebro, decir: Callable[..., None], log=print, ui=None,
                 preguntar: Callable[[str], bool] | None = None,
                 es_telegram: Callable[[], bool] | None = None, avisar: Callable[[str], None] | None = None,
                 enviar_documento: Callable[[str, str], bool] | None = None):
        self.cerebro = cerebro
        self.decir = decir
        self.log = log
        self.ui = ui
        self.preguntar = preguntar or (lambda p: False)
        self.es_telegram = es_telegram or (lambda: False)
        self.avisar = avisar or (lambda t: None)
        self.enviar_documento = enviar_documento or (lambda r, p: False)
        self._buscador: Buscador | None = None
        self._firma = None
        self._lock = threading.Lock()
        self._indexando = False
        self._avisar_fin = False
        self.nex = None                                    # Nex (OpenRouter), lo pone Jarvis
        NOTAS.mkdir(parents=True, exist_ok=True)

    @property
    def ia(self) -> bool:
        return bool(self.cerebro and getattr(self.cerebro, "activo", False))

    def _ia(self, sistema: str, usuario: str, max_tokens: int = 1500, json_: bool = True, timeout: float = 60,
            ligero: bool = False):
        texto = self.cerebro.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                                  formato_json=json_, max_tokens=max_tokens, temperatura=0.3, timeout=timeout,
                                  ligero=ligero)
        return json_de(texto) if json_ else texto.strip()

    # ---------- panel
    def avisar_panel(self, ultimo: str = "") -> None:
        if not self.ui:
            return
        try:
            docs = len(json.loads(INDICE.read_text(encoding="utf-8")).get("archivos", {}))
        except (OSError, ValueError):
            docs = 0
        ev = {"hechos": len(leer_memoria()), "notas": len(list(NOTAS.glob("*.md"))), "docs": docs}
        if ultimo:
            ev["ultimo"] = ultimo[:40]
        self.ui.enviar(tipo="saber", **ev)

    # ---------- conocimiento cargado
    def _trozos(self) -> list[dict]:
        trozos = []
        for nota in sorted(NOTAS.glob("*.md")):
            texto = nota.read_text(encoding="utf-8", errors="ignore")
            titulo = texto.splitlines()[0].lstrip("# ").strip() if texto else nota.stem
            for t in trocear(texto):
                trozos.append({"texto": t, "titulo": titulo, "fuente": f"tu investigación «{titulo}»"})
        try:
            indice = json.loads(INDICE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            indice = {}
        for ruta, info in (indice.get("archivos") or {}).items():
            nombre = Path(ruta).name
            for t in info.get("trozos", []):
                trozos.append({"texto": t, "titulo": nombre, "fuente": f"el archivo «{nombre}»", "ruta": ruta})
        return trozos

    def buscador(self) -> Buscador:
        firma = (tuple((p.name, p.stat().st_mtime) for p in sorted(NOTAS.glob("*.md"))),
                 INDICE.stat().st_mtime if INDICE.exists() else 0)
        with self._lock:
            if self._buscador is None or firma != self._firma:
                self._buscador = Buscador(self._trozos())
                self._firma = firma
            return self._buscador

    def contexto(self, pregunta: str, maximo: int = 1500) -> str:
        """Extractos relacionados con la pregunta, para el cerebro. Vacío si no hay nada que venga al caso."""
        try:
            q = set(fichas(pregunta))
            if len(q) < 1:
                return ""
            res = self.buscador().buscar(pregunta, 3)
        except Exception as e:
            self.log(f"saber: contexto {e!r}")
            return ""
        utiles = [(s, a, t) for s, a, t in res if a >= min(2, len(q)) and a / len(q) >= 0.5 and s >= 1.0]
        partes, total = [], 0
        for _, _, t in utiles:
            trozo = f"[De {t['fuente']}] {t['texto'][:600]}"
            if total + len(trozo) > maximo:
                break
            partes.append(trozo)
            total += len(trozo)
        return "\n".join(partes)

    # ---------- investigar
    def investigar(self, tema: str, peticion: str, a_fondo: bool = False) -> Respuesta:
        if not self.ia:
            return Respuesta("Para investigar necesito la IA en la nube, y ahora mismo no está disponible.")
        tg = self.es_telegram()

        def hilo():
            try:
                texto, nota = self._investigar(tema, peticion, a_fondo)
            except Exception as e:
                self.log(f"saber: investigar {e!r}")
                texto, nota = f"No he podido investigar {tema}: {e}" if isinstance(e, RuntimeError) else \
                    f"No he podido investigar {tema} ({type(e).__name__}). Prueba otra vez en un rato.", None
            if tg:
                self.avisar(texto if not nota else texto + "\n\n" + nota.read_text(encoding="utf-8")[:3300])
            else:
                if nota and self.avisar:
                    try:
                        self.avisar("📚 " + nota.read_text(encoding="utf-8")[:3500])
                    except Exception:
                        pass
                self.decir(texto)
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta(f"Ahora mismo, señor. Me documento sobre {tema} y te cuento en un minuto.")

    def _investigar(self, tema: str, peticion: str, a_fondo: bool) -> tuple[str, Path]:
        consultas = [tema] + ([f"{tema} explicación", f"{tema} 2026"] if a_fondo else [f"{tema} qué es"])
        con_nex = bool(a_fondo and self.nex and self.nex.activo)     # Nex lee mucho más de una vez
        vistos, fuentes = set(), []
        for c in consultas:
            try:
                for r in buscar_web(c, 6):
                    u = r["url"]
                    dominio = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
                    if u in vistos or re.search(r"youtube|tiktok|instagram|facebook|twitter|x\.com|pinterest", dominio):
                        continue
                    vistos.add(u)
                    fuentes.append(r)
            except Exception as e:
                self.log(f"saber: búsqueda {c!r}: {e!r}")
        if not fuentes:
            raise RuntimeError("no encuentro nada en internet; puede que no haya conexión")
        leidas = []
        for r in fuentes:
            if len(leidas) >= (8 if a_fondo and con_nex else 6 if a_fondo else 4):
                break
            try:
                texto = leer_pagina(r["url"], 12000 if con_nex else 7000)
            except Exception as e:
                self.log(f"saber: no leo {r['url']}: {type(e).__name__}")
                texto = ""
            if len(texto) < 400:
                texto = r.get("texto", "")
                if len(texto) < 80:
                    continue
            leidas.append({**r, "contenido": texto})
        if not leidas:
            raise RuntimeError("no he podido leer ninguna página")
        bloque = "\n\n".join(f"[{i + 1}] {r['titulo']} ({r['url']})\n{r['contenido']}" for i, r in enumerate(leidas))
        spec = None
        if con_nex:
            try:
                spec = json_de(self.nex.texto(INSTR_INVESTIGAR, f"Encargo: {peticion}\n\nFuentes:\n{bloque[:90000]}",
                                              max_tokens=5000, json_=True, esfuerzo="medium", timeout=180))
                self.log("saber: investigación redactada por Nex")
            except Exception as e:
                self.log(f"saber: Nex no ha podido ({e}); sigo con Groq")
        spec = spec or self._ia(INSTR_INVESTIGAR, f"Encargo: {peticion}\n\nFuentes:\n{bloque[:16000]}", max_tokens=2200,
                                timeout=90)
        if spec.get("encontrado") is False or not str(spec.get("nota") or "").strip():
            voz = str(spec.get("voz") or "").strip()
            return ((voz + " " if voz else "") + f"No he encontrado información fiable sobre {tema}, así que no "
                    "guardo nada. Si me das más datos, como la web o la ciudad, lo intento otra vez."), None
        titulo = str(spec.get("titulo") or tema).strip()[:80]
        ruta = NOTAS / f"{slug(titulo)}.md"
        hoy = dt.date.today()
        cuerpo = (f"# {titulo}\n\n_Investigado el {hoy.day}/{hoy.month}/{hoy.year} · encargo: {peticion}_\n\n"
                  + str(spec.get("nota") or spec.get("voz") or "").strip() + "\n\n## Fuentes\n"
                  + "\n".join(f"{i + 1}. {r['titulo']} — {r['url']}" for i, r in enumerate(leidas)))
        if ruta.exists():                                         # ya lo había investigado: se añade debajo
            cuerpo = ruta.read_text(encoding="utf-8") + "\n\n---\n\n" + cuerpo.split("\n", 1)[1]
        ruta.write_text(cuerpo, encoding="utf-8")
        if self.ui:
            self.ui.enviar(tipo="resultados", titulo=f"Fuentes · {titulo}", items=[r["titulo"] for r in leidas])
        self.avisar_panel(titulo)
        voz = str(spec.get("voz") or "").strip() or f"Ya tengo una nota sobre {titulo}."
        preguntas = [str(p).strip().strip("¿?").strip() for p in (spec.get("preguntas") or []) if p][:1]
        extra = (" Si quieres, después puedo averiguar " + preguntas[0][:1].lower() + preguntas[0][1:] + ".") \
            if preguntas else ""
        return voz + " Lo he guardado en mi memoria para lo que necesites." + extra, ruta

    # ---------- responder con lo aprendido
    def responder(self, pregunta: str, solo_documentos: bool = False) -> str | None:
        res = self.buscador().buscar(pregunta, 6)
        if solo_documentos:
            res = [r for r in res if r[2].get("ruta")]
        res = [r for r in res if r[1] >= 1][:4]
        if not res:
            return None
        extractos = "\n\n".join(f"[{t['fuente']}]\n{t['texto'][:1200]}" for _, _, t in res)
        if not self.ia:
            mejor = res[0][2]
            return f"Según {mejor['fuente']}: {mejor['texto'][:300]}"
        canal = "Telegram (escrito)" if self.es_telegram() else "voz"
        texto = self._ia(INSTR_RESPONDER + f" Canal: {canal}.", f"Pregunta: {pregunta}\n\nExtractos:\n{extractos}",
                         max_tokens=700, json_=False)
        return texto

    # ---------- documentos del usuario
    def carpetas_docs(self) -> list[Path]:
        cfg = leer_config().get("carpetas_saber")
        if cfg:
            return [Path(c).expanduser() for c in cfg]
        return [carpeta_usuario("DOCUMENTS"), carpeta_usuario("DESKTOP")]

    def indexar(self, avisar_fin: bool = False) -> None:
        with self._lock:
            if avisar_fin:
                self._avisar_fin = True
            if self._indexando:
                return                                         # ya está leyendo: avisará al terminar
            self._indexando = True
        try:
            try:
                previo = json.loads(INDICE.read_text(encoding="utf-8")).get("archivos", {})
            except (OSError, ValueError):
                previo = {}
            nuevo, leidos, n = {}, 0, 0
            for carpeta in self.carpetas_docs():
                if not carpeta.is_dir() or carpeta == HOME:
                    continue
                for f in carpeta.rglob("*"):
                    if n >= MAX_ARCHIVOS:
                        break
                    if f.suffix.lower() not in EXT_DOCS or not f.is_file() or any(p.startswith(".") for p in f.parts):
                        continue
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    if st.st_size > MAX_BYTES or st.st_size == 0:
                        continue
                    n += 1
                    clave = str(f)
                    if clave in previo and previo[clave].get("mtime") == st.st_mtime:
                        nuevo[clave] = previo[clave]
                        continue
                    try:
                        texto = leer_texto(f, limite=60000)
                    except Exception as e:
                        self.log(f"saber: no leo {f.name}: {e!r}")
                        continue
                    if not texto or len(texto.strip()) < 30:
                        continue
                    nuevo[clave] = {"mtime": st.st_mtime, "trozos": trocear(texto)[:80]}
                    leidos += 1
                    time.sleep(0.05)                                 # sin acaparar el procesador
            SABER.mkdir(parents=True, exist_ok=True)
            tmp = INDICE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fecha": dt.datetime.now().isoformat(timespec="minutes"), "archivos": nuevo},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(INDICE)
            self.log(f"saber: {len(nuevo)} documentos indexados ({leidos} nuevos o cambiados)")
            self.avisar_panel(f"{len(nuevo)} documentos")
            if self._avisar_fin:
                self._avisar_fin = False
                self.decir(f"Ya he leído tus documentos: tengo {len(nuevo)} archivos en la memoria. "
                           f"Pregúntame, por ejemplo: qué dicen mis documentos sobre el seguro del coche.")
        except Exception as e:
            self.log(f"saber: indexar {e!r}")
        finally:
            self._indexando = False

    # ---------- datos sobre el usuario, sacados de lo que dice
    def observar(self, frase: str) -> None:
        """En segundo plano tras cada frase: si cuenta algo personal y duradero, se apunta."""
        if not self.ia or not PRIMERA_PERSONA.search(frase) or SECRETOS.search(frase) or len(frase) < 12:
            return
        if not leer_config().get("aprender_de_mi", True):
            return
        if re.match(r"^\s*(recuerda|acuerdate|apunta|memoriza|aprende|olvida|recuerdame)", normalizar(frase)):
            return                                                 # eso ya lo gestiona la memoria explícita

        def hilo():
            try:
                datos = self._ia(INSTR_HECHOS, frase, max_tokens=300, timeout=20, ligero=True).get("datos") or []
            except Exception as e:
                self.log(f"saber: observar {type(e).__name__}")
                return
            memoria = leer_memoria()
            conocidos = [normalizar(d["dato"]) for d in memoria]
            nuevos = []
            for d in datos:
                d = str(d).strip().rstrip(".")
                if not d or len(d) > 160 or SECRETOS.search(d):
                    continue
                if difflib.get_close_matches(normalizar(d), conocidos, n=1, cutoff=0.8):
                    continue
                memoria.append({"dato": d, "fecha": dt.date.today().isoformat(), "origen": "observado"})
                conocidos.append(normalizar(d))
                nuevos.append(d)
            if nuevos:
                guardar_memoria(memoria)
                self.log(f"saber: apuntado sobre el usuario: {nuevos}")
                self.avisar_panel(nuevos[-1])
                self.consolidar_pronto()
        threading.Thread(target=hilo, daemon=True).start()

    # ---------- memoria ordenada: sin duplicados y con lo último que ha dicho
    def consolidar_pronto(self, espera: float = 25) -> None:
        """Tras apuntar algo, en unos segundos (si no llega nada más) se ordena la memoria."""
        if getattr(self, "_temporizador", None):
            self._temporizador.cancel()
        self._temporizador = threading.Timer(espera, self.consolidar)
        self._temporizador.daemon = True
        self._temporizador.start()

    def consolidar(self) -> bool:
        if not self.ia:
            return False
        memoria = leer_memoria()
        if len(memoria) < 2:
            return False
        lista = "\n".join(f"{i + 1}. {d['dato']} ({d.get('fecha', '')})" for i, d in enumerate(memoria))
        try:
            r = self._ia(INSTR_CONSOLIDAR, lista, max_tokens=1500, timeout=40, ligero=True)
        except Exception as e:
            self.log(f"saber: consolidar {type(e).__name__}")
            return False
        nuevos = [re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", str(x)).strip().rstrip(".")
                  for x in (r.get("datos") or []) if str(x).strip()]
        if not nuevos or len(nuevos) < max(1, len(memoria) // 2) or len(nuevos) > len(memoria):
            self.log(f"saber: consolidación descartada ({len(memoria)} → {len(nuevos)})")
            return False
        if [normalizar(d["dato"]) for d in memoria] == [normalizar(x) for x in nuevos]:
            return True
        copia = Path(str(MEMORIA_JSON) + ".bak")
        try:
            copia.write_text(json.dumps(memoria, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        hoy = dt.date.today().isoformat()
        previos = {normalizar(d["dato"]): d for d in memoria}
        guardar_memoria([previos.get(normalizar(x), {"dato": x, "fecha": hoy, "origen": "ordenado"}) for x in nuevos])
        self.log(f"saber: memoria ordenada ({len(memoria)} → {len(nuevos)} datos; copia en {copia.name})")
        self.avisar_panel()
        return True

    # ---------- temas que sigue
    @staticmethod
    def temas() -> list[str]:
        return list(leer_config().get("temas_seguidos") or [])

    def novedades(self, temas: list[str] | None = None) -> tuple[str, str]:
        """(texto para voz, texto para Telegram) con lo nuevo de los temas seguidos."""
        temas = temas or self.temas()
        if not temas:
            return "No sigo ningún tema todavía. Dime, por ejemplo: mantenme informado sobre la Fórmula 1.", ""
        noticias = []
        for tema in temas[:8]:
            for n in noticias_web(tema, 5):
                noticias.append({**n, "tema": tema})
        if not noticias:
            return "No he encontrado novedades de tus temas en las últimas veinticuatro horas.", ""
        bloque = "\n".join(f"[{i + 1}] ({n['tema']}) {n['titulo']} — {n['texto'][:300]}" for i, n in enumerate(noticias))
        try:
            spec = self._ia(INSTR_NOVEDADES, f"Temas: {', '.join(temas)}\n\nNoticias:\n{bloque}", max_tokens=1500)
        except Exception as e:
            self.log(f"saber: novedades {e!r}")
            spec = {"temas": [{"tema": n["tema"], "resumen": n["titulo"], "fuentes": [i + 1]}
                              for i, n in enumerate(noticias[:6])]}
        voz, tg = [], []
        hoy = dt.date.today()
        por_tema: dict[str, list[str]] = {}
        for t in spec.get("temas") or []:
            tema, resumen = str(t.get("tema", "")).strip(), str(t.get("resumen", "")).strip()
            if not resumen:
                continue
            urls = [noticias[k - 1]["url"] for k in t.get("fuentes") or [] if isinstance(k, int) and 0 < k <= len(noticias)]
            por_tema.setdefault(tema, []).append(resumen)
            tg.append(f"▸ {tema}\n{resumen}" + ("".join(f"\n   {u}" for u in urls[:2])))
            ruta = NOTAS / f"{slug(tema)}.md"                         # lo nuevo queda aprendido en su nota
            previo = ruta.read_text(encoding="utf-8") if ruta.exists() else f"# {tema[:1].upper() + tema[1:]}\n"
            ruta.write_text(previo + f"\n\n## Novedades del {hoy.day}/{hoy.month}/{hoy.year}\n{resumen}\n"
                            + "".join(f"- {u}\n" for u in urls), encoding="utf-8")
        voz = [f"Sobre {tema}: " + " ".join(r) for tema, r in por_tema.items()]
        if not voz:
            return "Hoy no hay nada nuevo que merezca la pena en tus temas.", ""
        self.avisar_panel("novedades")
        return " ".join(voz), "🛰 Novedades de tus temas\n\n" + "\n\n".join(tg)

    def _agente(self) -> None:
        """Cada mañana, después del resumen: novedades de los temas por Telegram. Cada noche: reindexa documentos."""
        time.sleep(300)
        if not INDICE.exists():
            self.indexar()
        while True:
            try:
                cfg = leer_config()
                ahora = dt.datetime.now()
                hoy = ahora.date().isoformat()
                hora = cfg.get("resumen_hora", "08:00")
                if self.temas() and f"{ahora:%H:%M}" >= hora and ahora.hour < 14 and cfg.get("ultimas_novedades") != hoy:
                    guardar_config(ultimas_novedades=hoy)
                    _, tg = self.novedades()
                    if tg:
                        self.avisar(tg)
                if ahora.hour == 3 and cfg.get("ultimo_indice") != hoy:
                    guardar_config(ultimo_indice=hoy)
                    self.indexar()
            except Exception as e:
                self.log(f"saber: agente {e!r}")
            time.sleep(60)

    def arrancar(self) -> None:
        self.avisar_panel()
        threading.Thread(target=self._agente, daemon=True).start()

    # ---------- entrada
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)

        # temas que sigue
        m = re.match(r"^(?:mantenme (?:informado|al dia|al tanto)|informame (?:cada dia|a diario|todos los dias|"
                     r"cada manana)|sigue (?:el tema(?: de)?|las noticias(?: de| sobre)?|la actualidad(?: de)?)|"
                     r"avisame de las novedades)\s+(?:sobre|de|del|de la|acerca de)?\s*(.+)$", t)
        if m:
            tema = con_tildes(peticion, m.group(1).strip()) or m.group(1)
            temas = self.temas()
            if any(normalizar(x) == normalizar(tema) for x in temas):
                return Respuesta(f"Ya sigo {tema}. Cada mañana te mando las novedades por Telegram.")
            guardar_config(temas_seguidos=temas + [tema])
            return Respuesta(f"Hecho. Seguiré {tema} y cada mañana te mandaré por Telegram lo nuevo, y lo iré "
                             f"aprendiendo. Si lo quieres ahora, pregúntame qué hay de nuevo de mis temas.")
        m = re.match(r"^(?:deja de seguir|no me informes mas (?:de|sobre)|olvida el tema(?: de)?)\s+(.+)$", t)
        if m:
            temas = self.temas()
            objetivo = difflib.get_close_matches(m.group(1), [normalizar(x) for x in temas], n=1, cutoff=0.5)
            if not objetivo:
                return Respuesta("No sigo ningún tema con ese nombre.")
            quedan = [x for x in temas if normalizar(x) != objetivo[0]]
            guardar_config(temas_seguidos=quedan)
            return Respuesta("Hecho, dejo de seguirlo.")
        if re.search(r"\bque temas (sigues|tienes)\b|\bque noticias (sigues|vigilas)\b", t):
            temas = self.temas()
            if not temas:
                return Respuesta("No sigo ningún tema. Dime, por ejemplo: mantenme informado sobre la Fórmula 1.")
            return Respuesta("Sigo estos temas: " + ", ".join(temas) + ".")
        if re.search(r"\b(que hay de nuevo|novedades)\b.*\bmis temas\b|\bnovedades de (mis|los) temas\b", t):
            if not self.ia:
                return Respuesta("Para eso necesito la IA en la nube, y ahora no está disponible.")
            voz, tg = self.novedades()
            return Respuesta(tg if self.es_telegram() and tg else voz)

        # documentos del usuario
        if re.search(r"^(?:aprende(?:te)?|lee(?:te)?|estudia|indexa|actualiza|repasa|memoriza)\s+(?:todos )?mis "
                     r"(?:documentos|archivos|papeles)\b", t):
            threading.Thread(target=self.indexar, kwargs={"avisar_fin": True}, daemon=True).start()
            return Respuesta("Me pongo a leer tus documentos. Puede tardar unos minutos; te aviso al terminar.")
        m = re.match(r"^(?:que dicen|que pone en|que hay en|busca en|pregunta a|consulta)\s+mis (?:documentos|archivos|papeles)"
                     r"\s*(?:sobre|de|del|acerca de|que hable[n]? de)?\s*(.+)$", t)
        if m:
            if not INDICE.exists():
                threading.Thread(target=self.indexar, daemon=True).start()
                return Respuesta("Todavía no he leído tus documentos. Empiezo ahora; pregúntame otra vez en unos minutos.")
            r = self.responder(con_tildes(peticion, m.group(1)) or m.group(1), solo_documentos=True)
            return Respuesta(r or "No encuentro nada de eso en tus documentos.")

        # investigar
        m = re.match(r"^(?:investiga|averigua|informate|documentate|estudia|aprende|empapate|instruyete)"
                     r"(?:\s+(?:todo|bien|un poco|a fondo|en profundidad|lo que puedas|todo lo que puedas))*"
                     r"\s+(?:sobre|acerca de|de|del|de la|de los|de las)\s+(.+)$", t)
        if m and not re.match(r"^(mi|mis|mí)\b", m.group(1)):
            tema = (con_tildes(peticion, m.group(1)) or m.group(1)).strip(" .")
            a_fondo = bool(re.search(r"\b(a fondo|en profundidad|todo lo que puedas|bien)\b", t))
            return self.investigar(tema, peticion, a_fondo)

        if re.search(r"\bque (has investigado|investigaciones tienes|temas has investigado)\b", t):
            notas = sorted(NOTAS.glob("*.md"), key=lambda p: -p.stat().st_mtime)
            if not notas:
                return Respuesta("Todavía no he investigado nada. Dime, por ejemplo: investiga sobre la aerotermia.")
            titulos = [p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ") for p in notas[:10]]
            if self.ui:
                self.ui.enviar(tipo="resultados", titulo="Investigaciones", items=titulos)
            return Respuesta(f"Tengo {len(notas)} nota{'s' if len(notas) != 1 else ''}: " + ", ".join(titulos[:6]) + ".")
        m = re.match(r"^(?:olvida|borra)\s+(?:lo que (?:investigaste|has investigado|sabes) (?:sobre|de)|"
                     r"la (?:investigacion|nota) (?:sobre|de))\s+(.+)$", t)
        if m:
            notas = {normalizar(p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")): p for p in NOTAS.glob("*.md")}
            cerca = difflib.get_close_matches(normalizar(m.group(1)), list(notas), n=1, cutoff=0.45)
            if not cerca:
                return Respuesta("No tengo ninguna investigación con ese nombre.")
            notas[cerca[0]].unlink()
            self.avisar_panel()
            return Respuesta("Hecho, lo he olvidado.")
        m = re.match(r"^que (?:sabes|has aprendido|recuerdas) (?:sobre|de|del|de la|acerca de)\s+(.+)$", t)
        if m and not re.match(r"^(mi|mis)\b", m.group(1)):
            tema = con_tildes(peticion, m.group(1)) or m.group(1)
            r = self.responder(f"¿Qué sabes sobre {tema}?")
            if r:
                return Respuesta(r)
            if self.ia and self.preguntar(f"No tengo nada investigado sobre {tema}. ¿Quieres que lo investigue?"):
                return self.investigar(tema, f"investiga sobre {tema}")
            return Respuesta("De acuerdo.")
        return None
