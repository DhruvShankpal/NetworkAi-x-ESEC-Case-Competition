-- CaseWeb UI support: undo for decisions, session start day. Run as owner against `seriesdesk`.
alter table app.link_decisions add column if not exists undone_at timestamptz;
alter table app.link_decisions add column if not exists session_id text;
alter table app.replay_state add column if not exists start_date date;
alter table app.replay_state add column if not exists analyst text;
alter table app.replay_state add column if not exists ended_at timestamptz;
grant select, insert, update on app.link_decisions, app.replay_state to sd_app;
