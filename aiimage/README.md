# AI Image

A GIMP 3 plugin that generates new images using `sd-cli` with a diffusion model based on a text prompt.

## Menu

`<Image>/File/Create/AI Image...`

## Dependencies

- `sd-cli` tool installed and available in PATH
- A diffusion model GGUF file (e.g., boogu-edit-dit)
- A VAE model file

## Usage

1. Choose **File → Create → AI Image...**
2. Configure model paths and image dimensions
3. Enter a text prompt describing the image you want
4. Press **Shift+Enter** or click **OK**

The generated image will open in a new GIMP window.

## Parameters

| Parameter | Description |
|-----------|-------------|
| Diffusion Model | Path to the diffusion model GGUF file |
| VAE | Path to the VAE model file |
| T5XXL | Path to the T5XXL encoder (optional) |
| T5 | Path to the T5 encoder (optional) |
| LoRA | Path to the LoRA model (optional) |
| Width | Image width in pixels (64–8192) |
| Height | Image height in pixels (64–8192) |
| Prompt | Text description of the image to generate |

## License

GPLv3