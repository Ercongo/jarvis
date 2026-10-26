"""
Datos al momento de APIs públicas y gratuitas, sin clave (elegidas de github.com/public-apis/public-apis y de
fuentes oficiales españolas):

  Festivos (Nager.Date)        «cuándo es el próximo festivo», «qué festivos hay en diciembre», «es festivo mañana»
  Divisas (Frankfurter, BCE)   «a cuánto está el dólar», «cuántos dólares son 50 euros», «convierte 20 libras a euros»
  Criptomonedas (CoinGecko)    «a cuánto está el bitcoin»
  Precio de la luz (REE)       «cuánto cuesta la luz hoy», «a qué hora es más barata la luz», «precio de la luz ahora»
  Carburantes (Ministerio)     «dónde está la gasolina más barata», «precio del diésel en Dos Hermanas»
  Aire y polen (Open-Meteo)    «qué tal está el aire», «cuánto polen hay»
  Sol (Open-Meteo)             «a qué hora amanece», «a qué hora se pone el sol mañana»
  Wikipedia                    «busca en la wikipedia la Giralda», «qué dice la wikipedia de Tesla»
  Estación espacial            «dónde está la estación espacial»
  «qué datos puedes consultar» → esta lista.
La ciudad, si no se dice, es la del perfil («mi ciudad es …»).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from herramientas import leer_config, normalizar
from sistema import Respuesta, con_tildes, a_numero

UA = "AsistenteJarvis/1.0 (asistente personal; uso domestico)"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
COMUNIDADES = {  # admin1 de Open-Meteo → código ISO que usa Nager.Date
    "andalucia": "ES-AN", "aragon": "ES-AR", "asturias": "ES-AS", "principado de asturias": "ES-AS",
    "islas baleares": "ES-IB", "illes balears": "ES-IB", "baleares": "ES-IB", "canarias": "ES-CN",
    "cantabria": "ES-CB", "castilla y leon": "ES-CL", "castilla-la mancha": "ES-CM", "castilla la mancha": "ES-CM",
    "cataluna": "ES-CT", "catalunya": "ES-CT", "comunidad valenciana": "ES-VC", "comunitat valenciana": "ES-VC",
    "valencia": "ES-VC", "extremadura": "ES-EX", "galicia": "ES-GA", "comunidad de madrid": "ES-MD",
    "madrid": "ES-MD", "region de murcia": "ES-MC", "murcia": "ES-MC", "navarra": "ES-NC",
    "comunidad foral de navarra": "ES-NC", "pais vasco": "ES-PV", "euskadi": "ES-PV", "la rioja": "ES-RI",
    "ceuta": "ES-CE", "melilla": "ES-ML"}
MONEDAS = {"euro": "EUR", "dolar": "USD", "dolares": "USD", "libra": "GBP", "libras": "GBP", "yen": "JPY", "yenes": "JPY",
           "franco suizo": "CHF", "francos suizos": "CHF", "yuan": "CNY", "yuanes": "CNY", "peso mexicano": "MXN",
           "pesos mexicanos": "MXN", "real": "BRL", "reales": "BRL", "dolar canadiense": "CAD", "corona sueca": "SEK",
           "coronas suecas": "SEK", "zloty": "PLN", "zlotys": "PLN", "dirham": "MAD", "rupia": "INR", "rupias": "INR",
           "lira turca": "TRY", "liras turcas": "TRY", "euros": "EUR", "corona noruega": "NOK", "corona danesa": "DKK"}
NOMBRE_MONEDA = {"EUR": "euros", "USD": "dólares", "GBP": "libras", "JPY": "yenes", "CHF": "francos suizos",
                 "CNY": "yuanes", "MXN": "pesos mexicanos", "BRL": "reales", "CAD": "dólares canadienses",
                 "SEK": "coronas suecas", "PLN": "zlotys", "MAD": "dírhams", "INR": "rupias", "TRY": "liras turcas",
                 "NOK": "coronas noruegas", "DKK": "coronas danesas"}
CRIPTO = {"bitcoin": "bitcoin", "btc": "bitcoin", "ethereum": "ethereum", "ether": "ethereum", "solana": "solana",
          "dogecoin": "dogecoin", "cardano": "cardano", "xrp": "ripple", "ripple": "ripple", "litecoin": "litecoin"}
CARBURANTES = {"gasolina 95": "Precio Gasolina 95 E5", "gasolina": "Precio Gasolina 95 E5",
               "gasolina 98": "Precio Gasolina 98 E5", "diesel": "Precio Gasoleo A", "gasoil": "Precio Gasoleo A",
               "gasoleo": "Precio Gasoleo A", "glp": "Precio Gases licuados del petróleo",
               "autogas": "Precio Gases licuados del petróleo"}

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _json(url: str, timeout: int = 15, cache: float = 0):
    with _lock:
        if cache and url in _cache and time.time() - _cache[url][0] < cache:
            return _cache[url][1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    if cache:
        with _lock:
            _cache[url] = (time.time(), d)
    return d


def num(x: float, dec: int = 2) -> str:
    """1234.5 → «1234,50» (decimales con coma, como se dice en España)."""
    s = f"{x:.{dec}f}".replace(".", ",")
    return s[:-3] if dec and s.endswith("," + "0" * dec) else s


def _fecha(d: dt.date) -> str:
    return f"el {DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def lugar(ciudad: str | None) -> dict | None:
    ciudad = ciudad or leer_config().get("ciudad")
    if not ciudad:
        return None
    d = _json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": ciudad, "count": 1, "language": "es", "format": "json", "countryCode": "ES"}), cache=86400 * 30)
    if not d.get("results"):
        d = _json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": ciudad, "count": 1, "language": "es", "format": "json"}), cache=86400 * 30)
    return (d.get("results") or [None])[0]


# ================================================================ festivos
def festivos(anio: int, region: str | None = None) -> list[tuple[dt.date, str]]:
    d = _json(f"https://date.nager.at/api/v3/PublicHolidays/{anio}/ES", cache=86400)
    res = []
    for f in d:
        if f.get("global") or (region and region in (f.get("counties") or [])):
            res.append((dt.date.fromisoformat(f["date"]), f.get("localName") or f.get("name")))
    return sorted(set(res))


def _region() -> tuple[str | None, str]:
    try:
        g = lugar(None)
    except Exception:
        g = None
    if not g:
        return None, "nacionales"
    return COMUNIDADES.get(normalizar(g.get("admin1", ""))), f"de {g.get('admin1', 'tu comunidad')}"


# ================================================================ el módulo
class Apis:
    def __init__(self, log=print):
        self.log = log

    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis|dime|sabes)[ ,]+", "", t)
        try:
            for regla in (self._festivos, self._divisas, self._cripto, self._luz, self._carburantes, self._aire,
                          self._sol, self._wikipedia, self._iss, self._velocidad, self._ayuda):
                r = regla(t, peticion)
                if r is not None:
                    return r
        except (OSError, ValueError, KeyError, IndexError) as e:
            self.log(f"apis: {e!r}")
            return Respuesta("No he podido consultar ese dato ahora mismo; prueba en un rato.")
        return None

    # ------------------------------------------------------------ festivos
    def _festivos(self, t: str, peticion: str) -> Respuesta | None:
        if not re.search(r"\b(festivo|festivos|puente|dia de fiesta|dias de fiesta)\b", t):
            return None
        hoy = dt.date.today()
        region, nombre_region = _region()
        lista = festivos(hoy.year, region) + festivos(hoy.year + 1, region)
        m = re.search(r"\b(?:en|de) (" + "|".join(MESES) + r")\b", t)
        if m:
            mes = MESES.index(m.group(1)) + 1
            anio = hoy.year if mes >= hoy.month else hoy.year + 1
            del_mes = [(d, n) for d, n in lista if d.month == mes and d.year == anio]
            if not del_mes:
                return Respuesta(f"En {m.group(1)} no hay festivos nacionales{'' if not region else ' ni ' + nombre_region}.")
            return Respuesta(f"En {m.group(1)}: " + "; ".join(f"{_fecha(d)}, {n}" for d, n in del_mes) + ".")
        dia = None
        if re.search(r"\b(es|sera|hay) festivo (hoy)\b|\bhoy es festivo\b", t):
            dia = hoy
        elif re.search(r"\bmanana\b", t):
            dia = hoy + dt.timedelta(days=1)
        if dia:
            f = [n for d, n in lista if d == dia]
            return Respuesta(f"Sí, {_fecha(dia)} es festivo: {f[0]}." if f else
                             f"No, {_fecha(dia)} no es festivo{' en ' + nombre_region[3:] if region else ''}.")
        proximos = [(d, n) for d, n in lista if d >= hoy][:3]
        if not proximos:
            return Respuesta("No encuentro los próximos festivos.")
        d, n = proximos[0]
        falta = (d - hoy).days
        texto = f"El próximo festivo es {_fecha(d)}, {n}" + (" (es hoy)" if falta == 0 else f", dentro de {falta} días" if falta > 1 else ", mañana") + "."
        if len(proximos) > 1:
            texto += " Después: " + "; ".join(f"{_fecha(x)}, {y}" for x, y in proximos[1:]) + "."
        if not region:
            texto += " Son los nacionales; dime tu ciudad («mi ciudad es…») y te digo también los de tu comunidad."
        return Respuesta(texto)

    # ------------------------------------------------------------ divisas
    def _divisas(self, t: str, peticion: str) -> Respuesta | None:
        nombres = sorted(MONEDAS, key=len, reverse=True)
        alt = "|".join(re.escape(n) for n in nombres)
        m = re.search(r"\b(?:cuantos|cuantas)\s+(" + alt + r")\s+(?:son|serian|me dan por|hay en)\s+([\d.,]+|\w+(?: y \w+)?)\s+(" + alt + r")\b", t)
        if m:
            cantidad, de, a = m.group(2), MONEDAS[m.group(3)], MONEDAS[m.group(1)]
        else:
            m = re.search(r"\b(?:convierte|cambia|pasa|cuanto son|cuanto es|a cuanto son)\s+([\d.,]+|\w+(?: y \w+)?)\s+(" + alt
                          + r")\s+(?:a|en)\s+(" + alt + r")\b", t)
            if m:
                cantidad, de, a = m.group(1), MONEDAS[m.group(2)], MONEDAS[m.group(3)]
            else:
                m = re.search(r"\b(?:a cuanto|como) esta(?: el cambio del?| el)?\s+(?:el |la )?(" + alt + r")\b|"
                              r"\b(?:cambio|cotizacion|precio) del? (" + alt + r")\b", t)
                if not m:
                    return None
                cod = MONEDAS[m.group(1) or m.group(2)]
                if cod == "EUR":
                    cantidad, de, a = "1", "EUR", "USD"
                else:
                    cantidad, de, a = "1", "EUR", cod
        valor = a_numero(cantidad) if not re.match(r"[\d.,]+$", cantidad) else float(cantidad.replace(".", "").replace(",", "."))
        if valor is None:
            return None
        if de == a:
            return Respuesta("Es la misma moneda.")
        d = _json(f"https://api.frankfurter.dev/v1/latest?from={de}&to={a}", cache=3600)
        tasa = d["rates"][a]
        fecha = dt.date.fromisoformat(d["date"])
        singular = {"euros": "euro", "dólares": "dólar", "libras": "libra", "yenes": "yen", "francos suizos": "franco suizo"}
        nombre_de = NOMBRE_MONEDA.get(de, de)
        if valor == 1:
            nombre_de = singular.get(nombre_de, nombre_de)
        return Respuesta(f"{num(valor)} {nombre_de} {'es' if valor == 1 else 'son'} {num(valor * tasa)} {NOMBRE_MONEDA.get(a, a)}, "
                         f"al cambio oficial del Banco Central Europeo del {fecha.day} de {MESES[fecha.month - 1]}.")

    # ------------------------------------------------------------ criptomonedas
    def _cripto(self, t: str, peticion: str) -> Respuesta | None:
        m = re.search(r"\b(" + "|".join(CRIPTO) + r")\b", t)
        if not m or not re.search(r"\b(a cuanto|cuanto vale|cuanto esta|precio|cotiza\w*|como esta|valor)\b", t):
            return None
        ident = CRIPTO[m.group(1)]
        d = _json(f"https://api.coingecko.com/api/v3/simple/price?ids={ident}&vs_currencies=eur&include_24hr_change=true",
                  cache=120)[ident]
        cambio = d.get("eur_24h_change")
        extra = f", {'sube' if cambio >= 0 else 'baja'} un {num(abs(cambio), 1)} % en 24 horas" if cambio is not None else ""
        return Respuesta(f"El {m.group(1)} está a {num(d['eur'], 2 if d['eur'] < 100 else 0)} euros{extra}. "
                         "Es solo información, no un consejo de inversión.")

    # ------------------------------------------------------------ luz
    def _luz(self, t: str, peticion: str) -> Respuesta | None:
        if not re.search(r"\b(luz|electricidad|kilovatio|kwh|pvpc)\b", t) or \
                not re.search(r"\b(precio|cuesta|cuanto|barata|cara|vale|tarifa|hora)\b", t) or \
                re.search(r"\b(enciende|apaga|pon la luz|velocidad)\b", t):
            return None
        dia = dt.date.today() + dt.timedelta(days=1 if re.search(r"\bmanana\b", t) else 0)
        url = ("https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real?" + urllib.parse.urlencode(
            {"start_date": f"{dia}T00:00", "end_date": f"{dia}T23:59", "time_trunc": "hour"}))
        try:
            d = _json(url, cache=1800)
        except OSError:
            return Respuesta("Red Eléctrica todavía no ha publicado los precios de mañana (salen hacia las 20:30)."
                             if dia != dt.date.today() else "No he podido consultar el precio de la luz ahora mismo.")
        serie = next((i for i in d.get("included", []) if i.get("type") == "PVPC"), None)
        if not serie:
            return Respuesta("No encuentro el precio regulado de la luz para ese día.")
        horas = [(dt.datetime.fromisoformat(v["datetime"]).hour, v["value"] / 1000) for v in serie["attributes"]["values"]]
        cuando = "mañana" if dia != dt.date.today() else "hoy"
        barata = sorted(horas, key=lambda h: h[1])[:3]
        cara = max(horas, key=lambda h: h[1])
        media = sum(p for _, p in horas) / len(horas)
        texto = (f"El precio regulado de la luz {cuando} va de {num(barata[0][1], 3)} a {num(cara[1], 3)} euros el "
                 f"kilovatio hora, con una media de {num(media, 3)}. Lo más barato: a las "
                 + ", ".join(f"{h}:00" for h, _ in sorted(barata)) + f". Lo más caro, a las {cara[0]}:00.")
        if cuando == "hoy":
            ahora = dt.datetime.now().hour
            p = next((p for h, p in horas if h == ahora), None)
            if p is not None:
                texto = f"Ahora mismo está a {num(p, 3)} euros el kilovatio hora. " + texto
        return Respuesta(texto)

    # ------------------------------------------------------------ carburantes
    def _carburantes(self, t: str, peticion: str) -> Respuesta | None:
        m = re.search(r"\b(gasolina 9[58]|gasolina|diesel|gasoil|gasoleo|glp|autogas)\b", t)
        if not m or not re.search(r"\b(precio|barat\w*|cuesta|cuanto|donde|gasolinera\w*|esta)\b", t):
            return None
        campo = CARBURANTES[m.group(1)]
        mc = re.search(r"\ben ([a-zñ ]{3,40})$", t)
        ciudad = (con_tildes(peticion, mc.group(1)) or mc.group(1)) if mc else leer_config().get("ciudad")
        if not ciudad:
            return Respuesta("¿En qué ciudad? Dímelo así: dónde está el diésel más barato en Sevilla. "
                             "O dime «mi ciudad es…» y no tendrás que repetirlo.")
        base = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes"
        municipios = _json(f"{base}/Listados/Municipios/", timeout=40, cache=86400 * 7)
        clave = normalizar(ciudad)
        candidatos = [x for x in municipios if normalizar(x["Municipio"]) == clave] or \
            [x for x in municipios if normalizar(x["Municipio"]).startswith(clave)]
        if not candidatos:
            return Respuesta(f"No encuentro el municipio {ciudad} en la lista del Ministerio.")
        mun = candidatos[0]
        d = _json(f"{base}/EstacionesTerrestres/FiltroMunicipio/{mun['IDMunicipio']}", timeout=40, cache=1800)
        precios = []
        for e in d.get("ListaEESSPrecio", []):
            p = (e.get(campo) or "").replace(",", ".")
            if p:
                precios.append((float(p), e.get("Rótulo", "").title(), e.get("Dirección", "").title()))
        if not precios:
            return Respuesta(f"No hay precios de {m.group(1)} en {mun['Municipio']} ahora mismo.")
        precios.sort()
        nombre = {"diesel": "Diésel", "gasoil": "Gasoil", "gasoleo": "Gasóleo", "glp": "Autogás (GLP)",
                  "autogas": "Autogás"}.get(m.group(1), m.group(1).capitalize())
        texto = (f"{nombre} en {mun['Municipio']}: la más barata es {precios[0][1]}, en "
                 f"{precios[0][2]}, a {num(precios[0][0], 3)} euros el litro.")
        if len(precios) > 2:
            texto += (f" La siguiente, {precios[1][1]} a {num(precios[1][0], 3)}. La más cara está a "
                      f"{num(precios[-1][0], 3)}. Hay {len(precios)} gasolineras con ese combustible.")
        return Respuesta(texto)

    # ------------------------------------------------------------ aire y polen
    def _aire(self, t: str, peticion: str) -> Respuesta | None:
        polen = bool(re.search(r"\bpolen\b|\balergi\w*\b", t))
        if not polen and not re.search(r"\b(calidad del aire|contaminacion|como esta el aire|que tal (esta )?el aire)\b", t):
            return None
        mc = re.search(r"\ben ([a-zñ ]{3,40})$", t)
        g = lugar(con_tildes(peticion, mc.group(1)) if mc else None)
        if not g:
            return Respuesta("¿De qué ciudad? Dime «mi ciudad es…» y te lo digo siempre.")
        d = _json("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode({
            "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto",
            "current": "european_aqi,pm2_5,pm10,ozone,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen"}),
            cache=1800)["current"]
        aqi = d.get("european_aqi")
        nivel = ("buena" if aqi < 20 else "aceptable" if aqi < 40 else "regular" if aqi < 60 else "mala" if aqi < 80
                 else "muy mala") if aqi is not None else "desconocida"
        texto = f"En {g['name']} la calidad del aire es {nivel} (índice europeo {round(aqi) if aqi is not None else '?'})."
        if polen:
            nombres = {"alder_pollen": "aliso", "birch_pollen": "abedul", "grass_pollen": "gramíneas",
                       "mugwort_pollen": "artemisa", "olive_pollen": "olivo", "ragweed_pollen": "ambrosía"}
            altos = [(nombres[k], v) for k, v in d.items() if k in nombres and v is not None and v >= 10]
            texto += (" Polen: " + ", ".join(f"{n} {round(v)} granos por metro cúbico" for n, v in
                                              sorted(altos, key=lambda x: -x[1])) + "." if altos else
                      " De polen está tranquilo ahora mismo.")
        return Respuesta(texto)

    # ------------------------------------------------------------ sol
    def _sol(self, t: str, peticion: str) -> Respuesta | None:
        sale = re.search(r"\b(amanece|sale el sol|amanecer|salida del sol)\b", t)
        pone = re.search(r"\b(anochece|se pone el sol|atardece|atardecer|puesta de sol|puesta del sol|oscurece)\b", t)
        if not (sale or pone) or not re.search(r"\b(hora|cuando|que hora)\b", t):
            return None
        mc = re.search(r"\ben ([a-zñ ]{3,40})$", t)
        g = lugar(con_tildes(peticion, mc.group(1)) if mc else None)
        if not g:
            return Respuesta("¿De qué ciudad? Dime «mi ciudad es…» y te lo digo siempre.")
        i = 1 if re.search(r"\bmanana\b", t) else 0
        d = _json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "forecast_days": 2,
            "daily": "sunrise,sunset,daylight_duration"}), cache=3600)["daily"]
        sr, ss = d["sunrise"][i][11:16], d["sunset"][i][11:16]
        luz = d["daylight_duration"][i] / 3600
        cuando = "Mañana" if i else "Hoy"
        partes = []
        if sale or not pone:
            partes.append(f"amanece a las {sr}")
        if pone or not sale:
            partes.append(f"se pone el sol a las {ss}")
        return Respuesta(f"{cuando} en {g['name']} " + " y ".join(partes)
                         + f"; {int(luz)} horas y {round((luz % 1) * 60)} minutos de luz.")

    # ------------------------------------------------------------ Wikipedia
    def _wikipedia(self, t: str, peticion: str) -> Respuesta | None:
        m = re.match(r"^(?:busca(?:me)? en (?:la )?wikipedia|que dice (?:la )?wikipedia (?:de|sobre)|wikipedia)\s+(.+)$", t)
        if not m:
            return None
        tema = (con_tildes(peticion, m.group(1)) or m.group(1)).strip(" .")
        b = _json("https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": tema, "srlimit": 1, "format": "json"}), cache=86400)
        hits = b.get("query", {}).get("search") or []
        if not hits:
            return Respuesta(f"La Wikipedia no tiene nada sobre {tema}.")
        titulo = hits[0]["title"]
        d = _json("https://es.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(titulo.replace(" ", "_")),
                  cache=86400)
        extracto = d.get("extract") or ""
        frases = re.split(r"(?<=[.!?])\s+", extracto)
        return Respuesta(f"Según la Wikipedia, {' '.join(frases[:3])}" if extracto else f"Encuentro «{titulo}», pero sin resumen.")

    # ------------------------------------------------------------ velocidad de internet (Cloudflare, sin claves)
    def _velocidad(self, t: str, peticion: str) -> Respuesta | None:
        if not re.search(r"\b(velocidad|test|prueba)\b.*\b(internet|conexion|wifi|fibra|red)\b"
                         r"|\bcomo (va|anda|esta) (el |la )?(internet|conexion|wifi|fibra)\b|\bspeed ?test\b", t):
            return None
        import time as _t
        import urllib.request as _u
        base = "https://speed.cloudflare.com"
        ping = []
        for _ in range(4):
            t0 = _t.perf_counter()
            _u.urlopen(_u.Request(f"{base}/__down?bytes=0", headers={"User-Agent": "Athena"}), timeout=10).read()
            ping.append((_t.perf_counter() - t0) * 1000)
        bajada = []
        for tam in (2_000_000, 10_000_000, 25_000_000):
            t0 = _t.perf_counter()
            n = len(_u.urlopen(_u.Request(f"{base}/__down?bytes={tam}", headers={"User-Agent": "Athena"}), timeout=60).read())
            dur = _t.perf_counter() - t0
            bajada.append(n * 8 / dur / 1e6)
            if dur > 8:                                   # conexión lenta: no seguir gastando
                break
        datos = b"0" * 5_000_000
        t0 = _t.perf_counter()
        _u.urlopen(_u.Request(f"{base}/__up", data=datos, headers={"User-Agent": "Athena",
                                                                    "Content-Type": "application/octet-stream"}),
                   timeout=60).read()
        subida = len(datos) * 8 / (_t.perf_counter() - t0) / 1e6
        b, p = max(bajada), sorted(ping)[len(ping) // 2]
        valor = "muy buena" if b >= 100 else "buena" if b >= 30 else "justa" if b >= 10 else "lenta"
        return Respuesta(f"Internet va {valor}: {num(b, 0)} megas de bajada, {num(subida, 0)} de subida y "
                         f"{num(p, 0)} milisegundos de respuesta.")

    # ------------------------------------------------------------ estación espacial
    def _iss(self, t: str, peticion: str) -> Respuesta | None:
        if not re.search(r"\b(estacion espacial|la iss)\b", t) or not re.search(r"\b(donde|por donde|pasa|esta)\b", t):
            return None
        d = _json("https://api.wheretheiss.at/v1/satellites/25544", cache=20)
        lat, lon = d["latitude"], d["longitude"]
        try:
            g = _json(f"https://api.wheretheiss.at/v1/coordinates/{lat:.3f},{lon:.3f}", cache=20)
            sitio = g.get("country_code") or g.get("timezone_id") or ""
        except OSError:
            sitio = ""
        hemis = f"{num(abs(lat), 1)} grados {'norte' if lat >= 0 else 'sur'} y {num(abs(lon), 1)} {'este' if lon >= 0 else 'oeste'}"
        return Respuesta(f"La Estación Espacial Internacional va ahora sobre {hemis}"
                         + (f" (zona {sitio.replace('_', ' ')})" if sitio and sitio != "??" else "")
                         + f", a {round(d['altitude'])} kilómetros de altura y {num(d['velocity'] / 1000, 1)} mil "
                         "kilómetros por hora.")

    def _ayuda(self, t: str, peticion: str) -> Respuesta | None:
        if not re.search(r"\bque (datos|apis|cosas) (puedes|sabes) (consultar|mirar)\b|\bque apis tienes\b", t):
            return None
        return Respuesta("Puedo consultarte al momento: festivos, cambio de divisas, criptomonedas, el precio de la luz "
                         "por horas, la gasolinera más barata, la calidad del aire y el polen, a qué hora amanece y "
                         "anochece, la Wikipedia, dónde está la estación espacial y la velocidad de internet. Además del tiempo "
                         "y las noticias.")
