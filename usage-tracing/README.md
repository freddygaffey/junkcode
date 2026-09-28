# usage-tracing

Token and cost tracing for Claude Code agents, for any project on macOS, Linux or
Windows. It is a Claude Code skill: symlink this folder into `~/.claude/skills/`
and ask Claude to "set up usage tracing" in a project. `SKILL.md` is what Claude
follows; this file is for people.

```
ln -s ~/junkcode/usage-tracing ~/.claude/skills/usage-tracing
```

## Layout

| path | what |
|---|---|
| `SKILL.md` | the skill: how Claude installs and uses the kit |
| `tools/usage/trace.mjs` | the tool; `init` copies it into a project |
| `templates/` | what `init` installs: config, gate test, agent log, `lean` agent type |
| `tests/trace.test.mjs` | the kit's own tests: `node --test tests/*.test.mjs` |

## What a project gets

```
<project>/
  .claude/usage.json                 settings (only keys that differ from the defaults)
  .claude/settings.json              + SubagentStop hook: appends each finished agent to the ledger
  .claude/agents/lean.md             lean agent type, budget filled in from the settings
  tools/usage/trace.mjs              the tool
  tests/usage-ledger.test.mjs        gate test (the folder follows `testsDir`)
  docs/AGENT-LOG.md                  hand-annotated agent log
  docs/usage/agents.jsonl            machine ledger, written by the hook
```

## Settings (`.claude/usage.json`)

| key | default | meaning |
|---|---|---|
| `log` | `docs/AGENT-LOG.md` | the agent log `row` and `check` work with |
| `ledger` | `docs/usage/agents.jsonl` | the ledger the hook appends to |
| `testsDir` | `tests` | where `init` puts the gate test |
| `metric` | `total` | what `stats` ranks by |
| `outlierMultiple` | `4` | `stats` flags agents above this multiple of the median |
| `agentTypes` | `null` | e.g. `["lean"]` to report only those types |
| `extraPaths` | `[]` | other checkouts (e.g. an old location) whose transcripts count |
| `includeWorktrees` | `true` | count sessions run in the repo's git worktrees |
| `budget` | `{calls: 40, tokens: 100000, metric: "ctxEnd", stopAt: 0.8}` | per-agent budget for `stats`, `brief` and `lean.md` |
| `logRow` | `{metric: "ctxEnd", requireGreen: true}` | token figure in log rows; whether rows need `green: yes\|no\|n/a` |
| `prices` | `null` | `{"sonnet": {"input": …, "cacheWrite": …, "cacheRead": …, "output": …}}`, USD per million tokens, matched by substring of the model name; adds cost columns |

## Where the data comes from

Claude Code writes every session to
`<claude dir>/projects/<slug>/<session>.jsonl` and every agent to
`<slug>/<session>/subagents/agent-<id>.jsonl`, where `<claude dir>` is
`$CLAUDE_CONFIG_DIR` or `~/.claude`, and the slug is the launch folder with every
non-alphanumeric character replaced by `-`. Each assistant line carries a `usage`
block; every figure here is summed from those.

The tool finds a project's folders by slug and, failing that, by the `cwd` recorded
inside the transcripts. So Windows drive paths, symlinked folders, sessions started
in a subfolder and git worktrees are all matched without guessing the slug rules.

## The three token figures

| figure | definition | use it for |
|---|---|---|
| `total` | sum over turns of input + cache-creation + cache-read + output | what the API processed; cost and rate limits track this |
| `fresh` | sum of input + cache-creation | new material entering the context |
| `ctxEnd` | largest single-turn context | the figure the Agent tool reports as `subagent_tokens` |

`ctxEnd` matched the Agent tool's reported figure with a median ratio of 0.997 over
1186 agent notifications in one large project. `total` is typically 40–50× `ctxEnd`,
because every tool call re-reads the whole context: the cost is base context × tool
calls, so cut either.

## Budget rules of thumb

- Cost = base context × tool calls. The `lean` agent type cuts the base (no MCP
  tool schemas); the call budget cuts the multiplier.
- Never resume a large-context agent for follow-up work; launch a fresh one with a
  tight brief.
- Split any task expected to exceed ~150k context into two agents.
- Model is the difficulty knob, independent of agent type.

`trace.mjs brief` prints the budget paragraph for a brief, with the project's numbers.

## Caveats

- Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30). The
  ledger keeps a summary of every agent the hook saw, and `agents`/`stats` merge it
  back in, so history survives; raise the setting if you want full transcripts.
- The hook records an agent once its transcript has been quiet for a minute, so the
  most recent agent lands at the next agent's finish. `agents --append` catches up.
- The hook command uses `$CLAUDE_PROJECT_DIR`, which Claude Code sets for hooks. On
  Windows that relies on Claude Code running hooks through Git Bash, as it does by
  default; the Windows path handling is unit-tested but has not been run on Windows.
- Prices change. Nothing is priced unless `prices` is set; set it from current
  pricing when you need a dollar figure.
- Only agents launched through the Agent tool get a description, type and requested
  model (taken from the parent's tool call); others show their first prompt line.
