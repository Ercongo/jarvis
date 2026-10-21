"""
Modo «no molestar»: Jarvis sigue escuchando y contesta cuando le llamas, pero no habla por su cuenta
(bienvenidas, avisos de correo, novedades…). Los recordatorios y temporizadores sí suenan.

  "no me molestes", "silencio", "apágate" (a Jarvis, no al ordenador), "descansa", "no me molestes hasta las 6"
  "ya puedes hablar", "despierta", "vuelve" → normal.
Se quita solo a la hora pedida o, si no se dijo, a las 8 horas.
"""

from __future__ import annotations

import datetime as dt
import re
import time

from herramientas import normalizar
from sistema import Respuesta

URGENTE = re.compile(r"(?i)recordatorio|te recuerdo|temporizador|alarma|¿lo confirmas|confirma")


class NoMolestar:
    def __init__(self):
        self.hasta = 0.0

    @property
    def activo(self) -> bool:
        return time.time() < self.hasta

    def permite(self, texto: str) -> bool:
        """¿Se puede decir esto en voz alta por iniciativa propia?"""
        return not self.activo or bool(URGENTE.search(texto or ""))

    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)
        if re.fullmatch(r"(?:ya )?(?:puedes|podeis) (?:hablar|volver)|despierta|despiertate|vuelve|"
                        r"(?:quita|desactiva|sal del) (?:el )?(?:modo )?(?:no molestar|silencio)|ya me puedes molestar",
                        t):
            if not self.activo:
                return Respuesta("Estaba atento igualmente. Dime.")
            self.hasta = 0.0
            return Respuesta("De vuelta. Te vuelvo a avisar de todo.")
        m = re.fullmatch(r"(?:no me molestes|no molestes|silencio|calla(?:te)?|apagate|descansa|a dormir|"
                         r"(?:activa|pon) (?:el )?(?:modo )?(?:no molestar|silencio))"
                         r"(?: (?:hasta (?:las |la )?(\d{1,2})(?:[: ](\d{2}))?(?: de la (manana|tarde|noche))?|"
                         r"(?:durante |por )?(?:una|(\d+)) horas?))?", t)
        if not m:
            return None
        ahora = dt.datetime.now()
        if m.group(1):
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            if m.group(3) in ("tarde", "noche") and h < 12:
                h += 12
            fin = ahora.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
            if fin <= ahora:
                fin += dt.timedelta(days=1)
        elif m.group(4) or "una hora" in t:
            fin = ahora + dt.timedelta(hours=int(m.group(4) or 1))
        else:
            fin = ahora + dt.timedelta(hours=8)
        self.hasta = fin.timestamp()
        return Respuesta(f"Me quedo en silencio hasta las {fin:%H:%M}. Si me llamas, te contesto; los recordatorios "
                         "sí te los diré.")
