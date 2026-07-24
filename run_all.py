import os, sys, traceback, json
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _find_html_template():
    for name in ["parlayos_3.html","parlayos_transparent_v8.html","parlayos_transparent_v7.html","parlayos.html","index.html","parlayos_2.html"]:
        p=os.path.join(HERE,name)
        if os.path.exists(p):
            return p
    return None

def _run_one(label, module_name):
    print(f"\n{'='*70}\n  {label}\n{'='*70}")
    try:
        module=__import__(module_name)
        import importlib
        importlib.reload(module)
    except Exception as e:
        print(f"X {label}: FAILED IMPORT - {e}")
        traceback.print_exc()
        return (label,False,None,str(e))
    html_path=_find_html_template()
    if not html_path:
        msg="No html template found"
        print(msg)
        return (label,False,None,msg)
    try:
        picks=module.run(html_path)
        qual=sum(1 for p in (picks or []) if p.get("qualifies"))
        print(f"OK {label}: {len(picks or [])} games, {qual} qualify")
        return (label,True,picks,None)
    except Exception as e:
        print(f"X {label}: FAILED - {e}")
        traceback.print_exc()
        return (label,False,None,str(e))

def _auto_calibrate():
    # Auto-run calibration if enough graded picks
    for fit_script, log_file in [("mlb_fit_weights.py","picks_log.csv"), ("nfl_fit_weights.py","nfl_picks_log.csv"), ("nba_fit_weights.py","nba_picks_log.csv")]:
        try:
            log_path=os.path.join(HERE,log_file)
            if not os.path.exists(log_path):
                continue
            # count lines
            with open(log_path) as f:
                n=sum(1 for _ in f)-1
            if n>=60:
                print(f"\nAuto-calibrating {fit_script} (n={n})...")
                os.system(f"python {os.path.join(HERE,fit_script)} --calibrate --auto")
        except Exception as e:
            print(f"Auto-calibrate {fit_script} failed: {e}")

def main():
    html_path=_find_html_template()
    if not html_path:
        print("No html template found")
        sys.exit(1)
    print(f"Target: {html_path}")
    print(f"ENV ODDS_API_KEY set: {bool(__import__(chr(111)+chr(115)).getenv(chr(79)+chr(68)+chr(68)+chr(83)+chr(95)+chr(65)+chr(80)+chr(73)+chr(95)+chr(75)+chr(69)+chr(89)))}")
    print("Checking player data fixes...")
    results=[]
    # FIXED: Your files are named *_ace_2.py, not *_ace.py
    results.append(_run_one("MLB (mlb_ace_2.py)","mlb_ace_2"))
    results.append(_run_one("NFL (nfl_ace_2.py)","nfl_ace_2"))
    results.append(_run_one("NBA (nba_ace_2.py)","nba_ace_2"))
    _auto_calibrate()

    # Post-process: re-apply no-data/old-data fixes that get overwritten by ace exports
    try:
        html_file = Path(html_path)
        html_text = html_file.read_text(encoding='utf-8', errors='ignore')
        
        # Fix 1: renderDashboard fallback
        html_text = html_text.replace(
            "let list = [];\n\t\t\t        try{ list = filterTodayGames(games.slice()); }catch(e){ list = []; } // variable current day only",
            "let list = [];\n\t\t\t        try{ list = filterTodayGames(games.slice()); if(!list.length && games.length) list = games.slice(); }catch(e){ list = games.slice(); } // fallback to all if no today games"
        )
        
        # Fix 2: wrapper fallback
        html_text = html_text.replace(
            "    // OVERRIDE REMOVED - keep day filter only, show full daily slate always\n    const _originalFilterTodayGames = filterTodayGames;\n    function filterTodayGamesWithStarted(arr){\n        // bypass started filter, return day-filtered only\n        try{ return _originalFilterTodayGames(arr); }catch{ return arr; }\n    }\n    filterTodayGames = filterTodayGamesWithStarted;",
            "    // FIX: No data / old data - always show something\n    const _originalFilterTodayGames = filterTodayGames;\n    function filterTodayGamesWithStarted(arr){\n        try{\n            const filtered = _originalFilterTodayGames(arr);\n            if(!filtered.length && arr && arr.length) return arr;\n            return filtered;\n        }catch{ return arr; }\n    }\n    filterTodayGames = filterTodayGamesWithStarted;"
        )
        
        html_file.write_text(html_text, encoding='utf-8')
        print("Ã¢Å“â€œ Re-applied no-data fixes to HTML")
    except Exception as e:
        print(f"Post-process fix failed: {e}")

    # Re-inject live scores
    try:
        import json as _json
        live_path = HERE / "live_scores.json"
        if live_path.exists():
            live_data = _json.loads(live_path.read_text())
            # Inject logic would go here, but simplified: just ensure file exists
            print(f"Ã¢Å“â€œ live_scores.json exists: {live_data.get('count',0)} games")
    except Exception as e:
        print(f"Live scores check failed: {e}")

    print("\n"+"="*70+"\n SUMMARY\n"+"="*70)
    for label,ok,picks,err in results:
        if ok:
            q=sum(1 for p in (picks or []) if p.get("qualifies"))
            print(f"  OK {label}: {len(picks or [])} games, {q} qualify")
        else:
            print(f"  X {label}: {err}")

if __name__=="__main__":
    main()
