"""
Clips de Xbox de la persona → publicaciones de Asuka en YouTube (Shorts), TikTok y Twitch.

De dónde los coge (lo que encuentre, sin repetir):
  ~/jarvis/nexus/xbox/entrada/          cualquier vídeo que se deje aquí
  ~/Descargas (y Descargas/Telegram)     los que tengan nombre de captura de Xbox («Juego-2026_11_02-18-03-11.mp4»,
                                         «… 2026-11-02 18-03-11.mp4») o «xbox» en el nombre
  /media/<usuario>/<memoria USB>/        igual, en cualquier carpeta (la consola guarda sus capturas en un USB)

Para cada clip:
  vertical.mp4    1080×1920, el juego centrado sobre él mismo difuminado, máximo 59 s (TikTok y YouTube Shorts)
  horizontal.mp4  el clip tal cual, en H.264 (Twitch)
  portada.jpg     un fotograma
Los textos (título, descripción, hashtags) los escribe nexus.py con su voz.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

EXT = (".mp4", ".mkv", ".mov", ".webm")
PATRON = re.compile(r"xbox|\d{4}[_-]\d{2}[_-]\d{2}[ _-]\d{2}[-_.]\d{2}[-_.]\d{2}", re.I)
FUENTE_TXT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def fuentes(nx: Path) -> list[tuple[Path, bool, bool]]:
    """(carpeta, solo con nombre de Xbox, recursiva)."""
    h = Path.home()
    out = [(nx / "xbox" / "entrada", False, True)]
    for d in ("Descargas", "Downloads", "Vídeos", "Videos"):
        out.append((h / d, True, False))
        out.append((h / d / "Telegram", True, False))
    media = Path("/media") / h.name
    if media.exists():
        out += [(p, True, True) for p in media.iterdir() if p.is_dir()]
    return out


def clave(p: Path) -> str:
    try:
        return f"{p.name}|{p.stat().st_size}"
    except OSError:
        return p.name


def buscar(nx: Path, vistos: set[str]) -> list[Path]:
    import time
    nuevos = []
    for carpeta, filtrar, recursiva in fuentes(nx):
        if not carpeta.exists():
            continue
        try:
            archivos = carpeta.rglob("*") if recursiva else carpeta.glob("*")
            for p in archivos:
                if (p.is_file() and p.suffix.lower() in EXT and p.stat().st_size > 200_000
                        and (time.time() - p.stat().st_mtime > 30 or carpeta.name == "Telegram")   # ya copiado del todo
                        and (not filtrar or PATRON.search(str(p.relative_to(carpeta))))
                        and clave(p) not in vistos):
                    nuevos.append(p)
        except OSError:
            continue
    return sorted(set(nuevos), key=lambda p: p.stat().st_mtime)


def juego(p: Path) -> str:
    """«Forza Horizon 5-2026_11_02-18-03-11.mp4» → «Forza Horizon 5»."""
    n = PATRON.split(p.stem)[0] if PATRON.search(p.stem) else p.stem
    n = re.sub(r"(?i)\bxbox\b|[_]+", " ", n).strip(" -_.")
    return re.sub(r"\s{2,}", " ", n) or "partida"


def _probar(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
                       capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
    return {"dur": float(d.get("format", {}).get("duration") or 0), "w": v.get("width", 0), "h": v.get("height", 0),
            "codec": v.get("codec_name", ""), "audio": audio}


def _ff(args: list[str], timeout: int = 3600) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-300:]}")


def _mejor_inicio(origen: Path, dur: float, maximo: int) -> float:
    """Dónde empieza el trozo más intenso: la ventana de «maximo» s con más sonido (disparos, gritos, música de
    jefe), con un poco de ventaja para el final, que es donde la consola guarda lo que acaba de pasar."""
    import math
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(origen), "-vn", "-af",
                        "aresample=8000,asetnsamples=n=8000,astats=metadata=1:reset=1,"
                        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    rms = []
    for linea in r.stdout.splitlines():
        if "RMS_level=" in linea:
            v = linea.split("=", 1)[1].strip()
            rms.append(0.0 if v in ("-inf", "inf", "nan") else 10 ** (float(v) / 10))
    n = int(maximo)
    if len(rms) <= n + 2:
        return max(0.0, dur - maximo)
    mejor, ini, suma = -1.0, 0, sum(rms[:n])
    for i in range(0, len(rms) - n + 1):
        if i:
            suma += rms[i + n - 1] - rms[i - 1]
        puntos = suma * (1 + 0.15 * i / max(1, len(rms) - n))      # empate → mejor lo último
        if puntos > mejor:
            mejor, ini = puntos, i
    return float(min(ini, max(0.0, dur - maximo))) if not math.isnan(mejor) else max(0.0, dur - maximo)


def preparar(origen: Path, carpeta: Path, titulo: str = "", xbox: bool = True, maximo: int = 59) -> dict:
    """Hace las versiones de cada red. Tarda unos minutos por clip en este portátil.
    xbox=True y clip largo: el minuto con más acción (por el sonido). Si no, desde el principio, hasta «maximo» s."""
    carpeta.mkdir(parents=True, exist_ok=True)
    info = _probar(origen)
    if info["dur"] < 2 or not info["w"]:
        raise RuntimeError("no parece un vídeo válido")
    # Las capturas de Xbox guardan lo que acaba de pasar: lo bueno suele estar al final
    inicio = 0.0
    if xbox and info["dur"] > maximo:
        try:
            inicio = _mejor_inicio(origen, info["dur"], maximo) if info["audio"] else info["dur"] - maximo
        except Exception:
            inicio = info["dur"] - maximo
    corte = ["-ss", f"{inicio:.2f}"] if inicio else []
    audio = ["-c:a", "aac", "-b:a", "128k"] if info["audio"] else ["-an"]
    filtro = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,"
              "eq=brightness=-0.12[fondo];[0:v]scale=1080:-2[juego];[fondo][juego]overlay=(W-w)/2:(H-h)/2")
    if titulo and Path(FUENTE_TXT).exists():
        (carpeta / "titulo.txt").write_text(titulo[:42], encoding="utf-8")
        tf = str(carpeta / "titulo.txt").replace(":", r"\:")
        filtro += (f",drawtext=fontfile={FUENTE_TXT}:textfile='{tf}':fontsize=62:fontcolor=white:borderw=4:"
                   "bordercolor=black@0.8:x=(w-text_w)/2:y=h*0.17")
    filtro += "[v]"
    _ff([*corte, "-i", str(origen), "-filter_complex", filtro, "-map", "[v]", *(["-map", "0:a:0"] if info["audio"] else []),
         "-t", str(maximo), "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", *audio,
         "-movflags", "+faststart", str(carpeta / "vertical.mp4")])
    horizontal = carpeta / "horizontal.mp4"
    if info["codec"] == "h264" and origen.suffix.lower() == ".mp4":
        shutil.copy(origen, horizontal)
    else:
        _ff(["-i", str(origen), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", *audio,
             "-movflags", "+faststart", str(horizontal)])
    _ff(["-ss", f"{info['dur'] * 0.7:.2f}", "-i", str(origen), "-frames:v", "1", "-q:v", "3",
         str(carpeta / "portada.jpg")], timeout=120)
    return {"duracion": round(info["dur"], 1), "medida": f"{info['w']}x{info['h']}", "recortado": bool(inicio)}
