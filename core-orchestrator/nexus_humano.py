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
    r"\baquí tienes\b", r"\ben serio\b", r"(^|[.!?]\s*)vale,", r"\bsin drama\b", r"\blisto para\b",
    r"\bmagia\b", r"\bdelve\b", r"\btapestry\b", r"\bunlock\b", r"\bgame[- ]?changer\b", r"\bembark\b",
]
_HUELLAS = [re.compile(h, re.I) for h in HUELLAS]

REGLAS = """Reescribe el texto para que suene a una persona real escribiendo en redes, no a una IA.
Quita: frases de relleno y de anuncio (fascinante, increíble viaje, descubre, sumérgete, al siguiente nivel, sin duda,
cabe destacar, en definitiva, la clave está en, juega un papel fundamental); los «no solo… sino también»; las listas
de tres cosas porque sí; los finales positivos genéricos; las preguntas retóricas de manual («¿Te imaginas…?»);
los sinónimos rebuscados en lugar de repetir la palabra normal; las rayas largas (—); las comillas curvas; el
exceso de emojis (máximo 1 o 2, y solo si pegan); las mayúsculas en cada palabra; los saludos de anuncio.
No metas muletillas de relleno («vale», «aquí tienes», «en serio») si no aportan; como mucho una.
Pon: frases de largo distinto, alguna muy corta; opiniones de verdad; detalles concretos en vez de generalidades;
humor seco si encaja; habla coloquial de una chica de veintitantos de Sevilla hablando con sus seguidores: tutea,
expresiones de aquí con naturalidad y variadas (qué pasada, me flipa, menudo día, tal cual, ni tan mal, de locos,
os lo juro, venga), como mucho una o dos por texto y nunca la misma dos veces seguidas; reacciones de persona
(«uff», «jajaja», «madre mía») cuando pegue; nada que suene a nota de prensa. Puede haber
alguna frase sin verbo o algo de desorden, como se escribe de verdad. Mantén el sentido y los datos.
Ella es una chica: todo en femenino (lista, cansada, contenta), nunca «listo» ni «cansado» hablando de sí misma.
No menciones la IA ni digas nunca que no lo eres (nada de «soy real», «no soy una IA»). Devuelve SOLO el texto final, sin comillas ni explicaciones."""

POR_TIPO = {
    "caption": "Es el texto de una publicación de TikTok/Instagram: 1-3 frases, gancho en la primera línea.",
    "guion": "Se va a decir en voz alta en un vídeo, como una charla a cámara: ritmo hablado y fluido, frases que se "
             "enlazan con naturalidad (pues, total, que, encima, al final), alguna pausa o comentario de pasada; nada "
             "telegráfico, nada de frases sueltas de anuncio. Sin emojis ni hashtags.",
    "bio": "Es una biografía de perfil: corta, con personalidad, sin listas de adjetivos.",
    "respuesta": "Es una respuesta a un comentario: como cuando contestas a alguien por chat, cercana y natural, 1-2 "
                 "frases, reaccionando a lo que dice esa persona en concreto; a veces con una pregunta de vuelta.",
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


_HABLA_DE_IA = re.compile(r"(?i)\b(ia|i\.a\.|inteligencia artificial|una ai|bot|robot|androide|humana de verdad|"
                         r"persona real|soy real)\b")


_NIEGA_IA = re.compile(r"(?i)\b(no\s+(soy|es|somos)\s+(una?\s+)?(ia|i\.a\.|bot|robot|inteligencia artificial)|"
                       r"soy\s+(real|humana|una persona|de carne)|no\s+una?\s+(ia|bot))\b")


def sin_ia(texto: str, solo_negaciones: bool = False) -> str:
    """Nunca niega ser una IA ni habla de ello en su contenido: se quita la frase entera que lo mencione
    (la transparencia va en la marca de la bio y en la etiqueta oficial de cada red)."""
    partes = re.split(r"(?<=[.!?…])\s+|(?<=;)\s+", texto or "")
    patron = _NIEGA_IA if solo_negaciones else _HABLA_DE_IA
    quedan = [p for p in partes if not patron.search(p)]
    if len(quedan) == len(partes):
        return texto
    t = " ".join(quedan).strip()
    return re.sub(r"[;,]\s*$", ".", t)


def limpiar(texto: str, tipo: str = "caption") -> str:
    """Arreglos que no necesitan IA."""
    t = (texto or "").strip().strip('"').strip("«»").strip()
    if tipo == "respuesta":                                # si le preguntan de verdad, lo reconoce: solo se quita negarlo
        t = sin_ia(t, solo_negaciones=True)
    elif tipo != "bio":                                    # la bio sí lleva su marca «✦ creadora digital IA»
        t = sin_ia(t)
    t = t.replace("—", ", ").replace("–", ", ").replace("“", '"').replace("”", '"').replace("’", "'")
    t = re.sub(r"(?i)\s*\baquí tienes\b[.!]?", "", t)                # muletillas de asistente
    t = re.sub(r"(?i)\blisto para\b", lambda m: "Lista para" if m.group(0)[0] == "L" else "lista para", t)
    t = re.sub(r"(?i)(?:^|(?<=[\s,.!?¡¿]))vale(?!\s+(?:la|lo|las|los|más|mucho|poco|de|por|para|un|una|\d))[,.!…]*",
               "", t)                                          # la muletilla «vale» suelta (no «vale la pena»)
    t = re.sub(r"(?i)\ben serio\b[,.!]*", "", t)
    t = re.sub(r"(?i)#(ai|ia|aiart|aiinfluencer|virtualinfluencer|influencervirtual|aigenerated|digitalcreator)\b", "", t)
    t = re.sub(r"\s+([,.!?…])", r"\1", t)
    t = re.sub(r"([,.!?])\1+", r"\1", t)
    t = re.sub(r"^[\s,.;:]+|[\s,;:]+$", "", t)
    t = re.sub(r"([.!?]\s+)([a-záéíóúñ])", lambda m: m.group(1) + m.group(2).upper(), t)   # mayúscula tras punto
    if t[:1].islower():
        t = t[0].upper() + t[1:]
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
    vistos = set()                                         # sin hashtags repetidos ni en inglés de relleno

    def tag(m):
        k = m.group(0).lower()
        if k in vistos or k in ("#smile", "#camera", "#photo", "#selfie", "#bookshelf", "#room"):
            return ""
        vistos.add(k)
        return m.group(0)
    t = re.sub(r"#\w+", tag, t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _copia_tono(texto: str, tono: str) -> bool:
    t = (texto or "").lower()
    trozos = [x.strip().lower() for x in re.split(r"[,.;:()]", tono or "") if len(x.strip()) >= 8]
    return any(x in t for x in trozos)


def humanizar(texto: str, cerebro, tono: str = "", tipo: str = "caption", limite: int | None = None) -> str:
    if not texto or cerebro is None:
        return limpiar(texto, tipo)
    actual = texto
    for _ in range(2):
        try:
            r = cerebro.chat([{"role": "system", "content": REGLAS + "\n" + POR_TIPO.get(tipo, "")
                               + (f"\nAsí habla el personaje (es una guía de estilo: NO la copies ni la describas "
                                  f"en el texto): {tono}" if tono else "")
                               + (f"\nMáximo {limite} caracteres." if limite else "")},
                              {"role": "user", "content": actual}], max_tokens=700, temperatura=0.85, timeout=60)
        except Exception:
            break
        nuevo = limpiar(r, tipo)
        if _copia_tono(nuevo, tono):                      # ha metido la descripción del estilo en el texto
            continue
        actual = nuevo
        if not huellas(actual):
            break
    if limite and len(actual) > limite:
        actual = actual[: limite - 1].rsplit(" ", 1)[0] + "…"
    return actual
