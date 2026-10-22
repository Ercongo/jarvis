#!/bin/bash
# Instala OmniRoute (https://github.com/cheaper-inference/OmniRoute, licencia MIT) para el asistente:
# una puerta de enlace de IA en este equipo que reparte entre varios proveedores gratuitos y salta al siguiente
# cuando uno agota su cupo. El asistente lo usa como segundo cerebro cuando Groq se queda sin cupo.
#
#   bash ~/jarvis/instalar_omniroute.sh          (no hace falta sudo; ocupa unos 2 GB y usa ~650 MB de RAM)
#
# - Node 24 en ~/.local/node (si no hay uno válido, se descarga el oficial de nodejs.org y se comprueba).
# - Servicio del usuario «omniroute» (systemd --user): solo escucha en 127.0.0.1:20128, con clave obligatoria
#   y la memoria limitada. Sin panel web (modo headless).
# - Clave y contraseña en ~/jarvis/omniroute.json (600). Conecta las claves que ya tenga el asistente (Groq,
#   Hugging Face, OpenRouter) y crea la combinación «asistente».
set -euo pipefail
trap 'echo "✖ Error en la línea $LINENO: $BASH_COMMAND" >&2' ERR

VERSION_OMNI="${OMNIROUTE_VERSION:-3.8.52}"
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
SECRETOS="${JARVIS_SECRETOS:-$J}"
NODO="$HOME/.local/node"
DATOS="$HOME/.local/share/omniroute"
ENTORNO="$HOME/.config/omniroute/entorno"
PUERTO=20128

paso() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

# ------------------------------------------------------------------ 1. Node 24
paso "Node.js (hace falta 22.22.2 o 24 en adelante)"
node_valido() {
    [ -x "$1" ] || return 1
    "$1" -e 'const [a,b,c]=process.versions.node.split(".").map(Number);
             process.exit((a>=24)||(a===22&&(b>22||(b===22&&c>=2)))?0:1)' 2>/dev/null
}
# el disco portátil ya lo trae preparado en /opt/omniroute (Node + OmniRoute): solo falta configurarlo
if ! node_valido "$NODO/bin/node" && node_valido /opt/omniroute/bin/node \
        && [ -f /opt/omniroute/lib/node_modules/omniroute/bin/omniroute.mjs ]; then
    NODO=/opt/omniroute
fi
if ! node_valido "$NODO/bin/node"; then
    echo "  Descargo Node 24 oficial en $NODO"
    T=$(mktemp -d)
    BASE=https://nodejs.org/dist/latest-v24.x
    curl -fsSL "$BASE/SHASUMS256.txt" -o "$T/SHASUMS256.txt"
    ARCHIVO=$(grep -oE "node-v[0-9.]+-linux-x64\.tar\.xz" "$T/SHASUMS256.txt" | head -1)
    curl -fsSL "$BASE/$ARCHIVO" -o "$T/$ARCHIVO"
    (cd "$T" && grep " $ARCHIVO\$" SHASUMS256.txt | sha256sum -c -)
    rm -rf "$NODO.nuevo"; mkdir -p "$NODO.nuevo"
    tar -xJf "$T/$ARCHIVO" -C "$NODO.nuevo" --strip-components=1
    [ -d "$NODO" ] && mv "$NODO" "$NODO.antes_$(date +%Y%m%d%H%M%S)"
    mv "$NODO.nuevo" "$NODO"
    rm -rf "$T"
fi
export PATH="$NODO/bin:$PATH"
echo "  Node $(node --version) en $NODO"

# ------------------------------------------------------------------ 2. OmniRoute
paso "OmniRoute $VERSION_OMNI (unos 2 GB; tarda varios minutos)"
CLI="$NODO/lib/node_modules/omniroute/bin/omniroute.mjs"
if [ -f "$CLI" ] && [ "$(node -p "require('$NODO/lib/node_modules/omniroute/package.json').version")" = "$VERSION_OMNI" ]; then
    echo "  Ya estaba instalado."
elif [ -w "$NODO/lib" ]; then
    npm install -g --no-audit --no-fund "omniroute@$VERSION_OMNI" 2>&1 | tail -3
else
    echo "  Uso la versión que trae el disco: $(node -p "require('$NODO/lib/node_modules/omniroute/package.json').version")"
fi
[ -f "$CLI" ] || { echo "No se ha instalado bien (falta $CLI)."; exit 1; }

# ------------------------------------------------------------------ 3. claves (solo legibles por ti)
paso "Clave y contraseña"
mkdir -p "$SECRETOS" "$DATOS" "$(dirname "$ENTORNO")"
CONF="$SECRETOS/omniroute.json"
if [ -f "$CONF" ]; then
    CLAVE=$(python3 -c "import json;print(json.load(open('$CONF'))['clave'])")
    CONTRA=$(python3 -c "import json;print(json.load(open('$CONF')).get('contrasena',''))")
fi
CLAVE="${CLAVE:-omni-$(openssl rand -hex 24)}"
CONTRA="${CONTRA:-$(openssl rand -base64 18 | tr -d '/+=')}"
umask 077
python3 - "$CONF" "$CLAVE" "$CONTRA" "$DATOS" "$PUERTO" <<'EOF'
import json, sys
ruta, clave, contra, datos, puerto = sys.argv[1:]
try:
    c = json.load(open(ruta))
except (OSError, ValueError):
    c = {}
c.update(url=f"http://127.0.0.1:{puerto}/v1", clave=clave, contrasena=contra, datos=datos)
c.setdefault("modelo", "asistente")
json.dump(c, open(ruta, "w"), indent=1)
EOF
chmod 600 "$CONF"
cat > "$ENTORNO" <<EOF
OMNIROUTE_API_KEY=$CLAVE
REQUIRE_API_KEY=true
OMNIROUTE_SERVER_HOST=127.0.0.1
PORT=$PUERTO
DATA_DIR=$DATOS
NODE_OPTIONS=--max-old-space-size=384
PATH=$NODO/bin:/usr/local/bin:/usr/bin:/bin
EOF
chmod 600 "$ENTORNO"
umask 022
DATA_DIR="$DATOS" node "$CLI" setup --non-interactive --password "$CONTRA" 2>&1 | grep -E "✔|✖" || true
echo "  Guardadas en $CONF (solo tú puedes leerlas)."

# ------------------------------------------------------------------ 4. servicio
paso "Servicio «omniroute» (arranca con la sesión)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/omniroute.service" <<EOF
[Unit]
Description=OmniRoute: puerta de enlace de IA para el asistente (solo 127.0.0.1)
After=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENTORNO
ExecStart=$NODO/bin/node $CLI serve --headless --no-open
Restart=on-failure
RestartSec=10
Nice=5
MemoryMax=900M

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable omniroute.service >/dev/null 2>&1
systemctl --user restart omniroute.service
echo -n "  Esperando a que responda"
for _ in $(seq 1 90); do
    c=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CLAVE" "http://127.0.0.1:$PUERTO/v1/models" || true)
    [ "$c" = 200 ] && break
    echo -n "."; sleep 2
done
echo
[ "$c" = 200 ] || { echo "No responde. Mira: journalctl --user -u omniroute -n 50"; exit 1; }
SIN=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PUERTO/v1/models" || true)
echo "  Responde (sin clave: $SIN, como debe ser)."

# ------------------------------------------------------------------ 5. proveedores y combinación
paso "Conectar las claves que ya tiene el asistente y crear la combinación «asistente»"
PY="$J/venv/bin/python"; [ -x "$PY" ] || PY=python3
cd "$J/core-orchestrator"
JARVIS_SECRETOS="$SECRETOS" "$PY" - <<'EOF'
import time
import omniroute
o = omniroute.OmniRoute(log=lambda t: print("  " + t))
o.sincronizar_claves()
o.rehacer_combo()
print("  Proveedores:", ", ".join(sorted({p.get("name") or p.get("provider") for p in o.proveedores()})) or "ninguno",
      "+ DuckDuckGo sin cuenta")
t0 = time.time()
try:
    r = o.chat([{"role": "user", "content": "Responde solo: funciono"}], max_tokens=300, timeout=60)
    print(f"  Prueba: «{r[:40]}» en {time.time() - t0:.1f} s con {getattr(o, 'ultimo_modelo', '?')}")
except omniroute.SinOmni as e:
    print(f"  La prueba no ha salido ({e}). El asistente seguirá con Groq; mira «estado de OmniRoute».")
EOF

paso "Listo"
echo "  Reinicia el asistente para que lo use: bash $J/reiniciar.sh"
echo "  Para tener más cupo gratis, conecta más proveedores: dile «conecta Gemini a OmniRoute»."
