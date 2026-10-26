"""Masked password prompt used when signing portable updates (dummy keys only)."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import manage_portable_updates as mpu  # noqa: E402


def _keys(*sequence: str):
    it = iter("".join(sequence))
    return lambda: next(it)


def test_read_masked_shows_stars_and_supports_backspace():
    out = io.StringIO()
    value = mpu.read_masked("pw: ", getch=_keys("abx", "\x08", "c\r"), out=out)
    assert value == "abc"
    assert out.getvalue() == "pw: ***\b \b*\n"
    assert "abc" not in out.getvalue()


def test_load_key_retries_on_wrong_password(tmp_path):
    from securesystemslib.interface import generate_and_write_ed25519_keypair

    key_path = tmp_path / "dummy_targets"
    generate_and_write_ed25519_keypair(password="right-pass", filepath=str(key_path))
    answers = iter(["wrong", "right-pass"])
    out = io.StringIO()
    key = mpu.load_private_key_interactive(
        "targets", key_path, read=lambda prompt: next(answers), out=out
    )
    assert key["keytype"] == "ed25519"
    text = out.getvalue()
    assert "targets" in text and "密码错误，请重试" in text and "已解锁" in text
    assert "right-pass" not in text and "wrong" not in text


def test_load_key_gives_up_after_max_attempts(tmp_path):
    from securesystemslib.interface import generate_and_write_ed25519_keypair

    key_path = tmp_path / "dummy_root"
    generate_and_write_ed25519_keypair(password="right-pass", filepath=str(key_path))
    with pytest.raises(PermissionError):
        mpu.load_private_key_interactive(
            "root", key_path, read=lambda prompt: "nope", out=io.StringIO()
        )
