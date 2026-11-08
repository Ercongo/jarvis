# Asuka en directo: instalador para el PC NUEVO (Windows 10/11 con tarjeta NVIDIA).
# Lo lanza INSTALAR.bat. Instala, en C:\AsukaDirecto:
#   - Deep-Live-Cam (cambia tu cara por la de Asuka en la webcam, en tiempo real)
#   - Applio (cambia tu voz por la de Asuka en tiempo real, con su modelo RVC)
#   - OBS Studio y el cable de audio virtual (para mandar la imagen y la voz a Twitch)
# No toca nada más del PC. Se puede volver a lanzar: lo que ya esté hecho se salta.

$ErrorActionPreference = "Stop"
$Base = "C:\AsukaDirecto"
$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path $Base | Out-Null
Start-Transcript -Path "$Base\instalacion.log" -Append | Out-Null

function Paso($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Hay($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------- 0. tarjeta gráfica
Paso "Compruebo la tarjeta gráfica"
$Gpu = "cpu"
if (Hay "nvidia-smi") {
    $info = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    Write-Host "   NVIDIA: $info" -ForegroundColor Green
    $Gpu = "cuda"
} else {
    $vga = (Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join ", "
    Write-Host "   No hay NVIDIA ($vga). Se instala igual, pero en directo irá a trompicones." -ForegroundColor Yellow
    Write-Host "   (Si tienes NVIDIA y no sale, instala su controlador: https://www.nvidia.com/Download/index.aspx)"
    $Gpu = "dml"
}

# ---------------------------------------------------------------- 1. programas base
Paso "Programas base (Python 3.11, Git, FFmpeg, OBS) con winget"
$apps = @(
    @{id = "Python.Python.3.11"; cmd = "py"},
    @{id = "Git.Git"; cmd = "git"},
    @{id = "Gyan.FFmpeg"; cmd = "ffmpeg"},
    @{id = "OBSProject.OBSStudio"; cmd = ""}
)
foreach ($a in $apps) {
    if ($a.cmd -and (Hay $a.cmd)) { Write-Host "   ya está: $($a.id)"; continue }
    winget install --id $a.id -e --accept-package-agreements --accept-source-agreements --silent
}
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# ---------------------------------------------------------------- 2. cable de audio virtual
Paso "Cable de audio virtual (VB-CABLE)"
if (Get-CimInstance Win32_SoundDevice | Where-Object { $_.Name -like "*VB-Audio*" }) {
    Write-Host "   ya está"
} else {
    $zip = "$Base\vbcable.zip"
    Invoke-WebRequest "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "$Base\vbcable" -Force
    Write-Host "   Se abre el instalador del cable: pulsa «Install Driver» y acepta." -ForegroundColor Yellow
    Start-Process "$Base\vbcable\VBCABLE_Setup_x64.exe" -Verb RunAs -Wait
}

# ---------------------------------------------------------------- 3. Deep-Live-Cam
Paso "Deep-Live-Cam (cara)"
$Dlc = "$Base\Deep-Live-Cam"
if (-not (Test-Path "$Dlc\run.py")) { git clone --depth 1 https://github.com/hacksider/Deep-Live-Cam.git $Dlc }
if (-not (Test-Path "$Dlc\venv")) { py -3.11 -m venv "$Dlc\venv" }
$Py = "$Dlc\venv\Scripts\python.exe"
& $Py -m pip install -U pip
& $Py -m pip install -r "$Dlc\requirements.txt"
if ($Gpu -eq "cuda") {
    & $Py -m pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
    & $Py -m pip uninstall -y onnxruntime onnxruntime-gpu
    # con [cuda,cudnn] trae sus propias librerías de CUDA: no hace falta instalar el CUDA Toolkit aparte
    & $Py -m pip install "onnxruntime-gpu[cuda,cudnn]==1.26.0"
} else {
    & $Py -m pip uninstall -y onnxruntime onnxruntime-directml
    & $Py -m pip install onnxruntime-directml==1.21.0
}
New-Item -ItemType Directory -Force -Path "$Dlc\models" | Out-Null
foreach ($m in @("inswapper_128_fp16.onnx", "gfpgan-1024.onnx")) {
    if (-not (Test-Path "$Dlc\models\$m")) {
        Write-Host "   bajo $m"
        Invoke-WebRequest "https://huggingface.co/hacksider/deep-live-cam/resolve/main/$m" -OutFile "$Dlc\models\$m"
    }
}

# ---------------------------------------------------------------- 4. Applio (voz)
Paso "Applio (voz de Asuka en tiempo real)"
$Applio = "$Base\Applio"
if (-not (Test-Path "$Applio\core.py")) { git clone --depth 1 https://github.com/IAHispano/Applio.git $Applio }
if (-not (Test-Path "$Applio\env")) {
    Push-Location $Applio
    cmd /c "run-install.bat"
    Pop-Location
}
# su modelo de voz (asuka.pth + asuka.index, del cuaderno de Kaggle)
New-Item -ItemType Directory -Force -Path "$Applio\logs\asuka" | Out-Null
if (Test-Path "$Aqui\modelo_voz") {
    Copy-Item "$Aqui\modelo_voz\*" "$Applio\logs\asuka\" -Force
    Write-Host "   modelo de voz de Asuka copiado"
} else {
    Write-Host "   Falta el modelo de voz: entrena «entrenar_voz_rvc_asuka.ipynb» en Kaggle y pon asuka.pth y asuka.index en la carpeta modelo_voz." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 5. lo de Asuka
Paso "Cara de Asuka, marca «avatar IA» y accesos directos"
Copy-Item "$Aqui\cara_asuka.jpg", "$Aqui\marca_avatar_ia.png", "$Aqui\iniciar_directo.ps1", "$Aqui\GUIA.txt" $Base -Force
Copy-Item "$Aqui\asuka_run.py" $Dlc -Force
Set-Content "$Base\gpu.txt" $Gpu
$Ws = New-Object -ComObject WScript.Shell
$Lnk = $Ws.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Asuka en directo.lnk")
$Lnk.TargetPath = "powershell.exe"
$Lnk.Arguments = "-ExecutionPolicy Bypass -File `"$Base\iniciar_directo.ps1`""
$Lnk.WorkingDirectory = $Base
$Lnk.IconLocation = "shell32.dll,138"
$Lnk.Save()

Paso "Hecho"
Write-Host "   En el escritorio tienes «Asuka en directo». Lee GUIA.txt para OBS (5 minutos, solo la primera vez)." -ForegroundColor Green
Stop-Transcript | Out-Null
Read-Host "Pulsa Intro para cerrar"
