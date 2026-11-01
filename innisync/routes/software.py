"""The Y1's software: checking for and installing InniClassic updates, and handing off to Updater CE."""
from .. import update
from ..state import S
from . import USB_MOVES, get, post


@get("/api/update/check")
def check(r):
    return update.check(r.info.get("launcher") if r.info.get("connected") else None, force=r.qs.get("force") == "1")


@get("/api/update/status")
def status(r):
    return S.update.status if S.update else {"state": "idle"}


@post("/api/update/install", connected=True, usb=USB_MOVES, exclusive=True)
def install(r):
    S.update = update.UpdateJob(r.info, dry_run=bool(r.body.get("dryRun"))).start()
    return {"ok": True}


@get("/api/updaterce")
def updater_status(r):
    return update.updater_status()


@post("/api/updaterce/open", exclusive=True, usb="Connect the Y1 by USB first, so InniSync can back it up.")
def open_updater(r):
    return update.open_updater(r.info)
