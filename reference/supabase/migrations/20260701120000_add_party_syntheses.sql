-- Party synthesis persistence for the Democrat and Republican party-lane product.
--
-- One row per (run_date, audience). Both lanes share the same facts_hash to prove
-- they were produced from the same factual snapshot. Neither lane can create a
-- duplicate row. Stale running claims and failed rows can be retried without
-- manual database edits.

create table if not exists public.party_syntheses (
  id                  uuid        primary key default gen_random_uuid(),
  run_date            date        not null,
  audience            text        not null
                                    check (audience in ('democrat', 'republican')),
  status              text        not null default 'queued'
                                    check (status in ('queued', 'running', 'completed', 'failed')),
  facts_hash          text,
  input_snapshot      jsonb,
  synthesis           jsonb,
  methodology_version text,
  model               text,
  attempts            integer     not null default 0 check (attempts >= 0),
  max_attempts        integer     not null default 3 check (max_attempts >= 1),
  claim_id            text,
  claimed_at          timestamptz,
  next_retry_at       timestamptz,
  error_message       text,
  error_code          text,
  completed_at        timestamptz,
  created_at          timestamptz not null default timezone('utc', now()),
  updated_at          timestamptz not null default timezone('utc', now()),
  constraint party_syntheses_unique_run_audience unique (run_date, audience)
);

create trigger set_party_syntheses_updated_at
before update on public.party_syntheses
for each row
execute function public.set_updated_at();

-- RLS: service role only. Public and authenticated clients cannot read or
-- mutate party synthesis rows directly.
alter table public.party_syntheses enable row level security;

revoke all on table public.party_syntheses from public;
revoke all on table public.party_syntheses from anon;
revoke all on table public.party_syntheses from authenticated;

-- ---------------------------------------------------------------------------
-- claim_party_synthesis
--
-- Atomically reserves a party synthesis row for one synthesizer invocation.
-- Creates a queued row if none exists yet, resets stale running claims, then
-- transitions queued → running. Returns true when the claim succeeds.
--
-- Stale threshold: a running claim older than 30 minutes is assumed abandoned.
-- Failed rows must be explicitly reset with reset_party_synthesis before they
-- can be claimed again.
-- ---------------------------------------------------------------------------
create or replace function public.claim_party_synthesis(
  p_run_date   date,
  p_audience   text,
  p_facts_hash text
)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  if p_audience not in ('democrat', 'republican') then
    raise exception 'Invalid audience: %. Must be democrat or republican.', p_audience;
  end if;

  -- Ensure a row exists; a duplicate call is harmless.
  insert into public.party_syntheses (run_date, audience, facts_hash)
  values (p_run_date, p_audience, p_facts_hash)
  on conflict (run_date, audience) do nothing;

  -- Release stale running claims so the synthesizer can retry without operator
  -- intervention.
  update public.party_syntheses ps
  set status       = 'queued',
      claim_id     = null,
      claimed_at   = null,
      error_message = 'stale claim released automatically'
  where ps.run_date  = p_run_date
    and ps.audience  = p_audience
    and ps.status    = 'running'
    and ps.claimed_at < timezone('utc', now()) - interval '30 minutes';

  -- Atomically claim the row. Only queued rows below the attempt cap are
  -- eligible; exhausted rows must be reset explicitly.
  update public.party_syntheses ps
  set status     = 'running',
      facts_hash = p_facts_hash,
      claim_id   = gen_random_uuid()::text,
      claimed_at = timezone('utc', now()),
      attempts   = ps.attempts + 1
  where ps.run_date  = p_run_date
    and ps.audience  = p_audience
    and ps.status    = 'queued'
    and ps.attempts  < ps.max_attempts;

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;

revoke execute on function public.claim_party_synthesis(date, text, text) from public;
revoke execute on function public.claim_party_synthesis(date, text, text) from anon;
revoke execute on function public.claim_party_synthesis(date, text, text) from authenticated;
grant  execute on function public.claim_party_synthesis(date, text, text) to service_role;

-- ---------------------------------------------------------------------------
-- complete_party_synthesis
--
-- Marks a running row as completed and records the synthesis payload. Only
-- the holder of the current claim_id can complete the row, preventing a
-- late-arriving retry from overwriting a successful result.
-- ---------------------------------------------------------------------------
create or replace function public.complete_party_synthesis(
  p_run_date            date,
  p_audience            text,
  p_claim_id            text,
  p_synthesis           jsonb,
  p_methodology_version text,
  p_model               text
)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  update public.party_syntheses ps
  set status               = 'completed',
      synthesis            = p_synthesis,
      methodology_version  = p_methodology_version,
      model                = p_model,
      claim_id             = null,
      claimed_at           = null,
      completed_at         = timezone('utc', now()),
      error_message        = null,
      error_code           = null
  where ps.run_date  = p_run_date
    and ps.audience  = p_audience
    and ps.claim_id  = p_claim_id
    and ps.status    = 'running';

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;

revoke execute on function public.complete_party_synthesis(date, text, text, jsonb, text, text) from public;
revoke execute on function public.complete_party_synthesis(date, text, text, jsonb, text, text) from anon;
revoke execute on function public.complete_party_synthesis(date, text, text, jsonb, text, text) from authenticated;
grant  execute on function public.complete_party_synthesis(date, text, text, jsonb, text, text) to service_role;

-- ---------------------------------------------------------------------------
-- fail_party_synthesis
--
-- Records a terminal failure on a running row. Leaves status as 'failed' so
-- the finalizer can inspect it. Use reset_party_synthesis to re-queue.
-- ---------------------------------------------------------------------------
create or replace function public.fail_party_synthesis(
  p_run_date     date,
  p_audience     text,
  p_claim_id     text,
  p_error_message text,
  p_error_code   text
)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  update public.party_syntheses ps
  set status        = 'failed',
      error_message = p_error_message,
      error_code    = p_error_code,
      claim_id      = null,
      claimed_at    = null
  where ps.run_date  = p_run_date
    and ps.audience  = p_audience
    and ps.claim_id  = p_claim_id
    and ps.status    = 'running';

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;

revoke execute on function public.fail_party_synthesis(date, text, text, text, text) from public;
revoke execute on function public.fail_party_synthesis(date, text, text, text, text) from anon;
revoke execute on function public.fail_party_synthesis(date, text, text, text, text) from authenticated;
grant  execute on function public.fail_party_synthesis(date, text, text, text, text) to service_role;

-- ---------------------------------------------------------------------------
-- reset_party_synthesis
--
-- Resets a failed or exhausted row back to queued so it can be claimed again.
-- Clears the attempt counter to give the row a fresh budget.
-- ---------------------------------------------------------------------------
create or replace function public.reset_party_synthesis(
  p_run_date date,
  p_audience text
)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  update public.party_syntheses ps
  set status        = 'queued',
      attempts      = 0,
      claim_id      = null,
      claimed_at    = null,
      error_message = null,
      error_code    = null,
      next_retry_at = null
  where ps.run_date = p_run_date
    and ps.audience = p_audience
    and ps.status in ('failed', 'queued');

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;

revoke execute on function public.reset_party_synthesis(date, text) from public;
revoke execute on function public.reset_party_synthesis(date, text) from anon;
revoke execute on function public.reset_party_synthesis(date, text) from authenticated;
grant  execute on function public.reset_party_synthesis(date, text) to service_role;
