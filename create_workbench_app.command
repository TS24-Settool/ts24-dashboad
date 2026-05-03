#!/bin/bash
# TS24 Workbench .app 作成スクリプト（macOS専用）
# このファイルをダブルクリックすると ~/Desktop/TS24\ Workbench.app を作成します。

set -e
cd "$(dirname "$0")"

SCRIPT_DIR="$(pwd)"
WORKBENCH_PY="${SCRIPT_DIR}/ts24_workbench.py"
APP_DEST="$HOME/Desktop/TS24 Workbench.app"

echo "=== TS24 Workbench.app 作成中 ==="
echo "スクリプト : ${WORKBENCH_PY}"
echo "出力先     : ${APP_DEST}"
echo ""

# ── Python3 を検索（PyQt6が入っているものを優先）──────────────────
PYTHON=""
for PY in \
    "/opt/homebrew/bin/python3" \
    "/opt/homebrew/bin/python3.12" \
    "/opt/homebrew/bin/python3.11" \
    "/usr/local/bin/python3" \
    "$(which python3 2>/dev/null)"; do
    if [ -x "$PY" ] && "$PY" -c "import PyQt6" 2>/dev/null; then
        PYTHON="$PY"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "⚠️  PyQt6が見つかりません。デフォルトの python3 を使います。"
    PYTHON="$(which python3 2>/dev/null || echo /usr/bin/python3)"
fi
echo "Python     : $PYTHON"
echo ""

# ── 既存の .app を削除 ────────────────────────────────────────────
[ -d "${APP_DEST}" ] && rm -rf "${APP_DEST}"

# ── バンドル構造を作成 ────────────────────────────────────────────
mkdir -p "${APP_DEST}/Contents/MacOS"
mkdir -p "${APP_DEST}/Contents/Resources"

# ── 起動スクリプト ────────────────────────────────────────────────
cat > "${APP_DEST}/Contents/MacOS/TS24Workbench" << LAUNCHER
#!/bin/bash
exec "${PYTHON}" "${WORKBENCH_PY}"
LAUNCHER
chmod +x "${APP_DEST}/Contents/MacOS/TS24Workbench"

# ── Info.plist ────────────────────────────────────────────────────
cat > "${APP_DEST}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>TS24 Workbench</string>
  <key>CFBundleDisplayName</key>
  <string>TS24 Workbench</string>
  <key>CFBundleIdentifier</key>
  <string>com.puccetti-racing.ts24workbench</string>
  <key>CFBundleVersion</key>
  <string>1.0</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleExecutable</key>
  <string>TS24Workbench</string>
  <key>CFBundleIconFile</key>
  <string>ts24-rocket</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSRequiresAquaSystemAppearance</key>
  <false/>
</dict>
</plist>
PLIST

# ── ロケットアイコンを Python で生成（stdlib のみ・依存なし）───────
"${PYTHON}" << 'ICON_PY'
import struct, zlib, os, math

def make_png(size):
    """ロケットアイコン PNG を純 Python stdlib で生成する。"""
    s = size
    cx, cy = s / 2, s / 2
    R = s / 2 - 1            # 外周円の半径

    # RGBA ピクセルバッファ（透明で初期化）
    buf = [[(0, 0, 0, 0)] * s for _ in range(s)]

    def dist2(x, y, px, py):
        return (x - px) ** 2 + (y - py) ** 2

    def in_circle(x, y, cx, cy, r):
        return dist2(x, y, cx, cy) <= r * r

    def set_px(x, y, color):
        if 0 <= x < s and 0 <= y < s:
            buf[y][x] = color

    def fill_rect(x0, y0, x1, y1, color, clip_circle=True):
        for y in range(max(0, int(y0)), min(s, int(y1) + 1)):
            for x in range(max(0, int(x0)), min(s, int(x1) + 1)):
                if not clip_circle or in_circle(x, y, cx, cy, R):
                    buf[y][x] = color

    def fill_triangle(pts, color, clip_circle=True):
        """pts: [(x0,y0),(x1,y1),(x2,y2)] バウンディングボックスで走査。"""
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        def sign(p1, p2, p3):
            return (p1[0]-p3[0])*(p2[1]-p3[1]) - (p2[0]-p3[0])*(p1[1]-p3[1])
        def in_tri(px, py):
            pt = (px, py)
            d1 = sign(pt, pts[0], pts[1])
            d2 = sign(pt, pts[1], pts[2])
            d3 = sign(pt, pts[2], pts[0])
            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
            return not (has_neg and has_pos)
        for y in range(max(0, int(min(ys))), min(s, int(max(ys)) + 1)):
            for x in range(max(0, int(min(xs))), min(s, int(max(xs)) + 1)):
                if in_tri(x, y) and (not clip_circle or in_circle(x, y, cx, cy, R)):
                    buf[y][x] = color

    def fill_ellipse(ex, ey, rx, ry, color, clip_circle=True):
        for y in range(max(0, int(ey - ry) - 1), min(s, int(ey + ry) + 2)):
            for x in range(max(0, int(ex - rx) - 1), min(s, int(ex + rx) + 2)):
                if ((x - ex) / rx) ** 2 + ((y - ey) / ry) ** 2 <= 1.0:
                    if not clip_circle or in_circle(x, y, cx, cy, R):
                        buf[y][x] = color

    # ─ 背景円（濃紺）
    fill_rect(0, 0, s - 1, s - 1, (10, 10, 46, 255))
    # 外周円より外を透明に
    for y in range(s):
        for x in range(s):
            if not in_circle(x, y, cx, cy, R):
                buf[y][x] = (0, 0, 0, 0)

    # ─ 星（白点）
    stars_rel = [(0.22, 0.20), (0.78, 0.17), (0.85, 0.43), (0.14, 0.55),
                 (0.90, 0.68), (0.18, 0.75)]
    for sx_r, sy_r in stars_rel:
        px, py = int(sx_r * s), int(sy_r * s)
        if in_circle(px, py, cx, cy, R):
            set_px(px, py, (255, 255, 255, 220))

    # ─ 寸法（サイズ比で定義）
    bw    = s * 0.12          # 胴体半幅
    btop  = cy - R * 0.50    # 胴体上端
    bbot  = cy + R * 0.22    # 胴体下端
    ntop  = cy - R * 0.85    # ノーズ頂点

    # ─ 胴体（白）
    fill_rect(cx - bw, btop, cx + bw, bbot, (230, 230, 240, 255))

    # ─ ノーズコーン（赤）
    fill_triangle(
        [(cx, ntop), (cx - bw, btop), (cx + bw, btop)],
        (210, 30, 30, 255)
    )

    # ─ 左フィン（赤）
    fin_out = cx - R * 0.55
    fill_triangle(
        [(cx - bw, bbot - 1), (fin_out, bbot + s * 0.12), (cx - bw, bbot + s * 0.12)],
        (210, 30, 30, 255)
    )
    # ─ 右フィン（赤）
    fin_out_r = cx + R * 0.55
    fill_triangle(
        [(cx + bw, bbot - 1), (fin_out_r, bbot + s * 0.12), (cx + bw, bbot + s * 0.12)],
        (210, 30, 30, 255)
    )

    # ─ 窓（水色）
    win_cy = cy - R * 0.08
    fill_ellipse(cx, win_cy, bw * 0.75, bw * 0.75, (79, 195, 247, 255))
    # 窓ハイライト
    fill_ellipse(cx - bw * 0.25, win_cy - bw * 0.25,
                 bw * 0.3, bw * 0.3, (179, 229, 252, 200))

    # ─ 炎（オレンジ → 黄 → 白）
    flame_top = bbot
    flame_bot = cy + R * 0.70
    fh = flame_bot - flame_top
    fill_ellipse(cx, flame_top + fh * 0.40, bw * 0.95, fh * 0.55,
                 (255, 100, 0, 220))
    fill_ellipse(cx, flame_top + fh * 0.30, bw * 0.65, fh * 0.38,
                 (255, 200, 0, 230))
    fill_ellipse(cx, flame_top + fh * 0.18, bw * 0.38, fh * 0.22,
                 (255, 255, 200, 200))

    # ─ PNG エンコード ───────────────────────────────────────────
    def pack32(v): return struct.pack('>I', v)
    def chunk(tag, data):
        c = tag + data
        return pack32(len(data)) + c + pack32(zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', s, s, 8, 6, 0, 0, 0)   # 8-bit RGBA
    raw = b''
    for row in buf:
        raw += b'\x00'   # filter = None
        for px in row:
            raw += bytes(px)

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw, 6))
            + chunk(b'IEND', b''))


# iconset を作成
import os
iconset_dir = os.path.expanduser(
    '~/Desktop/TS24 Workbench.app/Contents/Resources/ts24-rocket.iconset')
os.makedirs(iconset_dir, exist_ok=True)

for size in [16, 32, 64, 128, 256, 512, 1024]:
    png = make_png(size)
    fname = f'icon_{size}x{size}.png'
    with open(os.path.join(iconset_dir, fname), 'wb') as f:
        f.write(png)
    # @2x（倍密度版）
    if size <= 512:
        png2x = make_png(size * 2)
        fname2x = f'icon_{size}x{size}@2x.png'
        with open(os.path.join(iconset_dir, fname2x), 'wb') as f:
            f.write(png2x)

print('  PNG 生成完了')
ICON_PY

# ── iconutil で .icns に変換 ──────────────────────────────────────
ICONSET="${APP_DEST}/Contents/Resources/ts24-rocket.iconset"
ICNS="${APP_DEST}/Contents/Resources/ts24-rocket.icns"

if iconutil -c icns "${ICONSET}" -o "${ICNS}" 2>/dev/null; then
    rm -rf "${ICONSET}"
    echo "  アイコン変換完了 (.icns)"
else
    echo "  ⚠️  iconutil が使えません — アイコンなしで作成します"
    rm -rf "${ICONSET}"
fi

# ── Finder に .app として認識させる ──────────────────────────────
touch "${APP_DEST}"

echo ""
echo "✅ 作成完了: ~/Desktop/TS24 Workbench.app"
echo "   ダブルクリックで即起動できます 🚀"
echo ""
echo "※ 初回起動時に「開発元を確認できません」と出る場合:"
echo "   → 右クリック → 開く → 開く  で許可してください。"
