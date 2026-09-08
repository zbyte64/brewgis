#!/usr/bin/env bash
#
# check-sqlmesh-hang.sh — diagnose whether a running `sqlmesh plan` is
# progressing or hung (deadlocked).
#
# Detects the deadlock signature observed in the DuckDB staging fetches
# (duckdb.*.overture_* models): process alive, threads parked on futexes,
# ~1-5 ticks/s of CPU on a SINGLE thread in a periodic burst, zero network
# packets, zero disk writes. A healthy run shows either real network
# traffic (downloads), real disk writes (cache/materialization), or
# sustained multi-thread CPU (scan/transform).
#
# Usage:
#   scripts/check-sqlmesh-hang.sh [options]
#
# Options:
#   -c, --container NAME   sqlmesh run container (auto-discovered if omitted:
#                          newest `brewgis-django-run-*` running `sqlmesh plan`)
#   -s, --seconds N        sampling window in seconds (default 30)
#       --pg               also probe Postgres backends + recent state activity
#   -h, --help
#
# Exit codes:
#   0  PROGRESSING — network/disk/compute activity consistent with real work
#   1  HUNG — deadlock signature: low single-thread churn, no I/O
#   2  FROZEN / INCONCLUSIVE — no activity at all, or window too short
#   3  error (no container found, docker unavailable, bad args)
#
set -u

DUR=30
CONTAINER=""
CHECK_PG=0
SELF=$(basename "$0")

usage() {
    sed -n '2,39p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        -c|--container) CONTAINER="${2:-}"; shift 2 ;;
        -s|--seconds)   DUR="${2:-}"; shift 2 ;;
        --pg)           CHECK_PG=1; shift ;;
        -h|--help)      usage ;;
        *) echo "$SELF: unknown option: $1" >&2; echo "try: $SELF --help" >&2; exit 3 ;;
    esac
done

case "$DUR" in
    ''|*[!0-9]*) echo "$SELF: --seconds must be a positive integer" >&2; exit 3 ;;
    *) [ "$DUR" -ge 5 ] || { echo "$SELF: --seconds must be >= 5" >&2; exit 3; } ;;
esac

command -v docker >/dev/null 2>&1 || { echo "$SELF: docker not found" >&2; exit 3; }
docker info >/dev/null 2>&1 || { echo "$SELF: docker daemon not reachable" >&2; exit 3; }

# ── Discover the sqlmesh plan container ────────────────────────────────
if [ -z "$CONTAINER" ]; then
    # docker ps truncates {{.Command}}, so match by name, then inspect the
    # real argv (Config.Cmd) for sqlmesh + plan.
    candidates=$(docker ps --format '{{.Names}}' | awk '/^brewgis-django-run/ {print $1}')
    keep=""
    for c in $candidates; do
        case "$(docker inspect -f '{{json .Config.Cmd}}' "$c" 2>/dev/null)" in
            *sqlmesh*plan*) keep="$keep $c" ;;
        esac
    done
    [ -n "$keep" ] || {
        echo "$SELF: no running 'brewgis-django-run-*' container executing 'sqlmesh ... plan'" >&2
        exit 3
    }
    latest=""; latest_ts=0
    for c in $keep; do
        ts=$(docker inspect -f '{{.State.StartedAt}}' "$c" 2>/dev/null | date -u -f - +%s 2>/dev/null || echo 0)
        if [ "$ts" -gt "$latest_ts" ]; then latest_ts=$ts; latest=$c; fi
    done
    CONTAINER=$latest
fi

docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "$SELF: container '$CONTAINER' not found" >&2; exit 3; }

started=$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER")
up_s=$(date -u -d "$started" +%s 2>/dev/null || echo 0)
now_s=$(date -u +%s)
uptime_min=$(( (now_s - up_s) / 60 ))
cmd=$(docker inspect -f '{{.Config.Cmd}}' "$CONTAINER" | tr -d '[]' | tr ',' ' ')

echo "container : $CONTAINER"
echo "cmd       :$cmd"
echo "started   : $started  (up ${uptime_min} min)"
echo "window    : ${DUR}s"
echo

# ── Timed probe inside the container ───────────────────────────────────
# One docker exec runs the whole window (t0 -> sleep -> t1) and emits
# key=value lines; all values are single-line eval-safe.
PROBE=$(docker exec -i "$CONTAINER" bash -s -- "$DUR" 2>&1 <<'INNER'

# ===== inner probe: runs inside the container (bash -s -- DUR) =====
DUR=$1
ticks() { awk '{print $14+$15}' /proc/1/stat 2>/dev/null || echo 0; }
IFACE=$(awk 'NR>1 && $1 ~ /^eth[0-9]+:/ {print $1; exit}' /proc/1/net/dev 2>/dev/null)
IFACE=${IFACE%:}
[ -n "$IFACE" ] || IFACE=eth0
netrx() { awk -v i="$IFACE:" '$1==i{print $2}' /proc/1/net/dev; }
nettx() { awk -v i="$IFACE:" '$1==i{print $10}' /proc/1/net/dev; }

CPU_T0=$(ticks)
RX_T0=$(netrx)
TX_T0=$(nettx)
THREADS_T0=$(ls /proc/1/task 2>/dev/null | wc -l)
TMP0=$(mktemp)
for t in /proc/1/task/*; do
    echo "$(basename "$t") $(awk '{print $14+$15}' "$t/stat" 2>/dev/null)"
done > "$TMP0"
WAL_T0=$(stat -c %Y /app/planning/duckdb_cache.db.wal 2>/dev/null || echo 0)
CACHE_T0=$(ls -t /app/planning/http_cache 2>/dev/null | head -1 \
    | xargs -r -I{} stat -c %Y "/app/planning/http_cache/{}" 2>/dev/null || echo 0)
LOG_T0=$(ls -t /app/logs/sqlmesh_*.log 2>/dev/null | head -1 \
    | xargs -r stat -c %Y 2>/dev/null || echo 0)

sleep "$DUR"

CPU_T1=$(ticks)
RX_T1=$(netrx)
TX_T1=$(nettx)
THREADS_T1=$(ls /proc/1/task 2>/dev/null | wc -l)
WAL_T1=$(stat -c %Y /app/planning/duckdb_cache.db.wal 2>/dev/null || echo 0)
CACHE_T1=$(ls -t /app/planning/http_cache 2>/dev/null | head -1 \
    | xargs -r -I{} stat -c %Y "/app/planning/http_cache/{}" 2>/dev/null || echo 0)
LOG_T1=$(ls -t /app/logs/sqlmesh_*.log 2>/dev/null | head -1 \
    | xargs -r stat -c %Y 2>/dev/null || echo 0)

# per-thread tick deltas -> top 3 as "tid:ticks;tid:ticks;..."
TMP1=$(mktemp)
for t in /proc/1/task/*; do
    echo "$(basename "$t") $(awk '{print $14+$15}' "$t/stat" 2>/dev/null)"
done > "$TMP1"
TOP_DELTAS=$(awk 'NR==FNR{a[$1]=$2; next}{d=$2-a[$1]; if(d<0)d=0; print $1, d}' \
    "$TMP0" "$TMP1" | sort -k2 -rn | head -3 \
    | awk '$2>0 {printf "%s:%s;", $1, $2}' | sed 's/;$//')
rm -f "$TMP0" "$TMP1"

CPU_DELTA=$((CPU_T1 - CPU_T0))
[ "$CPU_DELTA" -lt 0 ] && CPU_DELTA=0
RX_DELTA=$((RX_T1 - RX_T0))
TX_DELTA=$((TX_T1 - TX_T0))
CPU_PCT=$(awk -v d="$CPU_DELTA" -v w="$DUR" 'BEGIN{printf "%.1f", d / w}')
read SOCK_EST SOCK_EXT < <(cat /proc/1/net/tcp /proc/1/net/tcp6 2>/dev/null \
    | awk 'NR>1 && $4=="01"{c++; split($3,a,":"); if(a[2]=="1BB"||a[2]=="50")e++}
           END{print c+0, e+0}')
WCHAN_HIST=$(for t in /proc/1/task/*; do cat "$t/wchan" 2>/dev/null; echo; done \
    | sort | uniq -c | awk '{printf "%s:%s,", $2, $1}' | sed 's/,$//')
WRITES=0
{ [ "$WAL_T1" -gt "$WAL_T0" ] || [ "$CACHE_T1" -gt "$CACHE_T0" ] || [ "$LOG_T1" -gt "$LOG_T0" ]; } && WRITES=1

echo "CPU_T0=$CPU_T0"
echo "CPU_T1=$CPU_T1"
echo "CPU_DELTA=$CPU_DELTA"
echo "CPU_PCT=$CPU_PCT"
echo "THREADS_T0=$THREADS_T0"
echo "THREADS_T1=$THREADS_T1"
echo "RX_T0=$RX_T0"
echo "RX_T1=$RX_T1"
echo "RX_DELTA=$RX_DELTA"
echo "TX_T0=$TX_T0"
echo "TX_T1=$TX_T1"
echo "TX_DELTA=$TX_DELTA"
echo "WAL_T0=$WAL_T0"
echo "WAL_T1=$WAL_T1"
echo "CACHE_T0=$CACHE_T0"
echo "CACHE_T1=$CACHE_T1"
echo "LOG_T0=$LOG_T0"
echo "LOG_T1=$LOG_T1"
echo "TOP_DELTAS='$TOP_DELTAS'"
echo "WCHAN_HIST='$WCHAN_HIST'"
echo "SOCK_EST=$SOCK_EST"
echo "SOCK_EXT=$SOCK_EXT"
echo "WRITES=$WRITES"
INNER
) || {
    echo "$SELF: probe failed in container: $PROBE" >&2
    exit 3
}
eval "$PROBE"

echo "--- snapshot t0 --------------------------------------------------"
echo "cpu_ticks        : $CPU_T0          threads: $THREADS_T0"
echo "eth0 rx/tx       : $RX_T0 / $TX_T0"
echo "wal mtime        : $WAL_T0          newest cache: $CACHE_T0   newest log: $LOG_T0"
echo
echo "--- snapshot t1 (after ${DUR}s) -----------------------------------"
echo "cpu_ticks        : $CPU_T1   delta: $CPU_DELTA  (${CPU_PCT}% of one core)"
echo "cpu attribution  : $TOP_DELTAS"
echo "threads          : $THREADS_T1   wchan: $WCHAN_HIST"
echo "eth0 rx delta    : $RX_DELTA bytes     tx delta: $TX_DELTA"
echo "established socks: $SOCK_EST   (web/443 peers: $SOCK_EXT)"
echo "wal mtime        : $WAL_T1    newest cache: $CACHE_T1   newest log: $LOG_T1"
echo "fresh writes     : $([ "$WRITES" = 1 ] && echo YES || echo NO)"
echo

# ── Postgres cross-check (optional) ────────────────────────────────────
if [ "$CHECK_PG" = 1 ]; then
    PG=$(docker ps --format '{{.Names}}' 2>/dev/null | awk '/brewgis.*postgres/ {print $1; exit}')
    IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$CONTAINER" 2>/dev/null | awk '{print $1}')
    if [ -n "$PG" ] && [ -n "$IP" ]; then
        PGUSER=$(docker exec "$PG" printenv POSTGRES_USER 2>/dev/null || echo postgres)
        PGDATABASE=$(docker exec "$PG" printenv POSTGRES_DB 2>/dev/null || echo postgres)
        echo "--- postgres ($PG, client $IP) ---------------------------------"
        docker exec -i "$PG" psql -U "$PGUSER" -d "$PGDATABASE" -t -A -F'|' 2>/dev/null <<SQL | sed 's/^/pg backend    : /'
SELECT count(*) || ' backends, active=' || count(*) FILTER (WHERE state = 'active')
  || ', last=' || COALESCE(max(to_char(query_start, 'HH24:MI:SS')), '-')
FROM pg_stat_activity WHERE client_addr = '$IP';
SELECT COALESCE(max(to_char(to_timestamp(last_altered_ts / 1000.0), 'MM-DD HH24:MI:SS')), '-')
FROM sqlmesh_state._intervals;
SQL
        echo "  (last sqlmesh_state interval alteration; stale = no run progress)"
        echo
    else
        echo "--- postgres: not found (skipping) -------------------------------"
        echo
    fi
fi

# ── Verdict ────────────────────────────────────────────────────────────
# Progress: real I/O (>= 200 KB moved in window), fresh disk writes, or
# sustained CPU (>= 10 ticks/s = >= 10% of one core).
# Hang: < 10 ticks/s, >= 50% of it on a single thread, no I/O, no writes.
# Frozen: essentially zero CPU and no I/O.
if [ "$RX_DELTA" -ge 200000 ] || [ "$TX_DELTA" -ge 200000 ] || [ "$WRITES" = 1 ] \
   || [ "$CPU_DELTA" -ge $((DUR * 10)) ]; then
    evidence=""
    [ "$RX_DELTA" -ge 200000 ] && evidence="$evidence rx=${RX_DELTA}B"
    [ "$TX_DELTA" -ge 200000 ] && evidence="$evidence tx=${TX_DELTA}B"
    [ "$WRITES" = 1 ] && evidence="$evidence disk-writes"
    [ "$CPU_DELTA" -ge $((DUR * 10)) ] && evidence="$evidence cpu=${CPU_PCT}%"
    echo "VERDICT: PROGRESSING (evidence:$evidence)"
    exit 0
elif [ "$CPU_DELTA" -lt 5 ] && [ "$RX_DELTA" -lt 2000 ] && [ "$WRITES" != 1 ]; then
    echo "VERDICT: FROZEN — no measurable activity in ${DUR}s (cpu delta $CPU_DELTA ticks)."
    echo "         Process alive but inert; check for SIGSTOP or a blocking prompt."
    exit 2
fi

top_tid=$(echo "$TOP_DELTAS" | awk -F'[:;]' '{print $1}')
top_ticks=$(echo "$TOP_DELTAS" | awk -F'[:;]' '{print $2}')
[ -n "${top_ticks:-}" ] && [ "$top_ticks" -gt "$CPU_DELTA" ] && top_ticks=$CPU_DELTA
if [ -n "${top_ticks:-}" ] && [ "$top_ticks" -ge $((CPU_DELTA / 2)) ] && [ "$top_ticks" -gt 0 ]; then
    echo "VERDICT: HUNG (deadlock signature) — ${CPU_PCT}% of one core on thread $top_tid"
    echo "         ($top_ticks of $CPU_DELTA ticks), zero network I/O, zero disk writes,"
    echo "         threads parked on futexes."
    echo
    echo "Likely: in-process lock deadlock inside DuckDB's fetch/cache machinery"
    echo "        (httpfs / cache_httpfs / postgres_scanner). Known trigger in this"
    echo "        repo: staging models reading whole-planet Overture globs with"
    echo "        force_download=true in the sqlmesh duckdb connector config."
    echo
    echo "Next steps:"
    echo "  1. Stop the run, then reproduce the stuck fetch standalone, e.g."
    echo "     docker compose run --rm django python scripts/duckdb_shell.py"
    echo "     and execute the stuck model's SQL directly."
    echo "  2. If it hangs identically, grab a native stack as root to pinpoint:"
    echo "     py-spy dump --pid <host pid of sqlmesh>   (or: gdb -p <pid>, then"
    echo "     'thread apply all bt')"
    exit 1
fi

echo "VERDICT: INCONCLUSIVE — low CPU with no I/O but not single-thread"
echo "         dominated. Re-run with a longer window (-s 120)."
exit 2
