#!/usr/bin/env python3
"""
mlb_backtest.py â€” MLB wrapper with YouTube Vision
"""
import os, sys, json
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_core import analyse, tune_config, print_report, track_live_bet, close_live_bet, grade_live_bet, list_live_bets

CSV_PATH = os.path.join(HERE, "picks_log.csv")
CONFIG_PATH = os.path.join(HERE, "mlb_config.json")

SPORT_CFG = {
    "sport": "mlb",
    "config_path": CONFIG_PATH,
    "edge_min": 0.02,
    "edge_max": 0.10,
    "line_floor": 6.0,
    "line_ceil": 13.5,
    "min_bets": 15,
}

def main(argv):
    dry = "--dry-run" in argv
    as_json = "--json" in argv

    if "--track" in argv:
        idx = argv.index("--track")
        desc = argv[idx+1] if idx+1 < len(argv) else ""
        stake = float(argv[argv.index("--stake")+1]) if "--stake" in argv else 1.0
        track_live_bet(CSV_PATH, desc, stake); return
    if "--close" in argv:
        idx = argv.index("--close"); close_desc = argv[idx+1] if idx+1 < len(argv) else ""
        bid = argv[argv.index("--bet-id")+1] if "--bet-id" in argv else ""
        if not bid: print("--close requires --bet-id <id>"); return
        close_live_bet(CSV_PATH, bid, close_desc); return
    if "--grade" in argv:
        idx = argv.index("--grade"); result = argv[idx+1] if idx+1 < len(argv) else ""
        bid = argv[argv.index("--bet-id")+1] if "--bet-id" in argv else ""
        if not bid: print("--grade requires --bet-id <id>"); return
        grade_live_bet(CSV_PATH, bid, result); return
    if "--list" in argv:
        list_live_bets(CSV_PATH); return

    paths = [a for a in argv if not a.startswith("--")]
    csv_path = paths[0] if paths else CSV_PATH
    if not os.path.exists(csv_path):
        print(f"picks_log.csv not found at {csv_path}"); sys.exit(1)

    a = analyse(csv_path, SPORT_CFG)
    if "error" in a:
        print(json.dumps(a) if as_json else "ERROR: "+a["error"]); return
    cfg, notes = tune_config(a, SPORT_CFG)

    wrote = False
    if not dry:
        try:
            # Preserve existing YT weights and other fields
            try:
                with open(CONFIG_PATH) as f:
                    existing = json.load(f)
            except:
                existing = {}
            out = {**existing, **cfg}
            out["_basis"] = f"{a['totals']['bets'] if a['totals'] else 0} graded totals, ROI {a['totals']['roi'] if a['totals'] else 'n/a'} (auto-tuned {date.today().isoformat()})"
            out["_updated"] = date.today().isoformat()
            with open(CONFIG_PATH,"w") as f: json.dump(out,f,indent=2)
            wrote = True
        except Exception as e:
            notes.append(f"could not write config: {e}")

    if as_json:
        a.pop("_totals_rows", None)
        print(json.dumps({"analysis":a,"config":cfg,"notes":notes,"wrote":wrote},indent=2,default=str))
    else:
        print_report(a, cfg, notes, wrote, "mlb")

if __name__ == "__main__":
    main(sys.argv[1:])
