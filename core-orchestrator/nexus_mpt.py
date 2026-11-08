"""MoneyPrinterTurbo (github.com/harry0703/MoneyPrinterTurbo) como motor de metraje para los vídeos narrados de Asuka.

Athena escribe el guion y pone la voz (la de Asuka, con Piper); MoneyPrinterTurbo busca metraje con movimiento real que
encaje con el guion (Pexels, Pixabay o Coverr, gratis con clave) o monta los clips locales, lo corta al largo exacto de la
narración y lo deja en vertical. Los subtítulos karaoke, su clip de entrada y la música los pone después Nexus, como en
el resto de sus vídeos.

Está instalado aparte (~/jarvis/herramientas/MoneyPrinterTurbo, con su propio Python 3.11 de uv) y se usa por su CLI,
que es la vía que el proyecto deja para leer audio de cualquier ruta del equipo. Las claves van a su config.toml y nunca
se escriben en el registro.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

MPT = Path.home() / "jarvis/herramientas/MoneyPrinterTurbo"
PY = MPT / ".venv/bin/python"
CONF = MPT / "config.toml"
FUENTES = ("pexels", "pixabay", "coverr")


class ErrorMPT(Exception):
    pass


def _ram_total_gb() -> float:
    try:
        for linea in Path("/proc/meminfo").read_text().splitlines():
            if linea.startswith("MemTotal:"):
                return int(linea.split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        pass
    return 0.0


# Topes según la RAM del equipo. Si se pasa, se corta MoneyPrinterTurbo, no el portátil entero (el 5 nov, con 6,5 GB
# y sin tope, lo dejó sin responder un buen rato). Con 16 GB (desde el 8 nov) hay margen para el doble y 2 hilos.
GRANDE = _ram_total_gb() >= 12
MEMORIA_ALTA, MEMORIA_MAX = ("3000M", "4000M") if GRANDE else ("1200M", "1600M")
MINIMO_LIBRE = 4500 if GRANDE else 1400     # MB libres para empezar (si no, se deja para la madrugada)
HILOS = "2" if GRANDE else "1"


def memoria_libre() -> int:
    try:
        for linea in Path("/proc/meminfo").read_text().splitlines():
            if linea.startswith("MemAvailable:"):
                return int(linea.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return 0


def _con_tope() -> list[str]:
    """Prefijo para que MoneyPrinterTurbo corra con la memoria limitada (systemd del usuario) y con prioridad baja."""
    import os
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    base = ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryHigh={MEMORIA_ALTA}", "-p", f"MemoryMax={MEMORIA_MAX}",
            "-p", "MemorySwapMax=0"]
    try:
        if shutil.which("systemd-run") and subprocess.run(base + ["true"], capture_output=True, timeout=30).returncode == 0:
            return base + ["nice", "-n", "15"]
    except (OSError, subprocess.SubprocessError):
        pass
    return ["nice", "-n", "15"]


def disponible() -> bool:
    return PY.exists() and (MPT / "cli.py").exists()


def _conf() -> str:
    if not CONF.exists():
        shutil.copy(MPT / "config.example.toml", CONF)
        CONF.chmod(0o600)
    t = CONF.read_text(encoding="utf-8")
    if re.search(r'(?m)^log_level\s*=\s*"DEBUG"', t):          # su registro, sin el detalle de depuración
        t = re.sub(r'(?m)^log_level\s*=\s*"DEBUG"', 'log_level = "INFO"', t)
        CONF.write_text(t, encoding="utf-8")
    return t


def fuentes_con_clave() -> list[str]:
    """Las fuentes de metraje que tienen clave puesta (sin leer ni enseñar la clave)."""
    if not CONF.exists():
        return []
    t = CONF.read_text(encoding="utf-8")
    return [f for f in FUENTES if re.search(rf'(?m)^\s*{f}_api_keys\s*=\s*\[\s*"[^"]+', t)]


def guardar_clave(fuente: str, clave: str) -> None:
    if fuente not in FUENTES or not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", clave):
        raise ErrorMPT("eso no parece una clave")
    t = _conf()
    linea = f'{fuente}_api_keys = ["{clave}"]'
    t, n = re.subn(rf"(?m)^\s*{fuente}_api_keys\s*=.*$", lambda _: linea, t, count=1)
    if not n:
        t = re.sub(r"(?m)^\[app\]\s*$", lambda m: m.group(0) + "\n" + linea, t, count=1)
    CONF.write_text(t, encoding="utf-8")
    CONF.chmod(0o600)


def _sin_claves(texto: str) -> str:
    t = texto
    if CONF.exists():
        for k in re.findall(r'_api_keys\s*=\s*\[\s*"([^"]+)"', CONF.read_text(encoding="utf-8")):
            t = t.replace(k, "[clave]")
    return t


def metraje(guion: str, terminos: list[str], audio: Path, destino: Path, fuente: str = "",
            materiales: list[Path] | None = None, duracion_clip: int = 5, log=print) -> Path:
    """Vídeo vertical del largo exacto de `audio`, con metraje que encaja con el guion. Lo devuelve en `destino`.

    fuente: pexels / pixabay / coverr (necesitan clave) o «local» con `materiales` (solo vídeos: nada de pases de
    fotos). Sin subtítulos ni música: eso lo pone Nexus."""
    if not disponible():
        raise ErrorMPT("MoneyPrinterTurbo no está instalado")
    libre = memoria_libre()
    if libre < MINIMO_LIBRE:
        raise ErrorMPT(f"poca memoria libre ahora ({libre} MB; necesita {MINIMO_LIBRE}); lo dejo para la madrugada")
    _conf()
    fuente = fuente or next(iter(fuentes_con_clave()), "")
    args = [str(PY), "cli.py", "--video-script", guion, "--video-aspect", "9:16", "--custom-audio-file", str(audio),
            "--no-subtitle-enabled", "--bgm-volume", "0", "--video-clip-duration", str(duracion_clip),
            "--video-transition-mode", "fade-in", "--n-threads", HILOS, "--video-language", "es-ES"]
    if fuente == "local":
        vids = [m for m in (materiales or []) if m.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv")]
        if not vids:
            raise ErrorMPT("no hay vídeos locales para montar")
        carpeta = MPT / "storage/local_videos"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombres = []
        for m in vids:                                # tiene que estar en su carpeta de material (lo exige por seguridad)
            dest = carpeta / f"asuka-{m.name}"
            if not dest.exists():
                shutil.copy(m, dest)
            nombres.append(dest.name)
        args += ["--video-source", "local", "--video-materials", ",".join(nombres), "--video-concat-mode", "random"]
    elif fuente in FUENTES:
        args += ["--video-source", fuente, "--video-terms", ",".join(t.replace(",", " ") for t in terminos[:8]),
                 "--match-materials-to-script"]
    else:
        raise ErrorMPT("falta una clave de Pexels, Pixabay o Coverr para el metraje")
    tarea = str(uuid.uuid4())
    args += ["--task-id", tarea]
    log(f"nexus: MoneyPrinterTurbo ({fuente}) montando metraje para {audio.name}")
    registro = destino.with_suffix(".mpt.log")         # su salida (mucha, en DEBUG) a un archivo, no a la memoria
    try:
        with open(registro, "w", encoding="utf-8") as fsal:
            r = subprocess.run([*_con_tope(), *args], cwd=MPT, stdout=fsal, stderr=subprocess.STDOUT, text=True,
                               timeout=45 * 60)
    except subprocess.TimeoutExpired as ex:
        raise ErrorMPT("MoneyPrinterTurbo ha tardado más de 45 minutos") from ex
    salida = registro.read_text(encoding="utf-8", errors="ignore")[-200_000:]
    resultado = {}
    for linea in reversed(salida.strip().splitlines()):
        if linea.startswith("{") and '"task_id"' in linea:
            try:
                resultado = json.loads(linea).get("result") or {}
            except ValueError:
                pass
            break
    videos = [Path(v) for v in (resultado.get("videos") or []) if Path(v).exists()]
    if not videos:
        final = MPT / "storage/tasks" / tarea / "final-1.mp4"
        videos = [final] if final.exists() else []
    if r.returncode in (-9, 137) and not videos:
        raise ErrorMPT("se ha quedado sin memoria (tope de seguridad); lo reintento de madrugada")
    if r.returncode or not videos:
        cola = _sin_claves(salida[-1500:])
        error = re.findall(r"(?:error|failed)[^\n]{0,200}", cola, re.I)
        raise ErrorMPT((error[-1] if error else cola[-300:]).strip() or f"código {r.returncode}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(videos[0], destino)
    registro.unlink(missing_ok=True)
    shutil.rmtree(MPT / "storage/tasks" / tarea, ignore_errors=True)   # no se acumulan descargas
    return destino
