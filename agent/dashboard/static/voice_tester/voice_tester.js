// Voice tester — WebSocket + mic capture + audio playback
// Phase 17 — vanilla JS, no framework, fits the existing /static/atlas vendored-only constraint.

(function () {
  const $ = sel => document.querySelector(sel);
  const els = {
    wsStatus:   $("#ws-status"),
    statePill:  $("#state-pill"),
    spendPill:  $("#spend-pill"),
    camPicker:  $("#cam-picker"),
    startBtn:   $("#start-btn"),
    resetBtn:   $("#reset-btn"),
    taskTable:  $("#task-table tbody"),
    proposed:   $("#proposed-pre"),
    transcript: $("#transcript"),
    micBtn:     $("#mic-btn"),
    micLabel:   $("#mic-label"),
    textInput:  $("#text-input"),
    sendBtn:    $("#send-btn"),
    kvTbody:    $("#kv-tbody"),
    totalsTurns: $("#totals-turns"),
    totalsCost:  $("#totals-cost"),
    totalsP50:   $("#totals-p50"),
    totalsP95:   $("#totals-p95"),
    audio:       $("#reply-audio"),
  };

  // ─── State ───
  let ws = null;
  let cams = [];
  let totals = { turns: 0, cost: 0, latencies: [] };
  let mediaRecorder = null;
  let audioChunks = [];

  // ─── WS connection ───
  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/api/voice/stream`;
    ws = new WebSocket(url);

    ws.onopen = () => setStatus("ws-status", "ok", "CONNECTED");
    ws.onclose = () => {
      setStatus("ws-status", "bad", "DISCONNECTED");
      setControlsEnabled(false);
    };
    ws.onerror = (e) => {
      console.error("ws error", e);
      setStatus("ws-status", "bad", "WS ERROR");
    };
    ws.onmessage = (evt) => {
      try { handleServerMsg(JSON.parse(evt.data)); }
      catch (e) { console.error("bad ws msg", evt.data, e); }
    };
  }

  function sendMsg(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    } else {
      logSys("⚠ WebSocket not open — refresh page.");
    }
  }

  // ─── Server msg dispatcher ───
  function handleServerMsg(m) {
    switch (m.type) {
      case "hello":
        cams = m.cams || [];
        populateCamPicker(cams);
        els.startBtn.disabled = false;
        els.camPicker.disabled = false;
        logSys(`▸ Cycle ${m.cycle_id} ready. ${cams.length} CAMs available.`);
        break;
      case "session_started":
        renderTasks(m.tasks);
        setStatus("state-pill", "info", m.state);
        setControlsEnabled(true);
        logSys(`▸ Session started as ${m.cam.name} (${m.cam.email}).`);
        break;
      case "reset_ack":
        totals = { turns: 0, cost: 0, latencies: [] };
        renderTotals();
        els.transcript.innerHTML = "";
        logSys(`▸ Reset. New cycle ${m.cycle_id}.`);
        setControlsEnabled(false);
        els.proposed.textContent = "none yet";
        break;
      case "transcript":
        logMsg("CAM", m.text, "vt-cam");
        break;
      case "tool":
        logMsg("TOOL", `${m.name}(${JSON.stringify(m.args)})`, "vt-tool");
        break;
      case "state":
        setStatus("state-pill", "info", m.state);
        break;
      case "reply_text":
        logMsg("ATLAS", m.text, "vt-atlas");
        break;
      case "reply_audio":
        playAudio(m.b64, m.mime);
        break;
      case "turn_summary":
        renderTurnSummary(m);
        break;
      case "error":
        logSys(`✗ ${m.detail}`);
        break;
      default:
        console.log("unknown msg", m);
    }
  }

  // ─── UI helpers ───
  function populateCamPicker(list) {
    els.camPicker.innerHTML = "";
    const ph = document.createElement("option");
    ph.value = ""; ph.textContent = "— select CAM —";
    els.camPicker.appendChild(ph);
    list.forEach(c => {
      const o = document.createElement("option");
      o.value = c.email;
      o.textContent = `${c.name}  ·  ${c.email}`;
      els.camPicker.appendChild(o);
    });
  }

  function renderTasks(tasks) {
    if (!tasks || !tasks.length) {
      els.taskTable.innerHTML = `<tr><td colspan="3" class="vt-muted">none</td></tr>`;
      return;
    }
    els.taskTable.innerHTML = tasks.map(t =>
      `<tr><td>${t.task_id}</td><td>${escapeHtml(t.name)}</td><td>${t.percent_complete ?? 0}%</td></tr>`
    ).join("");
  }

  function logMsg(who, body, cls) {
    const div = document.createElement("div");
    div.className = `vt-msg ${cls || ""}`;
    div.innerHTML = `<span class="vt-msg-who">${who}</span><span class="vt-msg-body">${escapeHtml(body)}</span>`;
    els.transcript.appendChild(div);
    els.transcript.scrollTop = els.transcript.scrollHeight;
  }

  function logSys(text) { logMsg("SYS", text, "vt-sys"); }

  function setStatus(elId, tone, text) {
    const el = document.getElementById(elId);
    el.className = `vt-pill ${tone}`;
    el.textContent = text;
  }

  function setControlsEnabled(on) {
    els.micBtn.disabled    = !on;
    els.textInput.disabled = !on;
    els.sendBtn.disabled   = !on;
  }

  function renderTurnSummary(m) {
    totals.turns += 1;
    totals.cost  += (m.llm_cost_usd || 0);
    if (m.llm_total_ms) totals.latencies.push(m.llm_total_ms + (m.tts_first_audio_ms || 0));
    renderTotals();
    setStatus("spend-pill", "ok", "$" + totals.cost.toFixed(4));

    const toolsCell = (els.kvTbody.rows[1] || {}).cells?.[1];
    const rows = els.kvTbody.rows;
    const set = (i, v) => { if (rows[i]) rows[i].cells[1].innerHTML = v; };
    set(0, escapeHtml((m.state_after || "—")));
    set(2, "$" + (m.llm_cost_usd || 0).toFixed(5));
    set(3, (m.llm_first_token_ms || 0) + " ms");
    set(4, (m.llm_total_ms || 0) + " ms");
    set(5, (m.tts_first_audio_ms || 0) + " ms");
    const ig = m.input_guard  || {};
    const og = m.output_guard || {};
    set(6, ig.passed ? "✓" : `✗ ${escapeHtml((ig.categories || []).join(","))}`);
    set(7, og.passed ? "✓" : `✗ ${escapeHtml((og.categories || []).join(","))}`);
  }

  function renderTotals() {
    els.totalsTurns.textContent = totals.turns;
    els.totalsCost.textContent  = "$" + totals.cost.toFixed(4);
    if (totals.latencies.length) {
      const sorted = [...totals.latencies].sort((a, b) => a - b);
      const p = (q) => sorted[Math.floor(sorted.length * q)] || 0;
      els.totalsP50.textContent = p(0.5) + " ms";
      els.totalsP95.textContent = p(0.95) + " ms";
    }
  }

  function playAudio(b64, mime) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const blob = new Blob([arr], { type: mime || "audio/mpeg" });
    const url = URL.createObjectURL(blob);
    els.audio.src = url;
    els.audio.play().catch(e => console.warn("audio play blocked", e));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, ch => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
  }

  // ─── Buttons ───
  els.startBtn.addEventListener("click", () => {
    const email = els.camPicker.value;
    if (!email) { logSys("⚠ select a CAM first"); return; }
    sendMsg({ type: "select_cam", email });
  });

  els.resetBtn.addEventListener("click", () => {
    sendMsg({ type: "reset" });
  });

  els.sendBtn.addEventListener("click", () => {
    const text = els.textInput.value.trim();
    if (!text) return;
    sendMsg({ type: "text", text });
    els.textInput.value = "";
  });

  els.textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") els.sendBtn.click();
  });

  // ─── Mic capture (push-to-talk) ───
  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Prefer webm/opus — small, well-supported by Whisper API
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      audioChunks = [];
      mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
      mediaRecorder.ondataavailable = (e) => { if (e.data.size) audioChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(audioChunks, { type: mime });
        const buf = await blob.arrayBuffer();
        const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
        sendMsg({ type: "audio", mime, b64 });
      };
      mediaRecorder.start();
      els.micBtn.classList.add("is-recording");
      els.micLabel.textContent = "RELEASE TO SEND";
    } catch (e) {
      logSys(`⚠ mic permission denied: ${e.message}`);
    }
  }
  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      mediaRecorder.stop();
      mediaRecorder = null;
    }
    els.micBtn.classList.remove("is-recording");
    els.micLabel.textContent = "HOLD TO TALK";
  }
  els.micBtn.addEventListener("mousedown",  startRecording);
  els.micBtn.addEventListener("mouseup",    stopRecording);
  els.micBtn.addEventListener("mouseleave", stopRecording);
  els.micBtn.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
  els.micBtn.addEventListener("touchend",   (e) => { e.preventDefault(); stopRecording(); });

  // ─── Boot ───
  connect();
})();
