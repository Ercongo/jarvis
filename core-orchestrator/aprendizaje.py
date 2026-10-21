"""
Aprendizaje de Jarvis: atajos y correcciones que se guardan en ~/jarvis/aprendido.json.

Formas de enseñarle:
  "aprende que cuando diga modo cine, baja el volumen al 30 y abre netflix"
  "cuando te diga buenas noches, apaga el ordenador"
  "no, me refería a hazme una foto"      → corrige la última orden y la aprende
  "aprende que mi color favorito es el azul"  → es un dato: va a la memoria personal
Consultar y olvidar:
  "qué has aprendido"
  "olvida lo que aprendiste de modo cine" / "olvida todo lo aprendido"

Además, cuando no entiende una frase y la IA adivina la orden (por ejemplo "apme un a foto" → "hazme una foto"),
se apunta la equivalencia para entenderla a la primera la próxima vez.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from pathlib import Path

from herramientas import normalizar
from sistema import Respuesta, con_tildes

APRENDIDO = Path.home() / "jarvis" / "aprendido.json"

VERBOS = (r"abre|abreme|pon|ponme|baja|bajale|sube|subele|haz|hazme|busca|cierra|apaga|activa|desactiva|enciende|"
          r"dime|di|reproduce|para|limpia|lee|escribe|muestra|muestrame|ensena|ensename|recuerdame|silencia|"
          r"reinicia|suspende|vacia|actualiza|comprueba|calcula|convierte|toma|saca|sacame|cuentame")


def leer() -> list[dict]:
    try:
        return json.loads(APRENDIDO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def guardar(datos: list[dict]) -> None:
    APRENDIDO.parent.mkdir(parents=True, exist_ok=True)
    APRENDIDO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def limpiar(t: str) -> str:
    t = normalizar(t)
    t = re.sub(r"[,;:.!¡¿?\"']", " ", t)
    t = re.sub(r"^(jarvis|oye|por favor|venga)\s+", "", t)
    t = re.sub(r"\s+por favor$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def dividir(ordenes: str) -> list[str]:
    """'baja el volumen al 30 y abre netflix' → ['baja el volumen al 30', 'abre netflix']."""
    partes = re.split(rf"\s*(?:,|;|\by luego\b|\by despues\b|\bluego\b|\by(?=\s+(?:{VERBOS})\b))\s*", ordenes)
    return [p.strip(" ,.") for p in partes if p and p.strip(" ,.")]


class Aprendizaje:
    def __init__(self, log=print):
        self.log = log
        datos = leer()                                    # lo aprendido "solo" daba equivalencias erróneas: fuera
        buenos = [a for a in datos if a.get("origen") != "auto"]
        if len(buenos) != len(datos):
            guardar(buenos)
            log(f"aprendizaje: quitadas {len(datos) - len(buenos)} equivalencias automáticas")

    # ---------- aplicar lo aprendido
    def buscar(self, entrada: str) -> dict | None:
        t = limpiar(entrada)
        if not t:
            return None
        mejor, puntos = None, 0.0
        for a in leer():
            r = difflib.SequenceMatcher(None, t, a["cuando"]).ratio()
            minimo = 0.84 if a.get("origen") == "usuario" else 0.9
            if r >= minimo and r > puntos:
                mejor, puntos = a, r
        return mejor

    def reescribir(self, entrada: str, anterior: str | None) -> tuple[list[str], str] | None:
        """Si la frase es un atajo, una corrección o un dato, devuelve (órdenes a ejecutar, aviso para el registro)."""
        t = normalizar(entrada).strip()
        t_sin = re.sub(r"^(jarvis|oye)[ ,]+", "", t)

        # Corrección de la orden anterior: "no, me refería a X" / "quería decir X"
        m = re.match(r"^(?:no[ ,]+)?(?:me referia a|me refiero a|queria decir|quise decir|lo que queria es|"
                     r"te pedia que|te he pedido que|te he dicho que)\s+(.+)$", t_sin)
        if m:
            objetivo = m.group(1).strip(" .")
            if objetivo in ("eso", "esto", "nada", "otra cosa") or len(objetivo) < 4:
                return None
            if anterior and limpiar(anterior) and limpiar(anterior) != limpiar(objetivo):
                self.aprender(anterior, [objetivo], "correccion")
                return [con_tildes(entrada, objetivo)], f"corrección aprendida: «{anterior}» → «{objetivo}»"
            return [con_tildes(entrada, objetivo)], "corrección"

        # Un dato sobre ti: "aprende que mi hermana se llama Ana" (sin "cuando") → memoria personal
        m = re.match(r"^aprende(?:te)?\s+que\s+(?!cuando\b)(.+)$", t_sin)
        if m and not re.search(r"\bcuando (te )?(diga|digo|pida)\b", m.group(1)):
            return ["recuerda que " + con_tildes(entrada, m.group(1))], "dato para la memoria"

        a = self.buscar(entrada)
        if a:
            a["usos"] = a.get("usos", 0) + 1
            datos = [x if x["cuando"] != a["cuando"] else a for x in leer()]
            guardar(datos)
            return list(a["hacer"]), f"atajo aprendido «{a['cuando']}»"
        return None

    def aprender(self, cuando: str, hacer: list[str], origen: str) -> None:
        clave = limpiar(cuando)
        if not clave or not hacer:
            return
        if origen == "auto" and len(clave.split()) < 2:
            return                                        # una sola palabra suelta es demasiado ambigua
        datos = [a for a in leer() if a["cuando"] != clave]
        datos.append({"cuando": clave, "hacer": hacer, "origen": origen,
                      "fecha": dt.date.today().isoformat(), "usos": 0})
        guardar(datos[-300:])
        self.log(f"aprendido ({origen}): «{clave}» → {hacer}")

    # ---------- enseñar, consultar, olvidar
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        t = re.sub(r"^(jarvis|oye|por favor)[ ,]+", "", t)

        m = re.match(r"^(?:aprende(?:te)?(?: que)?|a partir de ahora|desde ahora|recuerda que)?[ ,]*"
                     r"cuando (?:te )?(?:diga|digo|pida|escriba)\s+(.+?)[ ,]+"
                     r"(?:(?:tienes que|debes|quiero que|entonces|significa|quiere decir|quiero decir|es)\s+)?"
                     rf"((?:{VERBOS})\b.+)$", t)
        if m:
            cuando = m.group(1).strip(" ,.\"'«»")
            hacer = dividir(m.group(2))
            if not hacer:
                return Respuesta("No he entendido qué tengo que hacer. Dímelo así: cuando diga modo cine, baja el volumen al 30.")
            self.aprender(cuando, [con_tildes(peticion, h) for h in hacer], "usuario")
            pasos = " y luego ".join(con_tildes(peticion, h) for h in hacer)
            return Respuesta(f"Aprendido. Cuando digas «{con_tildes(peticion, cuando)}», haré esto: {pasos}.")

        if re.search(r"\bque (has aprendido|te he ensenado|atajos tienes|sabes hacer de nuevo)\b|\blo que has aprendido\b", t):
            datos = [a for a in leer() if a.get("origen") in ("usuario", "correccion")]
            auto = len(leer()) - len(datos)
            if not datos and not auto:
                return Respuesta("Todavía no me has enseñado nada. Prueba: aprende que cuando diga modo cine, baja el volumen al 30.")
            partes = [f"«{a['cuando']}» significa {' y '.join(a['hacer'])}" for a in datos[-5:]]
            texto = (f"Me has enseñado {len(datos)} cosa{'s' if len(datos) != 1 else ''}. " + ". ".join(partes) + "."
                     if datos else "No me has enseñado atajos todavía.")
            if auto:
                texto += f" Además he aprendido solo a entender {auto} frase{'s' if auto != 1 else ''} que antes no entendía."
            return Respuesta(texto)

        m = re.match(r"^olvida\w*\s+(?:todo\s+)?(?:lo que (?:has aprendido|aprendiste|te ensene)|lo aprendido|el atajo)"
                     r"(?:\s+(?:de|sobre|con)\s+(.+))?$", t)
        if m:
            if not m.group(1):
                guardar([])
                return Respuesta("He borrado todo lo aprendido. Empezamos de cero.")
            clave = limpiar(m.group(1))
            datos = leer()
            restantes = [a for a in datos if difflib.SequenceMatcher(None, clave, a["cuando"]).ratio() < 0.75
                         and clave not in a["cuando"]]
            if len(restantes) == len(datos):
                return Respuesta(f"No tengo nada aprendido sobre «{m.group(1)}».")
            guardar(restantes)
            return Respuesta(f"Olvidado lo de «{m.group(1)}».")
        return None
