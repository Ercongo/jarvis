# Asuka en directo: abre la cara (Deep-Live-Cam), la voz (Applio) y OBS.
$Base = "C:\AsukaDirecto"
$Gpu = (Get-Content "$Base\gpu.txt" -ErrorAction SilentlyContinue) -as [string]
if (-not $Gpu) { $Gpu = "cuda" }

# 1. la cara: Deep-Live-Cam con la foto de Asuka ya elegida. En su ventana: pulsa «Live» (webcam).
$Dlc = "$Base\Deep-Live-Cam"
Start-Process -WorkingDirectory $Dlc -FilePath "$Dlc\venv\Scripts\python.exe" -ArgumentList @(
    "asuka_run.py", "`"$Base\cara_asuka.jpg`"", "--execution-provider", $Gpu,
    "--frame-processor", "face_swapper", "--live-mirror", "--live-resizable")
# (la mejora de cara «face_enhancer» se activa en su ventana si la gráfica va sobrada: quita fotogramas)

# 2. la voz: Applio (se abre en el navegador; pestaña «Realtime»)
Start-Process -WorkingDirectory "$Base\Applio" -FilePath "cmd.exe" -ArgumentList "/c", "run-applio.bat"

# 3. OBS
$obs = "C:\Program Files\obs-studio\bin\64bit\obs64.exe"
if (Test-Path $obs) { Start-Process -WorkingDirectory (Split-Path $obs) -FilePath $obs }

Write-Host "Abiertos: Deep-Live-Cam (pulsa Live), Applio (pestaña Realtime) y OBS." -ForegroundColor Green
Write-Host "Recuerda: la marca «avatar IA en directo» tiene que verse en el directo."
Start-Sleep 8
