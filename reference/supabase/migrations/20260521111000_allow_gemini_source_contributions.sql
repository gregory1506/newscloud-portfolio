alter table public.source_contributions
  drop constraint if exists source_contributions_provider_check;

alter table public.source_contributions
  add constraint source_contributions_provider_check
  check (provider in ('rss', 'brave_news', 'newsdata_io', 'gemini_google_search'));
