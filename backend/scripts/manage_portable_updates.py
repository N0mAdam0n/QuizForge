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

APP_NAME = "QuestionBank-Portable"
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
    if not (bundle_dir / "question-bank.exe").is_file():
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
