-- Legislative action signals gathered from Congress.gov, FEC API,
-- and congressional member press release RSS feeds.
--
-- One row per (run_date, region). Rows are optional enrichment consumed by
-- the party scoring engine (Phase 3). A missing row does not block synthesis —
-- the scorer falls back to coverage-only signals and lowers confidence.

create table if not exists public.legislative_signals (
  id              uuid        primary key default gen_random_uuid(),
  run_date        date        not null,
  region          text        not null,
  dem_bill_count  integer,
  rep_bill_count  integer,
  dem_vote_count  integer,
  rep_vote_count  integer,
  dem_fundraising numeric,
  rep_fundraising numeric,
  dem_issue_terms jsonb,
  rep_issue_terms jsonb,
  member_coverage numeric,
  fec_coverage    numeric,
  source_hash     text,
  created_at      timestamptz not null default timezone('utc', now()),
  updated_at      timestamptz not null default timezone('utc', now()),
  unique (run_date, region)
);

create trigger set_legislative_signals_updated_at
before update on public.legislative_signals
for each row
execute function public.set_updated_at();

alter table public.legislative_signals enable row level security;

revoke all on table public.legislative_signals from public;
revoke all on table public.legislative_signals from anon;
revoke all on table public.legislative_signals from authenticated;
