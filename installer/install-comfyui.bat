@echo off
rem Installs a ComfyUI for xp-photocraft on this PC (Windows, NVIDIA GPU): ComfyUI itself, PyTorch,
rem the Qwen Image Edit 2511 models of the built-in workflow, and a start script. Nano Banana needs
rem nothing to install: it is a ComfyUI partner node billed to your comfy.org account (see INSTALL.md).
rem
rem   install-comfyui.bat [folder]        default folder: ComfyUI-xp next to this script
rem   set XP_QWEN_VARIANT=int8            for RTX 30 series (int8 weights), default fp8mixed
rem   set XP_SKIP_MODELS=1                install ComfyUI only, no model download (~32 GB)
rem
rem Needs about 40 GB of disk, a recent NVIDIA driver, and a good connection. Safe to re-run: it
rem resumes downloads and skips what is already there.
setlocal
set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=%~dp0ComfyUI-xp"
if "%XP_QWEN_VARIANT%"=="" set "XP_QWEN_VARIANT=fp8mixed"
set "UV=%USERPROFILE%\.local\bin\uv.exe"
rem The CUDA wheels are large and some mirrors slow: give each download ten minutes, not uv's 30 s.
set "UV_HTTP_TIMEOUT=600"

echo.
echo  ComfyUI for xp-photocraft  -^>  %ROOT%
echo  ---------------------------------------------------------------
where nvidia-smi >nul 2>nul || echo  WARNING: nvidia-smi not found. ComfyUI needs an NVIDIA GPU with its driver installed.

rem --- uv: one tool that brings Python and installs packages, no admin rights ---------------------
if not exist "%UV%" (
    echo  [1/5] Installing uv ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" || goto :fail
) else (
    echo  [1/5] uv already installed
)

rem --- ComfyUI sources (zip of the main branch: no git needed) -------------------------------------
mkdir "%ROOT%" 2>nul
if not exist "%ROOT%\ComfyUI\main.py" (
    echo  [2/5] Downloading ComfyUI ...
    curl -L --fail --progress-bar -o "%ROOT%\comfyui.zip" https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip || goto :fail
    tar -xf "%ROOT%\comfyui.zip" -C "%ROOT%" || goto :fail
    move "%ROOT%\ComfyUI-master" "%ROOT%\ComfyUI" >nul || goto :fail
    del "%ROOT%\comfyui.zip"
) else (
    echo  [2/5] ComfyUI already there
)

rem --- Python environment: PyTorch for the driver's CUDA (13 = ComfyUI's recommendation; an older
rem     driver, CUDA 12.x, gets the cu128 build), then ComfyUI's requirements -----------------------
set "CUDA=cu130"
for /f %%v in ('powershell -NoProfile -Command "try { (nvidia-smi | Select-String 'CUDA Version: (\d+)').Matches[0].Groups[1].Value } catch { 13 }"') do if %%v LSS 13 set "CUDA=cu128"
echo  [3/5] Python environment and PyTorch %CUDA% ^(about 3 GB^) ...
if not exist "%ROOT%\ComfyUI\.venv\Scripts\python.exe" "%UV%" venv --python 3.12 "%ROOT%\ComfyUI\.venv" || goto :fail
rem A torch built for another CUDA (same version number) would be kept as is: reinstall it then.
set "REINSTALL="
"%ROOT%\ComfyUI\.venv\Scripts\python.exe" -c "import torch, sys; sys.exit(0 if (torch.version.cuda or '').startswith('%CUDA:~2,2%') else 1)" >nul 2>nul || set "REINSTALL=--reinstall-package torch --reinstall-package torchvision --reinstall-package torchaudio"
"%UV%" pip install --python "%ROOT%\ComfyUI\.venv\Scripts\python.exe" %REINSTALL% torch torchvision torchaudio --index-url https://download.pytorch.org/whl/%CUDA% || goto :fail
"%UV%" pip install --python "%ROOT%\ComfyUI\.venv\Scripts\python.exe" -r "%ROOT%\ComfyUI\requirements.txt" || goto :fail

rem --- Models of the built-in workflow (the files ComfyUI's own Qwen Image Edit 2511 template uses) -
if "%XP_SKIP_MODELS%"=="1" (
    echo  [4/5] Models skipped ^(XP_SKIP_MODELS=1^)
) else (
    echo  [4/5] Models ^(about 32 GB, resumable^) ...
    call :get diffusion_models qwen_image_edit_2511_%XP_QWEN_VARIANT%.safetensors https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_%XP_QWEN_VARIANT%.safetensors || goto :fail
    call :get text_encoders qwen_2.5_vl_7b_fp8_scaled.safetensors https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors || goto :fail
    call :get vae qwen_image_vae.safetensors https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors || goto :fail
    call :get loras Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors || goto :fail
)

rem --- Start script ---------------------------------------------------------------------------------
echo  [5/5] Start script ...
> "%ROOT%\start-comfyui.bat" (
    echo @echo off
    echo rem ComfyUI for xp-photocraft, on this PC only ^(127.0.0.1^). Keep this window open while you work.
    echo cd /d "%ROOT%\ComfyUI"
    echo .venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188 --preview-method auto
    echo pause
)
echo.
echo  Done. Start it with:  %ROOT%\start-comfyui.bat
echo  Then tell the bridge:  xp-photocraft connect http://127.0.0.1:8188
echo  First generation loads the models ^(about a minute^); the next ones take 10 to 30 s.
goto :end

:get
rem :get <models subfolder> <file name> <url>  - resumable download, skipped when complete
set "DIR=%ROOT%\ComfyUI\models\%~1"
mkdir "%DIR%" 2>nul
if exist "%DIR%\%~2" if not exist "%DIR%\%~2.part" (echo        have %~2 & exit /b 0)
echo        %~2
curl -L --fail --progress-bar -C - -o "%DIR%\%~2.part" "%~3" || exit /b 1
move /Y "%DIR%\%~2.part" "%DIR%\%~2" >nul
exit /b 0

:fail
echo.
echo  Something failed above. Re-run this script: it resumes where it stopped.
:end
echo.
pause
