#!/bin/bash
# Linutil (https://github.com/ChrisTitusTech/linutil, MIT): la caja de herramientas de Chris Titus para Linux
# (la hermana de winutil, que es solo para Windows): instalar programas, ajustes y arreglos desde un menú.
#   bash ~/jarvis/instalar_linutil.sh       (sin sudo). Después: «abre la caja de herramientas de linux».
set -euo pipefail
mkdir -p "$HOME/.local/bin"
T=$(mktemp)
curl -fsSL -o "$T" https://github.com/ChrisTitusTech/linutil/releases/latest/download/linutil
head -c 4 "$T" | grep -q "ELF" || { echo "La descarga no es un programa válido."; rm -f "$T"; exit 1; }
install -m 755 "$T" "$HOME/.local/bin/linutil"
rm -f "$T"
echo "✔ Linutil instalado en ~/.local/bin/linutil ($("$HOME/.local/bin/linutil" --version 2>/dev/null || echo 'versión actual'))"
