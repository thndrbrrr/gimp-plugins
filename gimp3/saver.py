#!/usr/bin/env python

# This is a plug-in intended to be bound to Ctrl-S, and to act as
# a combination of Save, Save as..., Overwrite, and Export...
#
# It saves the image (whether its type would normally require Saving
# or Exporting), and optionally allows for a copy of the image to be
# exported to another file, possibly also scaled differently.
# The copy must be saved to the same directory as the original
# (because juggling two file choosers would make the dialog too huge
# to fit on most screens!)
#
# Regardless of image format chosen, the image will be marked clean
# so you won't get prompted for an unsaved image at quit or close time.
#
# The first time you save a file, you should be prompted for filename
# (even if you opened an existing file).
# After that, the plug-in will remember the filename you set.
# You can always change it with Saver as...
#
# So you can have your XCF with high resolution and all layers,
# and automatically export to a quarter-scale JPEG copy every time
# you save the original. Or you can just overwrite your JPG if
# all you're doing is a quick edit.
#
# The basic save filename follows img.filename.
# The copy, if any, is saved in a parasite:
# export-scaled: filename\npercent\nwidth\nheight

# This plug-in is hosted at https://github.com/akkana/gimp-plugins/blob/master/saver.py

# Copyright 2013,2014,2022 by Akkana Peck, http://www.shallowsky.com/software/
# You may use and distribute this plug-in under the terms of the GPL v2
# or, at your option, any later GPL version.

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gio

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk

import os, sys

def N_(message): return message
def _(message): return GLib.dgettext(None, message)

busy = False


def gimp_file_save(image, layers, filepath):
    """A PDB helper. Returns a Gimp.PDBStatusType"""
    return Gimp.get_pdb().run_procedure('gimp-file-save', [
        GObject.Value(Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE),
        GObject.Value(Gimp.Image, image),
        # Unlike some calls, file-save needs the size before the array
        GObject.Value(GObject.TYPE_INT, len(layers)),
        GObject.Value(Gimp.ObjectArray,
                      Gimp.ObjectArray.new(Gimp.Drawable,
                                          layers, False)),
        GObject.Value(Gio.File, Gio.File.new_for_path(filepath))
    ])


# A way to turn off notifications while we're calculating
# busy = False


class SaverPlugin(Gimp.PlugIn):
    ## Parameters ##
    __gproperties__ = {
    }

    ## GimpPlugIn virtual methods ##
    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return [ "python-fu-saver", "python-fu-saver-as" ]

    def do_create_procedure(self, name):
        """Register as a GIMP plug-in"""

        if name == "python-fu-saver-as":
            procedure = Gimp.ImageProcedure.new(self, name,
                                                Gimp.PDBProcType.PLUGIN,
                                                self.saver_as_dialog, None)
            procedure.set_menu_label("_Saver As");
        elif name == "python-fu-saver":
            procedure = Gimp.ImageProcedure.new(self, name,
                                                Gimp.PDBProcType.PLUGIN,
                                                self.saver, None)
            procedure.set_menu_label("_Saver");
        else:
            print("Eek, saver.py can't register", name)
            return

        # Both Saver and Saver As use all of the following
        procedure.set_image_types("*");

        procedure.set_icon_name(GimpUi.ICON_GEGL);
        procedure.add_menu_path('<Image>/File/Save/');

        procedure.set_documentation(
            "Save/export the current image",
            "Save/export the current image, "
            "optionally also exporting a scaled version",
            name);
        procedure.set_attribution("Akkana Peck", "Akkana Peck",
                                  "2010,2011,2022");

        return procedure

    @staticmethod
    def save_both(image, filepath, copyname, copywidth, copyheight):
        '''Save the image, and also save the copy if appropriate,
           doing any duplicating or scaling that might be necessary.
           Returns None on success, else a nonempty string error message.
           Also sets the image's filename to filepath.
        '''
        msg = "Saving " + filepath

        layers = image.list_selected_layers()

        def is_xcf(thefilename):
            base, ext = os.path.splitext(thefilename)
            ext = ext.lower()
            if ext == '.gz' or ext == '.bz2':
                base, ext = os.path.splitext(base)
                ext = ext.lower()
            return (ext == '.xcf')

        # First, save the original image.
        if is_xcf(filepath) or len(layers) < 2:
            mainres = gimp_file_save(image, layers, filepath)
            print("saved original to", filepath)
        else:
            # It's not XCF and it has multiple layers.
            # We need to make a new image and flatten it.
            copyimg = pdb.gimp_image_duplicate(img)
            # Don't actually flatten since that will prevent saving
            # transparent png.
            #copyimg.flatten()
            copyimage.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            mainres = gimp_file_save(copyimage, [copyimg.active_layer],
                                     filepath)
            gimp.delete(copyimg)
            print("merged layers then saved to", filepath)

        # print("result of main img gimp-file-save:", mainres, mainres.index(0))
        if (mainres.index(0) != Gimp.PDBStatusType.SUCCESS):
            print("gimp-file-save failed: %s" % mainres, file=sys.stderr)
            return mainres.index(0)

        # The important part is done, so mark the image clean
        # and record the filename: set_file expects a Gio.File.
        image.set_file(Gio.File.new_for_path(filepath))
        image.clean_all()

        print("Saver: copy is %s (%dx%d)" % (copyname, copywidth, copyheight))

        # Now try to save the copy, if applicable
        if (not copyname or not copywidth or not copyheight or
            copyname == filepath or copyname == os.path.basename(filepath)
            or (copywidth == image.get_width()
                and copyheight == image.get_height())):
            print("No need to save a copy")
            return mainres

        # Set up the parasite with information about the copied image,
        # so it will be saved with the main XCF image.
        if copywidth and copyheight:
            # print("percent is", copywidth, "* 100.0 /", image.get_width())
            # print("types:", type(copywidth), type(image.get_width()))
            percent = copywidth * 100.0 / image.get_width()
            # Note that this allows changed aspect ratios,
            # though the Saver As dialog doesn't allow that.
            parastring = '%s\n%d\n%d\n%d' % (copyname, percent,
                                             copywidth, copyheight)
            msg += "Saving a scaled copy '%s' (%dx%d), " \
                % (copyname, copywidth, copyheight)
        else:
            parastring = '%s\n100.0\n0\n0' % (copyname)
        print("Saving parasite:", parastring, "(end of parastring)")
        para = Gimp.Parasite.new("export-copy", 1, parastring.encode())
        print("trying to attach parasite to main image:", para)
        print("parasite name:", para.name)
        print("Parasite data:", bytes(para.get_data()))
        image.attach_parasite(para)

        # Don't use gimp_message -- it can pop up a dialog.
        # pdb.gimp_message_set_handler(MESSAGE_BOX)
        # pdb.gimp_message(msg)
        # Alternately, could use gimp_progress, though that's not ideal.
        # If using gimp_progress, don't forget to call pdb.gimp_progress_end()
        #pdb.gimp_progress_set_text(msg)

        # Is there any point to pushing and popping the context?
        #gimp.context_pop()

        # If copyname isn't a full pathname, make it relative to
        # the dirname of the main image.
        if copyname.startswith('/'):
            copypath = copyname
        else:
            copypath = os.path.join(os.path.dirname(filepath), copyname)

        # Now the parasite is safely attached, and we can save to copypath.
        # Alas, we can't attach the JPEG settings parasite until after
        # we've saved the copy, so that won't get saved with the main image
        # though it will be attached to the image and remembered in
        # this session, and the next time we save it should be remembered.

        imglayers = image.list_selected_layers()

        # We'll need a new image if the copy is non-xcf and we have more
        # than one layer, or if we're scaling.
        if (copywidth and copyheight):
            # We're scaling!
            copyimg = image.duplicate()
            print("Scaling to", copywidth, 'x', copyheight)
            copyimg.scale(copywidth, copyheight)
            if len(imglayers) > 1 and not is_xcf(copyname):
                copyimg.merge_visible_layers(copyimg, CLIP_TO_IMAGE)
                print("Also merging")
            else:
                print("No need to merge")

        elif len(imglayers) > 1 and not is_xcf(copyname):
            # We're not scaling, but we still need to flatten.
            copyimg = image.duplicate()
            # copyimg.flatten()
            copyimg.merge_visible_layers(copyimg, CLIP_TO_IMAGE)
            print("Merging but not scaling")

        else:
            copyimg = image
            print("Not scaling or flattening")

        # gimp-file-save insists on being passed a valid layer,
        # even if saving to a multilayer format such as XCF. Go figure.
        copylayers = copyimg.list_selected_layers()
        print("Calling gimp_file_save for copy", copyimg, copylayers, copypath)
        copyres = gimp_file_save(copyimg, copylayers, copypath)
        if (copyres.index(0) != Gimp.PDBStatusType.SUCCESS):
            print("Failed to save the copy")
            return copyres.index(0)

        # Find any image type settings parasites (e.g. jpeg settings)
        # that got set during save, so we'll be able to use them
        # next time.
        def copy_settings_parasites(fromimg, toimg):
            if fromimg == toimg:
                print("Same image, not copying")
                return
            for pname in fromimg.get_parasite_list():
                if pname[-9:] == '-settings' or pname[-13:] == '-save-options':
                    para = fromimg.get_parasite(pname)
                    if para:
                        toimg.attach_parasite(pname, para.flags, para.data)

        # Copy any settings parasites we may have saved from previous runs:
        copy_settings_parasites(copyimg, image)

        gimp.delete(copyimg)
        return None

    def init_from_parasite(self, img):
        '''Returns copyname, percent, width, height.'''
        para = img.get_parasite('export-copy')
        if para:
            print("Got parasite!")
            try:
                data = bytes(para.get_data()).decode()
                print("Parasite data:", data)
                paravals = [ 0 if x == 'None' or x == '' else x
                             for x in data.split('\n') ]
                self.copyname = paravals[0]
                self.export_percent = float(paravals[1])
                self.export_width = int(paravals[2])
                self.export_height = int(paravals[3])
                print("Read parasite values",
                      self.copyname, self.export_percent,
                      self.export_width, self.export_height)
            except Exception as e:
                print("Exception getting parasite values:", e)
                para = None
        if not para:
            print("No parasite")
            self.copyname = None
            self.export_percent = 100.0
            self.export_width = img.get_width()
            self.export_height = img.get_height()

    def saver(self, procedure, run_mode, image, n_drawables, drawables,
              args, data):

        # Can't print these: "TypeError: 'ValueArray' object is not iterable"
        # print("Would run saver plug-in with:")
        # print("args:", [x for x in args])
        # print("data:", [x for x in data])

        if not image.get_file():    # No filename set yet
            print("No filename set! Showing dialog")
            return self.saver_as_dialog(procedure, run_mode,
                                        image, n_drawables, drawables,
                                        args, data)

        filepath = image.get_file().get_path()

        # Now see if there's a parasite with copyimg info
        self.init_from_parasite(image)

        if self.copyname:
            print("Image has parasite data: copyname is", self.copyname,
                  "at", self.export_width, "x", self.export_height)
        print("Image's file is:", image.get_file().get_path())

        save_err = self.save_both(image, filepath,
                                  self.copyname,
                                  self.export_width, self.export_height)
        print("save_both returned", save_err)
        print("Now image.get_file() is",
              image.get_file(), image.get_file().get_path())

    def saver_as_dialog(self, procedure, run_mode, image,
                        n_drawables, drawables,
                        args, data):

        self.init_from_parasite(image)

        # Are the next two lines needed if we don't fetch any properties?
        config = procedure.create_config()
        config.begin_run(image, run_mode, args)

        if run_mode != Gimp.RunMode.INTERACTIVE:
            print("EEK, 'saver as' but not interactive?")
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
                                               GLib.Error())

        # GimpUi.init("saver")
        chooser = SaverChooserWin(image, self)

        while True:
            response = chooser.run()
            sys.stdout.flush()
            if response != Gtk.ResponseType.OK:
                chooser.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL,
                                                   GLib.Error())

            #### Save both the main file and a copy (if specified)
            filepath = chooser.get_filename()
            copyname, percent, copywidth, copyheight = chooser.get_copy_info()

            save_err = self.save_both(image, filepath,
                                      copyname, copywidth, copyheight)
            if save_err.index(0) == Gimp.PDBStatusType.SUCCESS:
                chooser.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                                   GLib.Error())
            print("SAVER looping:", save_err, file=sys.stderr)


class SaverChooserWin(Gtk.FileChooserDialog):
    def __init__(self, image, saver):
        self.image = image
        self.saver = saver

        # Create the dialog
        title = "GIMP Saver"
        if image.get_name():
            title = "%s: %s" % (title, image.get_name())
        Gtk.FileChooserDialog.__init__(self,
                                       title=title,
                                       action=Gtk.FileChooserAction.SAVE)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         "Save", Gtk.ResponseType.OK)
        # other maybe mandatory options:
        # https://docs.gtk.org/gtk3/class.FileChooserDialog.html

        # Obey the window manager quit signal:
        self.connect("destroy", Gtk.main_quit)

        imagefile = image.get_file()
        if imagefile:
            path = image.get_file().get_path()
            print("Existing path:", path)
            self.set_current_folder(os.path.dirname(path))
            self.set_filename(path)
        else:
            print("saver: image doesn't have a filename yet")

        # filter = Gtk.FileFilter()
        # filter.set_name(_("All files (*)"))
        # filter.add_pattern('*')
        # self.add_filter(filter)

        copybox = Gtk.Table(n_rows=3, n_columns=7)

        l = Gtk.Label(label="Saver: Export a copy")
        # name in Gtk css acts like id in html css
        # even though the GtkInspector calls it ID, not name
        l.set_name("savertitle")
        # They deprecated set_alignment, switched to using CSS for most
        # styling ... then didn't include alignment in Label's supported CSS
        # and instead made a new function, set_halign. Go figure.
        l.set_halign(Gtk.Align.START)
        copybox.attach(l, 0, 3, 0, 1, xpadding=5, ypadding=5)

        l = Gtk.Label(label="Export a copy to:")
        copybox.attach(l, 0, 1, 1, 2, xpadding=5, ypadding=5)

        self.copyname_e = Gtk.Entry()
        if self.saver.copyname:
            self.copyname_e.set_text(self.saver.copyname)
        copybox.attach(self.copyname_e, 1, 7, 1, 2, xpadding=5, ypadding=5)

        l = Gtk.Label(label="Scale the copy:")
        copybox.attach(l, 0, 1, 2, 3, xpadding=5, ypadding=5)

        l = Gtk.Label(label="Percent:")
        copybox.attach(l, 1, 2, 2, 3, xpadding=5, ypadding=5)

        adj = Gtk.Adjustment(value=int(self.saver.export_percent),
                             lower=1, upper=10000,
                             step_increment=1, page_increment=10, page_size=0)
        self.percent_e = Gtk.SpinButton.new(adj, 0, 0)
        copybox.attach(self.percent_e, 2, 3, 2, 3, xpadding=5, ypadding=5)

        l = Gtk.Label(label="Width:")
        copybox.attach(l, 3, 4, 2, 3, xpadding=5, ypadding=5)

        adj = Gtk.Adjustment(value=int(self.saver.export_width),
                             lower=1, upper=10000,
                             step_increment=1, page_increment=10, page_size=0)
        self.width_e = Gtk.SpinButton.new(adj, 0, 0)
        copybox.attach(self.width_e, 4, 5, 2, 3, xpadding=5, ypadding=5)

        l = Gtk.Label(label="Height:")
        copybox.attach(l, 5, 6, 2, 3, xpadding=5, ypadding=5)

        adj = Gtk.Adjustment(value=int(self.saver.export_height),
                             lower=1, upper=10000,
                             step_increment=1, page_increment=10, page_size=0)
        self.height_e = Gtk.SpinButton.new(adj, 0, 0)
        copybox.attach(self.height_e, 6, 7, 2, 3, xpadding=5, ypadding=5)

        # Now that the widgets are created, connect their entry_changed
        self.percent_e.connect("changed", self.entry_changed, 'p');
        self.width_e.connect("changed", self.entry_changed, 'w');
        self.height_e.connect("changed", self.entry_changed, 'h');

        self.warning_label = Gtk.Label(label="")
        self.warning_label.set_name("saverwarning")
        self.warning_label.set_halign(Gtk.Align.START)
        copybox.attach(self.warning_label, 0, 7, 3, 4, xpadding=5, ypadding=5)

        self.set_extra_widget(copybox)

        # Oh, cool, we could have shortcuts to image folders,
        # and maybe remove the stupid fstab shortcuts GTK adds for us.
        # self.add_shortcut_folder(folder)
        # self.remove_shortcut_folder(folder)

        self.show_all()

    def get_copy_info(self):
        """Return copyname, percent, width, height from the Saver As dialog
        """
        try:
            percent = float(self.percent_e.get_text())
        except ValueError:
            percent = 100
        try:
            width = int(self.width_e.get_text())
            height = int(self.height_e.get_text())
        except ValueError:
            width = self.image.get_width()
            height = self.image.get_height()

        return self.copyname_e.get_text(), percent, width, height

    def show_warning(self, s):
        if s:
            self.warning_label.set_text(s)
        else:
            self.warning_label.set_text('')

    def entry_changed(self, entry, which):
        global busy
        if busy:
            return

        # Can't use get_value() or get_value_as_int() because they
        # don't work before an update(), but update() will usually
        # overwrite what the user typed. So define a function:
        def get_num_value(spinbox):
            s = spinbox.get_text()
            if not s:
                return 0

            try:
                p = int(s)
                return p
            except ValueError:
                try:
                    p = float(s)
                    return p
                except ValueError:
                    return 0

        orig_width = self.image.get_width()
        orig_height = self.image.get_height()

        if which == 'p':
            p = get_num_value(self.percent_e)
            if not p: return
            busy = True
            w = int(orig_width * p / 100.)
            self.width_e.set_text(str(w))
            h = int(orig_height * p / 100.)
            self.height_e.set_text(str(h))
            busy = False

        elif which == 'w':
            w = get_num_value(self.width_e)
            if not w: return
            busy = True
            p = int(w * 100. / orig_width)
            self.percent_e.set_text(str(p))
            h = int(orig_height * p / 100.)
            self.height_e.set_text(str(h))
            busy = False

        elif which == 'h':
            h = get_num_value(self.height_e)
            if not h: return
            busy = True
            p = int(h * 100. / orig_height)
            self.percent_e.set_text(str(p))
            w = int(orig_width * p / 100.)
            self.width_e.set_text(str(w))
            busy = False
        else:
            print("I'm confused -- not width, height or percentage:", which)


Gimp.main(SaverPlugin.__gtype__, sys.argv)

