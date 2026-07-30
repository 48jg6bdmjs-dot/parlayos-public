"""
NBA Ace V2 - With Prop Expansion
"""
import sys

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("nba_ace_original", "nba_ace.py")
    orig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orig)
    ORIGINAL_AVAILABLE = True
except Exception as e:
    ORIGINAL_AVAILABLE = False
    print(f"NBA Original not available: {e}")

try:
    from nfl_nba_props_v2 import improve_nfl_nba_with_props
    PROP_AVAILABLE = True
except ImportError:
    PROP_AVAILABLE = False

def run(html_path=None):
    if html_path is None:
        html_path = "parlayos.html"
    print(f"\n=== NBA Ace V2 ===")
    if not ORIGINAL_AVAILABLE:
        return []
    original_export = orig.export_to_html
    captured = []
    def cap(picks, hp=None):
        nonlocal captured
        captured = picks
        return picks
    orig.export_to_html = cap
    try:
        orig.main()
    except:
        try:
            captured = orig.run(html_path)
        except:
            captured = []
    orig.export_to_html = original_export
    print(f"NBA Original: {len(captured)} games")
    if PROP_AVAILABLE and captured:
        try:
            enhanced = improve_nfl_nba_with_props("NBA", captured)
            prop_count = len([p for p in enhanced if p.get('kind')=='prop'])
            print(f"NBA V2: {len(enhanced)} total ({len(captured)} games + {prop_count} props)")
            original_export(enhanced, html_path)
            return enhanced
        except Exception as e:
            print(f"Prop failed: {e}")
            original_export(captured, html_path)
            return captured
    else:
        if captured:
            original_export(captured, html_path)
        return captured

def main():
    html_path = sys.argv[1] if len(sys.argv)>1 else "parlayos.html"
    return run(html_path)

if __name__ == "__main__":
    main()
