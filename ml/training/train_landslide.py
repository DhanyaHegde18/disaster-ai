"""
Train and test a landslide model for Karnataka, and compare it with the rain rule.

The question it answers: "Will there be a landslide in this ~27 km square in the next 3 days?"
One row per square per wet-season day (June-November), in the years the NASA catalog covers Karnataka.

  label     1 if a landslide was recorded in the square on day t+1, t+2 or t+3 (3 days of warning)
  features  rain just fallen, rain over 7 and 15 days (soaked soil), rain coming in the next 3 days,
            the wettest coming day, and how steep the square is (backend/app/services/landslide.py)

Models compared, each tested on years it never saw (leave-one-year-out):
  rule       the current rain rule: 3-day rain against the square's own HIGH thresholds (no learning)
  logistic   logistic regression on log-rain + terrain (simple, explainable)
  boosting   gradient-boosted trees (can learn "steep AND soaked AND more rain coming")
How they are judged:
  PR-AUC       how well real landslide days rank above the rest (the honest score when landslides are rare)
  caught @ x%  if we warn on the riskiest x% of square-days, what share of landslides got a warning
               in the 3 days before. Same warning budget for every model, so it's a fair fight.

The best model is retrained on all years and saved for the server, with MEDIUM/HIGH set at the riskiest
2% / 0.5% of square-days. A readable report goes to ml/reports/landslide_model.md.

Needs: ml/data/landslides_karnataka.csv (fetch_landslides.py), ml/data/cell_terrain.csv (fetch_cell_terrain.py),
       backend/app/grid_config.json (build_grid.py), IMD files in ml/data/raw/imd_grd/
Run from the project root:
    python ml/training/train_landslide.py
"""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.services import landslide  # noqa: E402

DATA = ROOT / "ml" / "data"
REPORT = ROOT / "ml" / "reports" / "landslide_model.md"
WET_MONTHS = (6, 7, 8, 9, 10, 11)
LEAD_DAYS = 3
BUDGETS = {"medium": 0.02, "high": 0.005}          # share of square-days flagged at each level
RAIN_COLS = [f for f in landslide.FEATURES if f.startswith("rain")]


# ---------- data ----------

def build_table(daily: pd.DataFrame, terrain: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Feature rows per square-day with the label (landslide in the next LEAD_DAYS days)."""
    t = landslide.table_features(daily, terrain)
    t["date"] = pd.to_datetime(t["date"])
    ev = events.assign(date=pd.to_datetime(events["date"]))
    warn_days = set()
    for e in ev.itertuples(index=False):
        for k in range(1, LEAD_DAYS + 1):
            warn_days.add((e.cell_id, e.date - pd.Timedelta(days=k)))
    t["label"] = [int((c, d) in warn_days) for c, d in zip(t["cell_id"], t["date"])]
    t = t[t["date"].dt.month.isin(WET_MONTHS)].dropna(subset=landslide.FEATURES)
    t["year"] = t["date"].dt.year
    return t.reset_index(drop=True)


# ---------- models ----------

def make_models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler

    return {
        "logistic": lambda: make_pipeline(FunctionTransformer(landslide.log_rain), StandardScaler(),
                                          LogisticRegression(class_weight="balanced", max_iter=3000, C=0.5)),
        "boosting": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250,
                                                           l2_regularization=1.0, class_weight="balanced",
                                                           random_state=0),
    }


def rule_score(t: pd.DataFrame, grid: dict) -> np.ndarray:
    """The current rain rule as a score: how far 3-day rain is past the square's HIGH thresholds (>= 1 is HIGH)."""
    cells = grid["cells"]
    past_hi = t["cell_id"].map(lambda c: cells.get(c, {}).get("past_3d", {}).get("high", np.inf))
    fc_hi = t["cell_id"].map(lambda c: cells.get(c, {}).get("forecast_3d", {}).get("high", np.inf))
    return np.maximum(t["rain_past_3d"] / past_hi, t["rain_next_3d"] / fc_hi).to_numpy()


def out_of_year_scores(t: pd.DataFrame) -> dict[str, np.ndarray]:
    """Leave-one-year-out: each year is scored by a model trained on the other years only."""
    models = make_models()
    scores = {name: np.full(len(t), np.nan) for name in models}
    for year in sorted(t["year"].unique()):
        test = t["year"] == year
        train = ~test
        if t.loc[train, "label"].sum() < 3:
            continue
        for name, build in models.items():
            m = build().fit(t.loc[train, landslide.FEATURES], t.loc[train, "label"])
            scores[name][test.to_numpy()] = m.predict_proba(t.loc[test, landslide.FEATURES])[:, 1]
    return scores


# ---------- judging ----------

def caught_at_budget(t: pd.DataFrame, score: np.ndarray, budget: float, events: list) -> tuple[float, int, int]:
    """Warn on the riskiest `budget` share of square-days. For each recorded landslide (square, day e),
    was there a warning on e-1, e-2 or e-3? Returns (share caught, caught, landslides counted)."""
    ok = ~np.isnan(score)
    thr = np.quantile(score[ok], 1 - budget)
    rows = set(zip(t.loc[ok, "cell_id"], t.loc[ok, "date"]))
    flagged = set(zip(t.loc[ok & (score >= thr), "cell_id"], t.loc[ok & (score >= thr), "date"]))
    hit = n = 0
    for cell, e in events:
        before = [(cell, e - pd.Timedelta(days=k)) for k in range(1, LEAD_DAYS + 1)]
        if not any(b in rows for b in before):
            continue                                    # this landslide's warning days aren't in the table
        n += 1
        hit += any(b in flagged for b in before)
    return (hit / n if n else float("nan")), hit, n


def judge(t: pd.DataFrame, scores: dict[str, np.ndarray], events: pd.DataFrame) -> pd.DataFrame:
    from sklearn.metrics import average_precision_score, roc_auc_score
    ev = sorted({(c, pd.Timestamp(d)) for c, d in zip(events["cell_id"], events["date"])})
    rows = []
    for name, s in scores.items():
        ok = ~np.isnan(s)
        y = t["label"].to_numpy()[ok]
        if y.sum() == 0 or y.sum() == len(y):
            continue
        r = {"model": name, "ROC-AUC": roc_auc_score(y, s[ok]), "PR-AUC": average_precision_score(y, s[ok]),
             "base rate": y.mean()}
        for level, b in BUDGETS.items():
            share, hit, n = caught_at_budget(t, s, b, ev)
            r[f"caught @ {b:.1%}"] = share
            r[f"_hits_{level}"] = f"{hit}/{n}"
        rows.append(r)
    return pd.DataFrame(rows).set_index("model")


def importance(model, t: pd.DataFrame) -> pd.Series:
    """Permutation importance: how much PR-AUC drops when a feature is shuffled."""
    from sklearn.inspection import permutation_importance
    sample = t.sample(min(len(t), 60_000), random_state=0) if len(t) > 60_000 else t
    if sample["label"].sum() < 5:
        sample = pd.concat([sample, t[t["label"] == 1]]).drop_duplicates()
    r = permutation_importance(model, sample[landslide.FEATURES], sample["label"], scoring="average_precision",
                               n_repeats=3, random_state=0)
    return pd.Series(r.importances_mean, index=landslide.FEATURES).sort_values(ascending=False)


# ---------- main ----------

def load_inputs():
    ev_file, ter_file = DATA / "landslides_karnataka.csv", DATA / "cell_terrain.csv"
    grid_file = ROOT / "backend" / "app" / "grid_config.json"
    for f, how in ((ev_file, "python ml/scripts/fetch_landslides.py"), (ter_file, "python ml/scripts/fetch_cell_terrain.py"),
                   (grid_file, "python ml/scripts/build_grid.py")):
        if not f.exists():
            raise SystemExit(f"{f.name} is missing. Run: {how}")
    events = pd.read_csv(ev_file)
    terrain = pd.read_csv(ter_file).set_index("cell_id")
    grid = json.loads(grid_file.read_text())
    spec = importlib.util.spec_from_file_location("build_grid", ROOT / "ml" / "scripts" / "build_grid.py")
    bg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bg)
    ev_years = set(pd.to_datetime(events["date"]).dt.year)
    years = [y for y in bg.available_years() if y in ev_years]
    if not years:
        raise SystemExit("No year has both IMD rain files and recorded landslides.")
    print(f"IMD years with recorded landslides: {years}")
    daily = bg.load_imd(years, set(terrain.index))
    return daily, terrain, events, grid


def train_and_save(t: pd.DataFrame, terrain: pd.DataFrame, grid: dict, events: pd.DataFrame, out_model: Path,
                   out_meta: Path, report: Path | None = REPORT) -> dict:
    scores = out_of_year_scores(t)
    scores["rule"] = rule_score(t, grid)
    table = judge(t, scores, events)
    learned = [m for m in ("logistic", "boosting") if m in table.index]
    if not learned:
        raise SystemExit("Too few landslides to test a model (need landslides in at least two years).")
    best = max(learned, key=lambda m: table.loc[m, "PR-AUC"])
    final = make_models()[best]().fit(t[landslide.FEATURES], t["label"])
    oof = scores[best][~np.isnan(scores[best])]
    thresholds = {lvl: float(np.quantile(oof, 1 - b)) for lvl, b in BUDGETS.items()}
    imp = importance(final, t)

    import joblib
    out_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, out_model)
    clean = table.drop(columns=[c for c in table.columns if c.startswith("_")])
    meta = {
        "created": str(date.today()), "model": best, "features": landslide.FEATURES, "lead_days": LEAD_DAYS,
        "thresholds": thresholds, "budgets": BUDGETS,
        "years": sorted(int(y) for y in t["year"].unique()), "rows": int(len(t)),
        "landslide_days": int(len({(c, d) for c, d in zip(events["cell_id"], events["date"])})),
        "positive_rows": int(t["label"].sum()),
        "metrics": json.loads(clean.round(4).to_json(orient="index")),
        "importance": {k: round(float(v), 4) for k, v in imp.items()},
        "terrain": {c: {k: float(terrain.loc[c, k]) for k in landslide.TERRAIN} for c in terrain.index},
    }
    out_meta.write_text(json.dumps(meta, indent=1))
    if report:
        write_report(report, meta, table, best)
    return meta


def write_report(path: Path, meta: dict, table: pd.DataFrame, best: str) -> None:
    lines = [f"# Landslide model report ({meta['created']})", "",
             f"Rows (square-days, Jun-Nov): {meta['rows']:,} · years {meta['years'][0]}-{meta['years'][-1]} · "
             f"landslide square-days: {meta['landslide_days']}", "",
             "Each model is tested on years it never saw (leave-one-year-out).", "",
             "| model | ROC-AUC | PR-AUC | caught @ 2% budget | caught @ 0.5% budget |", "|---|---|---|---|---|"]
    for m, r in table.iterrows():
        lines.append(f"| {m}{' (chosen)' if m == best else ''} | {r['ROC-AUC']:.3f} | {r['PR-AUC']:.4f} | "
                     f"{r['caught @ 2.0%']:.0%} ({r['_hits_medium']}) | {r['caught @ 0.5%']:.0%} ({r['_hits_high']}) |")
    lines += ["", f"Base rate: {table['base rate'].iloc[0]:.4%} of square-days are in the 3 days before a recorded landslide.",
              "", "## What the model relies on (permutation importance, drop in PR-AUC)", ""]
    lines += [f"- {k}: {v:.4f}" for k, v in meta["importance"].items()]
    lines += ["", "## Caveats", "",
              "- The NASA catalog is built from news and citizen reports: remote slides are missed, so some 'no landslide'"
              " days really had one. Scores are a lower bound.",
              "- One row per ~27 km square: the model says *where in the state* to worry, not which hillside.",
              "- Probabilities come from class-weighted training: use them to rank days, not as true percentages."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    daily, terrain, events, grid = load_inputs()
    t = build_table(daily, terrain, events)
    print(f"{len(t):,} square-days, {int(t['label'].sum())} in the 3 days before a landslide")
    meta = train_and_save(t, terrain, grid, events, landslide.MODEL_FILE, landslide.META_FILE)
    print("\nTested on unseen years:")
    for m, r in meta["metrics"].items():
        print(f"  {m:<9} ROC-AUC {r['ROC-AUC']:.3f}   PR-AUC {r['PR-AUC']:.4f}   "
              f"caught @2% {r['caught @ 2.0%']:.0%}   caught @0.5% {r['caught @ 0.5%']:.0%}")
    print(f"\nchosen: {meta['model']}   most important: {', '.join(list(meta['importance'])[:3])}")
    print(f"saved {landslide.MODEL_FILE.name}, {landslide.META_FILE.name} and {REPORT.relative_to(ROOT)}")
    print("Restart the server to use it.")


if __name__ == "__main__":
    main()
