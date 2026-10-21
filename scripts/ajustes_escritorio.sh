#!/bin/bash
# 1) Inicio sin pedir usuario  2) Icono de red (wifi/cable)  3) Memorias USB que se abren solas
U="$USER"

echo "== Diagnóstico de LightDM (configuración efectiva)"
sudo lightdm --show-config 2>&1 | grep -iE 'autologin|user-session|greeter-session|hide-users' || true
echo "-- sesiones disponibles:"; ls /usr/share/xsessions/

echo "== 1/3 Inicio automático (anulando cualquier ajuste que lo desactive)"
SESION=$(ls /usr/share/xsessions/ 2>/dev/null | grep -i xfce | head -1 | sed 's/\.desktop$//')
SESION=${SESION:-xfce}
[ -f /etc/lightdm/lightdm.conf ] && sudo sed -i 's/^\s*autologin-user\s*=\s*$/#&/; s/^\s*autologin-user-timeout\s*=.*/#&/' /etc/lightdm/lightdm.conf
sudo rm -f /etc/lightdm/lightdm.conf.d/50-jarvis-autologin.conf
sudo tee /etc/lightdm/lightdm.conf.d/99-jarvis-autologin.conf >/dev/null <<EOF
[Seat:*]
autologin-guest=false
autologin-user=$U
autologin-user-timeout=0
autologin-session=$SESION
user-session=$SESION
EOF
for g in autologin nopasswdlogin; do sudo groupadd -f -r $g; sudo gpasswd -a "$U" $g >/dev/null; done
echo "-- configuración final:"
sudo lightdm --show-config 2>&1 | grep -iE 'autologin|user-session' || true

echo "== 2/3 Red: icono de wifi/cable en la barra"
sudo apt install -y network-manager network-manager-gnome
sudo systemctl enable NetworkManager   # se activa al reiniciar (así no se corta esta conexión SSH)
echo "-- conexiones de red actuales:"; ip -brief address

echo "== 3/3 USB: memorias y discos se montan y abren solos"
sudo apt install -y gvfs gvfs-backends udisks2 thunar-volman xfce4-notifyd
export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" DISPLAY=:0   # para cambiar ajustes de tu sesión desde SSH
xfconf-query -c thunar-volman -p /automount-drives/enabled -n -t bool -s true 2>/dev/null || true
xfconf-query -c thunar-volman -p /automount-media/enabled  -n -t bool -s true 2>/dev/null || true
xfconf-query -c thunar-volman -p /autobrowse/enabled       -n -t bool -s true 2>/dev/null || true
echo "-- dispositivos USB conectados ahora mismo:"
lsusb

echo
echo "== Listo. Reinicia para probar el inicio automático:  sudo reboot"
