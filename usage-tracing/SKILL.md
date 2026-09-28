---
name: usage-tracing
description: Set up or use token/cost tracing for Claude Code agents in any project — per-agent and per-session tokens, tool calls, model, duration and optional dollar cost, read from the transcripts Claude Code already writes. Use when the user asks to set up (install, add) usage tracing, token tracking, agent cost tracking or an agent log in a project, or asks how many tokens / how much agents or sessions used, which agents were expensive, or for agent budget stats.
---

# Usage tracing

A drop-in kit that reads `~/.claude/projects/…` transcripts (or `$CLAUDE_CONFIG_DIR/projects/…`)
and reports tokens and tool calls per agent and per session. Everything lives in this
skill's folder; `tools/usage/trace.mjs` is the whole tool (Node 18+, no dependencies,
macOS/Linux/Windows). Below, `KIT` means this skill's base directory.

## Setting it up in a project

1. **Find the project root.** Use the git top level of the folder the user means
   (usually the current one). Never install into the skill folder itself.
2. **Preview.** `node KIT/tools/usage/trace.mjs init --project <root> --dry-run`
   and show the user the list of files it would create or update.
3. **Ask about custom settings, in one question**, unless the user already said.
   Offer the defaults as the recommended answer:
   - budget per agent (default ~40 tool calls / ~100k tokens of context, stop at 80%)
   - whether agent-log rows need a "green first try" flag (default yes)
   - dollar cost: only if the user gives prices. Do not invent prices; if they want
     cost, look current ones up (the claude-api skill has them) and confirm.
   - only count some agent types (e.g. `["lean"]`), log/ledger/test paths, if the
     project's layout differs from `docs/` and `tests/`.
4. **Write `<root>/.claude/usage.json`** with only the keys that differ from the
   defaults (every key is listed in `KIT/templates/usage.json`). If the file exists,
   edit it instead of replacing it.
5. **Install.** `node KIT/tools/usage/trace.mjs init --project <root>`. It copies the
   tool and gate test, creates the agent log, ledger folder and `lean` agent type, and
   merges a `SubagentStop` hook into `.claude/settings.json`. It never overwrites an
   existing file except `tools/usage/trace.mjs` (that is the upgrade path).
6. **Verify**, from the root:
   `node tools/usage/trace.mjs config` (transcript folders found?),
   `node tools/usage/trace.mjs stats`, and the project's test command (or
   `node --test <testsDir>/usage-ledger.test.mjs`).
7. **Tell the user**: the hook and the `lean` agent load at the next session start;
   add the gate test to CI if the project has one. Commit following the project's
   own conventions.

If the project has no transcripts yet, `config` says so. That is fine; they appear
after the first session run there.

## Using it

Run from the project root (or pass `--project PATH`):

| command | gives |
|---|---|
| `agents [--since YYYY-MM-DD]` | table of every agent run |
| `stats [--since D] [--metric total\|fresh\|ctxEnd]` | medians, per-model share, outliers, over-budget agents |
| `sessions` | main-session spend, which agent logs never see |
| `row --agent ID --outcome "…" --green yes\|no\|n/a` | an agent-log row, ready to paste |
| `brief` | the budget paragraph to paste into an agent brief |
| `check` | validate the agent log and ledger (what the gate test runs) |
| `config` | settings in effect and the transcript folders matched |

`--format md|tsv|json|jsonl` on `agents`/`sessions`. If a project doesn't have the
kit installed, run `KIT/tools/usage/trace.mjs … --project PATH` directly; it works
read-only without any setup.

Token figures: `total` is everything the API processed (cache re-reads dominate; cost
and rate limits track it), `fresh` is new context, `ctxEnd` is the peak context and
matches the Agent tool's reported `subagent_tokens`. Say which one you are quoting.

## Maintaining the kit

The kit's own tests: `node --test KIT/tests/*.test.mjs`. After changing `trace.mjs`,
re-run `init` in a project to upgrade its copy. The README has the design notes.
