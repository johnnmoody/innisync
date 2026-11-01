"""Podcasts, synced the way iTunes 9 did it, into InniClassic's own Podcasts menu.

InniClassic (MainActivity.java, read from FabianZettl/inniclassic master) keeps:
- subscriptions in /storage/sdcard0/Podcasts/subscriptions.txt, one "Channel Name|RSS_URL" per line, "#" comments;
- a downloaded episode at Podcasts/<channel>/<episode title>.mp3, both names with \\ / : * ? " < > | turned into "_",
  and ".mp3" whatever the real format (it saves enclosures that way itself);
- the show's art as Podcasts/<channel>/cover.jpg.
An episode at that exact path counts as downloaded (it plays the file and remembers its position), and offline it
lists the .mp3 files in the channel folder dated by modification time - so InniSync stamps each file with its
publish date. Episodes InniSync copied are tracked in the sync manifest; ones downloaded on the Y1 are never touched.
"""
import email.utils
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

from . import device

ROOT = f"{device.SD}/Podcasts"
SUBS = f"{ROOT}/subscriptions.txt"
RULES = ["all", "1 most recent", "3 most recent", "5 most recent", "10 most recent"]
HEADER = "# Y1 Podcast Subscriptions\n# Format: Channel Name|RSS_URL\n\n"
UA = "InniSync"
_feeds = {}   # rss url -> (fetched at, feed)
FEED_TTL = 900


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def episode_path(channel, title):
    return f"{ROOT}/{safe(channel)}/{safe(title)}.mp3"


def subscriptions():
    """[{name, url}] from the Y1, in file order."""
    out = []
    text = device.shell(f"cat {device.q(SUBS)} 2>/dev/null")
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("|")
        name, url = (parts[0].strip(), parts[1].strip()) if len(parts) >= 2 else ("Unknown Channel", parts[0].strip())
        out.append({"name": name, "url": url})
    return out


def _write_subscriptions(subs):
    import tempfile
    body = HEADER + "".join(f"{s['name'].replace('|', '/')}|{s['url']}\n" for s in subs)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(body)
        tmp = f.name
    try:
        device.shell(f"mkdir -p {device.q(ROOT)}")
        device.push(tmp, SUBS)
    finally:
        os.unlink(tmp)


def subscribe(url):
    """Add a feed (named from its own <title>, as the Y1's channel name). Returns the subscription."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise device.DeviceError("Paste the podcast's RSS feed address (http or https)")
    subs = subscriptions()
    if any(s["url"] == url for s in subs):
        raise device.DeviceError("Your Y1 is already subscribed to that podcast")
    feed = fetch(url, force=True)
    name = feed["title"].strip() or "Podcast"
    if any(s["name"] == name for s in subs):
        name = f"{name} ({len(subs) + 1})"   # the channel name is also the folder name, so it must be unique
    subs.append({"name": name, "url": url})
    _write_subscriptions(subs)
    return {"name": name, "url": url}


def unsubscribe(url, remove_episodes):
    subs = subscriptions()
    sub = next((s for s in subs if s["url"] == url), None)
    if not sub:
        raise device.DeviceError("That podcast isn't on the Y1")
    _write_subscriptions([s for s in subs if s["url"] != url])
    if remove_episodes:
        device.shell(f"rm -rf {device.q(ROOT + '/' + safe(sub['name']))}")
    return sub


def fetch(url, force=False):
    """{title, image, episodes: [{title, url, guid, date (unix), size}]} newest first. Cached for 15 minutes."""
    hit = _feeds.get(url)
    if hit and not force and time.time() - hit[0] < FEED_TTL:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    ch = root.find("channel")
    if ch is None:
        raise device.DeviceError("That address isn't an RSS podcast feed")
    itunes = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    img = ch.find(f"{itunes}image")
    image = img.get("href") if img is not None else (ch.findtext("image/url") or "")
    eps = []
    for it in ch.findall("item"):
        encs = it.findall("enclosure")
        if not encs or not encs[-1].get("url"):
            continue   # InniClassic skips items without audio too
        titles = it.findall("title")
        when = it.findtext("pubDate") or ""
        try:
            date = email.utils.parsedate_to_datetime(when).timestamp()
        except (TypeError, ValueError):
            date = 0
        eps.append({"title": (titles[-1].text or "") if titles else "", "url": encs[-1].get("url"),
                    "guid": it.findtext("guid") or encs[-1].get("url"), "date": date,
                    "size": int(encs[-1].get("length") or 0) if (encs[-1].get("length") or "").isdigit() else 0})
    eps.sort(key=lambda e: e["date"], reverse=True)
    feed = {"title": ch.findtext("title") or "", "image": image, "episodes": eps}
    _feeds[url] = (time.time(), feed)
    return feed


def wanted(settings, subs, feeds):
    """{device path: (subscription, episode)} the podcast settings put on the Y1."""
    p = settings.get("podcasts") or {}
    if not p.get("sync"):
        return {}
    out = {}
    n = None if p.get("rule") == "all" else int((p.get("rule") or "3").split()[0])
    for s in subs:
        feed = feeds.get(s["url"])
        if not feed:
            continue
        picks = []
        if p.get("auto", True) and (p.get("which") == "all" or s["url"] in p.get("selected", [])):
            picks = feed["episodes"] if n is None else feed["episodes"][:n]
        extra = set(p.get("extra", []))
        picks = picks + [e for e in feed["episodes"] if e["url"] in extra and e not in picks]
        for e in picks:
            out.setdefault(episode_path(s["name"], e["title"]), (s, e))
    return out


def downloaded():
    """Paths of every episode file on the Y1 (InniSync's or the Y1's own)."""
    out = device.shell(f"ls -R {device.q(ROOT)} 2>/dev/null", timeout=60)
    files, cur = set(), ROOT
    for line in out.splitlines():
        line = line.rstrip()
        if line.endswith(":") and line.startswith("/"):
            cur = line[:-1]
        elif line.lower().endswith(".mp3"):
            files.add(f"{cur}/{line}")
    return files


def download(ep, dest):
    req = urllib.request.Request(ep["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if ep["date"]:
        os.utime(dest, (ep["date"], ep["date"]))   # adb push keeps it: the Y1's offline list dates by mtime
