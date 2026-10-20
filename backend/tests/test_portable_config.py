from app.core import config


def test_frozen_portable_build_stores_data_beside_executable(tmp_path, monkeypatch):
    executable_dir = tmp_path / "QuestionBank-Portable"
    executable_dir.mkdir()
    (executable_dir / "portable.mode").write_text("portable", encoding="utf-8")

    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(executable_dir / "question-bank.exe"))
    monkeypatch.setattr(config.sys, "platform", "win32")

    assert config._default_data_dir() == executable_dir / "data"


def test_frozen_installer_keeps_per_user_data_location(tmp_path, monkeypatch):
    executable_dir = tmp_path / "InstalledApp"
    executable_dir.mkdir()

    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(executable_dir / "question-bank.exe"))
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))

    assert config._default_data_dir() == tmp_path / "AppData" / "QuestionBank"
