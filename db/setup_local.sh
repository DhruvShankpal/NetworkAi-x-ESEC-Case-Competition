#!/usr/bin/env bash
# Local dev DB bootstrap (no Docker needed). Reads passwords from .env.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
pw() { python3 -c "import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).password)" "$1"; }
PSQL="sudo -u postgres psql -v ON_ERROR_STOP=1 -q"
$PSQL -tc "select 1 from pg_database where datname='seriesdesk'" | grep -q 1 || $PSQL -c "create database seriesdesk"
$PSQL -d seriesdesk -f db/001_schema.sql
$PSQL -d seriesdesk -v app_pw="$(pw "$DATABASE_URL")" -v ro_pw="$(pw "$SD_READONLY_DSN")" \
      -v audit_pw="$(pw "$SD_AUDIT_DSN")" -f db/002_roles.sql
$PSQL -tc "select 1 from pg_database where datname='sealed_db'" | grep -q 1 || $PSQL -c "create database sealed_db"
$PSQL -c "revoke connect on database sealed_db from public"
$PSQL -c "grant connect on database sealed_db to sd_scorer"
$PSQL -d sealed_db -f db/010_sealed.sql
echo "seriesdesk + sealed_db ready"
