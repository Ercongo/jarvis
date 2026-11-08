r"""Deep-Live-Cam con la cara de Asuka ya puesta: abre su ventana (no el modo sin ventana) con la foto elegida.
Uso (lo hace iniciar_directo.ps1):  venv\Scripts\python asuka_run.py C:\AsukaDirecto\cara_asuka.jpg [opciones de run.py]"""
import os
import runpy
import sys

cara = sys.argv.pop(1)
aqui = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, aqui)
# run.py prepara las librerías de CUDA y carga el programa; con otro nombre que __main__ no arranca solo
runpy.run_path(os.path.join(aqui, "run.py"), run_name="asuka")

import modules.core as core          # noqa: E402
import modules.globals as g          # noqa: E402

_original = core.parse_args


def _con_cara() -> None:
    _original()
    g.source_path = cara
    g.headless = False               # con la ventana: ahí se pulsa «Live»


core.parse_args = _con_cara
core.run()
