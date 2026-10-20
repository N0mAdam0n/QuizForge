"""Create a self-contained ZIP archive from the PyInstaller portable build."""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app._version import __version__


DEFAULT_DIST_DIR = BACKEND_DIR / "dist" / "QuestionBank-Portable"
DEFAULT_ARCHIVE_PATH = BACKEND_DIR / "dist" / f"QuestionBank-Portable-{__version__}.zip"
README_SOURCE = BACKEND_DIR / "deploy" / "windows" / "portable" / "README.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=DEFAULT_DIST_DIR)
    parser.add_argument("--archive-path", type=Path, default=DEFAULT_ARCHIVE_PATH)
    args = parser.parse_args()
    dist_dir: Path = args.dist_dir
    archive_path: Path = args.archive_path

    if not (dist_dir / "question-bank.exe").is_file():
        raise FileNotFoundError(
            f"Portable executable not found at {dist_dir}; build run-portable.spec first."
        )

    (dist_dir / "portable.mode").write_text(
        "QuestionBank portable data is stored in the sibling data directory.\n",
        encoding="utf-8",
    )
    shutil.copy2(README_SOURCE, dist_dir / "README.txt")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(dist_dir.rglob("*")):
            if path.is_file() and path.relative_to(dist_dir).parts[0] != "data":
                archive.write(path, path.relative_to(dist_dir.parent))

    print(f"Created {archive_path}")


if __name__ == "__main__":
    main()
