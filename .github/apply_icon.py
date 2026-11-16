# -*- coding: utf-8 -*-
"""Apply custom app icon to Windows / Android / iOS targets. Non-fatal: any failure -> warning + exit 0."""
import glob, os, re, sys

try:
    from PIL import Image, ImageDraw
except Exception as e:
    print('::warning::pillow unavailable, keep default icons: %s' % e)
    sys.exit(0)

src_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/custom-icon.png'
try:
    src = Image.open(src_path).convert('RGBA')
except Exception as e:
    print('::warning::cannot open custom icon: %s' % e)
    sys.exit(0)

def base_square(img, pad_ratio=0.0, rounded=False):
    img = img.copy()
    m = max(img.size)
    canvas = Image.new('RGBA', (m, m), (0, 0, 0, 0))
    canvas.paste(img, ((m - img.size[0]) // 2, (m - img.size[1]) // 2), img)
    if pad_ratio > 0:
        p = int(m * pad_ratio)
        c2 = Image.new('RGBA', (m + 2 * p, m + 2 * p), (0, 0, 0, 0))
        c2.paste(canvas, (p, p), canvas)
        canvas = c2
    if rounded:
        s = canvas.size[0]
        mask = Image.new('L', (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
        canvas.putalpha(mask)
    return canvas

def sized(img, size):
    return img.resize((int(size), int(size)), Image.LANCZOS)

done = []

# 1) Windows: exe/installer icon (multi-size .ico)
ico = 'flutter/windows/runner/resources/app_icon.ico'
if os.path.exists(ico):
    try:
        base_square(src).save(ico, format='ICO',
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        done.append(ico)
    except Exception as e:
        print('::warning::windows icon failed: %s' % e)

# 2) Android launcher icons (remove adaptive XML so plain PNG mipmaps take effect)
densities = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
plain = base_square(src)
round_ = base_square(src, rounded=True)
for d, s in densities.items():
    rdir = 'flutter/android/app/src/main/res/mipmap-' + d
    if os.path.isdir(rdir):
        try:
            sized(plain, s).save(rdir + '/ic_launcher.png')
            sized(round_, s).save(rdir + '/ic_launcher_round.png')
            done.append('mipmap-' + d)
        except Exception as e:
            print('::warning::android %s failed: %s' % (d, e))
for f in glob.glob('flutter/android/app/src/main/res/mipmap-anydpi-v26/*.xml'):
    try:
        os.remove(f)
    except Exception:
        pass

# 3) iOS AppIcon.appiconset (sizes parsed from filenames)
adir = 'flutter/ios/Runner/Assets.xcassets/AppIcon.appiconset'
for f in glob.glob(adir + '/Icon-App-*.png'):
    mm = re.search(r'Icon-App-(\d+(?:\.\d+)?)x(\d+)@(\d+)x\.png$', os.path.basename(f))
    if not mm:
        continue
    size = int(round(float(mm.group(1)) * int(mm.group(3))))
    try:
        sized(base_square(src), size).save(f)
        done.append(os.path.basename(f))
    except Exception as e:
        print('::warning::ios %s failed: %s' % (os.path.basename(f), e))

print('custom icon applied to %d targets: %s' % (len(done), ', '.join(done[:8]) + ('...' if len(done) > 8 else '')))
sys.exit(0)
