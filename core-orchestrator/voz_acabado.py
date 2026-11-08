"""Acabado de la voz Piper: quita el brillo metálico, calienta los graves y le da una sala mínima (ffmpeg)."""
import subprocess
from pathlib import Path

ACABADO_VOZ = ("highpass=f=70,lowpass=f=9500,equalizer=f=3200:t=q:w=1.2:g=-2.5,equalizer=f=6500:t=q:w=2:g=-4,"
               "bass=g=2.5:f=180,aecho=0.8:0.5:22|37:0.12|0.07,loudnorm=I=-16:TP=-1.5")


def acabar_voz(ruta: Path) -> None:
    """Si falla, el audio se queda como estaba."""
    ruta = Path(ruta)
    tmp = ruta.with_name(ruta.stem + "_ac.wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ruta), "-af", ACABADO_VOZ, "-ar", "22050",
                        str(tmp)], check=True, timeout=30)
        tmp.replace(ruta)
    except Exception:
        tmp.unlink(missing_ok=True)
