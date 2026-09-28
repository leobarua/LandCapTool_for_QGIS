import os
import zipfile

SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR_NAME = "landcap_plugin"
OUT_DIR = os.path.join(SRC_ROOT, "dist")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_ZIP = os.path.join(OUT_DIR, "landcap_plugin-0.1.0.zip")

EXCLUDE_DIR_NAMES = {"__pycache__", ".git", "dist", "test"}  # test/ is dev-only, not needed at runtime
EXCLUDE_FILE_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo")

n_files = 0
total_bytes = 0
with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(SRC_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        for fname in filenames:
            if fname in EXCLUDE_FILE_NAMES or fname.endswith(EXCLUDE_FILE_SUFFIXES):
                continue
            if fname == "build_zip.py":
                continue
            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, SRC_ROOT)
            arcname = os.path.join(PLUGIN_DIR_NAME, rel_path)
            zf.write(full_path, arcname)
            n_files += 1
            total_bytes += os.path.getsize(full_path)

zip_size = os.path.getsize(OUT_ZIP)
print(f"Wrote {OUT_ZIP}")
print(f"  files: {n_files}")
print(f"  uncompressed: {total_bytes / (1024*1024):.1f} MB")
print(f"  zip size: {zip_size / (1024*1024):.1f} MB")

with zipfile.ZipFile(OUT_ZIP) as zf:
    names = zf.namelist()
    bad = [n for n in names if not n.startswith(PLUGIN_DIR_NAME + "/")]
    print(f"  entries not under {PLUGIN_DIR_NAME}/: {len(bad)}")
    print(f"  __init__.py present: {PLUGIN_DIR_NAME + '/__init__.py' in names}")
    print(f"  metadata.txt present: {PLUGIN_DIR_NAME + '/metadata.txt' in names}")
    print(f"  icon.png present: {PLUGIN_DIR_NAME + '/icon.png' in names}")
    print(f"  whitebox_tools.exe present: {PLUGIN_DIR_NAME + '/vendor/whitebox/whitebox_tools.exe' in names}")
    print(f"  corrupt entry: {zf.testzip()}")
