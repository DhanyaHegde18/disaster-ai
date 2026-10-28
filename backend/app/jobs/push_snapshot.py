"""
Check the rain HERE (laptop or GitHub Actions) and send the risk map to the live server.

Use it when the forecast API refuses the server (HTTP 429: free hosts share one internet address with many other
apps, which can use up Open-Meteo's free limit). The server saves the map and drafts alerts for HIGH taluks as usual.

    SERVER_URL=https://disaster-ai-3maf.onrender.com SNAPSHOT_TOKEN=... python -m backend.app.jobs.push_snapshot

The same SNAPSHOT_TOKEN must be set on the server. .github/workflows/score.yml runs this every 3 hours.
"""
import os
import sys

import requests

from .score_grid import score_now


def main() -> int:
    url = os.getenv("SERVER_URL", "").rstrip("/")
    token = os.getenv("SNAPSHOT_TOKEN", "")
    if not url or not token:
        print("Set SERVER_URL and SNAPSHOT_TOKEN (the same token as on the server).")
        return 2
    snap = score_now()
    s = snap["summary"]
    print(f"scored {len(snap['cells'])} squares: HIGH {s['HIGH']}  MEDIUM {s['MEDIUM']}  LOW {s['LOW']}"
          + (f"  (rivers skipped: {snap['rivers_error']})" if snap.get("rivers_error") else ""))
    for attempt in range(3):                      # a sleeping free server can take a minute to wake up
        try:
            r = requests.post(f"{url}/system/snapshot", json=snap, timeout=120,
                              headers={"X-Snapshot-Token": token})
            break
        except requests.RequestException as err:
            print(f"  server not answering ({type(err).__name__}); trying again")
    else:
        return 1
    print(f"server answered {r.status_code}: {r.text[:300]}")
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
