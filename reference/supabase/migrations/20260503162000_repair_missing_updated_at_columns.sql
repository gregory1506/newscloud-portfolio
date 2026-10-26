create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

alter table if exists public.word_frequencies
  add column if not exists updated_at timestamptz default timezone('utc', now());

update public.word_frequencies
set updated_at = coalesce(updated_at, created_at, timezone('utc', now()))
where updated_at is null;

alter table if exists public.word_frequencies
  alter column updated_at set default timezone('utc', now()),
  alter column updated_at set not null;

drop trigger if exists set_word_frequencies_updated_at on public.word_frequencies;
create trigger set_word_frequencies_updated_at
before update on public.word_frequencies
for each row
execute function public.set_updated_at();

alter table if exists public.generated_images
  add column if not exists updated_at timestamptz default timezone('utc', now());

update public.generated_images
set updated_at = coalesce(updated_at, created_at, timezone('utc', now()))
where updated_at is null;

alter table if exists public.generated_images
  alter column updated_at set default timezone('utc', now()),
  alter column updated_at set not null;

drop trigger if exists set_generated_images_updated_at on public.generated_images;
create trigger set_generated_images_updated_at
before update on public.generated_images
for each row
execute function public.set_updated_at();

alter table if exists public.regional_sentiment
  add column if not exists updated_at timestamptz default timezone('utc', now());

update public.regional_sentiment
set updated_at = coalesce(updated_at, created_at, timezone('utc', now()))
where updated_at is null;

alter table if exists public.regional_sentiment
  alter column updated_at set default timezone('utc', now()),
  alter column updated_at set not null;

drop trigger if exists set_regional_sentiment_updated_at on public.regional_sentiment;
create trigger set_regional_sentiment_updated_at
before update on public.regional_sentiment
for each row
execute function public.set_updated_at();
