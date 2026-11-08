#!/bin/bash
# Cancelación de eco de PipeWire (WebRTC) para que Athena no se oiga a sí misma y se la pueda interrumpir.
# ESTADO 4 nov: DESACTIVADO. En las pruebas bajaba ~25 dB también las voces de fuera (riesgo de que Athena no oiga).
# Probarlo solo con alguien hablando de verdad: si te oye bien con el micro «sin eco», se deja; si no, aec_quitar.
# Sin sudo. Si algo falla, lo deja como estaba.
set -u
C=~/.config/pipewire/pipewire.conf.d; F=$C/60-athena-eco.conf
echo "pipewire: $(pipewire --version 2>/dev/null | tail -1)"
M=$(find /usr/lib -name "libpipewire-module-echo-cancel.so" 2>/dev/null | head -1)
A=$(find /usr/lib -name "libspa-aec-webrtc.so" 2>/dev/null | head -1)
echo "módulo: ${M:-NO} · webrtc: ${A:-NO}"
[ -z "$M" ] && { echo "no hay módulo de eco: no se toca nada"; exit 0; }
SINK=$(pactl get-default-sink); SRC=$(pactl get-default-source)
if [[ "$SRC" == athena_eco* ]]; then echo "ya estaba puesto"; SINK=$(grep -o 'target.object = "[^"]*"' $F | sed -n 2p | cut -d'"' -f2); SRC=$(grep -o 'target.object = "[^"]*"' $F | sed -n 1p | cut -d'"' -f2); fi
echo "altavoz real: $SINK"; echo "micro real:   $SRC"
mkdir -p $C
cat > $F <<EOF
# Athena: cancelación de eco (lo que suena por el altavoz se quita del micro)
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name = aec/libspa-aec-webrtc
      monitor.mode = false
      capture.props = { node.name = "athena_eco_captura" target.object = "$SRC" node.passive = true }
      source.props = { node.name = "athena_eco_micro" node.description = "Micro sin eco (Athena)" }
      sink.props = { node.name = "athena_eco_altavoz" node.description = "Altavoz con cancelación de eco (Athena)" }
      playback.props = { node.name = "athena_eco_salida" target.object = "$SINK" node.passive = true }
    }
  }
]
EOF
systemctl --user restart pipewire pipewire-pulse wireplumber; sleep 5
if ! pactl list short sources | grep -q athena_eco_micro; then
    echo "NO ha salido el micro sin eco: deshago"; rm -f $F
    systemctl --user restart pipewire pipewire-pulse wireplumber; sleep 4; pactl set-default-sink "$SINK"; pactl set-default-source "$SRC"
    exit 1
fi
pactl set-default-source athena_eco_micro; pactl set-default-sink athena_eco_altavoz
echo "por defecto ahora: $(pactl get-default-sink) · $(pactl get-default-source)"
# prueba: ruido rosa por el altavoz con eco; se graba a la vez del micro real y del limpio
ffmpeg -loglevel error -y -f lavfi -i "anoisesrc=color=pink:amplitude=0.25:d=4" -ar 48000 /tmp/rosa.wav
timeout 5 parec -d "$SRC" --format=s16le --rate=16000 --channels=1 > /tmp/real.raw & P1=$!
timeout 5 parec -d athena_eco_micro --format=s16le --rate=16000 --channels=1 > /tmp/limpio.raw & P2=$!
sleep 0.5; pw-play --target athena_eco_altavoz /tmp/rosa.wav; wait $P1 $P2 2>/dev/null
~/jarvis/venv/bin/python - <<'P'
import numpy as np
r = np.fromfile("/tmp/real.raw", dtype=np.int16).astype(float) / 32768; l = np.fromfile("/tmp/limpio.raw", dtype=np.int16).astype(float) / 32768
f = lambda x: 20 * np.log10(np.sqrt(np.mean(x[8000:-8000] ** 2)) + 1e-9) if len(x) > 20000 else float("nan")
print(f"eco en el micro real: {f(r):.1f} dB · en el micro limpio: {f(l):.1f} dB · quitado: {f(r) - f(l):.1f} dB")
P
pkill -f core-orchestrator/jarvis.py; sleep 4
(setsid nohup bash ~/jarvis/reiniciar.sh >/tmp/reinicio.log 2>&1 &)
sleep 55; echo "athena: $(ps aux | grep -c '[c]ore-orchestrator/jarvis.py')"; grep -a "ruido de fondo\|micrófono" ~/jarvis/logs/jarvis.log | tail -2
