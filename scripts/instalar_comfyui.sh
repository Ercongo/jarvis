#!/bin/bash
# ComfyUI (https://github.com/Comfy-Org/ComfyUI): generar imágenes EN ESTE EQUIPO, sin internet.
# Este portátil no tiene tarjeta gráfica que sirva, así que va con el procesador: con SD-Turbo (un solo paso) y el
# decodificador rápido TAESD tarda alrededor de un minuto por imagen. El asistente lo usa cuando no hay internet o
# cuando dices «crea una imagen en local …». Solo en 127.0.0.1:8188; se apaga solo tras usarlo.
#
#   bash ~/jarvis/instalar_comfyui.sh        (sin sudo; ~8 GB con el modelo)
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR

BASE="$HOME/.local/share/comfyui"
C="$BASE/ComfyUI"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
export PATH="$HOME/.local/bin:$PATH"

paso "uv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh

paso "ComfyUI (código)"
mkdir -p "$BASE"
if [ -d "$C/.git" ]; then git -C "$C" pull --ff-only -q; else git clone --depth 1 -q https://github.com/Comfy-Org/ComfyUI "$C"; fi
git -C "$C" log -1 --format="  %h %cd" --date=short

paso "Python 3.12 + PyTorch para procesador + dependencias"
[ -x "$BASE/venv/bin/python" ] || uv venv --python 3.12 "$BASE/venv"
uv pip install --python "$BASE/venv/bin/python" torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -2
uv pip install --python "$BASE/venv/bin/python" -r "$C/requirements.txt" \
    --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match 2>&1 | tail -2

paso "Modelos: SD-Turbo (5,2 GB, licencia de Stability AI de uso no comercial) y TAESD"
M="$C/models"
if [ ! -s "$M/checkpoints/sd_turbo.safetensors" ]; then
    curl -fL --retry 3 -C - -o "$M/checkpoints/sd_turbo.safetensors.parcial" \
        https://huggingface.co/stabilityai/sd-turbo/resolve/main/sd_turbo.safetensors
    mv "$M/checkpoints/sd_turbo.safetensors.parcial" "$M/checkpoints/sd_turbo.safetensors"
fi
mkdir -p "$M/vae_approx"
for f in taesd_decoder.pth taesd_encoder.pth; do
    [ -s "$M/vae_approx/$f" ] || curl -fsSL -o "$M/vae_approx/$f" "https://github.com/madebyollin/taesd/raw/main/$f"
done
ls -la "$M/checkpoints" "$M/vae_approx" | grep -E "safetensors|pth"

paso "Servicio «comfyui» (no arranca solo)"
mkdir -p "$HOME/.config/systemd/user"
TOPE_MEM=$([ "$(awk '/MemTotal/{print int($2/1048576)}' /proc/meminfo)" -ge 12 ] && echo 9000M || echo 5500M)   # según la RAM
cat > "$HOME/.config/systemd/user/comfyui.service" <<EOF
[Unit]
Description=ComfyUI para el asistente (solo 127.0.0.1:8188, con el procesador)

[Service]
Type=simple
WorkingDirectory=$C
ExecStart=$BASE/venv/bin/python main.py --cpu --listen 127.0.0.1 --port 8188 --disable-auto-launch --preview-method none
Restart=no
Nice=10
MemoryMax=$TOPE_MEM
EOF
systemctl --user daemon-reload
echo "  Listo. Pruébalo: dile al asistente «crea una imagen en local de un gato en la luna»."
