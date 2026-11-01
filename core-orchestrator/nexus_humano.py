"""
Que lo que escribe el personaje suene a persona y no a texto de IA (método «humanizer», basado en la guía de
Wikipedia «Signs of AI writing», adaptado al español de España y a redes sociales).

  humanizar(texto, cerebro, tono, tipo) → reescribe con la IA siguiendo las reglas, limpia a mano lo que quede
                                          y repite una vez si aún se nota.
  huellas(texto) → lista de rasgos de «texto de IA» que quedan (para comprobar y para el panel).

Tipos: «caption», «guion» (se dice en voz alta), «bio», «respuesta» (a un comentario), «post» (X, Facebook…).
"""

from __future__ import annotations

import re

# Palabras y giros que delatan texto de IA en español (y los que se cuelan en inglés)
HUELLAS = [
    r"\bsin duda\b", r"\ben definitiva\b", r"\bcabe (destacar|mencionar|resaltar)\b", r"\bes (importante|crucial|clave) "
    r"(destacar|mencionar|recordar|tener en cuenta)\b", r"\bsumérge(te|nos)\b", r"\badéntrate\b", r"\bdescubre\b",
    r"\bno (solo|sólo) .{1,60}?\bsino (también|que)\b", r"\ben el (fascinante |apasionante )?mundo de\b",
    r"\bfascinante\b", r"\bapasionante\b", r"\bviaje\b", r"\bpotencia(r|ndo)?\b", r"\bcrucial\b", r"\bvibrante\b",
    r"\btestimonio de\b", r"\beleva(r|ndo)? (tu|tus|el|la)\b", r"\bdesbloquea(r)?\b", r"\brevolucionari[oa]\b",
    r"\bpanorama\b", r"\ben resumen\b", r"\ben conclusión\b", r"\bexplora(r|mos)?\b", r"\bemocionante\b",
    r"\bimprescindible\b", r"\binigualable\b", r"\bsin igual\b", r"\bal siguiente nivel\b", r"\bla clave (está|es)\b",
    r"\bjuega un papel\b", r"\bpapel (fundamental|crucial|clave)\b", r"\bdel futuro\b", r"\bespero que (te|os) (sirva|guste)\b",
    r"\b¡?vamos allá\b", r"\bsin más preámbulos\b", r"\bdicho esto\b", r"\bademás,", r"\basimismo\b", r"\bpor otro lado\b",
    r"\bmagia\b", r"\bdelve\b", r"\btapestry\b", r"\bunlock\b", r"\bgame[- ]?changer\b", r"\bembark\b",
]
_HUELLAS = [re.compile(h, re.I) for h in HUELLAS]

REGLAS = """Reescribe el texto para que suene a una persona real escribiendo en redes, no a una IA.
Quita: frases de relleno y de anuncio (fascinante, increíble viaje, descubre, sumérgete, al siguiente nivel, sin duda,
cabe destacar, en definitiva, la clave está en, juega un papel fundamental); los «no solo… sino también»; las listas
de tres cosas porque sí; los finales positivos genéricos; las preguntas retóricas de manual («¿Te imaginas…?»);
los sinónimos rebuscados en lugar de repetir la palabra normal; las rayas largas (—); las comillas curvas; el
exceso de emojis (máximo 1 o 2, y solo si pegan); las mayúsculas en cada palabra; los saludos de anuncio.
Pon: frases de largo distinto, alguna muy corta; opiniones de verdad; detalles concretos en vez de generalidades;
humor seco si encaja; palabras normales de una chica de veintitantos de España (sin forzar jerga). Puede haber
alguna frase sin verbo o algo de desorden, como se escribe de verdad. Mantén el sentido y los datos.
No menciones la IA. Devuelve SOLO el texto final, sin comillas ni explicaciones."""

POR_TIPO = {
    "caption": "Es el texto de una publicación de TikTok/Instagram: 1-3 frases, gancho en la primera línea.",
    "guion": "Se va a decir en voz alta en un vídeo: frases cortas, ritmo hablado, sin emojis ni hashtags.",
    "bio": "Es una biografía de perfil: corta, con personalidad, sin listas de adjetivos.",
    "respuesta": "Es una respuesta a un comentario: natural, breve (1-2 frases), como contesta una creadora a su gente.",
    "post": "Es un post de X o Facebook: directo, una idea, sin parecer un anuncio.",
}


def huellas(texto: str) -> list[str]:
    encontradas = [m.group(0) for h in _HUELLAS for m in [h.search(texto or "")] if m]
    if "—" in (texto or ""):
        encontradas.append("raya larga (—)")
    emojis = re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", texto or "")
    if len(emojis) > 2:
        encontradas.append(f"{len(emojis)} emojis")
    return encontradas


def limpiar(texto: str, tipo: str = "caption") -> str:
    """Arreglos que no necesitan IA."""
    t = (texto or "").strip().strip('"').strip("«»").strip()
    t = t.replace("—", ", ").replace("–", ", ").replace("“", '"').replace("”", '"').replace("’", "'")
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*,", ",", t)
    if tipo == "guion":                                    # en voz alta: ni emojis ni hashtags
        t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
        t = re.sub(r"#\w+", "", t)
    else:                                                  # máximo 2 emojis
        n = 0

        def quitar(m):
            nonlocal n
            n += 1
            return m.group(0) if n <= 2 else ""
        t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", quitar, t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def humanizar(texto: str, cerebro, tono: str = "", tipo: str = "caption", limite: int | None = None) -> str:
    if not texto or cerebro is None:
        return limpiar(texto, tipo)
    actual = texto
    for _ in range(2):
        try:
            r = cerebro.chat([{"role": "system", "content": REGLAS + "\n" + POR_TIPO.get(tipo, "")
                               + (f"\nVoz del personaje: {tono}" if tono else "")
                               + (f"\nMáximo {limite} caracteres." if limite else "")},
                              {"role": "user", "content": actual}], max_tokens=700, temperatura=0.85, timeout=60)
        except Exception:
            break
        actual = limpiar(r, tipo)
        if not huellas(actual):
            break
    if limite and len(actual) > limite:
        actual = actual[: limite - 1].rsplit(" ", 1)[0] + "…"
    return actual
