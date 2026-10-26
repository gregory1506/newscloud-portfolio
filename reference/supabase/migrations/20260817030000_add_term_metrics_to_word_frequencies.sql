alter table public.word_frequencies
  add column if not exists term_metrics jsonb not null default '{}'::jsonb;

alter table public.word_frequencies
  drop constraint if exists word_frequencies_term_metrics_is_object;

alter table public.word_frequencies
  add constraint word_frequencies_term_metrics_is_object
  check (jsonb_typeof(term_metrics) = 'object');
