#!/bin/bash
# La gráfica del portátil (AMD A10, "ARUBA", controlador radeon) se cuelga cuando Firefox dibuja con ella:
# la pantalla se queda en negro y el ordenador hay que reiniciarlo. Con estas preferencias Firefox dibuja
# con el procesador (la interfaz de Jarvis es un lienzo 2D, va igual de bien) y la gráfica queda tranquila.
# Además (v27) deja que YouTube y TikTok empiecen a sonar solos cuando Jarvis los abre.
PREFS='user_pref("gfx.webrender.software", true);
user_pref("gfx.webrender.all", false);
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.canvas.accelerated", false);
user_pref("webgl.disabled", true);
user_pref("media.hardware-video-decoding.enabled", false);
user_pref("media.ffmpeg.vaapi.enabled", false);
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);'
for perfil in "$HOME/snap/firefox/common/jarvis-perfil" "$HOME"/snap/firefox/common/.mozilla/firefox/*.default* \
              "$HOME"/.mozilla/firefox/*.default*; do
    [ -d "$perfil" ] || continue
    printf '%s\n' "$PREFS" > "$perfil/user.js"
done
