-- Phase 5: Add audience column to artifacts, subscriptions, and delivery_jobs.
--
-- Legacy rows retain audience = null (battleground email_brief product).
-- Party-lane rows use 'democrat' or 'republican'.
--
-- Distinct artifact_type values (party_email_democrat / party_email_republican)
-- already enforce uniqueness per audience, so the existing unique constraint on
-- artifacts does not need to change. The audience column is a queryable field.

alter table public.artifacts
  add column if not exists audience text
  check (audience is null or audience in ('democrat', 'republican'));

alter table public.subscriptions
  add column if not exists audience text
  check (audience is null or audience in ('democrat', 'republican'));

alter table public.delivery_jobs
  add column if not exists audience text
  check (audience is null or audience in ('democrat', 'republican'));

-- Efficient lookup by audience for party-lane artifact queries.
create index if not exists artifacts_audience_run_date_idx
  on public.artifacts (audience, run_date desc)
  where audience is not null;
