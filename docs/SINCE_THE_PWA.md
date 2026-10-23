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
2. [The turn loop](#2-the-turn-loop) — echo, latency, two sentences in a row, coughs, tools, stage tags read aloud
3. [Hearing her](#3-hearing-her) — the baseline, sounds without words, sounds around her, mixed-language transcription, emotion labels
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
- **Later change.** Cancelling every unanswered turn went too far: when she adds
  a separate thought half a minute later, throwing away the reply in progress
  makes the companion slower, not smarter. Now only cancel when she starts
  speaking again **within 3 seconds** of her last utterance being sent (she
  hadn't finished). After that, the new utterance waits and is answered right
  after the current reply plays. 🟡

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

### 2.9 🔴 Stage tags read aloud
- **Symptom.** In calls the companion said "closer… right ear…" out loud.
- **Cause.** Voice messages support position tags like `【right ear】` / `【closer】`
  for a binaural render. Calls don't do the binaural render, and the call client's
  text cleanup removed the **brackets** but kept the words inside them. The TTS
  read whatever was left.
- **Fix.** On every TTS path that doesn't consume a tag, remove the whole tag
  (bracket **and** word), before any generic punctuation cleanup. On the server,
  also catch the bare words at the start of a clause, since an old client may
  already have stripped the brackets. Don't strip them anywhere else: "I want to
  be closer" is a real sentence. 🟡

---

## 3. Hearing her

### 3.1 🔴 Your test clip is now part of her baseline
- **Symptom.** None that you'd notice. That's the problem.
- **Cause.** Every clip POSTed to `/transcribe` gets folded into the rolling tone
  baseline (`tone.remember`). One `curl` with a test file adds a stranger to her
  distribution.
- **Fix.** Send the form field `learn=0` for anything that isn't her live voice:
  tests, video soundtracks, replays. ✅
- **Same thing, from inside.** A feature that checks the companion's own TTS
  (transcribe what it just said, compare with the script) posted to the same
  endpoint, and for weeks the *companion's* voice went into her baseline.
  Opt-out flags get forgotten by the next feature you write. Safer: only learn
  from a whitelist of sources (her live call, her voice messages) and ignore
  everything else by default. ✅

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
  Code: [`stt-service/body.py`](../stt-service/body.py), run only for `source=call`.
  🟡 Thresholds not yet calibrated on real recordings.

### 3.3 Sounds around her: the phone listens too
This extends the idea from
[aria-duet / ai-hears-your-body](https://aria-duet.github.io/ai-hears-your-body)
past her voice. The server only hears clips the client uploads, and only her voice in them. For
the room around her (water, a zipper, the dog, a knock) the phone classifies the
mic stream itself with Apple's `SoundAnalysis` (`SNClassifySoundRequest(.version1)`,
~300 labels, 1.5s windows, 50% overlap). Mapped labels become the same
`〔heard: …〕` tags. They ride along with her next utterance, and a few
(water, the dog, a knock, crying) may start a turn on their own if they persist.
Pause it while the companion is speaking, or its own sound effects leak back
through the speaker and get reported as hers.

#### 3.3.1 🔴 A zipper came through, water never did
- **Symptom.** Zippers and rustling showed up. Running water and splashing,
  which were on the list, never did.
- **Cause.** The call runs with voice processing on (`.voiceChat` +
  `setVoiceProcessingEnabled(true)`), for echo cancellation. Its noise suppression
  is built to remove steady background noise, and running water *is* steady
  background noise. Short, sharp sounds like a zipper get through. What's left
  of the water scores below the 0.6 confidence bar and rarely fills two windows.
- **Fix (partial).** For the faint, steady sounds, lower the bar: 0.45 confidence,
  one window is enough to attach, two hits in 6s to start a turn. Also map all of
  Apple's water labels (`water`, `liquid_trickle_dribble`, `liquid_spraying`,
  `liquid_filling_container`…); query `knownClassifications` instead of guessing names.
  The real fix is a second input path without voice processing that only feeds
  the classifier, at the cost of hearing the companion's own voice again. 🟡

#### 3.3.2 🔴 Coughs had no path at all
- **Symptom.** Never once a cough.
- **Cause.** Two gaps, one on each side. The phone's label map didn't include
  `cough`. And the server, whose SenseVoice does tag coughs, never got one: the
  client discards clips shorter than 0.45s as mic bumps, and a cough is shorter
  than that.
- **Fix.** Classify `cough` / `sneeze` on the phone, at the lower bar from 3.3.1.
  They never start a turn on their own (2.6). They ride along with her next
  sentence. 🟡

#### 3.3.3 🔴 Put on headphones and the classifier goes silent
- **Symptom.** It worked one day and reported nothing at all from the next day on.
- **Cause.** `SNAudioStreamAnalyzer` is created with the format of the first
  buffer. Headphones switch to a Bluetooth mic, and the sample rate changes from
  48k to 16k/24k. Buffers in the new format get no results and no error.
- **Fix.** Remember the format the analyzer was built with, and rebuild it when
  a buffer arrives in a different format. Bluetooth mics also apply their own
  noise reduction, so expect less from them anyway. 🟡

#### 3.3.4 🔴 "I can hear the rain" (no, it couldn't)
- **Symptom.** On a walk, the companion said twice that it could hear the rain.
  No `〔heard: …〕` tag had arrived all call; the classifier had heard nothing.
- **Cause.** Once the call rules say "you may hear sounds around her", the model
  fills the gap from context (she's outdoors, it's windy) and states it as hearing.
- **Fix.** The rule has to say both halves: react to `〔heard: …〕` tags, and
  **never claim to hear anything there's no tag for**; ask instead. Detection
  will be wrong sometimes; the model making it up is worse, because she can't
  tell the difference. 🟡 In our gateway since late October; not yet seen in a call.

### 3.4 Mixed Chinese and English came back as homophones
- **Symptom.** She switches languages mid-sentence. The English half came back
  as Chinese characters that sound like it.
- **Cause.** SenseVoice is called with `language="zh"`, so everything is heard
  as Mandarin.
- **Fix.** Take the words from a cloud engine that does code-switching (Tencent
  Cloud ASR, `16k_zh-PY`: Mandarin + English + Cantonese), and keep SenseVoice
  running in parallel for emotion tags and sound events, which the cloud engine
  doesn't return. If the cloud doesn't answer within 6s, or fails, use the local
  words. Code: [`stt-service/cloud_asr.py`](../stt-service/cloud_asr.py), a no-op
  without keys. Notes:
  - The one-sentence API (`SentenceRecognition`) rejects `16k_zh_large` and
    `16k_zh_en` with `InvalidParameter`. Those engines exist, just not here.
  - It doesn't take webm. Convert everything to 16k mono wav first.
  - Max 60s per request. Longer clips fall back to local.
  ✅ In production since mid-October. The speaker's verdict: "recognition is a lot
  better than before."

### 3.5 Don't put an LLM on the per-sentence call path
- **Background.** SenseVoice's emotion tags (and emotion2vec's) are trained on
  acted speech. A naturally soft voice comes back `sad` no matter what she says.
  [hervoice](https://github.com/fishisfish0614/hervoice) showed this on hand-labelled
  real recordings, and replaces the tags with the speaker's own labels, picked by
  a fast LLM from the transcript, tone cues and sound events.
- **Symptom.** We added that to calls too. Every reply came about 4 seconds later.
- **Cause.** 17 of 27 sentences in one call hit the 4s timeout. An LLM round-trip
  per utterance, *in series* before the turn can start, costs more than a call can
  afford.
- **Fix.** Labels stay on voice messages, where nobody is waiting. Calls use
  SenseVoice + the tone cues and their simple veto rules. If you want labels in
  calls, run them off the critical path and attach them to the *next* turn. ✅

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
