"""Clips con movimiento en la GPU gratis de Kaggle (T4, 30 h a la semana), sin pantalla y sin tocar nada.

Athena prepara un cuaderno privado con las fotos de Asuka y el movimiento de cada una, lo sube con la API oficial de
Kaggle, lo deja corriendo (Wan2GP, modelo Wan 2.2 TI2V 5B FastWan, 3 pasos, vertical 480p) y cuando termina se baja los
vídeos. Sin marca de agua y sin gastar el cupo diario de Hugging Face.

La llave (kaggle.json) se guarda en ~/.kaggle/kaggle.json con permisos 600 y nunca se escribe en el registro.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

LLAVE = Path.home() / ".kaggle/kaggle.json"
TRABAJO = Path.home() / "jarvis/nexus/kaggle"
SLUG = "asuka-clips-wan"
KAGGLE = Path.home() / "jarvis/venv/bin/kaggle"


class ErrorKaggle(Exception):
    pass


def es_llave(datos) -> bool:
    return isinstance(datos, dict) and set(datos) >= {"username", "key"} and len(datos) <= 4


def guardar_llave(datos: dict) -> str:
    LLAVE.parent.mkdir(parents=True, exist_ok=True)
    LLAVE.parent.chmod(0o700)
    LLAVE.write_text(json.dumps({"username": datos["username"], "key": datos["key"]}), encoding="utf-8")
    LLAVE.chmod(0o600)
    return datos["username"]


def usuario() -> str:
    try:
        return json.loads(LLAVE.read_text(encoding="utf-8"))["username"]
    except (OSError, ValueError, KeyError):
        return ""


def disponible() -> bool:
    return bool(usuario()) and KAGGLE.exists()


def _kaggle(*args: str, timeout: float = 300) -> str:
    r = subprocess.run([str(KAGGLE), *args], capture_output=True, text=True, timeout=timeout)
    salida = (r.stdout + r.stderr).strip()
    salida = re.sub(r"[0-9a-f]{32}", "[llave]", salida)          # por si algún error repite la llave
    if r.returncode:
        raise ErrorKaggle(salida[-400:] or f"kaggle terminó con código {r.returncode}")
    return salida


def _foto_ligera(ruta: Path) -> str:
    """La foto, a 832 px de alto como mucho, en base64 (va dentro del propio cuaderno: no hace falta subir un dataset)."""
    tmp = TRABAJO / "tmp_foto.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ruta), "-vf", "scale=-2:'min(832,ih)'", "-q:v", "3",
                    str(tmp)], check=True, timeout=60)
    datos = base64.b64encode(tmp.read_bytes()).decode()
    tmp.unlink(missing_ok=True)
    return datos


SCRIPT = r'''
# Generado por Athena: clips de Asuka con Wan2GP (Wan 2.2 TI2V 5B FastWan) en una T4 de Kaggle.
import base64, glob, json, os, shutil, subprocess, sys, time

TRABAJOS = __TRABAJOS__
NEG = "blurry, distorted face, deformed hands, extra fingers, extra people, text, watermark, low quality, flicker"
SALIDA = "/kaggle/working/asuka_clips"
os.makedirs(SALIDA, exist_ok=True)
try:
    BASE = "/kaggle/temp"; os.makedirs(BASE, exist_ok=True)
except OSError:
    BASE = "/tmp/asuka"; os.makedirs(BASE, exist_ok=True)
os.environ["HF_HOME"] = f"{BASE}/hf"
os.environ["MPLBACKEND"] = "Agg"
informe = {"inicio": time.strftime("%H:%M:%S"), "clips": [], "errores": []}

def sh(cmd, timeout=None):
    print("$", cmd, flush=True)
    return subprocess.run(cmd, shell=True, timeout=timeout).returncode

sh("nvidia-smi --query-gpu=name,memory.total --format=csv")
sh("apt-get -qq update >/dev/null 2>&1; apt-get -qq install -y ffmpeg libglib2.0-0 libgl1 libportaudio2 >/dev/null 2>&1")
W = f"{BASE}/Wan2GP"
if not os.path.isdir(W):
    sh(f"git clone -q --depth 1 https://github.com/deepbeepmeep/Wan2GP {W}")
sh(f"pip freeze | grep -iE '^(torch|torchvision|torchaudio)==' > {BASE}/fijos.txt")
if sh(f"cd {W} && pip install -q -r requirements.txt -c {BASE}/fijos.txt"):
    sh(f"cd {W} && grep -viE '^(torch|torchvision|torchaudio)([<>=~ ]|$)' requirements.txt > {BASE}/req.txt && "
       f"pip install -q -r {BASE}/req.txt")
for f in glob.glob(f"{W}/**/interact_tools.py", recursive=True):
    s = open(f).read().replace("TkAgg", "Agg"); open(f, "w").write(s)

for t in TRABAJOS:
    foto = f"{BASE}/{t['nombre']}.jpg"
    open(foto, "wb").write(base64.b64decode(t["foto"]))
    ajustes = {"model_type": "ti2v_2_2_fastwan", "prompt": t["prompt"], "negative_prompt": NEG,
               "image_prompt_type": "S", "image_start": foto, "resolution": "480x832",
               "video_length": t.get("fotogramas", 121), "num_inference_steps": 3, "guidance_scale": 1,
               "flow_shift": 3, "seed": t.get("semilla", -1), "repeat_generation": 1}
    conf = f"{BASE}/{t['nombre']}.json"
    json.dump(ajustes, open(conf, "w"))
    out = f"{BASE}/out_{t['nombre']}"
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    try:
        cod = sh(f"cd {W} && python wgp.py --process {conf} --output-dir {out} --profile 5", timeout=40 * 60)
    except subprocess.TimeoutExpired:
        cod = "tiempo"
    vids = sorted(glob.glob(f"{out}/**/*.mp4", recursive=True), key=os.path.getmtime)
    if vids:
        shutil.copy(vids[-1], f"{SALIDA}/{t['nombre']}.mp4")
        informe["clips"].append({"nombre": t["nombre"], "segundos": round(time.time() - t0)})
    else:
        informe["errores"].append({"nombre": t["nombre"], "codigo": str(cod)})
    json.dump(informe, open(f"{SALIDA}/informe.json", "w"), indent=1)
    if len(informe["errores"]) >= 2 and not informe["clips"]:
        break                                   # si los dos primeros fallan, no se sigue gastando GPU
informe["fin"] = time.strftime("%H:%M:%S")
json.dump(informe, open(f"{SALIDA}/informe.json", "w"), indent=1)
print(json.dumps(informe), flush=True)
'''


def lanzar(trabajos: list[dict]) -> str:
    """trabajos: [{"nombre", "foto": Path, "prompt"}]. Sube el cuaderno privado y lo deja corriendo en una T4."""
    u = usuario()
    if not u or not KAGGLE.exists():
        raise ErrorKaggle("falta la llave de Kaggle")
    d = TRABAJO / "cuaderno"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    lote = [{"nombre": t["nombre"], "prompt": t["prompt"], "foto": _foto_ligera(Path(t["foto"])),
             "fotogramas": t.get("fotogramas", 121)} for t in trabajos]
    (d / "asuka_clips.py").write_text(SCRIPT.replace("__TRABAJOS__", json.dumps(lote)), encoding="utf-8")
    (d / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{u}/{SLUG}", "title": SLUG, "code_file": "asuka_clips.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "machine_shape": "NvidiaTeslaT4", "dataset_sources": [], "competition_sources": [], "kernel_sources": []}),
        encoding="utf-8")
    return _kaggle("kernels", "push", "-p", str(d), "--accelerator", "NvidiaTeslaT4", timeout=600)


def estado() -> str:
    """'running', 'queued', 'complete', 'error', 'cancelAcknowledged'…"""
    s = _kaggle("kernels", "status", f"{usuario()}/{SLUG}", timeout=60)
    m = re.search(r'status "?([A-Za-z_.]+)"?', s)
    return (m.group(1) if m else s).split(".")[-1].lower()


def recoger() -> tuple[list[Path], dict, str]:
    """Baja los vídeos, el informe y el final del registro del cuaderno."""
    d = TRABAJO / f"salida-{time.strftime('%Y%m%d-%H%M')}"
    d.mkdir(parents=True, exist_ok=True)
    _kaggle("kernels", "output", f"{usuario()}/{SLUG}", "-p", str(d), timeout=1800)
    vids = sorted(d.rglob("*.mp4"))
    inf = {}
    for f in d.rglob("informe.json"):
        try:
            inf = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    registro = ""
    for f in d.glob("*.log"):
        try:
            registro = f.read_text(encoding="utf-8", errors="ignore")[-3000:]
        except OSError:
            pass
    if not registro:
        try:
            registro = _kaggle("kernels", "logs", f"{usuario()}/{SLUG}", timeout=120)[-3000:]
        except Exception:
            pass
    return vids, inf, registro
