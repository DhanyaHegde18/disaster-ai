/* Relief control centre: reads /risk, /alerts, /relief, /shelters for the signed-in person's area
   (a Gram Panchayat official's taluk, an NGO's district, or the whole state). */
"use strict";

const REFRESH_MS = 60_000;
const state = { risk: null, alerts: [], tab: "pending", scheduler: null, health: null, dirty: new Set(),
                relief: null, expanded: new Set(), families: {}, role: null, me: null,
                shelters: null, candidates: null, candQuery: "", designating: null };
const NEED_LABEL = { rescue: "Rescue needed", food: "Food", water: "Drinking water", medicine: "Medicine", elderly_help: "Elderly / disabled help" };
const SHELTER_STATUS = { open: "Open", full: "Full", closed: "Not open", candidate: "Possible" };
const LEVEL_ORDER = { LOW: 0, MEDIUM: 1, HIGH: 2 };
let map, cellLayer, villageLayer, riverLayer, shelterLayer, candLayer, addMarker = null;

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
  toast._t = setTimeout(() => (t.hidden = true), isError ? 6000 : 3500);
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
  state.me = me;
  // body.role-gp / body.role-ngo shows or hides the parts marked gp-only / ngo-only.
  document.body.classList.toggle("role-gp", me.role === "gp");
  document.body.classList.toggle("role-ngo", me.role === "ngo");
  $("app-title").textContent = me.role === "ngo" ? "Relief Coordination" : "Gram Panchayat Control Centre";
  $("who-role").textContent = me.role === "ngo" ? "NGO" : "GP";
  $("who-area").textContent = me.area;
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
    $("code-sent").textContent = r.sent_by === "ntfy"
      ? `Code sent to the ntfy alarm app on your phone (your area's topic). It works for ${r.expires_in_min} minutes.`
      : `Code sent to ${r.phone}. It works for ${r.expires_in_min} minutes.`;
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
  state.tab = "pending"; state.expanded.clear(); state.candidates = null; renderMap._fitted = false;
  showSignIn("Signed out.");
});

// ---------- loading ----------
async function loadAll() {
  if (!state.signedIn) return;
  const [health, risk, sched, alerts, relief, shelters] = await Promise.allSettled([
    api("/health"), api("/risk"), api("/system/scheduler"), api("/alerts"), api("/relief/summary"), api("/shelters"),
  ]);
  if (health.status === "fulfilled") state.health = health.value;
  if (sched.status === "fulfilled") state.scheduler = sched.value;
  if (risk.status === "fulfilled") state.risk = risk.value;
  else toast("Could not load risk: " + risk.reason.message, true);
  if (alerts.status === "fulfilled") state.alerts = alerts.value;
  if (relief.status === "fulfilled") state.relief = relief.value;
  if (shelters.status === "fulfilled") state.shelters = shelters.value;
  render();
  checkForNewDanger();
}

// ---------- alarm: sound, desktop notification, flashing tab title ----------
const BASE_TITLE = document.title;
const alarm = {
  soundOn: false,
  audio: null,          // AudioContext, created on a click (browsers block sound before that)
  seenHigh: null,       // taluk ids that were HIGH at the last check (null = first load)
  seenPending: null,    // pending alert ids at the last check
  seenRescue: null,     // village id -> number of open rescue requests at the last check
  flashTimer: null,
  repeatTimer: null,    // replays the siren until someone clicks Acknowledge
};
const REPEAT_SIREN_MS = 30_000;

try { alarm.soundOn = localStorage.getItem("gp-sound") === "on"; } catch { }

function talukName(id) {
  const t = (state.risk ? state.risk.taluks : []).find((x) => x.taluk_id === id);
  return t ? t.name : id;
}

function checkForNewDanger() {
  const high = new Set((state.risk ? state.risk.taluks : []).filter((t) => t.level === "HIGH").map((t) => t.taluk_id));
  // Test drafts are made by someone at this screen, so they don't need an alarm.
  const pending = new Set(state.alerts.filter((a) => a.status === "pending" && !a.simulated).map((a) => a.id));
  const rescue = {};
  (state.relief ? state.relief.villages : []).forEach((v) => { if (v.rescue_requests) rescue[v.village_id] = v.rescue_requests; });

  if (alarm.seenHigh === null) {          // first load: remember what's there, don't sound
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

function describe(highIds, newAlertIds, already) {
  const parts = [];
  if (highIds.length) parts.push(`${already ? "" : "New "}HIGH risk: ${highIds.map(talukName).join(", ")}`);
  if (newAlertIds.length) {
    const names = newAlertIds.map((id) => (state.alerts.find((a) => a.id === id) || {}).taluk_name).filter(Boolean);
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
  toast("Notification" in window && Notification.permission === "granted" ? "Sound and desktop alerts on" : "Sound alerts on (desktop notifications not allowed)");
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
  renderArea();
  renderMap();
  // Don't wipe text someone is editing during an automatic refresh.
  if (state.dirty.size === 0) renderAlerts();
  renderSystem();
  renderRelief();
  renderShelters();
  renderShelterPins();
  state.expanded.forEach((vid) => loadFamilies(vid));   // keep open family lists up to date
}

function renderStatus() {
  const r = state.risk, s = state.scheduler;
  const parts = [];
  if (r) parts.push(`Rain checked ${fmtTime(r.generated_at)}`);
  if (r && r.rivers && r.rivers.length) {
    const rising = r.rivers.filter((p) => p.level !== "LOW").length;
    parts.push(rising ? `${rising} river point${rising > 1 ? "s" : ""} rising` : "rivers normal");
  }
  if (r && r.rivers_error) parts.push("rivers not checked (flood service unavailable)");
  if (s && s.enabled) parts.push(`next automatic check ${fmtTime(s.next_run_at)}`);
  if (state.health) parts.push(`alerts drafted by ${state.health.alert_drafting}`);
  $("statusline").textContent = parts.join(" · ") || "No data yet";
  $("demo-banner").hidden = !(r && r.demo_thresholds);
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

// One taluk: list its rain-grid squares (and every village below). Several taluks: one row per taluk.
function renderArea() {
  const r = state.risk, list = $("area-list");
  if (!r) { list.innerHTML = `<li class="empty">No risk data yet.</li>`; return; }
  const oneTaluk = !!r.villages;
  $("villages-title").textContent = r.area;
  $("area-note").textContent = oneTaluk
    ? "Risk is worked out for each rain-grid square (about 27 km wide); every village in a square shares its level."
    : "Most urgent first. Click a taluk to see it on the map.";
  if (oneTaluk) {
    list.innerHTML = r.cells.map((c) => `
      <li class="village" data-lat="${c.lat}" data-lon="${c.lon}" tabindex="0">
        <span class="pill ${c.level}">${c.level}</span>
        <div>
          <div class="names"><b>Around ${esc(c.places.join(", ") || "–")}</b></div>
          <div class="meta">${c.villages} village${c.villages === 1 ? "" : "s"} · last 3 days ${c.past_3d_mm} mm · next 3 days ${c.forecast_3d_mm} mm</div>
        </div>
        ${bars(c.daily_mm || [])}
        ${c.level !== "LOW" ? `<div class="reason">${c.reasons.map(esc).join(" · ")}</div>` : ""}
      </li>`).join("");
  } else {
    list.innerHTML = r.taluks.map((t) => {
      const cells = r.cells.filter((c) => t.cells_at_risk.includes(c.cell_id) || c.cell_id === t.worst_cell);
      const c0 = cells[0] || {};
      return `<li class="village" data-lat="${c0.lat || ""}" data-lon="${c0.lon || ""}" tabindex="0">
        <span class="pill ${t.level}">${t.level}</span>
        <div>
          <div class="names"><b>${esc(t.name)}</b>${t.name_kn ? ` <span class="kn" lang="kn">${esc(t.name_kn)}</span>` : ""}<span class="kn">${esc(t.district)}</span></div>
          <div class="meta">${t.villages_at_risk} of ${t.villages_total} villages at risk · last 3 days ${t.past_3d_mm} mm · next 3 days ${t.forecast_3d_mm} mm</div>
        </div>
        ${bars(t.daily_mm || [])}
        ${t.level !== "LOW" ? `<div class="reason">${t.places.length ? `Around ${esc(t.places.join(", "))}: ` : ""}${t.reasons.map(esc).join(" · ")}</div>` : ""}
      </li>`;
    }).join("");
  }
  list.querySelectorAll(".village").forEach((li) => {
    const go = () => { if (li.dataset.lat && map) map.flyTo([+li.dataset.lat, +li.dataset.lon], oneTaluk ? 11 : 10, { duration: 0.6 }); };
    li.addEventListener("click", go);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });

  $("all-villages").hidden = !oneTaluk;
  if (oneTaluk) {
    $("village-count").textContent = r.villages.length;
    renderVillageList();
  }
  const sel = $("sim-taluk"), current = sel.value;
  sel.innerHTML = r.taluks.map((t) => `<option value="${esc(t.taluk_id)}">${esc(t.name)}${r.taluks.length > 1 ? ` (${esc(t.district)})` : ""}</option>`).join("");
  if (current) sel.value = current;
}

// Kannada name next to the census name; AI-suggested spellings are marked until someone checks them
function knName(v) {
  if (!v.name_kn) return "";
  const ai = (v.name_kn_source || "").startsWith("ai");      // "ai", or "ai-local" (spelled with local examples)
  return ` <span class="kn" lang="kn"${ai ? ' title="Kannada spelling suggested by AI and checked only automatically. Wrong? Add the right one to ml/data/name_kn_fixes.csv"' : ""}>${esc(v.name_kn)}${ai ? " <small>(AI)</small>" : ""}</span>`;
}

function renderVillageList() {
  const q = $("village-filter").value.trim().toLowerCase();
  const vs = (state.risk.villages || []).filter((v) => !q || v.name.toLowerCase().includes(q) || (v.name_kn || "").includes(q));
  $("village-list").innerHTML = vs.slice(0, 400).map((v) =>
    `<li><span class="pill ${v.level}">${v.level}</span> <button class="link-btn" type="button" data-lat="${v.lat}" data-lon="${v.lon}">${esc(v.name)}</button>${knName(v)}
      <span class="meta">${v.population.toLocaleString("en-IN")} people</span></li>`).join("") || `<li class="empty">No village matches.</li>`;
  $("village-list").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    if (map) map.flyTo([+b.dataset.lat, +b.dataset.lon], 13, { duration: 0.6 });
  }));
}
$("village-filter").addEventListener("input", renderVillageList);

function renderMap() {
  if (typeof L === "undefined") { $("map").innerHTML = `<p class="empty">Map unavailable (no internet for map tiles).</p>`; return; }
  const r = state.risk;
  if (!map) {
    map = L.map("map", { scrollWheelZoom: false }).setView([14.5, 76.0], 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 17, attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    // featureGroups pass their layers' clicks on, so "add a centre" also works when the click lands on a
    // rain square or a village dot (Leaflet stops a click on a layer with a popup from reaching the map).
    cellLayer = L.featureGroup().addTo(map).on("click", onMapClick);
    villageLayer = L.featureGroup().addTo(map).on("click", onMapClick);
    riverLayer = L.featureGroup().addTo(map);
    map.on("click", onMapClick);
  }
  if (!r) return;
  const colors = LEVEL_COLOR();
  cellLayer.clearLayers();
  // Each rain-grid square is 0.25 degrees: draw it as a coloured square.
  [...r.cells].sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]).forEach((c) => {
    const h = 0.125;
    L.rectangle([[c.lat - h, c.lon - h], [c.lat + h, c.lon + h]], {
      color: colors[c.level], weight: c.level === "LOW" ? 1 : 2, fillColor: colors[c.level],
      fillOpacity: c.level === "HIGH" ? 0.35 : c.level === "MEDIUM" ? 0.25 : 0.08, interactive: true,
    }).bindPopup(`<b style="color:${colors[c.level]}">${c.level}</b> · ${c.villages} villages<br>Around ${esc(c.places.join(", "))}<br>` +
                 `${c.reasons.map(esc).join("<br>")}`).addTo(cellLayer);
  });
  villageLayer.clearLayers();
  (r.villages || []).forEach((v) => {
    L.circleMarker([v.lat, v.lon], { radius: 3, color: colors[v.level], fillColor: colors[v.level], fillOpacity: 0.9, weight: 1 })
      .bindTooltip(`${v.name} · ${v.level}`).addTo(villageLayer);
  });
  // River points (GloFAS forecast vs that point's own flood levels): a wave pin coloured by level
  riverLayer.clearLayers();
  const fmt = (x) => Math.round(x).toLocaleString("en-IN");
  (r.rivers || []).forEach((p) => {
    L.marker([p.lat, p.lon], {
      icon: L.divIcon({ className: `river-pin ${p.level}`, html: "≈", iconSize: [22, 22] }),
      title: `${p.river} at ${p.place}: ${p.level}`, zIndexOffset: 500,
    }).bindPopup(`<b>${esc(p.river)} river at ${esc(p.place)}</b> · <b style="color:${colors[p.level]}">${p.level}</b><br>` +
                 `Highest in the next days: ${fmt(p.peak_m3s)} m³/s on ${esc(p.peak_day)}<br>` +
                 `Flood levels here: ${fmt(p.medium_m3s)} m³/s (about every 2nd year), ${fmt(p.high_m3s)} m³/s (about every 5th year)<br>` +
                 `<span class="meta">Warns ${p.villages} villages within ${p.radius_km} km · GloFAS model, check with CWC / dam releases</span>`)
      .addTo(riverLayer);
  });
  if (r.cells.length && !renderMap._fitted) {
    map.fitBounds(L.latLngBounds(r.cells.map((c) => [[c.lat - 0.125, c.lon - 0.125], [c.lat + 0.125, c.lon + 0.125]]).flat()), { padding: [10, 10] });
    renderMap._fitted = true;
  }
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
  if (!r.villages.length) { body.innerHTML = `<tr><td colspan="7" class="empty">No family has reported in the last 3 days.</td></tr>`; return; }
  body.innerHTML = r.villages.map((v) => {
    const row = `<tr class="village-row${gp ? " clickable" : ""}" data-id="${esc(v.village_id)}"
        ${gp ? `tabindex="0" aria-expanded="${state.expanded.has(v.village_id)}"` : ""}>
      <td><b>${esc(v.name)}</b> <span class="kn">${esc(v.taluk)}</span></td>
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
  body.querySelectorAll("[data-handle]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); markHandled(b); }));
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
      <span class="when">${f.queued_at ? `written ${fmtTime(f.queued_at)} with no network, arrived ${fmtTime(f.reported_at)}`
                                        : fmtTime(f.reported_at)}</span>${status}</li>`;
  }).join("") + `</ul>`;
}

async function loadFamilies(vid) {
  try { state.families[vid] = (await api(`/relief/reports/${encodeURIComponent(vid)}`)).families; }
  catch (err) { state.families[vid] = []; toast(err.message, true); }
  renderRelief();
}

function toggleFamilies(vid) {
  if (state.expanded.has(vid)) { state.expanded.delete(vid); renderRelief(); return; }
  state.expanded.add(vid);
  renderRelief();
  loadFamilies(vid);
}

// ---------- relief centres ----------
const typing = (el) => el.contains(document.activeElement) && document.activeElement.tagName === "INPUT";

function renderShelters() {
  const box = $("shelter-list"), d = state.shelters;
  if (typing(box)) return;     // don't redraw while someone types a head count (the 60 s refresh would wipe it)
  if (!d) { box.innerHTML = `<p class="empty">Could not load relief centres.</p>`; return; }
  const t = d.totals;
  $("shelter-totals").textContent = t.centres
    ? `${t.open} of ${t.centres} open · ${t.people} people in ${t.places} places${t.full ? ` · ${t.full} full` : ""}`
    : "No relief centres yet";
  if (t.candidates != null) $("cand-count").textContent = t.candidates;
  const gp = state.role === "gp";
  box.innerHTML = d.taluks.map((g) => {
    const inside = g.shelters.reduce((n, s) => n + (s.is_open ? s.occupancy : 0), 0);
    const mismatch = g.reported_at_shelter > inside;
    return `<div class="shelter-village">
      <div class="sv-head"><b>${esc(g.name)}</b> <span class="kn">${esc(g.district)}</span>
        <span class="sv-say${mismatch ? " warn" : ""}" title="From families' own reports in the last 3 days">
          Families say ${g.reported_at_shelter} at a centre${mismatch ? ` · counted ${inside}` : ""}</span></div>
      ${g.shelters.length ? `<ul>${g.shelters.map((s) => shelterRow(s, gp)).join("")}</ul>`
        : `<p class="fine sv-empty">No relief centres yet.${gp ? " Mark a school or hall below, or add one on the map." : ""}</p>`}</div>`;
  }).join("") || `<p class="empty">No relief centres in your area yet.</p>`;
  box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => {
    const opening = b.dataset.open === "1";
    const s = d.taluks.flatMap((g) => g.shelters).find((x) => x.shelter_id === b.dataset.id);
    if (!opening && s && s.occupancy > 0 &&
        !window.confirm(`${s.occupancy} people are recorded inside ${s.name}. Close it and set the count to 0?`)) return;
    saveShelter(b, { is_open: opening });
  }));
  box.querySelectorAll("form.occ").forEach((f) => f.addEventListener("submit", (e) => {
    e.preventDefault();
    const n = Number(f.elements.n.value);
    if (!Number.isInteger(n) || n < 0 || n > 5000) { toast("Enter a whole number of people (0–5000).", true); return; }
    saveShelter(f.querySelector("button"), { occupancy: n });
  }));
  box.querySelectorAll("[data-unmark]").forEach((b) => b.addEventListener("click", () => {
    if (window.confirm("Stop using this building as a relief centre? Villagers will no longer see it.")) saveShelter(b, { designated: false });
  }));
}

function shelterRow(s, gp) {
  const pct = s.capacity ? Math.min(100, Math.round((s.occupancy / s.capacity) * 100)) : 0;
  const fill = s.status === "full" ? "full" : pct >= 90 ? "near" : "";
  const people = s.is_open
    ? `<div class="occ-bar" title="${s.occupancy} of ${s.capacity} places"><i class="${fill}" style="width:${pct}%"></i></div>
       <span class="occ-num">${s.occupancy} / ${s.capacity}</span>`
    : `<span class="occ-num muted">${s.capacity} places</span>`;
  const id = esc(s.shelter_id);
  const controls = !gp ? "" : s.is_open
    ? `<form class="occ"><label class="sr-only" for="occ-${id}">People inside ${esc(s.name)}</label>
         <input id="occ-${id}" name="n" type="number" inputmode="numeric" min="0" max="5000" value="${s.occupancy}">
         <button class="btn" type="submit" data-id="${id}">Update</button></form>
       <button class="btn" type="button" data-open="0" data-id="${id}">Close</button>`
    : `<button class="btn primary" type="button" data-open="1" data-id="${id}">Open centre</button>
       ${s.source === "osm" ? `<button class="link-btn" type="button" data-unmark="1" data-id="${id}">Un-mark</button>` : ""}`;
  const source = s.source === "official" ? "official list" : s.source === "gp" ? `added by ${esc(s.added_by || "GP")}` : "from OpenStreetMap";
  return `<li class="shelter">
    <div class="sh-name"><b>${esc(s.name)}</b>${s.name_kn ? ` <span class="kn" lang="kn">${esc(s.name_kn)}</span>` : ""}
      <span class="when">${source} · ${s.updated_at ? `updated ${fmtTime(s.updated_at)} by ${esc(s.updated_by)}` : "not opened yet"}${s.phone ? ` · <a href="tel:${esc(s.phone)}">${esc(s.phone)}</a>` : ""}</span></div>
    <span class="pill sh-${s.status}">${SHELTER_STATUS[s.status]}</span>
    <div class="sh-people">${people}</div>
    <div class="sh-ctl">${controls}</div>
  </li>`;
}

async function saveShelter(btn, body) {
  btn.disabled = true;
  try {
    const s = await api(`/shelters/${encodeURIComponent(btn.dataset.id)}`, { method: "PATCH", body: JSON.stringify(body) });
    toast(body.designated === true ? `${s.name} is now a relief centre. Villagers nearby can see it.`
      : body.designated === false ? `${s.name} is no longer a relief centre.`
      : body.is_open === true ? `${s.name} is open. Staff phones have been told.`
      : body.is_open === false ? `${s.name} closed.` : `${s.name}: ${s.occupancy} of ${s.capacity} places used.`);
    if (document.activeElement) document.activeElement.blur();
    state.shelters = await api("/shelters");
    if (body.designated !== undefined) await loadCandidates();
    renderShelters(); renderShelterPins();
  } catch (err) { btn.disabled = false; toast(err.message, true); }
}

// Possible centres (OpenStreetMap), loaded when the GP opens the list.
async function loadCandidates() {
  try { state.candidates = await api(`/shelters/candidates?limit=800${state.candQuery ? `&q=${encodeURIComponent(state.candQuery)}` : ""}`); }
  catch (err) { state.candidates = []; toast(err.message, true); }
  renderCandidates(); renderShelterPins();
}

function renderCandidates() {
  const list = $("cand-list"), cs = state.candidates || [];
  if (typing(list)) return;
  if (!state.candidates) { list.innerHTML = `<li class="empty">Loading…</li>`; return; }
  if (!cs.length) {
    list.innerHTML = `<li class="empty">${state.candQuery ? "No building matches." :
      "None loaded. Run python ml/scripts/fetch_osm_buildings.py on the server and restart it."}</li>`;
    return;
  }
  list.innerHTML = cs.slice(0, 300).map((c) => {
    const id = esc(c.shelter_id);
    const form = state.designating === c.shelter_id
      ? `<form class="designate" data-id="${id}"><label class="sr-only" for="cap-${id}">People it can hold</label>
           <input id="cap-${id}" name="cap" type="number" min="1" max="5000" placeholder="People it can hold" required>
           <button class="btn primary" type="submit" data-id="${id}">Save</button>
           <button class="btn" type="button" data-cancel="1">Cancel</button></form>`
      : `<button class="btn" type="button" data-designate="${id}">Mark as relief centre</button>`;
    return `<li><div><b>${esc(c.name)}</b>${c.name_kn ? ` <span class="kn" lang="kn">${esc(c.name_kn)}</span>` : ""}
      <span class="meta">${esc(c.kind || "")}</span>
      <button class="link-btn" type="button" data-show="${c.lat},${c.lon}">show on map</button></div>${form}</li>`;
  }).join("") + (cs.length > 300 ? `<li class="empty">${cs.length - 300} more: search by name to narrow down.</li>` : "");
  list.querySelectorAll("[data-designate]").forEach((b) => b.addEventListener("click", () => {
    state.designating = b.dataset.designate; renderCandidates();
    const inp = list.querySelector("form.designate input"); if (inp) inp.focus();
  }));
  list.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", () => { state.designating = null; renderCandidates(); }));
  list.querySelectorAll("form.designate").forEach((f) => f.addEventListener("submit", (e) => {
    e.preventDefault();
    const cap = Number(f.elements.cap.value);
    if (!Number.isInteger(cap) || cap < 1 || cap > 5000) { toast("Enter how many people it can hold (1–5000).", true); return; }
    state.designating = null;
    saveShelter(f.querySelector("button[type=submit]"), { designated: true, capacity: cap });
  }));
  list.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => {
    const [lat, lon] = b.dataset.show.split(",").map(Number);
    if (map) { map.flyTo([lat, lon], 15, { duration: 0.6 }); $("map").scrollIntoView({ behavior: "smooth", block: "center" }); }
  }));
}

$("candidates").addEventListener("toggle", () => { if ($("candidates").open && !state.candidates) loadCandidates(); });
let candTimer = null;
$("cand-filter").addEventListener("input", () => {
  clearTimeout(candTimer);
  candTimer = setTimeout(() => { state.candQuery = $("cand-filter").value.trim(); loadCandidates(); }, 300);
});

const SHELTER_ZOOM = 11;   // centre pins only once zoomed in, so they don't hide the risk squares

function renderShelterPins() {
  if (!map || typeof L === "undefined" || !state.shelters) return;
  if (!shelterLayer) {
    shelterLayer = L.layerGroup();
    candLayer = L.layerGroup();
    const toggle = () => {
      map.getZoom() >= SHELTER_ZOOM ? shelterLayer.addTo(map) : shelterLayer.remove();
      map.getZoom() >= 13 ? candLayer.addTo(map) : candLayer.remove();
    };
    map.on("zoomend", toggle);
    toggle();
  }
  shelterLayer.clearLayers();
  state.shelters.taluks.forEach((g) => g.shelters.forEach((s) => {
    const icon = L.divIcon({ className: "", html: `<span class="sq ${s.status}"></span>`, iconSize: [14, 14], iconAnchor: [7, 7] });
    L.marker([s.lat, s.lon], { icon, title: s.name }).addTo(shelterLayer)
      .bindPopup(`<b>${esc(s.name)}</b><br>${SHELTER_STATUS[s.status]}` +
        (s.is_open ? ` · ${s.occupancy} / ${s.capacity} people` : ` · ${s.capacity} places`));
  }));
  candLayer.clearLayers();
  (state.candidates || []).forEach((c) => {
    const icon = L.divIcon({ className: "", html: `<span class="sq candidate"></span>`, iconSize: [12, 12], iconAnchor: [6, 6] });
    L.marker([c.lat, c.lon], { icon, title: c.name }).addTo(candLayer)
      .bindPopup(`<b>${esc(c.name)}</b><br>Possible centre (${esc(c.kind || "")}), not designated`);
  });
}

// Add a centre by clicking the map (Gram Panchayat only).
const adding = { on: false, lat: null, lon: null };

$("btn-add-centre").addEventListener("click", () => {
  adding.on = !adding.on;
  $("map-add").hidden = !adding.on;
  $("add-form").hidden = true;
  $("map-add-hint").textContent = "Click the map where the new relief centre is. Zoom in first to place it exactly.";
  $("btn-add-centre").textContent = adding.on ? "Cancel adding" : "Add a centre on the map";
  $("map").classList.toggle("adding", adding.on);
  if (adding.on) $("map").scrollIntoView({ behavior: "smooth", block: "center" });
  else if (addMarker) { addMarker.remove(); addMarker = null; }
});
$("add-cancel").addEventListener("click", () => $("btn-add-centre").click());

function onMapClick(e) {
  if (!adding.on) return;
  setTimeout(() => map.closePopup(), 0);      // a click on a rain square shouldn't pop up while placing a centre
  adding.lat = +e.latlng.lat.toFixed(6); adding.lon = +e.latlng.lng.toFixed(6);
  if (addMarker) addMarker.remove();
  addMarker = L.marker([adding.lat, adding.lon]).addTo(map);
  $("map-add-hint").textContent = `Point chosen (${adding.lat.toFixed(4)}, ${adding.lon.toFixed(4)}). Click again to move it.`;
  $("add-form").hidden = false;
  $("add-name").focus();
}

$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("add-name").value.trim(), cap = Number($("add-cap").value);
  if (name.length < 2) { toast("Give the centre a name.", true); return; }
  if (!Number.isInteger(cap) || cap < 1 || cap > 5000) { toast("Enter how many people it can hold (1–5000).", true); return; }
  try {
    const s = await api("/shelters", { method: "POST", body: JSON.stringify({ name, lat: adding.lat, lon: adding.lon, capacity: cap }) });
    toast(`${s.name} added. Villagers nearby can see it; open it when needed.`);
    $("add-name").value = ""; $("add-cap").value = "";
    $("btn-add-centre").click();
    state.shelters = await api("/shelters");
    renderShelters(); renderShelterPins();
  } catch (err) { toast(err.message, true); }
});

// ---------- alerts ----------
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
      ? "No alerts waiting. When a taluk turns HIGH, a draft appears here for you to check."
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
  const r = a.risk || {};
  return `<div class="alert-head">
      <b>${esc(a.taluk_name)} taluk</b><span class="pill ${a.level}">${a.level}</span>
      ${sourceBadge(a)}${a.simulated ? `<span class="badge sim">Simulated</span>` : ""}${a.edited ? `<span class="badge">Edited</span>` : ""}
      <span class="when">drafted ${fmtTime(a.created_at)}</span>
    </div>
    ${r.villages_at_risk != null ? `<p class="why">${r.villages_at_risk} of ${r.villages_total} villages at risk${r.places && r.places.length ? `, around ${esc(r.places.join(", "))}` : ""}.</p>` : ""}
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
      toast(action === "approve" ? "Approved. Villagers in this taluk can now see this alert." : "Rejected. It will not be sent.");
    }
    state.alerts = await api("/alerts");
    renderAlerts(); renderSummary();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderSystem() {
  const s = state.scheduler || {}, h = state.health || {}, me = state.me || {};
  const rows = [
    ["Your area", me.area || "–"],
    ["Phone alerts", me.alert_topic ? `subscribe to “${me.alert_topic}” in the ntfy app` : "off (no ntfy topic set on the server)"],
    ["Automatic checks", h.automatic_scoring || "–"],
    ["Last run", s.last_run_at ? `${fmtTime(s.last_run_at)} (${s.last_duration_s}s)` : "not yet"],
    ["Next run", s.enabled ? fmtTime(s.next_run_at) : "–"],
    ["Thresholds", h.thresholds || "–"],
    ["Landslide model", h.landslide_model || "–"],
    ["Rivers", h.rivers || "–"],
    ["Coverage", h.coverage || "–"],
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
  const b = e.currentTarget; b.disabled = true; b.textContent = "Checking…";
  try {
    const r = await api("/system/scheduler/run-now", { method: "POST" });
    if (r.error) throw new Error(r.error);
    toast(r.summary ? `Checked: ${r.summary.HIGH} HIGH and ${r.summary.MEDIUM} MEDIUM squares in Karnataka · ${r.alerts_created.length} alert(s) drafted` : (r.detail || "Done"));
    await loadAll();
  } catch (err) { toast("Check failed: " + err.message, true); }
  finally { b.disabled = false; b.textContent = "Check the rain now"; }
});

$("btn-simulate").addEventListener("click", async (e) => {
  const b = e.currentTarget, id = $("sim-taluk").value;
  if (!id) return;
  b.disabled = true; b.textContent = "Drafting… (up to a minute)";
  try {
    const a = await api(`/alerts/draft/${encodeURIComponent(id)}?simulate_high=true`, { method: "POST" });
    toast(`Test alert drafted for ${a.taluk_name} (${a.source === "gemini" ? "AI" : "template"})`);
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
