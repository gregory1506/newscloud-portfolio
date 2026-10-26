alter table public.word_frequencies enable row level security;
alter table public.generated_images enable row level security;
alter table public.regional_sentiment enable row level security;
alter table public.source_contributions enable row level security;
alter table public.region_runs enable row level security;
alter table public.email_recipients enable row level security;
alter table public.email_deliveries enable row level security;

revoke all on table public.word_frequencies from public;
revoke all on table public.word_frequencies from anon;
revoke all on table public.word_frequencies from authenticated;

revoke all on table public.generated_images from public;
revoke all on table public.generated_images from anon;
revoke all on table public.generated_images from authenticated;

revoke all on table public.regional_sentiment from public;
revoke all on table public.regional_sentiment from anon;
revoke all on table public.regional_sentiment from authenticated;

revoke all on table public.source_contributions from public;
revoke all on table public.source_contributions from anon;
revoke all on table public.source_contributions from authenticated;

revoke all on table public.region_runs from public;
revoke all on table public.region_runs from anon;
revoke all on table public.region_runs from authenticated;

revoke all on table public.email_recipients from public;
revoke all on table public.email_recipients from anon;
revoke all on table public.email_recipients from authenticated;

revoke all on table public.email_deliveries from public;
revoke all on table public.email_deliveries from anon;
revoke all on table public.email_deliveries from authenticated;

revoke execute on function public.set_updated_at() from public;
revoke execute on function public.set_updated_at() from anon;
revoke execute on function public.set_updated_at() from authenticated;
