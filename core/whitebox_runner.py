"""Thin glue to the bundled WhiteboxTools binary.

Depression-filling and D8 flow accumulation stay on WhiteboxTools rather than
a native QGIS/GDAL/GRASS equivalent: GRASS's r.fill.dir matches WBT's fill
closely (validated: 97%+ of cells identical), but neither r.watershed nor
r.terraflow reproduces WBT's D8 accumulation on the highest-order drainage
cells (correlation as low as -0.39 there), because each tool resolves flow
direction ties across filled-flat areas differently. Keeping fill +
accumulation on the one tool that's proven internally consistent avoids that
mismatch, at the cost of bundling one small per-platform binary.

Populate vendor/whitebox/ the same way the desktop tool's README describes
for its root-level whitebox/ folder (not tracked in git due to size):
https://www.whiteboxgeo.com/geospatial-software/
"""

import sys

from ..vendor.whitebox.whitebox_tools import WhiteboxTools


class _DummyStream:
    def write(self, *args, **kwargs):
        pass

    def flush(self, *args, **kwargs):
        pass


def get_whitebox_tools():
    # vendor/whitebox/whitebox_tools.py calls sys.stdout.flush() unconditionally
    # (regardless of verbose) after every line it reads from the subprocess.
    # QGIS's embedded Python has no attached console, so sys.stdout/stderr are
    # None there - same root cause the desktop tool's main_app.py already
    # guards against with an identical dummy-stream fallback.
    if sys.stdout is None:
        sys.stdout = _DummyStream()
    if sys.stderr is None:
        sys.stderr = _DummyStream()

    wbt = WhiteboxTools()
    wbt.verbose = False
    wbt.remote_download = False
    return wbt
