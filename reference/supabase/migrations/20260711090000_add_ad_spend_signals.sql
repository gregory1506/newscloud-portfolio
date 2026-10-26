-- Per-candidate ad-spend signals: FEC Schedule E independent expenditures
-- (rolling 7 days, daily refresh) and Google political-ads placement spend
-- (weekly snapshot). One row per (run_date, region, candidate_id); the
-- candidate_id = '' row per (run_date, region) holds state-level
-- unattributed digital spend.
--
-- Rows are optional enrichment consumed by the party synthesizer's
-- money-vs-momentum classifier. Missing rows never block synthesis.

create table if not exists public.ad_spend_signals (
  id               uuid        primary key default gen_random_uuid(),
  run_date         date        not null,
  region           text        not null,
  candidate_id     text        not null default '',
  candidate_name   text,
  party            text,
  district         text,
  ie_support_7d    numeric,
  ie_oppose_7d     numeric,
  digital_spend_wk numeric,
  fec_coverage     numeric,
  digital_coverage numeric,
  gathered_at      timestamptz not null default timezone('utc', now()),
  created_at       timestamptz not null default timezone('utc', now()),
  updated_at       timestamptz not null default timezone('utc', now()),
  unique (run_date, region, candidate_id)
);

create trigger set_ad_spend_signals_updated_at
before update on public.ad_spend_signals
for each row
execute function public.set_updated_at();

alter table public.ad_spend_signals enable row level security;

revoke all on table public.ad_spend_signals from public;
revoke all on table public.ad_spend_signals from anon;
revoke all on table public.ad_spend_signals from authenticated;
