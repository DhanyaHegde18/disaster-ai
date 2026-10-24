/* Gram Panchayat dashboard: reads /risk, /alerts and /system/scheduler from the same server. */
"use strict";

const REFRESH_MS = 60_000;
const state = { risk: null, alerts: [], tab: "pending", scheduler: null, health: null, dirty: new Set(),
                relief: null, expanded: new Set(), families: {}, role: null };
const NEED_LABEL = { rescue: "Rescue needed", food: "Food", water: "Drinking water", medicine: "Medicine", elderly_help: "Elderly / disabled help" };
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
  // The session cookie is sent automatically (same server); JavaScript never sees it.
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...options });
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (res.status === 401 && !path.startsWith("/auth/")) {
    showSignIn("Your session ended. Please sign in again.");
    throw new Error("Please sign in.");
  }
  if (!res.ok) {
    const detail = body && body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : res.statusText;
    throw new Error(detail);
  }
  return body;
}

// ---------- sign-in ----------
let refreshTimer = null;

function showSignIn(message) {
  state.signedIn = false;
  clearInterval(refreshTimer);
  $("app").hidden = true;
  $("top-controls").hidden = true;
  $("signin").hidden = false;
  $("form-phone").hidden = false;
  $("form-code").hidden = true;
  signinError(message || "");
  $("phone").focus();
}

function showApp(me) {
  state.signedIn = true;
  state.role = me.role;
  // body.role-gp / body.role-ngo shows or hides the parts marked gp-only / ngo-only.
  document.body.classList.toggle("role-gp", me.role === "gp");
  document.body.classList.toggle("role-ngo", me.role === "ngo");
  $("app-title").textContent = me.role === "ngo" ? "Relief Coordination" : "Gram Panchayat Control Centre";
  $("who-role").textContent = me.role === "ngo" ? "NGO" : "GP";
  if (me.role !== "gp") state.tab = "approved";       // NGOs see approved alerts only
  $("who-name").textContent = me.name;
  $("signin").hidden = true;
  $("top-controls").hidden = false;
  $("app").hidden = false;
  if (map) setTimeout(() => map.invalidateSize(), 0);   // the map was hidden while signed out
  loadAll();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(loadAll, REFRESH_MS);
}

function signinError(msg) {
  $("signin-error").textContent = msg;
  $("signin-error").hidden = !msg;
}

$("form-phone").addEventListener("submit", async (e) => {
  e.preventDefault();
  signinError("");
  const btn = $("btn-send"); btn.disabled = true;
  try {
    const r = await api("/auth/request-code", { method: "POST", body: JSON.stringify({ phone: $("phone").value }) });
    $("code-sent").textContent = `Code sent to ${r.phone}. It works for ${r.expires_in_min} minutes.`;
    $("demo-code").hidden = !r.demo_code;
    if (r.demo_code) $("demo-code").innerHTML = `Demo mode (no SMS yet): your code is <b>${esc(r.demo_code)}</b>`;
    $("form-phone").hidden = true;
    $("form-code").hidden = false;
    $("code").value = "";
    $("code").focus();
  } catch (err) { signinError(err.message); }
  finally { btn.disabled = false; }
});

$("form-code").addEventListener("submit", async (e) => {
  e.preventDefault();
  signinError("");
  const btn = $("btn-verify"); btn.disabled = true;
  try {
    const me = await api("/auth/verify", { method: "POST", body: JSON.stringify({ phone: $("phone").value, code: $("code").value }) });
    showApp(me);
    toast(`Signed in as ${me.name}`);
  } catch (err) { signinError(err.message); }
  finally { btn.disabled = false; }
});

$("btn-back").addEventListener("click", () => { $("form-code").hidden = true; $("form-phone").hidden = false; signinError(""); $("phone").focus(); });

$("btn-logout").addEventListener("click", async () => {
  try { await api("/auth/logout", { method: "POST" }); } catch { }
  acknowledge();
  alarm.seenHigh = null; alarm.seenPending = null; alarm.seenRescue = null;
  document.body.classList.remove("role-gp", "role-ngo");
  state.tab = "pending"; state.expanded.clear();
  showSignIn("Signed out.");
});

// ---------- loading ----------
async function loadAll() {
  if (!state.signedIn) return;
  const [health, risk, sched, alerts] = await Promise.allSettled([
    api("/health"), api("/risk"), api("/system/scheduler"), api("/alerts"),
  ]);
  if (health.status === "fulfilled") state.health = health.value;
  if (sched.status === "fulfilled") state.scheduler = sched.value;
  if (risk.status === "fulfilled") state.risk = risk.value;
  else toast("Could not load risk: " + risk.reason.message, true);
  if (alerts.status === "fulfilled") state.alerts = alerts.value;
  try { state.relief = await api("/relief/summary"); } catch { /* shown as empty */ }
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
  seenRescue: null,     // village id -> number of open rescue requests at the last check
  flashTimer: null,
  repeatTimer: null,    // replays the siren until someone clicks Acknowledge
};
const REPEAT_SIREN_MS = 30_000;

try { alarm.soundOn = localStorage.getItem("gp-sound") === "on"; } catch { }

function checkForNewDanger() {
  const high = new Set((state.risk ? state.risk.villages : []).filter((v) => v.level === "HIGH").map((v) => v.village_id));
  // Test drafts are made by someone at this screen, so they don't need an alarm.
  const pending = new Set(state.alerts.filter((a) => a.status === "pending" && !a.simulated).map((a) => a.id));

  const rescue = {};
  (state.relief ? state.relief.villages : []).forEach((v) => { if (v.rescue_requests) rescue[v.village_id] = v.rescue_requests; });

  if (alarm.seenHigh === null) {          // first load: remember what's there, don't alarm
    alarm.seenHigh = high; alarm.seenPending = pending; alarm.seenRescue = rescue;
    const already = [];
    if (Object.keys(rescue).length) already.push(rescueText(Object.keys(rescue)));
    if (high.size) already.push(describe([...high], [], true));
    if (already.length) showAlarm(already.join(" · "));  // still flag what's already there
    return;
  }
  const newHigh = [...high].filter((id) => !alarm.seenHigh.has(id));
  const newPending = [...pending].filter((id) => !alarm.seenPending.has(id));
  const newRescue = Object.keys(rescue).filter((id) => rescue[id] > (alarm.seenRescue[id] || 0));
  alarm.seenHigh = high; alarm.seenPending = pending; alarm.seenRescue = rescue;
  const parts = [];
  if (newRescue.length) parts.push(rescueText(newRescue));      // most urgent first
  if (newHigh.length || newPending.length) parts.push(describe(newHigh, newPending, false));
  if (parts.length) raiseAlarm(parts.join(" · "));
}

function rescueText(ids) {
  const names = ids.map((id) => (state.relief.villages.find((v) => v.village_id === id) || {}).name || id);
  return `RESCUE requested: ${names.join(", ")}`;
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
  // Like a fire alarm: keep sounding every 30 s until someone acknowledges it.
  clearInterval(alarm.repeatTimer);
  alarm.repeatTimer = setInterval(() => {
    if (alarm.soundOn && !$("alarm-banner").hidden) playSiren();
  }, REPEAT_SIREN_MS);
}

function acknowledge() {
  $("alarm-banner").hidden = true;
  clearInterval(alarm.flashTimer);
  clearInterval(alarm.repeatTimer);
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

$("btn-ack").addEventListener("click", () => { acknowledge(); toast("Acknowledged. The siren stops until something new happens."); });

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
  renderRelief();
  state.expanded.forEach((vid) => loadFamilies(vid));   // keep open family lists up to date
}

// ---------- relief: where people are (from villagers' reports) ----------
function needPills(needs) {
  // needs is {code: count} in the summary, or [codes] for one family
  const entries = Array.isArray(needs) ? needs.map((n) => [n, 0]) : Object.entries(needs);
  entries.sort((a, b) => (a[0] === "rescue" ? -1 : b[0] === "rescue" ? 1 : 0));
  return entries.map(([n, c]) => `<span class="need ${n}">${esc(NEED_LABEL[n] || n)}${c > 1 ? ` × ${c}` : ""}</span>`).join("");
}

const num = (x) => `<td class="n${x ? "" : " zero"}">${x}</td>`;

function renderRelief() {
  const r = state.relief, body = $("relief-body");
  if (!r) { body.innerHTML = `<tr><td colspan="7" class="empty">Could not load reports.</td></tr>`; return; }
  const t = r.totals;
  $("relief-totals").textContent = t.families
    ? `${t.families} famil${t.families === 1 ? "y" : "ies"} reported · ${t.at_shelter} at relief centres · ${t.unknown} unknown`
    : "No reports yet";
  $("n-rescue").textContent = t.rescue_requests;
  const gp = state.role === "gp";
  body.innerHTML = r.villages.map((v) => {
    const row = `<tr class="village-row${gp && v.families ? " clickable" : ""}${v.families ? "" : " quiet"}" data-id="${esc(v.village_id)}"
        ${gp && v.families ? `tabindex="0" aria-expanded="${state.expanded.has(v.village_id)}"` : ""}>
      <td><b>${esc(v.name)}</b>${v.name_kn ? ` <span class="kn" lang="kn">${esc(v.name_kn)}</span>` : ""}</td>
      ${num(v.families)}${num(v.at_shelter)}${num(v.with_relatives)}${num(v.at_home)}
      <td class="n${v.unknown ? " unknown-hi" : " zero"}">${v.unknown}</td>
      <td>${needPills(v.needs)}</td></tr>`;
    const fam = gp && state.expanded.has(v.village_id)
      ? `<tr class="families"><td colspan="7">${familyList(v.village_id)}</td></tr>` : "";
    return row + fam;
  }).join("");
  if (gp) body.querySelectorAll("tr.clickable").forEach((tr) => {
    const toggle = () => toggleFamilies(tr.dataset.id);
    tr.addEventListener("click", toggle);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") toggle(); });
  });
  body.querySelectorAll("[data-handle]").forEach((b) => b.addEventListener("click", () => markHandled(b)));
}

async function markHandled(btn) {
  btn.disabled = true;
  try {
    await api(`/relief/reports/${encodeURIComponent(btn.dataset.handle)}/handled`, { method: "POST" });
    toast("Marked handled. Phone reminders for this family have stopped.");
    state.relief = await api("/relief/summary");
    await loadFamilies(btn.dataset.village);
  } catch (err) { btn.disabled = false; toast(err.message, true); }
}

function familyList(vid) {
  const fams = state.families[vid];
  if (!fams) return `<ul class="family-list"><li>Loading…</li></ul>`;
  if (!fams.length) return `<ul class="family-list"><li>No reports.</li></ul>`;
  return `<ul class="family-list">` + fams.map((f) => {
    const parts = [["at relief centre", f.at_shelter], ["with relatives", f.with_relatives], ["at home", f.at_home], ["unknown", f.unknown]]
      .filter(([, n]) => n).map(([l, n]) => `${n} ${l}`).join(", ");
    const rescue = f.needs.includes("rescue");
    const status = !rescue ? "" : f.handled_at
      ? `<span class="handled">✓ Handled by ${esc(f.handled_by)}, ${fmtTime(f.handled_at)}</span>`
      : `<button class="btn handle" type="button" data-handle="${esc(f.phone)}" data-village="${esc(vid)}">Mark handled</button>`;
    return `<li><a href="tel:${esc(f.phone)}">${esc(f.phone)}</a><span>${esc(parts)}</span>${needPills(f.needs)}
      <span class="when">${fmtTime(f.reported_at)}</span>${status}</li>`;
  }).join("") + `</ul>`;
}

async function loadFamilies(vid) {
  try { state.families[vid] = (await api(`/relief/reports/${vid}`)).families; }
  catch (err) { state.families[vid] = []; toast(err.message, true); }
  renderRelief();
}

function toggleFamilies(vid) {
  if (state.expanded.has(vid)) { state.expanded.delete(vid); renderRelief(); return; }
  state.expanded.add(vid);
  renderRelief();
  loadFamilies(vid);
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

  $("alerts-title").textContent = state.role === "gp" ? "Alerts" : "Approved alerts";
  const items = state.alerts.filter((a) => a.status === state.tab);
  const list = $("alert-list");
  if (!items.length) {
    list.innerHTML = `<p class="empty">${state.tab === "pending"
      ? "No alerts waiting. When a village turns HIGH, a draft appears here for you to check."
      : state.role === "gp" ? `No ${state.tab} alerts yet.`
      : "No approved alerts yet. When the Gram Panchayat approves a warning, it appears here."}</p>`;
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
      if (action === "reject" && !note) { $(`note-${id}`).focus(); throw new Error("Add a note saying why it is rejected."); }
      if (state.dirty.has(id)) {   // save unsaved edits before approving, so what's approved is what's shown
        await api(`/alerts/${id}`, { method: "PUT", body: JSON.stringify({ message_kn: $(`kn-${id}`).value, message_en: $(`en-${id}`).value }) });
      }
      // The server records the signed-in official as the reviewer.
      await api(`/alerts/${id}/${action}`, { method: "POST", body: JSON.stringify({ note }) });
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

// Start: already signed in (cookie still valid)? Go straight to the dashboard.
(async () => {
  try { showApp(await api("/auth/me")); }
  catch { showSignIn(""); }
})();
