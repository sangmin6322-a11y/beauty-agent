const $ = (id) => document.getElementById(id);

function bubble(text, who="bot") {
  const row = document.createElement("div");
  row.className = "row " + who;
  const b = document.createElement("div");
  b.className = "bubble " + who;
  b.textContent = text;
  row.appendChild(b);
  $("chat").appendChild(row);
  $("chat").scrollTop = $("chat").scrollHeight;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type":"application/json; charset=utf-8"},
    body: JSON.stringify(body)
  });
  const t = await r.text();
  try { return JSON.parse(t); } catch { return { error: t }; }
}

async function getJSON(url) {
  const r = await fetch(url);
  const t = await r.text();
  try { return JSON.parse(t); } catch { return { error: t }; }
}

function uid() { return $("userId").value.trim() || "test"; }

async function sendChat(text) {
  if (!text) return;
  bubble(text, "me");
  const data = await postJSON("/chat", { user_id: uid(), message: text });
  if (data.error) bubble("에러: " + data.error, "bot");
  else bubble(data.reply || "(no reply)", "bot");
}

$("send").onclick = () => { const t = $("msg").value; $("msg").value=""; sendChat(t); };
$("msg").addEventListener("keydown", (e)=>{ if(e.key==="Enter") $("send").click(); });

$("btnReset").onclick = () => sendChat("/reset");

$("btnHistory").onclick = async () => {
  const data = await getJSON(`/history?user_id=${encodeURIComponent(uid())}&limit=20`);
  bubble("— HISTORY —", "bot");
  if (Array.isArray(data)) {
    data.forEach(x => bubble(`[${x.ts}] ${x.state}\nQ: ${x.message}\nA: ${x.reply}`, "bot"));
  } else bubble(JSON.stringify(data, null, 2), "bot");
};

$("btnRadar").onclick = async () => {
  const data = await postJSON("/radar", { user_id: uid() });
  bubble("— RADAR —", "bot");
  bubble(data.reply || JSON.stringify(data, null, 2), "bot");
};

$("btnPulse").onclick = async () => {
  const data = await getJSON(`/pulse?user_id=${encodeURIComponent(uid())}&limit=50`);
  bubble("— PULSE —", "bot");
  bubble(JSON.stringify(data, null, 2), "bot");
};

$("btnAlerts").onclick = async () => {
  const data = await getJSON(`/alerts?user_id=${encodeURIComponent(uid())}&limit=50`);
  bubble("— ALERTS —", "bot");
  bubble(JSON.stringify(data, null, 2), "bot");
};

bubble("준비 완료. 메시지를 입력해봐.", "bot");
