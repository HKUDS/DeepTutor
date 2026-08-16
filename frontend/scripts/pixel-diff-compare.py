import os
import sys
from PIL import Image, ImageChops, ImageDraw
import json

BASE = os.path.join(os.path.dirname(__file__), '..', 'screenshots')

LAYOUTS = [
    ('l1', 'Left+Center+Right'),
    ('l2', 'Left+Center'),
    ('l3', 'Center'),
    ('l4', 'Center+Right'),
]

THRESHOLD = 5  # per-channel threshold
ALPHA_THRESHOLD = 10  # alpha channel threshold

def compare_images(mhtml_path, replica_path, threshold=THRESHOLD):
    """Compare two images and return diff stats + diff image."""
    mhtml = Image.open(mhtml_path).convert('RGBA')
    replica = Image.open(replica_path).convert('RGBA')
    
    # Ensure same dimensions
    w = min(mhtml.width, replica.width)
    h = min(mhtml.height, replica.height)
    if mhtml.size != replica.size:
        print(f'  Warning: size mismatch - MHTML {mhtml.size} vs Replica {replica.size}, using {w}x{h}')
    
    mhtml = mhtml.crop((0, 0, w, h))
    replica = replica.crop((0, 0, w, h))
    
    mhtml_px = mhtml.load()
    replica_px = replica.load()
    
    diff_img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    diff_px = diff_img.load()
    
    diff_count = 0
    color_diffs = 0
    alpha_diffs = 0
    
    for y in range(h):
        for x in range(w):
            m = mhtml_px[x, y]
            r = replica_px[x, y]
            
            dr = abs(m[0] - r[0])
            dg = abs(m[1] - r[1])
            db = abs(m[2] - r[2])
            da = abs(m[3] - r[3])
            
            color_diff = dr + dg + db
            is_diff = color_diff > threshold or da > ALPHA_THRESHOLD
            
            if is_diff:
                diff_count += 1
                if color_diff > threshold:
                    color_diffs += 1
                if da > ALPHA_THRESHOLD:
                    alpha_diffs += 1
                # Red tint for diff pixels
                diff_px[x, y] = (255, 0, 0, 180)
    
    total_pixels = w * h
    pct = (diff_count / total_pixels) * 100
    
    return {
        'width': w,
        'height': h,
        'total_pixels': total_pixels,
        'diff_pixels': diff_count,
        'color_diff_pixels': color_diffs,
        'alpha_diff_pixels': alpha_diffs,
        'diff_percent': round(pct, 3),
        'diff_image': diff_img,
    }

def generate_overlay(mhtml_path, replica_path):
    """Generate overlay image showing both with 50% blend where they differ."""
    mhtml = Image.open(mhtml_path).convert('RGBA')
    replica = Image.open(replica_path).convert('RGBA')
    
    w = min(mhtml.width, replica.width)
    h = min(mhtml.height, replica.height)
    
    mhtml = mhtml.crop((0, 0, w, h))
    replica = replica.crop((0, 0, w, h))
    
    mhtml_px = mhtml.load()
    replica_px = replica.load()
    
    overlay = replica.copy()
    overlay_px = overlay.load()
    
    for y in range(h):
        for x in range(w):
            m = mhtml_px[x, y]
            r = replica_px[x, y]
            
            dr = abs(m[0] - r[0])
            dg = abs(m[1] - r[1])
            db = abs(m[2] - r[2])
            da = abs(m[3] - r[3])
            
            if dr + dg + db > THRESHOLD or da > ALPHA_THRESHOLD:
                # Mark with magenta overlay
                overlay_px[x, y] = (
                    min(255, r[0] + 80),
                    r[1],
                    r[2],
                    200
                )
    
    return overlay

def main():
    results = {}
    
    for key, name in LAYOUTS:
        mhtml_path = os.path.join(BASE, f'mhtml-{key}.png')
        replica_path = os.path.join(BASE, f'replica-{key}.png')
        
        if not os.path.exists(mhtml_path):
            print(f'SKIP {key} ({name}): MHTML screenshot not found')
            continue
        if not os.path.exists(replica_path):
            print(f'SKIP {key} ({name}): Replica screenshot not found')
            continue
        
        print(f'Comparing {key} ({name})...')
        
        result = compare_images(mhtml_path, replica_path)
        result['name'] = name
        
        # Save diff image
        diff_path = os.path.join(BASE, f'diff-{key}.png')
        result['diff_image'].save(diff_path)
        print(f'  Diff image saved: {diff_path}')
        
        # Save overlay image
        overlay = generate_overlay(mhtml_path, replica_path)
        overlay_path = os.path.join(BASE, f'overlay-{key}.png')
        overlay.save(overlay_path)
        print(f'  Overlay saved: {overlay_path}')
        
        del result['diff_image']
        results[key] = result
        
        print(f'  Resolution: {result["width"]}x{result["height"]}')
        print(f'  Total pixels: {result["total_pixels"]:,}')
        print(f'  Diff pixels: {result["diff_pixels"]:,} ({result["diff_percent"]}%)')
        print(f'  Color diffs: {result["color_diff_pixels"]:,}, Alpha diffs: {result["alpha_diff_pixels"]:,}')
        print()
    
    # Summary
    print('=' * 60)
    print('SUMMARY: Pixel Diff Results')
    print('=' * 60)
    for key, result in results.items():
        status = 'PASS' if result['diff_percent'] < 2.0 else 'FAIL'
        print(f'{key} ({result["name"]}): {result["diff_percent"]}% diff [{status}]')
    print('=' * 60)
    
    # Save results
    with open(os.path.join(BASE, 'diff-results.json'), 'w') as f:
        json.dump(results, f, indent=2)
    print(f'\nResults saved to diff-results.json')

if __name__ == '__main__':
    main()
