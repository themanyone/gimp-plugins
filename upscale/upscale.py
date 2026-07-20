#!/usr/bin/env python3
#   Copyright (C) 2026
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <https://www.gnu.org/licenses/>.

import time
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
gi.require_version('Gegl', '0.4')
from gi.repository import Gegl
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gio

import sys
import os
import tempfile
from pathlib import Path
import locale
import gettext

import torch
from PIL import Image as PILImage

# Internationalization setup
PLUGIN_NAME = "python-fu-upscale"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'locale'))

# Set up gettext for the C library (GIMP/GTK)
locale.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)

# Set up gettext for Python
gettext.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.textdomain(PLUGIN_NAME)

def _(message): return gettext.gettext(message)
def N_(message): return message # For strings that should not be translated immediately

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
# Each entry specifies the pipeline type and per-model inference parameters.
#
#   "spandrel"  — UpscaleWithModel from image_gen_aux (UltraSharp, DAT2, etc.)
#   "ldm"       — LDMSuperResolutionPipeline from diffusers (latent diffusion)
#
# To switch models, change DEFAULT_MODEL to any key below.

MODEL_CONFIGS = {
    "Kim2091/UltraSharp": {
        "type": "spandrel",
        "tile_size": 768,
        "tile_overlap": 4,
    },
    "Phips/4xBHI_dat2_real": {
        "type": "spandrel",
        "tile_size": 512,
        "tile_overlap": 4,
    },
    "Phips/4xRealWebPhoto_v4_dat2": {
        "type": "spandrel",
        "tile_size": 512,
        "tile_overlap": 4,
    },
    "OzzyGT/DAT_X4": {
        "type": "spandrel",
        "tile_size": 512,
        "tile_overlap": 4,
    },
    "OzzyGT/4xRemacri": {
        "type": "spandrel",
        "tile_size": 768,
        "tile_overlap": 4,
    },
    "CompVis/ldm-super-resolution-4x-openimages": {
        "type": "ldm",
        "num_inference_steps": 50,
        "eta": 1,
    },
    "stabilityai/stable-diffusion-x4-upscaler": {
        "type": "sd_upscale",
        "prompt": "high quality, detailed, sharp image, 8k",
        "num_inference_steps": 20,
        "noise_level": 10,
    },
}

DEFAULT_MODEL = "Kim2091/UltraSharp"
MODEL_CACHE = {}  # Cache upscaler instances across invocations

# ---------------------------------------------------------------------------
# Model loading helpers
# ---------------------------------------------------------------------------

def get_upscaler(model_id):
    """Get or create a cached upscaler for *model_id*."""
    if model_id in MODEL_CACHE:
        return MODEL_CACHE[model_id]

    cfg = MODEL_CONFIGS.get(model_id)
    if cfg is None:
        raise ValueError(_("Unknown model '%s'. Add it to MODEL_CONFIGS.") % model_id)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_type = cfg["type"]

    if model_type == "spandrel":
        from image_gen_aux import UpscaleWithModel
        upscaler = UpscaleWithModel.from_pretrained(model_id).to(device)
    elif model_type == "ldm":
        from diffusers import LDMSuperResolutionPipeline
        upscaler = LDMSuperResolutionPipeline.from_pretrained(model_id).to(device)
        # Unconditional LDM — no prompt needed; reduce fp16 OOM risk
        if device == "cuda":
            upscaler = upscaler.to(torch.float16)
    elif model_type == "sd_upscale":
        from diffusers import StableDiffusionUpscalePipeline
        dtype = torch.float16 if device == "cuda" else torch.float32
        upscaler = StableDiffusionUpscalePipeline.from_pretrained(
            model_id, variant="fp16", torch_dtype=dtype
        )
        upscaler.enable_attention_slicing()
        upscaler.enable_vae_slicing()
        upscaler.enable_vae_tiling()
        if device == "cuda":
            upscaler.enable_model_cpu_offload()
        else:
            upscaler.to(device)
    else:
        raise ValueError(_("Unsupported model type '%s' in MODEL_CONFIGS.") % model_type)

    MODEL_CACHE[model_id] = upscaler
    return upscaler


def run_upscale(upscaler, model_id, pil_image):
    """Run *upscaler* on *pil_image* according to *model_id*'s config."""
    cfg = MODEL_CONFIGS[model_id]
    model_type = cfg["type"]

    if model_type == "spandrel":
        return upscaler(
            pil_image,
            tiling=True,
            tile_width=cfg["tile_size"],
            tile_height=cfg["tile_size"],
            overlap=cfg["tile_overlap"],
        )
    elif model_type == "ldm":
        return upscaler(
            pil_image,
            num_inference_steps=cfg["num_inference_steps"],
            eta=cfg["eta"],
        ).images[0]
    else:  # sd_upscale
        return upscaler(
            prompt=cfg["prompt"],
            image=pil_image,
            num_inference_steps=cfg["num_inference_steps"],
            noise_level=cfg["noise_level"],
        ).images[0]


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def upscale_func(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PLUGIN_NAME)
        dialog = GimpUi.ProcedureDialog.new(procedure, config, _("Upscale Image"))
        dialog.fill(None)
        if not dialog.run():
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    Gimp.context_push()
    image.undo_group_start()

    if not drawables:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error("No drawable provided."))

    drawable = drawables[0]
    input_path = None
    output_path = None

    try:
        temp_dir = Path(tempfile.gettempdir())
        input_path = temp_dir / f"gimp_upscale_input_{os.getpid()}.png"
        output_path = temp_dir / f"gimp_upscale_output_{os.getpid()}.png"

        Gimp.progress_init(_("Saving image for processing..."))

        Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE,
            image,
            Gio.File.new_for_path(str(input_path)),
            None
        )

        Gimp.progress_set_text(_("Running AI upscaling (this may take time)..."))
        Gimp.progress_pulse()

        # Load image and run the selected upscaler
        pil_image = PILImage.open(str(input_path)).convert("RGB")
        model_id = config.get_property("model")
        upscaler = get_upscaler(model_id)
        pil_result = run_upscale(upscaler, model_id, pil_image)

        pil_result.save(str(output_path), "PNG")
        del pil_image, pil_result

        Gimp.progress_set_text(_("Loading upscaled image..."))

        if not output_path.exists():
            error_message = _("Upscaling failed to produce the output file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        imported_image = Gimp.file_load(run_mode, Gio.File.new_for_path(str(output_path)))
        if not imported_image:
            error_message = _("Failed to load the upscaled image file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        new_layer = imported_image.get_layers()[0]

        layer_type = Gimp.ImageType.RGBA_IMAGE
        final_layer = Gimp.Layer.new(
            image,
            _("Upscaled Layer"),
            new_layer.get_width(),
            new_layer.get_height(),
            layer_type,
            100.0,
            Gimp.LayerMode.NORMAL
        )

        drawable = drawables[0]
        image.insert_layer(final_layer, drawable.get_parent(),
                           image.get_item_position(drawable))

        Gimp.progress_set_text(_("Transferring layer data..."))
        Gimp.edit_copy([new_layer])
        floating_sel = Gimp.edit_paste(final_layer, False)
        Gimp.floating_sel_anchor(floating_sel[0])

        Gimp.Image.delete(imported_image)

        final_layer.set_name(_("Upscaled"))
        final_layer.set_visible(True)
        drawable.set_visible(False)
        image.active_layer = final_layer
        image.resize_to_layers()

    except Exception as e:
        Gimp.message(_("An unexpected error occurred: %s") % e)
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))

    finally:
        if input_path and input_path.exists():
            os.remove(input_path)
        if output_path and output_path.exists():
            os.remove(output_path)

    Gimp.displays_flush()
    image.undo_group_end()
    Gimp.context_pop()

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class Upscale (Gimp.PlugIn):
    __gtype_name__ = "Upscale"

    def do_set_i18n(self, procname):
        return True, PLUGIN_NAME, None

    def do_query_procedures(self):
        return [ 'python-fu-upscale' ]

    def do_create_procedure(self, name):
        Gegl.init(None)

        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            upscale_func, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_documentation(
            _("Upscale Image"),
            _("Uses AI to upscale the active image or layer by 4x. Supports multiple backends: Spandrel (UltraSharp, DAT2) and Diffusers (LDM)."),
            name,
        )
        procedure.set_menu_label(_("_Upscale..."))
        procedure.set_attribution("Hugging Face (image_gen_aux / diffusers)",
                                  "Plugin Author",
                                  "2026")
        procedure.add_menu_path("<Image>/Filters/AI/")

        # Model selection dropdown
        model_choice = Gimp.Choice.new()
        for i, model_id in enumerate(MODEL_CONFIGS):
            model_choice.add(model_id, i, model_id, "")
        procedure.add_choice_argument(
            "model", _("_Model"), _("Upscaling model to use"),
            model_choice, DEFAULT_MODEL, GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(Upscale.__gtype_name__, sys.argv)
