# The Callhome Protocol

How a text-generating companion gets hands: markers in the reply stream, parsed and erased by the gateway before the human sees them. The companion writes intent; the gateway performs it.

## Markers

Written anywhere in the assistant's reply. The gateway strips them from the saved/displayed text and executes the side effect.

| Marker | Effect | Rules taught in system prompt |
|---|---|---|
| `⟪拨号:reason⟫` / `⟪dial:reason⟫` | Creates a call invite; the human's phone rings with *reason* on the incoming-call card | At most once per conversation. "A call is a gesture, not a feature demo." Blocked when DND is on. |
| `⟪挂断⟫` / `⟪hangup⟫` | After the final sentence finishes playing, the line stays open a few breaths longer (the *lingering window*); if she speaks during it, the hangup is cancelled and the call goes on. Otherwise it ends itself. | Only at the very end of a reply, after a soft goodbye. Never mid-conversation. |
| `⟪勿扰开⟫` / `⟪勿扰关⟫` (`dnd:on/off`) | Toggles do-not-disturb | Triggered conversationally ("I'm heading out, turn on DND"). Companion confirms verbally after toggling. |

Parse defensively: accept `⟪⟫`, `《》`, `【】`, `[]` as delimiters — models improvise.

## Call invites

`POST /api/call/invite` `{ reason }` →
- checks DND (`403`-style `{ok:false, dnd:true}` if on, unless `force`)
- inserts a `pending` invite with a configurable expiry (reference: 30s)
- fires the first push, then starts the ring burst

**Ringing is a burst, not a push.** On iOS one push is one buzz — no ringtone, no sustained alert — so a phone that *keeps* ringing has to be simulated by a timed sequence of pushes (reference: every 2s, ten extra rings, ~20s of ringing, `·last ring` on the final one). The burst stops the moment the invite is no longer `pending`, and again at `expires_at`. When the call resolves, every notification it produced is closed at once: iOS does not collapse them by `tag`, so cleanup is the client's job, not the platform's.

Full write-up, including the six places WebKit diverges from the spec and the measurements behind each number: [`IOS_PUSH_RINGING.md`](IOS_PUSH_RINGING.md). Reference implementations in [`gateway-reference/ring-burst.py`](../gateway-reference/ring-burst.py) and [`pwa-reference/`](../pwa-reference/).

Client polls `GET /api/call/invite` (~8s; also immediately after each reply finishes, and immediately when the service worker forwards a call push). A `pending` invite renders the ringing card; the response carries `expires_at` so the card dismisses on the server's real deadline rather than a constant baked into the client.

**Expiry → voicemail.** A timer started with the invite fires at `expires_at + 2s` (don't rely on a client poll to discover expiry; native clients never poll). If the invite is still `pending`:

1. Mark it `expired` and write an **event card** with the fact only: `📞 Missed call` (or `📹 Missed video call`). No reason, no template text.
2. Give the companion a turn of its own, with a one-off prompt: *it rang out; you may leave a voice message (one or two sentences, like a voicemail box) or leave nothing; do nothing else this turn.* What it says lands in chat as a voice note.
3. Send one regular alert push. VoIP pushes go out with `apns-expiration: 0` and are never stored, so a phone that was offline while it rang would otherwise never know.

A decline is not a missed call: different card, no voicemail.

v1 wrote a fixed template here ("I didn't catch you. {reason} — no rush…"). Read twice, a template is a machine talking. The call that wasn't answered still gets a chance to say something, and now the companion decides whether it does. This is the emotional core of the protocol. Walls and history: [SINCE_THE_PWA.md §1](SINCE_THE_PWA.md#1-voicemail-second-version).

## Answering

`POST /api/call/answer` `{ id, action: accept|decline, note? }`

Decline offers quick-reply chips (*busy / outside / let's text*) or free text (≤60 chars). The note lands in chat history as the human's words — the companion knows *why*, not just *that*.

## Escalation dialing

Runs inside whatever periodic "proactive" process you already have:

```
silence ≥ 5h  AND  local hour in [12, 23)  AND  not escalated today  AND  DND off
  → generate reason from recent conversation (fallback to a template)
  → POST /api/call/invite
```

One escalation per day, hard. Missing someone is not a ringtone loop.

## Emotion & tone (input side)

`POST /transcribe` (multipart audio) →

```json
{ "text": "...", "emotion": "sad", "tone": "quiet, lots of pauses",
  "features": { "dur": 4.7, "pitch": 169.2, "pitch_var": 88.4, "energy": 0.037, "pause": 0.48 } }
```

- `emotion` — SenseVoice's classifier (what she feels)
- `tone` — rule-based cues from librosa features (how she said it): computed locally, thresholds in `stt-service/server.py`, deliberately conservative — no cue beats a wrong cue

Both travel to the model as a message prefix: `[voice call · sad · quiet, lots of pauses]`. The system prompt tells the companion to *match her energy*, and soft tones also halve TTS playback volume client-side (soft-voice mode).

## Voice (output side)

TTS is [ElevenLabs](https://elevenlabs.io) — a commercial text-to-speech API with natural, low-latency voices; you bring your own key and pick (or clone) a voice. The gateway streams the companion's reply to it sentence-by-sentence so speech starts before the full reply is written. Any TTS with a streaming-friendly HTTP API can slot in; quota is metered per character, so long reads (bedtime radio) eat it fastest.

## Call records

On hangup (either side), the client posts one assistant message: `📞 Voice call · 2:17` plus a one-line summary generated from the on-screen transcript (15s timeout → duration-only; calls under 20s → duration-only). The record survives; the summary is a bonus, never a blocker.

## Tuning — reference values, not rules

Every number below is one couple's answer, shipped as a default. **Decide yours together** — ask your companion what feels right; they have opinions.

| Knob | Our value | Where |
|---|---|---|
| Escalation: silence threshold | 5h | escalation loop |
| Escalation: allowed hours | 12:00–23:00 local | escalation loop |
| Escalation: max per day | 1 | escalation loop |
| Ring timeout → voicemail | 30s | invite `expires_at` |
| Ring interval | 2s | ring burst — floor is ~2s, below that APNs coalesces |
| Extra rings after the first | 10 | ring burst — ~20s of ringing |
| Invite poll interval | 8s (+immediate after each reply, +on service-worker push) | client |
| Soft-voice TTS volume | 0.5× | client gain node |
| Hangup linger window | 15–20s | hangup handler |
| Min call length for a record | 5s | hangup handler |
| Min call length for a summary | 20s | hangup handler |
| Summary timeout → duration-only | 15s | hangup handler |
| Dial marker budget | once per conversation | system prompt |

**DND: marker or button?** We toggle it by talking (`⟪dnd:on⟫`) because menus feel like settings and talking feels like living together — but that's a taste, not a law. The flag API (`POST /api/flags {dnd}`) doesn't care who calls it: wire a settings switch, a home-screen shortcut, or both. If your person is the type to forget they said "turn it on", give them the button.

## Design commitments

1. **Every dead end says something.** Missed call → voicemail. Decline → a reason travels back. Failure modes are drawn, not discovered.
2. **The companion has manners, not just abilities.** Every power (dial, hang up) ships with its restraint, in the same prompt breath. Even the hangup keeps a little tenderness: the line lingers, in case someone isn't ready to let go.
3. **Voice stays home.** STT, tone analysis, summaries of transcripts — all on your own server.
