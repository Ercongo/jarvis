"""
Pantallas: dónde va la interfaz del asistente y dónde se trabaja, en cualquier PC.

  - Con dos o más pantallas, la interfaz va en una para ella sola (la «dedicada») y las ventanas que se abran se
    llevan a la de trabajo. Por defecto: en un portátil, la interna para trabajar y la externa para la interfaz;
    en un sobremesa, la principal para trabajar y otra para la interfaz.
  - Con una sola pantalla, la interfaz va a pantalla completa, sin quedarse siempre encima, y nada se mueve.

Ajustes del perfil ("pantallas"):
  "interfaz": "auto" | nombre de la salida (HDMI-1, DP-2…) | "ventana" (sin pantalla completa)
  "trabajo":  "auto" | nombre de la salida
  "colocar":  "no" | "izquierda" | "derecha" | "arriba" | "abajo"   (posición del monitor de la interfaz)

Desde un script:  eval "$(python3 pantallas.py --shell)"
  → INTERFAZ, GEO_INTERFAZ, X_INTERFAZ, Y_INTERFAZ, TRABAJO, GEO_TRABAJO, DEDICADA (1/0), COLOCAR, VENTANA (1/0)
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass

from perfil import perfil


@dataclass
class Salida:
    nombre: str
    principal: bool
    interna: bool
    ancho: int = 0
    alto: int = 0
    x: int = 0
    y: int = 0

    @property
    def geo(self) -> str:
        return f"{self.ancho}x{self.alto}+{self.x}+{self.y}" if self.ancho else ""

    def contiene(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.ancho and self.y <= py < self.y + self.alto


def listar() -> list[Salida]:
    """Las pantallas conectadas, según xrandr."""
    try:
        texto = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    fuera = []
    for linea in texto.splitlines():
        m = re.match(r"^(\S+) connected( primary)?(?: (\d+)x(\d+)\+(\d+)\+(\d+))?", linea)
        if m:
            s = Salida(m.group(1), bool(m.group(2)), bool(re.match(r"(eDP|LVDS|DSI)", m.group(1))))
            if m.group(3):
                s.ancho, s.alto, s.x, s.y = (int(m.group(i)) for i in range(3, 7))
            fuera.append(s)
    return fuera


@dataclass
class Plan:
    interfaz: Salida | None
    trabajo: Salida | None
    dedicada: bool          # la interfaz tiene una pantalla para ella sola
    colocar: str            # "no" o la posición del monitor de la interfaz respecto al de trabajo
    ventana: bool           # la interfaz en una ventana normal, no a pantalla completa


def plan(salidas: list[Salida] | None = None) -> Plan:
    ajustes = perfil().get("pantallas") or {}
    pedido_i = str(ajustes.get("interfaz") or "auto")
    pedido_t = str(ajustes.get("trabajo") or "auto")
    colocar = str(ajustes.get("colocar") or "no")
    salidas = listar() if salidas is None else salidas
    if not salidas:
        return Plan(None, None, False, "no", pedido_i == "ventana")
    por_nombre = {s.nombre: s for s in salidas}

    trabajo = por_nombre.get(pedido_t)
    if trabajo is None:
        trabajo = (next((s for s in salidas if s.interna), None) or next((s for s in salidas if s.principal), None)
                   or salidas[0])
    interfaz = por_nombre.get(pedido_i)
    if interfaz is None:
        otras = [s for s in salidas if s.nombre != trabajo.nombre]
        interfaz = otras[0] if otras else trabajo
    if interfaz.nombre == trabajo.nombre and len(salidas) > 1 and pedido_t == "auto":
        trabajo = next(s for s in salidas if s.nombre != interfaz.nombre)   # pidió la interfaz en la de trabajo
    dedicada = interfaz.nombre != trabajo.nombre and pedido_i != "ventana"
    return Plan(interfaz, trabajo, dedicada, colocar if dedicada else "no", pedido_i == "ventana")


def trabajo_geo() -> tuple[int, int, int, int] | None:
    """(ancho, alto, x, y) de la pantalla de trabajo, solo si la interfaz tiene otra para ella sola."""
    p = plan()
    if not (p.dedicada and p.trabajo and p.trabajo.ancho):
        return None
    t = p.trabajo
    return t.ancho, t.alto, t.x, t.y


def geometrias() -> dict[str, str]:
    """{'trabajo': 'WxH+X+Y', 'interfaz': …} (las claves que usa la visión)."""
    p = plan()
    fuera = {}
    if p.trabajo and p.trabajo.geo:
        fuera["trabajo"] = p.trabajo.geo
    if p.dedicada and p.interfaz and p.interfaz.geo:
        fuera["interfaz"] = p.interfaz.geo
    return fuera


def shell() -> str:
    p = plan()
    i, t = p.interfaz, p.trabajo
    valores = {
        "INTERFAZ": i.nombre if i else "", "GEO_INTERFAZ": i.geo if i else "",
        "X_INTERFAZ": str(i.x if i else 0), "Y_INTERFAZ": str(i.y if i else 0),
        "TRABAJO": t.nombre if t else "", "GEO_TRABAJO": t.geo if t else "",
        "DEDICADA": "1" if p.dedicada else "0", "COLOCAR": p.colocar, "VENTANA": "1" if p.ventana else "0",
    }
    return "\n".join(f"{k}={shlex.quote(v)}" for k, v in valores.items())


if __name__ == "__main__":
    import sys
    if "--shell" in sys.argv:
        print(shell())
    else:
        p = plan()
        for s in listar():
            papel = ("interfaz" if p.interfaz and s.nombre == p.interfaz.nombre else "") + \
                    (" + trabajo" if p.trabajo and s.nombre == p.trabajo.nombre else "")
            print(f"{s.nombre:10} {s.geo:20} {'interna' if s.interna else 'externa'}"
                  f"{' principal' if s.principal else ''}  → {papel.strip(' +') or '-'}")
        print(f"interfaz dedicada: {'sí' if p.dedicada else 'no'} · colocar: {p.colocar}")
