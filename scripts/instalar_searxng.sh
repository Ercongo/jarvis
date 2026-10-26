#!/bin/bash
# SearXNG (https://github.com/searxng/searxng, AGPL-3.0): buscador propio en este equipo que pregunta a la vez a
# Google, Bing, Brave, DuckDuckGo, Wikipedia… y devuelve los resultados juntos, sin cuentas ni rastreo. El asistente
# lo usa primero para «investiga…», «busca en internet…» y lo que aprende; si falla, sigue con DuckDuckGo.
# Solo en 127.0.0.1:8888 (no se ve desde fuera). ~110 MB de memoria.
#
#   bash ~/jarvis/instalar_searxng.sh        (sin sudo)
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR
BASE="$HOME/.local/share/searxng"
CONF="$HOME/.config/searxng"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
export PATH="$HOME/.local/bin:$PATH"

paso "uv (gestor de Python)"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
uv --version

paso "SearXNG (código de GitHub, rama principal)"
mkdir -p "$BASE" "$CONF"
if [ -d "$BASE/src/.git" ]; then git -C "$BASE/src" pull -q --ff-only; else git clone -q --depth 1 https://github.com/searxng/searxng "$BASE/src"; fi
git -C "$BASE/src" log -1 --format='  versión del %cd (%h)' --date=short
[ -x "$BASE/venv/bin/python" ] || uv venv -q --python 3.12 "$BASE/venv"
uv pip install -q --python "$BASE/venv/bin/python" -r "$BASE/src/requirements.txt"

paso "Configuración (español, solo este equipo, con salida JSON para el asistente)"
umask 077
[ -s "$CONF/entorno" ] || echo "SEARXNG_SECRET=$(openssl rand -hex 32)" > "$CONF/entorno"
umask 022
cat > "$CONF/settings.yml" <<'EOF'
use_default_settings: true
general:
  instance_name: "Athena"
  enable_metrics: false
search:
  safe_search: 0
  autocomplete: ""
  default_lang: "es-ES"
  formats: [html, json]
server:
  port: 8888
  bind_address: "127.0.0.1"
  limiter: false
  public_instance: false
  image_proxy: false
ui:
  default_locale: "es"
outgoing:
  request_timeout: 4.0
  max_request_timeout: 8.0
EOF

paso "Servicio «searxng» (arranca con la sesión)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/searxng.service" <<EOF
[Unit]
Description=SearXNG para el asistente (solo 127.0.0.1:8888)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$BASE/src
Environment=SEARXNG_SETTINGS_PATH=$CONF/settings.yml
Environment=PYTHONPATH=$BASE/src
EnvironmentFile=$CONF/entorno
ExecStart=$BASE/venv/bin/python -m searx.webapp
Restart=on-failure
RestartSec=15
Nice=5
MemoryMax=300M

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable -q searxng.service
systemctl --user restart searxng.service
for _ in $(seq 1 40); do
    curl -s -o /dev/null "http://127.0.0.1:8888/healthz" && break; sleep 1
done
N=$(curl -s -H "X-Real-IP: 127.0.0.1" "http://127.0.0.1:8888/search?q=Giralda+Sevilla&format=json" \
    | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null || echo 0)
echo "  Prueba «Giralda Sevilla»: $N resultados"
[ "$N" -gt 0 ] && echo "✔ SearXNG listo. El asistente ya busca con él." || echo "⚠ Arrancado, pero sin resultados aún (¿hay internet?)."
