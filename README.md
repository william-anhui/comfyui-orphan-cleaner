# comfyui-orphan-cleaner

Find and remove ComfyUI models that none of your saved workflows use, and get your disk space back.

ComfyUI models are huge (a single checkpoint can be 5-25 GB). After months of trying templates and workflows, your `models/` folder fills up with files you will never load again. This script scans your saved workflows, works out which model files are actually referenced, and reports the rest as **orphans**. You can then move them aside or delete them.

- One file, no dependencies, Python 3.8+
- Works on Windows, macOS and Linux
- Finds your ComfyUI folder automatically
- Safe by default: it only prints a report. Cleaning is opt-in, and permanent deletion needs typed confirmation

## Quick start

1. Download `comfyui_orphan_cleaner.py` (anywhere is fine).
2. Close ComfyUI.
3. Run it:

   ```
   python comfyui_orphan_cleaner.py
   ```

4. Read the report. Example (made-up numbers):

   ```
   ComfyUI folder : C:\Users\you\Documents\ComfyUI  (auto-detected)
   Workflows read : 15  (from 1 folder(s))
   Model files    : 33  (ignored folders: configs, embeddings, vae_approx)

   ORPHAN models (not used by any workflow), largest first:
       12.40 GB  checkpoints/old_experiment.safetensors
        6.20 GB  loras/test_style.safetensors

   Summary: 2 orphan file(s) = 18.60 GB, 31 used file(s).

   DRY RUN: nothing was changed.
   ```

5. Happy with the list? Clean up:

   ```
   python comfyui_orphan_cleaner.py --move      # safe: moves orphans into models/_orphan_models
   python comfyui_orphan_cleaner.py --delete    # permanent: asks you to type DELETE
   python comfyui_orphan_cleaner.py --purge     # permanent: empties models/_orphan_models later
   ```

Tip: try `--move` first. If nothing breaks after a few days, run `python comfyui_orphan_cleaner.py --purge` to delete the `_orphan_models` folder for good.

## Options

| Option | What it does |
|---|---|
| *(none)* | Dry run. Prints the report, changes nothing. |
| `COMFYUI_DIR` (positional) | Path of your ComfyUI folder (the one containing `models` and `user`). Default: auto-detect. |
| `--show-used` | Also list the models that are used, and which workflows use them. |
| `--move` | Move orphans into `<models>/_orphan_models/`, keeping the folder layout. Nothing is deleted. |
| `--delete` | **Permanently** delete orphans. You must type `DELETE` to confirm. No Recycle Bin. |
| `--purge` | **Permanently** delete the `_orphan_models` folder left by an earlier `--move`. You must type `DELETE` to confirm. |
| `--force` | Allow `--move` / `--delete` even if some workflow files could not be read. |
| `--extra-models DIR` | Also scan another models folder (for `extra_model_paths.yaml` setups). Repeatable. |
| `--extra-workflows DIR` | Also count workflow `.json` files in this folder as usage. Repeatable. |
| `--skip a,b,c` | Model sub-folders to ignore. Default: `vae_approx,embeddings,configs`. |

`--move`, `--delete` and `--purge` cannot be combined.

## How it decides what is an orphan

1. It reads every `.json` file under `<ComfyUI>/user/*/workflows` (plus any `--extra-workflows`).
2. It collects every string that looks like a model file name (`.safetensors`, `.ckpt`, `.pt`, `.pth`, `.bin`, `.gguf`, `.onnx`, `.sft`, `.pkl`). Nodes inside subgraphs and muted/bypassed nodes count as usage.
3. A model file is **used** if its file name appears in any workflow. Matching is by file name only (the sub-folder is ignored), so it leans towards "used".
4. Everything else is an **orphan**.

Folders ignored by default, because ComfyUI uses their files without naming them in a workflow: `vae_approx`, `embeddings`, `configs`.

## How the ComfyUI folder is found

In this order: the command-line argument, the `COMFYUI_DIR` environment variable, the `COMFY_DIR` setting at the top of the script, then auto-detection. Auto-detection checks:

- the current folder and the script's folder (and a `ComfyUI` or `ComfyUI_windows_portable/ComfyUI` folder inside them)
- `Documents/ComfyUI` (including Documents redirected to OneDrive), which is where ComfyUI Desktop installs by default
- `~/ComfyUI` and `~/comfy/ComfyUI` (git clone, comfy-cli)
- on Windows, portable builds unzipped in your home, Desktop, Downloads, `C:\` or `D:\`

A folder only counts if it contains `models/` and either `user/` or `main.py`. If nothing is found, or more than one install is found, the script stops and asks you to pass the path. It never guesses between installs.

## Safety notes (please read)

- **"Orphan" means "no saved workflow refers to it", not "never used".** The script cannot see API-format workflows stored elsewhere, custom nodes that pick models on their own, other apps sharing the folder, or workflows that only exist inside PNG metadata. Use `--extra-workflows` for folders it should also read, and prefer `--move` before `--delete`.
- **`--delete` is permanent.** No Recycle Bin, no undo.
- **Back up what you cannot re-download**, such as LoRAs you trained or checkpoints you merged yourself.
- **Close ComfyUI first.** Files that are in use cannot be moved or deleted.
- The script aborts if it finds no readable workflows (otherwise every model would look like an orphan). It also refuses to `--move` / `--delete` if any workflow file could not be parsed, unless you add `--force`.
- Provided as is, without warranty. Use at your own risk.

## Restoring

Models moved with `--move` live in `<models>/_orphan_models/<type>/...`. To restore one, move it back to `<models>/<type>/...`. To delete them for good, run `--purge`.

## Troubleshooting

**`python` is not found, or opens the Microsoft Store (Windows).** Use the Python that comes with ComfyUI:

- Portable build: `python_embeded\python.exe comfyui_orphan_cleaner.py`
- ComfyUI Desktop: `<your ComfyUI folder>\.venv\Scripts\python.exe comfyui_orphan_cleaner.py` (macOS: `.venv/bin/python`)

Or install Python 3.8+ from python.org.

**"could not find your ComfyUI folder automatically".** Pass it: `python comfyui_orphan_cleaner.py "/path/to/ComfyUI"`. On Windows in Git Bash, use forward slashes: `"C:/Users/you/Documents/ComfyUI"`.

**"no readable workflow .json files found".** Your workflows are somewhere unusual. Pass the right ComfyUI folder, or add the folder with `--extra-workflows`.

**My models live on another drive.** Add the folder with `--extra-models "D:/AI/models"` (the folder that contains `checkpoints`, `loras`, ...).

**A model I still need is listed as an orphan.** No saved workflow mentions it. Keep it (do not use `--delete`), or save a workflow that uses it.

**`[FAILED] ... in use`.** Close ComfyUI and run again.
