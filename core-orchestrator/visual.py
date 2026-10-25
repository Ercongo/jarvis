"""
Diagramas y vídeos animados hechos con código, en el propio portátil:

  Archify (github.com/tt-a1i/archify, Apache-2.0): diagramas interactivos en una página HTML.
      «haz un esquema de las partes del olivo», «hazme un mapa mental de la Revolución Francesa»   → árbol
      «haz un diagrama de los pasos para hacer pan», «diagrama de cómo se tramita una hipoteca»     → proceso
  HyperFrames (github.com/heygen-com/hyperframes, Apache-2.0): HTML animado convertido en vídeo MP4.
      «haz un vídeo animado sobre la Giralda», «crea un vídeo explicativo de cómo funciona la aerotermia»
      → guion en escenas, voz del asistente, animaciones y vídeo de 20-45 s en Vídeos.

La IA solo escribe los DATOS (nodos del diagrama o el texto de cada escena); la forma la ponen Archify y una
plantilla fija, así que el resultado siempre es válido. Se instalan con ~/jarvis/instalar_herramientas_visuales.sh.
"""

from __future__ import annotations

import datetime as dt
import glob
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Callable

from herramientas import carpeta_usuario, lanzar, normalizar
from sistema import Respuesta

HOME = Path.home()
ARCHIFY = HOME / ".local/share/archify/archify/bin/archify.mjs"
GSAP = HOME / ".local/share/hyperframes/gsap.min.js"
TRABAJO = HOME / ".cache/jarvis_visual"


def _node() -> str | None:
    for c in (HOME / ".local/node/bin/node", Path("/opt/omniroute/bin/node")):
        if c.exists():
            return str(c)
    return shutil.which("node")


def _hyperframes() -> str | None:
    for c in (HOME / ".local/node/bin/hyperframes", HOME / ".local/bin/hyperframes"):
        if c.exists():
            return str(c)
    return shutil.which("hyperframes")


def _chrome() -> str | None:
    """Un Chrome sin ventana para la comprobación de Archify (el que trae HyperFrames, si está)."""
    for patron in (".cache/hyperframes/**/chrome-headless-shell", ".cache/puppeteer/**/chrome-headless-shell",
                   ".cache/ms-playwright/**/chrome", ".cache/hyperframes/**/chrome"):
        for f in sorted(glob.glob(str(HOME / patron), recursive=True), reverse=True):
            if os.access(f, os.X_OK) and os.path.isfile(f):
                return f
    return shutil.which("chromium") or shutil.which("google-chrome")


def _entorno() -> dict:
    env = dict(os.environ)
    nodo = _node()
    if nodo:
        env["PATH"] = str(Path(nodo).parent) + ":" + env.get("PATH", "")
    env.update(ARCHIFY_UPDATE_CHECK_DISABLED="1", HYPERFRAMES_SKIP_SKILLS="1", DO_NOT_TRACK="1",
               HYPERFRAMES_NO_UPDATE_CHECK="1")
    ch = _chrome()
    if ch:
        env["ARCHIFY_CHROME"] = ch
    return env


def _nombre(t: str) -> str:
    t = re.sub(r"[^\w áéíóúñüÁÉÍÓÚÑ-]", "", t).strip()[:50] or "Diagrama"
    return t[:1].upper() + t[1:]


def _sin_pisar(p: Path) -> Path:
    if not p.exists():
        return p
    for i in range(2, 100):
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not q.exists():
            return q
    return p


# ================================================================ instrucciones para la IA
INSTR_DIAGRAMA = """Eres un diseñador de diagramas. Del encargo del usuario sacas un diagrama en JSON para Archify, \
en español de España, sin inventar datos (si algo depende de cosas que no sabes, quédate en lo general).
Elige el tipo:
- "tree": partes de algo, clasificaciones, temas y subtemas, mapa mental, organigrama. Un solo nodo raíz.
- "lifecycle": pasos de un proceso, recetas, trámites, cómo funciona algo paso a paso, estados de algo.
Reglas: ids en minúsculas ascii con guiones bajos; label de 1 a 4 palabras (máx. 24 caracteres); sublabel opcional \
de máx. 30 caracteres; nada de emojis.
TREE: 6-18 nodos, máx. 3 niveles; cada nodo salvo la raíz tiene "parent".
LIFECYCLE: "mainPath" con 3-7 ids del camino principal en orden; cada estado del camino principal lleva "step" \
("01", "02"…); "type" de cada estado: start (el primero), active, waiting, decision, success (final bueno), failure \
(final malo), neutral; máx. 10 estados; una transición por cada par seguido del camino principal y las que haga falta \
para desvíos o vueltas atrás; cada transición: {"id","from","to","label" (máx. 3 palabras)} y opcional \
"variant": "dashed" | "security" | "emphasis".
Añade 1-3 "cards" con {"dot": "cyan"|"emerald"|"amber"|"rose"|"violet", "title", "items": [2-3 frases cortas]} con \
consejos o datos útiles.
Devuelve SOLO JSON:
{"tipo": "tree" | "lifecycle", "titulo": "…", "nodes": [...] (si tree), "mainPath": [...], "states": [...], \
"transitions": [...] (si lifecycle), "cards": [...]}
Ejemplo tree: {"tipo":"tree","titulo":"Partes del olivo","nodes":[{"id":"olivo","label":"Olivo",\
"sublabel":"árbol mediterráneo"},{"id":"raiz","label":"Raíz","parent":"olivo"},{"id":"copa","label":"Copa",\
"parent":"olivo"},{"id":"hojas","label":"Hojas","parent":"copa"}],"cards":[]}
Ejemplo lifecycle: {"tipo":"lifecycle","titulo":"Hacer pan","mainPath":["amasar","reposar","hornear","listo"],\
"states":[{"id":"amasar","type":"start","label":"Amasar","step":"01"},{"id":"reposar","type":"waiting",\
"label":"Reposar","sublabel":"1-2 horas","step":"02"},{"id":"hornear","type":"active","label":"Hornear","step":"03"},\
{"id":"listo","type":"success","label":"Pan listo","step":"04"}],"transitions":[{"id":"t1","from":"amasar",\
"to":"reposar","label":"masa lisa"},{"id":"t2","from":"reposar","to":"hornear","label":"dobla volumen"},\
{"id":"t3","from":"hornear","to":"listo","label":"suena hueco"}],"cards":[]}"""

INSTR_VIDEO = """Eres guionista de vídeos cortos explicativos. Escribe el guion de un vídeo animado de 20 a 45 \
segundos en español de España sobre el encargo, sin inventar datos dudosos. Devuelve SOLO JSON:
{"titulo": "título corto del vídeo", "subtitulo": "una línea", \
"paleta": {"fondo": "#hex oscuro", "fondo2": "#hex", "tinta": "#hex claro", "acento": "#hex vivo"}, \
"escenas": [{"titulo": "2-5 palabras", "texto": "una frase de máx. 14 palabras para la pantalla", \
"voz": "lo que dice el narrador en esta escena, 1-2 frases naturales", "icono": "un emoji que la represente"}], \
"cierre": "frase final corta"}
Entre 3 y 6 escenas. La paleta debe tener buen contraste (texto claro sobre fondo oscuro)."""


# ================================================================ plantilla del vídeo (HyperFrames)
def _hex(c: str, defecto: str) -> str:
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else defecto


def composicion(spec: dict, duraciones: list[float], audios: list[str | None], ancho: int = 1280,
                alto: int = 720) -> str:
    """HTML de HyperFrames: portada, una escena por bloque del guion y cierre, con animaciones GSAP."""
    p = spec.get("paleta") or {}
    fondo, fondo2 = _hex(p.get("fondo"), "#0f172a"), _hex(p.get("fondo2"), "#1e3a8a")
    tinta, acento = _hex(p.get("tinta"), "#f8fafc"), _hex(p.get("acento"), "#f59e0b")
    esc = spec["escenas"]
    portada, cierre = 3.0, 3.0
    total = portada + sum(duraciones) + cierre
    e = lambda t: html.escape(str(t or ""))
    bloques, tl, t0 = [], [], 0.0
    bloques.append(f'''<div id="portada" class="esc clip" data-start="0" data-duration="{portada}" data-track-index="0">
  <div class="caja"><div id="pt" class="titulo grande">{e(spec.get("titulo"))}</div>
  <div id="pl" class="linea"></div><div id="ps" class="sub">{e(spec.get("subtitulo"))}</div></div></div>''')
    tl += ['tl.from("#pt",{y:60,opacity:0,duration:0.9,ease:"power3.out"},0.2);',
           'tl.from("#pl",{scaleX:0,duration:0.7,ease:"power2.inOut"},0.7);',
           'tl.from("#ps",{opacity:0,y:20,duration:0.6},1.0);',
           f'tl.to("#portada .caja",{{opacity:0,y:-30,duration:0.4}},{portada - 0.45});']
    t0 = portada
    for i, (s, d) in enumerate(zip(esc, duraciones), 1):
        bloques.append(f'''<div id="e{i}" class="esc clip" data-start="{t0:.2f}" data-duration="{d:.2f}" data-track-index="0">
  <div class="num">{i:02d}</div><div class="caja"><div id="i{i}" class="icono">{e(s.get("icono"))}</div>
  <div id="t{i}" class="titulo">{e(s.get("titulo"))}</div><div id="x{i}" class="texto">{e(s.get("texto"))}</div></div>
  <div id="b{i}" class="barra"></div></div>''')
        tl += [f'tl.from("#i{i}",{{scale:0,rotation:-25,opacity:0,duration:0.7,ease:"back.out(2)"}},{t0 + 0.15:.2f});',
               f'tl.from("#t{i}",{{x:-80,opacity:0,duration:0.7,ease:"power3.out"}},{t0 + 0.35:.2f});',
               f'tl.from("#x{i}",{{y:30,opacity:0,duration:0.7,ease:"power2.out"}},{t0 + 0.75:.2f});',
               f'tl.fromTo("#b{i}",{{scaleX:0}},{{scaleX:1,duration:{d - 0.2:.2f},ease:"none"}},{t0:.2f});',
               f'tl.to("#e{i} .caja",{{opacity:0,y:-25,duration:0.35}},{t0 + d - 0.4:.2f});']
        t0 += d
    bloques.append(f'''<div id="fin" class="esc clip" data-start="{t0:.2f}" data-duration="{cierre}" data-track-index="0">
  <div class="caja"><div id="ft" class="titulo grande">{e(spec.get("cierre") or spec.get("titulo"))}</div>
  <div id="fl" class="linea"></div></div></div>''')
    tl += [f'tl.from("#ft",{{scale:0.85,opacity:0,duration:0.8,ease:"power3.out"}},{t0 + 0.2:.2f});',
           f'tl.from("#fl",{{scaleX:0,duration:0.7}},{t0 + 0.6:.2f});']
    tl.append(f'tl.to("#fondo",{{backgroundPosition:"100% 50%",duration:{total:.2f},ease:"none"}},0);')
    sonidos, t = [], portada
    for i, (a, d) in enumerate(zip(audios, duraciones), 1):
        if a:
            sonidos.append(f'<audio id="voz{i}" class="clip" src="{a}" data-start="{t + 0.3:.2f}" '
                           f'data-duration="{d - 0.3:.2f}" data-track-index="1"></audio>')
        t += d
    return f'''<!doctype html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width={ancho}, height={alto}">
<script src="assets/gsap.min.js"></script>
<style>
:root{{--fondo:{fondo};--fondo2:{fondo2};--tinta:{tinta};--acento:{acento}}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{ancho}px;height:{alto}px;overflow:hidden;background:var(--fondo)}}
#root{{width:100%;height:100%;position:relative;font-family:"Inter","DejaVu Sans",sans-serif;color:var(--tinta)}}
#fondo{{position:absolute;inset:0;background:linear-gradient(120deg,var(--fondo),var(--fondo2),var(--fondo));background-size:300% 300%;background-position:0% 50%}}
.esc{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.caja{{width:78%;text-align:center}}
.titulo{{font-size:58px;font-weight:800;letter-spacing:-0.02em;line-height:1.1}}
.grande{{font-size:72px}}
.sub{{font-size:28px;opacity:.85;margin-top:22px}}
.texto{{font-size:34px;line-height:1.35;margin-top:26px;opacity:.92}}
.icono{{font-size:88px;margin-bottom:18px}}
.linea{{width:180px;height:6px;background:var(--acento);margin:26px auto 0;border-radius:3px;transform-origin:left}}
.num{{position:absolute;top:44px;left:64px;font-size:30px;font-weight:800;color:var(--acento)}}
.barra{{position:absolute;left:0;bottom:0;height:8px;width:100%;background:var(--acento);transform-origin:left}}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total:.2f}" data-width="{ancho}" data-height="{alto}">
<div id="fondo" class="clip" data-start="0" data-duration="{total:.2f}" data-track-index="2"></div>
{chr(10).join(bloques)}
{chr(10).join(sonidos)}
</div>
<script>
const tl = gsap.timeline({{paused:true}});
{chr(10).join(tl)}
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>'''


def _segundos_wav(ruta: Path) -> float:
    try:
        with wave.open(str(ruta)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


# ================================================================ el módulo
class Visual:
    def __init__(self, cerebro, decir: Callable[..., None], log=print, avisar: Callable[[str], None] | None = None,
                 enviar_documento: Callable | None = None, es_telegram: Callable[[], bool] | None = None,
                 sintetizar: Callable[[str, Path], None] | None = None):
        self.cerebro = cerebro
        self.decir = decir
        self.log = log
        self.avisar = avisar or (lambda t: None)
        self.enviar_documento = enviar_documento
        self.es_telegram = es_telegram or (lambda: False)
        self.sintetizar = sintetizar
        self._ocupado = False

    @property
    def ia(self) -> bool:
        return bool(self.cerebro and getattr(self.cerebro, "activo", False))

    def _json(self, sistema: str, usuario: str, max_tokens: int = 2500) -> dict:
        texto = self.cerebro.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                                  formato_json=True, max_tokens=max_tokens, temperatura=0.4, timeout=90)
        m = re.search(r"\{.*\}", texto or "", re.S)
        if not m:
            raise RuntimeError("la IA no ha devuelto el diseño")
        return json.loads(m.group(0))

    # ------------------------------------------------------------ órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)
        verbo = r"(?:haz|hazme|crea|creame|dibuja|dibujame|genera|generame|prepara|preparame|monta|montame)"
        m = re.match(verbo + r"\s+(?:un|una)\s+(?:diagrama|esquema|mapa mental|mapa conceptual|organigrama|"
                     r"diagrama de flujo|infografia)\s+(?:de|del|de la|de los|de las|sobre|con|para)?\s*(.+)$", t)
        if m:
            return self.diagrama(peticion)
        m = re.match(verbo + r"\s+(?:un|una)\s+(?:video|animacion)\s+(?:animado|explicativo|con texto|con animaciones|"
                     r"corto animado|tipo presentacion|de presentacion)\s*(?:de|del|de la|sobre|para|que explique)?\s*(.+)$", t) \
            or re.match(verbo + r"\s+(?:una )?animacion\s+(?:de|del|de la|sobre|que explique)\s+(.+)$", t)
        if m:
            return self.video(peticion)
        if re.search(r"\bque (herramientas|programas) (visuales|de diagramas)\b", t):
            return Respuesta(self.estado())
        return None

    def estado(self) -> str:
        partes = []
        partes.append("diagramas con Archify" if ARCHIFY.exists() and _node() else "")
        partes.append("vídeos animados con HyperFrames" if _hyperframes() else "")
        hay = [p for p in partes if p]
        return ("Puedo hacer " + " y ".join(hay) + ".") if hay else \
            "No tengo instaladas las herramientas visuales: bash ~/jarvis/instalar_herramientas_visuales.sh"

    def _segundo_plano(self, trabajo: Callable[[], tuple[str, Path | None]], aviso: str) -> Respuesta:
        if self._ocupado:
            return Respuesta("Estoy terminando otro diagrama o vídeo; en cuanto acabe, pídemelo otra vez.")
        tg = self.es_telegram()

        def hilo():
            self._ocupado = True
            try:
                texto, archivo = trabajo()
            except Exception as e:
                self.log(f"visual: {e!r}")
                texto, archivo = (f"No he podido: {e}" if isinstance(e, RuntimeError)
                                  else f"No ha salido ({type(e).__name__}). Prueba a pedírmelo de otra forma."), None
            finally:
                self._ocupado = False
            if tg:
                if archivo and self.enviar_documento:
                    self.enviar_documento(str(archivo), texto)
                else:
                    self.avisar(texto)
            else:
                if archivo:
                    try:
                        lanzar(["xdg-open", str(archivo)])
                    except OSError:
                        pass
                self.decir(texto)
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta(aviso)

    # ------------------------------------------------------------ diagramas (Archify)
    def diagrama(self, peticion: str) -> Respuesta:
        if not (ARCHIFY.exists() and _node()):
            return Respuesta("Para hacer diagramas me falta Archify. Instálalo con: "
                             "bash ~/jarvis/instalar_herramientas_visuales.sh")
        if not self.ia:
            return Respuesta("Para diseñar el diagrama necesito la IA en la nube, y ahora no está disponible.")

        def trabajo():
            spec = self._json(INSTR_DIAGRAMA, f"Encargo: {peticion}")
            carpeta = TRABAJO / f"diagrama-{dt.datetime.now():%Y%m%d-%H%M%S}"
            carpeta.mkdir(parents=True, exist_ok=True)
            titulo = str(spec.get("titulo") or "Diagrama")[:70]
            ruta, error = None, ""
            for intento in range(3):
                cand = self._candidato(spec, titulo)
                (carpeta / "candidate.json").write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")
                salida = carpeta / f"diagrama-{intento}.html"
                ok, error = self._finalizar(cand["diagram_type"], carpeta / "candidate.json", salida)
                if ok:
                    ruta = salida
                    break
                self.log(f"visual: Archify rechaza el diagrama ({error[:200]}); lo corrijo")
                spec = self._json(INSTR_DIAGRAMA, f"Encargo: {peticion}\n\nTu JSON anterior:\n"
                                  f"{json.dumps(spec, ensure_ascii=False)[:6000]}\n\nArchify lo rechaza por esto; "
                                  f"corrígelo y devuélvelo entero:\n{error[:1500]}")
            if not ruta:
                raise RuntimeError("el diagrama no ha pasado las comprobaciones de Archify")
            destino = _sin_pisar(carpeta_usuario("DOCUMENTS") / "Diagramas" / f"{_nombre(titulo)}.html")
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ruta, destino)
            return (f"Ya tienes el diagrama «{titulo}». Es interactivo: puedes acercarte, buscar y exportarlo a "
                    "imagen o PDF. Lo he guardado en Documentos, carpeta Diagramas."), destino
        return self._segundo_plano(trabajo, "Diseño el diagrama; en un minuto lo tienes.")

    @staticmethod
    def _candidato(spec: dict, titulo: str) -> dict:
        tipo = "lifecycle" if str(spec.get("tipo")).startswith("life") or spec.get("states") else "tree"
        meta = {"title": titulo, "output": "diagrama.html", "quality_profile": "standard", "locale": "es"}
        cards = [c for c in (spec.get("cards") or []) if isinstance(c, dict) and c.get("title") and c.get("items")][:3]
        for c in cards:
            if c.get("dot") not in ("cyan", "emerald", "violet", "amber", "rose", "orange", "slate"):
                c["dot"] = "cyan"
            c["items"] = [str(x)[:120] for x in c["items"]][:4]
        if tipo == "tree":
            cand = {"schema_version": 1, "diagram_type": "tree", "meta": meta, "nodes": spec.get("nodes") or []}
            if len(cand["nodes"]) > 12:
                cand["layout"] = {"direction": "right"}
        else:
            cand = {"schema_version": 3, "diagram_type": "lifecycle", "meta": meta,
                    "mainPath": spec.get("mainPath") or [], "states": spec.get("states") or [],
                    "transitions": spec.get("transitions") or []}
            for i, tr in enumerate(cand["transitions"]):
                tr.setdefault("id", f"t{i + 1}")
        if cards:
            cand["cards"] = cards
        return cand

    def _finalizar(self, tipo: str, candidato: Path, salida: Path) -> tuple[bool, str]:
        cmd = [_node(), str(ARCHIFY), "finalize", tipo, str(candidato), str(salida), "--quality", "standard", "--json"]
        try:
            r = subprocess.run(cmd, cwd=candidato.parent, capture_output=True, text=True, timeout=240, env=_entorno())
        except subprocess.TimeoutExpired:
            return False, "Archify ha tardado demasiado"
        try:
            d = json.loads(r.stdout[r.stdout.find("{"):])
        except ValueError:
            return False, (r.stderr or r.stdout)[-800:]
        g = d.get("gates") or {}
        # sin Chrome la comprobación en navegador se salta: si lo demás pasa, el diagrama vale
        if all(g.get(k) == "pass" for k in ("validate", "deliver", "check")) and salida.exists():
            return True, ""
        diag = "; ".join(f"{x.get('code')}: {x.get('message')}" for x in (d.get("diagnostics") or [])[:8])
        return False, diag or f"falló {d.get('failedStage')}"

    # ------------------------------------------------------------ vídeos (HyperFrames)
    def video(self, peticion: str) -> Respuesta:
        hf = _hyperframes()
        if not hf or not GSAP.exists():
            return Respuesta("Para los vídeos animados me falta HyperFrames. Instálalo con: "
                             "bash ~/jarvis/instalar_herramientas_visuales.sh")
        if not self.ia:
            return Respuesta("Para escribir el guion necesito la IA en la nube, y ahora no está disponible.")
        con_voz = self.sintetizar is not None and not re.search(r"\bsin (voz|narracion|narrador)\b", normalizar(peticion))

        def trabajo():
            spec = self._json(INSTR_VIDEO, f"Encargo: {peticion}", max_tokens=2000)
            escenas = [s for s in (spec.get("escenas") or []) if isinstance(s, dict) and s.get("titulo")][:6]
            if len(escenas) < 2:
                raise RuntimeError("el guion ha salido demasiado corto")
            spec["escenas"] = escenas
            proyecto = TRABAJO / f"video-{dt.datetime.now():%Y%m%d-%H%M%S}"
            (proyecto / "assets").mkdir(parents=True, exist_ok=True)
            shutil.copy2(GSAP, proyecto / "assets" / "gsap.min.js")
            duraciones, audios = [], []
            for i, s in enumerate(escenas, 1):
                d = 5.0
                audio = None
                if con_voz and s.get("voz"):
                    wav = proyecto / "assets" / f"voz{i}.wav"
                    try:
                        self.sintetizar(str(s["voz"]), wav)
                        largo = _segundos_wav(wav)
                        if largo > 0.5:
                            d = max(d, largo + 1.2)
                            audio = f"assets/voz{i}.wav"
                    except Exception as e:
                        self.log(f"visual: voz de la escena {i}: {e!r}")
                duraciones.append(round(min(d, 14.0), 2))
                audios.append(audio)
            (proyecto / "index.html").write_text(composicion(spec, duraciones, audios), encoding="utf-8")
            (proyecto / "hyperframes.json").write_text(json.dumps({"paths": {"assets": "assets"}}), encoding="utf-8")
            titulo = str(spec.get("titulo") or "Vídeo")[:60]
            destino = _sin_pisar(carpeta_usuario("VIDEOS") / f"{_nombre(titulo)}.mp4")
            destino.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            r = subprocess.run([hf, "render", "-o", str(destino), "-q", "standard", "-f", "24", "-w", "1", "--quiet"],
                               cwd=proyecto, capture_output=True, text=True, timeout=1800, env=_entorno())
            if r.returncode != 0 or not destino.exists():
                self.log(f"visual: hyperframes {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
                raise RuntimeError("HyperFrames no ha podido convertir la animación en vídeo")
            total = 6 + sum(duraciones)
            self.log(f"visual: vídeo de {total:.0f} s en {time.time() - t0:.0f} s")
            return (f"Ya tienes el vídeo «{titulo}», de {total:.0f} segundos"
                    + (", con mi voz" if any(audios) else "") + ". Está en la carpeta Vídeos."), destino
        return self._segundo_plano(trabajo, "Escribo el guion y monto la animación. Tardaré unos minutos; te aviso.")
