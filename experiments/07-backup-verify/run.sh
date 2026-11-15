#!/usr/bin/env bash
# Usage: run.sh <backup-verify checkout> <workdir>. Everything is synthetic and lives under <workdir>.
# Needs restic and the pgserver wheel's postgres on PATH (see README). Prints one line per case.
set -u
BV=$(realpath "$1"); W=$(realpath -m "$2"); rm -rf "$W"; mkdir -p "$W"/{src,scratch,repo,plan}
PGBIN=${PGBIN:?path to postgres bin dir}; export PATH="$PGBIN:$PATH"
export RESTIC_PASSWORD=throwaway
start() { # dir port
  initdb -D "$1" -U postgres --auth=trust >/dev/null && pg_ctl -D "$1" -o "-p $2 -k $W -c listen_addresses=''" -l "$1.log" -w start >/dev/null; }
start "$W/src" 55432; start "$W/scratch" 55433
trap 'pg_ctl -D "$W/src" -m immediate stop >/dev/null 2>&1; pg_ctl -D "$W/scratch" -m immediate stop >/dev/null 2>&1' EXIT
psql -h "$W" -p 55432 -U postgres -qc "create table users as select g id, now() - (g||' seconds')::interval created from generate_series(1,5000) g"
mkdir "$W/dump"; pg_dump -h "$W" -p 55432 -U postgres > "$W/dump/dump.sql"
restic -r "$W/repo" init -q; restic -r "$W/repo" backup -q "$W/dump"

plan() { # name expect_min extra-load-prefix
cat > "$W/plan/$1.yaml" <<YAML
fetch: {type: restic, repository: $W/repo, snapshot: latest}
restore:
  load_command: |
    psql -h $W -p 55433 -U postgres -q -c 'drop schema public cascade; create schema public' && \
    psql -h $W -p 55433 -U postgres -q -v ON_ERROR_STOP=1 -f \$(find . -name dump.sql | head -1)
checks:
  - {name: rows, command: "psql -h $W -p 55433 -U postgres -tAc 'select count(*) from users'", expect_min: $2}
  - {name: newest row age seconds, command: "psql -h $W -p 55433 -U postgres -tAc \"select extract(epoch from now()-max(created))::int from users\"", expect_max: 600}
notify: {history_file: $W/history-$1.jsonl}
YAML
}
run() { python3 "$BV/backup_verify.py" run "$W/plan/$1.yaml" >"$W/$1.out" 2>&1; echo "$1 exit=$? $(tail -n 3 "$W/$1.out" | tr '\n' '|')"; }

plan good 5000;     run good
plan floor_high 6000; run floor_high
# corrupt the backup: new snapshot with a truncated dump
head -c 2000 "$W/dump/dump.sql" > "$W/dump/d2" && mv "$W/dump/d2" "$W/dump/dump.sql"; restic -r "$W/repo" backup -q "$W/dump"
plan truncated 5000; run truncated
