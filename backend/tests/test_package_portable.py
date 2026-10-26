import sys
import zipfile

from app._version import __version__
from scripts import package_portable


def test_portable_package_includes_app_but_never_existing_user_data(tmp_path, monkeypatch):
    dist_dir = tmp_path / "QuizForge-Portable"
    dist_dir.mkdir()
    (dist_dir / "QuizForge.exe").write_bytes(b"exe")
    (dist_dir / "dependency.dll").write_bytes(b"dll")
    data_dir = dist_dir / "data"
    data_dir.mkdir()
    (data_dir / "app.db").write_bytes(b"private database")
    updates_dir = dist_dir / "updates"
    updates_dir.mkdir()
    (updates_dir / "state.json").write_text("private update state", encoding="utf-8")
    readme = tmp_path / "README.txt"
    readme.write_text("portable instructions", encoding="utf-8")
    archive_path = tmp_path / f"QuizForge-Portable-{__version__}.zip"

    monkeypatch.setattr(package_portable, "README_SOURCE", readme)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "package_portable.py",
            "--dist-dir",
            str(dist_dir),
            "--archive-path",
            str(archive_path),
        ],
    )

    package_portable.main()

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "QuizForge-Portable/QuizForge.exe" in names
        assert "QuizForge-Portable/dependency.dll" in names
        assert "QuizForge-Portable/portable.mode" in names
        assert "QuizForge-Portable/README.txt" in names
        assert not any("/data/" in name for name in names)
        assert not any("/updates/" in name for name in names)
