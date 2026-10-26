#!/bin/bash
# Copias de seguridad del asistente con restic (cifradas e incrementales), sin sudo:
#   - restic (última versión de GitHub, comprobada con su SHA-256) en ~/.local/bin;
#   - una clave aleatoria en ~/.config/athena-copias/clave (solo su usuario puede leerla; sin ella no se abren);
#   - copia automática cada domingo a las 3:30 (temporizador «athena-copia»).
#   bash ~/jarvis/instalar_copias.sh
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
mkdir -p "$HOME/.local/bin" "$HOME/.config/athena-copias"

paso "restic"
if ! command -v restic >/dev/null && [ ! -x "$HOME/.local/bin/restic" ]; then
    T=$(mktemp -d)
    V=$(curl -fsSL https://api.github.com/repos/restic/restic/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
    A="restic_${V}_linux_amd64.bz2"
    curl -fsSL -o "$T/$A" "https://github.com/restic/restic/releases/download/v$V/$A"
    curl -fsSL -o "$T/SHA256SUMS" "https://github.com/restic/restic/releases/download/v$V/SHA256SUMS"
    (cd "$T" && grep " $A\$" SHA256SUMS | sha256sum -c -)
    bunzip2 -c "$T/$A" > "$HOME/.local/bin/restic" && chmod 755 "$HOME/.local/bin/restic"
    rm -rf "$T"
fi
R=$(command -v restic || echo "$HOME/.local/bin/restic")
"$R" version | head -1

paso "Clave de las copias"
umask 077
[ -s "$HOME/.config/athena-copias/clave" ] || openssl rand -base64 33 > "$HOME/.config/athena-copias/clave"
umask 022
echo "  En ~/.config/athena-copias/clave. Guárdala también en otro sitio (sin ella no se pueden abrir las copias)."

paso "Copia semanal (domingos 3:30)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/athena-copia.service" <<EOF
[Unit]
Description=Copia de seguridad semanal del asistente (restic)

[Service]
Type=oneshot
WorkingDirectory=$J/core-orchestrator
ExecStart=$J/venv/bin/python -c "import copias; r = copias.copia(); print('archivos nuevos:', r.get('files_new'))"
Nice=15
IOSchedulingClass=idle
EOF
cat > "$HOME/.config/systemd/user/athena-copia.timer" <<'EOF'
[Unit]
Description=Copia de seguridad semanal del asistente

[Timer]
OnCalendar=Sun *-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now athena-copia.timer
paso "Primera copia"
systemctl --user start athena-copia.service && journalctl --user -u athena-copia -n 3 --no-pager -o cat | tail -1
echo "✔ Listo. Dile al asistente «haz una copia de seguridad» o «cuándo fue la última copia»."
