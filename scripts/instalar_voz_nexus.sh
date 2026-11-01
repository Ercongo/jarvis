#!/bin/bash
# Voz natural para el personaje de Nexus: Kokoro-82M (hexgrad, Apache-2.0) con kokoro-onnx (thewh1teagle, MIT).
# Funciona con el procesador, sin tarjeta gráfica; voz femenina en español «ef_dora». En su propio entorno de Python
# (no toca el del asistente). Sin sudo, coste 0. ~120 MB.
#   bash ~/jarvis/instalar_voz_nexus.sh
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR
K="$HOME/.local/share/kokoro"
export PATH="$HOME/.local/bin:$PATH"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
mkdir -p "$K"

paso "Entorno de Python para Kokoro"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
[ -x "$K/venv/bin/python" ] || uv venv -q --python 3.12 "$K/venv"
uv pip install -q --python "$K/venv/bin/python" "kokoro-onnx>=0.4" soundfile

paso "Modelo (int8) y voces"
B=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -s "$K/kokoro-v1.0.int8.onnx" ] || curl -fL --progress-bar -o "$K/kokoro-v1.0.int8.onnx" "$B/kokoro-v1.0.int8.onnx"
[ -s "$K/voices-v1.0.bin" ] || curl -fL --progress-bar -o "$K/voices-v1.0.bin" "$B/voices-v1.0.bin"

cat > "$K/decir.py" <<'EOF'
# uso: decir.py "texto" salida.wav [voz] [velocidad]
import sys
from kokoro_onnx import Kokoro
import soundfile as sf
k = Kokoro(sys.argv[0].rsplit("/", 1)[0] + "/kokoro-v1.0.int8.onnx", sys.argv[0].rsplit("/", 1)[0] + "/voices-v1.0.bin")
voz = sys.argv[3] if len(sys.argv) > 3 else "ef_dora"
vel = float(sys.argv[4]) if len(sys.argv) > 4 else 1.05
m, sr = k.create(sys.argv[1], voice=voz, speed=vel, lang="es")
sf.write(sys.argv[2], m, sr)
EOF

paso "Prueba"
time "$K/venv/bin/python" "$K/decir.py" "Hola. Soy un personaje creado con inteligencia artificial, y no vengo a caerte bien." /tmp/prueba_kokoro.wav
ls -la /tmp/prueba_kokoro.wav
echo "✔ Voz lista. El asistente la usa sola en los vídeos de Nexus."
