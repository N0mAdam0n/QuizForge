"""Create a self-contained ZIP archive from the PyInstaller portable build."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from app._version import __version__


BACKEND_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = BACKEND_DIR / "dist" / "QuestionBank-Portable"
ARCHIVE_PATH = BACKEND_DIR / "dist" / f"QuestionBank-Portable-{__version__}.zip"
README_SOURCE = BACKEND_DIR / "deploy" / "windows" / "portable" / "README.txt"


def main() -> None:
    if not (DIST_DIR / "question-bank.exe").is_file():
        raise FileNotFoundError(
            f"Portable executable not found at {DIST_DIR}; build run-portable.spec first."
        )

    (DIST_DIR / "portable.mode").write_text(
        "QuestionBank portable data is stored in the sibling data directory.\n",
        encoding="utf-8",
    )
    shutil.copy2(README_SOURCE, DIST_DIR / "README.txt")

    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DIST_DIR.rglob("*")):
            if path.is_file() and path.relative_to(DIST_DIR).parts[0] != "data":
                archive.write(path, path.relative_to(DIST_DIR.parent))

    print(f"Created {ARCHIVE_PATH}")


if __name__ == "__main__":
    main()
