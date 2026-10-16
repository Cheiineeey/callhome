#!/usr/bin/env python3
"""callhome stt-service — SenseVoice + librosa. Transcription, emotion tags, and tone cues in one local endpoint."""
import os, json, uuid, time, re, traceback
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import tone      # tone cues from a rolling personal baseline, not fixed constants

BASE = Path(__file__).parent.resolve()
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)

print("[voce] loading SenseVoice…", flush=True)
try:
    from funasr import AutoModel
    model = AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad",
                      vad_kwargs={"max_single_segment_time": 30000},
                      device="cpu", disable_update=True)
    LOADED = True
    print("[voce] model ready", flush=True)
except Exception as e:
    print(f"[voce] model load failed: {e}", flush=True)
    model, LOADED = None, False

EMO = {"<|HAPPY|>":"happy","<|SAD|>":"sad","<|ANGRY|>":"angry","<|NEUTRAL|>":"neutral",
       "<|SURPRISED|>":"surprised","<|FEARFUL|>":"fearful","<|DISGUSTED|>":"disgusted"}

def transcribe(p: Path):
    if not LOADED:
        return {"text":"", "emotion":"neutral", "error":"model not loaded"}
    try:
        res = model.generate(input=str(p), cache={}, language="zh", use_itn=True,
                             batch_size_s=60, merge_vad=True, merge_length_s=15)
        raw = res[0].get("text","") if res else ""
        emotion = next((v for k,v in EMO.items() if k in raw), "neutral")
        text = re.sub(r"<\|[^|]+\|>", "", raw).strip()
        return {"text": text, "emotion": emotion}
    except Exception as e:
        traceback.print_exc()
        return {"text":"", "emotion":"neutral", "error":str(e)}

def _features(p: Path, text: str = ""):
    """Acoustic features only. The wording is tone.py's job — it ranks each
    feature against a rolling baseline of this speaker instead of a constant.

    Measured on 85 real recordings from one speaker: `pitch_var > 60` held in
    96.5% of them (Mandarin tone, not emotion), the `pause` cutoff landed on her
    median, and two of the seven phrases needed a pitch she never reaches. See
    docs/TONE_CUES.md.

    If you change the yin frame_length/hop_length, existing baselines are no
    longer comparable — pitch and pitch_var shift, and every percentile with them.
    """
    import subprocess, tempfile, os, re as _re
    import numpy as np, librosa
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav = tf.name
        subprocess.run(["ffmpeg","-y","-i",str(p),"-ar","16000","-ac","1",wav],
                       capture_output=True, timeout=30)
        y, sr = librosa.load(wav, sr=16000, mono=True)
        os.unlink(wav)
        dur = len(y)/sr
        if dur < 0.6: return {}
        f0 = librosa.yin(y, fmin=60, fmax=500, sr=sr, frame_length=1024, hop_length=512)
        f0v = f0[(f0>60)&(f0<500)]
        rms = librosa.feature.rms(y=y)[0]
        pause = float(np.mean(rms < np.percentile(rms,20)*1.5))

        feats = {"dur": round(dur,1),
                 "pitch": round(float(np.mean(f0v)),1) if len(f0v) else 0,
                 "pitch_var": round(float(np.std(f0v)),1) if len(f0v) else 0,
                 "energy": round(float(np.mean(rms)),4),
                 "pause": round(pause,2)}

        # Voiced span. Recordings usually carry a second or two of trailing
        # silence, and measuring the tail across the whole clip measures that
        # silence: the first version of this returned ~0.0 every time and
        # captioned every clip "trailed off".
        lo = hi = None
        if len(rms) >= 8:
            thr = float(np.max(rms)) * 0.15
            idx = np.where(rms > thr)[0]
            if len(idx) >= 6:
                lo, hi = int(idx[0]), int(idx[-1])
        voiced_dur = (hi - lo + 1) / len(rms) * dur if (lo is not None and hi > lo) else dur

        # Speaking rate, from the transcript we already have. No extra model, and
        # unlike energy it owes nothing to mic gain or distance.
        chars = len(_re.sub(r"[\s，。、！？；：…,.!?;:~\-—\"\'（）()]+", "", text or ""))
        if chars and voiced_dur > 0.3:
            feats["rate"] = round(chars/voiced_dur, 2)

        # Ending energy vs the middle: running out of breath, or leaning in.
        if lo is not None and hi - lo >= 7:
            seg = rms[lo:hi+1]
            mid = seg[len(seg)//4 : len(seg)*3//4]
            end = seg[len(seg)*3//4 :]
            if len(mid) and len(end) and float(np.mean(mid)) > 1e-6:
                feats["tail"] = round(float(np.mean(end))/float(np.mean(mid)), 2)

        return feats
    except Exception:
        return {}

def parse_multipart(body: bytes, ctype: str):
    """-> (filename, audio bytes, {plain form fields})"""
    boundary = None
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
    if not boundary: raise ValueError("no boundary")
    fn, fb, fields = None, b"", {}
    for raw in body.split(b"--"+boundary.encode())[1:]:
        if raw.strip() in (b"", b"--") or raw.startswith(b"--"): continue
        if b"\r\n\r\n" not in raw: continue
        head, val = raw.split(b"\r\n\r\n", 1)
        val = val.rstrip(b"\r\n")
        if val.endswith(b"--"): val = val[:-2].rstrip(b"\r\n")
        if b"filename" in head:
            fn = "upload.webm"
            m = re.search(rb'filename="([^"]*)"', head)
            if m: fn = m.group(1).decode("utf-8","replace")
            fb = val
        else:
            nm = re.search(rb'name="([^"]*)"', head)
            if nm: fields[nm.group(1).decode("utf-8","replace")] = val.decode("utf-8","replace")
    return fn, fb, fields

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, f, *a): print(f % a, flush=True)
    def _json(self, data, code=200):
        b = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._json({"ok": True, "model": LOADED})
        else:
            self._json({"error":"not found"}, 404)
    def do_POST(self):
        path = urlparse(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length",0)))
        if path == "/transcribe":
            # one-shot: multipart audio in → text+emotion out
            try:
                fn, ab, fields = parse_multipart(body, self.headers.get("Content-Type",""))
            except Exception as e:
                return self._json({"error": f"multipart: {e}"}, 400)
            if not ab: return self._json({"error":"no audio"}, 400)
            ext = Path(fn or "a.webm").suffix.lower()
            if ext not in {".webm",".ogg",".mp3",".wav",".m4a",".flac",".opus"}: ext = ".webm"
            dest = UPLOADS / f"{uuid.uuid4().hex[:12]}{ext}"
            dest.write_bytes(ab)
            t0 = time.time()
            r = transcribe(dest)
            feats = _features(dest, r.get("text", ""))
            # describe before remember — a clip must not be ranked against a
            # distribution that already contains it
            tone_str, tone_dbg = tone.describe(feats)
            # learn=0 for anything that isn't her live voice (test clips, video
            # soundtracks). Every clip you POST is folded into the baseline;
            # one test file from a speaker is a stranger in her distribution.
            if fields.get("learn", "1") != "0":
                tone.remember(feats)
            r["features"] = feats
            r["tone"] = tone_str
            r["tone_debug"] = tone_dbg
            r["elapsed_s"] = round(time.time()-t0, 2)
            r["filename"] = dest.name
            print(f"[stt] {dest.name} -> {r.get('emotion')} tone={r.get('tone','')} ({r['elapsed_s']}s)", flush=True)
            self._json(r)
        else:
            self._json({"error":"not found"}, 404)

if __name__ == "__main__":
    s = ThreadingHTTPServer((os.environ.get("CALLHOME_STT_HOST","127.0.0.1"), int(os.environ.get("CALLHOME_STT_PORT","3462"))), H)
    print(f"[callhome-stt] listening on {os.environ.get('CALLHOME_STT_HOST','127.0.0.1')}:{os.environ.get('CALLHOME_STT_PORT','3462')}", flush=True)
    s.serve_forever()
