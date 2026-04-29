-- TS24 Supabase sessions sync (UPDATE + INSERT版)
-- Supabase SQL Editor に全文貼り付けて RUN してください

-- ① 既存レコードの更新 (ROUND11, ROUND12, TEST2, TEST3, TEST4)

UPDATE sessions SET
  circuit='ESTORIL',
  fork_type='FKR',
  f_spring='9/9.5',
  f_preload=15.0,
  f_comp=17,
  f_reb=20,
  shock_type='TTX',
  r_spring=85.0,
  r_preload=14.0,
  r_comp=16,
  r_reb=17,
  swing_arm=558,
  ride_height=249.0,
  track_temp=30.0, updated_at=NOW()
WHERE session_id='20251010-ROUND11-JA52';

UPDATE sessions SET
  circuit='JEREZ',
  fork_type='FKR',
  f_spring='9.5/10.0',
  f_preload=10.0,
  f_comp=21,
  f_reb=18,
  shock_type='TTX',
  r_spring=80.0,
  r_preload=14.0,
  r_comp=22,
  r_reb=17,
  swing_arm=557,
  ride_height=246.0,
  track_temp=46.0, updated_at=NOW()
WHERE session_id='20251017-ROUND12-JA52';

UPDATE sessions SET
  circuit='JEREZ',
  fork_type='FKR123 DA77',
  f_spring='9.5/9.5 → 8.5/8.5',
  f_preload=NULL,
  f_comp=17,
  f_reb=NULL,
  shock_type='TTX36 DA77 → 46S',
  r_spring=NULL,
  r_preload=NULL,
  r_comp=NULL,
  r_reb=NULL,
  swing_arm=562,
  ride_height=NULL,
  track_temp=NULL, updated_at=NOW()
WHERE session_id='20260126-TEST2-DA77';

UPDATE sessions SET
  circuit='JEREZ',
  fork_type='FKR123 123 JA1+2 → FKR123125 JA1+2',
  f_spring='9/9.5 → 9/9',
  f_preload=10.0,
  f_comp=22,
  f_reb=21,
  shock_type='TTX36 JA2',
  r_spring=NULL,
  r_preload=13.0,
  r_comp=25,
  r_reb=22,
  swing_arm=563,
  ride_height=NULL,
  track_temp=NULL, updated_at=NOW()
WHERE session_id='20260126-TEST2-JA52';

UPDATE sessions SET
  circuit='PORTIMAO',
  fork_type='FKR123',
  f_spring='9.5/10.5',
  f_preload=NULL,
  f_comp=20,
  f_reb=21,
  shock_type='S46',
  r_spring=95.0,
  r_preload=9.5,
  r_comp=20,
  r_reb=15,
  swing_arm=563,
  ride_height=245.0,
  track_temp=NULL, updated_at=NOW()
WHERE session_id='20260216-TEST3-DA77';

UPDATE sessions SET
  circuit='PORTIMAO',
  fork_type='FKR123',
  f_spring='9.5/10 → 9/9.5',
  f_preload=10.0,
  f_comp=20,
  f_reb=21,
  shock_type='TTX36',
  r_spring=NULL,
  r_preload=NULL,
  r_comp=21,
  r_reb=15,
  swing_arm=NULL,
  ride_height=249.0,
  track_temp=NULL, updated_at=NOW()
WHERE session_id='20260216-TEST3-JA52';

UPDATE sessions SET
  circuit='PI',
  fork_type='FKR123',
  f_spring='9/9.5',
  f_preload=11.0,
  f_comp=18,
  f_reb=15,
  shock_type='TTX36',
  r_spring=NULL,
  r_preload=NULL,
  r_comp=20,
  r_reb=15,
  swing_arm=NULL,
  ride_height=247.0,
  track_temp=NULL, updated_at=NOW()
WHERE session_id='20260313-TEST4-DA77';

UPDATE sessions SET
  circuit='PI',
  fork_type='FKR123',
  f_spring='9/9',
  f_preload=NULL,
  f_comp=18,
  f_reb=20,
  shock_type='TTX36',
  r_spring=86.0,
  r_preload=13.0,
  r_comp=20,
  r_reb=15,
  swing_arm=NULL,
  ride_height=NULL,
  track_temp=NULL, updated_at=NOW()
WHERE session_id='20260313-TEST4-JA52';

-- ② 新規レコードの追加 (TEST5 CREMONA)

INSERT INTO sessions (session_id, session_date, circuit, session_type, rider, bike_model, fork_type, f_spring, f_preload, f_comp, f_reb, shock_type, r_spring, r_preload, r_comp, r_reb, swing_arm, ride_height, track_temp)
SELECT '20260313-TEST5-DA77', '2026-03-13', 'CREMONA', 'TEST5', 'DA77', 'ZX-636', 'FKR', '9/9.5', 11.0, 18, 15, 'TTX', 90.0, 13.0, 20, 15, 565, 247.0, NULL
WHERE NOT EXISTS (
  SELECT 1 FROM sessions WHERE session_id='20260313-TEST5-DA77'
);

INSERT INTO sessions (session_id, session_date, circuit, session_type, rider, bike_model, fork_type, f_spring, f_preload, f_comp, f_reb, shock_type, r_spring, r_preload, r_comp, r_reb, swing_arm, ride_height, track_temp)
SELECT '20260313-TEST5-JA52', '2026-03-13', 'CREMONA', 'TEST5', 'JA52', 'ZX-636', 'FKR', '9/9.0', 14.0, 18, 20, 'TTX', 84.0, 13.0, 20, 15, 560, 244.0, NULL
WHERE NOT EXISTS (
  SELECT 1 FROM sessions WHERE session_id='20260313-TEST5-JA52'
);
