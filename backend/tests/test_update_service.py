from app.services.update_service import PortableUpdateService


def make_staging(path):
    path.mkdir()
    (path / "QuizForge.exe").write_bytes(b"exe")
    (path / "_internal").mkdir()
    (path / "portable.mode").write_text("portable", encoding="utf-8")
    return path


def test_update_staging_requires_portable_files_and_excludes_user_data(tmp_path):
    staging = make_staging(tmp_path / "valid")
    assert PortableUpdateService._valid_staging(staging)

    (staging / "data").mkdir()
    assert not PortableUpdateService._valid_staging(staging)


def test_update_staging_rejects_missing_runtime(tmp_path):
    staging = tmp_path / "missing-runtime"
    staging.mkdir()
    (staging / "QuizForge.exe").write_bytes(b"exe")
    (staging / "portable.mode").write_text("portable", encoding="utf-8")

    assert not PortableUpdateService._valid_staging(staging)


def test_update_check_is_safe_when_running_outside_portable_build():
    service = PortableUpdateService()

    result = service.check()

    assert result["phase"] == "unsupported"
    assert result["available"] is False


async def test_update_check_and_health_endpoints_are_setup_safe(client):
    version = await client.get("/api/v1/system/version")
    check = await client.get("/api/v1/system/update/check")
    health = await client.get("/api/v1/system/update/health")

    assert version.status_code == 200
    assert version.json()["portable"] is False
    assert version.json()["updater"] == "none"
    assert check.status_code == 200
    assert check.json()["phase"] == "unsupported"
    assert health.status_code == 200
    assert health.json()["migrations_ok"] is False
