-- Account-wide Resend recipient reservations pooled across every sending
-- function: functions/emailer/main.py, functions/intake/main.py, and
-- functions/performance_brief/main.py.
--
-- The Resend free allowance (100/day, 3,000/month) is counted per account, not
-- per function, and each of those functions sends exactly one recipient per
-- provider request. Every sender therefore calls
-- public.reserve_email_recipients(...) immediately before its ``POST
-- https://api.resend.com/emails`` and sends nothing when the grant is 0.
--
-- One shared counter per day and one per calendar month is the only source of
-- truth, so a function can never spend another function's reserved capacity and
-- the ceilings survive instance restarts, retries, and concurrent callers.
--
-- Deploy order: apply this migration before deploying the senders when
-- possible, so no recipients go out unreserved during the rollout. Deploying in
-- the other order is also safe: until public.reserve_email_recipients exists the
-- senders fail open, print one ``email_recipient_budget_unavailable`` marker per
-- instance, and begin enforcing as soon as the function is present.

create table if not exists public.email_recipient_budget (
  period_type text not null check (period_type in ('day', 'month')),
  period_start date not null,
  recipients_reserved integer not null default 0 check (recipients_reserved >= 0),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  primary key (period_type, period_start)
);

alter table public.email_recipient_budget enable row level security;

revoke all on table public.email_recipient_budget from public;
revoke all on table public.email_recipient_budget from anon;
revoke all on table public.email_recipient_budget from authenticated;

-- Reserve p_count recipients atomically. Never partially grants: the day and
-- month counters both advance by p_count or neither does, so callers can treat
-- any non-positive result as "send nothing".
--
-- Returns:
--   p_count  the reservation succeeded (both ceilings allow the recipients)
--   0        the daily ceiling for p_day would be exceeded
--   -1       the monthly ceiling for p_day's calendar month would be exceeded
--
-- The negative sentinel exists only so the caller can log which ceiling paused
-- the send; a grant is always a positive recipient count.
create or replace function public.reserve_email_recipients(
  p_day date,
  p_count integer,
  p_day_limit integer,
  p_month_limit integer
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_month_start date := date_trunc('month', p_day)::date;
  v_day_reserved integer;
  v_month_reserved integer;
begin
  if p_day is null then
    raise exception 'day is required';
  end if;
  if p_count is null or p_count < 1 then
    raise exception 'count must be >= 1';
  end if;
  if p_day_limit is null or p_day_limit < 1 then
    raise exception 'day_limit must be >= 1';
  end if;
  if p_month_limit is null or p_month_limit < 1 then
    raise exception 'month_limit must be >= 1';
  end if;

  -- One constant key serialises every reservation, so the two reads, the
  -- insert, and the increment below are a single atomic check-and-add across
  -- instances and concurrent callers. The lock is transaction scoped: a
  -- crashed caller can never leave the budget locked.
  perform pg_advisory_xact_lock(hashtext('newscloud.email_recipient_budget'));

  insert into public.email_recipient_budget (period_type, period_start)
  values ('day', p_day), ('month', v_month_start)
  on conflict (period_type, period_start) do nothing;

  select recipients_reserved into v_day_reserved
  from public.email_recipient_budget
  where period_type = 'day' and period_start = p_day
  for update;

  select recipients_reserved into v_month_reserved
  from public.email_recipient_budget
  where period_type = 'month' and period_start = v_month_start
  for update;

  if v_day_reserved + p_count > p_day_limit then
    return 0;
  end if;

  if v_month_reserved + p_count > p_month_limit then
    return -1;
  end if;

  update public.email_recipient_budget
  set recipients_reserved = recipients_reserved + p_count,
      updated_at = timezone('utc', now())
  where (period_type = 'day' and period_start = p_day)
     or (period_type = 'month' and period_start = v_month_start);

  return p_count;
end;
$$;

revoke execute on function public.reserve_email_recipients(date, integer, integer, integer) from public;
revoke execute on function public.reserve_email_recipients(date, integer, integer, integer) from anon;
revoke execute on function public.reserve_email_recipients(date, integer, integer, integer) from authenticated;
grant execute on function public.reserve_email_recipients(date, integer, integer, integer) to service_role;
