-- TS24 Dashboard Users — 修正・確認用SQL
-- Supabase SQL Editor に貼り付けて実行してください
-- ============================================================

-- ① 現在のユーザー一覧を確認
SELECT username, role, rider, created_at
FROM dashboard_users
ORDER BY created_at;

-- ② username に UNIQUE 制約がなければ追加（重複防止）
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_name = 'dashboard_users'
      AND constraint_type = 'UNIQUE'
      AND constraint_name = 'dashboard_users_username_key'
  ) THEN
    ALTER TABLE dashboard_users ADD CONSTRAINT dashboard_users_username_key UNIQUE (username);
    RAISE NOTICE 'UNIQUE constraint added to username';
  ELSE
    RAISE NOTICE 'UNIQUE constraint already exists';
  END IF;
END $$;

-- ③ 重複行があれば古い方を削除（id が大きい方 = 新しい方を残す）
DELETE FROM dashboard_users a
USING dashboard_users b
WHERE a.id < b.id
  AND LOWER(a.username) = LOWER(b.username);

-- ④ 確認：クリーンアップ後のユーザー一覧
SELECT id, username, role, rider
FROM dashboard_users
ORDER BY id;
