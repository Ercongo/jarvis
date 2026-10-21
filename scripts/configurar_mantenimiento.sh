#!/bin/bash
# Se ejecuta UNA vez:  sudo bash ~/jarvis/configurar_mantenimiento.sh
# Permite a Jarvis limpiar el sistema e instalar actualizaciones sin pedirte la contraseña,
# pero solo a través del script fijo /usr/local/sbin/jarvis-mantenimiento (nada más).
set -e
if [ "$(id -u)" != 0 ]; then
  echo "Ejecútalo así:  sudo bash ~/jarvis/configurar_mantenimiento.sh"
  exit 1
fi
USUARIO="${SUDO_USER:-$(logname 2>/dev/null || id -un)}"
DIR="$(cd "$(dirname "$0")" && pwd)"
install -o root -g root -m 755 "$DIR/jarvis-mantenimiento" /usr/local/sbin/jarvis-mantenimiento
echo "$USUARIO ALL=(root) NOPASSWD: /usr/local/sbin/jarvis-mantenimiento" > /etc/sudoers.d/jarvis-mantenimiento
chmod 440 /etc/sudoers.d/jarvis-mantenimiento
if ! visudo -cf /etc/sudoers.d/jarvis-mantenimiento >/dev/null; then
  rm -f /etc/sudoers.d/jarvis-mantenimiento
  echo "Error en la regla de sudo; no se ha instalado nada."
  exit 1
fi
command -v snap >/dev/null && snap set system refresh.retain=2 || true

# Encendido remoto (Wake-on-LAN) por el cable de red
echo 'ACTION=="add", SUBSYSTEM=="net", KERNEL=="en*", RUN+="/usr/sbin/ethtool -s $name wol g"' \
  > /etc/udev/rules.d/81-wake-on-lan.rules
for n in $(ls /sys/class/net | grep -E '^(en|eth)'); do
  ethtool -s "$n" wol g || true
  echo enabled > "/sys/class/net/$n/device/power/wakeup" 2>/dev/null || true
  echo "Wake-on-LAN en $n (MAC $(cat /sys/class/net/$n/address)): $(ethtool "$n" | grep -E '^\s*Wake-on:' | xargs)"
done
nmcli -t -f NAME,TYPE connection show 2>/dev/null | awk -F: '$2=="802-3-ethernet"{print $1}' | while read -r c; do
  nmcli connection modify "$c" 802-3-ethernet.wake-on-lan magic || true
done
echo "Listo: Jarvis ya puede limpiar el sistema, instalar actualizaciones, reiniciar a distancia y encenderse por la red."
