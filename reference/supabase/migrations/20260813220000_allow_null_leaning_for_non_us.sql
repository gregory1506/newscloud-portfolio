-- Non-U.S. regions (TT, UK) are collected for sentiment and wordcloud output
-- only. The scorer's leaning lexicons are US-specific (MAGA, medicare, GOP,
-- deportation), so applying them abroad produces a confident wrong answer
-- rather than a weak one:
--
--   UK 2026-08-12  leaning 1.06/5  driven by "labour" x17 -- the party's name,
--                                  present in every political story regardless
--                                  of slant, weighted 3 in LEFT_LEXICON
--   TT 2026-08-13  leaning 2.46/5  decided entirely by "free" x9, which in T&T
--                                  copy is "free up" / "free transport"
--   TT 2026-08-12  leaning 2.50/5  zero indicator matches -- the neutral prior
--
-- The scorer now writes NULL for these regions. leaning_score must therefore
-- become nullable. The existing range CHECK needs no change: a CHECK passes
-- on NULL under SQL three-valued logic.

alter table public.regional_sentiment
  alter column leaning_score drop not null;

comment on column public.regional_sentiment.leaning_score is
  'Political leaning 0-5 (0=left, 5=right). NULL for non-U.S. regions (TT, UK), '
  'where the US-specific leaning lexicons do not apply. Consumers must treat '
  'NULL as "not measured", never as neutral.';

-- Backfill: clear the historical non-U.S. leaning values. These are artifacts
-- of the US lexicon, not measurements, and leaving them mixes junk numbers
-- with genuine NULLs in the same column. Sentiment, wordcloud, and all other
-- columns are untouched.
update public.regional_sentiment
   set leaning_score   = null,
       left_indicators = '[]'::jsonb,
       right_indicators = '[]'::jsonb
 where region in ('TT', 'UK');
