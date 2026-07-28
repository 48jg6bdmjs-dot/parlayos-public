import os, sys, traceback

def _run_one(name, module_path, html_path):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name.replace(' ','_'), module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, 'run'):
            try:
                picks = module.run(html_path)
            except TypeError:
                picks = module.run()
        elif hasattr(module, 'main'):
            module.main()
            picks = []
        else:
            print(f"X {name}: no run() or main()")
            return False, 0, 0
        qualify = sum(1 for p in (picks or []) if p.get('qualifies', True))
        print(f"OK {name}: {len(picks or [])} games, {qualify} qualify")
        return True, len(picks or []), qualify
    except Exception as e:
        print(f"X {name}: FAILED - {e}")
        traceback.print_exc()
        return False, 0, 0

def main():
    has_key = bool(os.getenv("ODDS_API_KEY"))
    print(f"ODDS_API_KEY env set: {has_key}")
    if not has_key:
        print("Using hardcoded fallback e357fcc2... (add Secret ODDS_API_KEY in GitHub Settings to hide this warning)")
    
    html_path = os.path.join(os.path.dirname(__file__), "parlayos.html")
    results = []
    ok, total, qual = _run_one("MLB (mlb_ace.py)", "mlb_ace.py", html_path)
    results.append((ok, "MLB", total, qual))
    ok, total, qual = _run_one("NBA (nba_ace.py)", "nba_ace.py", "parlayos.html")
    results.append((ok, "NBA", total, qual))
    ok, total, qual = _run_one("NFL (nfl_ace.py)", "nfl_ace.py", "parlayos.html")
    results.append((ok, "NFL", total, qual))
    
    print(f"\n{'='*70}")
    print(" SUMMARY")
    print(f"{'='*70}")
    for ok, name, total, qual in results:
        status = "OK" if ok else "X"
        print(f"  {status} {name}: {total} games, {qual} qualify")
    
    if os.path.exists("parlayos.html"):
        with open("parlayos.html", "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        with open("index.html", "w", encoding="utf-8") as out:
            out.write(content)
        print("\n✓ parlayos.html -> index.html copied")
    else:
        print("\n! parlayos.html not found")

if __name__ == "__main__":
    main()
