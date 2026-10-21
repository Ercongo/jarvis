#!/bin/bash
# Firefox de Jarvis: máximo 24 fotogramas por segundo y sin animaciones propias del navegador.
P="$HOME/snap/firefox/common/jarvis-perfil"
mkdir -p "$P"
cat > "$P/user.js" <<'EOF'
user_pref("layout.frame_rate", 24);
user_pref("toolkit.cosmeticAnimations.enabled", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("app.update.enabled", false);
EOF
echo "== Ajustes aplicados. Reabriendo la interfaz…"
export DISPLAY=:0
setsid -f bash "$HOME/jarvis/arrancar_jarvis.sh" >/dev/null 2>&1
echo "== Esperando 60 s a que se estabilice para medir…"
sleep 60
bash "$HOME/jarvis/rendimiento.sh"
