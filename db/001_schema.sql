-- Series Desk schema. Run as a superuser/owner against database `seriesdesk`.
create extension if not exists postgis;
create extension if not exists pgcrypto;
create schema if not exists app;
create schema if not exists audit;

create table if not exists app.datasets (
  dataset_id text primary key, seed bigint, generator_sha text, created_at timestamptz default now(), meta jsonb);

create table if not exists app.incidents (
  case_id text primary key,
  source text not null check (source in ('spd_open','synthetic','blind')),
  dataset_id text references app.datasets,
  report_number_hash text,
  offense_start timestamptz, offense_end timestamptz, reported_at timestamptz,
  nibrs_code text, nibrs_desc text,
  beat text, sector text, precinct text, mcpp text, district_fictional text,
  geom geography(Point,4326),
  narrative text,
  narrative_origin text check (narrative_origin in ('synthetic_llm','synthetic_template','anonymized_public')),
  replay_visible_on date not null,
  ingested_at timestamptz default now()
);
create index if not exists incidents_geom_gix on app.incidents using gist (geom);
create index if not exists incidents_start_ix on app.incidents (offense_start);
create index if not exists incidents_visible_ix on app.incidents (replay_visible_on);

create table if not exists app.mo_features (
  extraction_id uuid primary key default gen_random_uuid(),
  case_id text not null references app.incidents,
  features jsonb not null, field_confidence jsonb, evidence_spans jsonb,
  model_id text not null, prompt_version text not null, schema_version text not null,
  extracted_at timestamptz default now(), is_current boolean default true
);
create unique index if not exists mo_current_uq on app.mo_features (case_id) where is_current;
create index if not exists mo_features_gin on app.mo_features using gin (features jsonb_path_ops);

create table if not exists app.pair_scores (
  case_a text references app.incidents, case_b text references app.incidents,
  block text check (block in ('local','corridor')),
  distance_km real, days_apart real, mo_jaccard real,
  prob real not null, contributions jsonb not null,
  model_version text not null, scored_at timestamptz default now(),
  primary key (case_a, case_b, model_version),
  check (case_a < case_b)
);
create index if not exists pair_scores_prob_ix on app.pair_scores (prob desc);

create table if not exists app.series (
  series_id uuid primary key default gen_random_uuid(), label text,
  status text check (status in ('candidate','active','closed','rejected')),
  created_at timestamptz default now(), created_by text);
create table if not exists app.series_members (
  series_id uuid references app.series, case_id text references app.incidents,
  added_via text check (added_via in ('accepted_link','manual')), added_at timestamptz, added_by text,
  primary key (series_id, case_id));

create table if not exists app.link_decisions (
  decision_id uuid primary key default gen_random_uuid(), case_a text, case_b text, series_id uuid,
  model_version text, prob_shown real, contributions_shown jsonb,
  decision text check (decision in ('accept','reject','defer')),
  reason_code text not null, free_text text, decided_by text not null,
  decided_at timestamptz not null, ui_shown_at timestamptz not null, clicks int not null);

create table if not exists app.sleeper_queue (
  case_id text primary key references app.incidents,
  status text check (status in ('screening','sleeping','awake','routed')),
  screener text, sergeant_audit boolean default false, sergeant_approved_by text,
  last_rescored_at timestamptz, woke_by_pair jsonb);

create table if not exists app.evidence_release (
  evidence_id uuid primary key default gen_random_uuid(), case_id text references app.incidents,
  kind text check (kind in ('latent_print','dna','video','other')),
  release_on_replay_date date not null, payload jsonb, released boolean default false);

create table if not exists app.replay_state (
  session_id text primary key, current_replay_date date not null, updated_at timestamptz default now());

-- Read-only surface for agents/MCP. Exposes lat/lon (not raw geom) and only current MO.
create or replace view app.v_cases as
  select i.case_id, i.source, i.offense_start, i.offense_end, i.reported_at, i.nibrs_code, i.nibrs_desc,
         i.district_fictional, st_y(i.geom::geometry) as lat, st_x(i.geom::geometry) as lon,
         i.narrative, i.narrative_origin, i.replay_visible_on, m.features as mo, m.evidence_spans,
         m.extraction_id, m.model_id, m.prompt_version
  from app.incidents i left join app.mo_features m on m.case_id = i.case_id and m.is_current;
create or replace view app.v_pair_scores as select * from app.pair_scores;

create table if not exists audit.audit_log (
  seq bigserial primary key, event_id uuid not null, ts timestamptz not null default now(),
  actor text not null, actor_type text check (actor_type in ('human','agent','system')),
  tool text, args jsonb, result_count int,
  fact_source jsonb, inferred jsonb, human_checked jsonb, action_taken text,
  prev_hash bytea not null, row_hash bytea not null unique);

create or replace function audit.forbid_mutation() returns trigger language plpgsql as $$
begin raise exception 'audit.audit_log is append-only'; end $$;
drop trigger if exists audit_no_update on audit.audit_log;
create trigger audit_no_update before update or delete on audit.audit_log
  for each row execute function audit.forbid_mutation();
drop trigger if exists audit_no_truncate on audit.audit_log;
create trigger audit_no_truncate before truncate on audit.audit_log
  for each statement execute function audit.forbid_mutation();

-- Lets the INSERT-only writer read the chain tip without SELECT on the table.
create or replace function audit.last_hash() returns bytea language sql stable security definer
  set search_path = audit, pg_temp as $$ select row_hash from audit.audit_log order by seq desc limit 1 $$;
