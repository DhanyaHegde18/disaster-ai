"""
Warnings that reach villagers' phones even when the villager page is closed.

1. Web Push (free, no app to install): a villager taps "Turn on alarm" on the villager page, the browser gives us a
   push address for that phone, and when a Gram Panchayat approves a warning for their taluk the phone shows it with
   sound and long vibration. Tapping it opens the page, which plays the siren and can read the warning aloud.
   The keys that sign these messages (VAPID) are made automatically on first use and kept in the database (so the
   backup keeps them too); VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY in the settings override them.
2. ntfy (optional, loudest): if NTFY_TOPIC_PUBLIC is set, each approved warning also goes to the public topic of the
   taluk, '<NTFY_TOPIC_PUBLIC>-<taluk>', at the highest priority. Villagers who install the free ntfy app and follow
   that topic get a loud alarm. The villager page shows the topic name.

Simulated (test) warnings only go to phones that subscribed from the demo villager page (?demo=true).
"""
import base64
import json
import re

import requests

from . import areas, config, database

# ---------- keys ----------

def _meta(c, key: str) -> str | None:
    r = c.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def keys() -> tuple[str, str]:
    """(public key for the browser, private key for signing), made once and stored."""
    if config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY:
        return config.VAPID_PUBLIC_KEY, config.VAPID_PRIVATE_KEY
    with database.connect() as c:
        pub, priv = _meta(c, "vapid_public"), _meta(c, "vapid_private")
        if pub and priv:
            return pub, priv
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        pub = b64(v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        priv = b64(v.private_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        c.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('vapid_public', ?)", (pub,))
        c.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('vapid_private', ?)", (priv,))
        return pub, priv


# ---------- subscriptions ----------

def subscribe(sub: dict, village_id: str, lang: str = "kn", demo: bool = False) -> dict:
    v = areas.get().village(village_id)
    if not v:
        raise ValueError("Unknown village")
    endpoint, k = sub.get("endpoint", ""), sub.get("keys") or {}
    if not endpoint.startswith("https://") or not k.get("p256dh") or not k.get("auth"):
        raise ValueError("Not a push subscription")
    with database.connect() as c:
        c.execute("""INSERT INTO push_subscriptions (endpoint, p256dh, auth, village_id, taluk_id, lang, demo, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth,
                       village_id = excluded.village_id, taluk_id = excluded.taluk_id, lang = excluded.lang,
                       demo = excluded.demo""",
                  (endpoint, k["p256dh"], k["auth"], village_id, v["taluk_id"], "en" if lang == "en" else "kn",
                   int(demo), database.now()))
    return {"village": v["name"], "taluk_id": v["taluk_id"], "public_topic": public_topic(v["taluk_id"])}


def unsubscribe(endpoint: str) -> bool:
    with database.connect() as c:
        return bool(c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).rowcount)


def count(taluk_ids=None) -> int:
    with database.connect() as c:
        if taluk_ids is None:
            return c.execute("SELECT COUNT(*) FROM push_subscriptions WHERE demo = 0").fetchone()[0]
        ids = list(taluk_ids)
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        return c.execute(f"SELECT COUNT(*) FROM push_subscriptions WHERE demo = 0 AND taluk_id IN ({q})", ids).fetchone()[0]


def public_topic(taluk_id: str) -> str | None:
    base = config.NTFY_TOPIC_PUBLIC
    return f"{base}-{re.sub(r'[^a-z0-9]+', '-', taluk_id.lower()).strip('-')}" if base else None


# ---------- sending ----------

def _send_one(row: dict, payload: dict) -> int:
    """HTTP status from the push service (201 = delivered to it; 404/410 = this phone unsubscribed)."""
    from pywebpush import WebPushException, webpush
    _, priv = keys()
    sub = {"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}}
    try:
        r = webpush(sub, json.dumps(payload, ensure_ascii=False), vapid_private_key=priv,
                    vapid_claims={"sub": config.PUBLIC_URL or "https://github.com/DhanyaHegde18/disaster-ai"},
                    ttl=6 * 3600, headers={"Urgency": "high"}, timeout=15)
        return getattr(r, "status_code", 201)
    except WebPushException as err:
        return getattr(err.response, "status_code", 0) or 0
    except requests.RequestException:
        return 0


def alert_villagers(alert: dict) -> dict:
    """Ring every subscribed phone in the alert's taluk (and the taluk's public ntfy topic). Call after approval."""
    simulated = bool(alert.get("simulated"))
    with database.connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM push_subscriptions WHERE taluk_id = ?" + (" AND demo = 1" if simulated else ""),
            (alert["taluk_id"],))]
    sent = gone = failed = 0
    for row in rows:
        kn = row["lang"] != "en"
        payload = {"title": ("ಪರೀಕ್ಷೆ: " if simulated and kn else "TEST: " if simulated else "")
                            + ("⚠️ ಪ್ರವಾಹ / ಭೂಕುಸಿತ ಎಚ್ಚರಿಕೆ" if kn else "⚠️ Flood / landslide warning"),
                   "body": alert["message_kn"] if kn else alert["message_en"],
                   "tag": f"alert-{alert['id']}",
                   "url": f"/villager/?v={row['village_id']}&alarm={alert['id']}" + ("&demo=true" if row["demo"] else "")}
        status = _send_one(row, payload)
        if status in (200, 201, 202):
            sent += 1
            with database.connect() as c:
                c.execute("UPDATE push_subscriptions SET last_ok_at = ? WHERE endpoint = ?", (database.now(), row["endpoint"]))
        elif status in (404, 410):
            gone += 1
            unsubscribe(row["endpoint"])
        else:
            failed += 1
    ntfy = False
    topic = public_topic(alert["taluk_id"])
    if topic and not simulated:
        try:
            from .notify import ntfy_headers
            r = requests.post(f"{config.NTFY_SERVER}/{topic}", data=alert["message_kn"].encode("utf-8"), timeout=10,
                              headers=ntfy_headers({"Title": f"Warning: {alert.get('taluk_name') or ''} taluk",
                                                    "Priority": "5", "Tags": "rotating_light,warning",
                                                    "Click": f"{config.PUBLIC_URL}/villager/"}))
            ntfy = r.status_code < 300
        except requests.RequestException:
            pass
    result = {"phones": len(rows), "sent": sent, "unsubscribed": gone, "failed": failed, "ntfy_public": ntfy}
    print(f"[push] alert {alert['id']} ({alert['taluk_id']}): {result}", flush=True)
    return result
