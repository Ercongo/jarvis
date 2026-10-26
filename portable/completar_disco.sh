#!/bin/bash
# Completa un disco portátil ya construido, sin borrarlo ni rehacerlo:
#   - pone al día el asistente de /opt/jarvis (código y scripts; los entornos de Python se conservan);
#   - IA local de reserva: Ollama + qwen2.5:1.5b (antes fallaba porque faltaba zstd);
#   - LibreDWG compilado (para leer planos DWG: Ubuntu 26.04 no lo trae);
#   - OmniRoute preparado en /opt/omniroute (cada persona lo configura al entrar);
#   - paquetes de Python nuevos, Archify, HyperFrames (con su Chrome) y GSAP en /opt/jarvis-herramientas;
#   - los instaladores de Alexa y SearXNG (cada persona los lanza sin sudo).
#
#   sudo bash portable/completar_disco.sh /dev/sdX          (pide escribir SEGUIR; no borra nada)
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO="${1:-}"
MONTAJE=/mnt/disco-asistente
LOG=/var/log/completar_disco_asistente.log
paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*" | tee -a "$LOG"; }

[ "$(id -u)" = 0 ] || { echo "Hace falta ejecutarlo con sudo."; exit 1; }
[ -b "$DESTINO" ] || { echo "Indica el disco: sudo bash $0 /dev/sdX   (míralo con: lsblk -d -o NAME,SIZE,TRAN,MODEL)"; exit 1; }
[ "$(lsblk -dno TRAN "$DESTINO" | tr -d ' ')" = "usb" ] || { echo "$DESTINO no es un disco USB. No."; exit 1; }
RAIZ=$(findmnt -no SOURCE / | sed -E 's/p?[0-9]+$//')
case "$RAIZ" in "$DESTINO"*) echo "$DESTINO es el disco del sistema en marcha. No."; exit 1 ;; esac
parte() { if [ -e "${DESTINO}p$1" ]; then echo "${DESTINO}p$1"; else echo "${DESTINO}$1"; fi; }
P_EFI=$(parte 2); P_RAIZ=$(parte 3)
[ "$(blkid -s LABEL -o value "$P_RAIZ" 2>/dev/null)" = "ASISTENTE" ] || {
    echo "$P_RAIZ no es la partición «ASISTENTE» de un disco portátil. Constrúyelo primero con construir_disco.sh."; exit 1; }
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DESTINO"
echo "Disco: $(lsblk -dno MODEL,SIZE "$DESTINO")"
echo "Se completa (no se borra nada). Escribe SEGUIR:"
read -r R
[ "$R" = "SEGUIR" ] || { echo "Cancelado."; exit 1; }
: > "$LOG"

limpiar() {
    set +e
    [ -L "$MONTAJE/etc/resolv.conf.asistente" ] && mv -f "$MONTAJE/etc/resolv.conf.asistente" "$MONTAJE/etc/resolv.conf"
    for d in dev/pts dev proc sys run boot/efi ""; do umount -l "$MONTAJE/$d" 2>/dev/null; done
}
trap limpiar EXIT

paso "Montar el disco"
{ lsblk -nlo MOUNTPOINT "$DESTINO" | grep -v '^$' || true; } | sort -r | while IFS= read -r m; do umount "$m" || umount -l "$m" || true; done
mkdir -p "$MONTAJE"
mount "$P_RAIZ" "$MONTAJE"
mount "$P_EFI" "$MONTAJE/boot/efi"
for d in dev dev/pts proc sys run; do mount --bind "/$d" "$MONTAJE/$d"; done
if [ -L "$MONTAJE/etc/resolv.conf" ]; then mv "$MONTAJE/etc/resolv.conf" "$MONTAJE/etc/resolv.conf.asistente"; fi
grep -E '^nameserver' /etc/resolv.conf | grep -v '127.0.0.53' > "$MONTAJE/etc/resolv.conf" 2>/dev/null || true
[ -s "$MONTAJE/etc/resolv.conf" ] || printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$MONTAJE/etc/resolv.conf"

paso "Poner al día el asistente (/opt/jarvis)"
J="$MONTAJE/opt/jarvis"
cp -a "$REPO/core-orchestrator/." "$J/core-orchestrator/"
find "$J/core-orchestrator" -name __pycache__ -prune -exec rm -rf {} +
for s in "$REPO"/scripts/*.sh "$REPO"/scripts/*.py "$REPO"/scripts/jarvis-mantenimiento; do [ -f "$s" ] && install -m 755 "$s" "$J/"; done
cp "$REPO/requirements.txt" "$REPO/instalar.sh" "$J/" 2>/dev/null || true
install -m 755 "$REPO/portable/primer_arranque.sh" "$MONTAJE/usr/local/sbin/asistente-primer-arranque"
md5sum "$J/core-orchestrator/jarvis.py" "$J/core-orchestrator/omniroute.py" | tee -a "$LOG"

chroot "$MONTAJE" /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin bash -c '
    export DEBIAN_FRONTEND=noninteractive
    falta() { echo "$1" >> /var/log/paquetes_omitidos.txt; echo "  (omitido: $1)"; }
    # lo que se vuelve a intentar sale de la lista de omitidos (si vuelve a fallar, se apunta otra vez)
    sed -i -E "/^(ollama|modelo qwen|libredwg|omniroute|paquetes de python|archify|hyperframes|chrome de|gsap|restic)/d" /var/log/paquetes_omitidos.txt 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq zstd xz-utils curl ca-certificates build-essential pkg-config git bzip2 >/dev/null

    echo "▸ IA local de reserva: Ollama + qwen2.5:1.5b"
    if [ -x /usr/local/bin/ollama ] || [ -x /usr/bin/ollama ] || \
       { curl -fsSL https://ollama.com/install.sh -o /tmp/ollama.sh && sh /tmp/ollama.sh; }; then
        export OLLAMA_MODELS=/usr/share/ollama/.ollama/models
        mkdir -p $OLLAMA_MODELS
        OLLAMA_HOST=127.0.0.1:11555 ollama serve >/tmp/ollama.log 2>&1 & P=$!
        sleep 8
        OLLAMA_HOST=127.0.0.1:11555 ollama pull qwen2.5:1.5b || falta "modelo qwen2.5:1.5b"
        kill $P 2>/dev/null; wait $P 2>/dev/null
        id ollama >/dev/null 2>&1 && chown -R ollama:ollama /usr/share/ollama
        systemctl enable ollama 2>/dev/null || true
    else
        falta "ollama"
    fi

    echo "▸ LibreDWG (planos DWG), compilado: Ubuntu 26.04 no lo trae (varios minutos)"
    if [ -x /usr/local/bin/dwg2dxf ] || [ -x /usr/bin/dwg2dxf ]; then
        echo "  ya estaba"
    else
        T=$(mktemp -d)
        V=$(curl -fsSL https://ftp.gnu.org/gnu/libredwg/ | grep -oE "libredwg-[0-9]+\.[0-9]+(\.[0-9]+)?\.tar\.xz" | sort -V | tail -1)
        if [ -n "$V" ] && curl -fsSL "https://ftp.gnu.org/gnu/libredwg/$V" -o "$T/$V" \
           && mkdir "$T/src" && tar -xJf "$T/$V" -C "$T/src" --strip-components=1 && cd "$T/src" \
           && ./configure --prefix=/usr/local --disable-bindings --disable-python --disable-shared >/tmp/dwg.log 2>&1 \
           && make -j"$(nproc)" >>/tmp/dwg.log 2>&1 && make install >>/tmp/dwg.log 2>&1; then
            echo "  $V instalado en /usr/local/bin/dwg2dxf"
        else
            tail -5 /tmp/dwg.log 2>/dev/null; falta "libredwg"
        fi
        cd /; rm -rf "$T"
    fi

    echo "▸ OmniRoute en /opt/omniroute (cada persona lo configura al entrar)"
    if [ -f /opt/omniroute/lib/node_modules/omniroute/bin/omniroute.mjs ]; then
        echo "  ya estaba"
    else
        T=$(mktemp -d); BASE=https://nodejs.org/dist/latest-v24.x
        if curl -fsSL "$BASE/SHASUMS256.txt" -o $T/S && A=$(grep -oE "node-v[0-9.]+-linux-x64\.tar\.xz" $T/S | head -1) \
           && curl -fsSL "$BASE/$A" -o $T/$A && (cd $T && grep " $A\$" S | sha256sum -c -) \
           && mkdir -p /opt/omniroute && tar -xJf $T/$A -C /opt/omniroute --strip-components=1 \
           && PATH=/opt/omniroute/bin:$PATH npm install -g --no-audit --no-fund omniroute@3.8.52 >/tmp/omni.log 2>&1; then
            echo "  OmniRoute preparado: $(du -sh /opt/omniroute | cut -f1)"
        else
            tail -5 /tmp/omni.log 2>/dev/null; rm -rf /opt/omniroute; falta "omniroute"
        fi
        rm -rf $T
    fi
    echo "▸ Paquetes de Python nuevos del asistente (YouTube, documentos, aprender…)"
    if /opt/jarvis/venv/bin/pip install -q -r /opt/jarvis/requirements.txt >/tmp/pip.log 2>&1; then
        echo "  al día: $(/opt/jarvis/venv/bin/pip list 2>/dev/null | grep -ciE "youtube-transcript-api|firecrawl-anydoc") de 2 nuevos"
    else
        tail -3 /tmp/pip.log; falta "paquetes de python nuevos"
    fi

    echo "▸ Herramientas visuales para todos los usuarios (/opt/jarvis-herramientas)"
    H=/opt/jarvis-herramientas; mkdir -p $H/home
    if [ -d $H/archify/.git ]; then git -C $H/archify pull -q --ff-only || true
    else git clone -q --depth 1 https://github.com/tt-a1i/archify $H/archify || falta "archify"; fi
    if [ -x /opt/omniroute/bin/node ]; then
        export PATH=/opt/omniroute/bin:$PATH HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1
        if npm install -g --no-audit --no-fund hyperframes@0.8.200 >/tmp/hf.log 2>&1; then
            HOME=$H/home hyperframes telemetry disable >/dev/null 2>&1 || true
            HOME=$H/home hyperframes browser ensure 2>&1 | tail -1 || falta "chrome de hyperframes"
        else
            tail -3 /tmp/hf.log; falta "hyperframes"
        fi
    else
        falta "hyperframes (sin node)"
    fi
    curl -fsSL -o $H/gsap.min.js https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js || falta "gsap"
    if [ ! -x $H/restic ]; then                        # copias de seguridad cifradas (copias.py)
        T=$(mktemp -d)
        V=$(curl -fsSL https://api.github.com/repos/restic/restic/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)[\"tag_name\"].lstrip(\"v\"))")
        A=restic_${V}_linux_amd64.bz2
        if [ -n "$V" ] && curl -fsSL -o $T/$A https://github.com/restic/restic/releases/download/v$V/$A \
           && curl -fsSL -o $T/S https://github.com/restic/restic/releases/download/v$V/SHA256SUMS \
           && (cd $T && grep " $A\$" S | sha256sum -c - >/dev/null) && bunzip2 -c $T/$A > $H/restic; then
            chmod 755 $H/restic; echo "  restic $V"
        else
            falta "restic"
        fi
        rm -rf $T
    fi
    chmod -R a+rX $H
    echo "  $(du -sh $H | cut -f1) en $H"

    apt-get clean
    true
' 2>&1 | tee -a "$LOG"

paso "Alexa, SearXNG y copias: los instala cada persona (sin sudo) al entrar"
mkdir -p "$J/alexa" && cp "$REPO"/scripts/alexa/* "$J/alexa/"
echo "  bash /opt/jarvis/instalar_alexa.sh · bash /opt/jarvis/instalar_searxng.sh · bash /opt/jarvis/instalar_copias.sh" | tee -a "$LOG"

paso "Comprobación"
for p in /usr/local/bin/ollama /usr/bin/ollama /usr/local/bin/dwg2dxf /opt/omniroute/bin/node /opt/omniroute/bin/hyperframes \
         /opt/jarvis-herramientas/archify/archify/bin/archify.mjs /opt/jarvis-herramientas/gsap.min.js \
         /opt/jarvis-herramientas/restic /opt/jarvis/instalar_alexa.sh /opt/jarvis/instalar_searxng.sh /usr/bin/vlc /usr/bin/librecad /usr/bin/firefox; do
    if [ -e "$MONTAJE$p" ]; then echo "  ✔ $p"; fi
done | tee -a "$LOG"
ls "$MONTAJE/usr/share/ollama/.ollama/models/manifests" -R 2>/dev/null | grep -q "1.5b" && echo "  ✔ modelo qwen2.5:1.5b" | tee -a "$LOG"
echo "  Omitidos: $(sort -u "$MONTAJE/var/log/paquetes_omitidos.txt" 2>/dev/null | tr '\n' ' ')" | tee -a "$LOG"
grep -q "root=UUID=" "$MONTAJE/boot/grub/grub.cfg" && echo "  ✔ menú de arranque por UUID" | tee -a "$LOG"
df -h "$MONTAJE" | tail -1 | tee -a "$LOG"
sync
paso "Listo. Ya puedes desconectarlo y arrancar un PC con él."
