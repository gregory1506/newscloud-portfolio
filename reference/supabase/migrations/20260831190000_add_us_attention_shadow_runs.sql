create table if not exists public.us_attention_shadow_runs (
  id uuid primary key default gen_random_uuid(),
  run_date date not null,
  scope text not null check (scope in ('US', 'US-PA')),
  query_id text not null,
  query_contract_version text not null,
  adapter_version text not null,
  upstream_version text not null,
  upstream_commit text not null,
  upstream_schema_version text not null,
  degraded boolean not null default false,
  source_status jsonb not null default '{}'::jsonb,
  rejected_counts jsonb not null default '{}'::jsonb,
  normalized_payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint us_attention_shadow_runs_idempotency
    unique (run_date, scope, query_id, query_contract_version, adapter_version)
);

create index if not exists us_attention_shadow_runs_review_idx
  on public.us_attention_shadow_runs (run_date desc, scope, degraded);

create trigger set_us_attention_shadow_runs_updated_at
before update on public.us_attention_shadow_runs
for each row execute function public.set_updated_at();

alter table public.us_attention_shadow_runs enable row level security;

revoke all on table public.us_attention_shadow_runs from public;
revoke all on table public.us_attention_shadow_runs from anon;
revoke all on table public.us_attention_shadow_runs from authenticated;

comment on table public.us_attention_shadow_runs is
  'Private last30days attention-signal pilot data. Never an input to canonical coverage, sentiment, favorability, or party scoring.';
