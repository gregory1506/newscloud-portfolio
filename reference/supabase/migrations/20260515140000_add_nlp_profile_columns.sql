-- Add deeper NLP profile columns to regional_sentiment
-- These are computed by the scorer alongside sentiment/leaning scores.

alter table public.regional_sentiment
  add column if not exists emotional_profile jsonb
    not null default '{}'::jsonb,
  add column if not exists entity_profile jsonb
    not null default '{}'::jsonb,
  add column if not exists topic_scores jsonb
    not null default '{}'::jsonb,
  add column if not exists lexical_stats jsonb
    not null default '{}'::jsonb;

comment on column public.regional_sentiment.emotional_profile is
  'NRC-style emotion scores: {"anger": N, "fear": N, "trust": N, "joy": N, "sadness": N, "surprise": N, "disgust": N, "anticipation": N}';

comment on column public.regional_sentiment.entity_profile is
  'Entity categorization: {"persons": {"name": count, ...}, "places": {...}, "organizations": {...}}';

comment on column public.regional_sentiment.topic_scores is
  'Topic cluster scores: {"Economy": N, "Immigration": N, "Crime": N, "Education": N, "Elections": N, "Disaster": N, "Environment": N, "Healthcare": N, "Infrastructure": N, "Civil Rights": N}';

comment on column public.regional_sentiment.lexical_stats is
  'Lexical diversity metrics: {"ttr": 0.20, "entropy": 7.1, "top20_coverage_pct": 24.7, "gini": -0.22, "total_tokens": 733, "unique_types": 150}';

-- Add checks to ensure JSON columns are objects
alter table public.regional_sentiment
  add constraint regional_sentiment_emotional_profile_is_object
    check (jsonb_typeof(emotional_profile) = 'object'),
  add constraint regional_sentiment_entity_profile_is_object
    check (jsonb_typeof(entity_profile) = 'object'),
  add constraint regional_sentiment_topic_scores_is_object
    check (jsonb_typeof(topic_scores) = 'object'),
  add constraint regional_sentiment_lexical_stats_is_object
    check (jsonb_typeof(lexical_stats) = 'object');
