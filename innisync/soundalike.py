"""How each song on the Y1 sounds (analysed on this computer) -> similar songs and mixes.

The Y1 is far too slow to judge similarity, so the thinking happens here and the results go to the Y1 as playlists.
Only songs on the Y1 are matched, since the next song has to be on the device.
"""
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import sync

FEATURES = os.path.join(sync.APP_DIR, "soundalike_features.json")
SR = 22050
CLIP = 45  # seconds analyzed per song, from about a third of the way in (skips intros)
VERSION = 1


def _decode(jf, song):
    """45 s of the song as mono float32, streamed straight from the music server (ffmpeg seeks with HTTP ranges)."""
    start = max(0, min(song.get("duration", 0) * 0.33, song.get("duration", 0) - CLIP))
    url, headers = jf.audio_source(song["id"])
    p = subprocess.run([sync.FFMPEG, "-v", "error", *(["-headers", headers] if headers else []),
                        "-ss", f"{start:.1f}", "-t", str(CLIP), "-i", url, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True, timeout=180)
    if p.returncode != 0 or len(p.stdout) < SR * 4 * 5:
        raise RuntimeError((p.stderr or b"no audio").decode(errors="replace")[:200])
    return np.frombuffer(p.stdout, dtype=np.float32)


def analyze(jf, song):
    """Feature vector: timbre (MFCC mean/std), brightness, texture, energy and its swing, rhythm, harmony."""
    import librosa
    y = _decode(jf, song)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    mel = librosa.feature.melspectrogram(S=S ** 2, sr=SR)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(mel), n_mfcc=13)
    onset = librosa.onset.onset_strength(y=y, sr=SR)
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=onset, sr=SR))[0])
    rms = librosa.feature.rms(S=S)[0]
    feats = {
        "mfcc_mean": mfcc.mean(axis=1).tolist(),
        "mfcc_std": mfcc.std(axis=1).tolist(),
        "centroid": float(librosa.feature.spectral_centroid(S=S, sr=SR).mean()),
        "rolloff": float(librosa.feature.spectral_rolloff(S=S, sr=SR).mean()),
        "contrast": librosa.feature.spectral_contrast(S=S, sr=SR).mean(axis=1).tolist(),
        "zcr": float(librosa.feature.zero_crossing_rate(y).mean()),
        "rms": float(rms.mean()),
        "rms_swing": float(rms.std() / (rms.mean() + 1e-9)),
        "onset": float(onset.mean()),
        "tempo": tempo,
        "chroma": librosa.feature.chroma_stft(S=S, sr=SR).mean(axis=1).tolist(),
    }
    return feats


FAMILIES = [  # messy library tags ("Electronic, Hip Hop, Pop", "Alternatif et Indé") -> a few clean families
    ("Hip-Hop", ("hip hop", "hip-hop", "rap", "trap")),
    ("R&B", ("r&b", "rnb", "soul", "funk")),
    ("Rock", ("rock", "punk", "metal", "emo", "grunge", "alternati", "indie", "indé")),
    ("Dance", ("dance", "electro", "house", "edm", "techno", "synth", "disco", "club")),
    ("Jazz & Blues", ("jazz", "blues")),
    ("Country", ("country", "folk", "americana")),
    ("Latin", ("latin", "reggaeton", "salsa")),
    ("Pop", ("pop",)),
]


def families(genres):
    out = []
    for g in genres or []:
        for part in g.replace("/", ",").replace(";", ",").split(","):
            p = part.strip().lower()
            for fam, keys in FAMILIES:
                if p and any(k in p for k in keys) and fam not in out:
                    out.append(fam)
                    break
    return out


def _vector(f):
    """Flatten with weights: sound texture and energy count most, harmony least."""
    t = f["tempo"]
    t = t / 2 if t > 150 else t * 2 if t < 70 else t  # half/double-time is the same feel
    parts = [
        (np.array(f["mfcc_mean"][1:]), 1.0),
        (np.array(f["mfcc_std"][1:]), 0.6),
        (np.array(f["contrast"]), 0.8),
        (np.log([f["centroid"] + 1, f["rolloff"] + 1]), 1.0),
        (np.array([f["zcr"], np.log(f["rms"] + 1e-6), f["rms_swing"], f["onset"]]), 1.2),
        (np.array([t]), 1.4),
        (np.array(f["chroma"]), 0.3),
    ]
    return parts


class Index:
    """Similarity over a set of analyzed songs (z-scored features, cosine) plus a little metadata."""

    def __init__(self, feats, lib):
        self.ids = [i for i in feats if i in lib]
        self.lib = lib
        if not self.ids:
            self.X = np.zeros((0, 1))
            return
        blocks = list(zip(*[_vector(feats[i]) for i in self.ids]))
        cols = []
        for blk in blocks:
            arr = np.vstack([b[0] for b in blk]).astype(float)
            w = blk[0][1]
            arr = (arr - arr.mean(axis=0)) / (arr.std(axis=0) + 1e-9)
            cols.append(arr * w / np.sqrt(arr.shape[1]))  # each group weighs the same whatever its size
        X = np.hstack(cols)
        self.X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
        self.pos = {i: n for n, i in enumerate(self.ids)}
        # one "energy" number per song (loudness, attack, pace) for naming mixes Mellow / High-Energy
        z = lambda a: (a - a.mean()) / (a.std() + 1e-9)
        tempo = np.array([_vector(feats[i])[5][0][0] for i in self.ids])
        self.energy = (z(np.log([feats[i]["rms"] + 1e-6 for i in self.ids])) + z(np.array([feats[i]["onset"] for i in self.ids]))
                       + 0.5 * z(tempo)) / 2.5

    def _meta_bonus(self, seed, cand):
        a, b = self.lib[seed], self.lib[cand]
        bonus = 0.0
        ga, gb = set(a.get("genres") or []), set(b.get("genres") or [])
        if ga and gb:
            bonus += 0.12 * len(ga & gb) / len(ga | gb)
        if a.get("year") and b.get("year") and abs(a["year"] - b["year"]) <= 5:
            bonus += 0.04
        return bonus

    def similar(self, seed, n=25, per_artist=3):
        """The n songs that best follow `seed`, with no artist taking over the list (so one artist never fills the list)."""
        if seed not in self.pos:
            return []
        sims = self.X @ self.X[self.pos[seed]]
        order = np.argsort(-sims)
        scored = sorted(((float(sims[k]) + self._meta_bonus(seed, self.ids[k]), self.ids[k]) for k in order[:400]
                         if self.ids[k] != seed), reverse=True)
        out, count = [], {}
        artist = lambda i: (self.lib[i].get("albumArtist") or self.lib[i].get("artist") or "").lower()
        for _, i in scored:
            a = artist(i)
            if count.get(a, 0) >= per_artist:
                continue
            count[a] = count.get(a, 0) + 1
            out.append(i)
            if len(out) >= n:
                break
        return out

    def mixes(self, k=None, size=100):
        """Mixes: groups of songs that sound alike, each named for its main genre, ordered to flow."""
        from scipy.cluster.vq import kmeans2
        n = len(self.ids)
        if n < 40:
            return []
        k = k or max(3, min(12, n // 45))
        _, labels = kmeans2(self.X, k, minit="++", seed=7, iter=30)
        mixes = []
        for c in range(k):
            rows = [j for j in range(n) if labels[j] == c]
            members = [self.ids[j] for j in rows]
            if len(members) < 15:
                continue
            fams = {}
            for i in members:
                for f in families(self.lib[i].get("genres")):
                    fams[f] = fams.get(f, 0) + 1
            artists = {}
            for i in members:
                a = self.lib[i].get("albumArtist") or self.lib[i].get("artist")
                if a:
                    artists[a] = artists.get(a, 0) + 1
            mixes.append({"genres": sorted(fams, key=lambda f: -fams[f])[:2], "energy": float(self.energy[rows].mean()),
                          "artists": sorted(artists, key=lambda a: -artists[a])[:4], "songs": self._flow(members)[:size]})
        # named for the main genre family, with the feel when it stands out
        for m in mixes:
            fam = m["genres"][0] if m["genres"] else "Mix"
            feel = "Mellow " if m["energy"] < -0.3 else "High-Energy " if m["energy"] > 0.3 else ""
            m["name"] = f"{feel}{fam} Mix"
        taken = {}
        for m in mixes:
            taken.setdefault(m["name"], []).append(m)
        for name, group in taken.items():
            if len(group) > 1:  # same name twice: tell them apart by their biggest artist
                for m in group:
                    m["name"] = f"{name}: {m['artists'][0]}" if m["artists"] else name
        for m in mixes:
            m["id"] = "mix:" + m["name"]
        return sorted(mixes, key=lambda m: m["name"])

    def _flow(self, members):
        """Order a mix so each song leads into a similar one, spacing out repeats of an artist."""
        rows = np.array([self.pos[i] for i in members])
        Xm = self.X[rows]
        centre = Xm.mean(axis=0)
        cur = int(np.argmax(Xm @ centre))
        left = set(range(len(members))) - {cur}
        order, recent = [cur], []
        artist = lambda j: (self.lib[members[j]].get("albumArtist") or self.lib[members[j]].get("artist") or "").lower()
        while left:
            cand = sorted(left, key=lambda j: -float(Xm[j] @ Xm[cur]))
            nxt = next((j for j in cand[:20] if artist(j) not in recent[-3:]), cand[0])
            order.append(nxt)
            recent.append(artist(nxt))
            left.discard(nxt)
            cur = nxt
        return [members[j] for j in order]


class Analyzer:
    """Background analysis of the Y1's songs; results cached on disk so each song is analyzed once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.feats = self._load()
        self.status = {"state": "idle", "done": 0, "total": 0, "failed": 0}
        self.thread = None
        self.version = 0  # bumps when features change, so cached results are rebuilt

    def _load(self):
        try:
            data = json.load(open(FEATURES))
            return data["songs"] if data.get("version") == VERSION else {}
        except (OSError, ValueError, KeyError):
            return {}

    def _save(self):
        os.makedirs(sync.APP_DIR, exist_ok=True)
        tmp = FEATURES + ".tmp"
        json.dump({"version": VERSION, "songs": self.feats}, open(tmp, "w"))
        os.replace(tmp, FEATURES)

    def start(self, jf, lib, ids):
        """Analyze any of `ids` not done yet. Safe to call often; only one run at a time."""
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            todo = [i for i in ids if i in lib and i not in self.feats]
            if not todo:
                return
            self.status = {"state": "analyzing", "done": 0, "total": len(todo), "failed": 0}
            self.thread = threading.Thread(target=self._run, args=(jf, lib, todo), daemon=True)
            self.thread.start()

    def _run(self, jf, lib, todo):
        last = time.time()
        def one(i):
            try:
                return i, analyze(jf, lib[i])
            except Exception:
                return i, None
        with ThreadPoolExecutor(4) as pool:
            for i, f in pool.map(one, todo):
                if f is None:
                    self.status["failed"] += 1
                else:
                    self.feats[i] = f
                self.status["done"] += 1
                if time.time() - last > 20:
                    self._save()
                    self.version += 1
                    last = time.time()
        self._save()
        self.version += 1
        self.status["state"] = "idle"

    def index(self, lib, ids):
        return Index({i: self.feats[i] for i in ids if i in self.feats}, lib)


ANALYZER = Analyzer()
