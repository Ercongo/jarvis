#!/bin/bash
# Se ejecuta DENTRO del disco que se está construyendo (chroot), lo lanza construir_disco.sh.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

# instala una lista; si alguno no existe en esta versión de Ubuntu, sigue con los demás y lo apunta
instalar() {
    apt-get install -y --no-install-recommends "$@" && return 0
    for p in "$@"; do
        apt-get install -y --no-install-recommends "$p" || echo "$p" >> /var/log/paquetes_omitidos.txt
    done
}

# idioma, teclado y hora de España (luego se puede cambiar en Configuración)
apt-get update
apt-get install -y locales tzdata keyboard-configuration console-setup
sed -i 's/^# *es_ES.UTF-8/es_ES.UTF-8/; s/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
locale-gen
update-locale LANG=es_ES.UTF-8
ln -sf /usr/share/zoneinfo/Europe/Madrid /etc/localtime; echo Europe/Madrid > /etc/timezone
cat > /etc/default/keyboard <<'EOF'
XKBMODEL="pc105"
XKBLAYOUT="es"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
EOF

# núcleo genérico + todo el firmware: arranca en casi cualquier PC
apt-get install -y --no-install-recommends linux-generic linux-firmware intel-microcode amd64-microcode \
    initramfs-tools grub-efi-amd64-signed shim-signed grub-pc-bin grub2-common efibootmgr
# el initramfs con todos los módulos (por defecto ya es MODULES=most): sirve para cualquier controladora de disco
grep -q '^MODULES=most' /etc/initramfs-tools/initramfs.conf || sed -i 's/^MODULES=.*/MODULES=most/' /etc/initramfs-tools/initramfs.conf

# escritorio ligero, red, sonido y lo que usa el asistente
instalar \
    xorg xserver-xorg-video-all xserver-xorg-input-all mesa-utils \
    xfce4 xfce4-terminal xfce4-whiskermenu-plugin xfce4-pulseaudio-plugin xfce4-notifyd xfce4-screenshooter \
    thunar mousepad ristretto lightdm lightdm-gtk-greeter dbus-x11 xdg-user-dirs xdg-utils \
    network-manager network-manager-gnome modemmanager wpasupplicant iw wireless-regdb \
    pipewire pipewire-pulse wireplumber pulseaudio-utils alsa-utils libspa-0.2-bluetooth bluez \
    fonts-dejavu fonts-noto-color-emoji language-pack-es language-pack-gnome-es \
    whiptail curl ca-certificates gnupg openssl git pciutils usbutils \
    python3 python3-venv python3-pip python3-dev build-essential ffmpeg libportaudio2 \
    x11-xserver-utils wmctrl xdotool scrot xclip poppler-utils \
    libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-l10n-es \
    gvfs gvfs-backends udisks2 polkitd pkexec ntfs-3g exfatprogs kdeconnect \
    xubuntu-wallpapers libnotify-bin at-spi2-core

# fondo de escritorio: Xfce busca xubuntu-wallpaper.png; si no viene, el primero que haya
if [ ! -e /usr/share/xfce4/backdrops/xubuntu-wallpaper.png ]; then
    mkdir -p /usr/share/xfce4/backdrops
    F=$(ls /usr/share/xfce4/backdrops/*.png /usr/share/xfce4/backdrops/*.jpg /usr/share/backgrounds/*.png \
          /usr/share/backgrounds/*.jpg 2>/dev/null | head -1 || true)
    [ -n "$F" ] && ln -sf "$F" /usr/share/xfce4/backdrops/xubuntu-wallpaper.png
fi

# la red la lleva NetworkManager (wifi y cable en cualquier PC)
mkdir -p /etc/netplan
printf 'network:\n  version: 2\n  renderer: NetworkManager\n' > /etc/netplan/01-network-manager.yaml
chmod 600 /etc/netplan/01-network-manager.yaml

# Firefox de Mozilla (el de Ubuntu es un snap, y los snaps no se instalan bien al construir un disco)
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg -o /etc/apt/keyrings/packages.mozilla.org.asc
echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
    > /etc/apt/sources.list.d/mozilla.list
printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' > /etc/apt/preferences.d/mozilla
apt-get update
apt-get install -y firefox firefox-l10n-es-es
# sin bienvenida, condiciones ni «navegador predeterminado» encima de la interfaz del asistente
mkdir -p /etc/firefox/policies
cat > /etc/firefox/policies/policies.json <<'EOF'
{"policies": {
  "SkipTermsOfUse": true,
  "DontCheckDefaultBrowser": true,
  "DisableTelemetry": true,
  "DisableFirefoxStudies": true,
  "OverrideFirstRunPage": "",
  "OverridePostUpdatePage": "",
  "UserMessaging": {"WhatsNew": false, "ExtensionRecommendations": false, "FeatureRecommendations": false,
                    "SkipOnboarding": true, "MoreFromMozilla": false, "Locked": false}
}}
EOF

# primer arranque: antes de la pantalla de entrada, pedir nombre, usuario y contraseña
cat > /etc/systemd/system/asistente-primer-arranque.service <<'EOF'
[Unit]
Description=Primer arranque del asistente (crear tu usuario)
ConditionPathExists=/etc/jarvis/primer-arranque
After=systemd-user-sessions.service plymouth-quit-wait.service
Before=display-manager.service getty@tty1.service
Conflicts=getty@tty1.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/asistente-primer-arranque
StandardInput=tty
StandardOutput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
EOF
systemctl enable asistente-primer-arranque.service
systemctl enable NetworkManager lightdm || true
systemctl set-default graphical.target

# arranque con el logo y sin esperar a la red
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/' /etc/default/grub
sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=3/' /etc/default/grub
grep -q '^GRUB_DISABLE_OS_PROBER' /etc/default/grub || echo 'GRUB_DISABLE_OS_PROBER=true' >> /etc/default/grub
systemctl mask systemd-networkd-wait-online.service NetworkManager-wait-online.service || true

update-initramfs -c -k all || update-initramfs -u -k all
apt-get -y autoremove
