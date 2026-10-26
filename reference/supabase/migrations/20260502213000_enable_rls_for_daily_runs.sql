alter table public.daily_runs enable row level security;

revoke all on table public.daily_runs from public;
revoke all on table public.daily_runs from anon;
revoke all on table public.daily_runs from authenticated;

revoke execute on function public.claim_site_export(date, text) from public;
revoke execute on function public.claim_site_export(date, text) from anon;
revoke execute on function public.claim_site_export(date, text) from authenticated;

revoke execute on function public.release_site_export_claim(date, text) from public;
revoke execute on function public.release_site_export_claim(date, text) from anon;
revoke execute on function public.release_site_export_claim(date, text) from authenticated;

revoke execute on function public.mark_site_export_published(date, text) from public;
revoke execute on function public.mark_site_export_published(date, text) from anon;
revoke execute on function public.mark_site_export_published(date, text) from authenticated;
