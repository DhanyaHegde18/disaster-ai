# Landslide model report (2026-10-24)

Rows (square-days, Jun-Nov): 572,790 · years 2007-2018 · landslide square-days: 38

Each model is tested on years it never saw (leave-one-year-out).

| model | ROC-AUC | PR-AUC | caught @ 2% budget | caught @ 0.5% budget |
|---|---|---|---|---|
| logistic | 0.959 | 0.0045 | 67% (22/33) | 21% (7/33) |
| boosting (chosen) | 0.948 | 0.0053 | 61% (20/33) | 36% (12/33) |
| rule | 0.946 | 0.0029 | 61% (20/33) | 12% (4/33) |

Base rate: 0.0169% of square-days are in the 3 days before a recorded landslide.

## What the model relies on (permutation importance, drop in PR-AUC)

- slope_p90: 0.3019
- rain_max_day_next3: 0.2862
- rain_past_3d: 0.2330
- rain_next_3d: 0.2321
- rain_past_15d: 0.2097
- rain_past_7d: 0.1980
- relief: 0.1816
- steep_share: 0.1352

## Caveats

- The NASA catalog is built from news and citizen reports: remote slides are missed, so some 'no landslide' days really had one. Scores are a lower bound.
- One row per ~27 km square: the model says *where in the state* to worry, not which hillside.
- Probabilities come from class-weighted training: use them to rank days, not as true percentages.
