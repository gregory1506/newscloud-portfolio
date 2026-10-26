alter table public.daily_runs
  drop constraint if exists daily_runs_status_check;

alter table public.daily_runs
  add column if not exists completed_region_count integer not null default 0,
  add column if not exists failed_region_count integer not null default 0,
  add column if not exists last_reconciled_at timestamptz,
  add column if not exists last_error text;

alter table public.daily_runs
  add constraint daily_runs_status_check
  check (status in ('running', 'reconciling', 'completed', 'failed', 'export_claimed', 'published'));

create table if not exists public.region_runs (
  run_date date not null,
  region text not null,
  gatherer_status text not null default 'none'
    check (gatherer_status in ('none', 'running', 'completed', 'failed')),
  scorer_status text not null default 'none'
    check (scorer_status in ('none', 'running', 'completed', 'failed')),
  generator_status text not null default 'none'
    check (generator_status in ('none', 'running', 'completed', 'failed')),
  gatherer_attempts integer not null default 0
    check (gatherer_attempts >= 0),
  scorer_attempts integer not null default 0
    check (scorer_attempts >= 0),
  generator_attempts integer not null default 0
    check (generator_attempts >= 0),
  gatherer_last_error text,
  scorer_last_error text,
  generator_last_error text,
  gatherer_started_at timestamptz,
  scorer_started_at timestamptz,
  generator_started_at timestamptz,
  gatherer_completed_at timestamptz,
  scorer_completed_at timestamptz,
  generator_completed_at timestamptz,
  next_retry_at timestamptz,
  last_event_at timestamptz not null default timezone('utc', now()),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  primary key (run_date, region)
);

create index if not exists region_runs_run_date_idx
  on public.region_runs (run_date desc);

create index if not exists region_runs_status_idx
  on public.region_runs (run_date, gatherer_status, scorer_status, generator_status);

create index if not exists region_runs_next_retry_idx
  on public.region_runs (run_date, next_retry_at);

create trigger set_region_runs_updated_at
before update on public.region_runs
for each row
execute function public.set_updated_at();

create or replace function public.claim_site_export(p_run_date date, p_claim_id text)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  update public.daily_runs dr
  set status = 'export_claimed',
      export_claim_id = p_claim_id,
      export_claimed_at = timezone('utc', now()),
      updated_at = timezone('utc', now())
  where dr.run_date = p_run_date
    and dr.status = 'completed'
    and dr.published_at is null
    and dr.export_claim_id is null;

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;

create or replace function public.release_site_export_claim(p_run_date date, p_claim_id text)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  update public.daily_runs dr
  set status = 'completed',
      export_claim_id = null,
      export_claimed_at = null,
      updated_at = timezone('utc', now())
  where dr.run_date = p_run_date
    and dr.published_at is null
    and dr.export_claim_id = p_claim_id;

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;
