/* Gram Panchayat dashboard: reads /risk, /alerts and /system/scheduler from the same server. */
"use strict";

const REFRESH_MS = 60_000;
const state = { risk: null, alerts: [], tab: "pending", scheduler: null, health: null, dirty: new Set() };
let map, markers = {};

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (iso) => iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";
const fmtDay = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short" }).slice(0, 2);
const LEVEL_COLOR = () => {
  const css = getComputedStyle(document.documentElement);
  return { HIGH: css.getPropertyValue("--high").trim(), MEDIUM: css.getPropertyValue("--medium").trim(), LOW: css.getPropertyValue("--low").trim() };
};

function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), isError ? 6000 : 3000);
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = body && body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : res.statusText;
    throw new Error(detail);
  }
  return body;
}

function reviewer() {
  return $("reviewer").value.trim();
}

// Remember the reviewer's name in this browser only.
try { $("reviewer").value = localStorage.getItem("gp-reviewer") || ""; } catch { /* storage blocked */ }
$("reviewer").addEventListener("input", () => { try { localStorage.setItem("gp-reviewer", reviewer()); } catch { } });

// ---------- loading ----------
async function loadAll() {
  const [health, risk, sched, alerts] = await Promise.allSettled([
    api("/health"), api("/risk"), api("/system/scheduler"), api("/alerts"),
  ]);
  if (health.status === "fulfilled") state.health = health.value;
  if (sched.status === "fulfilled") state.scheduler = sched.value;
  if (risk.status === "fulfilled") state.risk = risk.value;
  else toast("Could not load risk: " + risk.reason.message, true);
  if (alerts.status === "fulfilled") state.alerts = alerts.value;
  render();
  checkForNewDanger();
}

// ---------- alarm: sound, desktop notification, flashing tab title ----------
const BASE_TITLE = document.title;
const alarm = {
  soundOn: false,
  audio: null,          // AudioContext, created on a click (browsers block sound before that)
  seenHigh: null,       // village ids that were HIGH at the last check (null = first load)
  seenPending: null,    // pending alert ids at the last check
  flashTimer: null,
};

try { alarm.soundOn = localStorage.getItem("gp-sound") === "on"; } catch { }

function checkForNewDanger() {
  const high = new Set((state.risk ? state.risk.villages : []).filter((v) => v.level === "HIGH").map((v) => v.village_id));
  // Test drafts are made by someone at this screen, so they don't need an alarm.
  const pending = new Set(state.alerts.filter((a) => a.status === "pending" && !a.simulated).map((a) => a.id));

  if (alarm.seenHigh === null) {          // first load: remember what's there, don't alarm
    alarm.seenHigh = high; alarm.seenPending = pending;
    if (high.size) showAlarm(describe([...high], [], true));  // still flag HIGH villages already present
    return;
  }
  const newHigh = [...high].filter((id) => !alarm.seenHigh.has(id));
  const newPending = [...pending].filter((id) => !alarm.seenPending.has(id));
  alarm.seenHigh = high; alarm.seenPending = pending;
  if (newHigh.length || newPending.length) raiseAlarm(describe(newHigh, newPending, false));
}

function villageName(id) {
  const v = (state.risk ? state.risk.villages : []).find((x) => x.village_id === id);
  return v ? v.name : id;
}

function describe(highIds, newAlertIds, already) {
  const parts = [];
  if (highIds.length) parts.push(`${already ? "" : "New "}HIGH risk: ${highIds.map(villageName).join(", ")}`);
  if (newAlertIds.length) {
    const names = newAlertIds.map((id) => (state.alerts.find((a) => a.id === id) || {}).village_name).filter(Boolean);
    parts.push(`New alert${names.length > 1 ? "s" : ""} for ${names.join(", ")} waiting for approval`);
  }
  return parts.join(" · ");
}

function raiseAlarm(message) {
  showAlarm(message);
  if (alarm.soundOn) playSiren();
  notify(message);
}

function showAlarm(message) {
  $("alarm-text").textContent = message;
  $("alarm-banner").hidden = false;
  clearInterval(alarm.flashTimer);
  let on = false;
  const short = "⚠ " + message.split(" · ")[0];
  alarm.flashTimer = setInterval(() => { document.title = (on = !on) ? short : BASE_TITLE; }, 1000);
}

function acknowledge() {
  $("alarm-banner").hidden = true;
  clearInterval(alarm.flashTimer);
  document.title = BASE_TITLE;
}

// A two-tone siren made in the browser (no sound file needed): 3 rising/falling sweeps, about 2.4 s.
function playSiren() {
  if (!alarm.audio) return;
  const ctx = alarm.audio;
  if (ctx.state === "suspended") ctx.resume();
  const t0 = ctx.currentTime + 0.05;
  const osc = ctx.createOscillator(), gain = ctx.createGain();
  osc.type = "square";
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(0.18, t0 + 0.05);
  for (let i = 0; i < 3; i++) {
    const s = t0 + i * 0.8;
    osc.frequency.setValueAtTime(650, s);
    osc.frequency.linearRampToValueAtTime(1100, s + 0.4);
    osc.frequency.linearRampToValueAtTime(650, s + 0.8);
  }
  gain.gain.setValueAtTime(0.18, t0 + 2.3);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 2.45);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t0); osc.stop(t0 + 2.5);
}

function notify(message) {
  if (!alarm.soundOn || !("Notification" in window) || Notification.permission !== "granted") return;
  const n = new Notification("Flood / landslide warning", { body: message, tag: "gp-alert", requireInteraction: true });
  n.onclick = () => { window.focus(); n.close(); };
}

function setSound(on) {
  alarm.soundOn = on;
  try { localStorage.setItem("gp-sound", on ? "on" : "off"); } catch { }
  const b = $("btn-sound");
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "Sound alerts on" : "Turn on sound alerts";
}

$("btn-sound").addEventListener("click", async () => {
  if (alarm.soundOn) { setSound(false); toast("Sound alerts off"); return; }
  // This click is what browsers require before a page may play sound.
  alarm.audio = alarm.audio || new (window.AudioContext || window.webkitAudioContext)();
  await alarm.audio.resume();
  setSound(true);
  if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
  toast(Notification.permission === "granted" ? "Sound and desktop alerts on" : "Sound alerts on (desktop notifications not allowed)");
});

$("btn-test-alarm").addEventListener("click", () => {
  if (!alarm.soundOn || !alarm.audio) { toast("Turn on sound alerts first (button at the top).", true); return; }
  raiseAlarm("TEST: this is how a new HIGH risk alarm looks and sounds");
});

$("btn-ack").addEventListener("click", acknowledge);

// After a reload the browser forgets the click, so sound needs one click again.
if (alarm.soundOn) {
  setSound(true);
  $("btn-sound").textContent = "Click to re-enable sound";
  $("btn-sound").setAttribute("aria-pressed", "false");
  alarm.soundOn = false;
}

// ---------- rendering ----------
function render() {
  renderStatus();
  renderSummary();
  renderVillages();
  renderMap();
  // Don't wipe text someone is editing during an automatic refresh.
  if (state.dirty.size === 0) renderAlerts();
  renderSystem();
}

function renderStatus() {
  const r = state.risk, s = state.scheduler;
  const parts = [];
  if (r) parts.push(`Risk data from ${fmtTime(r.generated_at)}`);
  if (s && s.enabled) parts.push(`next automatic check ${fmtTime(s.next_run_at)}`);
  if (state.health) parts.push(`alerts drafted by ${state.health.alert_drafting}`);
  $("statusline").textContent = parts.join(" · ") || "No data yet";
  const banner = $("stale-banner");
  banner.hidden = !(r && r.stale);
  if (r && r.stale) banner.textContent = `Showing older data: the forecast could not be fetched (${r.stale_reason}).`;
}

function renderSummary() {
  const sum = state.risk ? state.risk.summary : null;
  $("n-high").textContent = sum ? sum.HIGH : "–";
  $("n-medium").textContent = sum ? sum.MEDIUM : "–";
  $("n-low").textContent = sum ? sum.LOW : "–";
  $("n-pending").textContent = state.alerts.filter((a) => a.status === "pending").length;
}

function bars(daily) {
  const max = Math.max(60, ...daily.map((d) => d.rain_mm));   // 60 mm keeps small rain looking small
  return `<div class="bars" title="Rain per day (mm): solid = observed/today, striped = forecast">` +
    daily.map((d) => `<div class="bar ${d.kind}" title="${esc(d.date)}: ${d.rain_mm} mm (${d.kind})">
        <i style="height:${Math.max(2, Math.round((d.rain_mm / max) * 30))}px"></i><span>${fmtDay(d.date)}</span></div>`).join("") +
    `</div>`;
}

function renderVillages() {
  const list = $("village-list");
  const vs = state.risk ? state.risk.villages : [];
  if (!vs.length) { list.innerHTML = `<li class="empty">No villages scored yet.</li>`; return; }
  list.innerHTML = vs.map((v) => `
    <li class="village" data-id="${esc(v.village_id)}" tabindex="0">
      <span class="pill ${v.level}">${v.level}</span>
      <div>
        <div class="names"><b>${esc(v.name)}</b>${v.name_kn ? `<span class="kn" lang="kn">${esc(v.name_kn)}</span>` : ""}</div>
        <div class="meta">${esc(v.district)} · last 3 days ${v.past_3d_mm} mm · next 3 days ${v.forecast_3d_mm} mm</div>
      </div>
      ${bars(v.daily_mm || [])}
      ${v.level !== "LOW" ? `<div class="reason">${v.reasons.map(esc).join(" · ")}</div>` : ""}
    </li>`).join("");
  list.querySelectorAll(".village").forEach((li) => {
    const go = () => focusVillage(li.dataset.id);
    li.addEventListener("click", go);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });

  const sel = $("sim-village");
  const current = sel.value;
  sel.innerHTML = vs.map((v) => `<option value="${esc(v.village_id)}">${esc(v.name)}</option>`).join("");
  if (current) sel.value = current;
}

function renderMap() {
  if (typeof L === "undefined") { $("map").innerHTML = `<p class="empty">Map unavailable (no internet for map tiles).</p>`; return; }
  const order = { LOW: 0, MEDIUM: 1, HIGH: 2 };   // draw LOW first so HIGH markers end up on top
  const vs = (state.risk ? state.risk.villages : []).filter((v) => v.lat != null && v.lon != null)
    .sort((a, b) => order[a.level] - order[b.level]);
  if (!map) {
    map = L.map("map", { scrollWheelZoom: false }).setView([13.0, 75.5], 8);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 13, attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
  }
  const colors = LEVEL_COLOR();
  Object.values(markers).forEach((m) => m.remove());
  markers = {};
  vs.forEach((v) => {
    const m = L.circleMarker([v.lat, v.lon], {
      radius: v.level === "HIGH" ? 12 : v.level === "MEDIUM" ? 10 : 8,
      color: colors[v.level], fillColor: colors[v.level], fillOpacity: 0.75, weight: 2,
    }).addTo(map);
    m.bindPopup(`<b>${esc(v.name)}</b> ${v.name_kn ? `<span lang="kn">${esc(v.name_kn)}</span>` : ""}<br>
      <b style="color:${colors[v.level]}">${v.level}</b> · next 3 days ${v.forecast_3d_mm} mm<br>${v.reasons.map(esc).join("<br>")}`);
    markers[v.village_id] = m;
  });
  if (vs.length && !renderMap._fitted) {
    map.fitBounds(L.latLngBounds(vs.map((v) => [v.lat, v.lon])), { padding: [30, 30] });
    renderMap._fitted = true;
  }
}

function focusVillage(id) {
  const m = markers[id];
  if (m && map) { map.flyTo(m.getLatLng(), 10, { duration: 0.6 }); m.openPopup(); }
}

function sourceBadge(a) {
  return a.source === "gemini"
    ? `<span class="badge gemini">AI · ${esc(a.source_note)}</span>`
    : `<span class="badge">Template</span>`;
}

function renderAlerts() {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.status === state.tab));
  const counts = { pending: 0, approved: 0, rejected: 0 };
  state.alerts.forEach((a) => counts[a.status]++);
  $("tab-pending").textContent = `Pending (${counts.pending})`;
  $("tab-approved").textContent = `Approved (${counts.approved})`;
  $("tab-rejected").textContent = `Rejected (${counts.rejected})`;

  const items = state.alerts.filter((a) => a.status === state.tab);
  const list = $("alert-list");
  if (!items.length) {
    list.innerHTML = `<p class="empty">${state.tab === "pending"
      ? "No alerts waiting. When a village turns HIGH, a draft appears here for you to check."
      : `No ${state.tab} alerts yet.`}</p>`;
    return;
  }
  list.innerHTML = items.map((a) => a.status === "pending" ? pendingCard(a) : reviewedCard(a)).join("");
  list.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", onAlertAction));
  list.querySelectorAll("textarea").forEach((t) => {
    autosize(t);   // show the whole message, never a clipped last line
    t.addEventListener("input", () => {
      autosize(t);
      state.dirty.add(t.dataset.id);
      const save = list.querySelector(`[data-action="save"][data-id="${t.dataset.id}"]`);
      if (save) save.disabled = false;
    });
  });
}

function autosize(t) {
  t.style.height = "auto";
  t.style.height = t.scrollHeight + 2 + "px";
}

function cardHead(a) {
  return `<div class="alert-head">
      <b>${esc(a.village_name)}</b><span class="pill ${a.level}">${a.level}</span>
      ${sourceBadge(a)}${a.simulated ? `<span class="badge sim">Simulated</span>` : ""}${a.edited ? `<span class="badge">Edited</span>` : ""}
      <span class="when">drafted ${fmtTime(a.created_at)}</span>
    </div>
    ${a.source === "template" && a.source_note ? `<p class="why">Template used: ${esc(a.source_note)}</p>` : ""}`;
}

function pendingCard(a) {
  return `<article class="alert" data-id="${a.id}">
    ${cardHead(a)}
    <label for="kn-${a.id}">Kannada</label>
    <textarea id="kn-${a.id}" data-id="${a.id}" data-lang="kn" lang="kn" rows="4">${esc(a.message_kn)}</textarea>
    <label for="en-${a.id}">English</label>
    <textarea id="en-${a.id}" data-id="${a.id}" data-lang="en" rows="3">${esc(a.message_en)}</textarea>
    <input class="reject-note" id="note-${a.id}" type="text" placeholder="Note (required to reject, optional to approve)">
    <div class="actions">
      <button class="btn" data-action="save" data-id="${a.id}" disabled>Save edits</button>
      <button class="btn danger" data-action="reject" data-id="${a.id}">Reject</button>
      <button class="btn primary" data-action="approve" data-id="${a.id}">Approve</button>
    </div>
  </article>`;
}

function reviewedCard(a) {
  return `<article class="alert">
    ${cardHead(a)}
    <p class="text" lang="kn">${esc(a.message_kn)}</p>
    <p class="text">${esc(a.message_en)}</p>
    <p class="reviewed">${a.status === "approved" ? "Approved" : "Rejected"} by ${esc(a.reviewed_by)} on ${fmtTime(a.reviewed_at)}${a.review_note ? ` · “${esc(a.review_note)}”` : ""}</p>
  </article>`;
}

async function onAlertAction(e) {
  const btn = e.currentTarget, id = btn.dataset.id, action = btn.dataset.action;
  const note = ($(`note-${id}`) || {}).value?.trim() || null;
  try {
    if (action === "save") {
      await api(`/alerts/${id}`, { method: "PUT", body: JSON.stringify({ message_kn: $(`kn-${id}`).value, message_en: $(`en-${id}`).value }) });
      state.dirty.delete(id);
      toast("Edits saved");
    } else {
      if (reviewer().length < 2) { $("reviewer").focus(); throw new Error("Enter your name or role under “Reviewing as” first."); }
      if (action === "reject" && !note) { $(`note-${id}`).focus(); throw new Error("Add a note saying why it is rejected."); }
      if (state.dirty.has(id)) {   // save unsaved edits before approving, so what's approved is what's shown
        await api(`/alerts/${id}`, { method: "PUT", body: JSON.stringify({ message_kn: $(`kn-${id}`).value, message_en: $(`en-${id}`).value }) });
      }
      await api(`/alerts/${id}/${action}`, { method: "POST", body: JSON.stringify({ reviewed_by: reviewer(), note }) });
      state.dirty.delete(id);
      toast(action === "approve" ? "Approved. Villagers can now see this alert." : "Rejected. It will not be sent.");
    }
    state.alerts = await api("/alerts");
    renderAlerts(); renderSummary();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderSystem() {
  const s = state.scheduler || {}, h = state.health || {};
  const rows = [
    ["Automatic scoring", h.automatic_scoring || "–"],
    ["Last run", s.last_run_at ? `${fmtTime(s.last_run_at)} (${s.last_duration_s}s)` : "not yet"],
    ["Next run", s.enabled ? fmtTime(s.next_run_at) : "–"],
    ["Rule calibrated", h.calibrated_on || "–"],
  ];
  $("sysinfo").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("") +
    (s.last_error ? `<dt>Last error</dt><dd class="err">${esc(s.last_error)}</dd>` : "");
}

// ---------- controls ----------
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  if (state.dirty.size && !window.confirm("You have unsaved edits. Discard them?")) return;
  state.dirty.clear();
  state.tab = t.dataset.status;
  renderAlerts();
}));

$("btn-run-now").addEventListener("click", async (e) => {
  const b = e.currentTarget; b.disabled = true; b.textContent = "Scoring…";
  try {
    const r = await api("/system/scheduler/run-now", { method: "POST" });
    if (r.error) throw new Error(r.error);
    toast(r.summary ? `Scored: ${r.summary.HIGH} high, ${r.summary.MEDIUM} medium · ${r.alerts_created.length} alert(s) drafted` : (r.detail || "Done"));
    await loadAll();
  } catch (err) { toast("Scoring failed: " + err.message, true); }
  finally { b.disabled = false; b.textContent = "Score all villages now"; }
});

$("btn-simulate").addEventListener("click", async (e) => {
  const b = e.currentTarget, id = $("sim-village").value;
  b.disabled = true; b.textContent = "Drafting… (up to a minute)";
  try {
    const a = await api(`/alerts/draft/${id}?simulate_high=true`, { method: "POST" });
    toast(`Test alert drafted for ${a.village_name} (${a.source === "gemini" ? "AI" : "template"})`);
    state.tab = "pending";
    state.alerts = await api("/alerts");
    renderAlerts(); renderSummary();
  } catch (err) { toast("Could not draft: " + err.message, true); }
  finally { b.disabled = false; b.textContent = "Draft test alert"; }
});

loadAll();
setInterval(loadAll, REFRESH_MS);
