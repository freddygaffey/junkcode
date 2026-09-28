// Tests for the kit itself: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, realpathSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { normPath, isWithin, projectSlug, checkLog, checkLedger, costOf, human, loadConfig, DEFAULTS } from "../tools/usage/trace.mjs";

const TRACE = join(dirname(fileURLToPath(import.meta.url)), "..", "tools", "usage", "trace.mjs");
const run = (args, env = {}) => execFileSync(process.execPath, [TRACE, ...args], { encoding: "utf8", env: { ...process.env, CLAUDE_PROJECT_DIR: "", ...env } });

test("Windows paths compare case-insensitively with either separator", () => {
  assert.equal(normPath("C:\\Users\\Me\\Proj\\", true), "c:/users/me/proj");
  assert.ok(isWithin("c:/users/me/proj/sub", "C:\\Users\\Me\\Proj", true));
  assert.ok(!isWithin("C:\\Users\\Me\\Project2", "C:\\Users\\Me\\Proj", true));
  assert.equal(projectSlug("C:\\Users\\me\\proj"), "C--Users-me-proj");
});

test("POSIX paths are case-sensitive and prefix-safe", () => {
  assert.ok(isWithin("/a/proj/x", "/a/proj/", false));
  assert.ok(!isWithin("/a/proj2", "/a/proj", false));
  assert.ok(!isWithin("/a/Proj", "/a/proj", false));
});

test("checkLog honours requireGreen and accepts k or M", () => {
  const rows = "| 2026-09-01 | m | t | x | y | 1.2M / 30 calls |\n| 2026-09-02 | m | t | x | y | 90k / 3 calls | green: yes |\r\n";
  assert.equal(checkLog(rows).problems.length, 1);
  assert.equal(checkLog(rows, { logRow: { requireGreen: false } }).problems.length, 0);
  assert.equal(checkLog("| 2026-09-01 | no tokens | green: no |").problems.length, 1);
});

test("checkLedger catches duplicates, missing fields and bad JSON", () => {
  const good = JSON.stringify({ agentId: "a", model: "m", total: 1, fresh: 1, ctxEnd: 1, toolCalls: 1, start: "x" });
  assert.deepEqual(checkLedger(good + "\n").problems, []);
  assert.equal(checkLedger(`${good}\n${good}\n{oops\n{"agentId":"b"}\n`).problems.length, 1 + 1 + 6);
});

test("cost uses the first matching model key", () => {
  const r = { model: "claude-sonnet-5", input: 1e6, cacheCreate: 0, cacheRead: 2e6, output: 1e6 };
  assert.equal(costOf(r, { sonnet: { input: 3, cacheRead: 0.3, output: 15 } }), 3 + 0.6 + 15);
  assert.equal(costOf(r, { opus: { input: 1 } }), null);
  assert.equal(costOf(r, null), null);
  assert.equal(human(250000), "250k");
  assert.equal(human(5_700_000), "5.7M");
});

test("config merges nested keys over defaults", () => {
  const dir = mkdtempSync(join(tmpdir(), "ut-"));
  mkdirSync(join(dir, ".claude"));
  writeFileSync(join(dir, ".claude", "usage.json"), JSON.stringify({ budget: { calls: 25 }, agentTypes: ["lean"] }));
  const cfg = loadConfig(dir);
  assert.equal(cfg.budget.calls, 25);
  assert.equal(cfg.budget.tokens, DEFAULTS.budget.tokens);
  assert.deepEqual(cfg.agentTypes, ["lean"]);
});

// A fake Claude dir whose transcript folder is NOT the project's slug: it must be
// found through the cwd recorded inside the transcript (the Windows/symlink case).
function fakeClaude(project) {
  const claude = mkdtempSync(join(tmpdir(), "ut-claude-"));
  const dir = join(claude, "projects", "not-the-slug");
  const sess = "11111111-2222-3333-4444-555555555555";
  mkdirSync(join(dir, sess, "subagents"), { recursive: true });
  const t0 = "2026-09-01T00:00:00.000Z", t1 = "2026-09-01T00:05:00.000Z";
  const msg = (id, usage, content, ts) => JSON.stringify({ type: "assistant", timestamp: ts, cwd: project, message: { id, model: "claude-sonnet-5", usage, content } });
  writeFileSync(join(dir, `${sess}.jsonl`), [
    JSON.stringify({ type: "user", timestamp: t0, cwd: project, message: { content: "do the thing" } }),
    msg("m1", { input_tokens: 10, output_tokens: 5 }, [{ type: "tool_use", id: "tu1", name: "Agent", input: { description: "fake agent", subagent_type: "lean" } }], t0),
    JSON.stringify({ type: "user", timestamp: t1, message: { content: [{ type: "tool_result", tool_use_id: "tu1", content: "done agentId: abcdef1234" }] } }),
  ].join("\n") + "\n");
  writeFileSync(join(dir, sess, "subagents", "agent-abcdef1234.jsonl"), [
    JSON.stringify({ type: "user", agentId: "abcdef1234", sessionId: sess, timestamp: t0, cwd: project, message: { content: "brief" } }),
    msg("a1", { input_tokens: 100, cache_creation_input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 50 }, [{ type: "tool_use", id: "x", name: "Bash", input: {} }], t0),
    msg("a2", { input_tokens: 10, cache_creation_input_tokens: 0, cache_read_input_tokens: 1100, output_tokens: 40 }, [{ type: "text", text: "ok" }], t1),
  ].join("\n") + "\n");
  return claude;
}

test("init installs into a project, and the installed kit works there", () => {
  const project = realpathSync(mkdtempSync(join(tmpdir(), "ut-proj-")));
  execFileSync("git", ["init", "-q"], { cwd: project });
  mkdirSync(join(project, ".claude"));
  writeFileSync(join(project, ".claude", "settings.json"), JSON.stringify({ permissions: { allow: ["Bash(ls)"] } }));
  writeFileSync(join(project, ".claude", "usage.json"), JSON.stringify({ testsDir: "src/__tests__", logRow: { requireGreen: false } }));

  assert.match(run(["init", "--project", project, "--dry-run"]), /Would install/);
  assert.ok(!existsSync(join(project, "tools")));
  const out = run(["init", "--project", project]);
  assert.match(out, /keep {4}\.claude\/usage\.json/);
  assert.match(out, /update {2}\.claude\/settings\.json/);

  const settings = JSON.parse(readFileSync(join(project, ".claude", "settings.json"), "utf8"));
  assert.deepEqual(settings.permissions, { allow: ["Bash(ls)"] });
  assert.match(settings.hooks.SubagentStop[0].hooks[0].command, /CLAUDE_PROJECT_DIR/);
  assert.match(run(["init", "--project", project]), /hook present/);

  const testFile = join(project, "src", "__tests__", "usage-ledger.test.mjs");
  assert.match(readFileSync(testFile, "utf8"), /"\.\.\/\.\.\/tools\/usage\/trace\.mjs"/);
  const log = readFileSync(join(project, "docs", "AGENT-LOG.md"), "utf8");
  assert.doesNotMatch(log, /\{\{/);
  assert.match(log, /\| tokens \/ calls \|\n\|---\|---\|---\|---\|---\|---\|\n/);
  assert.match(readFileSync(join(project, ".claude", "agents", "lean.md"), "utf8"), /~40 tool calls \/ ~100k tokens/);

  // The installed copy, run from a subfolder, with transcripts under an unrelated slug.
  const env = { CLAUDE_CONFIG_DIR: fakeClaude(project) };
  const installed = join(project, "tools", "usage", "trace.mjs");
  const sub = join(project, "src");
  const agents = JSON.parse(execFileSync(process.execPath, [installed, "agents", "--format", "json"], { cwd: sub, encoding: "utf8", env: { ...process.env, CLAUDE_PROJECT_DIR: "", ...env } }));
  assert.equal(agents.length, 1);
  assert.deepEqual([agents[0].description, agents[0].subagentType, agents[0].total, agents[0].ctxEnd, agents[0].toolCalls], ["fake agent", "lean", 2300, 1150, 1]);

  execFileSync(process.execPath, [installed, "agents", "--append"], { cwd: project, env: { ...process.env, ...env } });
  const row = execFileSync(process.execPath, [installed, "row", "--agent", "abcdef", "--outcome", "ok"], { cwd: project, encoding: "utf8", env: { ...process.env, ...env } });
  writeFileSync(join(project, "docs", "AGENT-LOG.md"), readFileSync(join(project, "docs", "AGENT-LOG.md"), "utf8") + row);
  assert.match(execFileSync(process.execPath, ["--test", "--test-reporter=tap", testFile], { cwd: project, encoding: "utf8", env: Object.fromEntries(Object.entries(process.env).filter(([k]) => k !== "NODE_TEST_CONTEXT")) }), /# pass 2/);
  assert.equal(readFileSync(join(project, "docs", "usage", "agents.jsonl"), "utf8").trim().split("\n").length, 1);
});

test("the hook never fails, even with no transcripts", () => {
  const project = mkdtempSync(join(tmpdir(), "ut-empty-"));
  assert.equal(run(["agents", "--append", "--quiet", "--project", project], { CLAUDE_CONFIG_DIR: join(project, "nope") }), "");
});
