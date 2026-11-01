"""
Vídeos cortos verticales (1080×1920) para el proyecto Nexus, a coste 0 y en este portátil:

  guion por escenas  →  voz del personaje: Qwen3-TTS (espacio gratuito de Qwen en Hugging Face, con la voz propia
                         del personaje diseñada una vez y reutilizada siempre); si falla, Kokoro «ef_dora»; si no, Piper
                     →  por escena, lo que mejor encaje: un clip del personaje (DeeVid, OpenGen, Viggle, Wan…), una de
                         sus fotos de referencia, o una imagen nueva con FLUX
                     →  movimiento suave (zoom), subtítulos grandes palabra a palabra y la etiqueta «IA»
                     →  MP4 listo para TikTok, Reels y Shorts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Callable

HOME = Path.home()
KOKORO = HOME / ".local/share/kokoro"
ANCHO, ALTO = 1080, 1920


# ================================================================ voz
def voz_kokoro(texto: str, destino: Path, voz: str = "ef_dora", velocidad: float = 1.05) -> bool:
    """Kokoro en su propio entorno (instalar_voz_nexus.sh): no mezcla paquetes con los del asistente."""
    py, guion = KOKORO / "venv/bin/python", KOKORO / "decir.py"
    if not (py.exists() and guion.exists()):
        return False
    r = subprocess.run([str(py), str(guion), texto, str(destino), voz, str(velocidad)], capture_output=True, timeout=300)
    return r.returncode == 0 and destino.exists() and destino.stat().st_size > 1000


QWEN_TTS = "Qwen/Qwen3-TTS"     # comprobado el 1 nov 2026: /generate_voice_design y /generate_voice_clone, ~15 s


def _qwen():
    from gradio_client import Client
    try:
        from estudio import leer_claves
        tok = leer_claves().get("hf") or None
    except Exception:
        tok = None
    return Client(QWEN_TTS, token=tok, verbose=False) if tok else Client(QWEN_TTS, verbose=False)


def voz_qwen_disenar(texto: str, descripcion_en: str, destino: Path) -> bool:
    """Crea una voz nueva a partir de una descripción (no copia la voz de nadie)."""
    try:
        a, _ = _qwen().predict(texto, "Spanish", descripcion_en, api_name="/generate_voice_design")
        shutil.copy(a, destino)
        return destino.stat().st_size > 1000
    except Exception:
        return False


def voz_qwen(texto: str, destino: Path, ref_wav: Path, ref_texto: str) -> bool:
    """La voz propia del personaje (su muestra de referencia) diciendo un texto nuevo: siempre suena igual."""
    if not (ref_wav and Path(ref_wav).exists() and ref_texto):
        return False
    try:
        from gradio_client import handle_file
        a, _ = _qwen().predict(handle_file(str(ref_wav)), ref_texto, texto, "Spanish", False, "1.7B",
                               api_name="/generate_voice_clone")
        tmp = destino.with_suffix(".qwen")
        shutil.copy(a, tmp)
        # a WAV normal (el espacio puede devolver otro formato)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-ar", "44100", "-ac", "1", str(destino)],
                       check=True)
        tmp.unlink(missing_ok=True)
        return destino.stat().st_size > 1000
    except Exception:
        return False


def voz_elevenlabs(texto: str, destino: Path) -> bool:
    """Una voz de ElevenLabs (por ejemplo «Sofia» de su biblioteca) con la clave de la persona:
    «clave de elevenlabs …» y «voz de elevenlabs <id de la voz>». El plan gratis no permite uso comercial."""
    try:
        from estudio import leer_claves
        import urllib.request
        c = leer_claves()
        clave, voz = c.get("elevenlabs"), c.get("elevenlabs_voz")
        if not (clave and voz):
            return False
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voz}?output_format=mp3_44100_128",
            data=json.dumps({"text": texto, "model_id": "eleven_multilingual_v2", "language_code": "es"}).encode(),
            headers={"xi-api-key": clave, "Content-Type": "application/json"})
        mp3 = destino.with_suffix(".mp3")
        with urllib.request.urlopen(req, timeout=120) as r:
            mp3.write_bytes(r.read())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(destino)],
                       check=True)
        mp3.unlink(missing_ok=True)
        return destino.stat().st_size > 1000
    except Exception:
        return False


def voz_piper(voz_piper, texto: str, destino: Path, hablante: int = 0) -> None:
    """La voz del asistente (sharvard) con su otra hablante (la 0 es femenina)."""
    from piper import SynthesisConfig
    with wave.open(str(destino), "wb") as w:
        voz_piper.synthesize_wav(texto, w, syn_config=SynthesisConfig(speaker_id=hablante, length_scale=1.0))


def duracion(ruta: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ================================================================ subtítulos
def _ass_tiempo(s: float) -> str:
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def subtitulos(escenas: list[dict], destino: Path, etiqueta: str) -> None:
    """Frases de 3-5 palabras, grandes y centradas (como los vídeos que funcionan en TikTok)."""
    cab = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
           "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
           "MarginR, MarginV, Encoding\n"
           "Style: Sub,DejaVu Sans,78,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,2,80,80,520,1\n"
           "Style: Eti,DejaVu Sans,34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,3,2,0,7,40,40,60,1\n\n"
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lineas, t = [], 0.0
    for e in escenas:
        palabras = e["texto"].split()
        trozos = [" ".join(palabras[i:i + 4]) for i in range(0, len(palabras), 4)] or [""]
        total = sum(len(x) for x in trozos) or 1
        for tr in trozos:
            d = e["dur"] * len(tr) / total
            limpio = tr.replace("{", "(").replace("}", ")").upper()
            lineas.append(f"Dialogue: 0,{_ass_tiempo(t)},{_ass_tiempo(t + d)},Sub,,0,0,0,,{limpio}")
            t += d
    lineas.append(f"Dialogue: 1,{_ass_tiempo(0)},{_ass_tiempo(t + 1)},Eti,,0,0,0,,{etiqueta}")
    destino.write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")


# ================================================================ montaje
def montar(escenas: list[dict], carpeta: Path, salida: Path, etiqueta: str, log: Callable[[str], None] = print) -> Path:
    """escenas: [{"imagen": Path | "clip": Path, "audio": Path, "texto": str}] → MP4 vertical con voz y subtítulos.
    Una imagen lleva zoom suave; un clip se recorta a vertical, se repite si es corto y pierde su sonido."""
    partes = []
    for i, e in enumerate(escenas):
        e["dur"] = max(1.5, duracion(e["audio"]) + 0.25)
        clip = carpeta / f"esc{i}.mp4"
        frames = int(e["dur"] * 30)
        zoom = "min(zoom+0.0009,1.12)" if i % 2 == 0 else "if(eq(on,0),1.12,max(zoom-0.0009,1.0))"
        if e.get("clip"):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(e["clip"]),
                            "-i", str(e["audio"]), "-filter_complex",
                            f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},"
                            "fps=30,format=yuv420p[v];[1:a]apad,aresample=44100[a]",
                            "-map", "[v]", "-map", "[a]", "-t", f"{e['dur']:.2f}", "-c:v", "libx264", "-preset",
                            "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", str(clip)], check=True)
            partes.append(clip)
            continue
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(e["imagen"]), "-i", str(e["audio"]),
                        "-filter_complex",
                        f"[0:v]scale=1620:2880,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:"
                        f"s={ANCHO}x{ALTO}:fps=30,format=yuv420p[v];[1:a]apad,aresample=44100[a]",
                        "-map", "[v]", "-map", "[a]", "-t", f"{e['dur']:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "21", "-c:a", "aac", "-b:a", "160k", str(clip)], check=True)
        partes.append(clip)
    lista = carpeta / "lista.txt"
    lista.write_text("".join(f"file '{p.name}'\n" for p in partes), encoding="utf-8")
    junto = carpeta / "junto.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
                    str(junto)], check=True, cwd=carpeta)
    ass = carpeta / "subs.ass"
    subtitulos(escenas, ass, etiqueta)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(junto), "-vf", f"ass={ass.name}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "copy", "-movflags", "+faststart",
                    str(salida)], check=True, cwd=carpeta)
    log(f"nexus: vídeo {salida.name} ({duracion(salida):.0f} s)")
    return salida


def crear_corto(guion: dict, identidad: dict, carpeta: Path, imagen: Callable[[str, int, int, Path, int | None], Path],
                voz_reserva: Callable[[str, Path], None] | None = None, log: Callable[[str], None] = print,
                fuente: Callable[[str, int], tuple[str, Path] | None] | None = None,
                voz_ref: tuple[Path, str] | None = None) -> Path:
    """guion = {"titulo", "escenas": [{"texto": lo que dice, "visual_en": la imagen en inglés}]}
    fuente(visual_en, i) → ("clip" | "imagen", ruta) con material propio del personaje, o None para hacer una con FLUX.
    voz_ref = (muestra.wav, lo que dice la muestra): la voz Qwen3 del personaje."""
    carpeta.mkdir(parents=True, exist_ok=True)
    aspecto = identidad.get("apariencia_en", "")
    semilla = int(identidad.get("semilla") or 1234)
    escenas = []
    for i, e in enumerate(guion["escenas"][:8]):
        audio = carpeta / f"voz{i}.wav"
        if voz_elevenlabs(e["texto"], audio) or voz_ref and voz_qwen(e["texto"], audio, *voz_ref):
            pass
        elif not voz_kokoro(e["texto"], audio):
            if voz_reserva is None:
                raise RuntimeError("no hay voz disponible (instala Kokoro con instalar_voz_nexus.sh)")
            voz_reserva(e["texto"], audio)
        propio = fuente(e.get("visual_en", ""), i) if fuente else None
        if propio and propio[0] == "clip":
            escenas.append({"clip": propio[1], "audio": audio, "texto": e["texto"]})
            continue
        if propio:
            from PIL import Image, ImageOps
            img = carpeta / f"img{i}.jpg"
            with Image.open(propio[1]) as im:      # a vertical 9:16 sin deformar (recorta lo que sobre)
                ImageOps.fit(im.convert("RGB"), (1080, 1920), Image.LANCZOS, centering=(0.5, 0.35)).save(img, quality=92)
            escenas.append({"imagen": img, "audio": audio, "texto": e["texto"]})
            continue
        img = carpeta / f"img{i}.jpg"
        prompt = (f"{aspecto}. {e.get('visual_en', '')}. Vertical 9:16 photo, cinematic lighting, high detail, "
                  "consistent character, no text, no watermark")
        imagen(prompt, 768, 1344, img, semilla + i)
        escenas.append({"imagen": img, "audio": audio, "texto": e["texto"]})
    nombre = re.sub(r"[^a-z0-9]+", "-", guion.get("titulo", "video").lower()).strip("-")[:40] or "video"
    salida = carpeta / f"{nombre}.mp4"
    return montar(escenas, carpeta, salida, identidad.get("etiqueta_video", "Personaje creado con IA"), log)


def hay_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def resumen_guion(guion: dict) -> str:
    return json.dumps(guion, ensure_ascii=False)[:2000]
