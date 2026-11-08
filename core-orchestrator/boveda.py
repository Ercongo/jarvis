"""La bóveda de Obsidian de Athena (~/jarvis/boveda): lo que hace Asuka y lo que aprende Athena, en notas Markdown
que se abren con Obsidian en cualquier equipo (o se leen tal cual: son texto).

No necesita Obsidian instalado en el portátil (la CLI oficial exige la app abierta y aquí falta memoria): Athena
escribe los archivos en los formatos abiertos de Obsidian (Markdown con propiedades, Bases y JSON Canvas, según
github.com/kepano/obsidian-skills) y Obsidian los muestra en el PC o en el móvil.

Lo que se genera se sobrescribe en cada exportación. Lo que escribe la persona (Diario/ y cualquier nota suya) no se
toca nunca.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from perfil import DATOS

BOVEDA = DATOS / "boveda"
NX = DATOS / "nexus"
NOTAS_SABER = DATOS / "saber" / "notas"
GENERADO = "<!-- generado por Athena: se rehace solo; lo que escribas aquí se pierde -->"


def _yaml(v) -> str:
    if v is None or v == "":
        return '""'
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_yaml(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)        # cadena JSON = cadena YAML válida (comillas dobles)


def _nota(ruta: Path, props: dict, cuerpo: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cab = "---\n" + "".join(f"{k}: {_yaml(v)}\n" for k, v in props.items()) + "---\n"
    nuevo = cab + GENERADO + "\n\n" + cuerpo.strip() + "\n"
    if not ruta.exists() or ruta.read_text(encoding="utf-8") != nuevo:   # sin tocar lo que no cambia (sincronía)
        ruta.write_text(nuevo, encoding="utf-8")


def _nombre(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|#^\[\]]', "", t)).strip()[:90] or "sin título"


def _miniatura(origen: Path, destino: Path) -> bool:
    """Una imagen pequeña (320 px) para las tarjetas: de la foto o de un fotograma del vídeo."""
    if destino.exists():
        return True
    if not origen.exists():
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-v", "error", "-y"]
    if origen.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
        args += ["-ss", "1.5"]
    args += ["-i", str(origen), "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "5", str(destino)]
    try:
        return subprocess.run(args, capture_output=True, timeout=60).returncode == 0 and destino.exists()
    except (OSError, subprocess.SubprocessError):
        return False


def _publicaciones(e: dict, dias: int = 90) -> int:
    carpeta = BOVEDA / "Asuka" / "Publicaciones"
    minis = BOVEDA / "Asuka" / "miniaturas"
    limite = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat()
    stats = {r.get("url"): r for r in e.get("rendimiento", []) if r.get("url")}
    vivas = set()
    for c in e.get("cola", []):
        if c.get("dia", "") < limite or c.get("estado") not in ("publicado", "pendiente", "error", "manual"):
            continue
        nombre = _nombre(f"{c['dia']} {c.get('hora', '')} {c['red']} {c.get('id', '')}".replace(":", "."))
        vivas.add(nombre + ".md")
        arch = NX / c.get("archivo", "")
        mini = minis / (re.sub(r"\W", "_", c.get("archivo", "x"))[-80:] + ".jpg")
        portada = f"[[{mini.relative_to(BOVEDA).as_posix()}]]" if c.get("archivo") and _miniatura(arch, mini) else ""
        s = stats.get(c.get("url"), {})
        props = {"red": c["red"], "tipo": c.get("tipo", "foto"), "fecha": c["dia"], "hora": c.get("hora", ""),
                 "estado": c.get("estado"), "origen": c.get("origen", "plan"), "url": c.get("url", ""),
                 "alcance": s.get("reach"), "vistas": s.get("views"), "me_gusta": s.get("me_gusta"),
                 "guardados": s.get("saved"), "compartidos": s.get("shares"), "comentarios": s.get("comentarios"),
                 "puntos": s.get("puntos"), "portada": portada, "tags": ["publicacion", c["red"]]}
        props = {k: v for k, v in props.items() if v not in (None, "")}
        cuerpo = (f"# {c.get('titulo') or c['red'].capitalize() + ' · ' + c['dia']}\n\n"
                  + (f"![[{mini.relative_to(BOVEDA).as_posix()}|320]]\n\n" if portada else "")
                  + "## Texto\n\n" + (c.get("texto") or "(sin texto)") + "\n"
                  + (f"\n> [!warning] Error\n> {c['error']}\n" if c.get("error") else "")
                  + f"\nArchivo en el portátil: `~/jarvis/nexus/{c.get('archivo', '')}`\n")
        _nota(carpeta / f"{nombre}.md", props, cuerpo)
    for viejo in carpeta.glob("*.md") if carpeta.exists() else []:   # lo que ya no está en la cola, fuera
        if viejo.name not in vivas and GENERADO in viejo.read_text(encoding="utf-8", errors="ignore")[:600]:
            viejo.unlink()
    return len(vivas)


BASE_PUBLICACIONES = """filters:
  and:
    - 'file.inFolder("Asuka/Publicaciones")'
formulas:
  interaccion: 'if(alcance, ((me_gusta + guardados * 3 + compartidos * 3 + comentarios * 2) / alcance * 100).round(1), "")'
  hace: '(today() - date(fecha)).days'
properties:
  formula.interaccion:
    displayName: "Interacción %"
  formula.hace:
    displayName: "Hace (días)"
views:
  - type: table
    name: "Últimas"
    order:
      - fecha
      - hora
      - red
      - tipo
      - estado
      - alcance
      - formula.interaccion
      - file.name
    sort:
      - property: fecha
        direction: DESC
  - type: table
    name: "Lo que mejor funciona"
    filters:
      and:
        - 'puntos > 0'
    order:
      - file.name
      - red
      - tipo
      - hora
      - alcance
      - guardados
      - compartidos
      - puntos
    sort:
      - property: puntos
        direction: DESC
    limit: 20
  - type: table
    name: "Por red"
    groupBy:
      property: red
      direction: ASC
    order:
      - fecha
      - tipo
      - estado
      - alcance
    summaries:
      alcance: Sum
  - type: cards
    name: "Galería"
    image: note.portada
    order:
      - file.name
      - red
      - fecha
      - estado
  - type: table
    name: "Pendientes y errores"
    filters:
      or:
        - 'estado == "pendiente"'
        - 'estado == "error"'
    order:
      - fecha
      - hora
      - red
      - estado
      - file.name
"""


def _diario_nexus(dias: int = 30) -> int:
    """El diario de Nexus (todo lo que pasa con Asuka), una nota por día."""
    try:
        lineas = (NX / "diario.jsonl").read_text(encoding="utf-8").splitlines()[-4000:]
    except OSError:
        return 0
    por_dia: dict[str, list[dict]] = {}
    for l in lineas:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        por_dia.setdefault(d.get("t", "")[:10], []).append(d)
    limite = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat()
    n = 0
    for dia, entradas in por_dia.items():
        if not dia or dia < limite:
            continue
        tipos = sorted({x.get("tipo", "") for x in entradas})
        cuerpo = f"# Asuka · {dia}\n\n" + "\n".join(
            f"- **{x.get('t', '')[11:16]}** · {x.get('tipo', '')}: {str(x.get('texto', '')).replace(chr(10), ' ')[:400]}"
            for x in entradas)
        _nota(BOVEDA / "Asuka" / "Diario de Nexus" / f"{dia}.md",
              {"fecha": dia, "eventos": len(entradas), "tipos": tipos, "tags": ["nexus", "diario"]}, cuerpo)
        n += 1
    return n


def _material(e: dict) -> None:
    """Resumen del material: fotos, clips, música y webs con crédito."""
    def indice(c: Path) -> list:
        try:
            return json.loads((c / "indice.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    refs, clips = indice(NX / "referencias"), indice(NX / "clips")
    cuenta = {k: sum(1 for r in refs if r.get("apta") == k) for k in ("publica", "revisar", "no")}
    filas = "\n".join(f"| {c['archivo']} | {c.get('origen', '')} | {c.get('apta', '')} | {c.get('escena', '')[:60]} |"
                      for c in clips)
    musica = sorted(p.name for p in (NX / "musica").glob("*.wav")) if (NX / "musica").exists() else []
    narrados = e.get("narrados", [])[-10:]
    cuerpo = (f"# Material de Asuka\n\n> [!info] Fotos\n> {len(refs)} referencias: {cuenta['publica']} verdes, "
              f"{cuenta['revisar']} ámbar, {cuenta['no']} rojas.\n\n## Clips con movimiento ({len(clips)})\n\n"
              "| Archivo | Origen | Apta | Escena |\n|---|---|---|---|\n" + filas
              + f"\n\n## Música ({len(musica)})\n\n" + "\n".join(f"- {m}" for m in musica)
              + "\n\n## Últimos vídeos narrados\n\n"
              + ("\n".join(f"- {x.get('fecha')} · {x.get('tema')} ({x.get('fuente')})" for x in narrados) or "- ninguno")
              + "\n\n## Kaggle\n\n" + (f"`{json.dumps({k: v for k, v in (e.get('kaggle') or {}).items() if k != 'trabajos' and k != 'registro'}, ensure_ascii=False)}`"
                                      if e.get("kaggle") else "Sin lanzar todavía."))
    _nota(BOVEDA / "Asuka" / "Material.md", {"actualizado": time.strftime("%Y-%m-%d %H:%M"),
                                              "tags": ["nexus"]}, cuerpo)


def _aprendido() -> int:
    """Las notas que Athena ha aprendido (saber/notas) y su memoria de hechos."""
    destino = BOVEDA / "Athena" / "Aprendido"
    n = 0
    if NOTAS_SABER.exists():
        for nota in sorted(NOTAS_SABER.glob("*.md")):
            texto = re.sub(r"\A---\n.*?\n---\n", "", nota.read_text(encoding="utf-8", errors="ignore"), flags=re.S)
            fecha = time.strftime("%Y-%m-%d", time.localtime(nota.stat().st_mtime))
            _nota(destino / nota.name, {"fecha": fecha, "tags": ["aprendido"]}, texto)
            n += 1
    try:
        hechos = json.loads((DATOS / "memoria.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hechos = []
    lineas = []
    for h in hechos[-300:]:
        t = h.get("texto") or h.get("hecho") or h.get("dato") if isinstance(h, dict) else str(h)
        if t:
            lineas.append(f"- {t}")
    _nota(BOVEDA / "Athena" / "Memoria.md", {"hechos": len(lineas), "tags": ["memoria"]},
          "# Lo que Athena recuerda\n\n" + ("\n".join(lineas) or "Nada todavía."))
    return n


CANVAS_NODOS = [
    ("athena", "# Athena\nVoz, Telegram, panel", 0, 0, "6"),
    ("nexus", "# Nexus\nPlan diario, cola y publicación", 420, 0, "5"),
    ("material", "## Material\nFotos (verde/ámbar/roja), entorno, clips", 420, -260, None),
    ("clips", "## Clips con movimiento\nHF (Wan, NiftyVid, Hunyuan, LTX), Kaggle, webs con crédito", 840, -260, None),
    ("narrado", "## Vídeos narrados\nGuion + su voz + MoneyPrinterTurbo + karaoke", 840, -60, None),
    ("montaje", "## Montaje\nSu voz (Piper), música, subtítulos karaoke", 840, 140, None),
    ("redes", "## Redes\nInstagram, Facebook (auto) · TikTok, YouTube, Pinterest, Twitch (a mano)", 1260, 0, "4"),
    ("comentarios", "## Comentarios\nSencillos: los contesta sola · resto: te los propone", 1260, 260, None),
    ("estadisticas", "## Estadísticas\nAlcance y guardados → guían el plan", 840, 400, None),
    ("boveda", "## Esta bóveda\n[[Inicio]] · [[Asuka/Publicaciones.base|Publicaciones]]", 0, 300, "3"),
]
CANVAS_FLECHAS = [("athena", "nexus", "órdenes"), ("material", "clips", ""), ("clips", "montaje", ""),
                  ("narrado", "montaje", ""), ("nexus", "narrado", ""), ("montaje", "redes", "cola"),
                  ("redes", "comentarios", ""), ("redes", "estadisticas", "cada mañana"),
                  ("estadisticas", "nexus", "plan"), ("nexus", "boveda", "cada noche")]


def _canvas() -> None:
    import hashlib
    ide = lambda s: hashlib.md5(s.encode()).hexdigest()[:16]
    nodos = [{"id": ide(k), "type": "text", "text": t, "x": x, "y": y, "width": 360, "height": 160,
              **({"color": c} if c else {})} for k, t, x, y, c in CANVAS_NODOS]
    flechas = [{"id": ide(a + b), "fromNode": ide(a), "toNode": ide(b), "toEnd": "arrow", **({"label": l} if l else {})}
               for a, b, l in CANVAS_FLECHAS]
    (BOVEDA / "Mapa de Athena y Asuka.canvas").write_text(
        json.dumps({"nodes": nodos, "edges": flechas}, ensure_ascii=False, indent=1), encoding="utf-8")


def _inicio(e: dict, n_pub: int) -> None:
    hoy = datetime.date.today().isoformat()
    de_hoy = [c for c in e.get("cola", []) if c.get("dia") == hoy]
    lineas = "\n".join(f"- {c.get('hora', '--:--')} · **{c['red']}** · {c.get('tipo', 'foto')} · {c.get('estado')}"
                       for c in sorted(de_hoy, key=lambda c: c.get("hora", ""))) or "- Nada para hoy."
    cuerpo = (f"# Athena y Asuka\n\n> [!tip] Actualizado {time.strftime('%d/%m/%Y %H:%M')}\n> Athena rehace estas "
              "notas cada noche y cuando le dices «actualiza obsidian». Tus notas van en **Diario/** o en cualquier "
              "carpeta nueva: esas no se tocan.\n\n## Hoy\n\n" + lineas
              + f"\n\n## Publicaciones ({n_pub} en los últimos 90 días)\n\n![[Asuka/Publicaciones.base#Últimas]]\n\n"
              "## Lo que mejor le funciona\n\n![[Asuka/Publicaciones.base#Lo que mejor funciona]]\n\n"
              "## Más\n\n- [[Asuka/Material|Material de Asuka]]\n- [[Mapa de Athena y Asuka.canvas|Mapa]]\n"
              "- [[Athena/Memoria|Lo que Athena recuerda]]\n- Diario de Nexus: carpeta `Asuka/Diario de Nexus`\n"
              "- Tu diario: carpeta `Diario` (Athena añade aquí lo que le dictas con «apunta en obsidian…»)\n")
    _nota(BOVEDA / "Inicio.md", {"tags": ["inicio"]}, cuerpo)


TIPOS = {"fecha": "date", "alcance": "number", "vistas": "number", "me_gusta": "number", "guardados": "number",
         "compartidos": "number", "comentarios": "number", "puntos": "number", "eventos": "number", "hechos": "number",
         "red": "text", "tipo": "text", "estado": "text", "origen": "text", "hora": "text", "url": "text",
         "portada": "text", "tipos": "multitext"}


def _config_obsidian() -> None:
    """Tipos de las propiedades (fechas y números de verdad en las Bases). Solo si la persona no ha tocado nada."""
    cfg = BOVEDA / ".obsidian"
    cfg.mkdir(exist_ok=True)
    f = cfg / "types.json"
    try:
        actual = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"types": {}}
    except ValueError:
        return
    nuevos = {k: v for k, v in TIPOS.items() if k not in actual.get("types", {})}
    if nuevos:
        actual.setdefault("types", {}).update(nuevos)
        f.write_text(json.dumps(actual, indent=2), encoding="utf-8")


def exportar() -> str:
    BOVEDA.mkdir(parents=True, exist_ok=True)
    _config_obsidian()
    (BOVEDA / "Diario").mkdir(exist_ok=True)
    try:
        e = json.loads((NX / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        e = {}
    n_pub = _publicaciones(e)
    (BOVEDA / "Asuka" / "Publicaciones.base").write_text(BASE_PUBLICACIONES, encoding="utf-8")
    n_dia = _diario_nexus()
    _material(e)
    n_apr = _aprendido()
    _canvas()
    _inicio(e, n_pub)
    return f"Bóveda al día: {n_pub} publicaciones, {n_dia} días de diario de Nexus y {n_apr} notas aprendidas."


def apuntar(texto: str) -> Path:
    """Añade una línea con la hora a la nota del día (Diario/AAAA-MM-DD.md). Nunca borra nada."""
    hoy = datetime.date.today().isoformat()
    ruta = BOVEDA / "Diario" / f"{hoy}.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        ruta.write_text(f"---\nfecha: {hoy}\ntags: [diario]\n---\n# {hoy}\n\n", encoding="utf-8")
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(f"- {time.strftime('%H:%M')} {texto.strip()}\n")
    return ruta
