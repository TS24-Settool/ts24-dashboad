#!/bin/bash
# SBK_Performance_Tool — macOS セットアップスクリプト
# ダブルクリックで実行してください

cd "$(dirname "$0")"
DESKTOP="$HOME/Desktop"
EXE="$DESKTOP/SBK_Performance_Tool.exe"

echo "=============================================="
echo "  SBK Performance Tool — macOS セットアップ"
echo "=============================================="
echo ""

# --- 1. exe ファイル確認 ---
if [ ! -f "$EXE" ]; then
  echo "❌ エラー: $EXE が見つかりません"
  echo "   SBK_Performance_Tool.exe をデスクトップに置いてください"
  read -p "Enterで終了..."
  exit 1
fi
echo "✅ SBK_Performance_Tool.exe を確認しました"

# --- 2. Homebrew チェック ---
if ! command -v brew &>/dev/null; then
  echo ""
  echo "📦 Homebrew をインストールします..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Apple Silicon の場合パス追加
  if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
  fi
else
  echo "✅ Homebrew: $(brew --version | head -1)"
fi

# --- 3. Wine インストール ---
if ! command -v wine &>/dev/null && ! command -v wine64 &>/dev/null; then
  echo ""
  echo "🍷 Wine をインストールします（数分かかります）..."
  brew install --cask --no-quarantine wine-stable
else
  echo "✅ Wine: $(wine --version 2>/dev/null || wine64 --version 2>/dev/null)"
fi

# --- 4. Wine の環境設定（初回のみ）---
WINE_PREFIX="$HOME/.wine_sbk"
export WINEPREFIX="$WINE_PREFIX"

if [ ! -d "$WINE_PREFIX" ]; then
  echo ""
  echo "⚙️  Wine 環境を初期化します..."
  wineboot --init 2>/dev/null
fi

# --- 5. ランチャースクリプト作成 ---
LAUNCHER="$DESKTOP/SBK_Tool_Launch.command"
cat > "$LAUNCHER" << 'LAUNCH'
#!/bin/bash
export WINEPREFIX="$HOME/.wine_sbk"
DESKTOP="$HOME/Desktop"
EXE="$DESKTOP/SBK_Performance_Tool.exe"
echo "SBK Performance Tool を起動しています..."
cd "$DESKTOP"
wine "$EXE" 2>/dev/null &
LAUNCH
chmod +x "$LAUNCHER"

echo ""
echo "=============================================="
echo "✅ セットアップ完了！"
echo ""
echo "使い方："
echo "  デスクトップの「SBK_Tool_Launch.command」を"
echo "  ダブルクリックしてツールを起動してください"
echo ""
echo "  または今すぐ起動する場合は Enter を押してください"
echo "=============================================="
read -p "Enter で起動 / Ctrl+C でキャンセル: "

export WINEPREFIX="$HOME/.wine_sbk"
cd "$DESKTOP"
wine "$EXE" 2>/dev/null

read -p "Press Enter to exit..."
