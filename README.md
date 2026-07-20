# GIMP 3 AI Plugins

A collection of Python-based AI plugins for **GIMP 3** (GNU Image Manipulation Program), using the GIMP 3 Python API via PyGObject introspection.

## Plugins

| Plugin | What it does | How it works | Dependencies |
|--------|-------------|--------------|--------------|
| **Background Remove** (`bgremove/`) | Removes backgrounds from images using AI | Exports layer → runs `backgroundremover` CLI → imports result as new transparent layer | `backgroundremover` (PyPI) |
| **AI Upscale** (`upscale/`) | Upscales images 4× using AI upscalers | Exports layer → runs PyTorch upscaler (3 backends) → imports result as new upscaled layer | `torch`, `pillow`, `image_gen_aux` / `diffusers` |
| **Test Plugin** (`test_plugin/`) | Minimal skeleton plugin | Hello-world GIMP 3 `Gimp.PlugIn` subclass | — |

## Security

**Arbitrary command execution.** Plugins for most applications can run any commands. This is not new. Open source relies on the community to find and fix bugs and exploits. You should always review new source code or test in a sandbox. Our plugins are not huge. The `bgremove` code is only 60 lines.

## Requirements

- **GIMP 3.0+** — these plugins use the GIMP 3 Python API (`gi.require_version('Gimp', '3.0')`)
- **Python 3** — GIMP 3 ships with its own Python environment
- **CUDA-capable GPU** — strongly recommended for the upscale plugin

## Installation

### 1. Install plugin dependencies

The `install.py` installer will attempt to perform these steps. Developers may want fine-grained control & knowledge of install locations so here goes.

**AI Edit**

See [aiedit/README.md](aiedit/README.md)

**Others.** Other plugins have their own Python dependencies. The installer will attempt to install these dependencies with `pip`.

```shell
# For Background Remove
pip install backgroundremover

# For AI Upscale
pip install image_gen_aux diffusers torch pillow

# For Stable-Diffusion-CPP
```

### 2. Place plugins in GIMP's plug-ins directory

The installer looks for the highest-numbered GIMP/xx.x/plug-ins directory.

```shell
git clone https://github.com/themanyone/gimp-plugins.git
cd gimp-plugins
ln -srf bgremove ~/.config/GIMP/3.2/plug-ins/
```

### 3. Restart GIMP

After restart, the plugins appear in the GIMP menus:
- **Background Remove**: Filters → AI → Remove Background...
- **AI Upscale**: Filters → AI → Upscale...
- **AI Image Edit**
- **Test Plugin**: Filters → AI → Test Plugin

## Plugin architecture

Every plugin follows the same pattern:

```
export layer as temp PNG → process (CLI or ML) → load result → new layer → copy pixels
```

See [AGENTS.md](AGENTS.md) for the full architecture guide and development notes.

## Customizing

### Background Remove

- This works with existing tools.
- Let's assume you have installed `backgroundremover`.

Don't want to use `backgroundremover`?
- Install any old command-line AI tool to remove backgrounds from images.
- You can use `pip install rembg` for example.
- Edit `bgremove/bgremove.py` and modify the `command` list to use a different CLI tool (e.g., `rembg` instead of `backgroundremover`).

### AI Upscale

The Upscale plugin prompts you to choose an AI model when you use the plugin in Gimp. And it allows you to save preferences. Models are downloaded automatically, so it might take some time to upscale your first image.

It is not necessary to edit `upscale/upscale.py` to:
- Change `DEFAULT_MODEL` or any key in `MODEL_CONFIGS`
- Add new upscaling models with appropriate config
- Tune inference parameters (tile_size, steps, noise_level, etc.)
...but you can!

## License

- `bgremove/` — [MIT](LICENSE)
- `upscale/` — [GNU General Public License v3.0](LICENSE)
- `test_plugin/` — None (public domain template)

## Author

**Henry Kroll III** ([@themanyone](https://github.com/themanyone))

## Thanks for trying out bgremove!
* GitHub https://github.com/themanyone
* YouTube https://www.youtube.com/themanyone
* Mastodon https://mastodon.social/@themanyone
* Linkedin https://www.linkedin.com/in/henry-kroll-iii-93860426/
* Buy me a coffee https://buymeacoffee.com/isreality
* TheNerdShow.com

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for
details.

