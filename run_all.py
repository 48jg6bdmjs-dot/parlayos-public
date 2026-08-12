import json, os, sys, traceback, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHD_FILES = {
    "combined": "parlayos_chd_data.json",
    "mlb": "parlayos_mlb_chd.json",
    "nfl": "parlayos_nfl_chd.json",
    "nba": "parlayos_nba_chd.json",
}


def _run_one(name, module_path, html_path):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    try:
        import importlib.util
        module_path = os.path.join(BASE_DIR, module_path)
        unique_name = f"{name.replace(' ','_').replace('(','').replace(')','').replace('.','_')}_{int(time.time()*1000000)}_{os.getpid()}"
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None or spec.loader is None:
            print(f"X {name}: Could not load spec for {module_path}")
            return False, 0, 0
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(unique_name, None)
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
        qualify = sum(1 for p in (picks or []) if isinstance(p, dict) and p.get('qualifies', True))
        print(f"OK {name}: {len(picks or [])} games, {qualify} qualify")
        return True, len(picks or []), qualify
    except Exception as e:
        print(f"X {name}: FAILED - {e}")
        traceback.print_exc()
        return False, 0, 0


def _load_json(name):
    path = os.path.join(BASE_DIR, CHD_FILES[name])
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing CHD output: {CHD_FILES[name]}")
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid CHD JSON object: {CHD_FILES[name]}")
    return data


def _validate_chd_payloads():
    payloads = {name: _load_json(name) for name in CHD_FILES}
    for sport in ("mlb", "nfl", "nba"):
        data = payloads[sport]
        if not isinstance(data.get("games"), list):
            raise ValueError(f"{CHD_FILES[sport]} is missing its games array")
        if "schedules" not in data:
            raise ValueError(f"{CHD_FILES[sport]} is missing schedules")
    combined = payloads["combined"]
    for sport in ("mlb", "nfl", "nba"):
        if not isinstance(combined.get(sport), dict):
            raise ValueError(f"{CHD_FILES['combined']} is missing {sport} data")
        combined_games = combined[sport].get("games")
        if combined_games != payloads[sport].get("games"):
            raise ValueError(f"{CHD_FILES['combined']} does not match {CHD_FILES[sport]}")
    print("OK CHD JSON validation: combined + MLB + NFL + NBA are present and consistent")
    return payloads


def _install_runtime_chd_loader(html):
    # Replace the existing CHD injection block rather than adding a second loader.
    marker = '<script id="CHD_DATA_INJECTION">'
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("CHD_DATA_INJECTION block not found in HTML")
    end = html.find('</script>', start)
    if end < 0:
        raise RuntimeError("CHD_DATA_INJECTION block is not closed")
    end += len('</script>')

    loader = '''<script id="CHD_DATA_INJECTION">
(function(){
  const SRC = {
    mlb: './parlayos_mlb_chd.json',
    nfl: './parlayos_nfl_chd.json',
    nba: './parlayos_nba_chd.json',
    combined: './parlayos_chd_data.json'
  };
  window.PARLAYOS_CHD_SOURCES = SRC;
  const bust = (url) => url + (url.includes('?') ? '&' : '?') + 'ts=' + Date.now();
  async function get(url) {
    const r = await fetch(bust(url), {cache:'no-store'});
    if (!r.ok) throw new Error(url + ' HTTP ' + r.status);
    return r.json();
  }
  function normalize(data) {
    const out = Object.assign({games:[], schedules:{}, teamStats:{}, standings:{}}, data || {});
    return out;
  }
  async function load() {
    const [mlb, nfl, nba, combined] = await Promise.all([
      get(SRC.mlb), get(SRC.nfl), get(SRC.nba), get(SRC.combined)
    ]);
    window.PARLAYOS_DATA = normalize(mlb);
    window.PARLAYOS_NFL_DATA = normalize(nfl);
    window.PARLAYOS_NBA_DATA = normalize(nba);
    window.PARLAYOS_GAMES = window.PARLAYOS_DATA.games;
    window.gamesNFL = window.PARLAYOS_NFL_DATA.games;
    window.gamesNBA = window.PARLAYOS_NBA_DATA.games;
    window.PARLAYOS_CHD_DATA = {
      mlb: window.PARLAYOS_DATA,
      nfl: window.PARLAYOS_NFL_DATA,
      nba: window.PARLAYOS_NBA_DATA,
      combined: combined
    };
    document.dispatchEvent(new CustomEvent('parlayos:chd-data-ready', {detail: window.PARLAYOS_CHD_DATA}));
    try { if (typeof window.loadRealData === 'function') window.loadRealData(); } catch (_) {}
    try { if (typeof window.chdWireSportHubs === 'function') window.chdWireSportHubs(); } catch (_) {}
    console.log('[CHD] Loaded MLB/NFL/NBA + combined JSON only');
  }
  window.loadParlayOSCHDData = load;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => load().catch(e => console.error('[CHD]', e)), {once:true});
  } else {
    load().catch(e => console.error('[CHD]', e));
  }
})();
</script>'''
    return html[:start] + loader + html[end:]


def _reject_mock_dashboard_content(html):
    forbidden = [
        "Sample Team A",
        "Sample Team B",
        "SAMPLE_LIVE_GAMES",
        "Using sample",
        "Using demo",
        "mock data",
        "MOCK DATA",
        "DEMO DATA",
    ]
    found = [token for token in forbidden if token in html]
    if found:
        raise RuntimeError("Dashboard contains mock/demo data markers: " + ", ".join(found))


def main():
    has_key = bool(os.getenv("ODDS_API_KEY"))
    print(f"ODDS_API_KEY env set: {has_key}")
    print("Backend - Real CHD JSON only")

    payloads = _validate_chd_payloads()

    base_template = os.path.join(BASE_DIR, "parlayos_3.html")
    parlayos_html = os.path.join(BASE_DIR, "parlayos.html")
    index_html = os.path.join(BASE_DIR, "index.html")

    if os.path.exists(base_template):
        shutil.copy(base_template, parlayos_html)
        print("Template parlayos_3.html -> parlayos.html (fresh)")

    if not os.path.exists(parlayos_html) or not os.path.getsize(parlayos_html):
        raise RuntimeError("No non-empty parlayos.html source/template is available")

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
                results.append((future.result()))
            except Exception as e:
                print(f"X {name}: Executor failed - {e}")
                traceback.print_exc()
                results.append((False, name, 0, 0))

    elapsed = time.time() - start
    for ok, name, total, qual in results:
        print(f"  {'OK' if ok else 'X'} {name}: {total} games, {qual} qualify")

    content = open(parlayos_html, 'r', encoding='utf-8', errors='ignore').read()
    _reject_mock_dashboard_content(content)
    content = _install_runtime_chd_loader(content)

    required = [
        'parlayos_mlb_chd.json',
        'parlayos_nfl_chd.json',
        'parlayos_nba_chd.json',
        'parlayos_chd_data.json',
        'loadParlayOSCHDData',
        'CHD_DATA_INJECTION',
    ]
    missing = [token for token in required if token not in content]
    if missing:
        raise RuntimeError('HTML CHD validation failed: ' + ', '.join(missing))
    if 'window.PARLAYOS_DATA={' in content:
        raise RuntimeError('HTML still contains a stale inline CHD snapshot')

    with open(parlayos_html, 'w', encoding='utf-8') as f:
        f.write(content)
    shutil.copyfile(parlayos_html, index_html)

    if not os.path.getsize(index_html):
        raise RuntimeError('index.html is empty after publish')
    if open(parlayos_html, 'r', encoding='utf-8').read() != open(index_html, 'r', encoding='utf-8').read():
        raise RuntimeError('parlayos.html and index.html diverged')

    print(f"CHD DATA ONLY: MLB/NFL/NBA + combined JSON wired into both dashboards ({len(content)} bytes) in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
