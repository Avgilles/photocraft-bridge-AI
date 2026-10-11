# xp-photocraft — installation guide

**Generative Fill** and **Remove (AI)** in PhotoCraft, on your own ComfyUI. Select an area, type
what you want to see there, and the result comes back as a new masked layer. Nothing leaves your
machine with the built-in model (Qwen Image Edit); Nano Banana is optional, through the comfy.org
cloud.

Three pieces, to install in this order. **Everything stays in one folder** (the one you unzip into):
the bridge, its settings in `data\`, and ComfyUI in `ComfyUI-xp\`. You can inspect it, move it, and
uninstall by deleting the folder.

| Piece | Role | Where |
|---|---|---|
| **PhotoCraft (XP build)** | the app, with the AI task bar under the selection and the **XP** menu | the PhotoCraft XP release of the fork, unzipped next to this one |
| **xp-photocraft** (this folder) | the bridge: PhotoCraft ↔ ComfyUI | `install.bat` / `install.sh` |
| **ComfyUI** + models | the generation, on this PC or on another PC with a good GPU | `install-comfyui.bat` / `.sh` → `ComfyUI-xp\`, or a ComfyUI you already have |

There is **nothing else to install** first: no Python, no Git. The bridge is a standalone
executable, and the ComfyUI installer brings its own Python (through the `uv` tool).

## 1. What you need

- Windows 10/11 64-bit, or Linux (binary built on Fedora 41, glibc 2.40 or later).
- To generate **locally**: an NVIDIA card. 24 GB of VRAM is comfortable (RTX 3090/4090/5090), 16 GB
  works; with 12 GB or less it is slow (the model spills into RAM): plan for 32 GB of RAM or more.
  No GPU: use the ComfyUI of another PC (§ 4) or Nano Banana (§ 5).
- About 40 GB of disk for ComfyUI and the models.

## 2. Install the bridge (Windows)

1. Create a folder (for example `C:\PhotoCraftXP`) and unzip both archives into it: PhotoCraft XP's
   and this one. You get `PhotoCraft-XP\photocraft.exe` and
   `xp-photocraft-…-windows-x64\xp-photocraft.exe`.
2. Double-click **`install.bat`**. It adds this folder to your user PATH (so that PhotoCraft's task
   bar finds the bridge), creates `data\` (settings and work folder) and puts the shipped workflows in
   `data\workflows\`. Nothing is copied anywhere else, no administrator rights.
3. Start PhotoCraft with **`start-photocraft.bat`** (it starts PhotoCraft with its control server
   and the shared work folder `data\work`). It finds `photocraft.exe` in a `PhotoCraft*` folder next
   to it; otherwise drop the exe on it once, or write its path in `photocraft-path.txt`.

Linux: `./install.sh` (links in `~/.local/bin`), then `start-photocraft`.

## 3. Install ComfyUI on this PC (NVIDIA)

Double-click **`install-comfyui.bat`** (Linux: `./install-comfyui.sh`). It installs into
`ComfyUI-xp\`, next to it: the `uv` tool and a Python of its own, ComfyUI, PyTorch CUDA (chosen from
your NVIDIA driver), the four files of the built-in workflow (Qwen Image Edit 2511, text encoder,
VAE, Lightning LoRA, ~32 GB) and a **`start-comfyui.bat`**. Expect 3 GB then 32 GB of downloads; run
it again and it resumes where it stopped. It first asks whether to also install **Qwen Image 2.1
Turbo** (~18 GB more, non-commercial use only, see § 5): answer `y` or just press Enter for no.

- RTX 30 series (3090, 3080…): before running it, open a console, type `set XP_QWEN_VARIANT=int8`,
  then `install-comfyui.bat`; the int8 weights are faster on these cards.
- Already have ComfyUI? No need to reinstall: open the *Qwen Image Edit 2511* template in it
  (Templates menu), it downloads the same files. The bridge finds them by name.

Then start `start-comfyui.bat` (keep its window open), and in a console:

```
xp-photocraft connect http://127.0.0.1:8188
```

Expected answer: `ComfyUI connected - built-in Qwen models OK`. PhotoCraft's **XP** menu has the same
field (*ComfyUI server* ▸ *Test & save*).

## 4. ComfyUI on another PC

On the GPU PC, start ComfyUI with `--listen` **on a trusted network** (ComfyUI has no
authentication: never expose it to the internet), then on the PhotoCraft PC:
`xp-photocraft connect http://PC-ADDRESS:8188`. Safer: an SSH tunnel
(`ssh -N -L 8188:127.0.0.1:8188 you@gpu-pc`) and the default address `http://127.0.0.1:8188`.

## 5. Nano Banana (cloud quality, optional)

Nano Banana 2.1 is a ComfyUI *partner node*: it runs at comfy.org and bills your account (a few
cents per image). It needs a recent ComfyUI (0.39 or later, which `install-comfyui` installs) and a
comfy.org API key:

1. Create an account on [comfy.org](https://www.comfy.org), buy a few credits, and create an API key
   in your profile (*API Keys* on platform.comfy.org). Copy it: it is not shown again.
2. Open **`data\.env`** (created by `install.bat` from `.env.example`) and fill in the line
   `XP_PHOTOCRAFT_COMFY_API_KEY=your-key`. The bridge reads this file at every run: nothing to
   restart. An environment variable of the same name, if you have one, wins.
3. In PhotoCraft, menu **XP ▸ Generative fill ▸ Nano Banana 2.1 (comfy.org)**. The choice is kept per
   action: local Qwen for *Remove*, Nano Banana for *Fill*, for example.

Without a key, the status bar says "GeminiNanoBanana…: Unauthorized: Please login first to use this
node". The key is never shown, and only goes to your ComfyUI, which hands it to comfy.org.

### Qwen Image 2.1 Turbo (local, non-commercial use)

The **XP** menu also offers *Qwen Image 2.1 Turbo (non-commercial)*: local, free, 12 to 15 s per
generation on an RTX 3090, with a quality close to Nano Banana. **Its license (Qwen Research
License) only allows research and evaluation**: for paid work, keep Qwen Edit 2511 (built in,
Apache-2.0) or Nano Banana. `install-comfyui.bat` installs it if you answer `y` to its question;
for a ComfyUI of your own (0.39 or later), put these four files (~18 GB) in its `models\` folders:

| Folder | File ([Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main)) |
|---|---|
| `diffusion_models` | `qwen_image_2.1_int8_convrot.safetensors` |
| `text_encoders` | `qwen3vl_8b_int8_convrot.safetensors` |
| `vae` | `qwen_image_2.1_vae_bf16.safetensors` |
| `loras` | `qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` |

### Add your own workflows

`data\workflows\` is the catalog: it starts with the three shipped workflows, the built-in one
included (`Qwen Edit 2511 (ComfyUI).json`, the default for both actions). Any ComfyUI graph dropped
in **`data\workflows\`** becomes a workflow, named after its file
(`Flux Fill.json` → *Flux Fill*): menu **XP ▸ Open Workflows Folder**, drop the file, open the XP
menu again, and pick it for *Generative fill* or *Remove (AI)*. In ComfyUI, save it with
**Workflow ▸ Export (API)** after giving a few nodes a title (right click ▸ *Title*): `pc:image` on
the *Load Image* that receives the selection, `pc:prompt` on the prompt node, and if needed
`pc:mask`, `pc:seed`, `pc:output` (details in the README). If the model needs instructions around
what you type, write them in the graph's prompt with `{prompt}` where your text goes.

## 6. Use

Select an area (rectangle, lasso…). A bar appears under it:

- **Generative fill**: type what you want in the field and click. A crossed card takes the spot
  while it generates and you keep working; the result replaces it, as a layer masked by your
  selection.
- **Remove (AI)**: erases what is selected and rebuilds the background. Include the shadow in the
  selection.
- **Remove**: PhotoCraft's classic fill, no AI.

Each result is also kept **next to the document's file**, in `xp-work\<document name>\` (the model's
image + a `.json` with the prompt, the workflow and the seed): one folder per project, nothing piles
up elsewhere. On a document never saved, the bar first offers to save it.

Tips: a margin around the object helps the model; to add something in a uniform area (sky, wall),
feather the selection (Feather 20–30 px) and leave room for the shadow or the smoke. A generation
overwrites the clipboard (known limit).

## 7. Troubleshooting

```
xp-photocraft doctor
```

It checks, line by line: the work folder, the link with PhotoCraft (was it started by
`start-photocraft`?), the ComfyUI server, the workflows and their models.

- *"PhotoCraft does not answer"*: PhotoCraft was not started by `start-photocraft.bat`.
- *"ComfyUI server unreachable"*: ComfyUI is not running, or the saved address is wrong
  (`xp-photocraft connect …`).
- *"… is not on the ComfyUI server"* or *"models not on the ComfyUI server"*: run
  `install-comfyui.bat` again (it resumes the downloads), or install the workflow's models (the
  *Qwen Image Edit 2511* template of ComfyUI for the built-in one).
- First generation slow (~1 min): the models are loading; then 10 to 30 s depending on the card.
- *Qwen Image 2.1 paints a black area* on a ComfyUI of your own: start it with `--fp32-text-enc`
  (`start-comfyui.bat` does). Without CUDA 13 kernels its text encoder overflows in fp16.

## 8. Uninstall

Delete the folder (bridge, `data\`, `ComfyUI-xp\` with its `uv`, its Python and its models) and remove
it from your user PATH (Settings ▸ Environment variables). Linux: also delete the two links in
`~/.local/bin`. Nothing else was written on the machine.
