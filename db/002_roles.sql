-- Roles. Passwords come from psql vars: -v app_pw=... -v ro_pw=... -v audit_pw=...
do $$ begin
  if not exists (select from pg_roles where rolname='sd_app') then create role sd_app login; end if;
  if not exists (select from pg_roles where rolname='sd_readonly') then create role sd_readonly login; end if;
  if not exists (select from pg_roles where rolname='sd_audit_writer') then create role sd_audit_writer login; end if;
  if not exists (select from pg_roles where rolname='sd_scorer') then create role sd_scorer login; end if;
end $$;
alter role sd_app password :'app_pw';
alter role sd_readonly password :'ro_pw';
alter role sd_audit_writer password :'audit_pw';

revoke all on schema public from public;
revoke all on all tables in schema app, audit from public;

grant usage on schema app to sd_app, sd_readonly, sd_scorer;
grant select, insert, update, delete on all tables in schema app to sd_app;
grant usage on all sequences in schema app to sd_app;

-- sd_readonly: SELECT on the two views only. No base tables, no audit, no server-file roles.
grant select on app.v_cases, app.v_pair_scores to sd_readonly;
alter role sd_readonly set default_transaction_read_only = on;
alter role sd_readonly set statement_timeout = '5s';

-- Audit: INSERT only (plus the chain-tip function). Nobody gets UPDATE/DELETE/TRUNCATE.
grant usage on schema audit to sd_audit_writer, sd_scorer;
revoke all on audit.audit_log from sd_app, sd_readonly, sd_audit_writer;
grant insert on audit.audit_log to sd_audit_writer;
grant usage on sequence audit.audit_log_seq_seq to sd_audit_writer;
revoke all on function audit.last_hash() from public;
grant execute on function audit.last_hash() to sd_audit_writer;

-- Scorer reads everything in app + audit, post-session only (it is the only role with sealed_db CONNECT).
grant select on all tables in schema app, audit to sd_scorer;
