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
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import Gdk

import sys
import os
import tempfile
import subprocess
from pathlib import Path
import locale
import gettext

# Internationalization setup
PLUGIN_NAME = "python-fu-aiimage"
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

# Default paths
DEFAULT_DIFFUSION_MODEL = MODELS_PATH + "/diffusion_models/boogu-edit-dit-Q4_0.gguf"
DEFAULT_LLM = LLM_PATH + "/Qwen3-VL-8B-Instruct-UD-IQ3_XXS.gguf"
DEFAULT_LLM_VISION = LLM_PATH + "/mmproj-F16.gguf"
DEFAULT_VAE = MODELS_PATH + "/vae/ae.safetensors"

def aiimage_func(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PLUGIN_NAME)

        dialog = Gtk.Dialog(title=_("AI Image"), transient_for=None)
        dialog.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL,
                           _("_OK"), Gtk.ResponseType.OK)
        dialog.set_default_size(600, 500)
        dialog.set_resizable(True)

        grid = Gtk.Grid()
        grid.set_border_width(12)
        grid.set_row_spacing(6)
        grid.set_column_spacing(8)
        dialog.get_content_area().add(grid)

        row = 0

        def add_file_row(label_text, prop_name, default):
            nonlocal row
            label = Gtk.Label.new_with_mnemonic(label_text)
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(False)
            entry = Gtk.Entry()
            entry.set_text(config.get_property(prop_name) or default)
            entry.set_hexpand(True)
            entry.set_valign(Gtk.Align.CENTER)
            label.set_mnemonic_widget(entry)

            def on_entry_changed(e, pn=prop_name):
                config.set_property(pn, e.get_text())

            entry.connect("changed", on_entry_changed)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            row += 1
            return entry

        def add_spin_row(label_text, prop_name, default, min_val, max_val):
            nonlocal row
            label = Gtk.Label.new_with_mnemonic(label_text)
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(False)
            adjustment = Gtk.Adjustment(value=default, lower=min_val,
                                        upper=max_val, step_incr=1, page_incr=64)
            spin = Gtk.SpinButton(adjustment=adjustment)
            spin.set_hexpand(True)
            spin.set_valign(Gtk.Align.CENTER)
            label.set_mnemonic_widget(spin)

            def on_spin_changed(s, pn=prop_name):
                config.set_property(pn, s.get_value_as_int())

            spin.connect("value-changed", on_spin_changed)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            row += 1
            return spin

        add_file_row(_("Diffusion _Model:"), "diffusion-model", DEFAULT_DIFFUSION_MODEL)
        add_file_row(_("_LLM:"), "llm", DEFAULT_LLM)
        add_file_row(_("LLM _Vision:"), "llm-vision", DEFAULT_LLM_VISION)
        add_file_row(_("_VAE:"), "vae", DEFAULT_VAE)
        add_file_row(_("T5_X_XL:"), "t5xxl", "")
        add_file_row(_("_T5:"), "t5", "")
        add_file_row(_("LoR_A:"), "lora", "")
        add_spin_row(_("_Width:"), "width", 1024, 64, 8192)
        add_spin_row(_("_Height:"), "height", 1024, 64, 8192)

        # Prompt: multi-line text view
        prompt_label = Gtk.Label.new_with_mnemonic(_("_Prompt:"))
        prompt_label.set_halign(Gtk.Align.START)
        prompt_label.set_valign(Gtk.Align.START)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(120)

        text_view = Gtk.TextView()
        text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        text_view.set_hexpand(True)
        text_view.set_vexpand(True)
        prompt_text = config.get_property("prompt")
        if prompt_text:
            text_view.get_buffer().set_text(prompt_text, len(prompt_text))

        def on_text_changed(buf):
            config.set_property("prompt", buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))

        text_view.get_buffer().connect("changed", on_text_changed)
        prompt_label.set_mnemonic_widget(text_view)

        # Shift+Enter submits the dialog
        def on_text_view_key(view, event, dlg):
            if event.keyval == Gdk.KEY_Return and (event.state & Gdk.ModifierType.SHIFT_MASK):
                dlg.response(Gtk.ResponseType.OK)
                return True
            return False

        text_view.connect("key-press-event", on_text_view_key, dialog)

        scrolled.add(text_view)
        grid.attach(prompt_label, 0, row, 1, 1)
        grid.attach(scrolled, 1, row, 1, 1)

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    input_path = None
    output_path = None

    try:
        temp_dir = Path(tempfile.gettempdir())
        output_path = temp_dir / f"gimp_aiimage_output_{os.getpid()}.png"

        Gimp.progress_init(_("Generating AI image (this may take time)..."))
        Gimp.progress_pulse()

        # Build sd-cli command for text-to-image
        command = ["sd-cli"]

        def add_flag(flag, value):
            if value and value.strip():
                command.append(flag)
                command.append(value)

        add_flag("--diffusion-model", config.get_property("diffusion-model"))
        add_flag("--llm", config.get_property("llm"))
        add_flag("--llm_vision", config.get_property("llm-vision"))
        add_flag("--vae", config.get_property("vae"))
        add_flag("--t5xxl", config.get_property("t5xxl"))
        add_flag("--t5", config.get_property("t5"))
        add_flag("--lora", config.get_property("lora"))

        command.extend([
            "--diffusion-fa",
            "-v",
            "--offload-to-cpu",
            "--width", str(config.get_property("width")),
            "--height", str(config.get_property("height")),
            "-o", str(output_path),
            "-p", config.get_property("prompt"),
        ])

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_lines = []
        for line in process.stderr:
            stderr_lines.append(line)
            line = line.rstrip()
            if line:
                Gimp.progress_set_text(line)
                Gimp.progress_pulse()
        process.wait()

        if process.returncode != 0:
            error_message = _("AI image generation failed. Ensure 'sd-cli' is installed and working.")
            Gimp.message("%s\nError Output: %s" % (error_message, "".join(stderr_lines)))
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        if not output_path.exists():
            error_message = _("AI image generation executed but failed to create the output file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        Gimp.progress_set_text(_("Loading generated image..."))

        imported_image = Gimp.file_load(run_mode, Gio.File.new_for_path(str(output_path)))

        if not imported_image:
            error_message = _("Failed to load the generated image file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        Gimp.Display.new(imported_image)

    except Exception as e:
        Gimp.message(_("An unexpected error occurred: %s") % e)
        return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(str(e)))

    finally:
        if output_path and output_path.exists():
            os.remove(output_path)

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class AIImage(Gimp.PlugIn):
    __gtype_name__ = "AIImage"

    def do_set_i18n(self, procname):
        return True, PLUGIN_NAME, None

    def do_query_procedures(self):
        return ['python-fu-aiimage']

    def do_create_procedure(self, name):
        Gegl.init(None)

        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            aiimage_func, None)

        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.ALWAYS
        )
        procedure.set_image_types("*")

        procedure.set_documentation(
            _("AI Image"),
            _("Generates a new image using sd-cli with a diffusion model based on a text prompt."),
            name,
        )
        procedure.set_menu_label(_("_AI Image..."))
        procedure.set_attribution("sd-cli (Tool), Plugin Author",
                                  "Plugin Author",
                                  "2026")
        procedure.add_menu_path("<Image>/File/Create")

        # Diffusion model path
        procedure.add_string_argument(
            "diffusion-model", _("Diffusion _Model"), _("Path to the diffusion model GGUF file"),
            DEFAULT_DIFFUSION_MODEL, GObject.ParamFlags.READWRITE,
        )
        # LLM path
        procedure.add_string_argument(
            "llm", _("LLM"), _("Path to the LLM GGUF file"),
            DEFAULT_LLM, GObject.ParamFlags.READWRITE,
        )
        # LLM vision projector
        procedure.add_string_argument(
            "llm-vision", _("LLM _Vision"), _("Path to the LLM vision model mmproj file"),
            DEFAULT_LLM_VISION, GObject.ParamFlags.READWRITE,
        )
        # VAE path
        procedure.add_string_argument(
            "vae", _("VAE"), _("Path to the VAE model file"),
            DEFAULT_VAE, GObject.ParamFlags.READWRITE,
        )
        # T5XXL encoder path (optional)
        procedure.add_string_argument(
            "t5xxl", _("T5X_XL"), _("Path to the T5XXL encoder model (optional)"),
            "", GObject.ParamFlags.READWRITE,
        )
        # T5 encoder path (optional)
        procedure.add_string_argument(
            "t5", _("_T5"), _("Path to the T5 encoder model (optional)"),
            "", GObject.ParamFlags.READWRITE,
        )
        # LoRA model path (optional)
        procedure.add_string_argument(
            "lora", _("LoRA"), _("Path to the LoRA model (optional)"),
            "", GObject.ParamFlags.READWRITE,
        )
        # Width
        procedure.add_int_argument(
            "width", _("_Width"), _("Image width in pixels"),
            64, 8192, 1024, GObject.ParamFlags.READWRITE,
        )
        # Height
        procedure.add_int_argument(
            "height", _("_Height"), _("Image height in pixels"),
            64, 8192, 1024, GObject.ParamFlags.READWRITE,
        )
        # Prompt
        procedure.add_string_argument(
            "prompt", _("_Prompt"), _("Describe the image you want to generate"),
            "", GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(AIImage.__gtype_name__, sys.argv)
