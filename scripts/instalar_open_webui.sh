#!/bin/bash
# Open WebUI (https://github.com/open-webui/open-webui): una página de chat tipo ChatGPT en este equipo, con
# historial, documentos y búsqueda web, que usa las IA del asistente: OmniRoute (Groq, Hugging Face, DuckDuckGo…)
# y, si está, la IA local de Ollama. Solo en 127.0.0.1:8080, sin cuentas (un solo usuario).
#
#   bash ~/jarvis/instalar_open_webui.sh        (sin sudo; ocupa ~3 GB; arranca solo cuando lo pides)
#   El asistente: «abre el chat web» / «cierra el chat web».
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR

VERSION="${OPEN_WEBUI_VERSION:-0.12.4}"
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
SECRETOS="${JARVIS_SECRETOS:-$J}"
BASE="$HOME/.local/share/open-webui"
ENTORNO="$HOME/.config/open-webui/entorno"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

paso "uv (gestor de Python de Astral)"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi
uv --version

paso "Open WebUI $VERSION con Python 3.12 (Open WebUI aún no admite 3.13+); varios minutos"
mkdir -p "$BASE/datos" "$(dirname "$ENTORNO")"
[ -x "$BASE/venv/bin/python" ] || uv venv --python 3.12 "$BASE/venv"
# PyTorch solo para procesador (la versión con CUDA ocupa 4 GB más y aquí no sirve)
uv pip install --python "$BASE/venv/bin/python" --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cpu "open-webui==$VERSION" 2>&1 | tail -3

paso "Configuración (conectada a OmniRoute y a Ollama)"
CLAVE_OMNI=""
[ -f "$SECRETOS/omniroute.json" ] && CLAVE_OMNI=$(python3 -c "import json;print(json.load(open('$SECRETOS/omniroute.json'))['clave'])")
SECRETO=$(cat "$BASE/secreto" 2>/dev/null || openssl rand -hex 32)
umask 077
echo "$SECRETO" > "$BASE/secreto"
cat > "$ENTORNO" <<EOF
DATA_DIR=$BASE/datos
WEBUI_AUTH=False
WEBUI_NAME=Athena · chat
WEBUI_SECRET_KEY=$SECRETO
ENABLE_OPENAI_API=True
OPENAI_API_BASE_URL=http://127.0.0.1:20128/v1
OPENAI_API_KEY=$CLAVE_OMNI
OLLAMA_BASE_URL=http://127.0.0.1:11434
ENABLE_WEB_SEARCH=True
WEB_SEARCH_ENGINE=duckduckgo
DEFAULT_LOCALE=es-ES
SCARF_NO_ANALYTICS=true
DO_NOT_TRACK=true
ANONYMIZED_TELEMETRY=false
RAG_EMBEDDING_MODEL_AUTO_UPDATE=False
ENABLE_VERSION_UPDATE_CHECK=False
ENABLE_PERSISTENT_CONFIG=False
DEFAULT_MODELS=asistente
EOF
umask 022

paso "Servicio «open-webui» (no arranca solo: lo enciende el asistente cuando lo pides)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/open-webui.service" <<EOF
[Unit]
Description=Open WebUI para el asistente (solo 127.0.0.1:8080)
After=network-online.target omniroute.service

[Service]
Type=simple
EnvironmentFile=$ENTORNO
ExecStart=$BASE/venv/bin/open-webui serve --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=10
Nice=5
MemoryMax=1600M
TimeoutStartSec=600
EOF
systemctl --user daemon-reload
systemctl --user restart open-webui.service
echo -n "  Primer arranque (descarga su modelo de búsqueda en documentos; puede tardar)"
for _ in $(seq 1 300); do
    curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health 2>/dev/null | grep -q 200 && break
    echo -n "."; sleep 3
done
echo
curl -s http://127.0.0.1:8080/health && echo "  ✔ Open WebUI responde en http://127.0.0.1:8080"
systemctl --user stop open-webui.service
echo "  Parado para no gastar memoria. Dile al asistente «abre el chat web» cuando lo quieras."
