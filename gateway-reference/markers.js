// callhome — marker parsing reference (extracted from production, persona removed)
// Runs after the reply stream is finalized, before saving/display.
// finalText: the assistant's complete reply. INVITE_API: your invite endpoint. AUTH: your bearer.

function handleMarkers(finalText, { INVITE_API, FLAGS_API, AUTH }) {
// ⟪拨号:理由⟫ → 创建来电邀请并从正文擦除
      try {
        const _dialM = finalText.match(/[⟪《【\[]\s*拨号\s*[:：]?\s*([^⟫》】\]]*)[⟫》】\]]/);
        if (_dialM) {
          const _dialReason = (_dialM[1] || "").trim() || "想听听你的声音";
          finalText = finalText.replace(_dialM[0], "").replace(/\n{3,}/g, "\n\n").trim();
          fetch("${INVITE_API}", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${AUTH}` },
            body: JSON.stringify({ reason: _dialReason })
          }).then(r => r.json()).then(d => console.log(`[chat/run] ⟪拨号⟫ invite#${d.id} push=${d.push}`)).catch(e => console.warn("[chat/run] 拨号失败:", e.message));
        }
      } catch (_de) { console.warn("[chat/run] 拨号解析失败:", _de.message); }
      try { finalText = finalText.replace(/[⟪《【\[]\s*挂断\s*[⟫》】\]]/g, "").trim(); } catch (_he) {}
      try {
        const _dm = finalText.match(/[⟪《【\[]\s*勿扰\s*(开|关)\s*[⟫》】\]]/);
        if (_dm) {
          finalText = finalText.replace(/[⟪《【\[]\s*勿扰\s*(开|关)\s*[⟫》】\]]/g, "").replace(/\n{3,}/g, "\n\n").trim();
          fetch("${FLAGS_API}", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${AUTH}` },
            body: JSON.stringify({ dnd: _dm[1] === "开" ? 1 : 0 })
          }).then(r => r.json()).then(d => console.log(`[chat/run] ⟪勿扰${_dm[1]}⟫ dnd=${d.dnd}`)).catch(e => console.warn("[chat/run] 勿扰切换失败:", e.message));
        }
      } catch (_dnde) {}
  return finalText;
}
module.exports = { handleMarkers };
