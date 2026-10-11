#!/usr/bin/env bash
# Installs a ComfyUI for xp-photocraft on this PC (Linux, NVIDIA GPU): ComfyUI, PyTorch, the Qwen
# Image Edit 2511 models of the built-in workflow, and a start script. Nano Banana needs nothing to
# install: it is a ComfyUI partner node billed to your comfy.org account (see INSTALL.md).
#
#   install-comfyui.sh [folder]        default: ComfyUI-xp next to this script
#   XP_QWEN_VARIANT=int8               for RTX 30 series (int8 weights), default fp8mixed
#   XP_SKIP_MODELS=1                   install ComfyUI only, no model download (~32 GB)
#   XP_QWEN21=y                        also Qwen Image 2.1 Turbo (~18 GB) without asking (n: never)
#
# Needs about 40 GB of disk and the NVIDIA driver. Safe to re-run: resumes downloads, skips what is there.
set -eu
root="${1:-$(cd "$(dirname "$0")" && pwd)/ComfyUI-xp}"
variant="${XP_QWEN_VARIANT:-fp8mixed}"
# uv, its Python and its downloads live inside the folder too: nothing lands in your profile.
uv="$root/uv/uv"
export UV_UNMANAGED_INSTALL="$root/uv" UV_PYTHON_INSTALL_DIR="$root/uv/python" UV_MANAGED_PYTHON=1 UV_NO_CACHE=1
# The CUDA wheels are large and some mirrors slow: give each download ten minutes, not uv's 30 s.
export UV_HTTP_TIMEOUT=600

echo
echo " ComfyUI for xp-photocraft  ->  $root"
echo " ---------------------------------------------------------------"
command -v nvidia-smi >/dev/null || echo " WARNING: nvidia-smi not found. ComfyUI needs an NVIDIA GPU with its driver installed."

# The optional second model, asked first: nobody waits half an hour for a question.
if [ -z "${XP_QWEN21:-}" ]; then
  echo
  echo " Also install Qwen Image 2.1 Turbo, a second local model (about 18 GB more)?"
  echo " Its licence (Qwen Research License) allows research and evaluation only: no commercial use."
  read -r -p " Install it? [y/N] " XP_QWEN21 || XP_QWEN21=""
fi
case "${XP_QWEN21:-}" in [yY] | [yY][eE][sS]) qwen21=1 ;; *) qwen21="" ;; esac
echo

mkdir -p "$root"
if [ ! -x "$uv" ]; then
  echo " [1/5] Installing uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo " [1/5] uv already installed"
fi

mkdir -p "$root"
if [ ! -f "$root/ComfyUI/main.py" ]; then
  echo " [2/5] Downloading ComfyUI ..."
  curl -L --fail --progress-bar -o "$root/comfyui.zip" https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip
  (cd "$root" && python3 -c "import zipfile; zipfile.ZipFile('comfyui.zip').extractall('.')" 2>/dev/null || unzip -q comfyui.zip)
  mv "$root/ComfyUI-master" "$root/ComfyUI"
  rm -f "$root/comfyui.zip"
else
  echo " [2/5] ComfyUI already there"
fi

# PyTorch for the driver's CUDA: 13 (ComfyUI's recommendation), or the cu128 build on an older driver.
cuda=cu130
driver_cuda="$(nvidia-smi 2>/dev/null | grep -oP 'CUDA Version: \K[0-9]+' || echo 13)"
[ "${driver_cuda:-13}" -lt 13 ] && cuda=cu128
echo " [3/5] Python environment and PyTorch $cuda (about 3 GB) ..."
[ -x "$root/ComfyUI/.venv/bin/python" ] || "$uv" venv --python 3.12 "$root/ComfyUI/.venv"
# A torch built for another CUDA (same version number) would be kept as is: reinstall it then.
reinstall=""
"$root/ComfyUI/.venv/bin/python" -c "import torch, sys; sys.exit(0 if (torch.version.cuda or '').startswith('${cuda:2:2}') else 1)" >/dev/null 2>&1 \
  || reinstall="--reinstall-package torch --reinstall-package torchvision --reinstall-package torchaudio"
# shellcheck disable=SC2086
"$uv" pip install --python "$root/ComfyUI/.venv/bin/python" $reinstall torch torchvision torchaudio --index-url "https://download.pytorch.org/whl/$cuda"
"$uv" pip install --python "$root/ComfyUI/.venv/bin/python" -r "$root/ComfyUI/requirements.txt"

get() { # <models subfolder> <file name> <url>
  local dir="$root/ComfyUI/models/$1"
  mkdir -p "$dir"
  if [ -f "$dir/$2" ] && [ ! -f "$dir/$2.part" ]; then echo "       have $2"; return; fi
  echo "       $2"
  curl -L --fail --progress-bar -C - -o "$dir/$2.part" "$3"
  mv -f "$dir/$2.part" "$dir/$2"
}
if [ "${XP_SKIP_MODELS:-}" = "1" ]; then
  echo " [4/5] Models skipped (XP_SKIP_MODELS=1)"
else
  echo " [4/5] Models (about 32 GB, resumable) ..."
  get diffusion_models "qwen_image_edit_2511_${variant}.safetensors" "https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_${variant}.safetensors"
  get text_encoders qwen_2.5_vl_7b_fp8_scaled.safetensors https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors
  get vae qwen_image_vae.safetensors https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors
  get loras Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors
  if [ -n "$qwen21" ]; then
    echo " [4/5] Qwen Image 2.1 Turbo (about 18 GB, resumable) ..."
    q=https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main
    get diffusion_models qwen_image_2.1_int8_convrot.safetensors "$q/diffusion_models/qwen_image_2.1_int8_convrot.safetensors"
    get text_encoders qwen3vl_8b_int8_convrot.safetensors "$q/text_encoders/qwen3vl_8b_int8_convrot.safetensors"
    get vae qwen_image_2.1_vae_bf16.safetensors "$q/vae/qwen_image_2.1_vae_bf16.safetensors"
    get loras qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors "$q/loras/qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors"
  fi
fi

echo " [5/5] Start script ..."
cat > "$root/start-comfyui.sh" <<EOF
#!/usr/bin/env bash
# ComfyUI for xp-photocraft, on this PC only (127.0.0.1). Keep this terminal open while you work.
cd "$root/ComfyUI"
# --fp32-text-enc: without CUDA 13 kernels, Qwen Image 2.1's int8 text encoder overflows in fp16
# (black results); fp32 keeps Qwen Edit 2511's text exact too, at no visible cost.
exec .venv/bin/python main.py --listen 127.0.0.1 --port 8188 --preview-method auto --fp32-text-enc
EOF
chmod +x "$root/start-comfyui.sh"
echo
echo " Done. Start it with:  $root/start-comfyui.sh"
echo " Then tell the bridge:  xp-photocraft connect http://127.0.0.1:8188"
echo " First generation loads the models (about a minute); the next ones take 10 to 30 s."
