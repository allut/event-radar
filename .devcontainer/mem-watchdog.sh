#!/usr/bin/env bash
# Diagnostic watchdog for the "reload the VS Code window" problem.
#
# The failure is intermittent and VS Code only retains four log sessions, so by
# the time you notice it the evidence has usually rotated away. This samples the
# signals that distinguish the competing causes and archives each VS Code
# session's logs before they are lost.
#
#   start   -- begin sampling in the background
#   stop    -- stop sampling
#   status  -- is it running, and what does right now look like
#   verdict -- read back what was captured and say what caused the last reload
#
# Everything lands in $DIAG_DIR, which survives a window reload and a container
# restart (but not a rebuild).
set -uo pipefail

DIAG_DIR="${DIAG_DIR:-$HOME/.event-radar-diag}"
SAMPLE_LOG="$DIAG_DIR/samples.tsv"
EVENT_LOG="$DIAG_DIR/events.log"
ARCHIVE_DIR="$DIAG_DIR/vscode-logs"
PID_FILE="$DIAG_DIR/watchdog.pid"
VSCODE_LOGS="$HOME/.vscode-server/data/logs"

INTERVAL="${INTERVAL:-5}"
# Warn when available memory drops below this many MB.
LOW_MEM_MB="${LOW_MEM_MB:-300}"

now() { date '+%Y-%m-%d %H:%M:%S'; }

event() { echo "$(now)  $*" >>"$EVENT_LOG"; }

# Processes whose death is the thing we are trying to catch.
#
# pgrep -f is useless here: this script's own command line contains the patterns,
# so it matches itself and every shell it spawns. Read /proc directly and skip
# anything belonging to the watchdog.
find_procs() {
  local pattern="$1" pid cmd
  for pid in /proc/[0-9]*; do
    pid="${pid#/proc/}"
    [ "$pid" = "$$" ] && continue
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null)" || continue
    [ -z "$cmd" ] && continue
    case "$cmd" in *mem-watchdog*) continue ;; esac
    case "$cmd" in *"$pattern"*) printf '%s ' "$pid" ;; esac
  done
}

exthost_pids() { find_procs '--type=extensionHost'; }
ptyhost_pids() { find_procs '--type=ptyHost'; }
server_pids() { find_procs 'out/server-main.js'; }

meminfo_mb() { awk -v k="$1" '$1==k":"{printf "%d", $2/1024}' /proc/meminfo; }

psi_full_total() {
  awk '/^full/{for(i=1;i<=NF;i++) if($i ~ /^total=/){sub("total=","",$i); print $i}}' \
    /proc/pressure/memory 2>/dev/null || echo 0
}

oom_kill_count() { awk '/^oom_kill /{print $2}' /proc/vmstat; }

top_rss() {
  ps -eo rss,comm --sort=-rss 2>/dev/null | awk 'NR>1 && NR<=6 {printf "%s=%dMB ", $2, $1/1024}'
}

snapshot() {
  echo "--- process table at $(now) ---"
  ps -eo pid,ppid,rss,etimes,comm --sort=-rss 2>/dev/null | head -20
  echo "--- meminfo ---"
  grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo
  echo "--- pressure ---"
  cat /proc/pressure/memory 2>/dev/null
}

# Copy a finished VS Code session's logs out before VS Code rotates them away.
archive_vscode_logs() {
  [ -d "$VSCODE_LOGS" ] || return 0
  local session dest
  for session in "$VSCODE_LOGS"/*/; do
    [ -d "$session" ] || continue
    dest="$ARCHIVE_DIR/$(basename "$session")"
    [ -d "$dest" ] && continue
    mkdir -p "$dest"
    cp "$session/remoteagent.log" "$dest/" 2>/dev/null
    cp "$session/exthost1/remoteexthost.log" "$dest/" 2>/dev/null
    cp "$session/exthost1/Anthropic.claude-code/Claude VSCode.log" "$dest/" 2>/dev/null
    event "ARCHIVED vscode session $(basename "$session")"
  done
}

sample_loop() {
  mkdir -p "$DIAG_DIR" "$ARCHIVE_DIR"
  [ -s "$SAMPLE_LOG" ] || printf 'timestamp\tavail_mb\tswapfree_mb\tpsi_full_total\toom_kills\texthost_pids\ttop_rss\n' >"$SAMPLE_LOG"

  local prev_oom prev_exthost prev_ptyhost
  prev_oom="$(oom_kill_count)"
  prev_exthost="$(exthost_pids)"
  prev_ptyhost="$(ptyhost_pids)"
  event "WATCHDOG START (exthost=[$prev_exthost] ptyhost=[$prev_ptyhost] oom_kills=$prev_oom)"

  while true; do
    local avail swapfree psi oom exthost ptyhost
    avail="$(meminfo_mb MemAvailable)"
    swapfree="$(meminfo_mb SwapFree)"
    psi="$(psi_full_total)"
    oom="$(oom_kill_count)"
    exthost="$(exthost_pids)"
    ptyhost="$(ptyhost_pids)"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$(now)" "$avail" "$swapfree" "$psi" "$oom" "${exthost:-none}" "$(top_rss)" >>"$SAMPLE_LOG"

    # The kernel OOM killer fired. This is the smoking gun for the RAM theory.
    if [ "$oom" != "$prev_oom" ]; then
      event "ALARM oom_kill counter $prev_oom -> $oom"
      snapshot >>"$EVENT_LOG"
      prev_oom="$oom"
    fi

    # An extension host we were watching is gone.
    local pid
    for pid in $prev_exthost; do
      if ! kill -0 "$pid" 2>/dev/null; then
        event "ALARM extension host pid $pid disappeared (avail=${avail}MB swapfree=${swapfree}MB oom_kills=$oom)"
        snapshot >>"$EVENT_LOG"
        # The exit code is the verdict: 0 = graceful reload, nonzero/signal = crash.
        local latest
        latest="$(ls -1d "$VSCODE_LOGS"/*/ 2>/dev/null | tail -1)"
        if [ -n "$latest" ]; then
          echo "--- remoteagent.log tail ---" >>"$EVENT_LOG"
          grep -E 'exited with code|terminated unexpectedly|disconnected|reconnected' \
            "$latest/remoteagent.log" 2>/dev/null | tail -10 >>"$EVENT_LOG"
        fi
        archive_vscode_logs
      fi
    done
    prev_exthost="$exthost"

    for pid in $prev_ptyhost; do
      if ! kill -0 "$pid" 2>/dev/null; then
        event "NOTE pty host pid $pid disappeared (avail=${avail}MB)"
      fi
    done
    prev_ptyhost="$ptyhost"

    if [ -n "$avail" ] && [ "$avail" -lt "$LOW_MEM_MB" ]; then
      event "WARN low memory: ${avail}MB available, ${swapfree}MB swap free -- $(top_rss)"
    fi

    archive_vscode_logs
    sleep "$INTERVAL"
  done
}

case "${1:-status}" in
  start)
    mkdir -p "$DIAG_DIR" "$ARCHIVE_DIR"
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "already running (pid $(cat "$PID_FILE"))"; exit 0
    fi
    nohup "$0" _loop >>"$DIAG_DIR/watchdog.out" 2>&1 &
    echo $! >"$PID_FILE"
    echo "watchdog started (pid $(cat "$PID_FILE")), logging to $DIAG_DIR"
    ;;
  _loop) sample_loop ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null && echo "stopped"
      rm -f "$PID_FILE"
    else
      echo "not running"
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running (pid $(cat "$PID_FILE")), $( [ -f "$SAMPLE_LOG" ] && wc -l <"$SAMPLE_LOG" || echo 0) samples"
    else
      echo "not running"
    fi
    echo "available: $(meminfo_mb MemAvailable)MB   swap free: $(meminfo_mb SwapFree)MB   oom_kills: $(oom_kill_count)"
    echo "top RSS: $(top_rss)"
    ;;
  verdict)
    echo "===== ALARMS / WARNINGS ====="
    grep -E 'ALARM|WARN' "$EVENT_LOG" 2>/dev/null | tail -40 || echo "(none recorded)"
    echo
    echo "===== kernel OOM kills since boot ====="
    echo "$(oom_kill_count)  (0 means the RAM-exhaustion theory is refuted)"
    echo
    echo "===== how each archived session's extension host exited ====="
    for d in "$ARCHIVE_DIR"/*/; do
      [ -d "$d" ] || continue
      echo "--- $(basename "$d") ---"
      grep -E 'exited with code|terminated unexpectedly|disconnected gracefully|has reconnected' \
        "$d/remoteagent.log" 2>/dev/null | tail -6 || echo "(no exit record)"
    done
    echo
    echo "===== lowest available memory recorded ====="
    if [ -f "$SAMPLE_LOG" ]; then
      awk -F'\t' 'NR>1 && $2!="" {if(min==""||$2<min){min=$2;line=$0}} END{if(line!="")print line; else print "(no samples)"}' "$SAMPLE_LOG"
    else
      echo "(no samples)"
    fi
    ;;
  *) echo "usage: $0 {start|stop|status|verdict}"; exit 1 ;;
esac
