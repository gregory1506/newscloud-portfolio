create or replace function public.claim_site_export(p_run_date date, p_claim_id text)
returns boolean
language plpgsql
as $$
declare
  updated_count integer;
  stale_claim_before timestamptz := timezone('utc', now()) - interval '60 minutes';
begin
  update public.daily_runs dr
  set status = 'export_claimed',
      export_claim_id = p_claim_id,
      export_claimed_at = timezone('utc', now()),
      updated_at = timezone('utc', now())
  where dr.run_date = p_run_date
    and dr.published_at is null
    and (
      dr.export_claim_id is null
      or (
        dr.status = 'export_claimed'
        and dr.export_claimed_at is not null
        and dr.export_claimed_at < stale_claim_before
      )
    )
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
