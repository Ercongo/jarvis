#!/bin/bash
# Conecta el Gmail del personaje de Nexus a su página (solo lectura).
# Antes, en el móvil o el PC, con la cuenta del personaje:
#   1. Activa la verificación en dos pasos:   https://myaccount.google.com/signinoptions/twosv
#   2. Crea una contraseña de aplicación:     https://myaccount.google.com/apppasswords  (nombre: Athena)
# Luego aquí:  bash ~/jarvis/configurar_correo_nexus.sh
# La contraseña de aplicación NO es la de la cuenta; se puede revocar cuando quieras desde esa misma página.
set -euo pipefail
CONF="$HOME/.config/athena-nexus"
mkdir -p "$CONF" && chmod 700 "$CONF"
DEF=$(python3 -c "import json;print(json.load(open('$HOME/jarvis/nexus/estado.json'))['id'].get('correo',''))" 2>/dev/null || true)
read -rp "Correo del personaje [$DEF]: " USU
USU=${USU:-$DEF}
read -rsp "Contraseña de aplicación (16 letras, no se ve al escribir): " CLAVE; echo
CLAVE=${CLAVE// /}
export USU CLAVE CONF
python3 - <<'EOF'
import imaplib, json, os, sys
u, c, conf = os.environ["USU"], os.environ["CLAVE"], os.environ["CONF"]
try:
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=25); m.login(u, c)
    n = m.select("INBOX", readonly=True)[1][0].decode(); m.logout()
except Exception as e:
    print("✖ Google no la acepta:", str(e)[:150]); print("  Revisa que sea una contraseña de APLICACIÓN y la verificación en dos pasos esté activa."); sys.exit(1)
ruta = os.path.join(conf, "correo.json")
fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f: json.dump({"usuario": u, "clave": c, "servidor": "imap.gmail.com"}, f)
print(f"✔ Conectado: {n} correos en la bandeja. Ya se ven en la página de Asuka (apartado Correo).")
EOF
unset CLAVE
