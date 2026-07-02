#!/usr/bin/env bash
# scripts/lib.sh — shared output helpers for the retail-stock-take local scripts.
#
# Source this near the top of setup.sh / preflight.sh / verify.sh / reset.sh:
#
#     ROOT="$(cd "$(dirname "$0")/.." && pwd)"
#     # shellcheck source=scripts/lib.sh
#     . "$ROOT/scripts/lib.sh"
#
# What it gives you:
#   • chalk-style ANSI colors that auto-disable when output isn't a terminal
#     (or when NO_COLOR is set) so piping to a log file stays clean.
#   • consistent status printers: step / say / ok / warn / err / die
#   • spin_wait — an animated spinner that polls a condition until it's true,
#     with a live status line and optional fast-fail, degrading to plain
#     heartbeat lines when there's no TTY.
#
# Nothing here changes any cluster state; it's purely presentation + waiting.

# ---------------------------------------------------------------------------
# Colors  (honor https://no-color.org; FORCE_COLOR=1 overrides the TTY check)
# ---------------------------------------------------------------------------
if { [ -t 1 ] || [ "${FORCE_COLOR:-}" = "1" ]; } && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m';   C_DIM=$'\033[2m'
  C_RED=$'\033[31m';  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'; C_CYAN=$'\033[36m';  C_GREY=$'\033[90m'
else
  C_RESET=''; C_BOLD=''; C_DIM=''
  C_RED='';   C_GREEN=''; C_YELLOW=''
  C_BLUE='';  C_CYAN='';  C_GREY=''
fi

# ---------------------------------------------------------------------------
# Status printers
# ---------------------------------------------------------------------------
# step: a major phase header — bold cyan, with a leading blank line for spacing.
step() { printf '\n%s==>%s %s%s%s\n' "$C_CYAN$C_BOLD" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"; }
# say:  ordinary progress detail (dim bullet).
say()  { printf '%s   •%s %s\n'  "$C_GREY"  "$C_RESET" "$*"; }
# ok:   a completed/healthy result (green check).
ok()   { printf '%s   ✓%s %s\n'  "$C_GREEN" "$C_RESET" "$*"; }
# warn: a non-fatal problem (yellow) — to stderr so it survives stdout capture.
warn() { printf '%s   ! %s%s\n'  "$C_YELLOW" "$*" "$C_RESET" >&2; }
# err:  a fatal problem (red bold) — to stderr. Caller decides whether to exit.
err()  { printf '%s   ✗ %s%s\n'  "$C_RED$C_BOLD" "$*" "$C_RESET" >&2; }
# die:  print an error and abort the script.
die()  { err "$*"; exit 1; }
# hl:   wrap a value in bold cyan for emphasis inside a sentence (URLs, creds…).
hl()   { printf '%s%s%s' "$C_BOLD$C_CYAN" "$*" "$C_RESET"; }

# ---------------------------------------------------------------------------
# spin_wait — poll a condition with an animated spinner
# ---------------------------------------------------------------------------
# Usage:
#   spin_wait <label> <timeout_s> <poll_every_s> \
#             [--status <fn>] [--abort <fn>] -- <predicate-cmd...>
#
#   <predicate-cmd>  Run every <poll_every_s> seconds. Return 0 when the thing
#                    we're waiting for is ready. (It's fine for it to also stash
#                    state in globals that --status / --abort then read.)
#   --status <fn>    Optional. Its stdout is shown live on the spinner line
#                    (e.g. "appdb=Running web=Pending"). Must return 0.
#   --abort  <fn>    Optional. Polled alongside the predicate; if it returns 0
#                    spin_wait bails out immediately with code 3 (use for
#                    terminal failure states so we don't wait for the timeout).
#
# Returns: 0 ready · 1 timed out · 3 aborted.
#
# The spinner animates every ~0.2s for smooth feedback, but the (potentially
# expensive) predicate is only evaluated every <poll_every_s> seconds so we
# never hammer the Kubernetes API. With no TTY it prints one heartbeat line per
# poll instead of animating.
spin_wait() {
  local label="$1" timeout="$2" poll_every="$3"; shift 3
  local status_fn='' abort_fn=''
  while [ $# -gt 0 ]; do
    case "$1" in
      --status) status_fn="$2"; shift 2 ;;
      --abort)  abort_fn="$2";  shift 2 ;;
      --)       shift; break ;;
      *)        break ;;
    esac
  done
  # Everything left in "$@" is the predicate command.

  # Run the wait loop in a subshell with errexit OFF, so a failing predicate
  # (the normal "not ready yet" case) never trips the caller's `set -e`.
  (
    set +e
    local frames=( ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏ )
    local start=$SECONDS i=0 last_poll=-100000 status='' elapsed tty=0
    [ -t 1 ] && tty=1
    while :; do
      elapsed=$(( SECONDS - start ))
      if [ $(( SECONDS - last_poll )) -ge "$poll_every" ]; then
        last_poll=$SECONDS
        if "$@"; then
          [ "$tty" = 1 ] && printf '\r\033[K'
          ok "$label ${C_GREY}(${elapsed}s)${C_RESET}"
          exit 0
        fi
        if [ -n "$abort_fn" ] && "$abort_fn"; then
          [ "$tty" = 1 ] && printf '\r\033[K'
          exit 3
        fi
        [ -n "$status_fn" ] && status="$("$status_fn")"
        [ "$tty" = 0 ] && printf '   … %s  (%ds)\n' "${status:-$label}" "$elapsed"
      fi
      if [ "$elapsed" -ge "$timeout" ]; then
        [ "$tty" = 1 ] && printf '\r\033[K'
        err "$label — timed out after ${timeout}s"
        exit 1
      fi
      if [ "$tty" = 1 ]; then
        printf '\r %s %s  %s%s %s(%ds)%s' \
          "$C_CYAN${frames[i % ${#frames[@]}]}$C_RESET" "$label" \
          "$C_DIM" "$status" "$C_GREY" "$elapsed" "$C_RESET"
        i=$(( i + 1 ))
        sleep 0.2
      else
        sleep "$poll_every"
      fi
    done
  )
}
