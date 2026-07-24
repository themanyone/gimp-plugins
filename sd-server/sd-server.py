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
import json
from pathlib import Path
import locale
import gettext

# Internationalization setup
PLUGIN_NAME = "python-fu-sd-server"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'locale'))

locale.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.textdomain(PLUGIN_NAME)

def _(message): return gettext.gettext(message)
def N_(message): return message

# Default SD server URL
DEFAULT_SERVER_URL = "http://127.0.0.1:1234"


def _fetch_capabilities(server_url):
    """Fetch server capabilities, returns dict or None on failure."""
    try:
        import requests
        resp = requests.get(f"{server_url}/sdcpp/v1/capabilities", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def sd_server_func(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PLUGIN_NAME)

        dialog = Gtk.Dialog(title=_("SD Server"), transient_for=None)
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

        # --- Server URL ---
        server_label = Gtk.Label.new_with_mnemonic(_("_Server:"))
        server_label.set_halign(Gtk.Align.START)
        server_label.set_hexpand(False)
        server_entry = Gtk.Entry()
        server_entry.set_text(config.get_property("server-url") or DEFAULT_SERVER_URL)
        server_entry.set_hexpand(True)
        server_entry.set_valign(Gtk.Align.CENTER)
        server_label.set_mnemonic_widget(server_entry)

        def on_server_changed(e):
            config.set_property("server-url", e.get_text())

        server_entry.connect("changed", on_server_changed)
        grid.attach(server_label, 0, row, 1, 1)
        grid.attach(server_entry, 1, row, 1, 1)
        row += 1

        # --- Model info label ---
        model_info_label = Gtk.Label(label="")
        model_info_label.set_halign(Gtk.Align.START)
        model_info_label.set_hexpand(True)
        model_info_label.set_ellipsize(3)
        grid.attach(model_info_label, 0, row, 2, 1)
        row += 1

        # Probe server capabilities (GLib.idle_add to let Gtk init finish)
        def probe_caps():
            url = server_entry.get_text()
            import requests
            try:
                resp = requests.get(f"{url}/sdcpp/v1/capabilities", timeout=5)
                resp.raise_for_status()
                caps = resp.json()
                stem = caps.get("model", {}).get("stem", "")
                if stem:
                    model_info_label.set_text(_("Model: %s") % stem)
                    model_info_label.set_tooltip_text(stem)
                else:
                    model_info_label.set_text(_("Connected"))
            except Exception:
                model_info_label.set_text(_("Could not fetch server capabilities"))
        GLib.idle_add(probe_caps)

        # --- Generate new image checkbox ---
        generate_label = Gtk.CheckButton.new_with_mnemonic(
            _("Generate new image (no layer or checked)")
        )
        generate_label.set_halign(Gtk.Align.START)
        generate_label.set_valign(Gtk.Align.CENTER)
        generate_label.set_active(
            config.get_property("generate-new") or False
        )

        def on_generate_changed(cb):
            config.set_property("generate-new", cb.get_active())

        generate_label.connect("toggled", on_generate_changed)
        grid.attach(generate_label, 0, row, 2, 1)
        row += 1

        # --- Width ---
        width_label = Gtk.Label.new_with_mnemonic(_("_Width:"))
        width_label.set_halign(Gtk.Align.START)
        width_label.set_hexpand(False)
        width_adj = Gtk.Adjustment(
            value=config.get_property("width") or 1024,
            lower=64, upper=8192, step_increment=64, page_increment=64
        )
        width_spin = Gtk.SpinButton(adjustment=width_adj)
        width_spin.set_hexpand(True)
        width_spin.set_valign(Gtk.Align.CENTER)
        width_label.set_mnemonic_widget(width_spin)

        def on_width_changed(s):
            config.set_property("width", s.get_value_as_int())

        width_spin.connect("value-changed", on_width_changed)
        grid.attach(width_label, 0, row, 1, 1)
        grid.attach(width_spin, 1, row, 1, 1)
        row += 1

        # --- Height ---
        height_label = Gtk.Label.new_with_mnemonic(_("_Height:"))
        height_label.set_halign(Gtk.Align.START)
        height_label.set_hexpand(False)
        height_adj = Gtk.Adjustment(
            value=config.get_property("height") or 1024,
            lower=64, upper=8192, step_increment=64, page_increment=64
        )
        height_spin = Gtk.SpinButton(adjustment=height_adj)
        height_spin.set_hexpand(True)
        height_spin.set_valign(Gtk.Align.CENTER)
        height_label.set_mnemonic_widget(height_spin)

        def on_height_changed(s):
            config.set_property("height", s.get_value_as_int())

        height_spin.connect("value-changed", on_height_changed)
        grid.attach(height_label, 0, row, 1, 1)
        grid.attach(height_spin, 1, row, 1, 1)
        row += 1

        # --- Steps ---
        steps_label = Gtk.Label.new_with_mnemonic(_("_Steps:"))
        steps_label.set_halign(Gtk.Align.START)
        steps_label.set_hexpand(False)
        steps_adj = Gtk.Adjustment(
            value=config.get_property("steps") or 30,
            lower=1, upper=100, step_increment=1, page_increment=10
        )
        steps_spin = Gtk.SpinButton(adjustment=steps_adj)
        steps_spin.set_hexpand(True)
        steps_spin.set_valign(Gtk.Align.CENTER)
        steps_label.set_mnemonic_widget(steps_spin)

        def on_steps_changed(s):
            config.set_property("steps", s.get_value_as_int())

        steps_spin.connect("value-changed", on_steps_changed)
        grid.attach(steps_label, 0, row, 1, 1)
        grid.attach(steps_spin, 1, row, 1, 1)
        row += 1

        # --- CFG Scale ---
        cfg_label = Gtk.Label.new_with_mnemonic(_("CFG S_cale:"))
        cfg_label.set_halign(Gtk.Align.START)
        cfg_label.set_hexpand(False)
        cfg_adj = Gtk.Adjustment(
            value=config.get_property("cfg-scale") or 7.0,
            lower=1.0, upper=30.0, step_increment=0.5, page_increment=5
        )
        cfg_spin = Gtk.SpinButton(adjustment=cfg_adj, digits=1)
        cfg_spin.set_hexpand(True)
        cfg_spin.set_valign(Gtk.Align.CENTER)
        cfg_label.set_mnemonic_widget(cfg_spin)

        def on_cfg_changed(s):
            config.set_property("cfg-scale", s.get_value())

        cfg_spin.connect("value-changed", on_cfg_changed)
        grid.attach(cfg_label, 0, row, 1, 1)
        grid.attach(cfg_spin, 1, row, 1, 1)
        row += 1

        # --- Denoising Strength (img2img only) ---
        denoise_label = Gtk.Label.new_with_mnemonic(_("_Denoising:"))
        denoise_label.set_halign(Gtk.Align.START)
        denoise_label.set_hexpand(False)
        denoise_adj = Gtk.Adjustment(
            value=config.get_property("denoising-strength") or 0.75,
            lower=0.0, upper=1.0, step_increment=0.05, page_increment=0.1
        )
        denoise_spin = Gtk.SpinButton(adjustment=denoise_adj, digits=2)
        denoise_spin.set_hexpand(True)
        denoise_spin.set_valign(Gtk.Align.CENTER)
        denoise_label.set_mnemonic_widget(denoise_spin)

        def on_denoise_changed(s):
            config.set_property("denoising-strength", s.get_value())

        denoise_spin.connect("value-changed", on_denoise_changed)
        grid.attach(denoise_label, 0, row, 1, 1)
        grid.attach(denoise_spin, 1, row, 1, 1)
        row += 1

        # --- Prompt ---
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
            config.set_property("prompt",
                                buf.get_text(buf.get_start_iter(),
                                             buf.get_end_iter(), False))

        text_view.get_buffer().connect("changed", on_text_changed)
        prompt_label.set_mnemonic_widget(text_view)

        def on_text_view_key(view, event, dlg):
            if (event.keyval == Gdk.KEY_Return and
                    (event.state & Gdk.ModifierType.SHIFT_MASK)):
                dlg.response(Gtk.ResponseType.OK)
                return True
            return False

        text_view.connect("key-press-event", on_text_view_key, dialog)

        scrolled.add(text_view)
        grid.attach(prompt_label, 0, row, 1, 1)
        grid.attach(scrolled, 1, row, 1, 1)
        row += 1

        # --- Negative prompt ---
        neg_label = Gtk.Label.new_with_mnemonic(_("_Negative Prompt:"))
        neg_label.set_halign(Gtk.Align.START)
        neg_label.set_valign(Gtk.Align.START)
        neg_scrolled = Gtk.ScrolledWindow()
        neg_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        neg_scrolled.set_hexpand(True)
        neg_scrolled.set_vexpand(True)
        neg_scrolled.set_min_content_height(60)

        neg_text_view = Gtk.TextView()
        neg_text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        neg_text_view.set_hexpand(True)
        neg_text_view.set_vexpand(True)
        neg_text = config.get_property("negative-prompt")
        if neg_text:
            neg_text_view.get_buffer().set_text(neg_text, len(neg_text))

        def on_neg_text_changed(buf):
            config.set_property("negative-prompt",
                                buf.get_text(buf.get_start_iter(),
                                             buf.get_end_iter(), False))

        neg_text_view.get_buffer().connect("changed", on_neg_text_changed)
        neg_label.set_mnemonic_widget(neg_text_view)

        def on_neg_text_view_key(view, event, dlg):
            if (event.keyval == Gdk.KEY_Return and
                    (event.state & Gdk.ModifierType.SHIFT_MASK)):
                dlg.response(Gtk.ResponseType.OK)
                return True
            return False

        neg_text_view.connect("key-press-event", on_neg_text_view_key, dialog)

        neg_scrolled.add(neg_text_view)
        grid.attach(neg_label, 0, row, 1, 1)
        grid.attach(neg_scrolled, 1, row, 1, 1)
        row += 1

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, GLib.Error()
            )

    # Determine if we should generate a new image
    generate_new = config.get_property("generate-new")
    no_drawables = not drawables

    if generate_new or no_drawables:
        return _generate_new(procedure, run_mode, image, config)
    else:
        return _edit_layer(procedure, run_mode, image, drawables, config)


def _generate_new(procedure, run_mode, image, config):
    """Generate a new image via the SD server API."""
    server_url = config.get_property("server-url") or DEFAULT_SERVER_URL
    prompt = config.get_property("prompt") or ""
    width = config.get_property("width") or 1024
    height = config.get_property("height") or 1024
    steps = config.get_property("steps") or 30
    cfg_scale = config.get_property("cfg-scale") or 7.0
    negative_prompt = config.get_property("negative-prompt") or ""

    output_path = None

    try:
        temp_dir = Path(tempfile.gettempdir())
        output_path = temp_dir / f"gimp_sdserver_{os.getpid()}.png"

        Gimp.progress_init(_("Generating image via SD server..."))
        Gimp.progress_pulse()

        payload = {
            "prompt": prompt,
            "steps": steps,
            "width": width,
            "height": height,
            "cfg_scale": cfg_scale,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        import requests
        response = requests.post(
            f"{server_url}/sdapi/v1/txt2img",
            json=payload,
            timeout=600,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("images"):
            raise RuntimeError("No images in API response")

        import io
        import base64
        from PIL import Image

        image_data = Image.open(
            io.BytesIO(base64.b64decode(data["images"][0]))
        )
        image_data.save(str(output_path))

        Gimp.progress_set_text(_("Loading generated image..."))

        imported_image = Gimp.file_load(
            run_mode, Gio.File.new_for_path(str(output_path))
        )
        if not imported_image:
            raise RuntimeError("Failed to load generated image")

        Gimp.Display.new(imported_image)

    except Exception as e:
        Gimp.message(_("Error: %s") % e)
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e))
        )

    finally:
        if output_path and output_path.exists():
            os.remove(output_path)

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


def _edit_layer(procedure, run_mode, image, drawables, config):
    """Edit the current layer via the SD server API."""
    server_url = config.get_property("server-url") or DEFAULT_SERVER_URL
    prompt = config.get_property("prompt") or ""
    steps = config.get_property("steps") or 30
    cfg_scale = config.get_property("cfg-scale") or 7.0
    denoising = config.get_property("denoising-strength") or 0.75
    negative_prompt = config.get_property("negative-prompt") or ""

    Gimp.context_push()
    image.undo_group_start()

    if not drawables:
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR,
            GLib.Error("No drawable provided.")
        )

    drawable = drawables[0]
    input_path = None
    output_path = None

    # Check server capabilities to pick the right endpoint
    caps = _fetch_capabilities(server_url)
    model_name = (caps.get("model", {}) or {}).get("stem", "") if caps else ""
    supports_init_image = caps.get("features", {}).get("init_image", False) if caps else False

    # Vision-based edit models (Boogu, Qwen Image Edit) use the native
    # /sdcpp/v1/img_gen endpoint with init_image + strength, which avoids
    # the vision LLM tokenizer (massive RAM usage).
    is_vision_edit = any(kw in model_name.lower() for kw in
                         ["boogu-edit", "boogu_image", "qwen-image-edit",
                          "qwen_image_edit", "longcat-image-edit"])
    is_kontext = "kontext" in model_name.lower()
    # Models that support ref_images need both init_image and extra_images
    supports_ref = caps.get("features", {}).get("ref_images", False) if caps else False

    try:
        temp_dir = Path(tempfile.gettempdir())
        input_path = temp_dir / f"gimp_sdserver_input_{os.getpid()}.png"
        output_path = temp_dir / f"gimp_sdserver_output_{os.getpid()}.png"

        Gimp.progress_init(_("Saving layer for editing..."))

        Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE,
            image,
            Gio.File.new_for_path(str(input_path)),
            None
        )

        Gimp.progress_set_text(_("Sending to SD server for editing..."))
        Gimp.progress_pulse()

        import requests
        import base64
        from PIL import Image
        import io

        with open(input_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        if is_kontext or supports_ref:
            # Models with ref_image support (Kontext, Boogu, Z-Image) need
            # extra_images for reference conditioning + init_images for VAE.
            payload = {
                "prompt": prompt,
                "init_images": [img_b64],
                "extra_images": [img_b64],
                "strength": denoising,
                "steps": steps,
                "cfg_scale": cfg_scale,
            }
        else:
            # Standard SD img2img: init_images + denoising_strength.
            payload = {
                "prompt": prompt,
                "init_images": [img_b64],
                "steps": steps,
                "cfg_scale": cfg_scale,
                "denoising_strength": denoising,
            }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        width = config.get_property("width")
        height = config.get_property("height")
        if width:
            payload["width"] = width
        if height:
            payload["height"] = height

        response = requests.post(
            f"{server_url}/sdapi/v1/img2img",
            json=payload,
            timeout=600,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("images"):
            raise RuntimeError("No images in API response")
        image_data = Image.open(
            io.BytesIO(base64.b64decode(data["images"][0]))
        )
        image_data.save(str(output_path))

        Gimp.progress_set_text(_("Loading edited image..."))

        imported_image = Gimp.file_load(
            run_mode, Gio.File.new_for_path(str(output_path))
        )
        if not imported_image:
            raise RuntimeError("Failed to load edited image")

        new_layer = imported_image.get_layers()[0]
        layer_type = Gimp.ImageType.RGBA_IMAGE

        final_layer = Gimp.Layer.new(
            image,
            _("SD Server Edit"),
            new_layer.get_width(),
            new_layer.get_height(),
            layer_type,
            100.0,
            Gimp.LayerMode.NORMAL
        )

        drawable = drawables[0]
        image.insert_layer(
            final_layer, drawable.get_parent(),
            image.get_item_position(drawable)
        )

        Gimp.progress_set_text(_("Transferring layer data..."))

        Gimp.edit_copy([new_layer])
        floating_sel = Gimp.edit_paste(final_layer, False)
        Gimp.floating_sel_anchor(floating_sel[0])

        Gimp.Image.delete(imported_image)

        final_layer.set_name(_("SD Server"))
        final_layer.set_visible(True)
        drawable.set_visible(False)
        image.active_layer = final_layer
        image.resize_to_layers()

    except Exception as e:
        Gimp.message(_("Error: %s") % e)
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e))
        )

    finally:
        if input_path and input_path.exists():
            os.remove(input_path)
        if output_path and output_path.exists():
            os.remove(output_path)

    Gimp.displays_flush()
    image.undo_group_end()
    Gimp.context_pop()

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class SDServer(Gimp.PlugIn):
    __gtype_name__ = "SDServer"

    def do_set_i18n(self, procname):
        return True, PLUGIN_NAME, None

    def do_query_procedures(self):
        return ["python-fu-sd-server"]

    def do_create_procedure(self, name):
        Gegl.init(None)

        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, sd_server_func, None
        )

        # Available with or without an image (for generation mode)
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.ALWAYS
        )
        procedure.set_image_types("*")

        procedure.set_documentation(
            _("SD Server"),
            _("Edit the current layer or generate a new image using a "
              "local stable-diffusion.cpp server API."),
            name,
        )
        procedure.set_menu_label(_("_SD Server..."))
        procedure.set_attribution(
            "stable-diffusion.cpp (API), Henry Kroll III (Plugin)",
            "Henry Kroll III",
            "2026"
        )
        procedure.add_menu_path("<Image>/Filters/AI")

        # Server URL
        procedure.add_string_argument(
            "server-url", _("Server URL"),
            _("URL of the stable-diffusion.cpp server"),
            DEFAULT_SERVER_URL, GObject.ParamFlags.READWRITE,
        )
        # Generate new image flag
        procedure.add_boolean_argument(
            "generate-new", _("Generate new"),
            _("Generate a new image instead of editing the current layer"),
            False, GObject.ParamFlags.READWRITE,
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
            1, 100, 30, GObject.ParamFlags.READWRITE,
        )
        # CFG scale
        procedure.add_double_argument(
            "cfg-scale", _("CFG S_cale"),
            _("Classifier-free guidance scale"),
            1.0, 30.0, 7.0, GObject.ParamFlags.READWRITE,
        )
        # Denoising strength
        procedure.add_double_argument(
            "denoising-strength", _("_Denoising"),
            _("img2img denoising strength (0=no change, 1=full change)"),
            0.0, 1.0, 0.75, GObject.ParamFlags.READWRITE,
        )
        # Prompt
        procedure.add_string_argument(
            "prompt", _("_Prompt"),
            _("Describe the image you want to generate or edit"),
            "", GObject.ParamFlags.READWRITE,
        )
        # Negative prompt
        procedure.add_string_argument(
            "negative-prompt", _("_Negative Prompt"),
            _("Things you don't want in the image"),
            "", GObject.ParamFlags.READWRITE,
        )

        return procedure


Gimp.main(SDServer.__gtype_name__, sys.argv)
