#!/bin/bash
# Escritorio Xfce en el portátil (para trabajar) + Jarvis a pantalla completa en el monitor externo.
set -e
echo "== 1/4 Instalando un escritorio Xfce ligero (tarda unos minutos)"
sudo apt install -y xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-settings thunar \
                    xfce4-terminal mousepad wmctrl dbus-x11

echo "== 2/4 Nuevo lanzador de Jarvis (coloca la interfaz en el monitor externo)"
chmod +x "$HOME/jarvis/arrancar_jarvis.sh"

echo "== 3/4 Al encender: escritorio Xfce, y Jarvis arranca con él"
printf '#!/bin/sh\nexec startxfce4\n' > "$HOME/.xinitrc"
chmod +x "$HOME/.xinitrc"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/jarvis.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=Jarvis
Comment=Asistente de voz local
Exec=$HOME/jarvis/arrancar_jarvis.sh
X-GNOME-Autostart-enabled=true
EOD

echo "== 4/4 Relanzando la sesión para probar (el portátil se reiniciará en pantalla)"
pkill -f core-orchestrator/jarvis.py || true
sudo systemctl restart getty@tty1
echo "   Mira las pantallas: escritorio en el portátil y Jarvis en el monitor en 30-60 s."
