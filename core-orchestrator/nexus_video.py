"""
Vídeos cortos verticales (1080×1920) para el proyecto Nexus, a coste 0 y en este portátil:

  guion por escenas  →  voz del personaje: Qwen3-TTS (espacio gratuito de Qwen en Hugging Face, con la voz propia
                         del personaje diseñada una vez y reutilizada siempre); si falla, Kokoro «ef_dora»; si no, Piper
                     →  por escena, lo que mejor encaje: un clip del personaje (DeeVid, OpenGen, Viggle, Wan…), una de
                         sus fotos de referencia, o una imagen nueva con FLUX
                     →  movimiento suave (zoom), subtítulos grandes palabra a palabra
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


def voz_piper(voz_piper, texto: str, destino: Path, hablante: int = 0, ajustes: dict | None = None) -> None:
    """Voz Piper (la entrenada de Asuka) con los mismos ajustes de naturalidad que Athena (perfil «voz»)."""
    from piper import SynthesisConfig
    a = ajustes or {}
    with wave.open(str(destino), "wb") as w:
        voz_piper.synthesize_wav(texto, w, syn_config=SynthesisConfig(
            speaker_id=hablante if getattr(getattr(voz_piper, "config", None), "num_speakers", 2) > 1 else None,
            length_scale=float(a.get("lentitud") or 1.0), noise_scale=a.get("ruido"), noise_w_scale=a.get("ritmo")))
    if a.get("acabado"):
        from voz_acabado import acabar_voz
        acabar_voz(destino)


def tiene_audio(ruta: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                        str(ruta)], capture_output=True, text=True)
    return bool(r.stdout.strip())


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


def _karaoke(e: dict, inicio: float) -> list[str]:
    """Subtítulos como los de TikTok: 3 palabras en pantalla y la que está diciendo, en amarillo y un poco más grande.
    Los tiempos salen de su voz (Whisper con marcas por palabra); el texto, del guion (sin faltas)."""
    if not e.get("audio"):
        return []
    try:
        from fuentes import palabras_con_tiempo
        oidas = palabras_con_tiempo(Path(e["audio"]))
    except Exception:
        return []
    mias = [w.replace("{", "(").replace("}", ")") for w in e["texto"].split()]
    if not oidas or abs(len(oidas) - len(mias)) > max(2, len(mias) // 5):
        return []                                      # no cuadran: mejor los de siempre
    if len(oidas) != len(mias):                       # una o dos de diferencia: se reparten los tiempos
        a0, b0 = oidas[0]["a"], oidas[-1]["b"]
        paso = (b0 - a0) / len(mias)
        oidas = [{"a": a0 + i * paso, "b": a0 + (i + 1) * paso} for i in range(len(mias))]
    lineas = []
    for g in range(0, len(mias), 3):
        grupo = list(range(g, min(g + 3, len(mias))))
        for k, i in enumerate(grupo):
            a = inicio + oidas[i]["a"]
            b = inicio + (oidas[grupo[k + 1]]["a"] if k + 1 < len(grupo) else
                          (oidas[grupo[-1] + 1]["a"] if grupo[-1] + 1 < len(mias) else oidas[i]["b"] + 0.35))
            texto = " ".join((r"{\c&H00E5FF&\fscx112\fscy112}" + mias[j].upper() + r"{\r}") if j == i else mias[j].upper()
                             for j in grupo)
            lineas.append(f"Dialogue: 0,{_ass_tiempo(a)},{_ass_tiempo(max(b, a + 0.08))},Sub,,0,0,0,,{texto}")
    return lineas


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
        karaoke = _karaoke(e, t)                       # palabra a palabra, con su momento real (si se puede)
        if karaoke:
            lineas += karaoke
            t += e["dur"]
            continue
        palabras = e["texto"].split()
        trozos = [" ".join(palabras[i:i + 4]) for i in range(0, len(palabras), 4)] or [""]
        total = sum(len(x) for x in trozos) or 1
        for tr in trozos:
            d = e["dur"] * len(tr) / total
            limpio = tr.replace("{", "(").replace("}", ")").upper()
            lineas.append(f"Dialogue: 0,{_ass_tiempo(t)},{_ass_tiempo(t + d)},Sub,,0,0,0,,{limpio}")
            t += d
    if etiqueta:
        lineas.append(f"Dialogue: 1,{_ass_tiempo(0)},{_ass_tiempo(t + 1)},Eti,,0,0,0,,{etiqueta}")
    destino.write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")


# ================================================================ montaje
MUSICA = Path.home() / "jarvis/nexus/musica"
ESTILOS = {   # estilo: (palabras del vídeo que lo piden, lo que se le pide a MusicGen)
    "acustica": (r"perr|peques|jazm|leia|parque|rio|pantano|playa|paseo|excursi|dog|river|lake|beach|park",
                 "warm acoustic guitar, light percussion, happy relaxed afternoon walk, instrumental, 90 bpm"),
    "synthwave": (r"xbox|partida|juego|gaming|gamer|halo|forza|souls|crimson|setup|rgb",
                  "synthwave retro gaming beat, punchy drums, neon arpeggios, energetic, instrumental, 110 bpm"),
    "epica": (r"anime|cosplay|akatsuki|naruto|titan|demon|evangelion|epic|tablada|avion|saeta",
              "epic cinematic anime orchestral, taiko drums, rising strings, heroic, instrumental"),
    "lofi": (r".", "lofi hip hop chill beat, soft piano, vinyl crackle, cozy evening, instrumental, 80 bpm"),
}


def elegir_musica(texto: str) -> Path | None:
    """Una pista de su biblioteca (hecha con MusicGen en el portátil: sin derechos de autor) según de qué va el vídeo."""
    import random as _r
    t = (texto or "").lower()
    for estilo, (patron, _) in ESTILOS.items():
        if re.search(patron, t):
            pistas = sorted(MUSICA.glob(f"{estilo}-*.wav"))
            if pistas:
                return _r.choice(pistas)
    todas = sorted(MUSICA.glob("*.wav"))
    return _r.choice(todas) if todas else None


def poner_musica(video: Path, musica: Path, volumen: float = 0.13) -> Path:
    """La música por debajo de la voz (más baja cuando ella habla), con entrada y salida suaves."""
    dur = duracion(video)
    tmp = video.with_name(video.stem + "-m.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(musica),
                        "-filter_complex",
                        f"[1:a]volume={volumen},afade=t=in:d=1,afade=t=out:st={max(0.0, dur - 1.5):.2f}:d=1.5[m];"
                        "[m][0:a]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];"
                        "[0:a][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{dur:.2f}",
                        "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 10000:
        tmp.replace(video)
    return video


def montar(escenas: list[dict], carpeta: Path, salida: Path, etiqueta: str, log: Callable[[str], None] = print) -> Path:
    """escenas: [{"imagen": Path | "clip": Path, "audio": Path, "texto": str}] → MP4 vertical con voz y subtítulos.
    Una imagen lleva zoom suave; un clip se recorta a vertical, se repite si es corto y pierde su sonido."""
    partes = []
    for i, e in enumerate(escenas):
        e["dur"] = max(1.5, duracion(e["audio"]) + 0.25)
        clip = carpeta / f"esc{i}.mp4"
        frames = int(e["dur"] * 30)
        zoom = "min(zoom+0.0009,1.12)" if i % 2 == 0 else "if(eq(on,0),1.12,max(zoom-0.0009,1.0))"
        if e.get("clip") and e.get("seguido"):
            # toma de una historia (Kling…): entera y sin repetirse; si la voz dura más, se ralentiza un poco y
            # se queda en el último fotograma
            larga = duracion(e["clip"]) or 5.0
            e["dur"] = max(larga, duracion(e["audio"]) + 0.3)
            lento = min(1.3, max(1.0, e["dur"] / larga))
            if e.get("marca"):   # con marca de agua: el clip entero (la marca se ve) sobre él mismo difuminado
                vf = (f"[0:v]setpts={lento:.3f}*PTS,fps=30,tpad=stop_mode=clone:stop_duration=5,split[a][b];"
                      f"[a]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},boxblur=30:3[f];"
                      f"[b]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=decrease[c];[f][c]overlay=(W-w)/2:(H-h)/2,"
                      "format=yuv420p[v];[1:a]apad,aresample=44100[a]")
            else:
                vf = (f"[0:v]setpts={lento:.3f}*PTS,scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
                      f"crop={ANCHO}:{ALTO},fps=30,tpad=stop_mode=clone:stop_duration=5,format=yuv420p[v];"
                      "[1:a]apad,aresample=44100[a]")
            if tiene_audio(e["clip"]) and lento == 1.0 and not e.get("propio"):
                # el clip trae su sonido (LTX 2.3: terraza, calle, perros…): se queda bajito debajo de su voz
                vf = vf.replace("[1:a]apad,aresample=44100[a]",
                                "[0:a]aresample=44100,volume=0.28,apad[amb];[1:a]aresample=44100,apad[vz];"
                                "[vz][amb]amix=inputs=2:duration=first:normalize=0[a]")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(e["clip"]), "-i", str(e["audio"]),
                            "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-t", f"{e['dur']:.2f}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                            str(clip)], check=True)
            partes.append(clip)
            continue
        if e.get("clip"):
            if e.get("marca"):      # la marca de agua del servicio gratis se respeta: clip entero sobre fondo difuminado
                vf = (f"[0:v]split[a][b];[a]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},"
                      f"boxblur=30:3[f];[b]scale={ANCHO}:-2[c];[f][c]overlay=0:(H-h)/2,fps=30,format=yuv420p[v];"
                      "[1:a]apad,aresample=44100[a]")
            else:
                vf = (f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},"
                      "fps=30,format=yuv420p[v];[1:a]apad,aresample=44100[a]")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(e["clip"]),
                            "-i", str(e["audio"]), "-filter_complex", vf,
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
    pista = elegir_musica(" ".join(e.get("texto", "") for e in escenas) + " " + salida.stem)
    if pista:
        poner_musica(salida, pista)
    log(f"nexus: vídeo {salida.name} ({duracion(salida):.0f} s)" + (f" con música «{pista.stem}»" if pista else ""))
    return salida


def _duracion(ruta: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                       capture_output=True, text=True, timeout=60)
    return float((r.stdout or "0").strip() or 0)


def repartir_voz(total: Path, textos: list[str], carpeta: Path) -> bool:
    """Corta la locución entera en un trozo por escena: por lo que mide cada texto, ajustando cada corte al
    silencio más cercano (entre frase y frase)."""
    try:
        dur = _duracion(total)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(total), "-af", "silencedetect=noise=-35dB:d=0.18",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=120)
        ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
        fin = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
        silencios = [(a + b) / 2 for a, b in zip(ini, fin)]
        pesos = [max(1, len(t)) for t in textos]
        cortes, acum = [0.0], 0
        for p in pesos[:-1]:
            acum += p
            ideal = dur * acum / sum(pesos)
            cerca = min(silencios, key=lambda s: abs(s - ideal), default=ideal)
            c = cerca if abs(cerca - ideal) < 1.5 and cerca > cortes[-1] + 0.5 else ideal
            cortes.append(c)
        cortes.append(dur)
        for i in range(len(textos)):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(total), "-ss", f"{cortes[i]:.3f}", "-to",
                            f"{cortes[i + 1]:.3f}", "-ar", "44100", "-ac", "1", str(carpeta / f"voz{i}.wav")],
                           check=True, timeout=120)
        return all((carpeta / f"voz{i}.wav").stat().st_size > 1000 for i in range(len(textos)))
    except Exception:
        return False


def crear_corto(guion: dict, identidad: dict, carpeta: Path, imagen: Callable[[str, int, int, Path, int | None], Path],
                voz_reserva: Callable[[str, Path], None] | None = None, log: Callable[[str], None] = print,
                fuente: Callable[[str, int], tuple[str, Path] | None] | None = None,
                voz_ref: tuple[Path, str] | None = None,
                voz_propia: Callable[[str, Path], None] | None = None) -> Path:
    """guion = {"titulo", "escenas": [{"texto": lo que dice, "visual_en": la imagen en inglés}]}
    fuente(visual_en, i) → ("clip" | "imagen", ruta) con material propio del personaje, o None para hacer una con FLUX.
    voz_ref = (muestra.wav, lo que dice la muestra): la voz Qwen3 del personaje."""
    carpeta.mkdir(parents=True, exist_ok=True)
    aspecto = identidad.get("apariencia_en", "")
    semilla = int(identidad.get("semilla") or 1234)
    escenas = []
    textos = [e["texto"] for e in guion["escenas"][:8]]

    def reserva(texto: str, audio: Path) -> None:
        if not voz_kokoro(texto, audio):
            if voz_reserva is None:
                raise RuntimeError("no hay voz disponible (instala Kokoro con instalar_voz_nexus.sh)")
            voz_reserva(texto, audio)

    # la voz, entera de una misma fuente: si la buena falla a mitad (p. ej. se acaba el cupo diario de Hugging Face),
    # todo el vídeo se hace con la de reserva, para que no cambie de voz entre escenas
    buena = None
    if voz_propia:       # la voz entrenada de Asuka (Piper, en el portátil): sin cupo ni internet
        try:
            for i, tx in enumerate(textos):
                voz_propia(tx, carpeta / f"voz{i}.wav")
            buena = "Asuka (Piper)"
        except Exception as ex:
            log(f"nexus: la voz entrenada ha fallado ({ex}); pruebo con Qwen3")
    if not buena and voz_ref:          # Qwen3 de una sola vez (cada petición gasta ~90 s del cupo diario gratis) y se reparte
        total = carpeta / "voz_total.wav"
        if voz_qwen(" ".join(textos), total, *voz_ref) and repartir_voz(total, textos, carpeta):
            buena = "Qwen3"
    if not buena and all(voz_elevenlabs(tx, carpeta / f"voz{i}.wav") for i, tx in enumerate(textos)):
        buena = "ElevenLabs"
    if not buena:
        for i, tx in enumerate(textos):
            reserva(tx, carpeta / f"voz{i}.wav")
    log(f"nexus: voz del vídeo con {buena or 'Kokoro (reserva)'}")
    for i, e in enumerate(guion["escenas"][:8]):
        audio = carpeta / f"voz{i}.wav"
        propio = fuente(e.get("visual_en", ""), i) if fuente else None
        if propio and propio[0] == "clip":
            escenas.append({"clip": propio[1], "audio": audio, "texto": e["texto"],
                            "marca": len(propio) > 2 and propio[2]})
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
    # sin rótulo «IA» quemado en la imagen: la transparencia va en la etiqueta oficial de cada red al publicar
    return montar(escenas, carpeta, salida, identidad.get("etiqueta_video", ""), log)


def hay_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def resumen_guion(guion: dict) -> str:
    return json.dumps(guion, ensure_ascii=False)[:2000]
