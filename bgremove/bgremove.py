#!/usr/bin/env python3
#   Copyright (C) 2025-2026 Henry Kroll III
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
PLUGIN_NAME = "python-fu-bgremove"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'locale'))

# Set up gettext for the C library (GIMP/GTK)
locale.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)

# Set up gettext for Python
gettext.bindtextdomain(PLUGIN_NAME, LOCALE_DIR)
gettext.textdomain(PLUGIN_NAME)

def _(message): return gettext.gettext(message)
def N_(message): return message # For strings that should not be translated immediately

def bgremove_func(procedure, run_mode, image, drawables, config, data):
    # This plugin is primarily non-interactive, as backgroundremover has few user options
    # and we want quick execution.

    Gimp.context_push()
    image.undo_group_start()

    # We will process only the first active drawable for simplicity
    if not drawables:
        # Should not happen if sensitivity mask is set correctly, but handle safety
        return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error("No drawable provided."))

    drawable = drawables[0]

    input_path = None
    output_path = None

    try:
        # 1. Create temporary files

        # We use tempfile to safely handle temp file creation and naming
        temp_dir = Path(tempfile.gettempdir())

        # We must ensure the input path has a known extension (e.g., PNG) for GIMP export
        # and for backgroundremover to identify the format.
        input_path = temp_dir / f"gimp_bgremove_input_{os.getpid()}.png"
        output_path = temp_dir / f"gimp_bgremove_output_{os.getpid()}.png"

        Gimp.progress_init(_("Saving image for processing..."))

        # 2. Save the active drawable to a temporary PNG file
        # Use Gimp.file_save which handles export based on file extension
        # We need an image object for file_save, so we use the parent image.

        # NOTE: Gimp.file_save saves the whole image, not just the drawable.
        # This is usually desired for background removal context.
        Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE,
            image,
            Gio.File.new_for_path(str(input_path)),
            None       # Progress data (4th argument)
        )

        Gimp.progress_set_text(_("Running background removal (this may take time)..."))
        Gimp.progress_pulse()

        # 3. Execute the backgroundremover command
        command = [
            "backgroundremover",
            "-i", str(input_path),
            "-o", str(output_path),
            # Optional parameters can be added here, e.g., --model u2net
        ]

        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            error_message = _("Background remover failed. Ensure 'backgroundremover' is installed and working.")
            Gimp.message(f"{error_message}\nError Output: {result.stderr}")
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        # 4. Load the processed image back into GIMP
        if not output_path.exists():
            error_message = _("Background remover executed successfully but failed to create the output file.")
            Gimp.message(error_message)
            return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        Gimp.progress_set_text(_("Loading processed image..."))

        # Load the new image file. This returns a new Gimp.Image object temporarily
        imported_image = Gimp.file_load(run_mode, Gio.File.new_for_path(str(output_path)))

        if not imported_image:
             error_message = _("Failed to load the processed image file.")
             Gimp.message(error_message)
             return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(error_message))

        # Get the new layer (should be the first drawable in the imported image)
        new_layer = imported_image.get_layers()[0]

        # Determine the type of layer we need (RGBA is crucial for transparency)
        layer_type = Gimp.ImageType.RGBA_IMAGE

        # 5. Create a brand new layer in the original image (The destination)
        final_layer = Gimp.Layer.new(
            image,
            _("Background Removed Layer"),
            new_layer.get_width(),
            new_layer.get_height(),
            layer_type,
            100.0,
            Gimp.LayerMode.NORMAL
        )

        # Insert the new, empty layer into the original image
        drawable = drawables[0] # Reference to the original layer for position
        image.insert_layer(final_layer, drawable.get_parent(),
                           image.get_item_position(drawable))

        Gimp.progress_set_text(_("Transferring layer data..."))

        # 6. Copy the new_layer image data to the final_layer
        Gimp.edit_copy([new_layer])

        floating_sel = Gimp.edit_paste(final_layer, False)
        Gimp.floating_sel_anchor(floating_sel[0])

        # Clean up temp image
        Gimp.Image.delete(imported_image)

        # Final setup
        final_layer.set_name(_("Background Removed"))
        final_layer.set_visible(True)
        drawable.set_visible(False)
        image.active_layer = final_layer


    except Exception as e:
        Gimp.message(_("An unexpected error occurred: %s") % e)
        return procedure.new_return_values(Gimp.PDBStatusType.ERROR, GLib.Error(str(e)))

    finally:
        # 5. Cleanup temporary files
        if input_path and input_path.exists():
            os.remove(input_path)
        if output_path and output_path.exists():
            os.remove(output_path)

    Gimp.displays_flush()
    image.undo_group_end()
    Gimp.context_pop()

    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

class BgRemove (Gimp.PlugIn):
    ## GimpPlugIn virtual methods ##
    def do_set_i18n(self, procname):
        return True, PLUGIN_NAME, None

    def do_query_procedures(self):
        return [ 'python-fu-bgremove' ]

    def do_create_procedure(self, name):
        Gegl.init(None)

        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            bgremove_func, None)

        procedure.set_image_types("RGB*, GRAY*");

        # This ensures the plugin runs on the currently active layer/drawable
        procedure.set_sensitivity_mask (Gimp.ProcedureSensitivityMask.DRAWABLE |
                                        Gimp.ProcedureSensitivityMask.DRAWABLES)

        procedure.set_documentation (_("Remove Background"),
                                     _("Uses the external 'backgroundremover' tool to automatically remove the background from the active image or layer."),
                                     name)

        procedure.set_menu_label(_("Remove _Background..."))
        procedure.set_attribution("James Henstridge (Template), Nadermx/BackgroundRemover (Tool), Henry Kroll III (Plugin Adaption)",
                                  "Henry Kroll III",
                                  "2026")

        # Add to the Layer/Transparency menu
        procedure.add_menu_path ("<Image>/Filters/AI")

        # No configuration arguments needed for basic execution

        return procedure

Gimp.main(BgRemove.__gtype__, sys.argv)
