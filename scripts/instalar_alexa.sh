#!/bin/bash
# Alexa de Amazon para el asistente (sin sudo): con alexa-remote2 (Apollon77, MIT) el asistente maneja lo que
# tienes conectado a Alexa (luces, enchufes, ventiladores… de cualquier marca) y puede hablar por el Echo.
#
#   bash ~/jarvis/instalar_alexa.sh
#   Luego dile «conecta alexa»: se abre la página de Amazon y entras TÚ con tu cuenta (la contraseña no pasa por
#   el asistente). Se guarda solo la sesión, en ~/jarvis/alexa.json, y se renueva sola.
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
SECRETOS="${JARVIS_SECRETOS:-$J}"
ORIGEN="${JARVIS_PROYECTO:-$HOME/jarvis-proyecto}/scripts/alexa"
[ -d "$ORIGEN" ] || ORIGEN="$J/alexa"
DEST="$HOME/.local/share/alexa-puente"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

NODO="$HOME/.local/node"
[ -x "$NODO/bin/node" ] || NODO=/opt/omniroute
[ -x "$NODO/bin/node" ] || { echo "Falta Node 24: instala antes OmniRoute (bash $J/instalar_omniroute.sh)."; exit 1; }
export PATH="$NODO/bin:$PATH"

paso "Puente con Alexa (alexa-remote2 8.1.1)"
mkdir -p "$DEST"
cp "$ORIGEN/puente.js" "$ORIGEN/package.json" "$DEST/"
(cd "$DEST" && npm install --omit=dev --no-audit --no-fund 2>&1 | tail -1)
node --check "$DEST/puente.js"

paso "Servicio «alexa-puente» (arranca con la sesión; solo 127.0.0.1:3457)"
mkdir -p "$HOME/.config/systemd/user" "$SECRETOS"
cat > "$HOME/.config/systemd/user/alexa-puente.service" <<EOF
[Unit]
Description=Puente del asistente con Alexa (luces, enchufes y Echo)
After=network-online.target

[Service]
Type=simple
Environment=JARVIS_SECRETOS=$SECRETOS
Environment=ALEXA_AMAZON=amazon.es
ExecStart=$NODO/bin/node $DEST/puente.js
Restart=on-failure
RestartSec=20
Nice=5
MemoryMax=250M

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now alexa-puente.service
for _ in $(seq 1 20); do
    E=$(curl -s http://127.0.0.1:3457/estado || true)
    [ -n "$E" ] && break; sleep 1
done
echo "  Estado: $E" | sed -E 's/"echos":\[[^]]*\]//'
echo
if echo "$E" | grep -q '"listo":true'; then
    echo "✔ Alexa conectada. Prueba: «enciende la luz del salón» o «qué dispositivos tiene alexa»."
else
    URL=$(echo "$E" | grep -o 'http://[^"]*' || true)
    echo "✔ Instalado. Falta entrar en Amazon: abre ${URL:-http://IP-del-portátil:3456/} en un navegador de casa"
    echo "  (mejor el del ordenador que el del móvil) y entra con tu cuenta. O dile al asistente «conecta alexa»."
fi
