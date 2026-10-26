"""Copy the desktop and portable packages into a unique versioned output folder."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path(r"D:\VS Code Compile")
VERSION_FILE = BACKEND_DIR / "compile-output-version.txt"
DESKTOP_EXE = BACKEND_DIR / "dist" / "QuizForge.exe"
PORTABLE_DIST = BACKEND_DIR / "build" / "package-to-output" / "QuizForge-Portable"
VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _read_version() -> tuple[int, int, int]:
    value = VERSION_FILE.read_text(encoding="utf-8").strip()
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            f"Invalid compile output version {value!r} in {VERSION_FILE}; expected vX.Y.Z."
        )
    return tuple(int(part) for part in match.groups())


def _format_version(version: tuple[int, int, int]) -> str:
    return f"v{version[0]}.{version[1]}.{version[2]}"


def _next_patch(version: tuple[int, int, int]) -> tuple[int, int, int]:
    return version[0], version[1], version[2] + 1


def main() -> None:
    if not DESKTOP_EXE.is_file():
        raise FileNotFoundError(f"Desktop executable not found: {DESKTOP_EXE}")
    if not (PORTABLE_DIST / "QuizForge.exe").is_file():
        raise FileNotFoundError(
            f"Portable build not found: {PORTABLE_DIST}; build run-portable.spec first."
        )

    version = _read_version()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output_dir = OUTPUT_ROOT / _format_version(version)
    while output_dir.exists():
        version = _next_patch(version)
        output_dir = OUTPUT_ROOT / _format_version(version)
    output_dir.mkdir()

    shutil.copy2(DESKTOP_EXE, output_dir / "QuizForge-Desktop.exe")
    archive_path = output_dir / "QuizForge-Lite.zip"
    subprocess.run(
        [
            sys.executable,
            str(BACKEND_DIR / "scripts" / "package_portable.py"),
            "--dist-dir",
            str(PORTABLE_DIST),
            "--archive-path",
            str(archive_path),
        ],
        cwd=BACKEND_DIR,
        check=True,
    )
    if not archive_path.is_file():
        raise FileNotFoundError(f"Portable archive was not created: {archive_path}")

    VERSION_FILE.write_text(
        _format_version(_next_patch(version)) + "\n",
        encoding="utf-8",
    )
    print(f"Packaged desktop and portable editions in {output_dir}")


if __name__ == "__main__":
    main()
