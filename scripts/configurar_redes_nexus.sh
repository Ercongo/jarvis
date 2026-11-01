#!/bin/bash
# Conecta Facebook (página), Instagram y X de Asuka para que Athena publique sola.
#   bash ~/jarvis/configurar_redes_nexus.sh
# Lo que pegues aquí no se ve al escribir y se guarda solo en este portátil (~/.config/athena-nexus/redes.json, 600).
exec python3 - "$@" <<'EOF'
import getpass, json, os, sys, urllib.parse, urllib.request
sys.path.insert(0, os.path.expanduser("~/jarvis/core-orchestrator"))
from nexus_publicar import CONF, GRAPH, _http, _oauth1, config, ErrorRed

def preguntar(txt, secreto=False):
    v = (getpass.getpass if secreto else input)(txt).strip()
    return v

c = config()
print("\n=== Facebook + Instagram (Meta) ===")
if input("¿Configurar Meta ahora? [s/N] ").lower().startswith("s"):
    app = preguntar("ID de la app (App ID): ")
    secreto = preguntar("Clave secreta de la app (App Secret, no se ve): ", True)
    corto = preguntar("Token de acceso del Explorador de la Graph API (no se ve): ", True)
    try:
        largo = _http("GET", f"{GRAPH}/oauth/access_token?" + urllib.parse.urlencode({
            "grant_type": "fb_exchange_token", "client_id": app, "client_secret": secreto, "fb_exchange_token": corto}))
        paginas = _http("GET", f"{GRAPH}/me/accounts?fields=id,name,access_token,instagram_business_account&"
                               f"access_token={largo['access_token']}").get("data", [])
    except ErrorRed as e:
        print("✖ Meta no lo acepta:", e); paginas = []
    if paginas:
        for i, p in enumerate(paginas, 1):
            print(f"  {i}. {p['name']}" + ("  (con Instagram)" if p.get("instagram_business_account") else ""))
        n = int(preguntar("¿Cuál es la página de Asuka? Número: ") or 1)
        p = paginas[n - 1]
        c["meta"] = {"page_id": p["id"], "page_name": p["name"], "page_token": p["access_token"],
                     "ig_id": (p.get("instagram_business_account") or {}).get("id", "")}
        print(f"✔ Página «{p['name']}» conectada" + (" con su Instagram." if c["meta"]["ig_id"] else
              ". ✖ No tiene Instagram enlazado: enlázalo en la página (Configuración → Cuentas vinculadas) y repite."))
    elif "meta" not in c:
        print("✖ No veo ninguna página: marca en el Explorador los permisos de la lista y elige la página de Asuka.")

print("\n=== X ===")
if input("¿Configurar X ahora? [s/N] ").lower().startswith("s"):
    x = {"api_key": preguntar("API Key: "), "api_secret": preguntar("API Key Secret (no se ve): ", True),
         "token": preguntar("Access Token: "), "token_secret": preguntar("Access Token Secret (no se ve): ", True)}
    try:
        url = "https://api.x.com/2/users/me"
        yo = _http("GET", url, None, {"Authorization": _oauth1("GET", url, x)})
        c["x"] = x
        print(f"✔ X conectado como @{yo['data']['username']}.")
    except ErrorRed as e:
        print("✖ X no lo acepta:", e, "\n  Revisa que la app tenga permisos «Read and write» y que regeneraste los tokens después.")

CONF.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(CONF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(c, f)
print("\nGuardado. Athena ya puede publicar en:", ", ".join(k for k in ("meta", "x") if k in c) or "nada todavía")
EOF
