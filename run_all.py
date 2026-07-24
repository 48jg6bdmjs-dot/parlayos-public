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
    try:
        picks=module.run(html_path) if html_path else module.run()
        qual=sum(1 for p in (picks or []) if p.get("qualifies"))
        player_ok = sum(1 for p in (picks or []) if p.get("player_data_ok"))
        print(f"OK {label}: {len(picks or [])} games, {qual} qualify, player_data_ok={player_ok}")
        return (label,True,picks,None)
    except Exception as e:
        print(f"X {label}: FAILED - {e}")
        traceback.print_exc()
        return (label,False,None,str(e))

def main():
    print(f"ODDS_API_KEY set: {bool(os.getenv('ODDS_API_KEY'))}")
    results=[]
    results.append(_run_one("MLB (mlb_ace.py)","mlb_ace"))
    results.append(_run_one("NFL (nfl_ace.py)","nfl_ace"))
    results.append(_run_one("NBA (nba_ace.py)","nba_ace"))
    print("\n"+"="*70+"\n SUMMARY\n"+"="*70)
    for label,ok,picks,err in results:
        if ok:
            q=sum(1 for p in (picks or []) if p.get("qualifies"))
            print(f"  OK {label}: {len(picks or [])} games, {q} qualify")
        else:
            print(f"  X {label}: {err}")

if __name__=="__main__":
    main()
