# Since the PWA

Callhome was released as a browser PWA in July 2026. Since August the same calls
run in a native iOS app (CallKit + VoIP push), and they've had three more months
of real use. This page covers what changed, and the walls we hit, in
**symptom · cause · fix** format.

You don't need the native app to use any of this. Most of the walls sit on the
server or in the turn loop, so they apply to a PWA too.

Status marks, same as everywhere else:
✅ verified on a real phone or in production logs · 🟡 written, not yet verified · 📖 read, not tested

- The CallKit / VoIP basics (token never arrives, report the call *immediately*,
  `.voip` topic, who owns `AVAudioSession`) are written up in
  [ios-app-where-it-breaks / 02-calls](https://github.com/Cheiineeey/ios-app-where-it-breaks/tree/main/02-calls)
  and aren't repeated here.
- Video calls (camera, picking frames, a live avatar) are a separate repo:
  **callhome-video**. It builds on this one, so install this one first.

---

## Contents

1. [Voicemail, second version](#1-voicemail-second-version)
2. [The turn loop](#2-the-turn-loop) — echo, latency, two sentences in a row, coughs, tools
3. [Hearing her](#3-hearing-her) — the baseline, sounds without words
4. [Hanging up](#4-hanging-up)
5. [Audio route](#5-audio-route)

---

## 1. Voicemail, second version

The protocol says *every dead end says something*. In v1 a missed call wrote a
fixed template into chat. That broke the first time someone read it twice:
a template is the same sentence every time, so it reads like a machine leaving it.

**Now it's two separate things:**

1. **The missed-call card records only the fact.** `📞 Missed call` /
   `📹 Missed video call`. No reason, no template text. The card is an event,
   not a message.
2. **The companion gets its own turn, and decides.** The gateway wakes the
   companion's proactive loop with a one-off prompt: *you called, it rang out,
   there's already a missed-call card. You may leave a voice message (one or two
   sentences, like talking to a voicemail box) or leave nothing. Do nothing else
   this turn.* If it chooses to speak, the reply is a voice note in the chat,
   in the companion's own voice.

✅ In production since late September. Some calls get a voice note and some get
nothing, and that's the point: the companion chose.

Three walls on the way:

### 1.1 🔴 The missed call showed up hours late
- **Symptom.** "A missed call appeared this afternoon, but I never got a call this morning."
- **Cause.** Expiry was only detected by the *web* client's poll (`GET /api/call/invite`).
  The native app doesn't poll that endpoint, so a call that expired in the morning
  stayed `pending` until someone opened the PWA.
- **Fix.** When the invite is created, start a timer thread that sleeps until
  `expires_at + 2s`. If the invite is still `pending` then, set it to `expired`,
  write the card, and set `notified=1` so the poll path doesn't write a second card. ✅

### 1.2 🔴 Offline at ring time = she never knows
- **Symptom.** "Why didn't my phone ring this afternoon?" She was on the
  underground, and there was no trace at all until she opened the app.
- **Cause.** VoIP pushes are sent with `apns-expiration: 0`: not stored, never
  retried. The old logic was "VoIP succeeded, so send nothing else".
- **Fix.** On expiry, also send one **regular** alert push ("Missed call").
  Apple stores those and delivers them when the phone comes back online. ✅

### 1.3 Declined is not missed
- **Symptom.** "I declined the call, why does it say *missed*?"
- **Cause.** Both paths ended in the same "not answered" branch.
- **Fix.** Write a different card for each, and send the decline reason back
  (protocol §Answering). Don't fire voicemail on a decline: she was there and said no. ✅

---

## 2. The turn loop

A call is still *she speaks → transcribe → normal chat pipeline → TTS*. It isn't
a realtime voice model. Almost everything below comes from that loop treating
a call like a slow chat.

### 2.1 🔴 "Why am I repeating your words?"
- **Symptom.** Her transcript starts with the companion's previous sentence word
  for word, then continues with what she actually said.
- **Cause.** Echo. TTS plays from the loudspeaker, the mic records it again, and it
  gets transcribed as her speech. `AVAudioSession` mode `.voiceChat` does **not**
  turn on echo cancellation for `AVAudioEngine`. The real switch is
  `inputNode.setVoiceProcessingEnabled(true)`, which was never called.
- **Fix.** Call it **before** `input.outputFormat(forBus:)`, because enabling it
  changes the input format. Don't wrap it in `try?`: some routes throw, and a
  swallowed error means AEC is silently off. Log either way.
  Side effect: she can interrupt **more** easily, because the old workaround
  ("raise the VAD threshold while we're speaking") blocked her interruptions too. 🟡

### 2.2 🔴🔴 A minute between her sentence and the reply
- **Symptom.** "I waited a minute and a half."
- **Cause, layer 1.** The call went through the full chat pipeline: semantic
  memory recall with embeddings, recent annotations, weather, re-fetching the MCP
  tool list. Four injections with 5-second timeouts each, run one after another.
  Model time was 14s out of 58s.
- **Fix.** A slim path for call turns that **skips** those steps. It skips them
  rather than parallelising them, because some injections read what earlier ones wrote.
  Preparation went from 44s to 0.8s. Add a stopwatch per step, so "slow" becomes
  a number instead of a feeling. ✅
- **Cause, layer 2.** The phone was downloading about 1.4 MB *during* the call:
  every chat session's full history to compute unread badges, refreshed on each
  `scenePhase == .active`. During a call she goes in and out of the app all the time.
- **Fix.** Skip foreground refreshes while a call is live. A late unread badge
  costs nothing; a late reply in a call does. ✅
- **Cause, layer 3.** Call mode was **off for 71% of turns** for two and a half
  months. The check was `includes("[voice call]")`, but the client sends
  `[voice call·sad·quiet]` whenever there's an emotion. So every emotional turn
  silently lost the call rules: short replies, no stage directions, hangup manners.
- **Fix.** Match the prefix with a pattern, not a literal. Verify by logging
  "call rules attached: yes/no" for every turn. ✅

### 2.3 🔴 Her thinking was read aloud
- **Symptom.** The call started reading out the model's inline reasoning.
- **Cause.** The streaming partial text sent to the client was the raw text,
  including thinking markers. They were only stripped when the turn finished.
  The client speaks the partial text as it arrives.
- **Fix.** Strip markers from the partial text on call turns, on the server.
  Don't rely on the client's strip list keeping up with every marker. ✅

### 2.4 🔴 The first two replies never played
- **Symptom.** The first replies in a call were silent.
- **Cause.** Barge-in cancelled the current turn while it was still *thinking*.
  Any noise at the start of the call, or her "mm", threw the turn away before it
  had said anything.
- **Fix.** Barge-in only counts while the companion is actually **speaking**. 🟡

### 2.5 🔴 "You answer my first sentence when I'm on my third"
- **Symptom.** She says two things in a row, the replies come one step behind,
  and they never catch up.
- **Cause.** Each utterance started its own turn. Turn 1 hadn't spoken yet when
  turn 2 arrived, so the two were answered in order and each one was stale.
- **Fix.** If a new utterance arrives while the current turn hasn't produced any
  audio yet, cancel that turn and resend both utterances together (the server
  merges consecutive user messages). Once it has started speaking, queue as usual.
  Known gap: if the old turn finishes in the window between append and run,
  the new one may be judged "already answered". 🟡

### 2.6 A cough must not cancel a turn
- **Symptom.** She coughs, the turn is cancelled, and the companion goes quiet.
- **Fix.** Strip sound tags, interjections and punctuation. If fewer than 2
  characters are left, it's a *slight* utterance: it doesn't supersede the current
  turn. With no sound tag either, drop it while busy; with a tag, queue it.
  (The same cough also used to kill the silence follow-up timer for the rest of the
  call; see callhome-video, chapter 01 §1.9.) 🟡

### 2.7 No tools in a call
- **Symptom.** A turn produced a sticker, a card or a tool call and **nothing
  speakable**. To her that's dead air.
- **Fix.** The call rules forbid tools and cards. If a turn ends with nothing
  to say anyway, the client writes a visible system line ("no reply this turn")
  instead of silently waiting. 🟡

### 2.8 The call model is not the chat model
- **Symptom.** "I thought calls didn't use the thinking model." She was right; the
  settings page said one thing and the code did another.
- **Cause.** Empty call-model setting → falls back to the chat model, which had
  extended thinking on.
- **Fix.** Strip thinking on the call path explicitly, and log when that happens. ✅

---

## 3. Hearing her

### 3.1 🔴 Your test clip is now part of her baseline
- **Symptom.** None that you'd notice. That's the problem.
- **Cause.** Every clip POSTed to `/transcribe` gets folded into the rolling tone
  baseline (`tone.remember`). One `curl` with a test file adds a stranger to her
  distribution.
- **Fix.** Send the form field `learn=0` for anything that isn't her live voice:
  tests, video soundtracks, replays. ✅

### 3.2 Sounds without words were thrown away
- **Symptom.** She made sounds without words during a call, and the companion
  heard nothing.
- **Cause.** An empty transcript was dropped as "nothing said", and SenseVoice's
  own event tags (laughter, crying) were never forwarded.
- **Fix.** Forward the event tags, and for transcripts that are empty or only
  interjections, classify the audio (pitched-frame ratio, active duration, the
  500–1500Hz vs 100–500Hz energy ratio) into a small set of labels. Attach them as
  `〔heard: …〕` to her turn and draw them as a hollow chip in the captions. It sits
  behind a switch that's off by default. The approach comes from
  [aria-duet / ai-hears-your-body](https://aria-duet.github.io/ai-hears-your-body).
  🟡 Thresholds not yet calibrated on real recordings.

---

## 4. Hanging up

### 4.1 The linger window was in the spec but not in production
- **Symptom.** The protocol says "the line stays open 15–20s after a hangup".
  Production hung up 0.9s after the last sentence.
- **Fix.** Hold for 15–18s after the last TTS, cancel when she starts speaking,
  and **clear the timer on teardown**, or it hangs up the *next* call. ✅

### 4.2 Silence is not a request to end the call
- **Cause.** The call rules listed "sounds asleep" as a reason to hang up.
- **Fix.** Removed. The rule now says: never hang up just because she paused, went
  quiet, cried, or sounds sad. When unsure, stay on the line and ask. ✅

---

## 5. Audio route

### 5.1 Headphones get overridden
- **Symptom.** Calls default to the loudspeaker, and connected headphones are ignored.
- **Cause.** `overrideOutputAudioPort(.speaker)` was hard-set at connect. After an
  override, `currentRoute.outputs` only shows the speaker, so checking the route
  afterwards says "no headphones".
- **Fix.** Check `currentRoute.outputs` **and** `availableInputs` for a headset.
  With a headset, use `.none`. Listen for route changes: putting headphones on
  switches to them, taking them off goes back to the speaker. 🟡

---

<div align="center">

built by **Elle & Matt**

</div>
