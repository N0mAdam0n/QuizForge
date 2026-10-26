"""Initialize the signed-update repository or publish a portable build."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app._version import __version__

APP_NAME = "QuizForge-Portable"
DEFAULT_REPO_DIR = Path(r"D:\qb-update-repo")
DEFAULT_KEYS_DIR = Path(r"D:\qb-keys")
DEFAULT_BUNDLE_DIR = BACKEND_DIR / "build" / "package-to-output" / APP_NAME
TRUSTED_ROOT = BACKEND_DIR / "deploy" / "windows" / "update" / "root.json"
ENCRYPTED_ROLES = ["root", "targets", "snapshot", "timestamp"]
METADATA_EXPIRATION_DAYS = {
    "root": 365,
    "targets": 90,
    "snapshot": 90,
    "timestamp": 30,
}


ROLE_LABELS = {
    "root": "root（根密钥）",
    "targets": "targets（目标文件）",
    "snapshot": "snapshot（快照）",
    "timestamp": "timestamp（时间戳）",
}
MAX_PASSWORD_ATTEMPTS = 5


def read_masked(prompt: str, getch=None, out=None) -> str:
    """Read a password showing one '*' per character; Backspace erases one.

    The password is never echoed or logged. Falls back to getpass when no
    Windows console is available.
    """
    out = out or sys.stdout
    if getch is None:
        try:
            import msvcrt
        except ImportError:
            import getpass

            return getpass.getpass(prompt)
        if not sys.stdin.isatty():
            import getpass

            return getpass.getpass(prompt)
        getch = msvcrt.getwch
    out.write(prompt)
    out.flush()
    chars: list[str] = []
    while True:
        ch = getch()
        if ch in ("\r", "\n"):
            out.write("\n")
            out.flush()
            return "".join(chars)
        if ch == "\x03":
            out.write("\n")
            raise KeyboardInterrupt
        if ch in ("\x08", "\x7f"):
            if chars:
                chars.pop()
                out.write("\b \b")
                out.flush()
            continue
        if ch in ("\x00", "\xe0"):
            getch()  # swallow the second half of arrow/function keys
            continue
        chars.append(ch)
        out.write("*")
        out.flush()


def load_private_key_interactive(role_name: str, key_path, read=read_masked, out=None):
    """Decrypt one signing key, asking for its password until it is correct."""
    from securesystemslib.exceptions import CryptoError
    from securesystemslib.interface import import_ed25519_privatekey_from_file

    out = out or sys.stdout
    try:
        return import_ed25519_privatekey_from_file(filepath=str(key_path), prompt=False)
    except CryptoError:
        pass  # encrypted: ask for the password below
    label = ROLE_LABELS.get(role_name, role_name)
    out.write(f"\n>>> 需要 {label} 角色的签名密钥密码（文件 {Path(key_path).name}）\n")
    for attempt in range(1, MAX_PASSWORD_ATTEMPTS + 1):
        password = read(f"请输入 {label} 密钥密码: ")
        try:
            key = import_ed25519_privatekey_from_file(filepath=str(key_path), password=password)
        except CryptoError:
            key = None
        finally:
            password = None
        if key is not None:
            out.write(f"    ✓ {label} 密钥已解锁\n")
            return key
        remaining = MAX_PASSWORD_ATTEMPTS - attempt
        if remaining:
            out.write(f"    密码错误，请重试（还可尝试 {remaining} 次）\n")
    raise PermissionError(f"{label} 密钥密码连续错误 {MAX_PASSWORD_ATTEMPTS} 次，已停止")


def install_interactive_signing(repository) -> None:
    """Make tufup ask for each key password with a masked, retrying prompt."""
    from securesystemslib.signer import SSlibSigner

    cache: dict[str, object] = {}

    def sign_role(role_name, private_key_path):
        cache_key = str(Path(private_key_path).resolve())
        if cache_key not in cache:
            cache[cache_key] = load_private_key_interactive(role_name, private_key_path)
        getattr(repository.roles, role_name).sign(SSlibSigner(cache[cache_key]), append=True)

    repository.roles.sign_role = sign_role


def _ensure_private_key_dir_is_safe(keys_dir: Path) -> None:
    resolved = keys_dir.resolve()
    if resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents:
        raise ValueError("Signing keys must be stored outside the source repository")


def _copy_trusted_root(metadata_dir: Path) -> None:
    root_path = metadata_dir / "root.json"
    if not root_path.is_file():
        raise FileNotFoundError(f"Signed TUF root metadata is missing: {root_path}")
    TRUSTED_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root_path, TRUSTED_ROOT)
    print(f"Public trust root copied to {TRUSTED_ROOT}")


def initialize_repository(repo_dir: Path, keys_dir: Path) -> None:
    from tufup.repo import Repository

    repo_dir = repo_dir.resolve()
    keys_dir = keys_dir.resolve()
    _ensure_private_key_dir_is_safe(keys_dir)
    if keys_dir.exists() and any(keys_dir.iterdir()):
        raise FileExistsError(
            f"Signing key directory is not empty; refusing to overwrite keys: {keys_dir}"
        )
    repo_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)
    repository = Repository(
        app_name=APP_NAME,
        repo_dir=repo_dir,
        keys_dir=keys_dir,
        encrypted_keys=ENCRYPTED_ROLES,
        expiration_days=METADATA_EXPIRATION_DAYS,
    )
    previous_cwd = Path.cwd()
    try:
        os.chdir(repo_dir)
        repository.initialize()
        repository.save_config()
    finally:
        os.chdir(previous_cwd)
    _copy_trusted_root(repository.metadata_dir)
    print("TUF signing keys are encrypted and remain outside the source repository.")
    print("Rebuild clients after the public root.json has been added to the project.")


def publish_bundle(repo_dir: Path, keys_dir: Path, bundle_dir: Path) -> None:
    from tufup.repo import Repository

    repo_dir = repo_dir.resolve()
    keys_dir = keys_dir.resolve()
    bundle_dir = bundle_dir.resolve()
    _ensure_private_key_dir_is_safe(keys_dir)
    if not (bundle_dir / "QuizForge.exe").is_file():
        raise FileNotFoundError(f"Portable executable is missing: {bundle_dir}")
    if (bundle_dir / "data").exists() or (bundle_dir / "updates").exists():
        raise ValueError("Update bundles must not contain data or updates directories")
    config_path = repo_dir / Repository.config_filename
    if not config_path.is_file():
        raise FileNotFoundError(
            f"TUF repository is not initialized; run the init command first: {config_path}"
        )

    previous_cwd = Path.cwd()
    try:
        os.chdir(repo_dir)
        repository = Repository.from_config()
        repository.add_bundle(
            new_bundle_dir=bundle_dir,
            new_version=__version__,
            skip_patch=False,
        )
        install_interactive_signing(repository)
        repository.publish_changes(private_key_dirs=[keys_dir])
    finally:
        os.chdir(previous_cwd)
    _copy_trusted_root(repository.metadata_dir)
    print(f"Signed portable update v{__version__}.")
    print(f"Upload {repository.targets_dir} before {repository.metadata_dir}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    init_parser = subparsers.add_parser("init", help="create encrypted signing keys and TUF root")
    init_parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    init_parser.add_argument("--keys-dir", type=Path, default=DEFAULT_KEYS_DIR)
    publish_parser = subparsers.add_parser("publish", help="sign a portable build for updates")
    publish_parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    publish_parser.add_argument("--keys-dir", type=Path, default=DEFAULT_KEYS_DIR)
    publish_parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    args = parser.parse_args()

    if args.action == "init":
        initialize_repository(args.repo_dir, args.keys_dir)
    else:
        publish_bundle(args.repo_dir, args.keys_dir, args.bundle_dir)


if __name__ == "__main__":
    main()
