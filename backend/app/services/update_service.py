from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.engine import make_url
from tufup.client import AuthRequestsFetcher, Client

from app._version import __version__
from app.core.config import get_db_url, settings

logger = logging.getLogger(__name__)

_APP_NAME = "QuizForge-Portable"


@dataclass
class UpdateStatus:
    phase: str = "idle"
    current_version: str = __version__
    latest_version: str = ""
    available: bool = False
    is_patch: bool = False
    size: int = 0
    downloaded: int = 0
    error: str = ""


class _PinnedFetcher(AuthRequestsFetcher):
    def __init__(self, certificate_path: Path) -> None:
        super().__init__()
        self.socket_timeout = 30
        self.certificate_path = certificate_path

    def _get_session(self, url: str):
        session = super()._get_session(url)
        session.verify = str(self.certificate_path)
        return session


class PortableUpdateService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status = UpdateStatus()
        self._client: Client | None = None
        self._staging_path: Path | None = None
        self._shutdown_callback: Callable[[], None] | None = None
        self._downloader: threading.Thread | None = None

    @staticmethod
    def _install_dir() -> Path:
        return Path(sys.executable).resolve().parent

    @staticmethod
    def _bundled_root_path() -> Path:
        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS")) / "update" / "root.json"
        return Path(__file__).resolve().parents[2] / "deploy" / "windows" / "update" / "root.json"

    @staticmethod
    def _installer_template_path() -> Path:
        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS")) / "update" / "installer.ps1"
        return Path(__file__).resolve().parents[2] / "deploy" / "windows" / "update" / "installer.ps1"

    @property
    def is_portable(self) -> bool:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return False
        install_dir = self._install_dir()
        try:
            return (
                (install_dir / "portable.mode").is_file()
                and settings.DATA_DIR.resolve() == (install_dir / "data").resolve()
            )
        except OSError:
            return False

    @property
    def configured(self) -> bool:
        return self.is_portable and self._bundled_root_path().is_file()

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self._shutdown_callback = callback

    def _paths(self) -> dict[str, Path]:
        updates_dir = self._install_dir() / "updates"
        return {
            "updates": updates_dir,
            "metadata": updates_dir / "metadata",
            "targets": updates_dir / "targets",
            "staging": updates_dir / "staging",
            "backup": updates_dir / "backup",
            "state": updates_dir / "state.json",
            "certificate": updates_dir / "server.crt",
        }

    def _load_persisted_status(self) -> None:
        state_path = self._paths()["state"]
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(state, dict):
            return
        if state.get("status") == "ready":
            staging = self._paths()["staging"]
            if self._valid_staging(staging):
                self._staging_path = staging
                self._status = UpdateStatus(
                    phase="ready",
                    current_version=__version__,
                    latest_version=str(state.get("latest_version") or ""),
                    available=True,
                    is_patch=bool(state.get("is_patch")),
                    size=int(state.get("size") or 0),
                    downloaded=int(state.get("size") or 0),
                )
        elif state.get("status") in {"rolled_back", "rollback_failed", "failed"}:
            messages = {
                "rolled_back": "上次更新未通过启动检查，已自动回滚",
                "rollback_failed": "上次更新失败且回滚不完整，请查看 updates/update.log",
                "failed": "上次更新未能开始（旧进程未退出或安装出错），请查看 updates/update.log",
            }
            self._status = UpdateStatus(
                phase="failed",
                current_version=__version__,
                latest_version=str(state.get("latest_version") or ""),
                error=messages[state["status"]],
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._status.phase == "idle":
                self._load_persisted_status()
            return asdict(self._status)

    def _persist_state(self, status: str) -> None:
        state_path = self._paths()["state"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "status": status,
            "latest_version": self._status.latest_version,
            "is_patch": self._status.is_patch,
            "size": self._status.size,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, state_path)

    def _ensure_tls_certificate(self) -> Path | bool:
        endpoint = settings.UPDATE_METADATA_BASE_URL
        parsed = urlparse(endpoint)
        if parsed.scheme == "http":
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Update HTTP is permitted only for loopback endpoints")
            return True
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Update metadata URL must use HTTPS")

        paths = self._paths()
        cert_path = paths["certificate"]
        pin = settings.TELEMETRY_CERT_SHA256.replace(":", "").upper()
        if cert_path.is_file():
            try:
                certificate = ssl.PEM_cert_to_DER_cert(
                    cert_path.read_text(encoding="ascii")
                )
                if hashlib.sha256(certificate).hexdigest().upper() == pin:
                    return cert_path
            except (OSError, UnicodeError, ValueError):
                cert_path.unlink(missing_ok=True)

        def fetch_pinned_certificate() -> bytes:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection(
                (parsed.hostname, parsed.port or 443), timeout=5
            ) as raw_socket:
                with context.wrap_socket(raw_socket, server_hostname=parsed.hostname) as tls:
                    der_certificate = tls.getpeercert(binary_form=True)
            if hashlib.sha256(der_certificate).hexdigest().upper() != pin:
                raise ssl.SSLError("update server certificate pin mismatch")
            return der_certificate

        der = fetch_pinned_certificate()
        paths["updates"].mkdir(parents=True, exist_ok=True)
        temporary = cert_path.with_suffix(".crt.tmp")
        temporary.write_text(ssl.DER_cert_to_PEM_cert(der), encoding="ascii")
        os.replace(temporary, cert_path)
        return cert_path

    def _make_client(self) -> Client:
        if not self.configured:
            raise RuntimeError("Signed update metadata is not provisioned in this build")
        paths = self._paths()
        paths["metadata"].mkdir(parents=True, exist_ok=True)
        paths["targets"].mkdir(parents=True, exist_ok=True)
        root_path = paths["metadata"] / "root.json"
        if not root_path.exists():
            shutil.copy2(self._bundled_root_path(), root_path)

        certificate = self._ensure_tls_certificate()
        fetcher = _PinnedFetcher(certificate) if isinstance(certificate, Path) else None
        client = Client(
            app_name=_APP_NAME,
            app_install_dir=self._install_dir(),
            current_version=__version__,
            metadata_dir=paths["metadata"],
            metadata_base_url=settings.UPDATE_METADATA_BASE_URL,
            target_dir=paths["targets"],
            target_base_url=settings.UPDATE_TARGET_BASE_URL,
            extract_dir=paths["staging"],
        )
        if fetcher is not None:
            # tufup 0.10 hardcodes its own fetcher; swap in the pinned one
            client._fetcher = fetcher
        return client

    def check(self) -> dict[str, Any]:
        with self._lock:
            if self._status.phase == "idle":
                self._load_persisted_status()
            if self._status.phase == "ready":
                return asdict(self._status)
            self._status = UpdateStatus(phase="checking", current_version=__version__)
        if not self.is_portable:
            with self._lock:
                self._status.phase = "unsupported"
                self._status.error = "热更新仅支持 Windows 便携版"
                return asdict(self._status)
        if not self.configured:
            with self._lock:
                self._status.phase = "unconfigured"
                self._status.error = "尚未配置签名更新信任根"
                return asdict(self._status)
        try:
            client = self._make_client()
            target = client.check_for_updates(patch=True)
            with self._lock:
                self._client = client
                if target is None:
                    self._status = UpdateStatus(
                        phase="current",
                        current_version=__version__,
                    )
                else:
                    target_files = list((client.new_targets or {}).values())
                    self._status = UpdateStatus(
                        phase="available",
                        current_version=__version__,
                        latest_version=str(target.version or ""),
                        available=True,
                        is_patch=any(target.is_patch for target in client.new_targets),
                        size=sum(int(item.length) for item in target_files),
                    )
                return asdict(self._status)
        except Exception as error:
            logger.warning("Portable update check failed: %s", error, exc_info=True)
            with self._lock:
                self._client = None
                self._status = UpdateStatus(
                    phase="failed",
                    current_version=__version__,
                    error="暂时无法检查更新",
                )
                return asdict(self._status)

    def start_download(self) -> dict[str, Any]:
        with self._lock:
            if self._status.phase == "downloading":
                return asdict(self._status)
            if not self._status.available or self._client is None:
                raise RuntimeError("No verified update is available")
            self._status.phase = "downloading"
            self._status.downloaded = 0
            client = self._client
            self._downloader = threading.Thread(
                target=self._download_update,
                args=(client,),
                name="portable-update-download",
                daemon=True,
            )
            self._downloader.start()
            return asdict(self._status)

    def _download_update(self, client: Client) -> None:
        paths = self._paths()
        staging = paths["staging"]
        try:
            if staging.is_symlink():
                staging.unlink()
            elif staging.exists():
                shutil.rmtree(staging)
            total_size = max(self._status.size, 1)
            if shutil.disk_usage(self._install_dir()).free < total_size * 3:
                raise OSError("磁盘空间不足，至少需要更新包大小的三倍可用空间")

            def on_progress(bytes_downloaded: int, bytes_expected: int) -> None:
                # tufup calls the hook with cumulative bytes as keyword args
                with self._lock:
                    self._status.downloaded = min(bytes_downloaded, self._status.size)

            client.download_and_apply_update(
                skip_confirmation=True,
                install=self._validate_and_stage,
                progress_hook=on_progress,
            )
            if not self._valid_staging(staging):
                raise RuntimeError("Downloaded update failed the portable package checks")
            with self._lock:
                self._staging_path = staging
                self._status.phase = "ready"
                self._status.downloaded = self._status.size
                self._persist_state("ready")
        except Exception as error:
            logger.warning("Portable update download failed: %s", error, exc_info=True)
            with self._lock:
                self._status.phase = "failed"
                self._status.error = "更新下载或校验失败，请稍后重试"
                self._staging_path = None
                try:
                    self._persist_state("failed")
                except OSError:
                    logger.warning("Could not persist portable update failure state")

    def _validate_and_stage(self, src_dir: Path, dst_dir: Path, **_kwargs: Any) -> None:
        # tufup calls install(src_dir=..., dst_dir=...) with keyword arguments
        source = Path(src_dir).resolve()
        expected = self._paths()["staging"].resolve()
        if source != expected or not self._valid_staging(source):
            raise ValueError("The signed update does not contain a valid portable package")

    @staticmethod
    def _valid_staging(staging: Path) -> bool:
        if staging.is_symlink() or not staging.is_dir():
            return False
        required = (
            staging / "QuizForge.exe",
            staging / "_internal",
            staging / "portable.mode",
        )
        if not (
            required[0].is_file()
            and required[1].is_dir()
            and required[2].is_file()
        ):
            return False
        return not (staging / "data").exists() and not (staging / "updates").exists()

    def _sqlite_database_path(self) -> Path:
        database_url = get_db_url()
        if not database_url:
            raise RuntimeError("未配置本地数据库，不能安全备份数据")
        url = make_url(database_url)
        if not url.drivername.startswith("sqlite") or not url.database:
            raise RuntimeError("热更新仅支持 SQLite 便携版数据库")
        database_path = Path(url.database)
        if not database_path.is_absolute():
            database_path = settings.DATA_DIR / database_path
        return database_path.resolve()

    def _backup_database(self, destination: Path) -> Path:
        source = self._sqlite_database_path()
        if not source.is_file():
            raise FileNotFoundError(f"SQLite database not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source, timeout=30) as source_db:
            with sqlite3.connect(destination, timeout=30) as destination_db:
                source_db.backup(destination_db)
        return source

    @staticmethod
    def _ps_quote(value: str | Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _build_installer_script(
        self,
        *,
        backup_dir: Path,
        database_path: Path,
        database_backup: Path,
        latest_version: str,
        current_version: str,
        process_id: int,
        port: int,
    ) -> tuple[Path, Path]:
        """Copy the standalone installer template to %TEMP% plus a JSON params file."""
        template = self._installer_template_path()
        if not template.is_file():
            raise RuntimeError(f"Installer template missing: {template}")
        paths = self._paths()
        # The installer also waits for every QuizForge.exe under InstallDir,
        # so worker/child processes are covered without listing them here.
        wait_pids = [process_id]
        params = {
            "InstallDir": str(self._install_dir()),
            "StagingDir": str(paths["staging"]),
            "BackupDir": str(backup_dir),
            "WaitPids": wait_pids,
            "OldVersion": current_version,
            "NewVersion": latest_version,
            "HealthUrl": f"http://127.0.0.1:{port}/api/v1/system/update/health",
            "WaitTimeoutSec": 60,
            "HealthTimeoutSec": 90,
            "LogPath": str(paths["updates"] / "update.log"),
            "StatePath": str(paths["state"]),
            "ExeName": "QuizForge.exe",
            "Names": ["QuizForge.exe", "_internal", "portable.mode", "README.txt"],
            "DatabasePath": str(database_path),
            "DatabaseBackup": str(database_backup),
            "LaunchArgs": ["--post-update", current_version],
        }
        temp_dir = Path(tempfile.gettempdir())
        script_path = temp_dir / f"quizforge-update-{process_id}.ps1"
        params_path = temp_dir / f"quizforge-update-{process_id}.json"
        # utf-8-sig so Windows PowerShell 5.1 reads non-ASCII paths correctly.
        script_path.write_text(template.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
        params_path.write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8-sig")
        return script_path, params_path

    def install(self) -> dict[str, Any]:
        if not self.is_portable or not self._valid_staging(self._paths()["staging"]):
            raise RuntimeError("No verified portable update is ready to install")
        if self._shutdown_callback is None:
            raise RuntimeError("Portable update shutdown handler is unavailable")
        install_dir = self._install_dir()
        probe = install_dir / f".quizforge-update-{os.getpid()}.tmp"
        try:
            probe.write_text("update write test", encoding="ascii")
            probe.unlink()
        except OSError as error:
            raise PermissionError("应用目录不可写，请手动下载便携版更新") from error

        paths = self._paths()
        backup_dir = paths["backup"] / (
            f"{__version__}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        database_backup = backup_dir / "db" / "database.sqlite"
        database_path = self._backup_database(database_backup)
        script_path, params_path = self._build_installer_script(
            backup_dir=backup_dir,
            database_path=database_path,
            database_backup=database_backup,
            latest_version=self._status.latest_version,
            current_version=__version__,
            process_id=os.getpid(),
            port=int(os.getenv("PORT", "8000")),
        )
        # Launch the installer via WMI so it is NOT a child of this process and
        # not in our Windows job object; otherwise it dies when the tray exits.
        inner = (
            "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
            f'-WindowStyle Hidden -File "{script_path}" -ParamsFile "{params_path}"'
        )
        launcher = (
            "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            f"-Arguments @{{CommandLine = {self._ps_quote(inner)}}}; "
            "if ($r.ReturnValue -ne 0) { exit [int]$r.ReturnValue }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", launcher],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Failed to launch update installer: %s", result.stderr)
            raise RuntimeError("无法启动更新安装程序")
        threading.Timer(1.5, self._shutdown_callback).start()
        with self._lock:
            self._status.phase = "installing"
            return asdict(self._status)


update_service = PortableUpdateService()
