import json, os, sys, traceback, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _run_one(name, module_path, html_path):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    try:
        import importlib.util
        module_path = os.path.join(BASE_DIR, module_path)
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

def _load_json(path):
    p = os.path.join(BASE_DIR, path)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)

def _load_chd_payload():
    files = {
        'combined': 'parlayos_chd_data.json',
        'mlb': 'parlayos_mlb_chd.json',
        'nfl': 'parlayos_nfl_chd.json',
        'nba': 'parlayos_nba_chd.json',
    }
    payload = {k: _load_json(v) for k, v in files.items()}
    combined = payload['combined'] if isinstance(payload['combined'], dict) else {}

    # The combined file is the canonical complete object; the sport-specific
    # files are authoritative fallbacks/overrides for their respective data.
    out = {
        'mlb': combined.get('mlb', payload['mlb'].get('games', [])),
        'nfl': combined.get('nfl', payload['nfl'].get('games', [])),
        'nba': combined.get('nba', payload['nba'].get('games', [])),
        'mlb_data': payload['mlb'],
        'nfl_data': payload['nfl'],
        'nba_data': payload['nba'],
        'summary': combined.get('summary', {}),
    }
    out['_sources'] = {k: v for k, v in files.items()}
    return out

def _inject_chd_into_html(html_path, chd_payload):
    from importlib.util import spec_from_file_location, module_from_spec
    predictor_path = os.path.join(BASE_DIR, 'chd_master_predictor.py')
    spec = spec_from_file_location('_chd_injector', predictor_path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Unable to load chd_master_predictor.py for HTML injection')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        original = f.read()
    if not original.strip():
        raise RuntimeError(f'HTML source is empty: {html_path}')
    injected = module.inject_all(original, chd_payload)
    if not injected or 'id="chd-data"' not in injected or 'id="chd-wiring"' not in injected:
        raise RuntimeError('CHD HTML injection did not produce required data/wiring blocks')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(injected)
    return injected

def main():
    has_key = bool(os.getenv("ODDS_API_KEY"))
    print(f"ODDS_API_KEY env set: {has_key}")
    print("Backend - Parallel")

    base_template = os.path.join(BASE_DIR, "parlayos_3.html")
    parlayos_html = os.path.join(BASE_DIR, "parlayos.html")
    index_html = os.path.join(BASE_DIR, "index.html")

    if os.path.exists(base_template):
        shutil.copy(base_template, parlayos_html)
        print(f"Template parlayos_3.html -> parlayos.html (fresh)")

    html_path = parlayos_html
    engines = [
        ("MLB (mlb_ace.py)", "mlb_ace.py", html_path),
        ("NBA (nba_ace.py)", "nba_ace.py", html_path),
        ("NFL (nfl_ace.py)", "nfl_ace.py", html_path),
    ]

    existing_engines = []
    for name, mod_path, html_p in engines:
        if os.path.exists(os.path.join(BASE_DIR, mod_path)):
            existing_engines.append((name, mod_path, html_p))
        else:
            print(f"Skipping {name}: {mod_path} not found")

    results = []
    start = time.time()
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
    print(f" SUMMARY - REAL DATA ONLY (Parallel {elapsed:.1f}s)")
    print(f"{'='*70}")
    for ok, name, total, qual in results:
        status = "OK" if ok else "X"
        print(f"  {status} {name}: {total} games, {qual} qualify")

    if not os.path.exists(parlayos_html):
        raise RuntimeError("parlayos.html not found after engine run")

    if os.path.exists(os.path.join(BASE_DIR, "parlayos_chd_data.json")):
        chd_payload = _load_chd_payload()
        print("Injecting CHD data from all four JSON outputs:")
        for source in chd_payload['_sources'].values():
            print(f"  - {source}")
        content = _inject_chd_into_html(parlayos_html, chd_payload)
    else:
        raise RuntimeError("parlayos_chd_data.json missing; refusing to publish HTML without CHD data")

    shutil.copyfile(parlayos_html, index_html)

    with open(parlayos_html, 'r', encoding='utf-8') as f:
        parlayos_content = f.read()
    with open(index_html, 'r', encoding='utf-8') as f:
        index_content = f.read()

    if 'id="chd-data"' not in parlayos_content or 'id="chd-wiring"' not in parlayos_content:
        raise RuntimeError("parlayos.html missing CHD injection blocks")
    if parlayos_content != index_content:
        raise RuntimeError("parlayos.html and index.html diverged")

    print(f"\nCHD DATA: injected into parlayos.html and copied to index.html ({len(content)} bytes)")
    print(f"HTML entries identical: {parlayos_content == index_content}")

if __name__ == "__main__":
    main()
