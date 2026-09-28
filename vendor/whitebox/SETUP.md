This folder needs only what whitebox_tools.py's subprocess wrapper actually
uses - confirmed by reading its source: self.exe_path defaults to whatever
directory whitebox_tools.py itself lives in, it chdir's there before every
tool call, and it only reads settings.json from that same directory. The
full official download's WBT/ subfolder (duplicate exe + assets for the
WbRunner GUI) and plugins/ folder (separately-licensed extension tools we
never call, e.g. heat_map, raster_calculator) are unreferenced by our code
and were removed - dropped the vendored footprint from ~198MB to ~28MB.

Required per platform:
  whitebox_tools.py
  whitebox_tools.exe / whitebox_tools (per-platform binary)
  settings.json
  LICENSE.txt

Not tracked in git due to size. Download the full distribution from:
https://www.whiteboxgeo.com/geospatial-software/
...then copy only the files above into this folder per platform.

Note: WhiteboxTools ships its own readme.txt - on a case-insensitive
filesystem (Windows, default macOS) that collides with a same-named setup
note, silently overwriting it. That's why these instructions live in
SETUP.md instead of README.txt.

For a published plugin, ship one platform's binaries and detect the OS at
runtime, or publish separate per-platform plugin packages - a single zip
bundling Windows+macOS+Linux binaries would multiply the plugin's size for
no benefit to any single user.
