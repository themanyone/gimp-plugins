# AI Edit Plugin

Uses [sd-cli](https://github.com/leejet/stable-diffusion.cpp) (stable-diffusion.cpp) with a diffusion edit model and vision LLM to edit images based on text prompts.

## Usage

1. Open an image in GIMP
2. Go to Filters → AI → AI Edit...
3. Configure model paths (defaults provided) and enter your edit prompt
4. Click OK — the plugin saves the current layer, runs sd-cli, and loads the result as a new layer

## Dependencies

**stable-diffusion.cpp**

- See [sd-cli on GitHub](https://github.com/leejet/stable-diffusion.cpp) for updated install instructions.

**Get models.**

This was the first image editing model that worked for us. You may find better.

- Boogu Image (works on 8GB RTX 3070).
    - gguf: https://huggingface.co/realrebelai/Boogu-Image-Edit_GGUFs/blob/main/boogu-edit-dit-Q4_0.gguf
- Download vae
    - safetensors: https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/ae.safetensors
- Download Qwen3-VL 8B
    - gguf: https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF/blob/main/Qwen3-VL-8B-Instruct-UD-IQ3_XXS.gguf
    - mmproj: https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-F16.gguf?download=true

## Model Paths

Default paths are configured in the plugin for the author's setup. Change them in the dialog or edit the defaults at the top of `aiedit.py`.

## Menu

`<Image>/Filters/AI/` — AI Edit...

## Thanks for trying out gimp-plugins!

* GitHub https://github.com/themanyone
* YouTube https://www.youtube.com/themanyone
* Mastodon https://mastodon.social/@themanyone
* Linkedin https://www.linkedin.com/in/henry-kroll-iii-93860426/
* Buy me a coffee https://buymeacoffee.com/isreality
* TheNerdShow.com https://thenerdshow.com
