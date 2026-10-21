"""MusicGen (facebook/musicgen-small) en su propio entorno: ~/jarvis/venv_musica/bin/python musica_ia.py …
Lo lanza creativo.py en un proceso aparte, con prioridad baja, para que la memoria se libere al terminar."""
import argparse

import scipy.io.wavfile as wf
import torch
from transformers import AutoProcessor, MusicgenForConditionalGeneration

p = argparse.ArgumentParser()
p.add_argument("--prompt", required=True)
p.add_argument("--segundos", type=float, default=30)
p.add_argument("--salida", required=True)
a = p.parse_args()

torch.set_num_threads(3)                      # deja un núcleo libre para Jarvis
proc = AutoProcessor.from_pretrained("facebook/musicgen-small")
modelo = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
entrada = proc(text=[a.prompt], padding=True, return_tensors="pt")
with torch.inference_mode():
    audio = modelo.generate(**entrada, max_new_tokens=int(min(30, a.segundos) * 50), do_sample=True, guidance_scale=3)
wf.write(a.salida, modelo.config.audio_encoder.sampling_rate, audio[0, 0].numpy())
