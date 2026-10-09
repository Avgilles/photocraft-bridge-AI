# xp-photocraft — ComfyUI for PhotoCraft

**Generative Fill and Remove for [PhotoCraft](https://github.com/storytold/photocraft), on your own
ComfyUI, with your own workflows.** Select an area in PhotoCraft; `fill` repaints it from a prompt,
`remove` erases what is in it. The result comes back as a **new layer masked by your selection**:
aligned, non-destructive, and the pixels outside the selection are left untouched.

Generation runs on a ComfyUI server you control (this PC, or another PC with a GPU) with any
workflow you like: the built-in Qwen Image Edit graph, a graph you exported from ComfyUI (Flux Fill,
SDXL inpainting, a partner node such as Nano Banana…), or any command of your own. Nothing is
installed in PhotoCraft: the bridge drives it through its control protocol and talks to ComfyUI over
its HTTP API.

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
- **Keep working while it generates.** A placeholder layer, `Generative Fill (generating…)`, covers
  the selection right away: a crossed frame naming the action and the prompt. The bridge then leaves
  PhotoCraft alone until the result is ready, and puts it where the placeholder is (same document,
  just above it, same mask), handing back whatever document, layer and selection you have by then.
  Delete the placeholder to cancel.
- `remove` first shows the model PhotoCraft's classical Content-Aware Fill of the selection: given
  the object itself, an edit model tends to redraw it.

## Requirements

- PhotoCraft desktop, started with its control server and the bridge's work folder as automation
  roots (below). The [PhotoCraft fork](https://github.com/Avgilles/photocraft) adds a task bar under
  the selection and an **XP** menu that run this bridge; the command line works with any PhotoCraft.
- A ComfyUI server, with the models of the workflows you use (see [Workflows](#workflows)).
- Python 3.11+ and [uv](https://docs.astral.sh/uv/).

## Install

```bash
uv tool install git+https://github.com/Avgilles/xp-photocraft
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

## Use

```bash
xp-photocraft fill --prompt "a clean white licence plate, same night lighting"
xp-photocraft remove
```

Each command prints one JSON line on stdout (`fill@1`, `connect@1`, `doctor@1`, `workflows@1`) and a
readable report on stderr, whose last line is meant for a status bar: it never prints the server's
address or a key.

## Connect to a ComfyUI server

`xp-photocraft connect <url>` checks that a ComfyUI answers and saves it in `connection.json` (data
folder), for every command and for the fork's XP menu. Until one is saved, ComfyUI's own default
`http://127.0.0.1:8188` is used; `--server` overrides it for one run.

| Setting | Option | Environment variable | Default |
|---|---|---|---|
| ComfyUI URL | `connect` / `--server` | — | saved connection, else `http://127.0.0.1:8188` |
| PhotoCraft control port | `--port` | `PHOTOCRAFT_CONTROL_PORT` | `7878` |
| Shared work folder | `--work` | `XP_PHOTOCRAFT_WORK` | `<data folder>/work` |
| comfy.org API key (partner nodes) | — | `XP_PHOTOCRAFT_COMFY_API_KEY` | none |

A GPU on another machine: an **SSH tunnel** (`ssh -N -L 8188:127.0.0.1:8188 you@gpu-machine`, then
the default address works), or ComfyUI started with `--listen` on a **trusted LAN**. ComfyUI has no
authentication: never expose its port to the internet.

## Workflows

Each action (`fill`, `remove`) runs one workflow. `workflows.json` in the data folder adds yours and
assigns them ([example](examples/workflows.json)); the fork's XP menu does the same with a click.

```bash
xp-photocraft workflows                  # every workflow, and the one each action runs
xp-photocraft assign fill nano-banana    # Generative Fill now runs nano-banana
xp-photocraft fill --prompt "..." --workflow qwen-edit   # one run with another workflow
```

### Built-in: `qwen-edit`

Qwen Image Edit 2511 with the 4-step Lightning LoRA, ComfyUI core nodes only. It uses the files
ComfyUI's own *Qwen Image Edit 2511* template downloads, found by file name in any subfolder:

| Folder | File |
|---|---|
| `diffusion_models` | `qwen_image_edit_2511_fp8mixed.safetensors` (or the `int8_convrot` / `bf16` variant) |
| `text_encoders` | `qwen_2.5_vl_7b_fp8_scaled.safetensors` |
| `vae` | `qwen_image_vae.safetensors` |
| `loras` | `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` |

The graph is a plain API file, [`src/xp_photocraft/qwen-edit-2511.api.json`](src/xp_photocraft/qwen-edit-2511.api.json):
copy it next to your `workflows.json` as a starting point for your own settings (the
[example](examples/workflows.json) declares it as `qwen-custom`).

### Your own ComfyUI workflow

Build it in ComfyUI, save it with **Workflow ▸ Export (API)**, and give a few nodes a title (right
click ▸ Title) so the bridge knows where things go:

| Title | Node | What the bridge does |
|---|---|---|
| `pc:image` | Load Image | loads the selection plus a 96 px margin (sRGB PNG) |
| `pc:prompt` | the node with the prompt | sets its `prompt` or `text` input |
| `pc:mask` *(optional)* | Load Image / Load Image (as Mask) | loads the mask: white = repaint |
| `pc:seed` *(optional)* | the sampler | sets `seed` or `noise_seed` (else the prompt node's own `seed`) |
| `pc:output` *(optional)* | Save Image | keeps this image (else the first saved one) |

Then declare it, with a path relative to `workflows.json`:

```json
{"workflows": {"flux-fill": {"label": "Flux Fill", "graph": "flux_fill_api.json"}}}
```

`"prompt"` wraps what you type, for models that need instructions around it
(`"Image 2 is a mask… In the white area: {prompt}."`). The result is resized to the region and
masked by your selection, whatever size the graph returns.

### Partner nodes: Nano Banana and others

ComfyUI's API nodes run on comfy.org and bill your account. Set your comfy.org API key in
`XP_PHOTOCRAFT_COMFY_API_KEY`; the bridge passes it with each run (never printed, never saved).
[`examples/nano-banana-edit.api.json`](examples/nano-banana-edit.api.json) edits with Gemini Nano
Banana 2.1, the mask as its Image 2 (it has no mask input), and
[`examples/workflows.json`](examples/workflows.json) gives it the prompt that explains the mask.
The example uses the node's format of recent ComfyUI releases; on another version, export the
graph from your own ComfyUI and title its nodes as above.

### Any other command

A workflow can also be a command (`"command": ["python", "/path/to/my_runner.py"]`) speaking
**`xp-photocraft/runner@1`**: the bridge writes `request.json` in the work folder
(`{"contract", "image", "mask", "prompt", "seed", "mode"}`, `mode` being `fill` or `remove`) and passes
its path as the last argument. The command prints one JSON line `{"image": "<png>"}` (absolute, or
relative to the work folder), or exits non-zero with a short error as the last line of stderr, shown
in PhotoCraft's status bar. Commands never reach PhotoCraft: `workflows` shows ids and labels only.

## Limits

- The result is pasted through the clipboard (PhotoCraft does not let automation place a file into
  an open document), so a run **overwrites the clipboard**.
- One run leaves about twenty history steps (the placeholder's, then the result's), interleaved
  with yours when you keep working: undoing part of them brings the placeholder back.
- One generation at a time.
- The built-in workflow resizes the region to about one megapixel; very large selections lose
  detail.

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option, like PhotoCraft.
