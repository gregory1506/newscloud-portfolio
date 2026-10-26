alter table public.word_frequencies
  add column if not exists topic_clusters jsonb not null default '{}'::jsonb;

alter table public.word_frequencies
  drop constraint if exists word_frequencies_topic_clusters_is_object;

alter table public.word_frequencies
  add constraint word_frequencies_topic_clusters_is_object
  check (jsonb_typeof(topic_clusters) = 'object');

comment on column public.word_frequencies.topic_clusters is
  'Versioned story-level topic clusters derived from sanitized headline and excerpt metadata for approved non-US regions.';
