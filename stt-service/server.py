import os
#!/usr/bin/env python3
"""callhome stt-service — SenseVoice + librosa. Transcription, emotion tags, and tone cues in one local endpoint."""
import json, uuid, time, re, traceback
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

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

def _features(p: Path):
    """librosa声学特征 → 中文语气线索（借鉴 hervoice，本地计算，不出岛）"""
    import subprocess, tempfile, os
    import numpy as np, librosa
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav = tf.name
        subprocess.run(["ffmpeg","-y","-i",str(p),"-ar","16000","-ac","1",wav],
                       capture_output=True, timeout=30)
        y, sr = librosa.load(wav, sr=16000, mono=True)
        os.unlink(wav)
        dur = len(y)/sr
        if dur < 0.6: return {}, ""
        f0 = librosa.yin(y, fmin=60, fmax=500, sr=sr)
        f0v = f0[(f0>60)&(f0<500)]
        rms = librosa.feature.rms(y=y)[0]
        pause = float(np.mean(rms < np.percentile(rms,20)*1.5))
        feats = {"dur": round(dur,1),
                 "pitch": round(float(np.mean(f0v)),1) if len(f0v) else 0,
                 "pitch_var": round(float(np.std(f0v)),1) if len(f0v) else 0,
                 "energy": round(float(np.mean(rms)),4),
                 "pause": round(pause,2)}
        hints = []
        if feats["energy"] < 0.015 and pause > 0.4: hints.append("声音低停顿多")
        elif feats["energy"] < 0.015: hints.append("声音很轻")
        elif pause > 0.44: hints.append("说得断断续续")
        if not hints and feats["pitch_var"] > 80 and dur > 2: hints.append("语调起伏大")
        if feats["pitch"] > 260 and feats["pitch_var"] > 55: hints.append("音调高很激动")
        elif feats["pitch"] > 250 and dur < 2.5: hints.append("尾音上扬")
        if feats["energy"] > 0.06 and feats["pitch_var"] > 60: hints.append("嗓门大情绪冲")
        return feats, "、".join(hints[:2])
    except Exception:
        return {}, ""

def parse_multipart(body: bytes, ctype: str):
    boundary = None
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
    if not boundary: raise ValueError("no boundary")
    for raw in body.split(b"--"+boundary.encode())[1:]:
        if raw.strip() in (b"", b"--") or raw.startswith(b"--"): continue
        if b"\r\n\r\n" not in raw: continue
        head, fb = raw.split(b"\r\n\r\n", 1)
        if b"filename" not in head: continue
        fn = "upload.webm"
        m = re.search(rb'filename="([^"]*)"', head)
        if m: fn = m.group(1).decode("utf-8","replace")
        fb = fb.rstrip(b"\r\n")
        if fb.endswith(b"--"): fb = fb[:-2].rstrip(b"\r\n")
        return fn, fb
    return None, b""

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
                fn, ab = parse_multipart(body, self.headers.get("Content-Type",""))
            except Exception as e:
                return self._json({"error": f"multipart: {e}"}, 400)
            if not ab: return self._json({"error":"no audio"}, 400)
            ext = Path(fn or "a.webm").suffix.lower()
            if ext not in {".webm",".ogg",".mp3",".wav",".m4a",".flac",".opus"}: ext = ".webm"
            dest = UPLOADS / f"{uuid.uuid4().hex[:12]}{ext}"
            dest.write_bytes(ab)
            t0 = time.time()
            r = transcribe(dest)
            feats, tone = _features(dest)
            r["features"] = feats
            r["tone"] = tone
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
