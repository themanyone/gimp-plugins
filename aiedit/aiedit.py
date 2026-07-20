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
import subprocess
from pathlib import Path
import locale
import gettext

# Internationalization setup
PLUGIN_NAME = "python-fu-aiedit"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'locale'))

locale.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)

gettext.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.textdomain(PLUGIN_NAME)

def _(message): return gettext.gettext(message)
def N_(message): return message

# Models paths
HOME_PATH = os.environ.get('HOME')
MODELS_PATH = HOME_PATH + "/Downloads/src/ComfyUI/models"
LLM_PATH = "/win/models/Qwen3-VL-8B-Instruct-UD-IQ3_XXS"

# Default paths for sd-cli models
DEFAULT_DIFFUSION_MODEL = MODELS_PATH + "/diffusion_models/boogu-edit-dit-Q4_0.gguf"
DEFAULT_LLM = LLM_PATH + "/Qwen3-VL-8B-Instruct-UD-IQ3_XXS.gguf"
DEFAULT_LLM_VISION = LLM_PATH + "/mmproj-F16.gguf"
DEFAULT_VAE = MODELS_PATH + "/vae/ae.safetensors"

def aiedit_func(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PLUGIN_NAME)
        dialog = GimpUi.ProcedureDialog.new(procedure, config, _("AI Edit"))
        dialog.fill(None)
        if not dialog.run():
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    Gimp.context_push()
    image.undo_group_start()

    if not drawables:
        return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error("No drawable provided."))

    drawable = drawables[0]
    input_path = None
    output_path = None

    try:
        temp_dir = Path(tempfile.gettempdir())
        input_path = temp_dir / f"gimp_aiedit_input_{os.getpid()}.png"
        output_path = temp_dir / f"gimp_aiedit_output_{os.getpid()}.png"

        Gimp.progress_init(_("Saving image for processing..."))

        Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE,
            image,
            Gio.File.new_for_path(str(input_path)),
            None
        )

        Gimp.progress_set_text(_("Running AI edit (this may take time)..."))
        Gimp.progress_pulse()

        # Build sd-cli command
        command = [
            "sd-cli",
            "--diffusion-model", config.get_property("diffusion-model"),
            "--llm", config.get_property("llm"),
            "--llm_vision", config.get_property("llm-vision"),
            "--vae", config.get_property("vae"),
            "--diffusion-fa",
            "-v",
            "--offload-to-cpu",
            "-r", str(input_path),
            "-o", str(output_path),
            "-p", config.get_property("prompt"),
        ]

        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            error_message = _("AI edit failed. Ensure 'sd-cli' is installed and working.")
            Gimp.message(f"{error_message}\nError Output: {result.stderr}")
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        if not output_path.exists():
            error_message = _("AI edit executed but failed to create the output file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        Gimp.progress_set_text(_("Loading processed image..."))

        imported_image = Gimp.file_load(run_mode, Gio.File.new_for_path(str(output_path)))

        if not imported_image:
            error_message = _("Failed to load the processed image file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        new_layer = imported_image.get_layers()[0]

        layer_type = Gimp.ImageType.RGBA_IMAGE
        final_layer = Gimp.Layer.new(
            image,
            _("AI Edit Layer"),
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

        final_layer.set_name(_("AI Edited"))
        final_layer.set_visible(True)
        drawable.set_visible(False)
        image.active_layer = final_layer

    except Exception as e:
        Gimp.message(_("An unexpected error occurred: %s") % e)
        return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(str(e)))

    finally:
        if input_path and input_path.exists():
            os.remove(input_path)
        if output_path and output_path.exists():
            os.remove(output_path)

    Gimp.displays_flush()
    image.undo_group_end()
    Gimp.context_pop()

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class AIEdit(Gimp.PlugIn):
    __gtype_name__ = "AIEdit"

    def do_set_i18n(self, procname):
        return True, PLUGIN_NAME, None

    def do_query_procedures(self):
        return ['python-fu-aiedit']

    def do_create_procedure(self, name):
        Gegl.init(None)

        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            aiedit_func, None)

        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)

        procedure.set_documentation(
            _("AI Edit"),
            _("Uses sd-cli with a diffusion model and vision LLM to edit the active image or layer based on a text prompt."),
            name,
        )
        procedure.set_menu_label(_("AI _Edit..."))
        procedure.set_attribution("sd-cli (Tool), Plugin Author",
                                  "Plugin Author",
                                  "2026")
        procedure.add_menu_path("<Image>/Filters/AI")

        # Diffusion model path
        procedure.add_string_argument(
            "diffusion-model", _("Diffusion _Model"), _("Path to the diffusion model GGUF file"),
            DEFAULT_DIFFUSION_MODEL, GObject.ParamFlags.READWRITE,
        )
        # LLM path
        procedure.add_string_argument(
            "llm", _("_LLM"), _("Path to the LLM GGUF file"),
            DEFAULT_LLM, GObject.ParamFlags.READWRITE,
        )
        # LLM vision projector
        procedure.add_string_argument(
            "llm-vision", _("LLM _Vision"), _("Path to the LLM vision model mmproj file"),
            DEFAULT_LLM_VISION, GObject.ParamFlags.READWRITE,
        )
        # VAE path
        procedure.add_string_argument(
            "vae", _("_VAE"), _("Path to the VAE model file"),
            DEFAULT_VAE, GObject.ParamFlags.READWRITE,
        )
        # Prompt
        procedure.add_string_argument(
            "prompt", _("_Prompt"), _("Describe the edit you want to apply to the image"),
            "", GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(AIEdit.__gtype_name__, sys.argv)
