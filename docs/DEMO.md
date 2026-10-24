# 3-minute demo

Set up before you start: server running, Tailscale address open on the laptop (dashboard, signed in as a
Belthangady GP) and on your phone (villager page, village Ujre, signed in). ntfy app subscribed on the phone.
Sound alerts turned on in the dashboard. Have one relief centre designated near Ujire, not yet open.

| Time | Show | Say |
|---|---|---|
| 0:00 | Dashboard top: map of rain-grid squares, counts of HIGH / MEDIUM / LOW villages | "This covers all of Karnataka: 28,000 villages on IMD's rain grid. Each 27 km square is judged against its own rain history, so Agumbe and Kolar aren't held to the same number." |
| 0:25 | System box: thresholds from IMD 2015–2024, landslide model line | "On top of the rain rule there's a landslide model trained on NASA's landslide catalog, slope from a 90 m elevation map, and rain. Tested on unseen years, it warned before three times as many landslides as the rule at the strictest level." |
| 0:50 | System box → **Draft test alert** for Belthangady | "When a taluk turns HIGH, Gemini drafts a warning in Kannada and English. Every number is checked against the facts; if anything's off we fall back to a template." |
| 1:10 | Edit one word, **Approve** | "Nothing reaches villagers until a Gram Panchayat official approves it." |
| 1:20 | Phone: villager page shows the warning, siren, **ಓದಿ ಹೇಳಿ** (read aloud) | "Villagers see it in Kannada, with a siren and read-aloud for people who can't read." |
| 1:40 | Phone: nearest relief centre → **ನಕ್ಷೆಯಲ್ಲಿ ದಾರಿ ನೋಡಿ** (see route on map) | "The nearest open centre with the walking route from where they stand." (Open the centre on the dashboard first if it isn't.) |
| 2:00 | Phone: flight mode on → tick **ತುರ್ತು ರಕ್ಷಣೆ ಬೇಕು** (urgent rescue) → send → "saved on phone" | "In a flood the network goes first. The report waits on the phone…" |
| 2:15 | Flight mode off → phone rings (ntfy), dashboard siren + banner | "…and goes out the moment there's signal. Officials' phones ring even if nobody has the dashboard open, and keep ringing every 15 minutes." |
| 2:35 | Dashboard: Relief table → Ujre → family's number → **Mark handled** | "The GP calls the family, marks it handled, and the reminders stop." |
| 2:50 | Close | "Free data, free tools, runs on a laptop. Next: river levels for North Karnataka and Kannada village names." |

Backup if something fails live: `/health` shows what is configured; the 104 tests (`python -m pytest -q`) run
without network.
