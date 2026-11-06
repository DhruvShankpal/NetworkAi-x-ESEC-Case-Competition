-- Run on the TEAMMATE'S machine, against a separate database `sealed_db` owned by a separate role.
-- App roles get no CONNECT. Only sd_scorer, after session_end.
create table if not exists answer_key (
  case_id text primary key, true_series_id text, is_decoy boolean, notes text);
