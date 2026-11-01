"""
Prepara (de noche, sin prisa) las grabaciones para entrenar una voz de Piper con el timbre de Asuka, para que Athena
hable con su voz al instante (Piper es lo único lo bastante rápido en este portátil).

  1. La IA escribe ~400 frases variadas en español de España (las que diría una asistente y las de Asuka).
  2. Piper (sharvard, hablante femenina) las dice.
  3. OpenVoice V2 (MyShell, MIT) les pone el timbre de la muestra de Asuka (~20 s por frase con este procesador).
  4. Queda ~/jarvis/voz-asuka-datos/{wavs/, metadata.csv} y un zip listo para entrenar en Kaggle (GPU gratis).

Se puede cortar y relanzar: sigue por donde iba.
  ~/.local/share/voz-asuka/venv/bin/python voz_asuka_datos.py [número de frases]
"""

import json
import os
import random
import re
import subprocess
import sys
import time
import wave
import zipfile
from pathlib import Path

SOLO_FRASES = "--solo-frases" in sys.argv          # esta parte corre con el Python del asistente (su cerebro)
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
N = int(ARGS[0]) if ARGS else 400
V = Path.home() / ".local/share/voz-asuka"
D = Path.home() / "jarvis/voz-asuka-datos"
W = D / "wavs"
W.mkdir(parents=True, exist_ok=True)
FRASES = D / "frases.json"
META = D / "metadata.csv"
JPY = str(Path.home() / "jarvis/venv/bin/python")
MODELO = next(Path.home().glob("jarvis/voces/*sharvard*.onnx"))
REF = Path.home() / "jarvis/nexus/voz_ref.wav"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------- 1. frases
def frases() -> list[str]:
    if FRASES.exists():
        return json.loads(FRASES.read_text(encoding="utf-8"))
    if not SOLO_FRASES:
        subprocess.run([JPY, __file__, "--solo-frases", str(N)], check=True, cwd=str(Path.home() / "jarvis/core-orchestrator"))
        return json.loads(FRASES.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path.home() / "jarvis/core-orchestrator"))
    from cerebro import Cerebro
    c = Cerebro(lambda *a: None)
    temas = ["avisos de una asistente de casa (luces, alarmas, tiempo, calendario)", "respuestas cortas y "
             "confirmaciones", "preguntas al usuario", "conversación informal con humor seco", "videojuegos y anime",
             "gimnasio y comida", "tecnología y ordenadores", "noticias y explicaciones breves", "números, horas, fechas "
             "y precios escritos con letra", "frases largas con comas y pausas", "exclamaciones y emociones",
             "recordatorios y agenda"]
    out: list[str] = []
    while len(out) < N:
        tema = temas[len(out) // 35 % len(temas)]
        try:
            r = c.chat([{"role": "system", "content": "Devuelve SOLO JSON."},
                        {"role": "user", "content": f"Escribe 40 frases distintas en español de España sobre: {tema}. "
                         "Entre 4 y 22 palabras cada una, naturales, variadas en sonidos (que salgan todas las letras: "
                         "ñ, ll, rr, j, z, ch, g, x), sin siglas ni números en cifras ni emojis. JSON: {\"frases\": [\"…\"]}"}],
                       formato_json=True, max_tokens=2500, temperatura=0.9, timeout=90)
            nuevas = json.loads(re.search(r"\{.*\}", r, re.S).group(0)).get("frases", [])
        except Exception as e:
            log("frases: reintento", e)
            time.sleep(20)
            continue
        vistos = set(out)
        out += [f.strip() for f in nuevas if 3 <= len(f.split()) <= 26 and f.strip() not in vistos
                and not re.search(r"\d", f)]
        log("frases", len(out))
    random.shuffle(out)
    out = out[:N]
    FRASES.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    return out


# ---------- 2-3. voz
def conversor():
    import torch
    torch.set_num_threads(max(1, os.cpu_count() - 1))   # deja un núcleo para el asistente
    from openvoice.api import OpenVoiceBaseClass, ToneColorConverter
    cv = ToneColorConverter.__new__(ToneColorConverter)
    OpenVoiceBaseClass.__init__(cv, str(V / "modelo/converter/config.json"), device="cpu")
    cv.watermark_model, cv.version = None, getattr(cv.hps, "_version_", "v1")
    cv.load_ckpt(str(V / "modelo/converter/checkpoint.pth"))
    se_asuka = torch.load(V / "asuka_se.pth") if (V / "asuka_se.pth").exists() else \
        cv.extract_se([str(REF)], se_save_path=str(V / "asuka_se.pth"))
    return cv, se_asuka


def main():
    lista = frases()
    hechas = {l.split("|", 1)[0] for l in META.read_text(encoding="utf-8").splitlines()} if META.exists() else set()
    cv, se_asuka = conversor()
    se_origen = None
    for i, f in enumerate(lista):
        nombre = f"asuka_{i:04d}.wav"
        if nombre in hechas:
            continue
        tmp = Path(f"/tmp/vozasuka_{i}.wav")
        subprocess.run([JPY, "-c", (
            "import sys, wave\nfrom piper import PiperVoice, SynthesisConfig\n"
            "v = PiperVoice.load(sys.argv[1])\n"
            "with wave.open(sys.argv[2], 'wb') as w:\n"
            "    v.synthesize_wav(sys.argv[3], w, syn_config=SynthesisConfig(speaker_id=0, length_scale=1.0))"),
            str(MODELO), str(tmp), f], check=True)
        if se_origen is None:
            se_origen = cv.extract_se([str(tmp)])
        t = time.time()
        cv.convert(audio_src_path=str(tmp), src_se=se_origen, tgt_se=se_asuka, output_path=str(W / nombre), tau=0.3)
        tmp.unlink(missing_ok=True)
        with open(META, "a", encoding="utf-8") as m:
            m.write(f"{nombre}|{f}\n")
        log(f"{i + 1}/{len(lista)} ({time.time() - t:.0f} s)")
    zipf = D.parent / "voz-asuka-datos.zip"
    with zipfile.ZipFile(zipf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(META, "metadata.csv")
        for w in sorted(W.glob("*.wav")):
            z.write(w, f"wavs/{w.name}")
    log("listo:", zipf, f"{zipf.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    if SOLO_FRASES:
        frases()
    else:
        main()
