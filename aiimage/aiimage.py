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
import json
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

# Default paths
DEFAULT_DIFFUSION_MODEL = MODELS_PATH + "/diffusion_models/z-image-turbo-Q5_K_M.gguf"
DEFAULT_LLM = MODELS_PATH + "/text_encoders/qwen_3_4b.safetensors"
DEFAULT_LLM_VISION = ""
DEFAULT_VAE = MODELS_PATH + "/vae/ae.safetensors"

# Config presets directory
CONFIG_DIR = os.path.join(os.environ.get('HOME'), '.config', 'gimp-plugins', 'aiimage')
PRESETS_FILE = os.path.join(CONFIG_DIR, 'presets.json')

def load_presets():
    try:
        with open(PRESETS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_presets(presets):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PRESETS_FILE, 'w') as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)

def get_preset_names():
    presets = load_presets()
    return sorted(presets.keys())

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

        # --- Preset management row ---
        preset_label = Gtk.Label.new_with_mnemonic(_("_Preset:"))
        preset_label.set_halign(Gtk.Align.START)
        preset_label.set_hexpand(False)

        preset_combo = Gtk.ComboBoxText()
        preset_combo.set_hexpand(True)
        preset_combo.set_valign(Gtk.Align.CENTER)
        preset_label.set_mnemonic_widget(preset_combo)

        preset_names = get_preset_names()
        for name in preset_names:
            preset_combo.append_text(name)
        if preset_names:
            preset_combo.set_active(0)

        save_btn = Gtk.Button.new_with_mnemonic(_("_Save"))
        rename_btn = Gtk.Button.new_with_mnemonic(_("_Rename"))
        delete_btn = Gtk.Button.new_with_mnemonic(_("_Delete"))

        preset_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        preset_hbox.pack_start(preset_combo, True, True, 0)
        preset_hbox.pack_start(save_btn, False, False, 0)
        preset_hbox.pack_start(rename_btn, False, False, 0)
        preset_hbox.pack_start(delete_btn, False, False, 0)

        grid.attach(preset_label, 0, row, 1, 1)
        grid.attach(preset_hbox, 1, row, 1, 1)
        row += 1

        # Widget storage for preset load/save
        widgets = {}

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
            widgets[prop_name] = entry

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
                                        upper=max_val, step_increment=1, page_increment=64)
            spin = Gtk.SpinButton(adjustment=adjustment)
            spin.set_hexpand(True)
            spin.set_valign(Gtk.Align.CENTER)
            label.set_mnemonic_widget(spin)
            widgets[prop_name] = spin

            def on_spin_changed(s, pn=prop_name):
                config.set_property(pn, s.get_value_as_int())

            spin.connect("value-changed", on_spin_changed)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            row += 1
            return spin

        def add_spin_row_float(label_text, prop_name, default, min_val, max_val):
            nonlocal row
            label = Gtk.Label.new_with_mnemonic(label_text)
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(False)
            adjustment = Gtk.Adjustment(value=default, lower=min_val,
                                        upper=max_val, step_increment=0.1, page_increment=10)
            spin = Gtk.SpinButton(adjustment=adjustment, digits=1)
            spin.set_hexpand(True)
            spin.set_valign(Gtk.Align.CENTER)
            label.set_mnemonic_widget(spin)
            widgets[prop_name] = spin

            def on_spin_changed(s, pn=prop_name):
                config.set_property(pn, s.get_value())

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
        add_spin_row(_("_Steps:"), "steps", 4, 1, 100)
        add_spin_row_float(_("CFG S_cale:"), "cfg-scale", 4.0, 0.0, 30.0)
        add_spin_row_float(_("G_uida_nce:"), "guidance", 3.5, 0.0, 30.0)
        add_file_row(_("VAE _Format:"), "vae-format", "auto")
        add_file_row(_("_Prediction:"), "prediction", "")

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
        widgets["prompt"] = text_view

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

        # --- Preset callbacks ---

        def load_preset_values(preset_name):
            presets = load_presets()
            preset = presets.get(preset_name, {})
            for key, value in preset.items():
                # Set config property with correct type
                prop = procedure.find_property(key)
                if prop:
                    try:
                        if prop.value_type == GObject.TYPE_INT:
                            config.set_property(key, int(value))
                        elif prop.value_type == GObject.TYPE_DOUBLE:
                            config.set_property(key, float(value))
                        else:
                            config.set_property(key, str(value))
                    except (ValueError, TypeError):
                        pass
                # Update widget
                widget = widgets.get(key)
                if widget is None:
                    continue
                try:
                    if isinstance(widget, Gtk.Entry):
                        widget.set_text(str(value))
                    elif isinstance(widget, Gtk.SpinButton):
                        widget.set_value(float(value))
                    elif isinstance(widget, Gtk.TextView):
                        buf = widget.get_buffer()
                        text = str(value)
                        buf.set_text(text, len(text))
                except (ValueError, TypeError):
                    pass

        def on_preset_changed(combo):
            active = combo.get_active()
            if active < 0:
                return
            name = combo.get_active_text()
            if name:
                load_preset_values(name)

        preset_combo.connect("changed", on_preset_changed)

        # Load initial preset values now that widgets exist
        if preset_combo.get_active() >= 0:
            name = preset_combo.get_active_text()
            if name:
                load_preset_values(name)

        def collect_widget_values():
            values = {}
            for key, widget in widgets.items():
                try:
                    if isinstance(widget, Gtk.Entry):
                        values[key] = widget.get_text()
                    elif isinstance(widget, Gtk.SpinButton):
                        values[key] = widget.get_value()
                    elif isinstance(widget, Gtk.TextView):
                        buf = widget.get_buffer()
                        values[key] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
                except (ValueError, TypeError):
                    pass
            return values

        def on_save_preset(btn):
            values = collect_widget_values()
            name_dialog = Gtk.Dialog(title=_("Save Preset"), transient_for=dialog,
                                     flags=Gtk.DialogFlags.MODAL)
            name_dialog.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL,
                                    _("_Save"), Gtk.ResponseType.OK)
            name_dialog.set_default_size(300, -1)
            name_dialog.set_resizable(False)
            content = name_dialog.get_content_area()
            content.set_border_width(12)
            name_label = Gtk.Label(label=_("Preset name:"))
            name_label.set_halign(Gtk.Align.START)
            name_entry = Gtk.Entry()
            name_entry.set_activates_default(True)
            content.pack_start(name_label, False, False, 0)
            content.pack_start(name_entry, False, False, 6)
            name_dialog.set_default_response(Gtk.ResponseType.OK)
            content.show_all()
            response = name_dialog.run()
            name = name_entry.get_text().strip()
            name_dialog.destroy()

            if response != Gtk.ResponseType.OK or not name:
                return

            presets = load_presets()
            presets[name] = values
            save_presets(presets)

            # Update combo
            found = False
            for i in range(preset_combo.get_model().iter_n_children(None)):
                if preset_combo.get_active_text() == name:
                    found = True
                    break
            if not found:
                preset_combo.append_text(name)
            preset_combo.set_active(-1)
            for i in range(preset_combo.get_model().iter_n_children(None)):
                if preset_combo.get_model().get_value(preset_combo.get_model().get_iter(i), 0) == name:
                    preset_combo.set_active(i)
                    break

        def on_rename_preset(btn):
            active = preset_combo.get_active()
            if active < 0:
                return
            old_name = preset_combo.get_active_text()
            if not old_name:
                return

            name_dialog = Gtk.Dialog(title=_("Rename Preset"), transient_for=dialog,
                                     flags=Gtk.DialogFlags.MODAL)
            name_dialog.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL,
                                    _("_Rename"), Gtk.ResponseType.OK)
            name_dialog.set_default_size(300, -1)
            name_dialog.set_resizable(False)
            content = name_dialog.get_content_area()
            content.set_border_width(12)
            name_label = Gtk.Label(label=_("New name:"))
            name_label.set_halign(Gtk.Align.START)
            name_entry = Gtk.Entry()
            name_entry.set_text(old_name)
            name_entry.set_activates_default(True)
            content.pack_start(name_label, False, False, 0)
            content.pack_start(name_entry, False, False, 6)
            name_dialog.set_default_response(Gtk.ResponseType.OK)
            content.show_all()
            response = name_dialog.run()
            new_name = name_entry.get_text().strip()
            name_dialog.destroy()

            if response != Gtk.ResponseType.OK or not new_name or new_name == old_name:
                return

            presets = load_presets()
            presets[new_name] = presets.pop(old_name)
            save_presets(presets)

            # Update combo
            model = preset_combo.get_model()
            for i in range(model.iter_n_children(None)):
                if model.get_value(model.get_iter(i), 0) == old_name:
                    model.set_value(model.get_iter(i), 0, new_name)
                    break

        def on_delete_preset(btn):
            active = preset_combo.get_active()
            if active < 0:
                return
            name = preset_combo.get_active_text()
            if not name:
                return

            confirm = Gtk.MessageDialog(transient_for=dialog, modal=True,
                                        message_type=Gtk.MessageType.QUESTION,
                                        buttons=Gtk.ButtonsType.YES_NO,
                                        text=_("Delete preset '%s'?") % name)
            response = confirm.run()
            confirm.destroy()

            if response != Gtk.ResponseType.YES:
                return

            presets = load_presets()
            presets.pop(name, None)
            save_presets(presets)

            # Update combo
            model = preset_combo.get_model()
            iters = []
            for i in range(model.iter_n_children(None)):
                if model.get_value(model.get_iter(i), 0) == name:
                    iters.append(model.get_iter(i))
            for it in iters:
                model.remove(it)
            if model.iter_n_children(None) > 0:
                preset_combo.set_active(0)
            else:
                preset_combo.set_active(-1)

        save_btn.connect("clicked", on_save_preset)
        rename_btn.connect("clicked", on_rename_preset)
        delete_btn.connect("clicked", on_delete_preset)

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
            "--steps", str(config.get_property("steps")),
        ])

        # CFG scale for traditional models
        cfg_scale = config.get_property("cfg-scale")
        if cfg_scale is not None:
            command.extend(["--cfg-scale", str(cfg_scale)])

        # Guidance for distilled flow-matching models
        guidance = config.get_property("guidance")
        if guidance is not None:
            command.extend(["--guidance", str(guidance)])

        # VAE format override
        add_flag("--vae-format", config.get_property("vae-format"))

        # Prediction type override
        add_flag("--prediction", config.get_property("prediction"))

        command.extend([
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
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        if not output_path.exists():
            error_message = _("AI image generation executed but failed to create the output file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        Gimp.progress_set_text(_("Loading generated image..."))

        imported_image = Gimp.file_load(run_mode, Gio.File.new_for_path(str(output_path)))

        if not imported_image:
            error_message = _("Failed to load the generated image file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        Gimp.Display.new(imported_image)

    except Exception as e:
        Gimp.message(_("An unexpected error occurred: %s") % e)
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))

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
        # Steps
        procedure.add_int_argument(
            "steps", _("_Steps"), _("Number of sampling steps"),
            1, 100, 4, GObject.ParamFlags.READWRITE,
        )
        # CFG scale (traditional, for CFG-based models)
        procedure.add_double_argument(
            "cfg-scale", _("CFG S_cale"), _("Classifier-free guidance scale (traditional models)"),
            0.0, 30.0, 4.0, GObject.ParamFlags.READWRITE,
        )
        # Guidance (distilled, for flow-matching models like Z-Image-Turbo)
        procedure.add_double_argument(
            "guidance", _("G_uida_nce"), _("Distilled guidance scale for flow-matching models"),
            0.0, 30.0, 3.5, GObject.ParamFlags.READWRITE,
        )
        # VAE format override
        procedure.add_string_argument(
            "vae-format", _("VAE _Format"), _("VAE latent format: auto, flux, sd3, flux2, wan"),
            "auto", GObject.ParamFlags.READWRITE,
        )
        # Prediction type override
        procedure.add_string_argument(
            "prediction", _("_Prediction"), _("Prediction type: eps, v, sd3_flow, flux_flow, etc."),
            "", GObject.ParamFlags.READWRITE,
        )
        # Prompt
        procedure.add_string_argument(
            "prompt", _("_Prompt"), _("Describe the image you want to generate"),
            "", GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(AIImage.__gtype_name__, sys.argv)
