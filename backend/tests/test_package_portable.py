import zipfile

from app._version import __version__
from scripts import package_portable


def test_portable_package_includes_app_but_never_existing_user_data(tmp_path, monkeypatch):
    dist_dir = tmp_path / "QuestionBank-Portable"
    dist_dir.mkdir()
    (dist_dir / "question-bank.exe").write_bytes(b"exe")
    (dist_dir / "dependency.dll").write_bytes(b"dll")
    data_dir = dist_dir / "data"
    data_dir.mkdir()
    (data_dir / "app.db").write_bytes(b"private database")
    readme = tmp_path / "README.txt"
    readme.write_text("portable instructions", encoding="utf-8")
    archive_path = tmp_path / f"QuestionBank-Portable-{__version__}.zip"

    monkeypatch.setattr(package_portable, "DIST_DIR", dist_dir)
    monkeypatch.setattr(package_portable, "ARCHIVE_PATH", archive_path)
    monkeypatch.setattr(package_portable, "README_SOURCE", readme)

    package_portable.main()

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "QuestionBank-Portable/question-bank.exe" in names
        assert "QuestionBank-Portable/dependency.dll" in names
        assert "QuestionBank-Portable/portable.mode" in names
        assert "QuestionBank-Portable/README.txt" in names
        assert not any("/data/" in name for name in names)
