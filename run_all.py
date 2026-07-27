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
        # Try run() first, then main()
        if hasattr(module, 'run'):
            picks = module.run(html_path) if html_path else module.run()
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
    print(f"ODDS_API_KEY set: {has_key}")
    if not has_key:
        print("Running in OFFSEASON/DEMO mode - games may be 0 but engine stays intact")
    
    html_path = os.path.join(os.path.dirname(__file__), "parlayos.html")
    
    results = []
    # MLB always runs
    ok, total, qual = _run_one("MLB (mlb_ace.py)", "mlb_ace.py", html_path)
    results.append((ok, "MLB", total, qual))
    
    # NBA - only if in season or forced
    ok, total, qual = _run_one("NBA (nba_ace.py)", "nba_ace.py", None)
    results.append((ok, "NBA", total, qual))
    
    # NFL - only if in season or forced
    ok, total, qual = _run_one("NFL (nfl_ace.py)", "nfl_ace.py", None)
    results.append((ok, "NFL", total, qual))
    
    print(f"\n{'='*70}")
    print(" SUMMARY")
    print(f"{'='*70}")
    for ok, name, total, qual in results:
        status = "OK" if ok else "X"
        print(f"  {status} {name}: {total} games, {qual} qualify")
    
    # Ensure parlayos.html exists and copy to index.html for Cloudflare Pages
    if os.path.exists("parlayos.html"):
        with open("parlayos.html", "r") as f:
            content = f.read()
        # Also write index.html for Pages
        with open("index.html", "w") as f:
            f.write(content)
        print("\nâœ“ parlayos.html -> index.html copied for Cloudflare Pages")
    else:
        print("\n! parlayos.html not found - build may have failed")

if __name__ == "__main__":
    main()
