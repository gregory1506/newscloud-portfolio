-- District gather state, mirroring ``region_runs`` for the bounded district
-- sweep. Districts previously wrote no state at all, so a duplicate delivery
-- spent another provider credit with nothing to stop it, a denied or empty
-- district left no record, and the coverage audit could not tell an attempted
-- but empty district from one the fan-out never reached.
--
-- The status vocabulary matches the region stage
-- (``none/running/completed/failed/deferred``) so the same claim shape and the
-- same retry vocabulary apply.

create table if not exists public.district_runs (
  run_date date not null,
  district text not null,
  gatherer_status text not null default 'none'
    check (gatherer_status in ('none', 'running', 'completed', 'failed', 'deferred')),
  gatherer_attempts integer not null default 0
    check (gatherer_attempts >= 0),
  gatherer_started_at timestamptz,
  next_retry_at timestamptz,
  last_event_at timestamptz not null default timezone('utc', now()),
  last_error text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  primary key (run_date, district)
);

create index if not exists district_runs_run_date_idx
  on public.district_runs (run_date desc);

create index if not exists district_runs_status_idx
  on public.district_runs (run_date, gatherer_status);

create index if not exists district_runs_next_retry_idx
  on public.district_runs (run_date, next_retry_at);

create trigger set_district_runs_updated_at
before update on public.district_runs
for each row
execute function public.set_updated_at();

-- Match the region_runs posture: the table is invisible to the client roles.
alter table public.district_runs enable row level security;

revoke all on table public.district_runs from public;
revoke all on table public.district_runs from anon;
revoke all on table public.district_runs from authenticated;

-- Claim the gather stage for one delivery of one district.
--
-- Mirrors ``claim_region_gather``: Pub/Sub delivers at least once, so this
-- compare-and-set decides whether *this* delivery does the work, and a duplicate
-- delivery costs one database read instead of a provider credit.
--
-- Returns:
--   claimed            this delivery owns the stage; proceed
--   in_progress        another delivery started inside the stale window; skip
--   already_completed  the stage already finished for this run date; skip

create or replace function public.claim_district_gather(
  p_run_date date,
  p_district text,
  p_stale_minutes integer default 10,
  p_now timestamptz default timezone('utc', now())
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_claimed text;
  v_status text;
begin
  if p_run_date is null or nullif(trim(p_district), '') is null then
    raise exception 'run_date and district are required';
  end if;
  if p_stale_minutes < 1 then
    raise exception 'stale_minutes must be >= 1';
  end if;

  update public.district_runs dr
  set gatherer_status = 'running',
      gatherer_started_at = p_now,
      gatherer_attempts = dr.gatherer_attempts + 1,
      last_error = null,
      last_event_at = p_now
  where dr.run_date = p_run_date
    and dr.district = p_district
    and (
      dr.gatherer_status in ('none', 'failed', 'deferred')
      or (
        dr.gatherer_status = 'running'
        and dr.gatherer_started_at is not null
        and dr.gatherer_started_at <= p_now - make_interval(mins => p_stale_minutes)
      )
    )
  returning dr.gatherer_status into v_claimed;

  if v_claimed is not null then
    return 'claimed';
  end if;

  select dr.gatherer_status into v_status
  from public.district_runs dr
  where dr.run_date = p_run_date
    and dr.district = p_district;

  if v_status is null then
    -- No seeded row: create it, and let a racing insert decide the winner.
    begin
      insert into public.district_runs (
        run_date, district, gatherer_status, gatherer_started_at, gatherer_attempts, last_event_at
      )
      values (p_run_date, p_district, 'running', p_now, 1, p_now);
    exception when unique_violation then
      return 'in_progress';
    end;
    return 'claimed';
  end if;

  if v_status = 'completed' then
    return 'already_completed';
  end if;

  return 'in_progress';
end;
$$;

revoke execute on function public.claim_district_gather(date, text, integer, timestamptz) from public;
revoke execute on function public.claim_district_gather(date, text, integer, timestamptz) from anon;
revoke execute on function public.claim_district_gather(date, text, integer, timestamptz) from authenticated;
grant execute on function public.claim_district_gather(date, text, integer, timestamptz) to service_role;
