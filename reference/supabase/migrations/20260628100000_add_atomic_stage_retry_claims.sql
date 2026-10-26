alter table public.region_runs
  add column if not exists gatherer_recovery_attempts integer not null default 0
    check (gatherer_recovery_attempts >= 0),
  add column if not exists scorer_recovery_attempts integer not null default 0
    check (scorer_recovery_attempts >= 0),
  add column if not exists generator_recovery_attempts integer not null default 0
    check (generator_recovery_attempts >= 0);

create or replace function public.claim_region_stage_retry(
  p_run_date date,
  p_region text,
  p_stage text,
  p_next_retry_at timestamptz,
  p_max_attempts integer,
  p_allow_recovery boolean default false,
  p_max_recoveries integer default 1
)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  if p_stage not in ('gatherer', 'scorer', 'generator') then
    raise exception 'Unsupported pipeline stage: %', p_stage;
  end if;
  if p_max_attempts < 1 or p_max_recoveries < 0 then
    raise exception 'Retry limits must be non-negative and max attempts must be positive.';
  end if;

  if p_stage = 'gatherer' then
    update public.region_runs rr
    set next_retry_at = p_next_retry_at,
        gatherer_attempts = case
          when rr.gatherer_attempts >= p_max_attempts then 0
          else rr.gatherer_attempts
        end,
        gatherer_recovery_attempts = case
          when rr.gatherer_attempts >= p_max_attempts then rr.gatherer_recovery_attempts + 1
          else rr.gatherer_recovery_attempts
        end,
        last_event_at = timezone('utc', now())
    where rr.run_date = p_run_date
      and rr.region = p_region
      and rr.gatherer_status <> 'completed'
      and (rr.next_retry_at is null or rr.next_retry_at <= timezone('utc', now()))
      and (
        rr.gatherer_attempts < p_max_attempts
        or (
          p_allow_recovery
          and rr.gatherer_attempts >= p_max_attempts
          and rr.gatherer_recovery_attempts < p_max_recoveries
        )
      );
  elsif p_stage = 'scorer' then
    update public.region_runs rr
    set next_retry_at = p_next_retry_at,
        scorer_attempts = case
          when rr.scorer_attempts >= p_max_attempts then 0
          else rr.scorer_attempts
        end,
        scorer_recovery_attempts = case
          when rr.scorer_attempts >= p_max_attempts then rr.scorer_recovery_attempts + 1
          else rr.scorer_recovery_attempts
        end,
        last_event_at = timezone('utc', now())
    where rr.run_date = p_run_date
      and rr.region = p_region
      and rr.scorer_status <> 'completed'
      and (rr.next_retry_at is null or rr.next_retry_at <= timezone('utc', now()))
      and (
        rr.scorer_attempts < p_max_attempts
        or (
          p_allow_recovery
          and rr.scorer_attempts >= p_max_attempts
          and rr.scorer_recovery_attempts < p_max_recoveries
        )
      );
  else
    update public.region_runs rr
    set next_retry_at = p_next_retry_at,
        generator_attempts = case
          when rr.generator_attempts >= p_max_attempts then 0
          else rr.generator_attempts
        end,
        generator_recovery_attempts = case
          when rr.generator_attempts >= p_max_attempts then rr.generator_recovery_attempts + 1
          else rr.generator_recovery_attempts
        end,
        last_event_at = timezone('utc', now())
    where rr.run_date = p_run_date
      and rr.region = p_region
      and rr.generator_status <> 'completed'
      and (rr.next_retry_at is null or rr.next_retry_at <= timezone('utc', now()))
      and (
        rr.generator_attempts < p_max_attempts
        or (
          p_allow_recovery
          and rr.generator_attempts >= p_max_attempts
          and rr.generator_recovery_attempts < p_max_recoveries
        )
      );
  end if;

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;

revoke execute on function public.claim_region_stage_retry(date, text, text, timestamptz, integer, boolean, integer) from public;
revoke execute on function public.claim_region_stage_retry(date, text, text, timestamptz, integer, boolean, integer) from anon;
revoke execute on function public.claim_region_stage_retry(date, text, text, timestamptz, integer, boolean, integer) from authenticated;
grant execute on function public.claim_region_stage_retry(date, text, text, timestamptz, integer, boolean, integer) to service_role;
