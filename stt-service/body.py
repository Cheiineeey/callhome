"""Sounds without words: what the transcript throws away.

During a call she may make sounds and say nothing: a moan, a whimper, heavy
breathing. The transcriber returns "" or a lone "嗯", and the turn loop used to
drop that as "nothing said". The companion heard nothing.

Approach from aria-duet / ai-hears-your-body (off-the-shelf classifiers barely
recognise soft vocal sounds; three conditions together work better):
  · no real words in the transcript (interjections like 嗯/啊/呜 don't count)
  · pitched: enough voiced frames have an f0 in 150–700Hz (pyin voiced_flag),
    which separates a voice from breathing or a vibration
  · mouth shape: 500–1500Hz vs 100–500Hz energy. Closed "mm" is low, open "ah" is high.
Unpitched but long enough → breathing.

Only run this on live call audio (source=call). Every decision is appended to
body.log with its numbers. These thresholds are starting points, not calibrated —
tune them on the speaker's real recordings.

Labels returned: laughter, crying, cough, sneeze (forwarded from SenseVoice events),
moan, cry_out, whimper, breathing.

🔴 server.py imports this as `import body as bodysnd`. A plain `import body`
collides with the `body = self.rfile.read(...)` local in do_POST, and every
/transcribe fails with "'bytes' object has no attribute 'detect'".
"""
import re, json, time
from pathlib import Path

LOG = Path(__file__).parent / "body.log"
_INTERJ = "嗯哼唔呃呜啊哈呀哦嘤嗷唉呼额恩"
_STRIP = r"[\s，。、！？；：…,.!?;:~\-—\"'（）()]+"
FORWARD = ("laughter", "crying", "cough", "sneeze")


def interjections_only(text: str) -> str | None:
    """Only interjections → that string ("" = no text at all). Real words → None."""
    t = re.sub(_STRIP, "", text or "")
    if not t: return ""
    return t if all(c in _INTERJ for c in t) else None


def detect(path: str, text: str, events: list) -> tuple[list, dict]:
    sounds = [e for e in events if e in FORWARD]
    ij = interjections_only(text)
    if ij is None:          # she said something; the words carry it
        return sounds, {}
    import subprocess, tempfile, os
    import numpy as np, librosa
    dbg = {}
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav = tf.name
        subprocess.run(["ffmpeg", "-y", "-i", str(path), "-ar", "16000", "-ac", "1", wav],
                       capture_output=True, timeout=30)
        y, sr = librosa.load(wav, sr=16000, mono=True)
        os.unlink(wav)
        if len(y) < sr * 0.4: return sounds, {}
        hop = 256
        rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
        peak = float(np.max(rms))
        if peak < 0.004:                 # near silence
            return sounds, {"peak": round(peak, 4)}
        active = rms > max(peak * 0.15, 0.003)
        active_s = float(np.sum(active)) * hop / sr
        f0, vflag, _ = librosa.pyin(y, fmin=150, fmax=700, sr=sr, frame_length=1024, hop_length=hop)
        n = min(len(active), len(vflag))
        act = active[:n]
        pitched = float(np.sum(vflag[:n] & act)) / max(1, float(np.sum(act)))
        S = np.abs(librosa.stft(y, n_fft=1024, hop_length=hop))[:, :n][:, act] ** 2
        freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
        lo = float(S[(freqs >= 100) & (freqs < 500)].sum()) or 1e-9
        mid = float(S[(freqs >= 500) & (freqs < 1500)].sum())
        mouth = mid / lo
        dbg = {"active_s": round(active_s, 2), "pitched": round(pitched, 2),
               "mouth": round(mouth, 2), "peak": round(peak, 4), "ij": ij}
        kind = None
        # Scanned 200 short real clips: with no text, 0.3–0.5s of sound
        # (mic bumps, half a syllable) gave 18 false moans out of 109.
        # Requiring ≥0.8s and ≥50% pitched took that to zero. With interjections the
        # bar is 30% pitched, still 0.8s — a plain "嗯。" in reply is pitched too.
        if (pitched >= 0.30 and ij and active_s >= 0.8) or (pitched >= 0.5 and not ij and active_s >= 0.8):
            if any(c in "呜嘤" for c in ij) or "crying" in events: kind = "whimper"
            elif any(c in "啊哈呀嗷" for c in ij): kind = "cry_out"
            elif ij: kind = "moan"
            else: kind = "moan" if mouth < 0.45 else "cry_out"
        elif not ij and active_s >= 0.6 and "laughter" not in sounds and "cough" not in sounds:
            kind = "breathing"
        if kind and kind not in sounds:
            sounds.append(kind)
    except Exception as e:
        dbg["err"] = str(e)
    return sounds, dbg


def log(name, text, sounds, dbg):
    try:
        with LOG.open("a") as f:
            f.write(json.dumps({"t": time.strftime("%m-%d %H:%M:%S"), "f": name, "text": text,
                                "sounds": sounds, **dbg}, ensure_ascii=False) + "\n")
    except Exception:
        pass
