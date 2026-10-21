import subprocess
import os

def hablar(texto):
    modelo = os.path.expanduser("~/jarvis/voice/models/es_ES-mls_10246-low.onnx")
    salida = os.path.expanduser("~/jarvis/voice/respuesta.wav")
    cmd = f'echo "{texto}" | python -m piper --model {modelo} --output_file {salida}'
    subprocess.run(cmd, shell=True)
    subprocess.run(["aplay", "-D", "plughw:1,0", salida])

def preguntar_ia(pregunta):
    resultado = subprocess.run(
        ["ollama", "run", "tinyllama", pregunta],
        capture_output=True, text=True
    )
    return resultado.stdout.strip()

if __name__ == "__main__":
    print("Asistente de prueba iniciado...")
    respuesta = preguntar_ia("Di hola en español de forma breve")
    print("IA:", respuesta)
    hablar(respuesta if respuesta else "Hola, estoy listo")
