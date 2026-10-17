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

# Model path defaults. Windows has no HOME env var, so resolve the user
# profile explicitly; these are editable defaults shown in the dialog.
HOME_PATH = os.environ.get('HOME') or str(Path.home())
MODELS_PATH = os.path.join(HOME_PATH, "Downloads", "src", "ComfyUI", "models")
if os.name == "nt":
    LLM_PATH = os.path.join(HOME_PATH, "models", "Qwen3-VL-8B-Instruct-UD-IQ3_XXS")
else:
    LLM_PATH = "/win/models/Qwen3-VL-8B-Instruct-UD-IQ3_XXS"

# Default paths (Qwen Image 2.1 Turbo)
DEFAULT_DIFFUSION_MODEL = os.path.join(MODELS_PATH, "diffusion_models", "qwen-image-2.1-turbo-Q4_K_M.gguf")
DEFAULT_LLM = os.path.join(LLM_PATH, "Qwen3-VL-8B-Instruct-UD-IQ3_XXS.gguf")
DEFAULT_LLM_VISION = os.path.join(LLM_PATH, "mmproj-F16.gguf")
DEFAULT_VAE = os.path.join(MODELS_PATH, "vae", "qwen_image_2.1_vae_bf16.safetensors")
DEFAULT_SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"

# Config presets directory
CONFIG_DIR = os.path.join(HOME_PATH, '.config', 'gimp-plugins', 'aiimage')
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

        # Built-in preset shown first in the dropdown. Selecting it restores
        # the script-defined defaults for every field (including sigmas).
        DEFAULT_PRESET_NAME = _("Default")

        def build_default_preset():
            return {
                "diffusion-model": DEFAULT_DIFFUSION_MODEL,
                "llm": DEFAULT_LLM,
                "llm-vision": DEFAULT_LLM_VISION,
                "vae": DEFAULT_VAE,
                "t5xxl": "",
                "t5": "",
                "lora": "",
                "width": 1024,
                "height": 1024,
                "steps": 8,
                "cfg-scale": 1.0,
                "guidance": 0.0,
                "sigmas": DEFAULT_SIGMAS,
                "vae-format": "auto",
                "prediction": "",
                "diffusion-fa": True,
                "offload-to-cpu": True,
                "max-vram": "",
                "prompt": "",
            }

        # --- Preset management row ---
        preset_label = Gtk.Label.new_with_mnemonic(_("_Preset:"))
        preset_label.set_halign(Gtk.Align.START)
        preset_label.set_hexpand(False)

        preset_combo = Gtk.ComboBoxText()
        preset_combo.set_hexpand(True)
        preset_combo.set_valign(Gtk.Align.CENTER)
        preset_label.set_mnemonic_widget(preset_combo)

        preset_combo.append_text(DEFAULT_PRESET_NAME)
        for name in get_preset_names():
            if name == DEFAULT_PRESET_NAME:
                continue
            preset_combo.append_text(name)
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

        def add_file_row(label_text, prop_name, default, tooltip=None):
            nonlocal row
            label = Gtk.Label.new_with_mnemonic(label_text)
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(False)
            entry = Gtk.Entry()
            entry.set_text(config.get_property(prop_name) or default)
            entry.set_hexpand(True)
            entry.set_valign(Gtk.Align.CENTER)
            label.set_mnemonic_widget(entry)
            if tooltip:
                label.set_tooltip_text(tooltip)
                entry.set_tooltip_text(tooltip)
            widgets[prop_name] = entry

            def on_entry_changed(e, pn=prop_name):
                config.set_property(pn, e.get_text())

            entry.connect("changed", on_entry_changed)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            row += 1
            return entry

        def add_spin_row(label_text, prop_name, default, min_val, max_val, tooltip=None):
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
            if tooltip:
                label.set_tooltip_text(tooltip)
                spin.set_tooltip_text(tooltip)
            widgets[prop_name] = spin

            def on_spin_changed(s, pn=prop_name):
                config.set_property(pn, s.get_value_as_int())

            spin.connect("value-changed", on_spin_changed)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            row += 1
            return spin

        def add_spin_row_float(label_text, prop_name, default, min_val, max_val, tooltip=None):
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
            if tooltip:
                label.set_tooltip_text(tooltip)
                spin.set_tooltip_text(tooltip)
            widgets[prop_name] = spin

            def on_spin_changed(s, pn=prop_name):
                config.set_property(pn, s.get_value())

            spin.connect("value-changed", on_spin_changed)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            row += 1
            return spin

        add_file_row(_("Diffusion _Model:"), "diffusion-model", DEFAULT_DIFFUSION_MODEL,
                     _("Diffusion model weights (GGUF) that generate the image; pick the checkpoint matching your desired style."))
        add_file_row(_("_LLM:"), "llm", DEFAULT_LLM,
                     _("Language model that reads and expands your prompt before generation."))
        add_file_row(_("LLM _Vision:"), "llm-vision", DEFAULT_LLM_VISION,
                     _("Vision projector (mmproj) that lets the LLM see reference images."))
        add_file_row(_("_VAE:"), "vae", DEFAULT_VAE,
                     _("VAE that decodes the model's latents into the final image; must match the diffusion model."))
        add_file_row(_("T5_X_XL:"), "t5xxl", "",
                     _("Optional T5-XXL text encoder used by some SD3/Flux-style models to read prompts."))
        add_file_row(_("_T5:"), "t5", "",
                     _("Optional T5 text encoder used by some models to embed the prompt."))
        add_file_row(_("LoR_A:"), "lora", "",
                     _("Optional LoRA adapter that adds a style or subject to the base model."))
        add_spin_row(_("_Width:"), "width", 1024, 64, 8192,
                     _("Output image width in pixels."))
        add_spin_row(_("_Height:"), "height", 1024, 64, 8192,
                     _("Output image height in pixels."))
        add_spin_row(_("_Steps:"), "steps", 8, 1, 100,
                     _("Number of denoising steps; more steps can improve quality but take longer."))
        add_spin_row_float(_("CFG S_cale:"), "cfg-scale", 1.0, 0.0, 30.0,
                           _("Classifier-free guidance strength for traditional CFG models; higher follows the prompt more strictly."))
        add_spin_row_float(_("G_uida_nce:"), "guidance", 0.0, 0.0, 30.0,
                           _("Distilled guidance scale for flow-matching models (e.g. Qwen/Flux); higher follows the prompt more closely."))
        add_file_row(_("Sig_mas:"), "sigmas", DEFAULT_SIGMAS,
                     _("Custom sigma schedule for distilled/turbo models; comma-separated values from 1.0 down to 0.0."))
        add_file_row(_("VAE _Format:"), "vae-format", "auto",
                     _("VAE latent layout override: auto, flux, sd3, flux2, or wan."))
        add_file_row(_("_Prediction:"), "prediction", "",
                     _("Override the model's prediction type (eps, v, sd3_flow, flux_flow); leave blank to auto-detect."))

        diffusion_fa_check = Gtk.CheckButton.new_with_mnemonic(
            _("Diffusion _flash attention"))
        diffusion_fa_check.set_active(bool(config.get_property("diffusion-fa")))
        diffusion_fa_check.set_tooltip_text(
            _("Pass --diffusion-fa. Turn off when sampling loses the Vulkan device."))
        diffusion_fa_check.set_hexpand(True)
        diffusion_fa_check.set_halign(Gtk.Align.START)
        widgets["diffusion-fa"] = diffusion_fa_check

        def on_diffusion_fa_toggled(cb):
            config.set_property("diffusion-fa", cb.get_active())

        diffusion_fa_check.connect("toggled", on_diffusion_fa_toggled)
        grid.attach(diffusion_fa_check, 0, row, 2, 1)
        row += 1

        offload_check = Gtk.CheckButton.new_with_mnemonic(
            _("Offload weights to _CPU"))
        offload_check.set_active(bool(config.get_property("offload-to-cpu")))
        offload_check.set_tooltip_text(
            _("Pass --offload-to-cpu. Turn off when keeping the weights in RAM overruns the GPU."))
        offload_check.set_hexpand(True)
        offload_check.set_halign(Gtk.Align.START)
        widgets["offload-to-cpu"] = offload_check

        def on_offload_toggled(cb):
            config.set_property("offload-to-cpu", cb.get_active())

        offload_check.connect("toggled", on_offload_toggled)
        grid.attach(offload_check, 0, row, 2, 1)
        row += 1

        max_vram_entry = Gtk.Entry()
        max_vram_entry.set_text(config.get_property("max-vram") or "")
        max_vram_entry.set_hexpand(True)
        max_vram_entry.set_placeholder_text(_("Blank lets sd-cli decide"))
        max_vram_tooltip = _(
            "Value for --max-vram, in GiB. Leave blank to omit the flag. "
            "A single number or a device assignment such as vulkan0=2.")
        max_vram_entry.set_tooltip_text(max_vram_tooltip)

        def on_max_vram_changed(entry):
            config.set_property("max-vram", entry.get_text())

        max_vram_entry.connect("changed", on_max_vram_changed)
        widgets["max-vram"] = max_vram_entry
        max_vram_label = Gtk.Label.new_with_mnemonic(_("Max _VRAM:"))
        max_vram_label.set_halign(Gtk.Align.START)
        max_vram_label.set_mnemonic_widget(max_vram_entry)
        max_vram_label.set_tooltip_text(max_vram_tooltip)
        grid.attach(max_vram_label, 0, row, 1, 1)
        grid.attach(max_vram_entry, 1, row, 1, 1)
        row += 1

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
        prompt_tooltip = _("Describe the image you want to generate.")
        prompt_label.set_tooltip_text(prompt_tooltip)
        text_view.set_tooltip_text(prompt_tooltip)

        # Ctrl+Enter submits the dialog
        def on_text_view_key(view, event, dlg):
            if event.keyval == Gdk.KEY_Return and (event.state & Gdk.ModifierType.CONTROL_MASK):
                dlg.response(Gtk.ResponseType.OK)
                return True
            return False

        text_view.connect("key-press-event", on_text_view_key, dialog)

        scrolled.add(text_view)
        grid.attach(prompt_label, 0, row, 1, 1)
        grid.attach(scrolled, 1, row, 1, 1)

        # --- Preset callbacks ---

        def load_preset_values(preset_name):
            if preset_name == DEFAULT_PRESET_NAME:
                preset = build_default_preset()
            else:
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
                        elif prop.value_type == GObject.TYPE_BOOLEAN:
                            if isinstance(value, bool):
                                config.set_property(key, value)
                            else:
                                config.set_property(key, str(value).lower() in ("1", "true", "yes", "on"))
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
                    elif isinstance(widget, Gtk.CheckButton):
                        if isinstance(value, bool):
                            widget.set_active(value)
                        else:
                            widget.set_active(str(value).lower() in ("1", "true", "yes", "on"))
                except (ValueError, TypeError):
                    pass
            # Clear widgets not in the preset
            for key, widget in widgets.items():
                if key in preset:
                    continue
                try:
                    if isinstance(widget, Gtk.Entry):
                        widget.set_text("")
                    elif isinstance(widget, Gtk.SpinButton):
                        prop = procedure.find_property(key)
                        if prop:
                            widget.set_value(prop.default_value)
                        else:
                            widget.set_value(0)
                    elif isinstance(widget, Gtk.TextView):
                        widget.get_buffer().set_text("", 0)
                    elif isinstance(widget, Gtk.CheckButton):
                        prop = procedure.find_property(key)
                        if prop:
                            widget.set_active(bool(prop.default_value))
                        else:
                            widget.set_active(False)
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
                    elif isinstance(widget, Gtk.CheckButton):
                        values[key] = widget.get_active()
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

            if name == DEFAULT_PRESET_NAME:
                Gimp.message(_("'%s' is a built-in preset and cannot be overwritten.") % name)
                return

            presets = load_presets()
            presets[name] = values
            save_presets(presets)

            # Update combo and select the saved preset
            model = preset_combo.get_model()
            found = False
            for i in range(model.iter_n_children(None)):
                if model.get_value(model.get_iter(i), 0) == name:
                    preset_combo.set_active(i)
                    found = True
                    break
            if not found:
                preset_combo.append_text(name)
                preset_combo.set_active(model.iter_n_children(None) - 1)

        def on_rename_preset(btn):
            active = preset_combo.get_active()
            if active < 0:
                return
            old_name = preset_combo.get_active_text()
            if not old_name:
                return
            if old_name == DEFAULT_PRESET_NAME:
                Gimp.message(_("The built-in '%s' preset cannot be renamed.") % old_name)
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
            if new_name == DEFAULT_PRESET_NAME:
                Gimp.message(_("'%s' is reserved for the built-in preset.") % new_name)
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
            if name == DEFAULT_PRESET_NAME:
                Gimp.message(_("The built-in '%s' preset cannot be deleted.") % name)
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
        # gtk_widget_destroy() only queues the teardown; flush it so the dead
        # window does not linger (as "not responding") while sd-cli runs.
        display = Gdk.Display.get_default()
        if display is not None:
            display.flush()

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

        if config.get_property("diffusion-fa"):
            command.append("--diffusion-fa")
        if config.get_property("offload-to-cpu"):
            command.append("--offload-to-cpu")
        max_vram = (config.get_property("max-vram") or "").strip()
        if max_vram:
            command.extend(["--max-vram", max_vram])
        command.extend([
            "-v",
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

        # Custom sigma schedule for distilled/turbo models
        add_flag("--sigmas", config.get_property("sigmas"))

        # VAE format override
        add_flag("--vae-format", config.get_property("vae-format"))

        # Prediction type override
        add_flag("--prediction", config.get_property("prediction"))

        command.extend([
            "-o", str(output_path),
            "-p", config.get_property("prompt"),
        ])

        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace")
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

        layers = imported_image.get_layers()
        if layers:
            layers[0].set_name(_("AI Image"))

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
            1, 100, 8, GObject.ParamFlags.READWRITE,
        )
        # CFG scale (traditional, for CFG-based models)
        procedure.add_double_argument(
            "cfg-scale", _("CFG S_cale"), _("Classifier-free guidance scale (traditional models)"),
            0.0, 30.0, 1.0, GObject.ParamFlags.READWRITE,
        )
        # Guidance (distilled, for flow-matching models)
        procedure.add_double_argument(
            "guidance", _("G_uida_nce"), _("Distilled guidance scale for flow-matching models"),
            0.0, 30.0, 0.0, GObject.ParamFlags.READWRITE,
        )
        # Custom sigma schedule (distilled/turbo models)
        procedure.add_string_argument(
            "sigmas", _("Sig_mas"), _("Custom sigma schedule (comma-separated values from 1.0 to 0.0)"),
            DEFAULT_SIGMAS, GObject.ParamFlags.READWRITE,
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
        procedure.add_boolean_argument(
            "diffusion-fa", _("Diffusion _flash attention"),
            _("Pass --diffusion-fa. Turn off when sampling loses the Vulkan device."),
            True, GObject.ParamFlags.READWRITE,
        )
        procedure.add_boolean_argument(
            "offload-to-cpu", _("Offload weights to _CPU"),
            _("Pass --offload-to-cpu. Turn off when keeping the weights in RAM overruns the GPU."),
            True, GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "max-vram", _("Max _VRAM"),
            _("Value for --max-vram, in GiB. Blank omits the flag."),
            "", GObject.ParamFlags.READWRITE,
        )
        # Prompt
        procedure.add_string_argument(
            "prompt", _("_Prompt"), _("Describe the image you want to generate"),
            "", GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(AIImage.__gtype_name__, sys.argv)
