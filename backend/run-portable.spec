# PyInstaller spec for the portable Windows desktop build.
#
# Build with: uv run pyinstaller run-portable.spec --clean
# Requires the generated frontend in ../frontend/.output/public.

from PyInstaller.utils.hooks import collect_all, collect_submodules

import os
import sys

sys.path.insert(0, os.path.abspath("."))

_ICON = os.path.abspath(os.path.join("build", "logo.ico"))
os.makedirs(os.path.dirname(_ICON), exist_ok=True)
try:
    from app.branding import save_ico

    save_ico(_ICON)
except Exception:
    _ICON = None

datas, binaries, hiddenimports = [], [], []

for pkg in [
    "chromadb",
    "onnxruntime",
    "tokenizers",
    "pypandoc",
    "google",
    "openai",
    "passlib",
    "aiosqlite",
    "aiomysql",
    "pystray",
    "PIL",
    "latex2mathml",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

datas += [
    ("alembic", "alembic"),
    ("alembic.ini", "."),
    ("../frontend/.output/public", "frontend"),
]

hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("scripts")
hiddenimports += [
    "aiosqlite",
    "passlib.handlers.bcrypt",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "pystray._win32",
]

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="question-bank",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=_ICON,
)

portable = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="QuestionBank-Portable",
)
