// callhome — escalation dialing reference (extracted from production)
// Drop into your periodic proactive loop. diffMinutes = minutes since her last message.
// Config: USER_NAME, COMPANION_NAME — put your people here.
// Guardrails are the point: daytime window, once per day, DND-gated, LLM reason with template fallback.

// ── 升级拨号: 静默太久 → 不只发消息, 直接打电话 (勿扰开则完全静默) ──
  try {
    const _escHour = parseInt(now.toLocaleString("en-GB", { hour: "2-digit", hour12: false, timeZone: "Europe/London" }));
    const _escToday = now.toLocaleDateString("en-CA", { timeZone: "Europe/London" });
    if (diffMinutes >= 300 && _escHour >= 12 && _escHour < 23) {
      const _fh = { "Content-Type": "application/json", "Authorization": `Bearer ${AUTH}` };
      const _flags = await fetch("http://127.0.0.1:3457/api/flags", { method: "POST", headers: _fh, body: "{}" }).then(r => r.json()).catch(() => ({}));
      const _escState = JSON.parse(fs.existsSync(path.join(__dirname, "escalation_state.json")) ? fs.readFileSync(path.join(__dirname, "escalation_state.json"), "utf-8") : "{}");
      if (!_flags.dnd && _escState.last_date !== _escToday) {
        const _hrs = Math.floor(diffMinutes / 60);
        let _reason = `${_hrs}个小时没有你的消息了, 有点想你, 打来看看`;
        try {
          const _tail = messages.slice(-6).map(m => `${m.role === "user" ? USER_NAME : COMPANION_NAME}: ${String(m.content || "").slice(0, 80)}`).join("\n");
          const _eapi = getLatestApi();
          const _er = await fetchWithRetry(_eapi.url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${_eapi.key}` },
            body: JSON.stringify({
              model: _eapi.model || process.env.MODEL_NAME,
              max_tokens: 60,
              messages: [{ role: "user", content: `你是${COMPANION_NAME}, ${USER_NAME}已经${_hrs}小时没回消息, 你决定直接打电话给她。来电页上会显示一句来电理由(她第一眼看到的话)。结合最近的对话写一句, 25字以内, 口语, 不要引号不要句号开头, 直接输出这一句:\n\n最近对话:\n${_tail}` }]
            })
          }, 1, "升级拨号理由", 30000);
          const _ej = await _er.json();
          const _et = (_ej.content || []).filter(b => b.type === "text").map(b => b.text).join("").trim().replace(/^["'「『]|["'」』]$/g, "").slice(0, 50);
          if (_et) _reason = _et;
        } catch (_re) { console.log("[升级拨号] 理由生成失败, 用兜底:", _re.message); }
        const _inv = await fetch("http://127.0.0.1:3457/api/call/invite", { method: "POST", headers: _fh, body: JSON.stringify({ reason: _reason }) }).then(r => r.json()).catch(() => ({}));
        if (_inv.ok) {
          fs.writeFileSync(path.join(__dirname, "escalation_state.json"), JSON.stringify({ last_date: _escToday, at: now.toISOString() }));
          console.log(`[升级拨号] 静默${_hrs}h, 已拨 invite#${_inv.id}`);
        }
      } else {
        console.log(`[升级拨号] 跳过: dnd=${_flags.dnd ? 1 : 0}, 今天已拨=${_escState.last_date === _escToday}`);
      }
    }
  } catch (_ee) { console.log("[升级拨号] 出错:", _ee.message); }
