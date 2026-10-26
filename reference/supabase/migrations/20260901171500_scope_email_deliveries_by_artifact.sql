alter table public.email_deliveries
  add column if not exists region text,
  add column if not exists artifact_type text;

update public.email_deliveries
set region = case
      when subject ilike '%Democratic Lane%' then 'all-states'
      when subject ilike '%Republican Lane%' then 'all-states'
      else 'battleground'
    end,
    artifact_type = case
      when subject ilike '%Democratic Lane%' then 'party_email_democrat'
      when subject ilike '%Republican Lane%' then 'party_email_republican'
      else 'email_brief'
    end
where region is null or artifact_type is null;

alter table public.email_deliveries
  alter column region set default 'battleground',
  alter column region set not null,
  alter column artifact_type set default 'email_brief',
  alter column artifact_type set not null;

alter table public.email_deliveries
  drop constraint if exists email_deliveries_run_date_recipient_email_key;

alter table public.email_deliveries
  add constraint email_deliveries_run_date_artifact_recipient_key
  unique (run_date, region, artifact_type, recipient_email);

create index if not exists email_deliveries_artifact_run_date_idx
  on public.email_deliveries (artifact_type, run_date desc);
