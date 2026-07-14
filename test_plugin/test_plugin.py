#!/usr/bin/env python3
import sys
import gi
gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, GObject, GLib

class TestPlugin(Gimp.PlugIn):
    __gtype_name__ = "TestPlugin"  # <-- PascalCase, no underscores

    def do_query_procedures(self):
        return ["testplugin"]  # <-- all lowercase, canonical

    def do_create_procedure(self, name):
        proc = Gimp.ImageProcedure.new(
            self,
            name,
            Gimp.PDBProcType.PLUGIN,
            self.run,
            None
        )
        proc.set_image_types("*")
        proc.set_menu_label("Test Plugin")
        proc.add_menu_path("<Image>/Filters/AI/")
        proc.set_attribution("Your Name", "Your Name", "2025")
        return proc

    def run(self, procedure, run_mode, image, drawables, args, data):
        Gimp.message("Hello from plugin!")
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

Gimp.main(TestPlugin.__gtype_name__, sys.argv)
