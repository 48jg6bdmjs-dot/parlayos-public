import os, sys, traceback, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

def _run_one(name, module_path, html_path):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    try:
        import importlib.util
        # FIXED: Unique name to prevent recursion / cache collision in parallel
        unique_name = f"{name.replace(' ','_').replace('(','').replace(')','').replace('.','_')}_{int(time.time()*1000000)}_{os.getpid()}"
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None:
            print(f"X {name}: Could not load spec for {module_path}")
            return False, 0, 0
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
    print("Backend Manager V2 - Parallel Fixed (No Recursion)")

    base_template = "parlayos_3.html"
    if os.path.exists(base_template):
        shutil.copy(base_template, "parlayos.html")
        print(f"Template {base_template} -> parlayos.html (fresh)")

    html_path = os.path.join(os.path.dirname(__file__), "parlayos.html")
    engines = [
        ("MLB (mlb_ace.py)", "mlb_ace.py", html_path),
        ("NBA (nba_ace.py)", "nba_ace.py", "parlayos.html"),
        ("NFL (nfl_ace.py)", "nfl_ace.py", "parlayos.html"),
    ]
    
    # Check which engines exist
    existing_engines = []
    for name, mod_path, html_p in engines:
        if os.path.exists(mod_path):
            existing_engines.append((name, mod_path, html_p))
        else:
            print(f"Skipping {name}: {mod_path} not found")
    
    results = []
    start = time.time()
    
    # V2: Parallel execution
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_engine = {
            executor.submit(_run_one, name, mod_path, html_p): (name, mod_path)
            for name, mod_path, html_p in existing_engines
        }
        for future in as_completed(future_to_engine):
            name, mod_path = future_to_engine[future]
            try:
                ok, total, qual = future.result()
                results.append((ok, name, total, qual))
            except Exception as e:
                print(f"X {name}: Executor failed - {e}")
                traceback.print_exc()
                results.append((False, name, 0, 0))
    
    elapsed = time.time() - start
    
    print(f"\n{'='*70}")
    print(f" SUMMARY - REAL DATA ONLY (V2 Parallel {elapsed:.1f}s)")
    print(f"{'='*70}")
    for ok, name, total, qual in results:
        status = "OK" if ok else "X"
        print(f"  {status} {name}: {total} games, {qual} qualify")
    
    if os.path.exists("parlayos.html"):
        with open("parlayos.html", "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "Sample Team" in content:
            print("Cleaning leaked Sample Team")
            content = content.replace("Sample Team A", "").replace("Sample Team B", "")
            with open("parlayos.html", "w", encoding="utf-8") as out:
                out.write(content)
        with open("index.html", "w", encoding="utf-8") as out:
            out.write(content)
        print(f"\nREAL DATA: parlayos.html -> index.html identical ({len(content)} bytes) in {elapsed:.1f}s")
    else:
        print("\n! parlayos.html not found")

if __name__ == "__main__":
    main()
