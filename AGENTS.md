# AGENTS.md — GIMP 3 Python Plugin Monorepo

## Overview

A monorepo of GIMP 3 plugins written in Python via PyGObject introspection. Each subdirectory is a self-contained plugin that GIMP loads from its `plug-ins/` directory. There is **no build system, no package manager, no tests, no CI**.

### Plugins

| Plugin | Directory | Function | External Dependencies | License |
|--------|-----------|----------|----------------------|---------|
| Background Remove | `bgremove/` | Saves layer → runs external `backgroundremover` CLI → loads result as new transparent layer | `backgroundremover` CLI tool (PyPI) | GPLv3 |
| AI Upscale | `upscale/` | Saves layer → runs PyTorch upscaler (3 backends) → loads result as new upscaled layer | `torch`, `pillow`, `image_gen_aux` / `diffusers` (Hugging Face) | GPLv3 |
| AI Image | `aiimage/` | Text-to-image generation via `sd-cli` → creates new GIMP image | `sd-cli` CLI tool | GPLv3 |
| AI Edit | `aiedit/` | Image editing via `sd-cli` with diffusion model + vision LLM | `sd-cli` CLI tool | GPLv3 |
| Test Plugin | `test_plugin/` | Minimal skeleton showing `Gimp.PlugIn` subclass | None | — |

---

## GIMP 3 Plugin Architecture

Every plugin follows this pattern:

```
#!/usr/bin/env python3
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib, Gio

class MyPlugin(Gimp.PlugIn):
    # __gtype_name__ = "MyPlugin"          # optional but recommended
    def do_query_procedures(self): ...
    def do_create_procedure(self, name): ...

Gimp.main(MyPlugin.__gtype_name__, sys.argv)
```

### Required methods

1. **`do_query_procedures()`** — returns list of procedure name strings (e.g. `["python-fu-bgremove"]`)
2. **`do_create_procedure(name)`** — creates and returns a `Gimp.ImageProcedure`:
   - Call `Gegl.init(None)` first
   - Wire a handler function (standalone function or bound method) via `Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, handler, None)`
   - Set `set_image_types()`, `set_sensitivity_mask()`, `set_menu_label()`, `add_menu_path()`, `set_attribution()`
   - Add `Gimp.Choice` arguments for configurable parameters

### Handler function signature

```python
def my_func(procedure, run_mode, image, drawables, config, data):
    # drawables is a list of Gimp.Layer
    # config gives GObject properties for dialog arguments
    ...
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
```

### GIMP 3 vs GIMP 2 gotchas

- Uses `gi.require_version('Gimp', '3.0')` — **not** `2.0` or `2.99`
- `Gimp.ImageProcedure` instead of `Gimp.PlugIn` procedural API from GIMP 2
- Plugin entry uses `Gimp.main(GType_or_string, sys.argv)` — never `Gimp.main()` with no args
- `GimpUi.ProcedureDialog` replaces old GTK dialog patterns

---

## Key Patterns Observed in the Codebase

### Save → Process → Load flow (both production plugins)

1. Export current layer to temp PNG via `Gimp.file_save(run_mode, image, Gio.File.new_for_path(path), None)`
2. Process the temp file externally (CLI or in-process ML)
3. Load processed result back via `Gimp.file_load(run_mode, Gio.File.new_for_path(path))`
4. Create a new `Gimp.Layer` in the original image
5. Copy pixel data: `Gimp.edit_copy([imported_layer])` → `Gimp.edit_paste(new_layer, False)` → `Gimp.floating_sel_anchor()` — note `edit_copy()` takes a **list** of layers
6. Hide original layer, show new layer, set `image.active_layer`
7. For upscaled images, also call `image.resize_to_layers()`

### Undo management

```python
Gimp.context_push()
image.undo_group_start()
try:
    ...
finally:
    Gimp.displays_flush()
    image.undo_group_end()
    Gimp.context_pop()
```

### Progress feedback

```python
Gimp.progress_init(_("message"))
Gimp.progress_set_text(_("message"))
Gimp.progress_pulse()
```

### Internationalization

```python
PLUGIN_NAME = "python-fu-<name>"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'locale'))
locale.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.textdomain(PLUGIN_NAME)
def _(message): return gettext.gettext(message)
def N_(message): return message
```

`locale/` directories exist but are empty (no `.mo` files yet).

### Temp file cleanup

Temp files use `os.getpid()` for uniqueness and are cleaned up in a `finally` block:

```python
input_path = temp_dir / f"gimp_<name>_input_{os.getpid()}.png"
output_path = temp_dir / f"gimp_<name>_output_{os.getpid()}.png"
```

---

## Plugin-Specific Details

### bgremove (`bgremove.py`)

- Calls `backgroundremover -i <input> -o <output>` via `subprocess.run()` (captures stdout/stderr, doesn't check)
- **Non-interactive only** — no dialog, uses `Gimp.RunMode.NONINTERACTIVE`
- Menu: `<Image>/Layer/Transparency`
- Procedure name: `python-fu-bgremove`
- Entry: `Gimp.main(BgRemove.__gtype__, sys.argv)` — uses `__gtype__` (GType object), NOT `__gtype_name__` (string)

### upscale (`upscale.py`)

- Three backend types in `MODEL_CONFIGS` dict:
  - `"spandrel"` → `UpscaleWithModel` from `image_gen_aux` (tile-based, configurable tile_size + overlap)
  - `"ldm"` → `LDMSuperResolutionPipeline` from `diffusers` (latent diffusion, configurable steps + eta)
  - `"sd_upscale"` → `StableDiffusionUpscalePipeline` from `diffusers` (text-guided, configurable prompt + steps + noise_level)
- Global `MODEL_CACHE` dict avoids reloading models across invocations
- Auto-detects CUDA: `device = "cuda" if torch.cuda.is_available() else "cpu"`
- FP16 applied for LDM/SD models on CUDA
- SD upscale enables attention slicing, VAE slicing, VAE tiling, and model CPU offload
- **Interactive mode** shows a `GimpUi.ProcedureDialog` with model selection dropdown
- Menu: `<Image>/Layer`
- Procedure name: `python-fu-upscale`
- Entry: `Gimp.main(Upscale.__gtype_name__, sys.argv)` — uses `__gtype_name__` (string)

### test_plugin (`test_plugin.py`)

- Skeleton for new plugins — good starting point
- `__gtype_name__ = "TestPlugin"` (PascalCase, no underscores — comment notes this explicitly)
- Menu: `<Image>/Filters/AI/`
- Uses `self.run` as the handler (class method)
- Entry: `Gimp.main(TestPlugin.__gtype_name__, sys.argv)`
- No i18n, no undo, minimal

### aiedit (`aiedit.py`)

- Image editing via `sd-cli` with diffusion model + vision LLM
- **Interactive mode** — custom `Gtk.Dialog` with model paths, multi-line prompt, Shift+Enter submit
- Takes an existing image, exports to temp PNG, runs `sd-cli` with `-r <input>`, loads result as new layer
- Menu: `<Image>/Filters/AI/AI Edit...`
- Procedure name: `python-fu-aiedit`
- Entry: `Gimp.main(AIEdit.__gtype_name__, sys.argv)`

### aiimage (`aiimage.py`)

- **Creation plugin** — generates new images from scratch via `sd-cli` text-to-image
- **Interactive mode** — custom `Gtk.Dialog` with model paths, width/height spin buttons, multi-line prompt, Shift+Enter submit
- Uses `Gimp.ImageProcedure` with `Gimp.ProcedureSensitivityMask.NO_IMAGE` — available even with no image open
- Creates a new `Gimp.Display` from the generated file (no undo context needed)
- Menu: `<Image>/File/Create/AI Image...`
- Procedure name: `python-fu-aiimage`
- Entry: `Gimp.main(AIImage.__gtype_name__, sys.argv)`
- Entry point must be executable (`chmod +x`) for GIMP to discover it

---

## Gotchas & Non-Obvious Patterns

### `__gtype__` vs `__gtype_name__` in `Gimp.main()`

Different plugins use different forms — both work but **`__gtype_name__` (string form) is safer**:

| Plugin | Expression |
|--------|-----------|
| bgremove | `BgRemove.__gtype__` (GType object) |
| upscale | `Upscale.__gtype_name__` (string) |
| test_plugin | `TestPlugin.__gtype_name__` (string) |

The string form doesn't require the GType to be initialized yet, so prefer it.

### `drawables[0]` goes stale

After `Gimp.file_save()`, the `drawables` list reference can become stale. Both plugins re-fetch with `drawable = drawables[0]` inside the try block (bgremove line 144, upscale line 252).

### `edit_copy()` takes a list

`Gimp.edit_copy([new_layer])` — the argument is a list of layers, not a single layer.

### f-string + gettext anti-pattern (bgremove)

```python
Gimp.message(_(f"An unexpected error occurred: {e}"))
```

The `_()` wraps an already-interpolated f-string, so translation lookup will fail for any dynamic content. Don't replicate this — use `%` formatting or `.format()` inside `_()` instead.

### Import order matters

`gi.require_version()` must be called **before** `from gi.repository import ...`. All plugins follow this correctly.

### No `requirements.txt` or dependency management

Dependencies must be installed manually. See each plugin's README for pip commands. The `.venv/` in `bgremove/` suggests venv is used but is not committed as a pattern.

---

## Installation

Plugins go in GIMP's plug-ins directory (varies by version):

- GIMP 3.0: `~/.config/GIMP/3.0/plug-ins/`
- GIMP 3.2: `~/.config/GIMP/3.2/plug-ins/`

Clone the whole repo or symlink individual plugin directories. Restart GIMP after adding/changing plugins.

---

## Code Style

- Python files use `#!/usr/bin/env python3` shebang
- Line length warnings exist (E501) throughout — the codebase does **not** strictly enforce 79 chars
- Indentation is 4 spaces
- Comments document intent, not mechanics
- Variable naming: `snake_case` for functions/variables, `PascalCase` for classes and GIMP types
- Procedure names: `python-fu-<name>` or just lowercase single word (testplugin)

---

## Diagnostics & Linting

An LSP (pylsp) is active. The project has ~50 pycodestyle E501 (line too long) and E302 (expected 2 blank lines) warnings. No errors. These are non-blocking.

---

## What This Codebase Is Good For (Template Patterns)

Both `bgremove.py` and `test_plugin.py` serve as templates for new plugins:

- **bgremove pattern**: Bridging GIMP to an external CLI tool via subprocess
- **upscale pattern**: In-process ML inference with PyTorch/Hugging Face models
- **test_plugin pattern**: Minimal `Gimp.PlugIn` skeleton to copy-paste

The common flow (save temp → process → load result → new layer → copy pixels) is reusable for any plugin that transforms image data.

---

## Key Developer Doc Locations

### GIMP 3 Python API

| Resource | URL |
|----------|-----|
| GIMP 3 API Reference | https://developer.gimp.org/api/3.0/ |
| `Gimp.Procedure` / `Gimp.ImageProcedure` | https://developer.gimp.org/api/3.0/class.ImageProcedure.html |
| `Procedure.add_menu_path()` | https://developer.gimp.org/api/3.0/libgimp/method.Procedure.add_menu_path.html |
| `Procedure.set_sensitivity_mask()` | https://developer.gimp.org/api/3.0/libgimp/method.Procedure.set_sensitivity_mask.html |
| `ProcedureSensitivityMask` flags | https://developer.gimp.org/api/3.0/libgimp/flags.ProcedureSensitivityMask.html |
| `Gimp.PDBProcType` enum | https://developer.gimp.org/api/3.0/libgimp/enum.PDBProcType.html |
| Python Plug-in Tutorial | https://docs.gimp.org/3.0/en/gimp-using-python-plug-in-tutorial.html |
| GIMP Developer: Python Plug-Ins | https://developer.gimp.org/resource/writing-a-plug-in/tutorial-python/ |

### Useful shell commands

```bash
# List all registered procedures matching a pattern
gimp -c -b '(plug-in-info "python-fu-*")' -b '(gimp-quit 0)'

# Query a specific procedure's parameters
gimp -c -b '(plug-in-query "python-fu-aiimage")' -b '(gimp-quit 0)'

# Check GIMP plugin directory
echo ~/.config/GIMP/3.0/plug-ins/
```
