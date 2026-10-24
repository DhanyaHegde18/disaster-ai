# Disaster AI: Flood & Landslide Early Warning (Karnataka)

An AI-first rebuild of the PS-11 hackathon project. A model predicts flood and
landslide risk per village a few days ahead; the app turns that into alerts,
evacuation tracking and relief coordination.

## Project layout

```
disaster-ai/
├── ml/                     # Phases 1–2: data + models
│   ├── data/
│   │   ├── villages.csv        # villages you cover (edit this)
│   │   ├── events.csv          # past floods/landslides = your labels (fill this)
│   │   ├── village_static.csv  # (later) slope, elevation, soil per village
│   │   ├── raw/                # downloaded data (git-ignored)
│   │   └── processed/          # training tables (git-ignored)
│   ├── scripts/
│   │   ├── fetch_rainfall.py   # step 1: download rainfall history
│   │   └── build_features.py   # step 2: build the training table
│   ├── notebooks/              # exploration
│   └── models/                 # saved models (git-ignored)
├── backend/                # Phase 3+: FastAPI app (coming next)
└── requirements.txt
```

## Setup (Linux Mint)

```bash
cd disaster-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Phase 1: build the dataset

1. **Edit `ml/data/villages.csv`.** The 8 starter rows are approximate town
   coordinates in Coastal/Malnad Karnataka. Check each one on a map and replace
   or add the villages you actually want to cover.

2. **Download rainfall** (free, Open-Meteo, no key):
   ```bash
   python ml/scripts/fetch_rainfall.py --start 2015-01-01 --end 2025-12-31
   ```

3. **Fill `ml/data/events.csv`** with real past events, one row per village per
   day affected:
   ```
   village_id,date,event_type
   V004,YYYY-MM-DD,landslide
   ```
   Where to find them: GSI Bhukosh landslide inventory, KSNDMC reports, district
   disaster management reports, and news archives for monsoon floods (2018, 2019
   and 2021 were severe in Kodagu and Dakshina Kannada). This is the slowest,
   most important step: the model can only learn from events you record.

4. **Build the training table:**
   ```bash
   python ml/scripts/build_features.py --horizon 3
   ```
   Each row is one village on one day. Features use only rainfall up to that day;
   `label = 1` means an event happened in the next 3 days.

### Features so far
| Feature | Meaning |
|---|---|
| `rain_1d` … `rain_30d` | Total rainfall over the last 1/3/7/14/30 days |
| `rain_max_7d` | Heaviest single day in the last week |
| `wet_streak_days` | Consecutive rainy days ending today (soil saturation proxy) |
| `month`, `is_monsoon` | Seasonality |

### Next in Phase 1
- `village_static.csv`: slope and elevation from SRTM (OpenTopography), distance
  to the nearest river, soil type. Columns: `village_id, slope_deg, elevation_m, ...`

## Things to watch
- **Class imbalance:** positives will be well under 1% of rows. Plain accuracy is
  useless here; use recall, precision and PR-AUC.
- **No time leakage:** split train/test by date (e.g. train ≤ 2022, test 2023+),
  never randomly.
- **Fallback rules:** keep simple rainfall thresholds as a backup alert path.

## State-wide version (all of Karnataka)

| Piece | Where it comes from |
|---|---|
| ~28,000 villages, 31 districts, 175 taluks | `ml/data/karnataka_villages.csv` + `karnataka_areas.json`, built by `ml/scripts/build_villages.py` from DataMeet's Census 2011 village boundaries (ODbL) |
| Risk | per IMD 0.25° rain-grid square (~310 squares); every village takes its square's level |
| Thresholds | `backend/app/grid_config.json`, built by `ml/scripts/build_grid.py` from your cached IMD files (wettest 15% / 5% of June–November days, with IMD heavy / very heavy rain floors) |
| Open-Meteo bias | `ml/scripts/fetch_grid_bias.py` (one wet season per square), then re-run `build_grid.py` |
| Alerts | one per taluk, naming its biggest villages in the wettest square |
| Relief centres | `ml/data/shelters.csv` (official lists you collect), `ml/data/shelter_candidates.csv` (schools/halls from OpenStreetMap via `ml/scripts/fetch_osm_buildings.py`, shown to villagers only once a GP designates them), or added by a GP on the map |
| Staff scope | GP officials: one taluk. NGOs: one district or the state. Phone topics follow the same areas |

Order on a new machine:

```bash
python ml/scripts/build_grid.py                 # thresholds from IMD (until then the app runs on DEMO thresholds)
python ml/scripts/fetch_grid_bias.py --year 2024 && python ml/scripts/build_grid.py   # optional but important for the ghats
python ml/scripts/fetch_osm_buildings.py        # possible relief centres
python -m backend.app.jobs.officials add 98xxxxxxxx "Name" --district "Dakshina Kannada" --taluk Belthangady
uvicorn backend.app.main:app --reload --host 0.0.0.0
```

Limits: the rain rule suits flash floods and landslides; river floods in North Karnataka driven by dam
releases upstream (Krishna, Bhima, Tungabhadra) need river-level data it doesn't have. Taluks created
after 2011 still appear under their old taluk. Village names are English only for now.
