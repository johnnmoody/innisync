"""Sync over Wi-Fi: the Y1's adbd on TCP, locked to this Mac.

This Y1's firmware runs adbd as root with key checks off (ro.adb.secure unset), so open adb on the network would be a
root shell for anyone on the LAN. So before TCP is switched on, an iptables chain on the Y1 drops port 5555 from
everything except this Mac: its IPs, and its MAC addresses as the Y1 sees them (read from the Y1's own ARP table; macOS
hides them from apps). IPv6 to the port is dropped outright.

Android 4.2.2's adbd (system/core/adb/adb.c) listens on USB and, when service.adb.tcp.port is set, on TCP as well;
`setprop ctl.restart adbd` has init restart it. Neither the property nor the firewall survives a reboot, so rebooting
the Y1 always puts it back to USB only. The allow-list is refreshed every time InniSync reaches the Y1, so it follows
this Mac between networks while it can still connect; if it can't, plug in the cable.

What it's good for, measured on a Y1 (2026-10-31): seeing the Y1 (status, battery) and sending play counts. Bulk data
doesn't work: adb push managed 0.06 MB/s, and even a raw TCP stream to busybox nc stalled at ~30 KB/s, screen on,
RSSI -46, link 65 Mbps, ping ~9 ms; 1472-byte pings lose half their packets, and MTU 1400 didn't fix the stall.
So file-moving jobs say "connect by USB". The Y1 also rejoins Wi-Fi with a new random MAC and DHCP address now and
then (4 addresses in 20 minutes), which is why reconnect() scans for it.
"""
import json
import os
import re
import subprocess
import threading
import time

from . import device, sync

PORT = 5555
CHAIN = "innisync_adb"
STATE = os.path.join(sync.APP_DIR, "wifi.json")   # serial -> {"ip": last Wi-Fi address}


def _load():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def _save(st):
    os.makedirs(sync.APP_DIR, exist_ok=True)
    json.dump(st, open(STATE, "w"), indent=1)


def mac_ips():
    """This Mac's IPv4 addresses (not loopback)."""
    out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=10).stdout
    return sorted({ip for ip in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out) if not ip.startswith("127.")})


def y1_wifi():
    """(ip, up) of the Y1's wlan0."""
    out = device.shell("netcfg 2>/dev/null | grep wlan0")
    m = re.search(r"wlan0\s+(UP|DOWN)\s+(\d+\.\d+\.\d+\.\d+)", out)
    if not m or m.group(2) == "0.0.0.0":
        return None, False
    return m.group(2), m.group(1) == "UP"


def _macs_seen_by_y1(ips):
    """MAC addresses the Y1 has for this Mac's IPs (it pings them first so they're in its ARP table)."""
    device.shell("; ".join(f"ping -c 1 -W 1 {ip} >/dev/null 2>&1" for ip in ips) + "; true", timeout=30)
    macs = set()
    for line in device.shell("cat /proc/net/arp").splitlines()[1:]:
        f = line.split()
        if len(f) >= 4 and f[0] in ips and f[3] != "00:00:00:00:00:00":
            macs.add(f[3].lower())
    return sorted(macs)


def lock(ips=None):
    """(Re)write the firewall on the Y1: port 5555 only from this Mac. Returns what it allowed."""
    ips = ips or mac_ips()
    macs = _macs_seen_by_y1(ips)
    rules = [f"iptables -N {CHAIN} 2>/dev/null", f"iptables -F {CHAIN}", f"iptables -A {CHAIN} -i lo -j ACCEPT"]
    rules += [f"iptables -A {CHAIN} -s {ip} -j ACCEPT" for ip in ips]
    rules += [f"iptables -A {CHAIN} -m mac --mac-source {m} -j ACCEPT" for m in macs]
    rules += [f"iptables -A {CHAIN} -j DROP",
              f"iptables -D INPUT -p tcp --dport {PORT} -j {CHAIN} 2>/dev/null",
              f"iptables -I INPUT 1 -p tcp --dport {PORT} -j {CHAIN}",
              f"ip6tables -D INPUT -p tcp --dport {PORT} -j DROP 2>/dev/null",
              f"ip6tables -I INPUT 1 -p tcp --dport {PORT} -j DROP"]
    for i in range(0, len(rules), 6):   # the Y1's adb refuses long lines
        device.shell("; ".join(rules[i:i + 6]))
    check = device.shell(f"iptables -S {CHAIN} 2>/dev/null || iptables -L {CHAIN} -n")
    if "DROP" not in check:
        raise device.DeviceError("The Y1's firewall rules didn't take, so Wi-Fi sync stays off")
    return {"ips": ips, "macs": macs}


def unlock():
    device.shell(f"iptables -D INPUT -p tcp --dport {PORT} -j {CHAIN} 2>/dev/null; iptables -F {CHAIN} 2>/dev/null; "
                 f"iptables -X {CHAIN} 2>/dev/null; ip6tables -D INPUT -p tcp --dport {PORT} -j DROP 2>/dev/null; true")


def listening():
    return device.shell("getprop service.adb.tcp.port").strip() == str(PORT)


def enable(serial):
    """Turn on Wi-Fi sync (over USB): Wi-Fi up, firewall, then adbd on TCP. Returns {"ip", "allowed"}."""
    if device.over_wifi():
        raise device.DeviceError("Connect the Y1 by USB to turn on Wi-Fi sync")
    ip, up = y1_wifi()
    if not up:
        device.shell("svc wifi enable")
        for _ in range(20):
            time.sleep(1)
            ip, up = y1_wifi()
            if up:
                break
        if not up:
            raise device.DeviceError("The Y1 didn't join a Wi-Fi network. Join one on the Y1, then try again.")
    allowed = lock()                       # firewall first: TCP never opens unguarded
    _restart_adbd(PORT)
    st = _load()
    st[serial] = {"ip": ip}
    _save(st)
    out = device.adb("connect", f"{ip}:{PORT}", timeout=15, check=False)
    if "connected" not in out:
        raise device.DeviceError(f"Wi-Fi sync is on, but this computer couldn't reach the Y1 at {ip}: {out.strip()}")
    return {"ip": ip, "allowed": allowed}


def disable(serial):
    """Turn Wi-Fi sync off: adbd back to USB only, firewall removed, forget the address."""
    ip = _load().get(serial, {}).get("ip")
    if ip:
        device.adb("disconnect", f"{ip}:{PORT}", timeout=10, check=False)
        device.connected()   # back to the USB transport for the restart
    _restart_adbd(0)         # port 0 = no TCP listener
    if _wait_usb():
        unlock()
    st = _load()
    st.pop(serial, None)
    _save(st)


def _restart_adbd(port):
    """Set adbd's TCP port and have init restart it. The shell carrying the command dies with the old adbd, and the
    Mac's adb server keeps a dead USB session afterwards (seen on this Y1: commands hang), so that one is allowed to
    time out and the adb server is restarted to pick the Y1 up fresh."""
    try:
        device.shell(f"setprop service.adb.tcp.port {port}; setprop ctl.restart adbd", timeout=6)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(2)
    device.adb("kill-server", timeout=15, check=False)
    device.adb("start-server", timeout=30, check=False)
    if not _wait_usb():
        raise device.DeviceError("The Y1 didn't come back on USB after restarting adb. Unplug it and plug it back in.")


def _wait_usb(secs=15):
    for _ in range(secs * 2):
        if device.connected():
            return True
        time.sleep(0.5)
    return False


def enabled(serial):
    return serial in _load()


def refresh(serial):
    """On every connection: keep the allow-list current and remember the Y1's address (DHCP can move it)."""
    if not enabled(serial) or not listening():
        return
    lock()
    ip, up = y1_wifi()
    if up:
        st = _load()
        st[serial] = {"ip": ip}
        _save(st)


_last_try = [0.0]
SCAN_EVERY = 30


def _open(ip, timeout=0.5):
    import socket
    try:
        with socket.create_connection((ip, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _candidates():
    """Every address on this Mac's /24 networks with port 5555 open (the Y1's firewall answers only this Mac)."""
    from concurrent.futures import ThreadPoolExecutor
    hosts = []
    for ip in mac_ips():
        net = ip.rsplit(".", 1)[0]
        hosts += [f"{net}.{n}" for n in range(1, 255) if f"{net}.{n}" != ip]
    with ThreadPoolExecutor(64) as pool:
        return [h for h, ok in zip(hosts, pool.map(_open, hosts)) if ok]


def _claim(ip, serial):
    """adb connect ip, and keep it only if it's this Y1."""
    out = device.adb("connect", f"{ip}:{PORT}", timeout=8, check=False)
    if "connected" not in out:
        return False
    p = subprocess.run([device.ADB, "-s", f"{ip}:{PORT}", "shell", "getprop ro.serialno"], capture_output=True,
                       text=True, timeout=15)
    if p.stdout.strip() == serial:
        return True
    device.adb("disconnect", f"{ip}:{PORT}", timeout=8, check=False)
    return False


def reconnect():
    """With no Y1 connected, look for Y1s that have Wi-Fi sync on (at most every 30 s, in the background).
    This Y1 rejoins Wi-Fi with a new random MAC and a new DHCP address now and then (seen 4 times in 20 min on 10-31),
    so the last address is tried first, then the local network is scanned and each hit checked by serial number."""
    st = _load()
    if not st or time.time() - _last_try[0] < SCAN_EVERY:
        return
    _last_try[0] = time.time()

    def run():
        try:
            # drop dead Wi-Fi sessions first: an "offline" entry blocks a fresh connect to the same address
            for line in device.adb("devices", timeout=10, check=False).splitlines()[1:]:
                if ":" in line and "offline" in line:
                    device.adb("disconnect", line.split()[0], timeout=8, check=False)
            for serial, s in st.items():
                if _open(s["ip"], 1.5) and _claim(s["ip"], serial):
                    continue
                for ip in _candidates():
                    if _claim(ip, serial):
                        st[serial] = {"ip": ip}
                        _save(st)
                        break
        except Exception:
            pass   # not reachable right now (Y1 asleep, away, or on another network)
    threading.Thread(target=run, daemon=True).start()
