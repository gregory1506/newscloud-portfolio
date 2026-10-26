alter table public.email_deliveries
  drop constraint if exists email_deliveries_status_check;

alter table public.email_deliveries
  add constraint email_deliveries_status_check
  check (status in ('sending', 'sent', 'failed', 'retry_scheduled', 'skipped'));

alter table public.email_deliveries
  add column if not exists attempt_count integer not null default 0,
  add column if not exists last_attempt_at timestamptz,
  add column if not exists next_retry_at timestamptz;
