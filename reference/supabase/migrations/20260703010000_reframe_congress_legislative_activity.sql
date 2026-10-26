-- Reframe Congress.gov as incremental legislative activity, not electoral
-- sentiment. Legacy cumulative bill/vote columns remain temporarily for safe
-- rollout but are no longer written by the gatherer.

alter table public.legislative_signals
  add column if not exists dem_bills_introduced integer,
  add column if not exists rep_bills_introduced integer,
  add column if not exists dem_bills_advanced integer,
  add column if not exists rep_bills_advanced integer,
  add column if not exists dem_introduced_per_member numeric,
  add column if not exists rep_introduced_per_member numeric,
  add column if not exists dem_advanced_per_member numeric,
  add column if not exists rep_advanced_per_member numeric,
  add column if not exists dem_policy_areas jsonb,
  add column if not exists rep_policy_areas jsonb,
  add column if not exists congress_coverage numeric;

comment on column public.legislative_signals.congress_coverage is
  '1 when the daily Congress.gov query completed, 0 when unavailable; empty successful days are valid zero activity.';
