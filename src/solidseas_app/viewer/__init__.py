"""SolidSeas Viewer, an early preview of the desktop app: a read-only window onto a
folder of SOLIDWORKS documents and other 3D files, built on the ``solidseas``
library: its public and provisional API (``docs/API.md``), and two private helpers
of :mod:`solidseas.jobs` (``_open_model`` and ``_param``) that :mod:`.modeljobs`
shares so its jobs open a file exactly as the library's own jobs do. The viewer
ships from the same repository; a change to those helpers changes both.

* :mod:`.reading` reads what the window shows, and writes exports through the
  CLI's write guards. It imports no Qt, so it is tested on its own.
* :mod:`.workers` runs every file read off the UI thread.
* :mod:`.documents` holds the document list model and its thumbnails,
  :mod:`.details` the details tabs, :mod:`.window` the main window.
  :mod:`.quickfilter` is the row of type buttons under the list's name filter,
  over the table of types in :mod:`.filetypes` (no Qt).
* :mod:`.preview` is the Preview tab: the stored image to pan and zoom and,
  when Settings turn it on, the 3D view of a part (:mod:`.view3d`, drawn with
  OpenGL from the mesh :mod:`.mesh3d` reads, in a child process that
  :mod:`.meshproc` runs). :mod:`.viewmath` holds the pan, zoom and orbit
  arithmetic, without Qt.
* :mod:`.settings` keeps the settings in an INI file in the roaming
  application-data folder, read and written in Python, and
  :mod:`.preferences` is their dialog.
* :mod:`.printing` (no Qt) and :mod:`.printaction` are 3D Print, from the button
  and the right-click menus: the slicer programs found and chosen, the export for
  them next to the model (or in a folder of the user's own under the system's
  temporary folder), and the one function that starts the program.
* Files of other 3D formats (STEP, STL, 3MF, Alibre Design...) are read only in
  worker processes: :mod:`.modelpool` is the window's pool, :mod:`.modeljobs`
  its jobs, :mod:`.modelview` names a model's rows and instances and measures
  its geometry, :mod:`.modeldetails` draws its Overview and :mod:`.thumbnailer`
  draws the thumbnails of files that store none, through the cache.
* :mod:`.selftest` drives the window for automation and screenshots,
  :mod:`.selftest_formats` checks every format on files :mod:`.samples` writes,
  :mod:`.icon` draws the icon and :mod:`.app` is the entry point.

The viewer never writes to, locks or modifies a document it reads. The files it
adds to a folder it reads are a 3D print file, always a new one, next to the
model it was made from (it never replaces a file there, and removes only its own
unfinished one, when that export fails or is cancelled, or, by the next 3D Print,
when the viewer ended while writing it), and a drawing's files, next to the part
by default: its ``.ssdrw`` and its PDF and DXF, never over a file SolidSeas did
not write, Save replacing only the same drawing's own unchanged files, and a
released export never replaced (``docs/DRAWINGS.md`` 12.6).
"""
