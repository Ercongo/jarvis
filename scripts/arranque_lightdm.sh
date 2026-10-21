#!/bin/bash
# Al instalar Xfce se instaló también la pantalla de inicio LightDM: es la que ahora pide la clave.
# Este script hace que LightDM entre solo en Xfce y que Jarvis arranque dentro de esa sesión.
set -e
U="$USER"
echo "== Gestor de inicio activo:"
cat /etc/X11/default-display-manager 2>/dev/null || true
systemctl is-enabled lightdm 2>/dev/null || true

if ! command -v lightdm >/dev/null; then
    echo "LightDM no está instalado: este script no aplica. Pega esta salida a Claude."
    exit 1
fi

echo "== 1/4 LightDM entra solo en tu sesión Xfce"
SESION=$(ls /usr/share/xsessions/ | grep -i xfce | head -1 | sed 's/\.desktop$//')
SESION=${SESION:-xfce}
sudo groupadd -f -r autologin
sudo gpasswd -a "$U" autologin >/dev/null
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf >/dev/null <<EOF
[Seat:*]
autologin-user=$U
autologin-user-timeout=0
autologin-session=$SESION
user-session=$SESION
EOF
cat /etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf

echo "== 2/4 Quitando el arranque por consola (ya no hace falta y chocaba con LightDM)"
sudo rm -f /etc/systemd/system/getty@tty1.service.d/autologin.conf
sudo systemctl daemon-reload
for P in "$HOME/.profile" "$HOME/.bash_profile"; do
    [ -f "$P" ] && sed -i '/# jarvis-autostart/d' "$P"
done

echo "== 3/4 Jarvis arranca 10 s después de entrar en Xfce"
mkdir -p "$HOME/.config/autostart" "$HOME/jarvis/logs"
cat > "$HOME/.config/autostart/jarvis.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Jarvis
Comment=Asistente de voz local
Exec=sh -c "sleep 10; $HOME/jarvis/arrancar_jarvis.sh >> $HOME/jarvis/logs/arranque.log 2>&1"
X-GNOME-Autostart-enabled=true
EOF
chmod +x "$HOME/jarvis/arrancar_jarvis.sh"

echo "== 4/4 Listo. Reiniciando en 5 s…"
sleep 5
sudo reboot
