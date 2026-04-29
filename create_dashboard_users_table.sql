-- TS24 Dashboard — User Management Table
-- Run this in Supabase SQL Editor:
-- https://supabase.com/dashboard → your project → SQL Editor

CREATE TABLE IF NOT EXISTS dashboard_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'engineer'
                       CHECK (role IN ('admin', 'engineer', 'viewer')),
    rider         TEXT CHECK (rider IN ('DA77', 'JA52') OR rider IS NULL),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Seed the admin account (ts24)
-- Password hash = SHA-256 of "Tatsuki1344"
INSERT INTO dashboard_users (username, password_hash, role, rider)
VALUES (
    'ts24',
    '5551f24d5577aea070ca497ea2050544bb3dfd00847ca5720aa4d10440c54302',
    'admin',
    NULL
)
ON CONFLICT (username) DO NOTHING;

-- Row Level Security: service_role key bypasses RLS automatically.
-- Enable RLS to block anonymous access.
ALTER TABLE dashboard_users ENABLE ROW LEVEL SECURITY;
