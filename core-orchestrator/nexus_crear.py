"""
Material nuevo del personaje a partir de sus propias fotos (la cara y el pelo se mantienen):

  editar_foto(foto, instruccion_en, destino) → FLUX.1 Kontext (Black Forest Labs) y, si no puede, Qwen-Image-Edit,
                                              los dos en Hugging Face, gratis con cupo diario (ZeroGPU).
  sjinn_video(mensaje, destino)              → SJinn (sjinn.ai), agente de vídeo de pago por créditos, si la persona
                                              ha dado su clave («clave de sjinn …»). Mínimo 200 créditos por tarea.

Los clips con movimiento a partir de una foto los sigue haciendo estudio.clip(..., forzar="wan").
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.request
from pathlib import Path

ESPACIOS = [("black-forest-labs/FLUX.1-Kontext-Dev", lambda: (0, True, 2.5, 24)),
            ("Qwen/Qwen-Image-Edit", lambda: (0, True, 4.0, 30, False))]
SJINN = "https://sjinn.ai/api/un-api"


class SinCupo(Exception):
    pass


def _token():
    try:
        from estudio import leer_claves
        return leer_claves().get("hf") or None
    except Exception:
        return None


def editar_foto(foto: Path, instruccion_en: str, destino: Path, log=print, orden: list[str] | None = None) -> str:
    """Devuelve el nombre del motor que la ha hecho. Lanza SinCupo si todos han gastado el cupo de hoy.
    `orden`: nombres de motor preferidos primero (Nexus los ordena según cuántas fotos de cada uno pasan el control)."""
    from gradio_client import Client, handle_file
    from PIL import Image
    errores = []
    prompt = ("Keep exactly the same woman: same face, same long red hair, same thin metal glasses, same body. "
              + instruccion_en + " Bright, well-lit realistic smartphone photo, natural daylight, her face clearly visible and"
              " recognizable, looking at the camera, no text, no watermark.")
    espacios = sorted(ESPACIOS, key=lambda e: (orden or []).index(e[0].split("/")[-1])
                      if e[0].split("/")[-1] in (orden or []) else 99)
    for espacio, extra in espacios:
        try:
            tok = _token()
            c = Client(espacio, token=tok, verbose=False) if tok else Client(espacio, verbose=False)
            r, _ = c.predict(handle_file(str(foto)), prompt[:1500], *extra(), api_name="/infer")
            ruta = r["path"] if isinstance(r, dict) else r
            with Image.open(ruta) as im:
                im.convert("RGB").save(destino, "JPEG", quality=93)
            log(f"nexus: foto nueva con {espacio.split('/')[-1]}")
            return espacio.split("/")[-1]
        except Exception as e:
            errores.append(f"{espacio.split('/')[-1]}: {str(e)[:90]}")
    if all("quota" in e.lower() or "limit" in e.lower() for e in errores):
        raise SinCupo("; ".join(errores))
    raise RuntimeError("; ".join(errores))


# ---------------------------------------------------------------- foto → vídeo con movimiento (Wan 2.2 rápido)
WAN_RAPIDO = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"   # comprobado el 3 nov 2026: 5 s en ~100 s, sin marca de agua
WAN_NIFTY = "cbensimon/wan2-2-fp8da-aoti-preview2"         # el de NiftyVid: admite foto final
LTX23 = "Lightricks/LTX-2-3"                              # LTX 2.3 oficial: 1024×1536, alta calidad (el de wan2.video)
LTX23_HABLA = "linoyts/LTX-2-3-sync"                     # LTX 2.3: retrato que habla con un audio dado (labios sincronizados)
HUNYUAN = "multimodalart/Hunyuan-Video-1-5"                  # HunyuanVideo 1.5 I2V destilado (6 pasos)
FOLEY = "tencent/HunyuanVideo-Foley"                       # le pone sonido realista a un vídeo mudo
LTX_RAPIDO = "Lightricks/ltx-video-distilled"           # el oficial de LTX (I2V, ZeroGPU), de reserva
NEGATIVO = "static, still image, blurry, distorted face, deformed hands, extra limbs, extra dogs, low quality, text"


def animar_foto(foto: Path, prompt_en: str, destino: Path, segundos: float = 4, log=print,
                final: Path | None = None) -> Path:
    """Una foto suya convertida en un clip con movimiento real (Wan 2.2 en espacios gratis de Hugging Face; el mismo
    que usa NiftyVid). Con «final», el vídeo va de la primera foto a la segunda (solo el espacio «preview2»).
    Si un espacio falla prueba el siguiente; LTX-Video de reserva. Lanza SinCupo si no queda cupo en ninguno."""
    from gradio_client import Client, handle_file
    tok = _token()
    prompt = prompt_en[:900] + ", natural realistic motion, same face, same person"
    segundos = max(2.0, min(float(segundos), 4.5))          # más de ~5 s, el espacio gratis se corta y no devuelve nada
    errores = []
    espacios = [("Wan 2.2", WAN_NIFTY)] if final else [("Wan 2.2", WAN_RAPIDO), ("Wan 2.2", WAN_NIFTY),
                                                        ("HunyuanVideo 1.5", HUNYUAN), ("LTX-Video", LTX_RAPIDO)]
    for nombre, espacio in espacios:
        try:
            c = Client(espacio, token=tok, verbose=False) if tok else Client(espacio, verbose=False)
            if espacio == WAN_RAPIDO:
                r = c.predict(handle_file(str(foto)), prompt, 6, NEGATIVO, segundos, 1, 1, 42, True,
                              api_name="/generate_video")
            elif espacio == WAN_NIFTY:
                r = c.predict(handle_file(str(foto)), handle_file(str(final)) if final else None, prompt, 6, NEGATIVO,
                              segundos, 1, 1, 42, True, 6, "UniPCMultistep", 3.0, 16, False, True,
                              api_name="/generate_video")
            elif espacio == HUNYUAN:                      # 61 fotogramas ≈ 2,5-4 s
                r = c.predict(handle_file(str(foto)), prompt, 61 if segundos <= 3 else 81, 6, 5.0, -1, 1.0, False,
                              api_name="/generate")
            else:                                         # vertical 448×768 (múltiplos de 32)
                r = c.predict(prompt, NEGATIVO, handle_file(str(foto)), None, 768, 448, "image-to-video",
                              segundos, 9, 42, True, 1, True, api_name="/image_to_video")
        except Exception as ex:
            errores.append((nombre, ex))
            log(f"nexus: {nombre} ({espacio.split('/')[-1]}) no ha podido ({str(ex)[:120]})")
            continue
        v = r[0] if isinstance(r, (list, tuple)) else r
        ruta = v.get("video") if isinstance(v, dict) else v
        if not ruta or not Path(str(ruta)).exists():
            errores.append((nombre, RuntimeError("no ha devuelto vídeo")))
            continue
        shutil.copy(ruta, destino)
        log(f"nexus: clip con movimiento ({nombre}, {espacio.split('/')[-1]}) a partir de {foto.name}")
        return destino
    if errores and all(("quota" in str(e).lower() or "limit" in str(e).lower()) for _, e in errores):
        raise SinCupo(str(errores[-1][1])[:200])
    raise errores[0][1] if errores else RuntimeError("sin espacios de vídeo")


def _cliente(espacio: str):
    from gradio_client import Client
    tok = _token()
    return Client(espacio, token=tok, verbose=False) if tok else Client(espacio, verbose=False)


def _sin_cupo(ex: Exception) -> bool:
    t = str(ex).lower()
    return "quota" in t or "limit" in t or "exceeded" in t


def poner_sonido(video: Path, descripcion_en: str, destino: Path, log=print) -> Path:
    """HunyuanVideo-Foley: sonido real para un clip mudo (pasos, perros, terraza, río…), a partir del propio vídeo."""
    from gradio_client import handle_file
    try:
        c = _cliente(FOLEY)
        try:
            r = c.predict({"video": handle_file(str(video))}, descripcion_en[:300], "speech, talking, music, noise", 4.5, 25, 1,
                          api_name="/process_inference")
        except Exception as ex:
            if _sin_cupo(ex):
                raise
            r = c.predict(handle_file(str(video)), descripcion_en[:300], "speech, talking, music, noise", 4.5, 25, 1,
                          api_name="/process_inference")
    except Exception as ex:
        if _sin_cupo(ex):
            raise SinCupo(str(ex)[:200]) from ex
        raise
    v = r[0] if isinstance(r, (list, tuple)) else r
    ruta = v.get("video") if isinstance(v, dict) else v
    if not ruta or not Path(str(ruta)).exists():
        raise RuntimeError("Foley no ha devuelto vídeo")
    shutil.copy(ruta, destino)
    log(f"nexus: sonido real puesto al clip (HunyuanVideo-Foley): {destino.name}")
    return destino


def video_alta_calidad(foto: Path, prompt_en: str, destino: Path, segundos: float = 5, log=print) -> Path:
    """Clip de alta calidad con LTX 2.3 (1024×1536 vertical, 24 fps, con sonido ambiente), como en wan2.video."""
    from gradio_client import handle_file
    try:
        r = _cliente(LTX23).predict(handle_file(str(foto)), prompt_en[:900] + ", photorealistic, natural motion, same "
                                    "face, ambient sound, no speech", float(segundos), False, 10, True, 1536, 1024,
                                    api_name="/generate_video")
    except Exception as ex:
        if _sin_cupo(ex):
            raise SinCupo(str(ex)[:200]) from ex
        raise
    shutil.copy(r[0] if isinstance(r, (list, tuple)) else r, destino)
    log(f"nexus: clip de alta calidad (LTX 2.3) a partir de {foto.name}")
    return destino


def video_hablando(foto: Path, audio: Path, destino: Path, prompt_en: str = "", log=print, alta: bool = True) -> Path:
    """Ella hablando a cámara con SU voz (el audio de Piper): LTX 2.3 anima el retrato y sincroniza los labios."""
    from gradio_client import handle_file
    import subprocess
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(audio)], capture_output=True, text=True).stdout.strip() or 4)
    alto, ancho = (1536, 1024) if alta else (768, 512)
    try:
        r = _cliente(LTX23_HABLA).predict(
            handle_file(str(foto)), None, (prompt_en or "she talks to the camera naturally, friendly, small head "
                                           "movements and expressions, realistic lip sync"),
            round(min(dur + 0.3, 8.0), 1), 0.85, False, False, 42, True, alto, ancho, handle_file(str(audio)),
            api_name="/generate_video")
    except Exception as ex:
        if _sin_cupo(ex):
            raise SinCupo(str(ex)[:200]) from ex
        raise
    shutil.copy(r[0] if isinstance(r, (list, tuple)) else r, destino)
    log(f"nexus: vídeo de ella hablando (LTX 2.3 con su voz) a partir de {foto.name}")
    return destino


# ---------------------------------------------------------------- SJinn
def _sjinn(clave: str, ruta: str, cuerpo: dict | None = None, timeout: float = 60) -> dict:
    req = urllib.request.Request(f"{SJINN}/{ruta}", data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    if not d.get("success"):
        codigo = d.get("error_code")
        motivo = {100: "no quedan créditos", 101: "hace falta una suscripción"}.get(codigo, d.get("errorMsg") or "error")
        raise RuntimeError(f"SJinn: {motivo} ({codigo})")
    return d.get("data") or {}


def sjinn_video(mensaje: str, destino: Path, barato: bool = True, log=print, espera: float = 1800) -> Path:
    from estudio import leer_claves
    clave = leer_claves().get("sjinn")
    if not clave:
        raise RuntimeError("falta la clave de SJinn («clave de sjinn …» por Telegram)")
    d = _sjinn(clave, "create_agent_task", {"message": mensaje[:4000], "quality": "cheap" if barato else "quality"})
    chat = d["chat_id"]
    log(f"nexus: SJinn trabajando ({chat})")
    t0 = time.time()
    while time.time() - t0 < espera:
        time.sleep(30)
        s = _sjinn(clave, "query_agent_task_status", {"chat_id": chat, "tool_names": ["ffmpeg_full_compose"]})
        if s.get("status") == 1 and s.get("tool_results"):
            urls = [u for tr in s["tool_results"] for u in (tr.get("result") or []) if str(u).endswith(".mp4")]
            if urls:
                with urllib.request.urlopen(urls[-1], timeout=300) as r, open(destino, "wb") as f:
                    shutil.copyfileobj(r, f)
                return destino
    raise RuntimeError("SJinn tarda demasiado")
