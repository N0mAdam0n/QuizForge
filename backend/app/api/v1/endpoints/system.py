import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app._version import __version__
from app.api import deps
from app.core.config import is_configured
from app.services.update_service import update_service

router = APIRouter()

# GitHub repository the desktop releases are published to. The frontend uses
# this to query the latest release and prompt the user to update.
GITHUB_REPO = "N0mAdam0n/QuizForge"


@router.get("/version")
async def get_version() -> dict:
    """Return the running application version and its release repository.

    Public (no auth): the frontend compares this against the latest GitHub
    release tag to decide whether to show an "update available" prompt.
    """
    return {
        "version": __version__,
        "repo": GITHUB_REPO,
        "releases_url": f"https://github.com/{GITHUB_REPO}/releases/latest",
        "portable": update_service.is_portable,
        "updater": "tufup" if update_service.configured else "none",
    }


def _lan_ip() -> str:
    """Best-effort primary LAN IPv4 address (no packets are actually sent)."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


@router.get("/network")
async def get_network_info(
    current_user=Depends(deps.get_current_active_user),
) -> dict:
    """Return LAN-sharing status and the address colleagues can use.

    Lets non-technical desktop users read the access URL directly in the UI
    instead of running ``ipconfig``. When sharing is off, no address is
    returned (the app is bound to 127.0.0.1 and only reachable locally).
    """
    import os

    from app.core.config import get_lan_share
    from app.services import mdns

    lan_share = get_lan_share()
    port = int(os.getenv("PORT", "8000"))
    ip = _lan_ip() if lan_share else None
    hostname = mdns.current_hostname() if lan_share else None
    return {
        "lan_share": lan_share,
        "port": port,
        "host_ip": ip,
        "lan_url": f"http://{ip}:{port}/" if ip else None,
        "lan_hostname": hostname,
        "lan_hostname_url": f"http://{hostname}:{port}/" if hostname else None,
    }


@router.get("/update/check")
async def check_portable_update() -> dict:
    """Check signed update metadata without transmitting a device identifier."""
    return await asyncio.to_thread(update_service.check)


@router.get("/update/status")
async def get_portable_update_status(
    _current_user=Depends(deps.get_current_active_superuser),
) -> dict:
    return update_service.snapshot()


@router.post("/update/download")
async def download_portable_update(
    _current_user=Depends(deps.get_current_active_superuser),
) -> dict:
    try:
        return update_service.start_download()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/update/install")
async def install_portable_update(
    _current_user=Depends(deps.get_current_active_superuser),
) -> dict:
    try:
        return await asyncio.to_thread(update_service.install)
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/update/health")
async def portable_update_health(request: Request) -> dict:
    """Health endpoint used by the external installer before finalizing updates."""
    return {
        "version": __version__,
        "configured": is_configured(),
        "migrations_ok": bool(
            is_configured()
            and getattr(request.app.state, "update_migrations_ok", False)
        ),
    }
