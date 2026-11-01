"""
La voz de Athena: «pon la voz de Asuka», «pon tu voz de antes».

La voz de Asuka para hablar al momento tiene que ser un modelo de Piper entrenado con su timbre
(es_ES-asuka-medium.onnx + .onnx.json): se prepara de noche con voz_asuka_datos.py y se entrena gratis en Kaggle con
voz_asuka_kaggle.ipynb. Mientras no exista, «pon la voz de Asuka» usa la voz femenina de sharvard.
Los archivos se buscan en Descargas (se bajan de Kaggle con el navegador del portátil) y en ~/jarvis/voces.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import perfil
from herramientas import normalizar
from sistema import Respuesta

VOCES = Path.home() / "jarvis/voces"
BUSCAR = [Path.home() / "Descargas", Path.home() / "Downloads", VOCES]   # (Telegram no pasa de 20 MB: no vale)


def _modelo_asuka() -> Path | None:
    for d in BUSCAR:
        if not d.exists():
            continue
        for onnx in sorted(d.rglob("*asuka*.onnx"), key=lambda p: p.stat().st_mtime, reverse=True):
            if Path(str(onnx) + ".json").exists():
                if d != VOCES:                          # se guarda con las demás voces
                    VOCES.mkdir(parents=True, exist_ok=True)
                    destino = VOCES / onnx.name
                    shutil.copy(onnx, destino)
                    shutil.copy(str(onnx) + ".json", str(destino) + ".json")
                    return destino
                return onnx
    return None


def _hablante(modelo: Path, sexo: str) -> int | None:
    """El número del hablante «F» o «M» según el .onnx.json (en sharvard la mujer es el 1)."""
    try:
        import json
        mapa = json.loads(Path(str(modelo) + ".json").read_text()).get("speaker_id_map") or {}
        return mapa.get(sexo)
    except (OSError, ValueError):
        return None


class VozPersonaje:
    def __init__(self, asistente, clase_voz, log=print):
        self.a, self.Voz, self.log = asistente, clase_voz, log

    def _cambiar(self, modelo: Path, hablante: int | None, lentitud: float) -> None:
        voz = dict(perfil.perfil().get("voz") or {})
        voz.update(modelo=str(modelo), lentitud=lentitud)
        if hablante is not None:
            voz["hablante"] = hablante
        perfil.guardar(voz=voz)
        if self.a.voz is not None:                      # se carga ya, sin reiniciar el asistente
            self.a.voz = self.Voz(modelo)

    def manejar(self, texto: str) -> Respuesta | None:
        t = normalizar(texto).strip(" .?¿!¡")
        if re.search(r"\bvoz de asuka\b", t) and re.search(r"\b(pon|usa|ten|cambia|habla|quiero)\w*\b", t):
            m = _modelo_asuka()
            if m:
                self._cambiar(m, None, 1.0)
                self.log(f"voz: ahora {m.name}")
                return Respuesta("Ya está. Desde ahora hablo con la voz de Asuka.")
            sharvard = next(VOCES.glob("*sharvard*.onnx"), None)
            if not sharvard:
                return Respuesta("No encuentro las voces de Piper.")
            self._cambiar(sharvard, _hablante(sharvard, "F"), 1.0)
            return Respuesta("Su voz entrenada aún no está; mientras, sigo con mi voz de mujer. Cuando "
                             "tengas los dos archivos de Kaggle, bájalos con el navegador del portátil (a Descargas) y "
                             "repíteme «pon la voz de Asuka».")
        if re.search(r"\b(tu |la )?voz (de antes|anterior|normal|de siempre|original|de athena)\b", t):
            sharvard = next(VOCES.glob("*sharvard*.onnx"), None)
            if sharvard:
                self._cambiar(sharvard, _hablante(sharvard, "F"), 1.0)
                return Respuesta("Vuelvo a mi voz de siempre.")
        return None
