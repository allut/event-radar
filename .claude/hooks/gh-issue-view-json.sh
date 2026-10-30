#!/usr/bin/env bash
# PreToolUse(Bash): deny `gh issue view <n> --comments` without --json.
# Plain --comments prints comments only, so an issue with none prints nothing.
# Deny, not rewrite: the global rtk hook also rewrites Bash input and parallel rewrites race.
cmd=$(jq -r '.tool_input.command // empty')
[[ $cmd =~ (^|[^[:alnum:]_-])gh[[:space:]]+issue[[:space:]]+view([[:space:]]|$) ]] || exit 0
[[ $cmd =~ (^|[[:space:]])(--comments|-c)([[:space:]]|$) ]] || exit 0
[[ $cmd == *--json* ]] && exit 0
jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: "`gh issue view <n> --comments` prints comments only (nothing for an issue without comments). Run `gh issue view <n> --json title,body,labels,comments` instead."}}'
