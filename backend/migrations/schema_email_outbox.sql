-- Schema for email outbox jobs

-- psql -U app -d privas_dev

CREATE TABLE IF NOT EXISTS email_jobs (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  rule_instance_id TEXT,
  recipient_email TEXT,
  subject TEXT,
  body TEXT,
  payload JSONB,
  status TEXT CHECK (status IN ('pending','processing','sent','failed')) NOT NULL DEFAULT 'pending',
  attempts INT DEFAULT 0,
  max_attempts INT DEFAULT 5,
  next_retry_at TIMESTAMPTZ NULL,
  last_error TEXT NULL,
  idempotency_key TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  sent_at TIMESTAMPTZ NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_email_jobs_status ON email_jobs (status);
CREATE INDEX IF NOT EXISTS idx_email_jobs_next_retry_at ON email_jobs (next_retry_at);
CREATE INDEX IF NOT EXISTS idx_email_jobs_session_id ON email_jobs (session_id);
CREATE UNIQUE INDEX ux_email_jobs_idempotency_key ON public.email_jobs (idempotency_key);

-- Unique constraint on idempotency_key when not null


-- \dt
-- privas_dev=> \dt
--                   List of tables
--  Schema |         Name         | Type  |  Owner
--  --------+----------------------+-------+----------
--  public | email_jobs           | table | app
