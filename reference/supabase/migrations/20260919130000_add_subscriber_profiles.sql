-- Race Board subscriber profiles: consent, acquisition source, and a light
-- demographic survey for the free consumer track.
--
-- Phase 4 (GR3-519) of docs/race-board-phased-plan.md. Delivery routing stays in
-- subscriptions; this table holds the profile/consent record and supports
-- deletion (soft delete via deleted_at, plus operator hard delete).
--
-- Service-role only: profiles are never exposed to the public bundle.

create table if not exists public.subscriber_profiles (
  id                uuid        primary key default gen_random_uuid(),
  email             text        not null unique,
  consent_version   text        not null,
  signup_source     text        not null default 'public',
  utm               jsonb       not null default '{}'::jsonb,
  role              text,
  states            text[]      not null default '{}',
  lean_preference   text,
  cadence           text,
  unsubscribe_token text        not null default replace(gen_random_uuid()::text, '-', ''),
  deleted_at        timestamptz,
  created_at        timestamptz not null default timezone('utc', now()),
  updated_at        timestamptz not null default timezone('utc', now())
);

create index if not exists subscriber_profiles_token_idx
  on public.subscriber_profiles (unsubscribe_token);

create trigger set_subscriber_profiles_updated_at
before update on public.subscriber_profiles
for each row
execute function public.set_updated_at();

alter table public.subscriber_profiles enable row level security;

revoke all on table public.subscriber_profiles from public;
revoke all on table public.subscriber_profiles from anon;
revoke all on table public.subscriber_profiles from authenticated;
