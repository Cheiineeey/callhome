# The Callhome Protocol

How a text-generating companion gets hands: markers in the reply stream, parsed and erased by the gateway before the human sees them. The companion writes intent; the gateway performs it.

## Markers

Written anywhere in the assistant's reply. The gateway strips them from the saved/displayed text and executes the side effect.

| Marker | Effect | Rules taught in system prompt |
|---|---|---|
| `⟪拨号:reason⟫` / `⟪dial:reason⟫` | Creates a call invite; the human's phone rings with *reason* on the incoming-call card | At most once per conversation. "A call is a gesture, not a feature demo." Blocked when DND is on. |
| `⟪挂断⟫` / `⟪hangup⟫` | After the final sentence finishes playing, the call ends itself | Only at the very end of a reply, after a soft goodbye. Never mid-conversation. |
| `⟪勿扰开⟫` / `⟪勿扰关⟫` (`dnd:on/off`) | Toggles do-not-disturb | Triggered conversationally ("I'm heading out, turn on DND"). Companion confirms verbally after toggling. |

Parse defensively: accept `⟪⟫`, `《》`, `【】`, `[]` as delimiters — models improvise.

## Call invites

`POST /api/call/invite` `{ reason }` →
- checks DND (`403`-style `{ok:false, dnd:true}` if on, unless `force`)
- inserts a `pending` invite with a 90s expiry
- fires a push notification

Client polls `GET /api/call/invite` (~8s; also immediately after each reply finishes). A `pending` invite renders the ringing card.

**Expiry → voicemail.** On the poll that discovers expiry, the server writes a message into the pinned chat session:

```
📞 Missed call
Voicemail: I didn't catch you. {reason} — no rush, talk to me when you're back.
```

The call that wasn't answered still says something. This is the emotional core of the protocol.

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

## Call records

On hangup (either side), the client posts one assistant message: `📞 Voice call · 2:17` plus a one-line summary generated from the on-screen transcript (15s timeout → duration-only; calls under 20s → duration-only). The record survives; the summary is a bonus, never a blocker.

## Design commitments

1. **Every dead end says something.** Missed call → voicemail. Decline → a reason travels back. Failure modes are drawn, not discovered.
2. **The companion has manners, not just abilities.** Every power (dial, hang up) ships with its restraint, in the same prompt breath.
3. **Voice stays home.** STT, tone analysis, summaries of transcripts — all on your own server.
