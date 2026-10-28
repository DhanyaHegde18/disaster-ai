# Run it 24/7 for free (Render + UptimeRobot, no card)

| Free service | What it does here | Card? |
|---|---|---|
| **Render** (free web service) | runs the server, fixed https address, redeploys on every `git push` | no |
| **UptimeRobot** (free plan) | visits the server every 5 minutes, so Render never puts it to sleep | no |
| **Hugging Face** (free account) | a **private** dataset that keeps a copy of the database | no |

The free tiers have three weak points, and the code handles each one:

- **The disk is wiped.** A free Render server's disk is wiped on every restart, deploy or sleep. The server copies
  the database (staff, alerts, family reports, relief centres) to a private Hugging Face dataset every 5 minutes and
  when it stops, and copies it back at start-up (`backend/app/state_backup.py`).
- **It sleeps after 15 minutes without visitors.** UptimeRobot visits every 5 minutes, and a GitHub Actions job
  (`.github/workflows/keepalive.yml`) is a second backup. Render's 750 free hours a month cover one server running
  all month.
- **There's no paid SMS.** Dashboard codes go to the official's ntfy alarm topic (`SMS_PROVIDER=ntfy`).
  Villagers' codes are shown on screen.

## 1. Push the code (laptop)

The repository must be **public**, because Render's free plan builds from it. Check first that `.env` was never committed: `git log --all -- .env` must print nothing.

Pin the library versions the landslide model was trained with:

```bash
pip freeze | grep -iE "^(scikit-learn|numpy|pandas|joblib|scipy)==" >> requirements-server.txt
git add -A && git status          # .env, *.log, alerts.db must NOT be listed
git commit -m "Deploy on Render" && git push
```

## 2. Hugging Face token (for the database copy)

1. Sign up at https://huggingface.co/join (email only).
2. Profile picture → **Settings → Access Tokens → Create new token**. Choose type **Write** and copy the `hf_...` token.

The private dataset is created by the server itself; you don't need to make it.

## 3. Render

1. https://render.com → **Get Started** → sign up **with GitHub** (no card).
2. **New + → Blueprint**. Connect your GitHub, pick **disaster-ai**. Render finds `render.yaml`.
3. Render asks for the secret values:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | your new Gemini key |
| `NTFY_TOPIC_GP` / `NTFY_TOPIC_NGO` | your two ntfy topics from `.env` |
| `OFFICIALS` | one per line: `98xxxxxxxx, Ujire GP, gp, Dakshina Kannada, Belthangady` |
| `HF_TOKEN` | the `hf_...` token |
| `STATE_REPO` | `<your-hf-username>/disaster-ai-state` |
| `PUBLIC_URL` | leave empty for now (step 4) |

4. **Apply**. The first build takes 5–10 minutes. Watch **Logs**; it ends with `Uvicorn running` and
   `[staff] 1 from OFFICIALS`.
5. The address is at the top of the service page, e.g. `https://disaster-ai.onrender.com` (Render adds letters if
   the name is taken). Put it in **Environment → PUBLIC_URL** and save. This restarts the server once.

## 4. Check it

- `https://<your-address>/health` should show thresholds from IMD, the landslide model, river points,
  `sign_in: staff codes by ntfy ...` and `database_backup: every 5 min to private dataset ...`.
  If `landslide_model` says "could not be loaded here", the versions in step 1 don't match.
- `https://<your-address>/dashboard/`: enter your phone, and the code arrives in the ntfy app.
- `https://<your-address>/villager/` is the link to share with villagers. You can stop Tailscale Funnel.
- **Stop the laptop server**, so the same alarms don't come twice.
- After about 10 minutes, `https://huggingface.co/datasets/<your-hf-username>/disaster-ai-state` shows 🔒 Private
  and a file `alerts.db`.

## 5. Keep it awake

1. https://uptimerobot.com → sign up (free, no card).
2. **New monitor** → type **HTTP(s)** → URL `https://<your-address>/health` → interval **5 minutes** → **Create**.
   You also get an email if the server goes down.
3. Backup: GitHub repository → **Settings → Secrets and variables → Actions → Variables → New variable**
   `SERVER_URL` = `https://<your-address>`. Then **Actions → keep the server awake → Run workflow** once.

## Letting anyone try the dashboard (demos)

Add the variable `OPEN_SIGNIN` under **Environment**:

- `viewer` (recommended on a public site): any phone number can sign in as a **read-only guest**, with the code
  shown on screen. Guests see all of Karnataka like NGO staff, but no phone numbers, and can't approve alerts or
  change relief centres.
- `gp`: any number signs in as a Gram Panchayat guest of `OPEN_SIGNIN_TALUK` (default Belthangady). Guests **can
  approve real alerts** that villagers see and that ring the alarm topic, so use it only while presenting, then set
  it back to `viewer` or `off`.

Registered staff (`OFFICIALS`) still get their codes by ntfy.

## Updating

`git push` is all it takes: Render rebuilds and restarts automatically (**autoDeploy**), and the database comes
back from the copy. To add staff, edit `OFFICIALS` under **Environment**.

## Limits of the free setup

- A restart can lose up to the last 5 minutes of reports (`STATE_BACKUP_MIN=2` makes that smaller).
- If UptimeRobot and the GitHub job both stop, Render puts the server to sleep after 15 minutes. The next visit
  wakes it in about a minute.
- Free servers are small (512 MB memory). This app uses about 250 MB.
- Many apps share Render's internet addresses, so Open-Meteo's free limit could occasionally be reached. The
  dashboard then shows "Showing older data".
- Villager codes are shown on screen, so villagers' numbers aren't verified. GPs should call back before sending a
  rescue team.
