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
PLUGIN_NAME = "python-fu-aiedit"
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

# Default paths for sd-cli models
DEFAULT_DIFFUSION_MODEL = os.path.join(MODELS_PATH, "diffusion_models", "qwen-image-2.1-turbo-Q4_K_M.gguf")
DEFAULT_LLM = os.path.join(LLM_PATH, "Qwen3-VL-8B-Instruct-UD-IQ3_XXS.gguf")
DEFAULT_LLM_VISION = os.path.join(LLM_PATH, "mmproj-F16.gguf")
DEFAULT_VAE = os.path.join(MODELS_PATH, "vae", "qwen_image_2.1_vae_bf16.safetensors")
DEFAULT_SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"

# Model filename hints for reference-image editing. These models consume the
# source image through sd-cli's -r flag (together with the vision LLM) instead
# of the classic --init-img img2img path.
REFERENCE_EDIT_HINTS = ("boogu", "kontext", "qwen", "longcat", "mage", "edit")


def uses_reference_image(model_path):
    name = os.path.basename(model_path or "").lower()
    return any(hint in name for hint in REFERENCE_EDIT_HINTS)


# Edit models that additionally require the Qwen3-VL vision projector (mmproj)
# passed via --llm_vision. Without it sd-cli disables vision and refuses to edit.
VISION_EDIT_HINTS = ("qwen", "boogu", "longcat", "mage")


def needs_vision_weights(model_path):
    name = os.path.basename(model_path or "").lower()
    return any(hint in name for hint in VISION_EDIT_HINTS)


def export_selection_mask(image, path):
    """Export the current selection (marching ants or quick mask) as a
    full-canvas grayscale PNG mask at `path`. White marks the selected region,
    which sd-cli repaints via --mask. Returns True when a non-empty selection
    existed and the file was written."""
    selection = image.get_selection()
    result = selection.bounds(image)
    if not result:
        return False
    non_empty = result[1] if len(result) == 6 else result[0]
    if not non_empty:
        return False

    width = image.get_width()
    height = image.get_height()
    mask_image = Gimp.Image.new(width, height, Gimp.ImageBaseType.GRAY)
    layer = Gimp.Layer.new(mask_image, "mask", width, height,
                           Gimp.ImageType.GRAY_IMAGE, 100.0,
                           Gimp.LayerMode.NORMAL)
    mask_image.insert_layer(layer, None, 0)
    Gimp.edit_copy([selection])
    floating = Gimp.edit_paste(layer, False)
    Gimp.floating_sel_anchor(floating[0])
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, mask_image,
                   Gio.File.new_for_path(str(path)), None)
    Gimp.Image.delete(mask_image)
    return True


def paste_layer_aligned(image, target_layer, source_layer):
    """Copy `source_layer`'s pixels into `target_layer`, aligned to the target
    layer origin. An active selection is temporarily cleared so the marching
    ants cannot shift the pasted content, then restored."""
    selection = image.get_selection()
    result = selection.bounds(image)
    non_empty = result[1] if len(result) == 6 else result[0] if result else False
    saved_channel = None
    if non_empty:
        saved_channel = selection.save(image)
        Gimp.Selection.none(image)
    Gimp.edit_copy([source_layer])
    floating_sel = Gimp.edit_paste(target_layer, False)
    if floating_sel:
        Gimp.floating_sel_anchor(floating_sel[0])
    if saved_channel is not None:
        image.select_item(Gimp.ChannelOps.REPLACE, saved_channel)
        image.remove_channel(saved_channel)


# Config presets directory
CONFIG_DIR = os.path.join(HOME_PATH, '.config', 'gimp-plugins', 'aiedit')
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

def aiedit_func(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PLUGIN_NAME)

        # Build a custom dialog so we can have a multi-line prompt
        dialog = Gtk.Dialog(title=_("AI Edit"), transient_for=None)
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
            if uses_reference_image(DEFAULT_DIFFUSION_MODEL):
                default_mode = "kontext"
            else:
                default_mode = "img2img"
            return {
                "diffusion-model": DEFAULT_DIFFUSION_MODEL,
                "clip-l": "",
                "llm": DEFAULT_LLM,
                "llm-vision": DEFAULT_LLM_VISION,
                "vae": DEFAULT_VAE,
                "t5xxl": "",
                "t5": "",
                "lora": "",
                "control-net": "",
                "steps": 8,
                "cfg-scale": 1.0,
                "guidance": 3.0,
                "sigmas": DEFAULT_SIGMAS,
                "vae-format": "auto",
                "prediction": "",
                "edit-mode": default_mode,
                "use-selection": True,
                "diffusion-fa": True,
                "offload-to-cpu": True,
                "max-vram": "",
                "seed": -1,
                "strength": 0.9,
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
        save_btn.set_tooltip_text(_("Save current settings as a named preset"))
        rename_btn = Gtk.Button.new_with_mnemonic(_("_Rename"))
        rename_btn.set_tooltip_text(_("Rename the selected preset"))
        delete_btn = Gtk.Button.new_with_mnemonic(_("_Delete"))
        delete_btn.set_tooltip_text(_("Delete the selected preset"))

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

        def add_file_row(label_text, prop_name, default, tooltip):
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

        def add_combined_row(pairs):
            nonlocal row
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            for (label_text, prop_name, kind, default,
                 min_val, max_val, tooltip) in pairs:
                label = Gtk.Label.new_with_mnemonic(label_text)
                label.set_halign(Gtk.Align.START)
                label.set_hexpand(False)
                if kind == "int":
                    adjustment = Gtk.Adjustment(
                        value=default, lower=min_val, upper=max_val,
                        step_increment=1, page_increment=64)
                    widget = Gtk.SpinButton(adjustment=adjustment)
                    widget.set_valign(Gtk.Align.CENTER)
                    widgets[prop_name] = widget

                    def on_changed(s, pn=prop_name):
                        config.set_property(pn, s.get_value_as_int())

                    widget.connect("value-changed", on_changed)
                elif kind == "float":
                    adjustment = Gtk.Adjustment(
                        value=default, lower=min_val, upper=max_val,
                        step_increment=0.1, page_increment=10)
                    widget = Gtk.SpinButton(adjustment=adjustment, digits=1)
                    widget.set_valign(Gtk.Align.CENTER)
                    widgets[prop_name] = widget

                    def on_changed(s, pn=prop_name):
                        config.set_property(pn, s.get_value())

                    widget.connect("value-changed", on_changed)
                else:
                    widget = Gtk.Entry()
                    widget.set_text(config.get_property(prop_name) or default)
                    widget.set_valign(Gtk.Align.CENTER)
                    widgets[prop_name] = widget

                    def on_changed(e, pn=prop_name):
                        config.set_property(pn, e.get_text())

                    widget.connect("changed", on_changed)
                widget.set_tooltip_text(tooltip)
                label.set_mnemonic_widget(widget)
                hbox.pack_start(label, False, False, 0)
                hbox.pack_start(widget, False, False, 0)
            grid.attach(hbox, 0, row, 2, 1)
            row += 1

        add_file_row(_("Diffusion _Model:"), "diffusion-model", DEFAULT_DIFFUSION_MODEL,
                     _("Path to the diffusion model GGUF file"))
        add_file_row(_("Clip _L:"), "clip-l", "",
                     _("Path to the CLIP-L text encoder GGUF (optional)"))
        add_file_row(_("_LLM:"), "llm", DEFAULT_LLM,
                     _("Path to the LLM for vision-based prompting"))
        add_file_row(_("LLM _Vision:"), "llm-vision", DEFAULT_LLM_VISION,
                     _("Path to the LLM vision projector (mmproj) file"))
        add_file_row(_("_VAE:"), "vae", DEFAULT_VAE,
                     _("Path to the VAE decoder file"))
        add_file_row(_("T5_X_XL:"), "t5xxl", "",
                     _("Path to T5XXL encoder (required by some models like Kontext) — leave empty if not needed"))
        add_file_row(_("_T5:"), "t5", "",
                     _("Path to T5 encoder (alternative to T5XXL) — leave empty if not needed"))
        add_file_row(_("LoR_A:"), "lora", "",
                     _("Path to a LoRA adapter file to apply (optional)"))
        add_file_row(_("Control-_Net:"), "control-net", "",
                     _("Path to a ControlNet model for guided generation (optional)"))
        add_combined_row([
            (_("_Steps:"), "steps", "int", 8, 1, 100,
             _("Number of sampling steps — higher values improve quality but take longer")),
            (_("CFG S_cale:"), "cfg-scale", "float", 1.0, 0.0, 30.0,
             _("How strongly to follow the prompt (1=creative, ~30=strict)")),
            (_("G_uida_nce:"), "guidance", "float", 0.0, 0.0, 30.0,
             _("Distilled guidance for flow-matching models like Flux (0=disabled)")),
        ])
        add_file_row(_("Sig_mas:"), "sigmas", DEFAULT_SIGMAS,
                     _("Custom sigma schedule (comma-separated values from 1.0 to 0.0) for distilled/turbo models — leave empty to use the model default"))
        add_file_row(_("_Prediction:"), "prediction", "",
                     _("Prediction type override: eps, v, sd3_flow, flux_flow (leave empty for auto-detect)"))

        # Edit mode: combo box with auto-detect from model name
        mode_label = Gtk.Label.new_with_mnemonic(_("Edit _Mode:"))
        mode_label.set_halign(Gtk.Align.START)
        mode_label.set_hexpand(False)
        mode_combo = Gtk.ComboBoxText()
        mode_combo.set_hexpand(True)
        mode_combo.set_valign(Gtk.Align.CENTER)
        mode_combo.append_text("Img2Img (edit)")
        mode_combo.append_text("Kontext (reference edit)")
        mode_label.set_mnemonic_widget(mode_combo)
        mode_combo.set_tooltip_text(_("Img2Img: noise then denoise the input image. Kontext: reference-based editing via the input image (Qwen Image Edit, Boogu, Flux Kontext)"))

        # Auto-detect mode from model filename
        diffusion_model = config.get_property("diffusion-model") or ""
        default_mode = "kontext" if uses_reference_image(diffusion_model) else "img2img"
        current_mode = config.get_property("edit-mode") or default_mode
        mode_combo.set_active(0 if current_mode == "img2img" else 1)
        widgets["edit-mode"] = mode_combo

        def on_mode_changed(cb):
            active = cb.get_active()
            config.set_property("edit-mode", "img2img" if active == 0 else "kontext")
        mode_combo.connect("changed", on_mode_changed)
        grid.attach(mode_label, 0, row, 1, 1)
        grid.attach(mode_combo, 1, row, 1, 1)
        row += 1

        # Restrict the edit to the current selection (inpaint)
        use_selection_check = Gtk.CheckButton.new_with_mnemonic(
            _("Use _selection as mask (inpaint only selected area)"))
        use_selection_check.set_active(bool(config.get_property("use-selection")))
        use_selection_check.set_tooltip_text(
            _("Restrict the AI edit to the current marching-ants selection or "
              "quick mask. Without a selection, the whole image is edited."))
        use_selection_check.set_hexpand(True)
        use_selection_check.set_halign(Gtk.Align.START)
        widgets["use-selection"] = use_selection_check

        def on_use_selection_toggled(cb):
            config.set_property("use-selection", cb.get_active())

        use_selection_check.connect("toggled", on_use_selection_toggled)
        grid.attach(use_selection_check, 0, row, 2, 1)
        row += 1

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

        add_combined_row([
            (_("_Seed:"), "seed", "int", -1, -1, 2147483647,
             _("Random seed (-1 for random) — use the same seed to reproduce results")),
            (_("_Strength:"), "strength", "float", 0.75, 0.0, 1.0,
             _("How much to transform the image — 0=unchanged, 1=fully replaced")),
            (_("VAE _Format:"), "vae-format", "text", "auto", 0, 0,
             _("VAE latent format: auto, flux, sd3, flux2, wan")),
        ])

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
        text_view.set_tooltip_text(_("Describe the edit you want to apply — be detailed for best results"))
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

        # Ctrl+Enter submits the dialog, plain Enter inserts a newline
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
                    elif isinstance(widget, Gtk.ComboBoxText):
                        if key == "edit-mode":
                            widget.set_active(0 if str(value) == "img2img" else 1)
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
                    elif isinstance(widget, Gtk.ComboBoxText):
                        widget.set_active(0)
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
                    elif isinstance(widget, Gtk.ComboBoxText):
                        values[key] = "img2img" if widget.get_active() == 0 else "kontext"
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
        # gtk_widget_destroy() only queues the window teardown. Flush it now,
        # otherwise the dead window stays mapped while sd-cli runs (we never
        # return to the main loop), and the desktop eventually reports
        # "GIMP is not responding" for it.
        display = Gdk.Display.get_default()
        if display is not None:
            display.flush()

        if response != Gtk.ResponseType.OK:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    Gimp.context_push()
    image.undo_group_start()

    if not drawables:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error("No drawable provided."))

    drawable = drawables[0]
    input_path = None
    output_path = None
    mask_path = None

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

        # Export the current selection (marching ants or quick mask) as an
        # inpaint mask when requested and a non-empty selection exists.
        if config.get_property("use-selection"):
            mask_path = temp_dir / f"gimp_aiedit_mask_{os.getpid()}.png"
            if not export_selection_mask(image, mask_path):
                mask_path = None

        Gimp.progress_set_text(_("Running AI edit (this may take time)..."))
        Gimp.progress_pulse()

        # Build sd-cli command
        command = ["sd-cli"]

        def add_flag(flag, value):
            if value and value.strip():
                command.append(flag)
                command.append(value)

        add_flag("--diffusion-model", config.get_property("diffusion-model"))
        add_flag("--clip_l", config.get_property("clip-l"))
        # Qwen3-VL-based edit models need both the vision LLM and its mmproj
        # projector; fall back to the configured defaults when left empty.
        model_path = config.get_property("diffusion-model") or ""
        llm = config.get_property("llm")
        llm_vision = config.get_property("llm-vision")
        if needs_vision_weights(model_path):
            llm = llm or DEFAULT_LLM
            llm_vision = llm_vision or DEFAULT_LLM_VISION
        add_flag("--llm", llm)
        add_flag("--llm_vision", llm_vision)
        add_flag("--vae", config.get_property("vae"))
        add_flag("--t5xxl", config.get_property("t5xxl"))
        add_flag("--t5", config.get_property("t5"))
        add_flag("--lora", config.get_property("lora"))
        add_flag("--control-net", config.get_property("control-net"))

        seed = config.get_property("seed")
        if seed is not None:
            command.extend(["--seed", str(seed)])

        # Sampling options apply to both img2img and reference-based editing
        command.extend([
            "--steps", str(config.get_property("steps")),
            "--cfg-scale", str(config.get_property("cfg-scale")),
        ])
        # Guidance for distilled flow-matching models
        guidance = config.get_property("guidance")
        if guidance:
            command.extend(["--guidance", str(guidance)])
        # Custom sigma schedule for distilled/turbo models
        add_flag("--sigmas", config.get_property("sigmas"))
        # VAE format override
        add_flag("--vae-format", config.get_property("vae-format"))
        # Prediction type override
        add_flag("--prediction", config.get_property("prediction"))

        edit_mode = config.get_property("edit-mode") or "img2img"
        if edit_mode == "kontext":
            # Reference-based editing: condition on the source image via -r
            command.extend(["-r", str(input_path)])
        else:
            # Classic img2img: noise then denoise the init image
            command.extend(["--init-img", str(input_path)])
            strength = config.get_property("strength")
            if strength is not None:
                command.extend(["--strength", str(strength)])

        # Restrict inpainting to the marching-ants selection when available.
        # The mask needs the source as an init image to blend against; in
        # kontext mode the reference alone leaves the unmasked region filled
        # from a blank latent, which comes out garbled.
        if mask_path is not None:
            if edit_mode == "kontext":
                command.extend(["--init-img", str(input_path)])
            command.extend(["--mask", str(mask_path)])

        if config.get_property("diffusion-fa"):
            command.append("--diffusion-fa")
        if config.get_property("offload-to-cpu"):
            command.append("--offload-to-cpu")
        max_vram = (config.get_property("max-vram") or "").strip()
        if max_vram:
            command.extend(["--max-vram", max_vram])
        command.extend([
            "-v",
            "-o", str(output_path),
            "-p", config.get_property("prompt"),
        ])

        # sd-cli writes its [I]/[W] logs to stdout and [E] to stderr. Merge both
        # so nothing is lost and the pipe cannot fill and deadlock the process.
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", errors="replace")
        output_lines = []
        for line in process.stdout:
            output_lines.append(line)
            stripped = line.rstrip()
            if stripped and not stripped.startswith("[V]"):
                Gimp.progress_set_text(stripped)
                Gimp.progress_pulse()
        process.wait()

        if process.returncode != 0:
            error_message = _("AI edit failed. Ensure 'sd-cli' is installed and working.")
            details = "".join(
                line for line in output_lines
                if line.startswith("[E]") or line.startswith("[W]")
            )
            if not details:
                details = "".join(output_lines[-20:])
            Gimp.message("%s\n\nError Output:\n%s" % (error_message, details))
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        if not output_path.exists():
            error_message = _("AI edit executed but failed to create the output file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

        Gimp.progress_set_text(_("Loading processed image..."))

        imported_image = Gimp.file_load(run_mode, Gio.File.new_for_path(str(output_path)))

        if not imported_image:
            error_message = _("Failed to load the processed image file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))

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
        paste_layer_aligned(image, final_layer, new_layer)

        Gimp.Image.delete(imported_image)

        final_layer.set_name(_("AI Edited"))
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
        if mask_path and mask_path.exists():
            os.remove(mask_path)

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
        # CLIP-L path
        procedure.add_string_argument(
            "clip-l", _("Clip _L"), _("Path to the CLIP-L text encoder"),
            "", GObject.ParamFlags.READWRITE,
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
        # T5XXL encoder path (optional, needed by some models like Kontext)
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
        # ControlNet model path (optional)
        procedure.add_string_argument(
            "control-net", _("Control-_Net"), _("Path to the ControlNet model (optional)"),
            "", GObject.ParamFlags.READWRITE,
        )
        # Steps
        procedure.add_int_argument(
            "steps", _("_Steps"), _("Number of sampling steps"),
            1, 100, 8, GObject.ParamFlags.READWRITE,
        )
        # CFG scale
        procedure.add_double_argument(
            "cfg-scale", _("CFG S_cale"), _("Classifier-free guidance scale"),
            0.0, 30.0, 1.0, GObject.ParamFlags.READWRITE,
        )
        # Guidance (distilled, for flow-matching models)
        procedure.add_double_argument(
            "guidance", _("G_uida_nce"), _("Distilled guidance scale for flow-matching models (0=disabled)"),
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
        # Edit mode
        edit_mode_choice = Gimp.Choice.new()
        edit_mode_choice.add("img2img", 0, "Img2Img (edit)", "Standard img2img: noise then denoise the input image")
        edit_mode_choice.add("kontext", 1, "Kontext (reference edit)", "Reference-based editing: pass the input as a reference image (Qwen Image Edit, Boogu, Flux Kontext)")
        procedure.add_choice_argument(
            "edit-mode", _("Edit _Mode"), _("Editing mode: img2img or Kontext style transfer"),
            edit_mode_choice, "img2img", GObject.ParamFlags.READWRITE,
        )
        # Use selection as inpaint mask
        procedure.add_boolean_argument(
            "use-selection", _("Use _selection as mask"), _("Limit the edit to the current selection (inpaint)"),
            True, GObject.ParamFlags.READWRITE,
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
        # Seed
        procedure.add_int_argument(
            "seed", _("_Seed"), _("RNG seed (-1 for random)"),
            -1, 2147483647, -1, GObject.ParamFlags.READWRITE,
        )
        # Strength (denoising for img2img)
        procedure.add_double_argument(
            "strength", _("_Strength"), _("Denoising strength (0.0-1.0)"),
            0.0, 1.0, 0.75, GObject.ParamFlags.READWRITE,
        )
        # Prompt
        procedure.add_string_argument(
            "prompt", _("_Prompt"), _("Describe the edit you want to apply to the image"),
            "", GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(AIEdit.__gtype_name__, sys.argv)
