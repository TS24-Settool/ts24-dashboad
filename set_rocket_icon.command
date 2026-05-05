#!/bin/bash
# launch_workbench.command にロケットアイコンを設定（一度だけ実行）

TARGET="$HOME/Desktop/Data TS24 Claude/05_SCRIPTS/launch_workbench.command"

python3 - << 'PYEOF'
import os, sys

target = os.path.expanduser(
    "~/Desktop/Data TS24 Claude/05_SCRIPTS/launch_workbench.command"
)

try:
    import AppKit

    # 🚀 絵文字から NSImage を生成
    font = AppKit.NSFont.systemFontOfSize_(96)
    attrs = {AppKit.NSFontAttributeName: font}
    attr_str = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        "🚀", attrs
    )

    sz  = AppKit.NSMakeSize(128, 128)
    img = AppKit.NSImage.alloc().initWithSize_(sz)
    img.lockFocus()
    AppKit.NSColor.clearColor().set()
    AppKit.NSBezierPath.fillRect_(AppKit.NSMakeRect(0, 0, 128, 128))
    bound = attr_str.size()
    ox = (128 - bound.width)  / 2
    oy = (128 - bound.height) / 2
    attr_str.drawAtPoint_(AppKit.NSMakePoint(ox, oy))
    img.unlockFocus()

    ok = AppKit.NSWorkspace.sharedWorkspace().setIcon_forFile_options_(
        img, os.path.expanduser(target), 0
    )
    print("✅ ロケットアイコンを設定しました！" if ok else "❌ 設定失敗（ファイルパスを確認）")

except Exception as e:
    print(f"エラー: {e}")
PYEOF

echo ""
read -p "Press Enter to close..."
