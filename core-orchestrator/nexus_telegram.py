"""
Lo que la persona manda por Telegram para que Asuka lo publique.

  Foto + «instagram» / «instagram y x» / «todas»       → la mira, escribe el texto de cada red y la publica
  Vídeo + «xbox» (opcional: el juego, «todas», redes)  → vertical para TikTok/Shorts/Reels, horizontal para Twitch,
                                                         rótulo, texto y hashtags, y lo publica
  Vídeo + redes                                        → igual, sin tratarlo como partida

Se publica al momento donde hay conexión oficial (hoy: Instagram y Facebook; YouTube y X cuando se conecten). Lo que
no se puede publicar desde fuera (TikTok, Twitch, Pinterest) queda en «Hoy toca» con su texto, para subirlo con un clic.
"""

from __future__ import annotations

import base64
import io
import re
import shutil
import subprocess
import time
from pathlib import Path

from herramientas import normalizar

ALIAS = {"tiktok": "tiktok", "tik tok": "tiktok", "instagram": "instagram", "insta": "instagram", "ig": "instagram",
         "reels?": "instagram", "youtube": "youtube", "yt": "youtube", "shorts?": "youtube", "x": "x",
         "twitter": "x", "twitch": "twitch", "pinterest": "pinterest", "facebook": "facebook", "face": "facebook",
         "fb": "facebook"}
FOTO = ("instagram", "facebook", "x", "pinterest", "tiktok")
VIDEO = ("youtube", "tiktok", "instagram", "facebook", "twitch")
XBOX = ("youtube", "tiktok", "twitch")
LIMITE = {"x": 270, "instagram": 600, "facebook": 600, "pinterest": 450, "tiktok": 300, "youtube": 600, "twitch": 140}
EXT_VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
EXT_FOTO = (".jpg", ".jpeg", ".png", ".webp")


def entender(pie: str, es_video: bool) -> dict | None:
    """¿Es algo para publicar? Devuelve redes, si es de Xbox y el resto del texto (pistas: juego, lugar…)."""
    t = normalizar(pie or "").strip(" .!¡?¿")
    redes = []
    for k, v in ALIAS.items():
        if re.search(rf"\b{k}\b", t) and v not in redes:
            redes.append(v)
    xbox = bool(re.search(r"\bxbox\b", t))
    todas = bool(re.search(r"\b(todas?|todo|en todas partes)\b", t))
    if not (redes or xbox or todas or re.search(r"\b(asuka|nexus|sube\w*|subel\w*|publica\w*|cuelga\w*)\b", t)):
        return None
    posibles = VIDEO if es_video else FOTO
    if todas:
        redes = list(posibles)
    elif not redes:
        redes = list(XBOX if (es_video and xbox) else (("instagram", "facebook", "youtube", "tiktok") if es_video
                                                        else ("instagram", "facebook")))
    sobran = [r for r in redes if r not in posibles]
    redes = [r for r in redes if r in posibles]
    resto = t
    for k in list(ALIAS) + [r"xbox", r"todas?", r"todo", r"en todas partes", r"asuka", r"nexus", r"sube\w*", r"subel\w*", r"para", r"pon\w*",
                            r"publica\w*", r"cuelga\w*", r"en", r"y", r"a", r"las?", r"redes", r"de"]:
        resto = re.sub(rf"\b{k}\b", " ", resto)
    return {"redes": redes, "sobran": sobran, "xbox": xbox, "pista": re.sub(r"[\s,]+", " ", resto).strip()}


def foto_dataurl(ruta: Path, lado: int = 1024) -> str:
    from PIL import Image, ImageOps
    with Image.open(ruta) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((lado, lado))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def fotograma(video: Path, destino: Path, posicion: float = 0.7) -> Path:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, timeout=60)
    dur = float((r.stdout or "0").strip() or 0)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur * posicion:.2f}", "-i", str(video),
                    "-frames:v", "1", "-q:v", "3", str(destino)], timeout=120, check=True)
    return destino


def guardar_foto(origen: Path, destino: Path) -> Path:
    from PIL import Image, ImageOps
    with Image.open(origen) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2160, 2160))
        im.save(destino, "JPEG", quality=92)
    return destino


def copiar(origen: Path, carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    d = carpeta / ("original" + origen.suffix.lower())
    shutil.copy(origen, d)
    return d


def marca_tiempo() -> str:
    return time.strftime("%Y%m%d-%H%M%S")
