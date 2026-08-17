# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Projectify desktop app — shared by the Mac and
Windows CI jobs so both freeze identically.

PyInstaller finds imports by static analysis, which misses three things this app
relies on. Each block below exists because leaving it out produces a build that
compiles fine and then dies at runtime on the user's machine:

  * pdfplumber/pdfminer load CMap and encoding tables from package *data* files.
    Without them the app launches and then throws on the first PDF.
  * pywebview picks its GUI backend by dynamic import at startup and ships JS
    bridge assets as data.
  * keyring discovers its OS backend through an entry-point scan, invisible to
    static analysis — no backend means the setup wizard can't store the PAT.

Build:  pyinstaller --noconfirm packaging/Projectify.spec
Output: dist/Projectify.app (macOS) · dist/Projectify/ (Windows)
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821 (PyInstaller global)

datas, binaries, hiddenimports = [], [], []


def _bundle(package):
    """collect_all(package), tolerating packages absent on this platform."""
    global datas, binaries, hiddenimports
    try:
        d, b, h = collect_all(package)
    except Exception:
        return
    datas += d
    binaries += b
    hiddenimports += h


# PDF parsing stack — data files are the point here, not the modules.
for _pkg in ("pdfplumber", "pdfminer", "pypdfium2"):
    _bundle(_pkg)

# Native window + its JS bridge assets.
_bundle("webview")

# TLS trust for the Asana calls. certifi's cacert.pem is a data file PyInstaller
# will not pick up on its own, and truststore is imported lazily inside
# csms.asana_client, so neither is reachable by static analysis.
_bundle("certifi")
hiddenimports += collect_submodules("truststore")

# OS keychain backends (macOS Keychain / Windows Credential Manager).
hiddenimports += collect_submodules("keyring.backends")

if sys.platform == "win32":
    # pywebview's EdgeChromium backend calls into WinForms through pythonnet.
    hiddenimports += ["clr", "System", "System.Windows.Forms"]
    for _pkg in ("clr_loader", "pythonnet"):
        _bundle(_pkg)

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],  # noqa: F821
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Test-only and dev-only deps; excluded to keep the download small.
    excludes=["tkinter", "pytest", "matplotlib", "numpy.testing"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Projectify",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # no console window behind the app
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Projectify",
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Projectify.app",
        bundle_identifier="com.lettersclark.projectify",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            # Contracts are read from disk and never uploaded anywhere but Asana.
            "NSHumanReadableCopyright": "Letters & Clark",
        },
    )
