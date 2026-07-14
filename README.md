# GIMP 3 AI Plugins

A collection of Python-based AI plugins for **GIMP 3** (GNU Image Manipulation Program), using the GIMP 3 Python API via PyGObject introspection.

## Plugins

| Plugin | What it does | How it works | Dependencies |
|--------|-------------|--------------|--------------|
| **Background Remove** (`bgremove/`) | Removes backgrounds from images using AI | Exports layer → runs `backgroundremover` CLI → imports result as new transparent layer | `backgroundremover` (PyPI) |
| **AI Upscale** (`upscale/`) | Upscales images 4× using AI upscalers | Exports layer → runs PyTorch upscaler (3 backends) → imports result as new upscaled layer | `torch`, `pillow`, `image_gen_aux` / `diffusers` |
| **Test Plugin** (`test_plugin/`) | Minimal skeleton plugin | Hello-world GIMP 3 `Gimp.PlugIn` subclass | — |

## Requirements

- **GIMP 3.0+** — these plugins use the GIMP 3 Python API (`gi.require_version('Gimp', '3.0')`)
- **Python 3** — GIMP 3 ships with its own Python environment
- **CUDA-capable GPU** — strongly recommended for the upscale plugin

## Installation

### 1. Install plugin dependencies

Each plugin has its own Python dependencies. Install them in GIMP's Python environment:

```shell
# For Background Remove
pip install backgroundremover

# For AI Upscale
pip install image_gen_aux diffusers torch pillow
```

### 2. Place plugins in GIMP's plug-ins directory

```shell
cd ~/.config/GIMP/3.0/plug-ins/
git clone https://github.com/themanyone/gimp-plugins.git
```

Or symlink individual plugins:

```shell
ln -s /path/to/gimp-plugins/bgremove ~/.config/GIMP/3.0/plug-ins/
```

### 3. Restart GIMP

After restart, the plugins appear in the GIMP menus:
- **Background Remove**: Layer → Transparency → Remove Background...
- **AI Upscale**: Layer → Upscale...
- **Test Plugin**: Filters → AI → Test Plugin

## Plugin architecture

Every plugin follows the same pattern:

```
export layer as temp PNG → process (CLI or ML) → load result → new layer → copy pixels
```

See [AGENTS.md](AGENTS.md) for the full architecture guide and development notes.

## Customizing

### Background Remove

Edit `bgremove/bgremove.py` and modify the `command` list to use a different CLI tool (e.g., `rembg` instead of `backgroundremover`).

### AI Upscale

Edit `upscale/upscale.py` to:
- Change `DEFAULT_MODEL` to any key in `MODEL_CONFIGS`
- Add new upscaling models with appropriate config
- Tune inference parameters (tile_size, steps, noise_level, etc.)

## License

- `bgremove/` — [MIT](LICENSE)
- `upscale/` — [GNU General Public License v3.0](LICENSE)
- `test_plugin/` — None (public domain template)

## Author

**Henry Kroll III** ([@themanyone](https://github.com/themanyone))
