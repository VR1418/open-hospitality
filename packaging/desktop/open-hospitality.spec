# PyInstaller spec: Open Hospitality desktop, ONE-FOLDER build.
#
# One folder, never --onefile. pystray is LGPL-3.0, and a folder keeps it a
# separately replaceable module (NOTICE); a onefile build would also unpack
# ~170 MB into a temp directory on every single launch.
#
#   uv run --extra desktop --group build python scripts/desktop/build.py
#
# Output: dist/Open Hospitality/ (and dist/Open Hospitality.app on macOS).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 — SPECPATH is injected by PyInstaller
sys.path.insert(0, str(ROOT / "src"))
from usali.desktop.pg_runtime import platform_tag  # noqa: E402

TAG = platform_tag()
PG = ROOT / "vendor" / "postgres" / TAG
PORTAL = ROOT / "frontend" / "dist-desktop"
for required, how in (
    (PG / "bin", "uv run python scripts/desktop/fetch_postgres.py"),
    (PORTAL / "index.html", "cd frontend && npm run build:desktop"),
):
    if not required.exists():
        raise SystemExit(f"missing {required} -- run: {how}")

datas = [
    # The bundle MIRRORS THE REPO LAYOUT: the engine ships as source under
    # src/usali/, beside mapping/, migrations/ and frontend/. Upstream finds
    # several resources relative to its own files — gl_chart, qbo_push,
    # preview and portal_api use Path(__file__).parents[2] — and in this
    # layout parents[2] is the bundle root exactly as it is the repo root in
    # a checkout, so every one of those lookups works without an engine edit.
    (str(ROOT / "src" / "usali"), "src/usali"),
    # Read at runtime from the bundle root (usali.desktop.app.resource_root).
    (str(ROOT / "migrations"), "migrations"),
    (str(ROOT / "mapping"), "mapping"),
    (str(PORTAL), "frontend/dist-desktop"),
    (str(ROOT / "docs" / "reference" / "samples"), "docs/reference/samples"),
    (str(PG), f"vendor/postgres/{TAG}"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE"), "."),
]
datas += collect_data_files("pdfminer")  # font metrics + CMaps pdfplumber reads
# keyring finds its OS backends through entry points, which need the
# package's metadata in the bundle (ADR-D5).
datas += copy_metadata("keyring")

hiddenimports = (
    # Migrations are loaded by FILE PATH, so nothing they import is visible
    # to the analyser — take the whole engine.
    collect_submodules("usali")
    + collect_submodules("pystray")  # the platform backend is chosen at runtime
    + collect_submodules("keyring.backends")  # likewise the keychain backend
    + ["psycopg_binary"]
)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "desktop" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    runtime_hooks=[str(ROOT / "packaging" / "desktop" / "rthook_src_layout.py")],
    # The face-matching extra is off by default and fetched on demand (PRD 6.1).
    excludes=["onnxruntime", "tkinter", "pytest", "testcontainers"],
)
# Analysis still walks usali, which is how its third-party imports get
# collected; only the compiled copies are dropped, so the one engine on the
# path is the src/ layout above.
a.pure = [entry for entry in a.pure if not (entry[0] == "usali" or entry[0].startswith("usali."))]
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Open Hospitality",
    # M1 builds are unsigned and for reviewers: a console window shows the
    # log as it happens. M3 (signing) turns this off.
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Open Hospitality")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Open Hospitality.app",
        # A menu-bar app: no Dock icon, no app menu.
        info_plist={"LSUIElement": True, "CFBundleShortVersionString": "0.1.0"},
    )
