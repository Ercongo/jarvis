#!/bin/bash
# Instala el asistente en este PC (Ubuntu o derivadas, con escritorio) y abre el asistente de configuración.
#
#   bash instalar.sh                 instala en ~/jarvis
#   bash instalar.sh --destino DIR   instala en otra carpeta
#   bash instalar.sh --sin-arranque  no lo pone en el inicio automático
#   bash instalar.sh --con-ollama    instala también la IA local de reserva (Ollama, unos 2 GB)
#
# Se puede repetir sin miedo: no toca la memoria, las claves ni los ajustes que ya hubiera; solo el programa
# (guardando antes una copia del programa anterior en copias_codigo/).
set -euo pipefail

ORIGEN="$(cd "$(dirname "$0")" && pwd)"
DESTINO="$HOME/jarvis"
ARRANQUE=1
OLLAMA=0
while [ $# -gt 0 ]; do
    case "$1" in
        --destino) DESTINO="$2"; shift 2 ;;
        --sin-arranque) ARRANQUE=0; shift ;;
        --con-ollama) OLLAMA=1; shift ;;
        -h|--help) sed -n 2,10p "$0"; exit 0 ;;
        *) echo "No conozco la opción $1"; exit 1 ;;
    esac
done

paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] && { echo "Ejecútalo con tu usuario normal, sin sudo (lo pedirá cuando haga falta)."; exit 1; }
command -v apt-get >/dev/null || { echo "Este instalador es para Ubuntu y derivadas (apt)."; exit 1; }
[ -f "$ORIGEN/core-orchestrator/jarvis.py" ] || { echo "Ejecútalo desde la carpeta del proyecto."; exit 1; }

# ------------------------------------------------------------------ 1. programas del sistema
paso "Programas del sistema (pedirá tu contraseña)"
PAQUETES="python3 python3-venv python3-pip python3-dev build-essential ffmpeg openssl curl git pciutils
          x11-xserver-utils wmctrl xdotool scrot xclip pulseaudio-utils pipewire-pulse libportaudio2
          poppler-utils libreoffice-writer libreoffice-calc libreoffice-impress fonts-dejavu"
FALTAN=""
for p in $PAQUETES; do dpkg -s "$p" >/dev/null 2>&1 || FALTAN="$FALTAN $p"; done
if [ -n "$FALTAN" ]; then
    sudo apt-get update -qq
    # pipewire-pulse y pulseaudio-utils pueden chocar en algunas versiones: se instalan aparte y sin romper nada
    sudo apt-get install -y $(echo "$FALTAN" | tr ' ' '\n' | grep -vE '^(pipewire-pulse|pulseaudio-utils)$' | tr '\n' ' ')
    sudo apt-get install -y pulseaudio-utils 2>/dev/null || aviso "pulseaudio-utils no se pudo instalar (se usará pw-record)"
else
    echo "  ya estaban todos"
fi
command -v firefox >/dev/null || command -v chromium >/dev/null || { aviso "No hay navegador: instalando Firefox"; sudo snap install firefox || true; }

# ------------------------------------------------------------------ 2. el programa
paso "Copiando el programa a $DESTINO"
mkdir -p "$DESTINO/logs" "$DESTINO/voces"
if [ -d "$DESTINO/core-orchestrator" ] && [ "$ORIGEN" != "$DESTINO" ]; then
    COPIA="$DESTINO/copias_codigo/antes_instalar_$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$COPIA"
    cp -a "$DESTINO/core-orchestrator" "$COPIA/" 2>/dev/null || true
    echo "  programa anterior guardado en $COPIA"
fi
if [ "$ORIGEN" != "$DESTINO" ]; then
    mkdir -p "$DESTINO/core-orchestrator"
    cp -a "$ORIGEN/core-orchestrator/." "$DESTINO/core-orchestrator/"
    find "$DESTINO/core-orchestrator" -name __pycache__ -prune -exec rm -rf {} +
    for s in "$ORIGEN"/scripts/*.sh "$ORIGEN"/scripts/jarvis-mantenimiento; do
        [ -f "$s" ] && install -m 755 "$s" "$DESTINO/$(basename "$s")"
    done
    cp -a "$ORIGEN/requirements.txt" "$DESTINO/" 2>/dev/null || true
fi

# ------------------------------------------------------------------ 3. Python
paso "Entorno de Python (la primera vez tarda unos minutos)"
[ -x "$DESTINO/venv/bin/python" ] || python3 -m venv "$DESTINO/venv"
PIP="$DESTINO/venv/bin/pip"
"$PIP" install -q --upgrade pip
if ! "$PIP" install -q -r "$ORIGEN/requirements.txt"; then
    aviso "Las versiones exactas no encajan con este Python: instalo las mismas librerías en su última versión"
    sed -E 's/[=<>~!].*$//' "$ORIGEN/requirements.txt" | grep -v '^\s*$' > /tmp/jarvis_requisitos_sin_version.txt
    "$PIP" install -q -r /tmp/jarvis_requisitos_sin_version.txt
fi

# ------------------------------------------------------------------ 4. una voz para empezar
paso "Voz para empezar"
if ! find "$DESTINO" -name '*.onnx' -not -path '*/venv/*' | grep -q .; then
    V=es_ES-sharvard-medium
    B="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/$V.onnx"
    mkdir -p "$DESTINO/voces/$V"
    curl -fL --retry 3 -o "$DESTINO/voces/$V/$V.onnx.json" "$B.json"
    curl -fL --retry 3 -o "$DESTINO/voces/$V/$V.onnx" "$B"
    echo "  voz $V descargada (en la configuración se pueden bajar más)"
else
    echo "  ya había voz"
fi

# ------------------------------------------------------------------ 5. IA local de reserva (opcional)
if [ "$OLLAMA" = 1 ]; then
    paso "IA local de reserva (Ollama)"
    if ! command -v ollama >/dev/null; then
        echo "  Se descarga e instala el instalador oficial de https://ollama.com"
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    MODELO=$(cd "$DESTINO/core-orchestrator" && "$DESTINO/venv/bin/python" -c "import equipo; print(equipo.recomendar()['ia_local'] or '')")
    [ -n "$MODELO" ] && ollama pull "$MODELO" || true
fi

# ------------------------------------------------------------------ 6. inicio automático
if [ "$ARRANQUE" = 1 ]; then
    paso "Inicio automático al entrar en el escritorio"
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/jarvis.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Asistente
Comment=Asistente de voz
Exec=env JARVIS_INSTALACION=$DESTINO bash $DESTINO/arrancar_jarvis.sh
X-GNOME-Autostart-enabled=true
EOF
    echo "  listo (se puede quitar en Configuración → Sesión e inicio)"
fi
grep -q "alias jarvis=" "$HOME/.bashrc" 2>/dev/null || echo "alias jarvis='bash $DESTINO/arrancar_jarvis.sh'" >> "$HOME/.bashrc"

# ------------------------------------------------------------------ 7. configuración
paso "Abriendo el asistente de configuración"
echo "  Si no se abre solo, entra en http://127.0.0.1:8765/asistente"
pkill -xf "python core-orchestrator/jarvis.py" 2>/dev/null || true    # el asistente usa el mismo puerto
cd "$DESTINO/core-orchestrator"
JARVIS_INSTALACION="$DESTINO" exec "$DESTINO/venv/bin/python" asistente.py
