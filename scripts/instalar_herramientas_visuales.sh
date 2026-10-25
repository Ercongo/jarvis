#!/bin/bash
# Herramientas visuales para el asistente (sin sudo):
#   - anydoc (Firecrawl, MIT): lee Word, PowerPoint, Excel, OpenDocument, RTF, EPUB y PDF como texto limpio.
#   - Archify (tt-a1i, Apache-2.0): diagramas interactivos en una página HTML («haz un esquema de…»).
#   - HyperFrames (HeyGen, Apache-2.0): HTML animado → vídeo MP4 («haz un vídeo animado sobre…»), con su
#     Chrome sin ventana (~150 MB). Telemetría desactivada.
#   bash ~/jarvis/instalar_herramientas_visuales.sh
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
NODO="$HOME/.local/node"
[ -x "$NODO/bin/node" ] || NODO=/opt/omniroute
[ -x "$NODO/bin/node" ] || { echo "Falta Node 24: instala antes OmniRoute (bash $J/instalar_omniroute.sh)."; exit 1; }
export PATH="$NODO/bin:$HOME/.local/bin:$PATH" HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1

paso "anydoc (documentos → texto)"
"$J/venv/bin/pip" install -q "firecrawl-anydoc==0.2.4"
"$J/venv/bin/python" -c "import anydoc; print('  anydoc listo')"

paso "Archify (diagramas)"
A="$HOME/.local/share/archify"
if [ -d "$A/.git" ]; then git -C "$A" pull -q --ff-only; else git clone -q --depth 1 https://github.com/tt-a1i/archify "$A"; fi
ARCHIFY_UPDATE_CHECK_DISABLED=1 node "$A/archify/bin/archify.mjs" doctor | tail -1

paso "HyperFrames (vídeos con HTML) y su Chrome"
if [ -w "$NODO/lib" ]; then
    npm install -g --no-audit --no-fund hyperframes@0.8.200 2>&1 | tail -1
    HF="$NODO/bin/hyperframes"
else                                  # disco portátil: Node del sistema en /opt, sin permiso de escritura
    npm install --prefix "$HOME/.local" -g --no-audit --no-fund hyperframes@0.8.200 2>&1 | tail -1
    HF="$HOME/.local/bin/hyperframes"
fi
"$HF" telemetry disable >/dev/null 2>&1 || true
"$HF" browser ensure 2>&1 | tail -1
mkdir -p "$HOME/.local/share/hyperframes"
curl -fsSL -o "$HOME/.local/share/hyperframes/gsap.min.js" https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js
echo "  GSAP $(head -c 120 "$HOME/.local/share/hyperframes/gsap.min.js" | grep -o 'GSAP [0-9.]*' || echo 'descargado')"
echo
echo "✔ Listo. Prueba: «haz un esquema de las partes del olivo» o «haz un vídeo animado sobre la Giralda»."
