"""
MLB Ace V2 - Integrated with Prop Engine
"""

import sys, os

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("mlb_ace_original", "mlb_ace.py")
    mlb_original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mlb_original)
    ORIGINAL_AVAILABLE = True
except Exception as e:
    ORIGINAL_AVAILABLE = False

try:
    from mlb_props_v2 import improve_mlb_prediction_with_props
    PROP_AVAILABLE = True
except ImportError:
    PROP_AVAILABLE = False

def run(html_path=None):
    if html_path is None:
        html_path = "parlayos.html"
    print("\n=== MLB Ace V2 ===")
    if not ORIGINAL_AVAILABLE:
        return []
    original_export = mlb_original.export_to_html
    captured = []
    def cap(picks, hp=None):
        nonlocal captured
        captured = picks
        return picks
    mlb_original.export_to_html = cap
    try:
        mlb_original.main()
    except:
        try:
            captured = mlb_original.run(html_path)
        except:
            captured = []
    mlb_original.export_to_html = original_export
    print(f"MLB Original: {len(captured)} games")
    if PROP_AVAILABLE and captured:
        try:
            enhanced = improve_mlb_prediction_with_props(captured)
            prop_count = len([p for p in enhanced if p.get('kind')=='prop'])
            print(f"MLB V2: {len(enhanced)} total ({len(captured)} games + {prop_count} props)")
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
