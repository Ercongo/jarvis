#!/bin/bash
# Arranque automático de Jarvis SIN gestor de inicio gráfico:
#   encender -> entra solo en tty1 (sin contraseña) -> abre la parte gráfica -> Jarvis saluda.
# Ejecútalo una vez:  bash ~/jarvis/activar_arranque.sh

set -e
U="$USER"
J="$HOME/jarvis"
echo "== Activando el arranque automático de Jarvis para el usuario $U"

echo "== 1/4 Paquetes para el modo gráfico mínimo (te pedirá la contraseña)"
sudo apt install -y xinit xserver-xorg x11-xserver-utils

echo "== 2/4 Entrar solo en la consola 1, sin contraseña"
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $U --noclear %I \$TERM
EOF
sudo systemctl daemon-reload

echo "== 3/4 Qué se abre al arrancar la parte gráfica"
if command -v startxfce4 >/dev/null; then
    echo "   Xfce encontrado: se abrirá el escritorio y Jarvis arrancará con él."
    printf '#!/bin/sh\nexec startxfce4\n' > "$HOME/.xinitrc"
else
    echo "   Sin Xfce: modo pantalla dedicada (solo Jarvis, gasta menos memoria)."
    printf '#!/bin/sh\nxset s off -dpms\n%s/arrancar_jarvis.sh\nwhile true; do sleep 3600; done\n' "$J" > "$HOME/.xinitrc"
fi
chmod +x "$HOME/.xinitrc"

echo "== 4/4 Lanzar la parte gráfica al entrar en la consola 1 (no por SSH)"
PERFIL="$HOME/.profile"
[ -f "$HOME/.bash_profile" ] && PERFIL="$HOME/.bash_profile"
sed -i '/# jarvis-autostart/d' "$PERFIL"
echo '[ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && startx  # jarvis-autostart (sin exec: si falla, te quedas en la consola)' >> "$PERFIL"

echo
echo "== Listo. Reinicia con:  sudo reboot"
echo "   Para volver a pedir contraseña: sudo rm /etc/systemd/system/getty@tty1.service.d/autologin.conf"
