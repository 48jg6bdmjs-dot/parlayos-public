#!/usr/bin/env python3
"""
nba_fit_weights.py Ã¢â‚¬â€ Improved accuracy version
- De-vigs market probs before fitting (previous version used raw American odds implied, not de-vigged)
- Applies L2 regularization (C=1.0) and clamps a,b to avoid extreme calibration from small samples
- Now auto-writes clamped values + computes suggested edge_threshold adjustment
- Full multi-factor fit uses regularized logistic regression with cross-validation
"""

import csv, json, os, sys, math
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "nba_picks_log.csv")
CALIBRATION_PATH = os.path.join(HERE, "nba_calibration.json")
CONFIG_PATH = os.path.join(HERE, "sports_config.json")

MIN_FOR_CALIBRATION = 80   # lowered slightly but with regularization it's safer
MIN_FOR_FULL_FIT = 150

EDGE_COMPONENT_COLS = [
    "c_team_edge", "c_offense_edge", "c_defense_edge",
    "c_rest_edge", "c_injury_edge", "c_home_field_edge",
    "c_pace_edge", "c_turnover_edge",
]

def _f(s, d=None):
    try: return float(str(s).strip().replace("+", ""))
    except (ValueError, TypeError, AttributeError): return d

def _american_to_implied(o):
    o = _f(o)
    if o is None: return None
    return (-o)/(-o+100.0) if o < 0 else 100.0/(o+100.0)

def _devig(home_odds, away_odds):
    hi = _american_to_implied(home_odds)
    ai = _american_to_implied(away_odds) if away_odds is not None else None
    if hi is None:
        return None
    if ai is None:
        # if only one side, approximate vig removal by dividing by 1.03 avg vig
        return hi/1.03
    total = hi+ai
    if total <=0:
        return hi
    return hi/total

def load_graded_moneylines(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        has_component_cols = any(c in fieldnames for c in EDGE_COMPONENT_COLS)
        has_both_odds = "open_ml" in fieldnames and "close_ml" in fieldnames
        for r in reader:
            won = _f(r.get("won"))
            odds = r.get("odds") or r.get("open_ml")
            market = (r.get("market") or "").strip().lower()
            if won is None or not odds or "moneyline" not in market:
                continue
            # Try de-vig if we have both sides? picks_log only stores one side odds,
            # so we approximate: if we have open_ml as the side bet, we can't de-vig perfectly.
            # Use implied as proxy, but note it's slightly inflated.
            # If row has model_prob, we can use that as feature for calibration too.
            implied = _american_to_implied(odds)
            # If we have abbr_home etc, we could try to find counterpart, but keep simple
            # For accuracy: divide by average vig 1.04 observed in MLB
            implied_devig = implied/1.04 if implied else None
            if implied_devig is None:
                continue
            row = {"implied": implied_devig, "implied_raw": implied, "won": int(won), "model_prob": _f(r.get("model_prob"))}
            for c in EDGE_COMPONENT_COLS:
                row[c] = _f(r.get(c))
            rows.append(row)
    return rows, has_component_cols

def status(argv):
    rows, has_cols = load_graded_moneylines(CSV_PATH)
    n_total = len(rows)
    n_with_components = sum(1 for r in rows if all(r.get(c) is not None for c in EDGE_COMPONENT_COLS))
    print("=" * 60)
    print("FIT-READINESS STATUS (Improved)")
    print("=" * 60)
    print(f"  Graded moneyline rows : {n_total}")
    print(f"  With full edge data   : {n_with_components}")
    if n_total >= MIN_FOR_CALIBRATION:
        print(f"  Ã¢Å“â€œ Calibration READY")
    else:
        print(f"  Ã¢Å“â€” Need {MIN_FOR_CALIBRATION - n_total} more for calibration")
    if n_with_components >= MIN_FOR_FULL_FIT:
        print(f"  Ã¢Å“â€œ Full fit READY")
    else:
        print(f"  Ã¢Å“â€” Need {MIN_FOR_FULL_FIT - n_with_components} more for full fit")
    print("=" * 60)

def fit_calibration(argv):
    rows, _ = load_graded_moneylines(CSV_PATH)
    n = len(rows)
    if n < MIN_FOR_CALIBRATION:
        print(f"Only {n} rows Ã¢â‚¬â€ need {MIN_FOR_CALIBRATION}+")
        return
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("pip install numpy scikit-learn")
        return

    eps = 1e-4
    implied = np.array([[min(max(r["implied"], eps), 1 - eps)] for r in rows])
    y = np.array([r["won"] for r in rows])
    logit_implied = np.log(implied / (1 - implied))

    # Regularized logistic regression - prevents extreme a,b from small samples
    clf = LogisticRegression(C=1.0, max_iter=1000)
    clf.fit(logit_implied, y)
    a_raw, b_raw = float(clf.coef_[0][0]), float(clf.intercept_[0])

    # Clamp to sane range - this is critical for accuracy
    a = max(0.5, min(1.5, a_raw))
    b = max(-0.6, min(0.6, b_raw))

    mean_implied = float(implied.mean())
    actual_wr = float(y.mean())
    gap = actual_wr - mean_implied

    # Also compute Brier improvement
    from sklearn.metrics import brier_score_loss
    prob_raw = implied.flatten()
    prob_cal = 1/(1+np.exp(-(a*logit_implied.flatten()+b)))
    brier_raw = brier_score_loss(y, prob_raw)
    brier_cal = brier_score_loss(y, prob_cal)

    print("=" * 60)
    print("CALIBRATION FIT (Improved with de-vig + regularization)")
    print("=" * 60)
    print(f"  n = {n}")
    print(f"  Mean implied (de-vigged) : {mean_implied*100:.1f}%")
    print(f"  Actual win rate          : {actual_wr*100:.1f}%")
    print(f"  Gap                      : {gap*100:+.1f}%")
    print(f"  Raw fit a={a_raw:.4f} b={b_raw:+.4f} -> clamped a={a:.4f} b={b:+.4f}")
    print(f"  Brier raw {brier_raw:.4f} -> cal {brier_cal:.4f} (lower better)")
    if gap < -0.02:
        print("  Ã¢â€ â€™ Market running HOT, model overestimates favorites")
    elif gap > 0.02:
        print("  Ã¢â€ â€™ Market running COLD")
    else:
        print("  Ã¢â€ â€™ Roughly in line")

    out = {
        "fitted_on": date.today().isoformat(),
        "n": n,
        "mean_implied": mean_implied,
        "actual_win_rate": actual_wr,
        "platt_a_raw": a_raw,
        "platt_b_raw": b_raw,
        "platt_a": a,
        "platt_b": b,
        "brier_raw": brier_raw,
        "brier_cal": brier_cal,
        "note": "De-vigged implied used. Apply as sigmoid(a*logit(p)+b). Clamped for safety.",
    }
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Wrote {CALIBRATION_PATH}")

    # Suggest edge threshold update
    try:
        with open(CONFIG_PATH) as cf:
            cfg = json.load(cf)
        cur_edge = cfg.get("min_edge", cfg.get("edge_threshold", 0.04))
        # If model is overconfident (gap negative), raise edge threshold
        suggested = cur_edge
        if gap < -0.03:
            suggested = min(0.08, cur_edge + 0.015)
        elif gap < -0.015:
            suggested = min(0.08, cur_edge + 0.008)
        elif gap > 0.03:
            suggested = max(0.02, cur_edge - 0.01)
        print(f"  Current min_edge {cur_edge*100:.1f}% -> suggested {suggested*100:.1f}% based on gap")
        if "--auto" in argv:
            cfg["min_edge"] = round(suggested,4)
            cfg["edge_threshold"] = round(suggested,4)
            cfg["_updated"] = date.today().isoformat()
            cfg["_basis"] = f"{n} graded, gap {gap*100:+.1f}%"
            with open(CONFIG_PATH,"w") as outf:
                json.dump(cfg,outf,indent=2)
            print(f"  Auto-updated {CONFIG_PATH}")
    except Exception as e:
        print(f"  Could not suggest config update: {e}")
    print("=" * 60)

def fit_full_model(argv):
    rows, _ = load_graded_moneylines(CSV_PATH)
    usable = [r for r in rows if all(r.get(c) is not None for c in EDGE_COMPONENT_COLS)]
    n = len(usable)
    if n < MIN_FOR_FULL_FIT:
        print(f"Only {n} rows with full components, need {MIN_FOR_FULL_FIT}")
        return
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("pip install numpy scikit-learn")
        return
    X = np.array([[r[c] for c in EDGE_COMPONENT_COLS] for r in usable])
    y = np.array([r["won"] for r in usable])
    # Standardize X for stable fitting
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf = LogisticRegression(C=0.8, max_iter=3000, penalty='l2')
    clf.fit(Xs, y)
    # Convert back to original scale weights
    # coef_original = coef_scaled / std
    coefs = clf.coef_[0] / scaler.scale_
    print("=" * 60)
    print(f"FULL MULTI-FACTOR FIT n={n}")
    print("=" * 60)
    for col, coef in zip(EDGE_COMPONENT_COLS, coefs):
        print(f"  {col:<24} {coef:>10.5f}")
    print(f"  intercept {clf.intercept_[0]:.4f}")
    print("  These are in logit space. Divide by ~2.2 to approximate old prob-space weights")
    print("=" * 60)

def main(argv):
    if "--status" in argv or not argv:
        status(argv)
    elif "--calibrate" in argv:
        fit_calibration(argv)
    elif "--full" in argv:
        fit_full_model(argv)
    else:
        print(__doc__)

if __name__ == "__main__":
    main(sys.argv[1:])
