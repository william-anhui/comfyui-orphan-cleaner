#!/usr/bin/env python3
"""
ComfyUI Orphan Model Cleaner

Finds model files in your ComfyUI install that NO saved workflow refers to,
so you can reclaim disk space.

Default  = DRY RUN: only prints a report, nothing is touched.
--move   = moves the orphans into <models>/_orphan_models/ (same layout, easy to restore).
--delete = PERMANENTLY deletes the orphans (asks you to type DELETE first).
--purge  = PERMANENTLY deletes the _orphan_models folder left by --move (asks to confirm).

The ComfyUI folder (the one that contains models/ and user/) is found
automatically on Windows, macOS and Linux. To override it, pass it as an
argument, set the COMFYUI_DIR environment variable, or edit COMFY_DIR below.

  python comfyui_orphan_cleaner.py [COMFYUI_DIR] [--show-used] [--move | --delete | --purge]

Matching is done by file name only (the sub-folder is ignored), so it errs on
the side of "this model is used". A model is an orphan only if its file name
appears in NO workflow JSON (muted/bypassed nodes and subgraphs count as usage).
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# Optional: hard-code your ComfyUI folder to skip auto-detection, e.g.
#   COMFY_DIR = r"D:\AI\ComfyUI"
# Leave it empty to auto-detect.
COMFY_DIR = ""

EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft", ".pkl"}
QUARANTINE = "_orphan_models"
# These folders hold files that ComfyUI/custom nodes use WITHOUT naming them in a workflow
DEFAULT_SKIP = ["vae_approx", "embeddings", "configs"]


# ----------------------------------------------------------------------------
# Finding the ComfyUI folder
# ----------------------------------------------------------------------------
def looks_like_comfy(p):
    return (p / "models").is_dir() and ((p / "user").is_dir() or (p / "main.py").is_file())


def candidate_dirs():
    home = Path.home()
    cands = []

    # Next to the script / current folder (script dropped inside a portable install, etc.)
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        cands += [base, base / "ComfyUI", base / "ComfyUI_windows_portable" / "ComfyUI"]

    # "Documents" (also when Windows redirects it into OneDrive)
    docs = [home / "Documents", home / "OneDrive" / "Documents"]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.environ.get(var)
        if v:
            docs.append(Path(v) / "Documents")
    for d in docs:
        cands += [d / "ComfyUI", d / "comfy" / "ComfyUI"]  # ComfyUI Desktop / comfy-cli

    # Plain installs in the home folder (git clone, comfy-cli on Linux)
    cands += [home / "ComfyUI", home / "comfy" / "ComfyUI"]

    # Windows portable builds unzipped in the usual places
    if os.name == "nt":
        roots = [home, home / "Desktop", home / "Downloads", Path("C:/"), Path("D:/")]
        for r in roots:
            cands += [r / "ComfyUI_windows_portable" / "ComfyUI", r / "ComfyUI"]
    return cands


def find_comfy_dir():
    seen, found = set(), []
    for c in candidate_dirs():
        try:
            r = c.resolve()
            if r in seen:
                continue
            seen.add(r)
            if looks_like_comfy(r):
                found.append(r)
        except OSError:
            continue
    return found


# ----------------------------------------------------------------------------
# Scanning
# ----------------------------------------------------------------------------
def norm(s):
    return s.replace("\\", "/").strip().lstrip("/").lower()


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} GB"


def walk_strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for i in v:
            yield from walk_strings(i)
    elif isinstance(v, dict):
        for i in v.values():
            yield from walk_strings(i)


def collect_models(model_dirs, skip):
    models = []
    for root in model_dirs:
        if not root.is_dir():
            print(f"[!] Models folder not found: {root}")
            continue
        for sub in sorted(root.iterdir()):
            if not sub.is_dir() or sub.name.lower() in skip:
                continue
            for f in sub.rglob("*"):
                if f.is_file() and f.suffix.lower() in EXTS:
                    models.append({
                        "root": root,
                        "type": sub.name,
                        "file": f,
                        "rel": f.relative_to(sub).as_posix(),
                        "base": f.name.lower(),
                        "size": f.stat().st_size,
                    })
    return models


def collect_refs(wf_dirs):
    """Return ({model file name: set(workflows)}, readable count, unreadable files)."""
    refs, ok, bad = {}, 0, []
    for d in wf_dirs:
        if not d.is_dir():
            print(f"[!] Workflows folder not found: {d}")
            continue
        for f in sorted(d.rglob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
            except Exception:
                bad.append(f)
                continue
            ok += 1
            wf_name = f.relative_to(d).as_posix()
            for s in walk_strings(data):
                if len(s) > 1000:  # skip prompts / embedded blobs
                    continue
                base = norm(s.split("?")[0]).rsplit("/", 1)[-1]
                if Path(base).suffix in EXTS:
                    refs.setdefault(base, set()).add(wf_name)
    return refs, ok, bad


# ----------------------------------------------------------------------------
def purge_quarantine(model_dirs):
    """Permanently delete the _orphan_models folder(s) that --move created."""
    targets = []
    for root in model_dirs:
        q = root / QUARANTINE
        if q.is_symlink() or not q.is_dir():
            continue
        files = [f for f in q.rglob("*") if f.is_file()]
        targets.append((q, len(files), sum(f.stat().st_size for f in files)))
    if not targets:
        print(f"Nothing to purge: no '{QUARANTINE}' folder found.")
        return
    total = sum(t[2] for t in targets)
    print("Folders to purge:")
    for q, n, s in targets:
        print(f"  {human(s):>10}  {n} file(s)  {q}")
    print(f"\n!!! PERMANENT DELETE of {human(total)}. No Recycle Bin, this cannot be undone.")
    print("!!! Close ComfyUI first.")
    try:
        answer = input("Type DELETE (all caps) to confirm, anything else cancels: ")
    except EOFError:
        answer = ""
    if answer.strip() != "DELETE":
        print("Cancelled. Nothing was deleted.")
        return
    freed = 0
    for q, n, s in targets:
        try:
            shutil.rmtree(q)
            freed += s
            print(f"Deleted {q}")
        except OSError as e:
            print(f"  [FAILED] {q}: {e}")
    print(f"Freed {human(freed)}.")


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Find ComfyUI models that no workflow uses.")
    ap.add_argument("comfy_dir", nargs="?", default=None,
                    help="ComfyUI folder (contains models/ and user/). "
                         "Default: auto-detect.")
    ap.add_argument("--extra-models", action="append", default=[],
                    help="Extra models folder (from extra_model_paths.yaml). Repeatable.")
    ap.add_argument("--extra-workflows", action="append", default=[],
                    help="Extra folder with workflow .json files to count as usage. Repeatable.")
    ap.add_argument("--skip", default=",".join(DEFAULT_SKIP),
                    help="Comma-separated model sub-folders to ignore (default: %(default)s)")
    ap.add_argument("--show-used", action="store_true",
                    help="Also list the models that ARE used, with the workflows using them")
    ap.add_argument("--move", action="store_true",
                    help=f"Move orphans into <models>/{QUARANTINE}/ instead of only reporting")
    ap.add_argument("--delete", action="store_true",
                    help="PERMANENTLY delete the orphans to free disk space "
                         "(asks you to type DELETE first, no Recycle Bin)")
    ap.add_argument("--purge", action="store_true",
                    help=f"PERMANENTLY delete the {QUARANTINE} folder left by --move "
                         "(asks you to type DELETE first)")
    ap.add_argument("--force", action="store_true",
                    help="Allow --move/--delete even if some workflow files could not be read")
    args = ap.parse_args()
    if sum([args.move, args.delete, args.purge]) > 1:
        sys.exit("Use only one of --move, --delete, --purge.")

    # Which ComfyUI folder?
    given = args.comfy_dir or os.environ.get("COMFYUI_DIR") or COMFY_DIR
    if given:
        comfy, how = Path(given).expanduser(), "given"
    else:
        found = find_comfy_dir()
        if not found:
            sys.exit("ERROR: could not find your ComfyUI folder automatically.\n"
                     "Re-run with the path (the folder that contains 'models' and 'user'):\n"
                     '  python comfyui_orphan_cleaner.py "/path/to/ComfyUI"')
        if len(found) > 1:
            sys.exit("Found more than one ComfyUI folder:\n  "
                     + "\n  ".join(str(p) for p in found)
                     + "\nRe-run with the one you want:\n"
                     '  python comfyui_orphan_cleaner.py "<path>"')
        comfy, how = found[0], "auto-detected"

    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()} | {QUARANTINE}
    model_dirs = [comfy / "models"] + [Path(p).expanduser() for p in args.extra_models]
    wf_dirs = [d for d in sorted((comfy / "user").glob("*/workflows")) if d.is_dir()]
    wf_dirs += [Path(p).expanduser() for p in args.extra_workflows]

    print(f"ComfyUI folder : {comfy}  ({how})")

    if args.purge:
        purge_quarantine(model_dirs)
        return

    refs, ok, bad = collect_refs(wf_dirs)
    if ok == 0:
        sys.exit("ERROR: no readable workflow .json files found in:\n  "
                 + ("\n  ".join(str(d) for d in wf_dirs) or str(comfy / "user" / "*" / "workflows"))
                 + "\nAborting, otherwise every model would look like an orphan.")

    models = collect_models(model_dirs, skip)
    if not models:
        sys.exit("ERROR: no model files found. Check the ComfyUI folder path.")

    used = [m for m in models if m["base"] in refs]
    orphans = sorted((m for m in models if m["base"] not in refs), key=lambda m: -m["size"])

    print(f"Workflows read : {ok}  (from {len(wf_dirs)} folder(s))")
    print(f"Model files    : {len(models)}  (ignored folders: {', '.join(sorted(skip - {QUARANTINE}))})")
    if bad:
        print(f"[!] {len(bad)} workflow file(s) could NOT be read, their models may be wrongly shown as orphans:")
        for f in bad:
            print(f"      {f}")
    print()

    if args.show_used:
        print("USED models:")
        for m in sorted(used, key=lambda m: (m["type"], m["rel"])):
            wfs = sorted(refs[m["base"]])
            more = f" (+{len(wfs) - 3} more)" if len(wfs) > 3 else ""
            print(f"  {m['type']}/{m['rel']}   <- {', '.join(wfs[:3])}{more}")
        print()

    if not orphans:
        print("No orphan models. Every model file is used by at least one workflow.")
        return

    print("ORPHAN models (not used by any workflow), largest first:")
    for m in orphans:
        print(f"  {human(m['size']):>10}  {m['type']}/{m['rel']}")

    by_type = {}
    for m in orphans:
        by_type[m["type"]] = by_type.get(m["type"], 0) + m["size"]
    print("\nOrphan size per folder:")
    for t, s in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {human(s):>10}  {t}")
    total = sum(m["size"] for m in orphans)
    print(f"\nSummary: {len(orphans)} orphan file(s) = {human(total)}, "
          f"{len(used)} used file(s).")

    if not (args.move or args.delete):
        print("\nDRY RUN: nothing was changed.")
        print(f"  --move    moves the orphans into '{QUARANTINE}' (nothing is deleted)")
        print("  --delete  permanently deletes the orphans to free disk space (asks to confirm)")
        return

    if bad and not args.force:
        sys.exit("\nRefusing to continue because some workflow files were unreadable. "
                 "Fix them or re-run with --force.")

    if args.delete:
        print(f"\n!!! PERMANENT DELETE: {len(orphans)} file(s) = {human(total)} listed above.")
        print("!!! No Recycle Bin, this cannot be undone. Close ComfyUI first.")
        try:
            answer = input("Type DELETE (all caps) to confirm, anything else cancels: ")
        except EOFError:
            answer = ""
        if answer.strip() != "DELETE":
            print("Cancelled. Nothing was deleted.")
            return
        deleted, failed, freed = 0, 0, 0
        for m in orphans:
            try:
                m["file"].unlink()  # a symlink is removed itself, its target is untouched
            except OSError as e:
                failed += 1
                print(f"  [FAILED] {m['type']}/{m['rel']}: {e}")
                continue
            deleted += 1
            freed += m["size"]
            type_dir = m["root"] / m["type"]
            p = m["file"].parent
            while p != type_dir and type_dir in p.parents:  # prune emptied sub-folders
                try:
                    p.rmdir()
                except OSError:
                    break
                p = p.parent
        print(f"Deleted {deleted} file(s), freed {human(freed)}; failed {failed}.")
        return

    print(f"\nMoving orphans into <models>/{QUARANTINE}/ ... (close ComfyUI first, "
          "files in use cannot be moved)")
    moved, failed, moved_size = 0, 0, 0
    for m in orphans:
        dest = m["root"] / QUARANTINE / m["type"] / m["rel"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        n = 1
        while dest.exists():
            dest = dest.with_name(f"{dest.stem}_{n}{dest.suffix}")
            n += 1
        try:
            shutil.move(str(m["file"]), str(dest))
            moved += 1
            moved_size += m["size"]
        except OSError as e:
            failed += 1
            print(f"  [FAILED] {m['type']}/{m['rel']}: {e}")
    print(f"Moved {moved} file(s) = {human(moved_size)}; failed {failed}.")
    print(f"To free the space: run again with --purge (or delete the {QUARANTINE} folder yourself).")
    print("To restore a model: move it back to the same sub-folder under models/.")


if __name__ == "__main__":
    main()
