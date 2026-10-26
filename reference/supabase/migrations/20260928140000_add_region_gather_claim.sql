-- Claim the gather stage for one delivery of one region.
--
-- Pub/Sub delivers at least once and the finalizer republishes recovery
-- attempts, so the same (run_date, region) can arrive more than once. A gather
-- attempt spends a NewsData credit, so a duplicate delivery must be cheap: this
-- claim is the compare-and-set that decides whether *this* delivery does the
-- work. The caller returns immediately when it loses.
--
-- Returns:
--   claimed            this delivery owns the stage; proceed
--   in_progress        another delivery started inside the stale window; skip
--   already_completed  the stage already finished for this run date; skip
--
-- A row still at 'none' is a queued message, not a failure, so it is claimable,
-- as are 'failed' and 'deferred' (a quota window denial). A 'running' row is
-- only claimable once it is older than p_stale_minutes -- the same window the
-- finalizer uses to call an invocation hung.
--
-- The single UPDATE ... WHERE is the whole lock: concurrent claims on one row
-- serialise on the row lock and the loser re-evaluates the predicate against the
-- committed state, which is now 'running' with a fresh started_at.

create or replace function public.claim_region_gather(
  p_run_date date,
  p_region text,
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
  if p_run_date is null or nullif(trim(p_region), '') is null then
    raise exception 'run_date and region are required';
  end if;
  if p_stale_minutes < 1 then
    raise exception 'stale_minutes must be >= 1';
  end if;

  update public.region_runs rr
  set gatherer_status = 'running',
      gatherer_started_at = p_now,
      gatherer_attempts = rr.gatherer_attempts + 1,
      gatherer_last_error = null,
      last_event_at = p_now
  where rr.run_date = p_run_date
    and rr.region = p_region
    and (
      rr.gatherer_status in ('none', 'failed', 'deferred')
      or (
        rr.gatherer_status = 'running'
        and rr.gatherer_started_at is not null
        and rr.gatherer_started_at <= p_now - make_interval(mins => p_stale_minutes)
      )
    )
  returning rr.gatherer_status into v_claimed;

  if v_claimed is not null then
    return 'claimed';
  end if;

  select rr.gatherer_status into v_status
  from public.region_runs rr
  where rr.run_date = p_run_date
    and rr.region = p_region;

  if v_status is null then
    -- No seeded row: a manual publication or a region the orchestrator did not
    -- seed. Create it, and let a racing insert decide the winner.
    begin
      insert into public.region_runs (
        run_date, region, gatherer_status, gatherer_started_at, gatherer_attempts, last_event_at
      )
      values (p_run_date, p_region, 'running', p_now, 1, p_now);
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

revoke execute on function public.claim_region_gather(date, text, integer, timestamptz) from public;
revoke execute on function public.claim_region_gather(date, text, integer, timestamptz) from anon;
revoke execute on function public.claim_region_gather(date, text, integer, timestamptz) from authenticated;
grant execute on function public.claim_region_gather(date, text, integer, timestamptz) to service_role;
