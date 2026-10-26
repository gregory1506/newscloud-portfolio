create table if not exists public.daily_runs (
  run_date date primary key,
  expected_region_count integer not null check (expected_region_count > 0),
  expected_regions jsonb not null default '[]'::jsonb,
  status text not null default 'running'
    check (status in ('running', 'export_claimed', 'published')),
  export_claim_id text,
  export_claimed_at timestamptz,
  published_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint daily_runs_expected_regions_is_array
    check (jsonb_typeof(expected_regions) = 'array')
);

create trigger set_daily_runs_updated_at
before update on public.daily_runs
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
    and dr.published_at is null
    and dr.export_claim_id is null
    and (
      select count(*)
      from public.regional_sentiment rs
      where rs.date = p_run_date
    ) >= dr.expected_region_count
    and (
      select count(*)
      from public.generated_images gi
      where gi.date = p_run_date
    ) >= dr.expected_region_count;

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
  set status = 'running',
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

create or replace function public.mark_site_export_published(p_run_date date, p_claim_id text)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
begin
  update public.daily_runs dr
  set status = 'published',
      export_claim_id = null,
      published_at = timezone('utc', now()),
      updated_at = timezone('utc', now())
  where dr.run_date = p_run_date
    and dr.published_at is null
    and dr.export_claim_id = p_claim_id;

  get diagnostics updated_count = row_count;
  return updated_count = 1;
end;
$$;
