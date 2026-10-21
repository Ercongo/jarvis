#!/bin/bash
set -e
cd ~/jarvis
cp arrancar_jarvis.sh copias_codigo/arrancar_jarvis.sh.antes_grafica
if ! grep -q sin_aceleracion arrancar_jarvis.sh; then
  sed -i '/^    mkdir -p "\$PERFIL_FF"$/a\    bash "$J/sin_aceleracion.sh"          # sin aceleración gráfica: la radeon se cuelga con Firefox' arrancar_jarvis.sh
fi
grep -n -B1 -A1 sin_aceleracion arrancar_jarvis.sh
bash -n arrancar_jarvis.sh && echo "SINTAXIS OK"
chmod +x sin_aceleracion.sh
bash sin_aceleracion.sh
ls -la ~/snap/firefox/common/jarvis-perfil/user.js ~/snap/firefox/common/.mozilla/firefox/*/user.js 2>/dev/null
