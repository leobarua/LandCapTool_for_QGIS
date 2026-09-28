`whitebox_tools.py`, `LICENSE.txt`, and `settings.json` are tracked in git
and already here - nothing to do for those. The only thing you need to add
per platform is the compiled binary:

  whitebox_tools.exe (Windows, already included)
  whitebox_tools     (Linux/macOS - not tracked, download separately)

Get it from https://www.whiteboxgeo.com/geospatial-software/ and drop the
binary for your platform straight into this folder.

`whitebox_tools.py` here is NOT the vanilla upstream file - it's trimmed
down from the full ~570-method, 10,701-line WhiteboxTools Python API to
just the two tool calls this plugin actually uses (`fill_depressions`,
`d8_flow_accumulation`) plus the `run_tool` machinery they depend on. Do
**not** overwrite it with a fresh download from upstream: the full file
reintroduces extension-install/license-registration/self-update code paths
this plugin never calls, which is exactly what got v0.1.0 blocked by
plugins.qgis.org's security scanner (bandit flags `os.system()` with
string-concatenated shell commands and `urllib.request.urlopen()` in that
unused code, regardless of reachability). See CHANGELOG.md for the before/
after finding counts. If you need a different upstream tool this plugin
doesn't currently call, port just that method over rather than restoring
the whole file.

The full official download also ships a `WBT/` subfolder (duplicate exe +
GUI runner assets) and a `plugins/` folder (separately-licensed extension
tools, e.g. heat_map, raster_calculator) - both are unreferenced by
`whitebox_tools.py`'s own logic (confirmed by reading its source: it always
resolves its working directory to wherever it itself lives, never `WBT/`)
and aren't needed here.

Note: WhiteboxTools ships its own readme.txt - on a case-insensitive
filesystem (Windows, default macOS) that collides with a same-named setup
note, silently overwriting it. That's why these instructions live in
SETUP.md instead of README.txt.

For a published plugin, ship one platform's binaries and detect the OS at
runtime, or publish separate per-platform plugin packages - a single zip
bundling Windows+macOS+Linux binaries would multiply the plugin's size for
no benefit to any single user.
