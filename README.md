# PhotoCraft Bridge AI — ComfyUI for PhotoCraft

**Generative Fill and Remove for [PhotoCraft](https://github.com/storytold/photocraft), on your own
ComfyUI, with your own workflows.** Select an area in PhotoCraft, type what you want there, and the
result comes back as a **new layer masked by your selection**: aligned, non-destructive, and the
pixels outside the selection are left untouched. The bridge is the `xp-photocraft` command
(`xp-photocraft.exe` in the releases).

![Before and after: a licence plate filled in, the man and his shadow removed, a dragon on each side](docs/before-after.jpg)

*Before / after, in four selections: a licence plate typed in, the man and his shadow removed, a
dragon on the left by Qwen Image 2.1 Turbo on a local GPU, a dragon on the right by Nano Banana
in the cloud.*

**Videos:** [the 2-minute demo](https://youtu.be/Znu5G5QCVYk) ·
[installing on Windows, step by step](https://youtu.be/XhTdAG_x7qA)

Generation runs on a ComfyUI server you control (this PC, or another PC with a GPU) with any
workflow you like: the built-in Qwen Image Edit graph, a graph you exported from ComfyUI (Flux Fill,
SDXL inpainting, a partner node such as Nano Banana…), or any command of your own. You pick the
model for each action from PhotoCraft's menu.

## Quick start (Windows)

1. From [Releases](https://github.com/Avgilles/photocraft-bridge-AI/releases), download
   `xp-photocraft-…-windows-x64.zip` (the bridge) and `PhotoCraft-XP-windows-x64.zip` (PhotoCraft
   with the task bar), and unzip both into one empty folder, e.g. `C:\PhotoCraftXP`.
2. Run `install.bat`, then `install-comfyui.bat` (ComfyUI, PyTorch and the built-in model, ~35 GB,
   NVIDIA GPU), then `start-comfyui.bat`.
3. Run `start-photocraft.bat`, open an image, select an area and use the bar under the selection.

Nothing else to install first (no Python, no Git), and everything stays in that folder: delete it to
uninstall. The step-by-step guide, with ComfyUI on another PC and Nano Banana, is
[`installer/INSTALL.md`](installer/INSTALL.md). On Linux, the bridge's `.tar.gz` works the same way
with its `.sh` scripts; build PhotoCraft from [the fork](https://github.com/Avgilles/photocraft).

## In PhotoCraft

![The task bar under a selection: prompt, Generative fill, Remove, Remove (AI), Inverse, Mask, Deselect](docs/task-bar.jpg)

The bar shows under any selection once PhotoCraft XP runs for the bridge (`start-photocraft.bat`
starts it with its control server):

- **Generative fill**: type what you want in the bar's field and click. A crossed card covers the
  selection while it generates and you keep working; the result replaces it.
- **Remove (AI)**: erases what is selected and rebuilds the background (include the shadow).
- **Remove** is PhotoCraft's classic fill; *Inverse*, *Mask* and *Deselect* act on the selection.
- **The workflow** of Generative fill is the list beside the field: starred ones first, then the
  recent ones, then each category.
- **×1 / ×3 / ×5** makes that many variations, one seed each, in one group. The first one to come
  is shown; under the group, a picker shows one at a time (**◀ 2/5 ▶**), **Keep** keeps the shown
  one as a plain masked layer, **↻** runs it again (its seed, the field's prompt or new settings),
  **Cancel** stops those still to come. Each variation of a partner node (Nano Banana) is billed.
- **Settings** (⚙): the settings a workflow shows, when it comes with an App Builder save (see
  [Settings](#settings-comfyui-app-mode)); each can be spread over the variations (from → to).
- **Several at once**: select elsewhere and generate again while a run goes on; each has its card,
  ComfyUI queues them.
- **XP menu** (last in the menu bar): the workflow of each action, by category with the starred and
  recent ones and a search field, *Import Workflow…*, *Open Workflows Folder*, and the ComfyUI
  server.

## Status

0.2.0. Tested on Windows 11 (RTX 4060 laptop, 8 GB), with ComfyUI on the same PC or on a Fedora 41
PC (RTX 3090) through an SSH tunnel. The Linux bridge installs and connects but has seen less use;
macOS is untested; PhotoCraft XP is only built for Windows so far. See [Limits](#limits).

## How it works

```
PhotoCraft (desktop, --control)                       ComfyUI (this PC or another one)
  │  selection                                          ▲
  ▼                                                     │ POST /upload/image, /prompt
xp-photocraft ── control protocol (loopback) ──► export region + margin and mask (PNG, sRGB)
     │                                                  │ poll /history, GET /view
     └── paste the result back at the same place ◄──────┘
         as a new layer, masked by the selection
```

- Only existing PhotoCraft commands are used: the region and the mask leave through throwaway
  duplicates written under PhotoCraft's automation root; the result comes back pasted in place.
- **Keep working while it generates.** A placeholder layer,
  `Generative Fill (generating… delete to cancel)`, covers the selection right away: a crossed
  frame naming the action and the prompt. The bridge then leaves PhotoCraft alone until the result
  is ready, and puts it where the placeholder is (same document, just above it, same mask), handing
  back whatever document, layer and selection you have by then.
- **Delete the placeholder to cancel.** While it waits, the bridge looks every half second whether
  the placeholder's document changed, which costs PhotoCraft nothing, and only then whether the
  placeholder is still there, at most every two seconds (reading a document's layers makes
  PhotoCraft measure them all); it never switches documents. Once the placeholder is gone, or its
  document closed, the job leaves ComfyUI's queue, or is stopped if it already runs (only that
  job), and nothing is placed. A cancel is final: undoing the deletion brings back the card alone,
  with no generation behind it; delete it again. A deletion undone before the bridge looks goes
  unnoticed, and the run goes on. Two limits: a Nano Banana image already requested from comfy.org is billed anyway, and
  a workflow run by a command goes to its end, its result placed only if the card is back by then.
- `remove` first shows the model PhotoCraft's classical Content-Aware Fill of the selection: given
  the object itself, an edit model tends to redraw it.
- **Variations** (`--variations N`): the region is uploaded once and the N graphs (one seed each)
  are queued at once; each result is pasted into one group carrying the selection's mask as soon as
  it comes, named `Variation <n> · seed <s> · <run>` (what PhotoCraft XP's picker and a re-run
  read). Deleting the group stops those still to come; a failure keeps those that came.
- **Runs side by side** each work in their own folder of the work dir, and edit PhotoCraft only
  while holding a lock file, so two runs never switch the active document under each other.
  ComfyUI's ten-minute timeout counts from a prompt's start, not from its queueing.
- **One undo step per result**: a run's edits share one History step (PhotoCraft's `coalesce`),
  so a run never pushes your own steps out of the 50 History keeps.

## Install from source

The releases need nothing else; from source you need:

- PhotoCraft desktop, started with its control server and the bridge's work folder as automation
  roots (below). The [PhotoCraft fork](https://github.com/Avgilles/photocraft) adds a task bar under
  the selection and an **XP** menu that run this bridge; the command line works with any PhotoCraft.
- A ComfyUI server, with the models of the workflows you use (see [Workflows](#workflows)).
- Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/Avgilles/photocraft-bridge-AI
xp-photocraft connect http://127.0.0.1:8188   # your ComfyUI; saved for every run
xp-photocraft doctor                          # checks PhotoCraft, ComfyUI, workflows, models
```

## Start PhotoCraft for the bridge

The bridge and PhotoCraft share **one folder**, granted as both automation roots (PhotoCraft refuses
any path outside them). It lives in the bridge's data folder: `%LOCALAPPDATA%\xp-photocraft` on
Windows, `$XDG_DATA_HOME/xp-photocraft` or `~/.local/share/xp-photocraft` on macOS and Linux.

```powershell
# Windows
$work = "$env:LOCALAPPDATA\xp-photocraft\work"; New-Item -ItemType Directory -Force $work
photocraft.exe --control 7878 --control-token-file "$work\control.token" `
  --automation-read-root $work --automation-write-root $work
```

```bash
# macOS, Linux
work="${XDG_DATA_HOME:-$HOME/.local/share}/xp-photocraft/work"; mkdir -p "$work"
photocraft --control 7878 --control-token-file "$work/control.token" \
  --automation-read-root "$work" --automation-write-root "$work"
```

## Command line

The fork's task bar runs these commands; you can run them yourself too:

```bash
xp-photocraft fill --prompt "a clean white licence plate, same night lighting"
xp-photocraft fill --prompt "a dragon" --variations 5            # five seeds, one group
xp-photocraft fill --prompt "a dragon" --variations 3 --vary 3.steps=4..12 --set 3.cfg=1.5
xp-photocraft remove --variations 3
xp-photocraft rerun --run 142233-9f1c --seed 812 --group 57 --prompt "a red dragon"
```

`rerun` takes what a variation's layer name says (`Variation 2 · seed 812 · 142233-9f1c`) and the
group's layer id; PhotoCraft XP's ↻ does it for you.

Each command prints one JSON line on stdout (`fill@1`, `connect@1`, `doctor@1`, `workflows@1`,
`import@1`, `params@1`) and a readable report on stderr, whose last line is meant for a status bar:
it never prints the server's address or a key.

## Connect to a ComfyUI server

`xp-photocraft connect <url>` checks that a ComfyUI answers and saves it in `connection.json` (data
folder), for every command and for the fork's XP menu. Until one is saved, ComfyUI's own default
`http://127.0.0.1:8188` is used; `--server` overrides it for one run.

| Setting | Option | Environment variable | Default |
|---|---|---|---|
| ComfyUI URL | `connect` / `--server` | — | saved connection, else `http://127.0.0.1:8188` |
| PhotoCraft control port | `--port` | `PHOTOCRAFT_CONTROL_PORT` | `7878` |
| Shared work folder | `--work` | `XP_PHOTOCRAFT_WORK` | `<data folder>/work` |
| comfy.org API key (partner nodes) | `.env` in the data folder | `XP_PHOTOCRAFT_COMFY_API_KEY` | none |

A GPU on another machine: an **SSH tunnel** (`ssh -N -L 8188:127.0.0.1:8188 you@gpu-machine`, then
the default address works), or ComfyUI started with `--listen` on a **trusted LAN**. ComfyUI has no
authentication: never expose its port to the internet.

## Workflows

Each action (`fill`, `remove`) runs one workflow. A workflow is **a folder** of the data folder's
`workflows` folder, named as the menus show it, holding `workflow.json` (the graph exported from
ComfyUI) and optionally `app.json` (the same graph saved from ComfyUI's App Builder: its
[settings](#settings-comfyui-app-mode)). A folder above it is its **category**, a submenu of the XP
menu (one level):

```
workflows/
  Local/Qwen Edit 2511 (ComfyUI)/workflow.json
  Local/Qwen Image 2.1 Turbo (non-commercial)/workflow.json
  Cloud/Nano Banana 2.1 (comfy.org)/workflow.json
  Flux Fill/workflow.json, app.json
```

**Import** does it for you, from the XP menu (*Import Workflow…*) or the command line: it takes an
export (and the `.app.json` saved beside it) or a whole folder, refuses a file that is not an API
export or lacks the `pc:*` titles, and says which node types or model files the server lacks.

```bash
xp-photocraft import "Flux Fill.json" --category Local   # Flux Fill.app.json comes along
xp-photocraft workflows                  # every workflow, its category, the starred and recent
xp-photocraft assign fill "Flux Fill"    # Generative Fill now runs it
xp-photocraft favorite "Flux Fill"       # starred: listed first (--off to unstar)
xp-photocraft fill --prompt "..." --workflow qwen-edit   # one run with another workflow
```

A 0.1 catalog (graphs dropped loose in `workflows`) still works; the installer moves them into
folders. `workflows.json` in the data folder keeps the assignments, the starred and recent
workflows and the settings last used, and can declare a workflow by hand — a graph elsewhere, an
external command, another label ([example](examples/workflows.json)).

### Built-in: `qwen-edit`

Qwen Image Edit 2511 with the 4-step Lightning LoRA, ComfyUI core nodes only. The region is
generated at its own size (clamped between 0.25 and 1 megapixel, see `pc:scale` below), with the
reference latent encoded at that same size and the mask feathered: a small selection no longer
costs a full-megapixel run. It uses the files
ComfyUI's own *Qwen Image Edit 2511* template downloads, found by file name in any subfolder:

| Folder | File |
|---|---|
| `diffusion_models` | `qwen_image_edit_2511_fp8mixed.safetensors` (or the `int8_convrot` / `bf16` variant) |
| `text_encoders` | `qwen_2.5_vl_7b_fp8_scaled.safetensors` |
| `vae` | `qwen_image_vae.safetensors` |
| `loras` | `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` |

The graph is a plain API file, [`src/xp_photocraft/qwen-edit-2511.api.json`](src/xp_photocraft/qwen-edit-2511.api.json).
A release puts it in the `workflows` folder as
[`Local/Qwen Edit 2511 (ComfyUI)`](examples/workflows/Local/Qwen%20Edit%202511%20(ComfyUI)/workflow.json):
that folder *is* the built-in workflow (one menu entry; edit it to change the default, delete it and
the copy inside the bridge takes over). Its loaders follow the server's files: the `int8_convrot` or `bf16` variant if
that is what the server has, and any subfolder.

### Your own ComfyUI workflow

Build it in ComfyUI, save it with **Workflow ▸ Export (API)**, and give a few nodes a title (right
click ▸ Title) so the bridge knows where things go:

| Title | Node | What the bridge does |
|---|---|---|
| `pc:image` | Load Image | loads the selection plus a 96 px margin (sRGB PNG) |
| `pc:prompt` | the node with the prompt | sets its `prompt` or `text` input; a text holding `{prompt}` is kept around what you type |
| `pc:mask` *(optional)* | Load Image / Load Image (as Mask) | loads the mask: white = repaint |
| `pc:seed` *(optional)* | the sampler | sets `seed` or `noise_seed` (else the prompt node's own `seed`) |
| `pc:output` *(optional)* | Save Image | keeps this image (else the first saved one) |
| `pc:scale` *(optional)* | Image Scale To Total Pixels, or Qwen Image 2.1's text encoder | sets `megapixels` (or `resolution`, the side of a square of that area) to the region's own size, clamped to 0.25–1 MP |

A title can carry several tags, space-separated: Qwen Image 2.1's text encoder is
`pc:prompt pc:scale`.

Then import it (XP menu ▸ *Import Workflow…*). A model that needs instructions around what you
type gets them in the prompt node itself, before the export: `Image 2 is a mask… In the white area:
{prompt}.` (or in a `"prompt"` entry of `workflows.json`). The result is resized to the region and
masked by your selection, whatever size the graph returns.

### Settings (ComfyUI App Mode)

In ComfyUI, **App Mode ▸ App Builder** lets you pick which inputs of a graph its app shows (steps,
guidance, a sampler, Nano Banana's options…), name them and describe them. Save that app beside the
export (`Flux Fill.app.json` next to `Flux Fill.json`) and import both: PhotoCraft XP's ⚙ shows
those fields, typed and bounded as ComfyUI declares them, and each can be spread over the
variations. The bridge reads the app's `extra.linearData` and sets the same node's input in the
API export, so re-export both after editing the graph. The bridge's own inputs (the `pc:*` titles)
are never settings; a field promoted from a subgraph is not supported yet (the import says so).

```bash
xp-photocraft params "Flux Fill"         # its settings, and those it last ran with
```

### Shipped: Qwen Image 2.1 Turbo (local, non-commercial)

[`Local/Qwen Image 2.1 Turbo (non-commercial)`](examples/workflows/Local/Qwen%20Image%202.1%20Turbo%20(non-commercial)/workflow.json)
edits with Qwen Image 2.1 and its Turbo LoRA (8 steps), ComfyUI core nodes only (ComfyUI 0.39 or
later), the mask as its `<image2>`, generated at the region's size. `install-comfyui` asks whether
to install it; its files come from
[Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) (about 18 GB):

| Folder | File |
|---|---|
| `diffusion_models` | `qwen_image_2.1_int8_convrot.safetensors` |
| `text_encoders` | `qwen3vl_8b_int8_convrot.safetensors` |
| `vae` | `qwen_image_2.1_vae_bf16.safetensors` |
| `loras` | `qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` |

On the demo's four gestures (a plate, a logo, a person and their shadow, a dragon), with one RTX
3090, it took 12 to 15 s each, against 18 to 47 s for Nano Banana, at a comparable quality.
On a ComfyUI without PyTorch CUDA 13 (an older NVIDIA driver), start it with `--fp32-text-enc`
(the installer's `start-comfyui` does): otherwise the int8 text encoder overflows in fp16 and the
area comes back black.
**Its weights are for research and evaluation only** (Qwen Research License: "You shall not use
the Materials for any commercial purpose without obtaining a separate commercial license"); for
paid work, use the built-in Qwen Image Edit 2511 (Apache-2.0) or a commercial model.

### Partner nodes: Nano Banana and others

ComfyUI's API nodes run on comfy.org and bill your account. Give the bridge your comfy.org API key,
either in `XP_PHOTOCRAFT_COMFY_API_KEY` or in the data folder's `.env` file (same name; a release
ships `.env.example`); it is passed with each run (never printed, never written anywhere else).
[`Cloud/Nano Banana 2.1 (comfy.org)`](examples/workflows/Cloud/Nano%20Banana%202.1%20(comfy.org)/workflow.json)
edits with Gemini Nano Banana 2.1, the mask as its Image 2 (it has no mask input), with the prompt
that explains the mask; a release ships it in `data/workflows`. The example uses the node's format
of recent ComfyUI releases; on another version, export the graph from your own ComfyUI and title
its nodes as above.

### Any other command

A workflow can also be a command (`"command": ["python", "/path/to/my_runner.py"]`) speaking
**`xp-photocraft/runner@1`**: the bridge writes `request.json` in the work folder
(`{"contract", "image", "mask", "prompt", "seed", "mode"}`, `mode` being `fill` or `remove`) and passes
its path as the last argument. The command prints one JSON line `{"image": "<png>"}` (absolute, or
relative to the work folder), or exits non-zero with a short error as the last line of stderr, shown
in PhotoCraft's status bar. Commands never reach PhotoCraft: `workflows` shows ids and labels only.

## Where the results go

Each result becomes a layer, and is also kept **next to the document's file**:
`<document folder>/xp-work/<document name>/<time>_<action>_<seed>.png`, with a `.json` beside it
(prompt, workflow, seed, settings, run, selection and placed bounds), and each run's region, mask
and description in `xp-work/<document name>/runs/<run>` (what a re-run starts from). Fifteen
projects, fifteen `xp-work` folders, nothing piling up in one place. A document never saved has
nowhere to keep them: the fork's task bar asks to save it first (Save…, Continue without, Cancel).
The bridge's own work folder keeps its ten newest runs, one folder each.

## Limits

- The result is pasted through the clipboard (PhotoCraft does not let automation place a file into
  an open document), so a run **overwrites the clipboard**.
- Undoing a run's steps brings its placeholder back, as a plain layer.
- A variation of a document never saved can be run again only while the work folder keeps its run
  (its ten newest runs).
- PhotoCraft and a local ComfyUI share the graphics card: with 8 GB, a generation can take all of
  it and PhotoCraft closes. Use ComfyUI on another PC, or Nano Banana, there.
- The built-in workflow generates at one megapixel at most; very large selections lose
  detail.

## Credits

- [PhotoCraft](https://github.com/storytold/photocraft) by storytold, the app this bridge drives
  (MIT or Apache-2.0); the PhotoCraft XP build adds only the task bar and the XP menu.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI), and the model files repackaged by
  [Comfy-Org](https://huggingface.co/Comfy-Org).
- Qwen Image Edit 2511 and Qwen Image 2.1 by the [Qwen team](https://github.com/QwenLM); the
  Lightning LoRA by [lightx2v](https://huggingface.co/lightx2v); Nano Banana (Gemini) through
  comfy.org's partner nodes.

An independent project, not affiliated with any of them.

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option, like PhotoCraft.
The models keep their own licenses (see each workflow above).
