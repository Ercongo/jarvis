"""
Frases variadas para que Jarvis no conteste siempre igual.

- frase("clave") elige una alternativa al azar sin repetir la última que usó.
- variar(texto) cambia las respuestas fijas de los módulos ("Hecho.", "Abriendo X.") por otras equivalentes.
"""

from __future__ import annotations

import random
import re

_ultima: dict[str, str] = {}

FRASES = {
    "si": ["¿Sí?", "Dime.", "Te escucho.", "¿Qué necesitas?", "A tus órdenes.", "¿En qué te ayudo?", "Aquí estoy."],
    "de_nada": ["De nada. Aquí estaré.", "Para eso estoy.", "Cuando quieras.", "A mandar.", "Encantado de ayudar.",
                "No hay de qué."],
    "en_linea": ["Todos los sistemas en línea.", "Sistemas operativos y listos.", "Todo en orden por aquí.",
                 "Ya estoy despierto y funcionando.", "Listo para lo que necesites.", "Arranque completado sin novedad."],
    "aviso_voz": ["Di Jarvis cuando me necesites.", "Llámame cuando quieras.", "Estaré atento.",
                  "Si me necesitas, di mi nombre."],
    "no_entiendo": ["No te he entendido bien, ¿me lo repites?", "Perdona, no lo he pillado. ¿Me lo dices otra vez?",
                    "No estoy seguro de qué me pides. ¿Puedes decirlo de otra forma?",
                    "Se me ha escapado. ¿Lo repites, por favor?"],
    "foto": ["Foto hecha.", "Clic. Ya la tengo.", "¡Sonríe! Hecho.", "Listo, foto guardada.", "Ya está la foto."],
    "te_veo": ["Sí, te veo.", "Sí, te tengo delante.", "Te veo perfectamente.", "Claro, ahí estás."],
    "no_te_veo": ["Ahora mismo no te veo. Ponte delante de la cámara.", "No te veo. ¿Estás frente a la pantalla?",
                  "No veo a nadie delante de la cámara."],
    "hola_de_nuevo": ["Hola de nuevo.", "Bienvenido de vuelta.", "Ya estás aquí otra vez.", "Qué bien, has vuelto."],
}

# Respuestas fijas de los módulos → alternativas. {0}, {1}… son los grupos del patrón.
VARIANTES = [
    (r"Hecho\.", ["Hecho.", "Listo.", "Ya está.", "Hecho, sin problema.", "Solucionado."]),
    (r"Abriendo (.+)\.", ["Abriendo {0}.", "Te abro {0}.", "Ahí tienes {0}.", "Marchando {0}.", "Abro {0}."]),
    (r"Volumen al (\S+) por ciento\.", ["Volumen al {0} por ciento.", "Ahora al {0} por ciento.",
                                        "Puesto al {0} por ciento.", "Volumen en {0}."]),
    (r"Ahí va\.", ["Ahí va.", "Dale caña.", "Sonando.", "Allá va."]),
    (r"Música parada\.", ["Música parada.", "Silencio.", "Paro la música.", "Música fuera."]),
    (r"Anotado\.", ["Anotado.", "Apuntado.", "Guardado en tus notas.", "Tomo nota."]),
    (r"Escrito\.", ["Escrito.", "Ya lo he escrito.", "Hecho, está escrito."]),
    (r"Captura guardada en (.+)\.", ["Captura guardada en {0}.", "Pantallazo hecho, está en {0}.",
                                     "Listo, la captura está en {0}."]),
]


def frase(clave: str, **datos) -> str:
    opciones = FRASES[clave]
    candidatas = [o for o in opciones if o != _ultima.get(clave)] or opciones
    elegida = random.choice(candidatas)
    _ultima[clave] = elegida
    from perfil import con_nombre
    return con_nombre(elegida.format(**datos) if datos else elegida)


def variar(texto: str) -> str:
    if not texto:
        return texto
    for patron, opciones in VARIANTES:
        m = re.fullmatch(patron, texto.strip())
        if m:
            candidatas = [o for o in opciones if o != _ultima.get(patron)] or opciones
            elegida = random.choice(candidatas)
            _ultima[patron] = elegida
            return elegida.format(*m.groups())
    return texto
