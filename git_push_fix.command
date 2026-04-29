#!/bin/bash
# TS24 Dashboard — Push to GitHub
# Double-click this file to run

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  TS24 Dashboard — GitHub Push"
echo "========================================="
echo ""

git config user.email "tatsuki1344@gmail.com"
git config user.name "TS24-Settool"

# ── 全変更ファイルを自動追跡（新規ファイルも含む）──────────────
git add -A

# コミットメッセージ: 変更内容を自動生成
CHANGED=$(git diff --cached --name-only 2>/dev/null | head -10 | tr '\n' ' ')
if [ -z "$CHANGED" ]; then
    echo "(既にコミット済み — pushのみ実行)"
else
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
    git commit -m "update: ${TIMESTAMP}

Changed files: ${CHANGED}"
fi

echo "Pulling remote changes (rebase)..."
git pull --rebase origin main

echo "Pushing to GitHub..."
git push origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Push完了! Streamlit Cloudが自動的に再デプロイされます。"
    echo "   約1〜2分後にダッシュボードを更新してください。"
else
    echo ""
    echo "❌ Pushに失敗しました。GitHubの認証を確認してください。"
fi

echo ""
read -p "Press Enter to exit..."
