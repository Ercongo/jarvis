"""
Cómo es este PC y qué le conviene: lo usan el arranque (arreglos de la gráfica) y el asistente de instalación
(qué instalar según la RAM, el procesador y la gráfica).

  python3 equipo.py           → resumen y recomendaciones
  python3 equipo.py --shell   → SIN_ACELERACION=1/0, RAM_GB, NUCLEOS, GRAFICA… para los scripts
  python3 equipo.py --json
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass, field


@dataclass
class Equipo:
    ram_gb: float = 0.0
    nucleos: int = 1
    cpu: str = ""
    avx2: bool = False
    graficas: list[str] = field(default_factory=list)
    controladores: list[str] = field(default_factory=list)
    nvidia: bool = False
    portatil: bool = False
    disco_libre_gb: float = 0.0


def _leer(ruta: str) -> str:
    try:
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def detectar() -> Equipo:
    e = Equipo()
    m = re.search(r"MemTotal:\s+(\d+)", _leer("/proc/meminfo"))
    e.ram_gb = round(int(m.group(1)) / 1024 / 1024, 1) if m else 0.0
    e.nucleos = os.cpu_count() or 1
    info = _leer("/proc/cpuinfo")
    m = re.search(r"model name\s*:\s*(.+)", info)
    e.cpu = m.group(1).strip() if m else ""
    e.avx2 = " avx2" in info
    if shutil.which("lspci"):
        try:
            salida = subprocess.run(["lspci", "-k"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            salida = ""
        bloques = re.split(r"\n(?=\S)", salida)
        for b in bloques:
            if re.search(r"VGA compatible|3D controller|Display controller", b):
                e.graficas.append(b.splitlines()[0].split(": ", 1)[-1].strip())
                m = re.search(r"Kernel driver in use:\s*(\S+)", b)
                if m:
                    e.controladores.append(m.group(1))
    e.nvidia = any("nvidia" in c for c in e.controladores) or any("NVIDIA" in g for g in e.graficas)
    e.portatil = any(os.path.exists(f"/sys/class/power_supply/{b}") for b in ("BAT0", "BAT1", "BATT")) or \
        _leer("/sys/class/dmi/id/chassis_type").strip() in ("8", "9", "10", "14", "31", "32")
    try:
        e.disco_libre_gb = round(shutil.disk_usage(os.path.expanduser("~")).free / 1024 ** 3, 1)
    except OSError:
        pass
    return e


def sin_aceleracion(e: Equipo | None = None) -> bool:
    """Gráficas AMD antiguas con el controlador «radeon» (anteriores a GCN, como la ARUBA del primer portátil):
    se cuelgan cuando el navegador dibuja con ellas."""
    e = e or detectar()
    return "radeon" in e.controladores and "amdgpu" not in e.controladores


def recomendar(e: Equipo | None = None) -> dict:
    """Qué instalar y cómo configurarlo en este PC. Lo enseña el asistente; la persona decide."""
    e = e or detectar()
    ram = e.ram_gb
    r: dict = {
        "whisper_local": "tiny" if ram < 4 else "base" if ram < 12 else "small",
        "ia_local": None if ram < 4 else "qwen2.5:1.5b" if ram < 10 else "qwen2.5:3b" if ram < 20 else "qwen2.5:7b",
        "efectos_interfaz": "bajos" if ram < 6 or e.nucleos <= 2 or sin_aceleracion(e) else "normales",
        "musica_ia_local": ram >= 16 and e.nucleos >= 8,
        "voz_clonada": "lenta" if not e.nvidia else "rapida",
        "sin_aceleracion": sin_aceleracion(e),
        "avisos": [],
    }
    if ram < 4:
        r["avisos"].append("Con menos de 4 GB de RAM irá justo: mejor sin IA local y con el cerebro en la nube.")
    if not e.avx2:
        r["avisos"].append("El procesador no tiene AVX2: el reconocimiento de voz local irá más lento.")
    if e.disco_libre_gb and e.disco_libre_gb < 15:
        r["avisos"].append(f"Solo quedan {e.disco_libre_gb} GB libres: las voces y modelos ocupan varios GB.")
    if e.nvidia:
        r["avisos"].append("Hay una gráfica NVIDIA: con sus controladores se podrían usar modelos locales más grandes.")
    return r


def shell(e: Equipo | None = None) -> str:
    e = e or detectar()
    v = {"SIN_ACELERACION": "1" if sin_aceleracion(e) else "0", "RAM_GB": str(e.ram_gb), "NUCLEOS": str(e.nucleos),
         "GRAFICA": "; ".join(e.graficas), "PORTATIL": "1" if e.portatil else "0"}
    return "\n".join(f"{k}={shlex.quote(x)}" for k, x in v.items())


if __name__ == "__main__":
    import sys
    eq = detectar()
    if "--shell" in sys.argv:
        print(shell(eq))
    elif "--json" in sys.argv:
        print(json.dumps({"equipo": asdict(eq), "recomendado": recomendar(eq)}, ensure_ascii=False, indent=2))
    else:
        print(f"{'Portátil' if eq.portatil else 'Sobremesa'} · {eq.cpu} ({eq.nucleos} núcleos) · {eq.ram_gb} GB de RAM")
        print("Gráfica: " + ("; ".join(f"{g} [{c}]" for g, c in zip(eq.graficas, eq.controladores + [''] * 5))
                             or "desconocida"))
        rec = recomendar(eq)
        print(f"Recomendado: whisper {rec['whisper_local']}, IA local {rec['ia_local'] or 'ninguna'}, efectos "
              f"{rec['efectos_interfaz']}, música con IA local {'sí' if rec['musica_ia_local'] else 'no'}"
              f"{', navegador sin aceleración' if rec['sin_aceleracion'] else ''}.")
        for a in rec["avisos"]:
            print("· " + a)
