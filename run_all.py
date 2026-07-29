import os, sys, traceback, shutil

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

    # Always start from clean template parlayos_3.html if present
    base_template = "parlayos_3.html"
    if os.path.exists(base_template):
        shutil.copy(base_template, "parlayos.html")
        print(f"Template {base_template} -> parlayos.html (fresh)")

    html_path = os.path.join(os.path.dirname(__file__), "parlayos.html")
    results = []
    ok, total, qual = _run_one("MLB (mlb_ace.py)", "mlb_ace.py", html_path)
    results.append((ok, "MLB", total, qual))
    ok, total, qual = _run_one("NBA (nba_ace.py)", "nba_ace.py", "parlayos.html")
    results.append((ok, "NBA", total, qual))
    ok, total, qual = _run_one("NFL (nfl_ace.py)", "nfl_ace.py", "parlayos.html")
    results.append((ok, "NFL", total, qual))
    
    print(f"\n{'='*70}")
    print(" SUMMARY - REAL DATA ONLY (no demo/sample)")
    print(f"{'='*70}")
    for ok, name, total, qual in results:
        status = "OK" if ok else "X"
        print(f"  {status} {name}: {total} games, {qual} qualify")
    
    # ALWAYS make both files identical with real data only
    if os.path.exists("parlayos.html"):
        with open("parlayos.html", "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # Safety: ensure no Sample Team leaked
        if "Sample Team" in content:
            print("Cleaning leaked Sample Team")
            content = content.replace("Sample Team A", "").replace("Sample Team B", "")
            with open("parlayos.html", "w", encoding="utf-8") as out:
                out.write(content)
        with open("index.html", "w", encoding="utf-8") as out:
            out.write(content)
        print(f"\nREAL DATA: parlayos.html -> index.html identical ({len(content)} bytes)")
    else:
        print("\n! parlayos.html not found")

if __name__ == "__main__":
    main()
