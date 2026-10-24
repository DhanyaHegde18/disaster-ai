/* Offline support for the villager page.
   - The page itself (HTML, CSS, JS, icons) is kept on the phone, so it opens with no network.
   - Warnings, villages and relief centres: fetched fresh when there is network, otherwise the last
     copy is shown (the page says it is offline).
   - A family report written with no network waits in the phone's storage (IndexedDB "outbox") and is
     sent when signal returns: by the page when it is open, or here in the background (Background Sync,
     Android Chrome) even if the page was closed. */
"use strict";
// Change the version when the page files change, so phones drop the old copy.
const SHELL_CACHE = "village-shell-v1";
const DATA_CACHE = "village-data-v1";
const SHELL = ["/villager/", "/villager/index.html", "/villager/villager.css", "/villager/villager.js",
               "/villager/manifest.json", "/villager/icon-192.png", "/villager/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => ![SHELL_CACHE, DATA_CACHE].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Page files: show the saved copy at once, refresh it in the background (next visit gets the new one).
async function shellFirst(req) {
  const cache = await caches.open(SHELL_CACHE);
  const key = req.mode === "navigate" ? "/villager/" : req;
  const saved = await cache.match(key, { ignoreSearch: req.mode === "navigate" });
  const fresh = fetch(req).then((res) => { if (res.ok) cache.put(key, res.clone()); return res; }).catch(() => null);
  return saved || (await fresh) || new Response("Offline", { status: 503 });
}

// Warnings and centres: try the network (fresh is what matters in an emergency), fall back to the last copy.
async function networkFirst(req) {
  const cache = await caches.open(DATA_CACHE);
  try {
    // A weak signal can hang for a minute; after 8 s show the saved copy instead.
    const res = await Promise.race([fetch(req), new Promise((_, no) => setTimeout(() => no(new Error("slow")), 8000))]);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    const saved = await cache.match(req);
    if (saved) {
      const h = new Headers(saved.headers);
      h.set("X-From-Cache", "1");
      return new Response(await saved.blob(), { status: 200, headers: h });
    }
    return new Response(JSON.stringify({ detail: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } });
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;     // reports go straight to the server
  if (url.pathname.startsWith("/villager/")) { e.respondWith(shellFirst(req)); return; }
  const publicData = ["/public/status/", "/public/shelters/", "/public/districts", "/public/villages", "/public/village/"];
  if (publicData.some((p) => url.pathname.startsWith(p))) e.respondWith(networkFirst(req));
});

// ---------- outbox (same tiny IndexedDB helper as the page) ----------
function db() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open("village-alert", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("outbox");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
async function outbox(mode, value) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction("outbox", mode === "get" ? "readonly" : "readwrite");
    const st = tx.objectStore("outbox");
    const r = mode === "get" ? st.get("report") : mode === "del" ? st.delete("report") : st.put(value, "report");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function sendSaved() {
  const item = await outbox("get");
  if (!item) return;
  const res = await fetch("/public/report", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.body) });   // network error -> sync retries
  if (res.ok || (res.status >= 400 && res.status < 500 && res.status !== 401)) {
    await outbox("del");
    const clients = await self.clients.matchAll();
    clients.forEach((c) => c.postMessage({ type: res.ok ? "outbox-sent" : "outbox-refused", status: res.status }));
  }
}

self.addEventListener("sync", (e) => { if (e.tag === "send-report") e.waitUntil(sendSaved()); });
self.addEventListener("message", (e) => { if (e.data === "send-report") e.waitUntil(sendSaved()); });
