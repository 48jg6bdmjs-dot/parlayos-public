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
    results=[]
    results.append(_run_one("MLB (mlb_ace.py)","mlb_ace"))
    results.append(_run_one("NFL (nfl_ace.py)","nfl_ace"))
    results.append(_run_one("NBA (nba_ace.py)","nba_ace"))
    _auto_calibrate()

    # Post-process: strict date enforcement and live score injection
    try:
        html_file = Path(html_path)
        html_text = html_file.read_text(encoding='utf-8', errors='ignore')
        
        # FIX 1: Strict date enforcement. Do NOT fallback to old games if today is empty.
        html_text = html_text.replace(
            "let list = [];\n\t\t\t        try{ list = filterTodayGames(games.slice()); }catch(e){ list = []; } // variable current day only",
            "let list = [];\n\t\t\t        try{ list = filterTodayGames(games.slice()); if(!list.length) console.warn('No games scheduled for today.'); }catch(e){ list = []; } // strict current day filter only"
        )
        
        # FIX 2: Remove the bypass that shows old games. Fail safely to empty array.
        html_text = html_text.replace(
            "    // OVERRIDE REMOVED - keep day filter only, show full daily slate always\n    const _originalFilterTodayGames = filterTodayGames;\n    function filterTodayGamesWithStarted(arr){\n        // bypass started filter, return day-filtered only\n        try{ return _originalFilterTodayGames(arr); }catch{ return arr; }\n    }\n    filterTodayGames = filterTodayGamesWithStarted;",
            "    // FIX: Strict date enforcement - prevent old/incorrect games from displaying\n    const _originalFilterTodayGames = filterTodayGames;\n    function filterTodayGamesWithStarted(arr){\n        try{\n            return _originalFilterTodayGames(arr); // strict filter only\n        }catch{ return []; } // fail safely to empty array\n    }\n    filterTodayGames = filterTodayGamesWithStarted;"
        )
        
        # FIX 3: Properly inject live scores into the HTML DOM
        live_path = os.path.join(HERE, "live_scores.json")
        if os.path.exists(live_path):
            live_data = json.loads(Path(live_path).read_text(encoding='utf-8'))
            # Embed the JSON data securely into a script tag for the UI to consume
            inject_script = f"\n<script>window.LIVE_SCORES_DATA = {json.dumps(live_data)};</script>\n"
            if "</body>" in html_text:
                html_text = html_text.replace("</body>", inject_script + "</body>")
                print(f"✓ live_scores.json injected into HTML: {live_data.get('count', 0)} games")
            else:
                print("⚠ Could not find </body> tag to inject live scores.")
        else:
            print("ℹ live_scores.json not found, skipping injection.")
            
        html_file.write_text(html_text, encoding='utf-8')
        print("✓ Re-applied strict date filters and live scores to HTML")
    except Exception as e:
        print(f"Post-process fix failed: {e}")

    print("\n"+"="*70+"\n SUMMARY\n"+"="*70)
    for label,ok,picks,err in results:
        if ok:
            q=sum(1 for p in (picks or []) if p.get("qualifies"))
            print(f"  OK {label}: {len(picks or [])} games, {q} qualify")
        else:
            print(f"  X {label}: {err}")

if __name__=="__main__":
    main()