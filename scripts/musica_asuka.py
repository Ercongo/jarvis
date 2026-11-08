"""
Biblioteca de música de fondo para los vídeos de Asuka, hecha en el portátil con MusicGen (sin derechos de autor).
Espera a las 3:00 (cuando nadie usa el portátil), hace 2 pistas de 30 s de cada estilo y se va.
  ~/jarvis/venv/bin/python musica_asuka.py [--ya]
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "jarvis/core-orchestrator"))
from nexus_video import ESTILOS, MUSICA  # noqa: E402

PY = Path.home() / "jarvis/venv_musica/bin/python"
GEN = Path.home() / "jarvis/core-orchestrator/musica_ia.py"

if "--ya" not in sys.argv:
    ahora = time.localtime()
    espera = ((3 - ahora.tm_hour) % 24) * 3600 - ahora.tm_min * 60 - ahora.tm_sec
    time.sleep(max(0, espera))
MUSICA.mkdir(parents=True, exist_ok=True)
# en este portátil cada pista de 30 s tarda 1-2 h: primero una de cada estilo, luego la segunda; y a las 7 se para
# (lo que falte se hace la noche siguiente), para no quitarle memoria a Athena durante el día
for n in (1, 2):
    for estilo, (_, prompt) in ESTILOS.items():
        destino = MUSICA / f"{estilo}-{n}.wav"
        if destino.exists():
            continue
        if "--ya" in sys.argv and "--todo" not in sys.argv and 7 <= time.localtime().tm_hour < 23:
            print(time.strftime("%H:%M"), "son más de las 7: sigo la noche que viene", flush=True)
            sys.exit(0)
        t = time.time()
        r = subprocess.run(["nice", "-n", "19", str(PY), str(GEN), "--prompt", prompt, "--segundos", "30",
                            "--salida", str(destino)], capture_output=True, text=True)
        print(time.strftime("%H:%M"), estilo, n, "ok" if r.returncode == 0 else "ERROR " + r.stderr[-300:],
              f"{time.time() - t:.0f} s", flush=True)
print("biblioteca:", sorted(p.name for p in MUSICA.glob("*.wav")))
