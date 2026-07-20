# upscale.py
A GIMP 3 plugin for AI image upscaling supporting three backends:

- **Spandrel** (`image_gen_aux`) — UltraSharp, DAT2, Remacri
- **LDM** (`diffusers`) — CompVis latent diffusion
- **SD Upscale** (`diffusers`) — Stability AI text-guided 4x upscaler

## How it works

1. The plugin saves the current layer to a temp PNG,
2. runs the selected AI upscaler via PyTorch (CUDA if available),
3. and loads the upscaled result as a new layer.

**Make it your own.** Edit `upscale.py` with any text editor to change the default model, add new models, or configure inference parameters. The plugin supports Spandrel (fast, tile-based), LDM (latent diffusion), and SD Upscale (text-guided) models — mix and match!

## Changing the model

Edit `DEFAULT_MODEL` in `upscale.py` to any key from `MODEL_CONFIGS`:

| Model | Type | Scale | Notes |
|-------|------|-------|-------|
| `stabilityai/stable-diffusion-x4-upscaler` | sd_upscale | 4x | Text-guided, safetensors, 20 steps, default |
| `Kim2091/UltraSharp` | spandrel | 4x | Fast, lightweight, sharp |
| `Phips/4xBHI_dat2_real` | spandrel | 4x | DAT2, handles noise/blur/compression |
| `Phips/4xRealWebPhoto_v4_dat2` | spandrel | 4x | DAT2, optimized for web photos |
| `OzzyGT/DAT_X4` | spandrel | 4x | Original DAT transformer |
| `OzzyGT/4xRemacri` | spandrel | 4x | BSRGAN, photo-realistic |
| `CompVis/ldm-super-resolution-4x-openimages` | ldm | 4x | Latent diffusion, 50 steps |

## Dependencies

1. **Before installing**, make sure you have Gimp version 3 or above. That should ensure you have the necessary Python environment and any required libraries.
2. **Install the packages** with pip:
    ```shell
    pip install image_gen_aux diffusers torch pillow
    ```
3. CUDA GPU is strongly recommended for reasonable performance.

## Plugin setup

Updated plugin is available from https://github.com/themanyone/upscale

    ```shell
    cd ~/.config/GIMP/3.2/plug-ins/
    git clone https://github.com/themanyone/upscale.git
    ```

**Restart GIMP:** The "Upscale..." plugin should now appear in your GIMP filters menu. The AI is not the fastest. It might take 30 seconds or more to automatically download the model the first time it is used. You may change what menu to place it on by modifying this line near the bottom of `upscale.py`:

    ```python
        # Add to the Layer/Transparency menu
        procedure.add_menu_path ("<Image>/Filters/AI/")
    ```

## Thanks for trying out bgremove!
* GitHub https://github.com/themanyone
* YouTube https://www.youtube.com/themanyone
* Mastodon https://mastodon.social/@themanyone
* Linkedin https://www.linkedin.com/in/henry-kroll-iii-93860426/
* Buy me a coffee https://buymeacoffee.com/isreality
* TheNerdShow.com

