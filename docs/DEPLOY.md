# Run it 24/7 for free (Hugging Face Spaces, no card)

A free Hugging Face Space runs the server all day with a fixed https address. Three things make the free tier
work for this project:

- **The database is backed up.** A Space's disk is wiped whenever it restarts. The server copies the database
  (staff, alerts, family reports, relief centres) to a **private** Hugging Face dataset every 5 minutes, and copies it
  back at start-up (`backend/app/state_backup.py`). At most the last 5 minutes can be lost.
- **It's kept awake.** Free Spaces sleep when nobody visits, and a sleeping Space doesn't check the rain. A GitHub
  Actions job visits it every 6 hours (`.github/workflows/keepalive.yml`).
- **Staff sign in by ntfy.** There's no paid SMS. Dashboard codes go to the ntfy alarm topic the official's phone
  already follows (`SMS_PROVIDER=ntfy`). Villagers' codes are still shown on screen.

## 1. Prepare the code (laptop)

The Space downloads the code from GitHub, so the repository must be **public** (GitHub → Settings → General →
Danger Zone → Change visibility). Check that `.env` was never committed first: `git log --all -- .env` must print nothing.

Pin the library versions the landslide model was trained with, so the server can load it:

```bash
pip freeze | grep -iE "^(scikit-learn|numpy|pandas|joblib|scipy)==" >> requirements-server.txt
git add requirements-server.txt deploy/ docs/DEPLOY.md .github/ backend/
git commit -m "Deploy to Hugging Face Spaces"
git push
```

## 2. Hugging Face account and token

1. Sign up at https://huggingface.co/join. It only needs an email address.
2. Profile picture → **Settings → Access Tokens → Create new token**. Choose type **Write** and copy the token
   (it starts with `hf_`). Treat it like a password.

## 3. Create the Space

1. https://huggingface.co/new-space. Name: `disaster-ai`. SDK: **Docker**, then **Blank**. Hardware: **CPU basic
   (free)**. Visibility: **Public** (villagers must be able to open it).
2. In the Space: **Files → Add file → Upload files**. Upload `deploy/huggingface/Dockerfile` and
   `deploy/huggingface/README.md` from your project; the README replaces the one already there. Commit.

## 4. Settings → Variables and secrets

**Secrets** (hidden):

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | your new Gemini key |
| `NTFY_TOPIC_GP` | your GP topic (the random `gp-...` name) |
| `NTFY_TOPIC_NGO` | your NGO topic |
| `HF_TOKEN` | the `hf_...` write token |
| `OFFICIALS` | one per line: `98xxxxxxxx, Ujire GP, gp, Dakshina Kannada, Belthangady` |

**Variables** (visible):

| Name | Value |
|---|---|
| `SMS_PROVIDER` | `ntfy` |
| `COOKIE_SECURE` | `true` |
| `STATE_REPO` | `<your-hf-username>/disaster-ai-state` (created automatically, private) |
| `PUBLIC_URL` | `https://<your-hf-username>-disaster-ai.hf.space` |
| `GEMINI_MODEL` | the model you use, e.g. `gemini-3.5-flash-lite` |

Saving secrets restarts the Space. The first build takes about 5 minutes (**Logs** shows progress).

## 5. Check it

- Open `https://<your-hf-username>-disaster-ai.hf.space/health`. You should see: thresholds from IMD, the landslide
  model, river points, `sign_in: staff codes by ntfy ...`, and `database_backup: every 5 min to private dataset ...`.
- Open `/dashboard/` **at that address directly**, not the Space page on huggingface.co, which shows the app in a
  frame where sign-in cookies don't work. Enter your phone number. The code arrives in the ntfy app.
- Open `/villager/` on your phone. That link is now the one to share with villagers. You can stop Tailscale Funnel.
- **Stop the laptop server** (or set `SCHEDULER_ENABLED=false` in the laptop's `.env`). Otherwise both send the
  same alarms.

## 6. Keep it awake

GitHub repository → **Settings → Secrets and variables → Actions → Variables → New variable**:
`SPACE_URL` = `https://<your-hf-username>-disaster-ai.hf.space`. Then **Actions → keep the server awake → Run
workflow** once, to check it works. GitHub pauses scheduled jobs in repositories with no activity for 60 days. A
push, or re-enabling the job, starts it again.

## Updating

After `git push`, open the Space → **Settings → Factory rebuild**. The Dockerfile downloads the newest commit. The
database comes back from the backup.

Adding staff: edit the `OFFICIALS` secret. The Space restarts and adds them (existing staff are kept).

## Limits of the free setup

- If the keep-alive stops, the Space falls asleep. The first visit wakes it, which takes about a minute.
- A restart loses at most the last 5 minutes of reports. To lower that, set `STATE_BACKUP_MIN` to `2`.
- Many apps share the Space's internet address, so Open-Meteo's free limit could occasionally be reached.
  The dashboard then shows "Showing older data" until the next successful check.
- Villager codes are shown on screen, so villagers' phone numbers aren't verified. GPs should call back before
  sending a rescue team.
