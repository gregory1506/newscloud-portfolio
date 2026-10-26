-- Race Board entity layer: races, candidates, and daily race snapshots.
--
-- Phase 1 (GR3-516) of docs/race-board-phased-plan.md. These tables hold the
-- 2026 race roster, candidate/campaign-finance detail, and one deterministic
-- Coverage Rating snapshot per race per day. Service-role only: the public
-- board is served from sanitized static exports, never these rows.

create table if not exists public.races (
  id              uuid        primary key default gen_random_uuid(),
  race_id         text        not null unique,
  cycle           int         not null,
  chamber         text        not null check (chamber in ('senate', 'house', 'governor')),
  state           text        not null,
  district        int,
  seat_class      text,
  election_date   date        not null,
  seat_status     text        not null default 'unknown'
                              check (seat_status in ('incumbent', 'open', 'retiring', 'unknown')),
  incumbent_party text,
  data_status     text        not null default 'structural_only',
  rating_band     text,
  created_at      timestamptz not null default timezone('utc', now()),
  updated_at      timestamptz not null default timezone('utc', now())
);

create index if not exists races_chamber_state_idx on public.races (chamber, state);
create index if not exists races_cycle_idx on public.races (cycle);

create table if not exists public.candidates (
  id               uuid        primary key default gen_random_uuid(),
  candidate_id     text        not null,
  race_id          text        not null references public.races (race_id) on delete cascade,
  name             text,
  party            text,
  is_incumbent     boolean     not null default false,
  status           text        not null default 'unknown',
  committee_ids    text[]      not null default '{}',
  photo_url        text,
  photo_credit     text,
  ballotpedia_url  text,
  raised_total     numeric,
  cash_on_hand     numeric,
  last_quarter     numeric,
  small_dollar_pct numeric,
  fec_coverage     numeric,
  created_at       timestamptz not null default timezone('utc', now()),
  updated_at       timestamptz not null default timezone('utc', now()),
  unique (race_id, candidate_id)
);

create index if not exists candidates_race_idx on public.candidates (race_id);

create table if not exists public.race_snapshots (
  id                  uuid        primary key default gen_random_uuid(),
  run_date            date        not null,
  race_id             text        not null references public.races (race_id) on delete cascade,
  coverage_leaning    numeric,
  coverage_tone       numeric,
  issue_mix           jsonb       not null default '{}'::jsonb,
  headline_count      int,
  source_count        int,
  ie_support          numeric,
  ie_oppose           numeric,
  digital_spend       numeric,
  dem_money           numeric,
  rep_money           numeric,
  fec_coverage        numeric,
  rating_score        numeric,
  rating_band         text,
  rating_confidence   numeric,
  components          jsonb       not null default '{}'::jsonb,
  methodology_version text        not null default 'coverage-rating-v1',
  evidence            jsonb       not null default '[]'::jsonb,
  created_at          timestamptz not null default timezone('utc', now()),
  updated_at          timestamptz not null default timezone('utc', now()),
  unique (run_date, race_id)
);

create index if not exists race_snapshots_run_date_idx on public.race_snapshots (run_date);
create index if not exists race_snapshots_race_idx on public.race_snapshots (race_id);

create trigger set_races_updated_at
before update on public.races
for each row
execute function public.set_updated_at();

create trigger set_candidates_updated_at
before update on public.candidates
for each row
execute function public.set_updated_at();

create trigger set_race_snapshots_updated_at
before update on public.race_snapshots
for each row
execute function public.set_updated_at();

alter table public.races enable row level security;
alter table public.candidates enable row level security;
alter table public.race_snapshots enable row level security;

revoke all on table public.races from public;
revoke all on table public.races from anon;
revoke all on table public.races from authenticated;

revoke all on table public.candidates from public;
revoke all on table public.candidates from anon;
revoke all on table public.candidates from authenticated;

revoke all on table public.race_snapshots from public;
revoke all on table public.race_snapshots from anon;
revoke all on table public.race_snapshots from authenticated;
