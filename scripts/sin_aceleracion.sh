#!/bin/bash
# Preferencias del navegador del asistente:
#  - siempre: que YouTube y TikTok suenen solos cuando el asistente los abre, y sin pantallas de bienvenida ni
#    avisos de Firefox que tapen la interfaz (ni «restaurar sesión» tras un apagón);
#  - solo si la gráfica lo necesita (AMD antiguas con el controlador «radeon», como la ARUBA del primer portátil, que
#    se cuelgan cuando Firefox dibuja con ellas): dibujar con el procesador. Lo detecta core-orchestrator/equipo.py.
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
M="${JARVIS_MOTOR:-$J/core-orchestrator}"
PY="$J/venv/bin/python"; [ -x "$PY" ] || PY=python3
SIN_ACELERACION="${JARVIS_SIN_ACELERACION:-}"
[ -z "$SIN_ACELERACION" ] && eval "$(cd "$M" && "$PY" equipo.py --shell 2>/dev/null)"
PREFS='user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("trailhead.firstrun.didSeeAboutWelcome", true);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("termsofuse.bypassNotification", true);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);'
if [ "$SIN_ACELERACION" = "1" ]; then
PREFS="$PREFS"'
user_pref("gfx.webrender.software", true);
user_pref("gfx.webrender.all", false);
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.canvas.accelerated", false);
user_pref("webgl.disabled", true);
user_pref("media.hardware-video-decoding.enabled", false);
user_pref("media.ffmpeg.vaapi.enabled", false);'
fi
for perfil in "$HOME/snap/firefox/common/jarvis-perfil" "$HOME"/snap/firefox/common/.mozilla/firefox/*.default* \
              "$HOME"/.mozilla/firefox/*.default*; do
    [ -d "$perfil" ] || continue
    printf '%s\n' "$PREFS" > "$perfil/user.js"
done

# Toda la sesión gráfica sin 3D en esa gráfica: Firefox prueba la gráfica al abrirse (gfxtest) aunque tenga la
# aceleración desactivada, y eso bastó para colgarla el 22 oct. Con LIBGL_ALWAYS_SOFTWARE todo se dibuja con el
# procesador (llvmpipe). Lo lee la sesión de LightDM/Xsession al entrar (~/.xsessionrc).
XS="$HOME/.xsessionrc"
if [ "$SIN_ACELERACION" = "1" ]; then
    if ! grep -q "JARVIS-SIN-ACELERACION" "$XS" 2>/dev/null; then
        cat >> "$XS" <<'EOF2'
# JARVIS-SIN-ACELERACION: la gráfica integrada (radeon) se cuelga con el 3D. Todo se dibuja con el procesador.
export LIBGL_ALWAYS_SOFTWARE=1
export MOZ_WEBRENDER=1
export MOZ_X11_EGL=0
# FIN-JARVIS-SIN-ACELERACION
EOF2
    fi
elif [ -f "$XS" ] && grep -q "JARVIS-SIN-ACELERACION" "$XS"; then
    sed -i '/# JARVIS-SIN-ACELERACION/,/# FIN-JARVIS-SIN-ACELERACION/d' "$XS"
fi


# La sesión arranca con startx (~/.xinitrc), que NO lee ~/.xsessionrc: sin esto lo de arriba no servía y la gráfica
# se volvió a colgar el 26 oct (radeon «ring 3 stalled», pantalla congelada). Además el compositor de Xfce dibuja
# con 3D: se apaga.
XI="$HOME/.xinitrc"
if [ "$SIN_ACELERACION" = "1" ]; then
    if [ -f "$XI" ] && ! grep -q "xsessionrc" "$XI"; then
        sed -i '1a [ -f "$HOME/.xsessionrc" ] \&\& . "$HOME/.xsessionrc"   # JARVIS: sin 3D en la gráfica radeon' "$XI"
    fi
    if command -v xfconf-query >/dev/null && xfconf-query -c xfwm4 -p /general/use_compositing >/dev/null 2>&1; then
        xfconf-query -c xfwm4 -p /general/use_compositing -s false 2>/dev/null || true
    fi
    XW="$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"
    [ -f "$XW" ] && sed -i 's|name="use_compositing" type="bool" value="true"|name="use_compositing" type="bool" value="false"|' "$XW"
fi
