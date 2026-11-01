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


def editar_foto(foto: Path, instruccion_en: str, destino: Path, log=print) -> str:
    """Devuelve el nombre del motor que la ha hecho. Lanza SinCupo si todos han gastado el cupo de hoy."""
    from gradio_client import Client, handle_file
    from PIL import Image
    errores = []
    prompt = ("Keep exactly the same woman: same face, same long red hair, same thin metal glasses, same body. "
              + instruccion_en + " Realistic smartphone photo, natural light, no text, no watermark.")
    for espacio, extra in ESPACIOS:
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
