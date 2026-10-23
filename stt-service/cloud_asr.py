"""Optional cloud transcription: Tencent Cloud ASR, one-sentence recognition.

Why: SenseVoice is called with language="zh". When the speaker mixes Chinese and
English mid-sentence (most bilingual people do), the English half comes back as
Chinese homophones. Tencent's 16k_zh-PY engine handles zh/en/yue code-switching.

How it's used: server.py runs this *in parallel* with SenseVoice and takes only
the words from here. Emotion tags and sound events (laughter, cough, BGM) still
come from SenseVoice — the cloud engine doesn't return them, and body.py needs them.

Every failure returns None and the caller falls back to the local transcript.
A call must never go deaf because a cloud API is down.

Setup: a Tencent Cloud account with ASR enabled, then
    export TENCENTCLOUD_SECRET_ID=...  TENCENTCLOUD_SECRET_KEY=...
Without those two variables this module is a no-op.
"""
import base64, hashlib, hmac, json, os, subprocess, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HOST = "asr.tencentcloudapi.com"
# SentenceRecognition rejects 16k_zh_large and 16k_zh_en with InvalidParameter
# (they exist, just not for this API). 16k_zh-PY = Mandarin + English + Cantonese.
_ENGINES = ("16k_zh-PY",)
_MAX_WAV = 1_930_000   # the API caps one request at 60s; 60s of 16k mono wav ≈ 1.92MB


def _keys():
    sid, skey = os.environ.get("TENCENTCLOUD_SECRET_ID"), os.environ.get("TENCENTCLOUD_SECRET_KEY")
    return (sid, skey) if sid and skey else None


def _sign(key, msg): return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _call(action, payload, sid, skey, timeout=8):
    """TC3-HMAC-SHA256 by hand, so there's no SDK dependency."""
    ts = int(time.time()); date = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    body = json.dumps(payload)
    canon = ("POST\n/\n\ncontent-type:application/json; charset=utf-8\nhost:%s\n\ncontent-type;host\n%s"
             % (_HOST, hashlib.sha256(body.encode()).hexdigest()))
    scope = f"{date}/asr/tc3_request"
    sts = f"TC3-HMAC-SHA256\n{ts}\n{scope}\n" + hashlib.sha256(canon.encode()).hexdigest()
    k = _sign(_sign(_sign(("TC3" + skey).encode(), date), "asr"), "tc3_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("https://" + _HOST, data=body.encode(), headers={
        "Authorization": f"TC3-HMAC-SHA256 Credential={sid}/{scope}, SignedHeaders=content-type;host, Signature={sig}",
        "Content-Type": "application/json; charset=utf-8", "Host": _HOST,
        "X-TC-Action": action, "X-TC-Version": "2019-06-14", "X-TC-Timestamp": str(ts)})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["Response"]


def transcribe(p: Path):
    """-> (text, engine) or None. text may be "" (nothing was said)."""
    keys = _keys()
    if not keys: return None
    try:
        # Always convert to 16k mono wav: phones send m4a, browsers send webm,
        # and the API doesn't take webm.
        wav = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000", "-f", "wav", "-"],
                             capture_output=True, timeout=10).stdout
        if not wav or len(wav) > _MAX_WAV: return None
        data = base64.b64encode(wav).decode()
        for eng in _ENGINES:
            r = _call("SentenceRecognition", {"EngSerViceType": eng, "SourceType": 1, "VoiceFormat": "wav",
                                              "Data": data, "DataLen": len(wav), "FilterPunc": 0, "ConvertNumMode": 1}, *keys)
            if "Error" in r:
                print(f"[cloud-asr] {eng} {r['Error'].get('Code')}: {r['Error'].get('Message')}", flush=True)
                continue
            return (r.get("Result") or "").strip(), eng
    except Exception as e:
        print(f"[cloud-asr] {type(e).__name__}: {e}", flush=True)
    return None
