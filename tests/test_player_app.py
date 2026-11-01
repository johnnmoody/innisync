"""Switching a Y1 from InniClassic to InniClassic Autoplay: backed up first, installed beside the original, made the
player, Autoplay turned on; and nothing installed when the download doesn't check out."""
import pytest

from innisync import backup, device, update

REL = {"pkg": device.AUTOPLAY, "app": "InniClassic Autoplay", "version": "1.4.5-autoplay1", "name": "a.apk",
       "url": "u", "size": 1, "sha256": "x", "published": None, "page": None}


@pytest.fixture
def steps(monkeypatch):
    log = []
    monkeypatch.setattr(device, "LAUNCHER", device.ORIGINAL)
    monkeypatch.setattr(update, "latest_release", lambda pkg, force=False: {**REL, "pkg": pkg})
    monkeypatch.setattr(update, "download", lambda rel, progress: log.append("download") or "/tmp/a.apk")
    monkeypatch.setattr(update, "preflight", lambda apk, rel: log.append("verify") or {"same_signer": None})
    monkeypatch.setattr(backup, "create", lambda info, reason: log.append(f"backup: {reason}") or {"name": "b"})
    monkeypatch.setattr(backup, "prune", lambda serial: None)
    monkeypatch.setattr(device, "install_apk", lambda apk: log.append("install"))
    monkeypatch.setattr(device, "switch_player", lambda pkg: log.append(f"switch to {pkg}"))
    monkeypatch.setattr(device, "set_player_prefs", lambda changes: log.append(f"prefs {changes}"))
    monkeypatch.setattr(device, "restart_player", lambda: log.append("restart"))
    return log


def test_switch_backs_up_installs_then_switches(steps):
    job = update.UpdateJob({"serial": "S", "launcher": "1.4.5"}, switch=True)
    job._run()
    assert job.status["state"] == "done", job.status
    assert steps == ["download", "verify", "backup: before InniClassic Autoplay 1.4.5-autoplay1", "install",
                     f"switch to {device.AUTOPLAY}", "prefs {'autoplay': True}"]


def test_a_bad_download_changes_nothing(steps, monkeypatch):
    def bad(rel, progress):
        raise device.DeviceError("a.apk didn't match GitHub's checksum, so it was thrown away")
    monkeypatch.setattr(update, "download", bad)
    job = update.UpdateJob({"serial": "S", "launcher": "1.4.5"}, switch=True)
    job._run()
    assert job.status["state"] == "error" and "checksum" in job.status["message"] and steps == []


def test_dry_run_says_what_it_would_do(steps):
    job = update.UpdateJob({"serial": "S", "launcher": "1.4.5"}, switch=True, dry_run=True)
    job._run()
    assert "make it the Y1's player" in job.status["message"] and steps == ["download", "verify"]
