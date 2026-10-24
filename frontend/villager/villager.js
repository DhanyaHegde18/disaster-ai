/* Villagers' warning page. Shows ONLY alerts the Gram Panchayat approved (from /public/status). */
"use strict";

const POLL_MS = 60_000;
const DEMO = new URLSearchParams(location.search).get("demo") === "true";

const T = {
  kn: {
    app: "ಊರಿನ ಎಚ್ಚರಿಕೆ",
    tagline: "ಪ್ರವಾಹ ಮತ್ತು ಭೂಕುಸಿತ ಮುನ್ನೆಚ್ಚರಿಕೆ",
    choose: "ನಿಮ್ಮ ಊರನ್ನು ಆಯ್ಕೆಮಾಡಿ",
    change: "ಊರು ಬದಲಿಸಿ",
    warnHead: "ಎಚ್ಚರಿಕೆ!",
    calmHead: "ಸದ್ಯ ಯಾವುದೇ ಎಚ್ಚರಿಕೆ ಇಲ್ಲ",
    calmText: "ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಎಚ್ಚರಿಕೆ ನೀಡಿದರೆ ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತದೆ. ಈ ಪುಟ ಪ್ರತಿ ನಿಮಿಷ ತಾನಾಗಿ ಪರಿಶೀಲಿಸುತ್ತದೆ.",
    approvedBy: (who, when) => `${who} ಅವರು ${when} ರಂದು ಅನುಮೋದಿಸಿದ್ದಾರೆ`,
    speak: "ಓದಿ ಹೇಳಿ",
    soundOff: "ಎಚ್ಚರಿಕೆ ಶಬ್ದ ಆನ್ ಮಾಡಿ",
    soundOn: "ಎಚ್ಚರಿಕೆ ಶಬ್ದ ಆನ್ ಆಗಿದೆ",
    soundAgain: "ಶಬ್ದ ಮತ್ತೆ ಆನ್ ಮಾಡಿ",
    call: "112 ಗೆ ಕರೆ ಮಾಡಿ",
    recent: "ಕಳೆದ 7 ದಿನಗಳ ಎಚ್ಚರಿಕೆಗಳು",
    tipsTitle: "ಮಳೆಗಾಲದ ಸುರಕ್ಷತಾ ಸಲಹೆಗಳು",
    tips: [
      "ನದಿ, ಹಳ್ಳ ಅಥವಾ ಸೇತುವೆಯ ಮೇಲೆ ನೀರು ಹರಿಯುತ್ತಿದ್ದರೆ ದಾಟಬೇಡಿ.",
      "ಗುಡ್ಡದಲ್ಲಿ ಬಿರುಕು, ಮಣ್ಣು ಜಾರುವುದು ಅಥವಾ ಕೆಸರು ನೀರು ಹರಿಯುವುದು ಕಂಡರೆ ತಕ್ಷಣ ಆ ಜಾಗ ಬಿಡಿ.",
      "ಮೊಬೈಲ್ ಚಾರ್ಜ್ ಮಾಡಿಟ್ಟುಕೊಳ್ಳಿ. ಟಾರ್ಚ್, ಔಷಧಿ ಮತ್ತು ಮುಖ್ಯ ದಾಖಲೆಗಳನ್ನು ಸಿದ್ಧವಾಗಿಡಿ.",
      "ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಸೂಚಿಸಿದರೆ ತಡಮಾಡದೆ ಕಾಳಜಿ ಕೇಂದ್ರಕ್ಕೆ ತೆರಳಿ.",
    ],
    onlyApproved: "ನಿಮ್ಮ ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಅನುಮೋದಿಸಿದ ಎಚ್ಚರಿಕೆಗಳು ಮಾತ್ರ ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತವೆ.",
    checked: (t) => `ಕೊನೆಯ ಪರಿಶೀಲನೆ: ${t}`,
    test: "ಪರೀಕ್ಷೆ – ನಿಜವಾದ ಎಚ್ಚರಿಕೆಯಲ್ಲ",
    demo: "ಡೆಮೊ ಮೋಡ್: ಪರೀಕ್ಷಾ ಎಚ್ಚರಿಕೆಗಳೂ ಕಾಣಿಸುತ್ತವೆ.",
    offline: "ಸಂಪರ್ಕ ಇಲ್ಲ. ಕೊನೆಯದಾಗಿ ಪಡೆದ ಮಾಹಿತಿ ತೋರಿಸಲಾಗುತ್ತಿದೆ.",
    noKnVoice: "ಈ ಫೋನಿನಲ್ಲಿ ಕನ್ನಡ ಧ್ವನಿ ಇಲ್ಲ. ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಓದಲಾಗುತ್ತಿದೆ.",
    notifTitle: "ಊರಿನ ಎಚ್ಚರಿಕೆ",
    langBtn: "English",
  },
  en: {
    app: "Village Alert",
    tagline: "Flood and landslide warnings",
    choose: "Choose your village",
    change: "Change village",
    warnHead: "Warning!",
    calmHead: "No warnings right now",
    calmText: "If your Gram Panchayat issues a warning, it will appear here. This page checks by itself every minute.",
    approvedBy: (who, when) => `Approved by ${who} on ${when}`,
    speak: "Read aloud",
    soundOff: "Turn on alarm sound",
    soundOn: "Alarm sound is on",
    soundAgain: "Turn sound on again",
    call: "Call 112",
    recent: "Warnings in the last 7 days",
    tipsTitle: "Monsoon safety tips",
    tips: [
      "Do not cross a river, stream or bridge when water is flowing over it.",
      "If you see cracks on a hillside, soil slipping or muddy water flowing, leave that place at once.",
      "Keep your phone charged. Keep a torch, medicines and important documents ready.",
      "If the Gram Panchayat asks, go to the relief centre (ಕಾಳಜಿ ಕೇಂದ್ರ) without delay.",
    ],
    onlyApproved: "Only warnings approved by your Gram Panchayat appear here.",
    checked: (t) => `Last checked: ${t}`,
    test: "TEST – not a real warning",
    demo: "Demo mode: test warnings are shown too.",
    offline: "No connection. Showing the last information received.",
    noKnVoice: "No Kannada voice on this phone. Reading in English.",
    notifTitle: "Village Alert",
    langBtn: "ಕನ್ನಡ",
  },
};

const S = {
  lang: "kn", village: null, data: null, villages: [],
  seen: null, sound: false, audio: null,
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const t = (k) => T[S.lang][k];
const fmt = (iso) => new Date(iso).toLocaleString(S.lang === "kn" ? "kn-IN" : "en-IN",
  { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function store(k, v) { try { localStorage.setItem(k, v); } catch { } }
function load(k) { try { return localStorage.getItem(k); } catch { return null; } }

function toast(msg) {
  const el = $("toast"); el.textContent = msg; el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (el.hidden = true), 4000);
}

// ---------- language ----------
function applyLang() {
  document.documentElement.lang = S.lang;
  document.title = t("app");
  document.querySelectorAll("[data-t]").forEach((el) => {
    const v = T[S.lang][el.dataset.t];
    if (typeof v === "string") el.textContent = v;
  });
  $("btn-lang").textContent = t("langBtn");
  $("tips").innerHTML = t("tips").map((x) => `<li>${esc(x)}</li>`).join("");
  setSoundButton();
  renderPicker();
  if (S.data) renderStatus();
}

$("btn-lang").addEventListener("click", () => {
  S.lang = S.lang === "kn" ? "en" : "kn";
  store("v-lang", S.lang);
  applyLang();
});

// ---------- village choice ----------
function renderPicker() {
  $("village-buttons").innerHTML = S.villages.map((v) => `
    <button type="button" data-id="${esc(v.village_id)}">
      <b>${esc(S.lang === "kn" ? (v.name_kn || v.name) : v.name)}</b>
      <span>${esc(S.lang === "kn" ? v.name : (v.name_kn || ""))} · ${esc(v.district)}</span>
    </button>`).join("");
  $("village-buttons").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => chooseVillage(b.dataset.id)));
}

function chooseVillage(id) {
  S.village = id; S.seen = null; S.data = null;
  store("v-village", id);
  showHome();
  refresh();
}

function showHome() {
  $("picker").hidden = !!S.village;
  $("home").hidden = !S.village;
}

$("btn-change").addEventListener("click", () => {
  S.village = null; store("v-village", "");
  showHome();
  window.scrollTo(0, 0);
});

// ---------- data ----------
async function refresh() {
  if (!S.village) return;
  try {
    const res = await fetch(`/public/status/${encodeURIComponent(S.village)}${DEMO ? "?demo=true" : ""}`);
    if (res.status === 404) { S.village = null; showHome(); return; }
    if (!res.ok) throw new Error(res.statusText);
    S.data = await res.json();
    store("v-last", JSON.stringify(S.data));      // shown if the network drops later
    renderStatus();
    checkNew();
  } catch {
    const cached = load("v-last");
    if (cached && !S.data) { S.data = JSON.parse(cached); renderStatus(); }
    toast(t("offline"));
  }
}

// ---------- rendering ----------
const WARN_ICON = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2 1 21h22L12 2zm0 6 .01 0c.55 0 1 .45 1 1v5a1 1 0 1 1-2 0V9c0-.55.45-1 1-1zm0 9.5a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5z"/></svg>`;

function message(a) { return S.lang === "kn" ? a.message_kn : a.message_en; }

function renderStatus() {
  const d = S.data;
  const v = d.village;
  $("place-name").textContent = S.lang === "kn" ? (v.name_kn || v.name) : v.name;
  $("call").href = `tel:${d.emergency_number || "112"}`;

  if (d.active.length) {
    $("status").innerHTML = d.active.map((a) => `
      <article class="card warn${a.test ? " test" : ""}">
        ${a.test ? `<span class="testtag">${t("test")}</span>` : ""}
        <div class="head">${WARN_ICON}<span>${t("warnHead")}</span></div>
        <p class="msg" lang="${S.lang}">${esc(message(a))}</p>
        <p class="who">${esc(t("approvedBy")(a.approved_by, fmt(a.approved_at)))}</p>
        <button class="speak" type="button" data-id="${a.id}">🔊 ${t("speak")}</button>
      </article>`).join("");
    $("status").querySelectorAll(".speak").forEach((b) =>
      b.addEventListener("click", () => speak(d.active.find((a) => String(a.id) === b.dataset.id))));
  } else {
    $("status").innerHTML = `<article class="card calm"><div class="head">${t("calmHead")}</div><p>${t("calmText")}</p></article>`;
  }

  $("recent-wrap").hidden = !d.recent.length;
  $("recent").innerHTML = d.recent.map((a) => `
    <div class="past">${a.test ? `<span class="testtag">${t("test")}</span>` : ""}
      <p lang="${S.lang}">${esc(message(a))}</p>
      <p class="when">${esc(t("approvedBy")(a.approved_by, fmt(a.approved_at)))}</p></div>`).join("");
  $("checked").textContent = t("checked")(fmt(d.checked_at));
}

// ---------- new warning: siren, vibration, notification ----------
function checkNew() {
  const ids = new Set(S.data.active.map((a) => a.id));
  if (S.seen === null) { S.seen = ids; return; }          // first load of this village: no siren
  const fresh = S.data.active.filter((a) => !S.seen.has(a.id));
  S.seen = ids;
  if (!fresh.length) return;
  if (S.sound) playSiren();
  if (navigator.vibrate) navigator.vibrate([600, 300, 600, 300, 600]);
  if (S.sound && "Notification" in window && Notification.permission === "granted") {
    new Notification(t("notifTitle"), { body: message(fresh[0]), tag: "village-alert", requireInteraction: true });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function playSiren() {
  if (!S.audio) return;
  const ctx = S.audio;
  if (ctx.state === "suspended") ctx.resume();
  const t0 = ctx.currentTime + 0.05, osc = ctx.createOscillator(), g = ctx.createGain();
  osc.type = "square";
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(0.2, t0 + 0.05);
  for (let i = 0; i < 4; i++) {
    const s = t0 + i * 0.8;
    osc.frequency.setValueAtTime(650, s);
    osc.frequency.linearRampToValueAtTime(1100, s + 0.4);
    osc.frequency.linearRampToValueAtTime(650, s + 0.8);
  }
  g.gain.setValueAtTime(0.2, t0 + 3.1);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + 3.25);
  osc.connect(g).connect(ctx.destination);
  osc.start(t0); osc.stop(t0 + 3.3);
}

function setSoundButton() {
  const b = $("btn-sound");
  b.setAttribute("aria-pressed", String(S.sound));
  b.textContent = S.sound ? t("soundOn") : (load("v-sound") === "on" ? t("soundAgain") : t("soundOff"));
}

$("btn-sound").addEventListener("click", async () => {
  if (S.sound) { S.sound = false; store("v-sound", "off"); setSoundButton(); return; }
  S.audio = S.audio || new (window.AudioContext || window.webkitAudioContext)();   // needs this tap
  await S.audio.resume();
  S.sound = true; store("v-sound", "on"); setSoundButton();
  if ("Notification" in window && Notification.permission === "default") {
    try { await Notification.requestPermission(); } catch { }
  }
});

// ---------- read aloud ----------
function speak(a) {
  if (!a || !("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const voices = speechSynthesis.getVoices();
  let text = message(a), lang = S.lang === "kn" ? "kn-IN" : "en-IN";
  let voice = voices.find((v) => v.lang.toLowerCase().startsWith(S.lang));
  if (S.lang === "kn" && !voice) {            // many phones have no Kannada voice
    toast(t("noKnVoice"));
    text = a.message_en; lang = "en-IN";
    voice = voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang.startsWith("en"));
  }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang; if (voice) u.voice = voice; u.rate = 0.9;
  speechSynthesis.speak(u);
}
if ("speechSynthesis" in window) speechSynthesis.getVoices();   // some browsers load voices lazily

// ---------- start ----------
async function start() {
  S.lang = load("v-lang") === "en" ? "en" : "kn";
  S.village = load("v-village") || null;
  $("demo-banner").hidden = !DEMO;
  try { S.villages = await (await fetch("/public/villages")).json(); } catch { S.villages = []; }
  applyLang();
  showHome();
  refresh();
  setInterval(refresh, POLL_MS);
}
start();
