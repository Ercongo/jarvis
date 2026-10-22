#!/bin/bash
# Construye un disco arrancable con Ubuntu + el asistente, que funciona en (casi) cualquier PC de 64 bits,
# con UEFI (también Secure Boot) o BIOS antigua. Se ejecuta en un Ubuntu (el portátil original), con el disco
# externo conectado por USB. BORRA EL DISCO ENTERO.
#
#   sudo bash portable/construir_disco.sh /dev/sdX          → construye en el disco (pide confirmación)
#   sudo bash portable/construir_disco.sh --imagen disco.img [--tamano 24G]   → en un archivo (para probar)
#   ... --reanudar                                          → si se cortó, sigue donde se quedó (no borra nada)
#
# Al arrancar el disco por primera vez sale una pantalla que pide el nombre, el usuario y la contraseña de
# la persona; luego entra en el escritorio y abre la configuración del asistente.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO=""; IMAGEN=""; TAMANO="24G"; REANUDAR=0
while [ $# -gt 0 ]; do
    case "$1" in
        --imagen) IMAGEN="$2"; shift 2 ;;
        --tamano) TAMANO="$2"; shift 2 ;;
        --reanudar) REANUDAR=1; shift ;;
        -h|--help) sed -n 2,10p "$0"; exit 0 ;;
        /dev/*) DESTINO="$1"; shift ;;
        *) echo "No entiendo «$1»"; exit 1 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo "Hace falta ejecutarlo con sudo."; exit 1; }
[ -f "$REPO/core-orchestrator/jarvis.py" ] || { echo "No encuentro el programa en $REPO"; exit 1; }

. /etc/os-release
VERSION="${JARVIS_UBUNTU:-$VERSION_CODENAME}"
ESPEJO="${JARVIS_ESPEJO:-http://es.archive.ubuntu.com/ubuntu}"
MONTAJE=/mnt/disco-asistente
LOG=/var/log/construir_disco_asistente.log
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*" | tee -a "$LOG"; }

# ------------------------------------------------------------------ 0. qué disco (con todas las comprobaciones)
if [ -n "$IMAGEN" ]; then
    [ "$REANUDAR" = 1 ] || truncate -s "$TAMANO" "$IMAGEN"
    DESTINO=$(losetup --find --show --partscan "$IMAGEN")
    echo "Imagen $IMAGEN en $DESTINO"
else
    [ -b "$DESTINO" ] || { echo "Indica el disco: sudo bash $0 /dev/sdX   (míralo con: lsblk -d -o NAME,SIZE,TRAN,MODEL)"; exit 1; }
    TRAN=$(lsblk -dno TRAN "$DESTINO" | tr -d ' ')
    [ "$TRAN" = "usb" ] || { echo "$DESTINO no es un disco USB ($TRAN). Por seguridad solo se construye en discos USB."; exit 1; }
    RAIZ=$(findmnt -no SOURCE / | sed -E 's/p?[0-9]+$//')
    case "$RAIZ" in "$DESTINO"*) echo "$DESTINO es el disco del sistema en marcha. No."; exit 1 ;; esac
    lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DESTINO"
    echo
    echo "Disco: $(lsblk -dno MODEL,SIZE "$DESTINO")"
    if [ "$REANUDAR" = 1 ]; then
        echo "Se reanuda la construcción en este disco (no se borra). ¿Seguro? Escribe SEGUIR:"
        read -r R
        [ "$R" = "SEGUIR" ] || { echo "Cancelado."; exit 1; }
    else
        echo "SE BORRARÁ ENTERO. Para seguir escribe BORRAR (en mayúsculas):"
        read -r R
        [ "$R" = "BORRAR" ] || { echo "Cancelado. No se ha tocado nada."; exit 1; }
    fi
    # desmontar lo que el escritorio haya montado (los nombres pueden llevar espacios: «Disco externo»)
    lsblk -nlo MOUNTPOINT "$DESTINO" | grep -v '^$' | sort -r | while IFS= read -r m; do umount "$m" || umount -l "$m"; done
    if lsblk -nlo MOUNTPOINT "$DESTINO" | grep -q .; then echo "No he podido desmontar $DESTINO. Ciérralo en el explorador y repite."; exit 1; fi
fi
[ "$REANUDAR" = 1 ] || : > "$LOG"
parte() { if [ -e "${DESTINO}p$1" ]; then echo "${DESTINO}p$1"; else echo "${DESTINO}$1"; fi; }

limpiar() {
    local codigo=$?
    set +e
    if [ "$codigo" != 0 ]; then
        printf '\n\033[1;31m✖ Ha fallado (código %s). Las últimas líneas del registro:\033[0m\n' "$codigo" | tee -a "$LOG"
        tail -n 12 "$LOG" | cut -c1-200
        echo "Arreglado el problema, sigue con: sudo bash $0 --reanudar $DESTINO"
    fi
    for d in dev/pts dev proc sys run boot/efi ""; do umount -l "$MONTAJE/$d" 2>/dev/null; done
    [ -n "$IMAGEN" ] && losetup -d "$DESTINO" 2>/dev/null
}
trap limpiar EXIT

# ------------------------------------------------------------------ 1. herramientas en este equipo
paso "Herramientas para construirlo"
apt-get install -y -qq debootstrap gdisk dosfstools e2fsprogs >>"$LOG" 2>&1
[ -e "/usr/share/debootstrap/scripts/$VERSION" ] || ln -s gutsy "/usr/share/debootstrap/scripts/$VERSION"

hecho() { [ -f "$MONTAJE/var/lib/asistente-construccion/$1" ]; }
marcar() { mkdir -p "$MONTAJE/var/lib/asistente-construccion"; touch "$MONTAJE/var/lib/asistente-construccion/$1"; }

if [ "$REANUDAR" = 1 ]; then
    paso "Reanudando en $DESTINO"
    partprobe "$DESTINO" 2>/dev/null || true; sleep 2
    P_EFI=$(parte 2); P_RAIZ=$(parte 3)
    mkdir -p "$MONTAJE"; mount "$P_RAIZ" "$MONTAJE"
    if [ "${JARVIS_PRUEBA_SIN_VFAT:-0}" != 1 ]; then mount "$P_EFI" "$MONTAJE/boot/efi"; fi
    hecho base || { echo "No llegó a instalarse Ubuntu base: empieza de cero (sin --reanudar)."; exit 1; }
    for d in dev dev/pts proc sys run; do mount --bind "/$d" "$MONTAJE/$d"; done
    rm -f "$MONTAJE/etc/resolv.conf"
    grep -E '^nameserver' /etc/resolv.conf | grep -v '127.0.0.53' > "$MONTAJE/etc/resolv.conf" 2>/dev/null || true
    [ -s "$MONTAJE/etc/resolv.conf" ] || printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$MONTAJE/etc/resolv.conf"
else
# ------------------------------------------------------------------ 2. particiones: BIOS + EFI + sistema
paso "Particiones en $DESTINO"
wipefs -a "$DESTINO" >>"$LOG" 2>&1 || true
# borrar restos de tablas viejas (al principio y al final del disco); sgdisk da código de error si la tabla
# vieja estaba dañada («CRC doesn't check out») aunque la borre bien: por eso se comprueba aparte
SECTORES=$(blockdev --getsz "$DESTINO")
dd if=/dev/zero of="$DESTINO" bs=1M count=4 conv=fsync status=none
dd if=/dev/zero of="$DESTINO" bs=512 seek=$((SECTORES - 8192)) count=8192 conv=fsync status=none
sgdisk --zap-all "$DESTINO" >>"$LOG" 2>&1 || true
partprobe "$DESTINO" 2>/dev/null || true
sgdisk -n1:1M:+1M -t1:EF02 -c1:"BIOS" \
       -n2:0:+512M -t2:EF00 -c2:"EFI" \
       -n3:0:0 -t3:8300 -c3:"ASISTENTE" "$DESTINO" >>"$LOG" 2>&1 \
    || { echo "No he podido crear las particiones (mira $LOG)."; exit 1; }
partprobe "$DESTINO" 2>/dev/null || true; udevadm settle 2>/dev/null || true; sleep 2
P_EFI=$(parte 2); P_RAIZ=$(parte 3)
mkfs.vfat -F32 -n EFI "$P_EFI" >>"$LOG"
mkfs.ext4 -F -q -L ASISTENTE "$P_RAIZ"
mkdir -p "$MONTAJE"
mount "$P_RAIZ" "$MONTAJE"
mkdir -p "$MONTAJE/boot/efi"
if [ "${JARVIS_PRUEBA_SIN_VFAT:-0}" = 1 ]; then
    echo "  (prueba: la partición EFI no se monta; sus archivos quedan en /boot/efi)"
else
    mount "$P_EFI" "$MONTAJE/boot/efi"
fi

# ------------------------------------------------------------------ 3. Ubuntu base
paso "Ubuntu $VERSION base (descarga ~300 MB)"
debootstrap --arch=amd64 --components=main,restricted,universe,multiverse "$VERSION" "$MONTAJE" "$ESPEJO" >>"$LOG" 2>&1
for d in dev dev/pts proc sys run; do mount --bind "/$d" "$MONTAJE/$d"; done
# resolv.conf es un enlace al resolvedor de systemd, que no funciona mientras se construye: uno de verdad ahora
# y el enlace de vuelta al final
rm -f "$MONTAJE/etc/resolv.conf"
grep -E '^nameserver' /etc/resolv.conf | grep -v '127.0.0.53' > "$MONTAJE/etc/resolv.conf" 2>/dev/null || true
[ -s "$MONTAJE/etc/resolv.conf" ] || printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$MONTAJE/etc/resolv.conf"

cat > "$MONTAJE/etc/apt/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: $ESPEJO
Suites: $VERSION $VERSION-updates $VERSION-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: $VERSION-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
rm -f "$MONTAJE/etc/apt/sources.list"

UUID_RAIZ=$(blkid -s UUID -o value "$P_RAIZ"); UUID_EFI=$(blkid -s UUID -o value "$P_EFI")
cat > "$MONTAJE/etc/fstab" <<EOF
UUID=$UUID_RAIZ  /          ext4  noatime,errors=remount-ro  0 1
UUID=$UUID_EFI   /boot/efi  vfat  umask=0077                 0 1
EOF
echo asistente > "$MONTAJE/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 asistente\n' > "$MONTAJE/etc/hosts"
marcar base
fi

# Solo para probar en un entorno con proxy (no hace falta en un PC normal): pasar el proxy y su certificado
ENTORNO_RED=()
for v in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY; do
    [ -n "${!v:-}" ] && ENTORNO_RED+=("$v=${!v}")
done
if [ -n "${JARVIS_PRUEBA_CA:-}" ] && [ -f "$JARVIS_PRUEBA_CA" ]; then
    mkdir -p "$MONTAJE/usr/local/share/ca-certificates"
    cp "$JARVIS_PRUEBA_CA" "$MONTAJE/usr/local/share/ca-certificates/prueba-proxy.crt"
    chroot "$MONTAJE" update-ca-certificates >>"$LOG" 2>&1 || true
    ENTORNO_RED+=("SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt"
                  "PIP_CERT=/etc/ssl/certs/ca-certificates.crt" "CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt")
    printf 'Acquire::https::CaInfo "/etc/ssl/certs/ca-certificates.crt";\n' > "$MONTAJE/etc/apt/apt.conf.d/99prueba-ca"
fi

# ------------------------------------------------------------------ 4. núcleo, escritorio y programas
if hecho programas; then echo "  (núcleo, escritorio y programas: ya estaban)"; else
paso "Núcleo, controladores, escritorio y programas (la parte larga: ~2 GB)"
cp "$REPO/portable/dentro_del_disco.sh" "$MONTAJE/tmp/"
chroot "$MONTAJE" /usr/bin/env -i HOME=/root TERM=xterm PATH=/usr/sbin:/usr/bin:/sbin:/bin "${ENTORNO_RED[@]}" \
    DESTINO="$( [ -n "$IMAGEN" ] && echo "" || echo "$DESTINO")" bash /tmp/dentro_del_disco.sh >>"$LOG" 2>&1 \
    || { echo "Ha fallado dentro del disco; mira $LOG (se puede reanudar con --reanudar)"; tail -30 "$LOG"; exit 1; }
marcar programas
fi

# ------------------------------------------------------------------ 5. el asistente (plantilla en /opt/jarvis)
paso "El asistente"
J="$MONTAJE/opt/jarvis"
mkdir -p "$J/logs" "$J/voces"
cp -a "$REPO/core-orchestrator" "$J/"
find "$J/core-orchestrator" -name __pycache__ -prune -exec rm -rf {} +
for s in "$REPO"/scripts/*.sh "$REPO"/scripts/jarvis-mantenimiento; do [ -f "$s" ] && install -m 755 "$s" "$J/"; done
cp "$REPO/requirements.txt" "$J/" 2>/dev/null || true
cp "$REPO/instalar.sh" "$J/" 2>/dev/null || true
install -m 755 "$REPO/portable/primer_arranque.sh" "$MONTAJE/usr/local/sbin/asistente-primer-arranque"
chroot "$MONTAJE" /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin "${ENTORNO_RED[@]}" bash -c '
    set -e
    python3 -m venv /opt/jarvis/venv
    /opt/jarvis/venv/bin/pip install -q --upgrade pip
    if ! /opt/jarvis/venv/bin/pip install -q -r /opt/jarvis/requirements.txt; then
        sed -E "s/[=<>~!].*$//" /opt/jarvis/requirements.txt | grep -v "^\s*$" > /tmp/req.txt
        /opt/jarvis/venv/bin/pip install -q -r /tmp/req.txt
    fi
    V=es_ES-sharvard-medium
    B=https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/$V.onnx
    mkdir -p /opt/jarvis/voces/$V
    curl -fsSL --retry 3 -o /opt/jarvis/voces/$V/$V.onnx.json $B.json
    curl -fsSL --retry 3 -o /opt/jarvis/voces/$V/$V.onnx $B
    # el reconocimiento de voz local ya descargado: funciona desde el primer arranque aunque no haya internet
    HF_HOME=/opt/jarvis/hf-cache /opt/jarvis/venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel(\"base\", device=\"cpu\", compute_type=\"int8\")"
'  >>"$LOG" 2>&1 || { echo "Ha fallado al preparar el asistente; mira $LOG (se puede reanudar con --reanudar)"; tail -30 "$LOG"; exit 1; }

# ------------------------------------------------------------------ 5b. extras: lo mismo que el portátil original
# Si algo de esto falla (sin internet, un servidor caído…) el disco sigue valiendo: se apunta y se sigue.
paso "Extras: otra voz, IA local de reserva y música con IA (lo más largo: varios GB)"
chroot "$MONTAJE" /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin "${ENTORNO_RED[@]}" bash -c '
    falta() { echo "$1" >> /var/log/paquetes_omitidos.txt; echo "  (omitido: $1)"; }
    # segunda voz en español (la anterior del primer asistente)
    V=es_ES-davefx-medium
    B=https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/$V.onnx
    mkdir -p /opt/jarvis/voces/$V
    { curl -fsSL --retry 3 -o /opt/jarvis/voces/$V/$V.onnx.json $B.json && \
      curl -fsSL --retry 3 -o /opt/jarvis/voces/$V/$V.onnx $B; } || { rm -rf /opt/jarvis/voces/$V; falta "voz davefx"; }
    # IA local de reserva: Ollama + qwen2.5:1.5b (contesta sin internet si el cerebro en la nube no puede)
    if curl -fsSL https://ollama.com/install.sh -o /tmp/ollama.sh && sh /tmp/ollama.sh; then
        export OLLAMA_MODELS=/usr/share/ollama/.ollama/models
        mkdir -p $OLLAMA_MODELS
        ollama serve >/tmp/ollama.log 2>&1 & P=$!
        sleep 8
        ollama pull qwen2.5:1.5b || falta "modelo qwen2.5:1.5b"
        kill $P 2>/dev/null; wait $P 2>/dev/null
        id ollama >/dev/null 2>&1 && chown -R ollama:ollama /usr/share/ollama
        systemctl enable ollama 2>/dev/null || true
    else
        falta "ollama"
    fi
    # música con IA (MusicGen) en su propio entorno, como en el portátil original
    if python3 -m venv /opt/jarvis/venv_musica && \
       /opt/jarvis/venv_musica/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu && \
       /opt/jarvis/venv_musica/bin/pip install -q transformers scipy numpy; then
        HF_HOME=/opt/jarvis/hf-cache /opt/jarvis/venv_musica/bin/python -c "from transformers import AutoProcessor, MusicgenForConditionalGeneration as M; AutoProcessor.from_pretrained(\"facebook/musicgen-small\"); M.from_pretrained(\"facebook/musicgen-small\")" \
            || falta "modelo musicgen-small"
    else
        rm -rf /opt/jarvis/venv_musica; falta "venv_musica (MusicGen)"
    fi
    true
' >>"$LOG" 2>&1 || true
grep -a "omitido" "$LOG" | tail -5 || true

# ------------------------------------------------------------------ 6. arranque en cualquier PC
paso "Arranque (UEFI con Secure Boot y BIOS antigua)"
# El menú de arranque tiene que buscar el sistema por su UUID (en otro PC el disco no se llamará igual que
# aquí). update-grub solo usa el UUID si existe /dev/disk/by-uuid/<uuid>: se asegura aunque no haya udev.
UUID_RAIZ=$(blkid -s UUID -o value "$P_RAIZ")
mkdir -p /dev/disk/by-uuid
[ -e "/dev/disk/by-uuid/$UUID_RAIZ" ] || ln -s "$P_RAIZ" "/dev/disk/by-uuid/$UUID_RAIZ"
EFI_INSTALAR="grub-install --target=x86_64-efi --efi-directory=/boot/efi --boot-directory=/boot --removable --uefi-secure-boot --no-nvram"
[ "${JARVIS_PRUEBA_SIN_VFAT:-0}" = 1 ] && EFI_INSTALAR="echo '(prueba: arranque UEFI sin instalar, la partición EFI no está montada)'"
chroot "$MONTAJE" /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin bash -c "
    set -e
    $EFI_INSTALAR
    grub-install --target=i386-pc --boot-directory=/boot $DESTINO
    update-grub
" >>"$LOG" 2>&1 || { echo "Ha fallado el cargador de arranque; mira $LOG"; tail -30 "$LOG"; exit 1; }
if grep -q "root=/dev/" "$MONTAJE/boot/grub/grub.cfg" || ! grep -q "root=UUID=$UUID_RAIZ" "$MONTAJE/boot/grub/grub.cfg"; then
    echo "El menú de arranque no usa el UUID del disco: no arrancaría en otro PC. Revisa $LOG"; exit 1
fi
echo "  menú de arranque con root=UUID=$UUID_RAIZ (vale en cualquier PC)"

# ------------------------------------------------------------------ 7. dejarlo como recién salido de fábrica
paso "Últimos retoques"
truncate -s0 "$MONTAJE/etc/machine-id"; rm -f "$MONTAJE/var/lib/dbus/machine-id"
ln -sf ../run/systemd/resolve/stub-resolv.conf "$MONTAJE/etc/resolv.conf"
mkdir -p "$MONTAJE/etc/jarvis"; date -Iseconds > "$MONTAJE/etc/jarvis/primer-arranque"
chroot "$MONTAJE" apt-get clean
rm -f "$MONTAJE/tmp/dentro_del_disco.sh" "$MONTAJE/etc/apt/apt.conf.d/99prueba-ca" \
      "$MONTAJE/usr/local/share/ca-certificates/prueba-proxy.crt"
[ -n "${JARVIS_PRUEBA_CA:-}" ] && chroot "$MONTAJE" update-ca-certificates --fresh >>"$LOG" 2>&1 || true
sync
echo
du -sh --exclude=proc --exclude=sys --exclude=dev "$MONTAJE" 2>/dev/null | tee -a "$LOG"
paso "Listo. Arranca un PC desde este disco (menú de arranque: F9, F12, F8 o Esc según la marca)."
