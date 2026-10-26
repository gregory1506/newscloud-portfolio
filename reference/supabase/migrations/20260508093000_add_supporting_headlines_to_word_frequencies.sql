alter table public.word_frequencies
  add column if not exists supporting_headlines jsonb not null default '[]'::jsonb;

alter table public.word_frequencies
  drop constraint if exists word_frequencies_supporting_headlines_is_array;

alter table public.word_frequencies
  add constraint word_frequencies_supporting_headlines_is_array
  check (jsonb_typeof(supporting_headlines) = 'array');
