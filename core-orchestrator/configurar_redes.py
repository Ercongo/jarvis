"""Asistente de terminal para conectar Facebook, Instagram y X de Asuka (lo lanza configurar_redes_nexus.sh)."""
import getpass, json, os, sys, urllib.parse, urllib.request
sys.path.insert(0, os.path.expanduser("~/jarvis/core-orchestrator"))
from nexus_publicar import CONF, GRAPH, _http, _oauth1, config, ErrorRed

def preguntar(txt, secreto=False, comprobar=None, ayuda=""):
    """Pregunta hasta que el valor tiene la forma esperada. Lo secreto no se ve: solo se dice cuántos caracteres llegaron."""
    while True:
        v = "".join((getpass.getpass if secreto else input)(txt).split())
        if v.count("EAA") > 1:                           # pegado dos veces seguidas: vale la primera copia
            v = "EAA" + v.split("EAA")[1]
        if secreto:
            print(f"   (recibidos {len(v)} caracteres)")
        if not comprobar or comprobar(v):
            return v
        print("   ✖ Eso no parece correcto. " + ayuda)

c = config()
print("\n=== Facebook + Instagram (Meta) ===")
if input("¿Configurar Meta ahora? [s/N] ").lower().startswith("s"):
    app = preguntar("ID de la app (App ID, solo números): ", comprobar=lambda v: v.isdigit() and 10 <= len(v) <= 20,
                    ayuda="Es el «Identificador de la app»: solo números.")
    secreto = preguntar("Clave secreta de la app (App Secret, no se ve): ", True,
                        comprobar=lambda v: len(v) == 32 and all(c in "0123456789abcdef" for c in v.lower()),
                        ayuda="Son 32 letras y números (Configuración de la app → Básica → Mostrar). Vuelve a pegarla.")
    corto = preguntar("Token de acceso del Explorador de la Graph API (no se ve): ", True,
                      comprobar=lambda v: v.startswith("EAA") and len(v) > 100,
                      ayuda="El token empieza por «EAA» y es muy largo. Vuelve a generarlo y pégalo.")
    try:
        largo = _http("GET", f"{GRAPH}/oauth/access_token?" + urllib.parse.urlencode({
            "grant_type": "fb_exchange_token", "client_id": app, "client_secret": secreto, "fb_exchange_token": corto}))
        paginas = _http("GET", f"{GRAPH}/me/accounts?fields=id,name,access_token,instagram_business_account&"
                               f"access_token={largo['access_token']}").get("data", [])
    except ErrorRed as e:
        import re
        print("✖ Meta no lo acepta:", re.sub(r"EAA\w+", "[token]", str(e))); paginas = []
    if paginas:
        for i, p in enumerate(paginas, 1):
            print(f"  {i}. {p['name']}" + ("  (con Instagram)" if p.get("instagram_business_account") else ""))
        try:
            n = int(preguntar("¿Cuál es la página de Asuka? Número: ") or 1)
            p = paginas[n - 1]
        except (ValueError, IndexError):
            p = paginas[0]
            print(f"  Número no válido: uso «{p['name']}».")
        c["meta"] = {"page_id": p["id"], "page_name": p["name"], "page_token": p["access_token"],
                     "ig_id": (p.get("instagram_business_account") or {}).get("id", "")}
        print(f"✔ Página «{p['name']}» conectada" + (" con su Instagram." if c["meta"]["ig_id"] else
              ". ✖ No tiene Instagram enlazado: enlázalo en la página (Configuración → Cuentas vinculadas) y repite."))
    elif "meta" not in c:
        print("✖ No veo ninguna página de Facebook en esa cuenta.")
        try:                                               # para saber por qué (no muestra nada secreto)
            t = largo["access_token"]
            yo = _http("GET", f"{GRAPH}/me?fields=name&access_token={t}")
            per = _http("GET", f"{GRAPH}/me/permissions?access_token={t}").get("data", [])
            dados = sorted(x["permission"] for x in per if x.get("status") == "granted")
            faltan = [x for x in ("pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic",
                                  "instagram_content_publish", "business_management") if x not in dados]
            print(f"  Cuenta del token: {yo.get('name')}")
            print(f"  Permisos dados: {', '.join(dados) or 'ninguno'}")
            if faltan:
                print(f"  ✖ Faltan: {', '.join(faltan)}. Añádelos en el Explorador antes de «Generate Access Token».")
            else:
                print("  Los permisos están bien: en la ventana de Facebook no se marcó la página de Asuka, o esa página"
                      " no la administra esta cuenta. Revísalo en facebook.com/settings → Integraciones comerciales, o"
                      " en la página de Asuka → Configuración → Acceso a la página.")
        except Exception as e:
            print("  (No he podido ver los permisos:", type(e).__name__, ")")

print("\n=== X ===")
if input("¿Configurar X ahora? [s/N] ").lower().startswith("s"):
    print("  (Son las 4 claves de developer.x.com → tu app → Keys and tokens. No son las de Meta.)")
    no_meta = lambda v: not v.isdigit() and not v.startswith("EAA") and len(v) >= 20
    aviso = "Esa no es una clave de X (parece de Meta). Cópiala de developer.x.com → Keys and tokens."
    x = {"api_key": preguntar("API Key (no se ve): ", True, no_meta, aviso),
         "api_secret": preguntar("API Key Secret (no se ve): ", True, no_meta, aviso),
         "token": preguntar("Access Token (no se ve): ", True, lambda v: "-" in v and no_meta(v),
                            "El Access Token de X lleva un guion en medio (números-letras)."),
         "token_secret": preguntar("Access Token Secret (no se ve): ", True, no_meta, aviso)}
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
