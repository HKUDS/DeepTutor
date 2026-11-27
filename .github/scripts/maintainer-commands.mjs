#!/usr/bin/env node
/**
 * Maintainer-only slash commands for HKUDS/DeepTutor Issues and Pull Requests.
 *
 * Supported commands (one per line, outside fenced code blocks):
 *   /claim [--force]          (alias: /take)
 *   /unclaim [@username]      (alias: /unclaimed)
 *   /assign @user1 [@user2]
 *   /label <tag1> [tag2 ...]
 *   /unlabel <tag1> [tag2 ...]
 *   /need-info                (alias: /needs-info)
 *   /close [dup #N | fixed #N | not-planned | invalid | stale]
 *   /reopen
 *   /ci                       (alias: /ok-to-test, PR only)
 *   /pancake [note]           (alias: /escalate [note])
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const LABEL_ALIASES = {
  bug: "bug",
  feat: "enhancement",
  feature: "enhancement",
  enhancement: "enhancement",
  doc: "documentation",
  docs: "documentation",
  documentation: "documentation",
  q: "question",
  question: "question",
  dup: "duplicate",
  duplicate: "duplicate",
  invalid: "invalid",
  wontfix: "wontfix",
  stale: "stale",
  p0: "P0",
  p1: "P1",
  p2: "P2",
  win: "os:windows",
  windows: "os:windows",
  mac: "os:macos",
  macos: "os:macos",
  linux: "os:linux",
  mobile: "area:mobile",
  android: "area:mobile",
  ios: "area:mobile",
  desktop: "area:desktop",
  rag: "area:rag",
  kb: "area:rag",
  web: "area:web",
  ui: "area:web",
};

const LABEL_COLORS = {
  reviewing: "1d76db",
  claimed: "0e8a16",
  "needs-info": "d876e3",
  "needs-pancake": "d93f0b",
  P0: "b60205",
  P1: "d93f0b",
  P2: "fbca04",
  "os:windows": "0075ca",
  "os:macos": "5319e7",
  "os:linux": "cfd3d7",
  "area:mobile": "1d76db",
  "area:desktop": "0052cc",
  "area:rag": "0e8a16",
  "area:web": "5319e7",
};

export function parseMaintainersYaml(text) {
  const logins = new Set();
  for (const raw of (text || "").split(/\r?\n/)) {
    const line = raw.replace(/#.*$/, "").trim();
    const m = line.match(/^-\s*@?([A-Za-z0-9-]+)\s*$/);
    if (m) logins.add(m[1].toLowerCase());
  }
  return logins;
}

export function resolveLabelName(token) {
  const cleaned = (token || "").trim().replace(/^['"`]|['"`]$/g, "");
  if (!cleaned) return "";
  return LABEL_ALIASES[cleaned.toLowerCase()] || cleaned;
}

export function parseCommands(commentBody) {
  const stripped = (commentBody || "").replace(/```[\s\S]*?```/g, "");
  const commands = [];
  for (const rawLine of stripped.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line.startsWith("/")) continue;
    const m = line.match(/^\/([A-Za-z0-9_-]+)(?:\s+(.*))?$/);
    if (!m) continue;
    const verb = m[1].toLowerCase();
    const rest = (m[2] || "").trim();

    if (verb === "claim" || verb === "take") {
      commands.push({ type: "claim", force: /(?:^|\s)--force(?:\s|$)/i.test(rest) });
    } else if (verb === "unclaim" || verb === "unclaimed") {
      const u = rest.match(/^@?([A-Za-z0-9-]+)$/);
      commands.push({ type: "unclaim", target: u ? u[1] : null });
    } else if (verb === "assign") {
      const users = [...rest.matchAll(/@?([A-Za-z0-9-]+)/g)].map((x) => x[1]);
      if (users.length > 0) commands.push({ type: "assign", users });
    } else if (verb === "label" || verb === "unlabel") {
      const labels = rest
        .split(/[\s,]+/)
        .map(resolveLabelName)
        .filter(Boolean);
      if (labels.length > 0) commands.push({ type: verb, labels });
    } else if (verb === "need-info" || verb === "needs-info") {
      commands.push({ type: "need-info" });
    } else if (verb === "close") {
      commands.push({ type: "close", arg: rest });
    } else if (verb === "reopen") {
      commands.push({ type: "reopen" });
    } else if (verb === "ci" || verb === "ok-to-test") {
      commands.push({ type: "ci" });
    } else if (verb === "pancake" || verb === "escalate") {
      commands.push({ type: "pancake", note: rest });
    }
  }
  return commands;
}

class GitHubClient {
  constructor(owner, repo, token) {
    this.owner = owner;
    this.repo = repo;
    this.token = token;
    this.base = `https://api.github.com/repos/${owner}/${repo}`;
  }

  async request(method, urlPath, body = undefined, allowStatus = []) {
    const url = urlPath.startsWith("http") ? urlPath : `${this.base}${urlPath}`;
    const res = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok && !allowStatus.includes(res.status)) {
      const text = await res.text();
      const err = new Error(`GitHub API ${method} ${urlPath} -> ${res.status}: ${text}`);
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return { status: 204, data: null };
    const text = await res.text();
    return { status: res.status, data: text ? JSON.parse(text) : null };
  }

  async isMaintainer(username, allowlist) {
    if (allowlist.has(username.toLowerCase())) return true;
    const { status, data } = await this.request(
      "GET",
      `/collaborators/${encodeURIComponent(username)}/permission`,
      undefined,
      [404, 403],
    );
    if (status !== 200 || !data) return false;
    return ["admin", "maintain", "write"].includes(data.permission);
  }

  async reactComment(commentId, content = "+1") {
    if (!commentId) return;
    await this.request(
      "POST",
      `/issues/comments/${commentId}/reactions`,
      { content },
      [404, 422],
    );
  }

  async ensureLabel(name) {
    const encoded = encodeURIComponent(name);
    const { status } = await this.request("GET", `/labels/${encoded}`, undefined, [404]);
    if (status === 200) return;
    const color = LABEL_COLORS[name] || "ededed";
    await this.request("POST", "/labels", { name, color }, [422]);
  }

  async addLabels(issueNumber, names) {
    for (const name of names) await this.ensureLabel(name);
    await this.request("POST", `/issues/${issueNumber}/labels`, { labels: names });
  }

  async removeLabel(issueNumber, name) {
    await this.request(
      "DELETE",
      `/issues/${issueNumber}/labels/${encodeURIComponent(name)}`,
      undefined,
      [404],
    );
  }

  async comment(issueNumber, body) {
    await this.request("POST", `/issues/${issueNumber}/comments`, { body });
  }

  async getIssue(issueNumber) {
    const { data } = await this.request("GET", `/issues/${issueNumber}`);
    return data;
  }
}

function sameLogin(a, b) {
  return (a || "").toLowerCase() === (b || "").toLowerCase();
}

async function runSelfTest() {
  const allow = parseMaintainersYaml(`
    # comment
    maintainers:
      - pancacake
      - @Alice-Dev
  `);
  assert.equal(allow.has("pancacake"), true);
  assert.equal(allow.has("alice-dev"), true);

  const cmds = parseCommands([
    "```",
    "/close invalid",
    "```",
    "/claim --force",
    "/label bug p1 win",
    "/ci",
    "/pancake 需要确认一下架构边界",
  ].join("\n"));
  assert.deepEqual(cmds, [
    { type: "claim", force: true },
    { type: "label", labels: ["bug", "P1", "os:windows"] },
    { type: "ci" },
    { type: "pancake", note: "需要确认一下架构边界" },
  ]);

  assert.deepEqual(parseCommands("/close dup #2072"), [
    { type: "close", arg: "dup #2072" },
  ]);
  assert.deepEqual(parseCommands("/assign @foo @bar"), [
    { type: "assign", users: ["foo", "bar"] },
  ]);
  console.log("maintainer-commands self-test passed.");
}

async function main() {
  if (process.argv.includes("--self-test")) {
    await runSelfTest();
    return;
  }

  const repoFull = process.env.GITHUB_REPOSITORY || "";
  const [owner, repo] = repoFull.split("/");
  const token = process.env.GH_TOKEN || "";
  const issueNumber = Number(process.env.ISSUE_NUMBER || "0");
  const isPR = String(process.env.IS_PR || "").toLowerCase() === "true";
  const commentId = process.env.COMMENT_ID || "";
  const commentBody = process.env.COMMENT_BODY || "";
  const actor = process.env.COMMENT_USER || "";
  const issueAuthor = process.env.ISSUE_AUTHOR || "";
  const issueUrl = process.env.ISSUE_HTML_URL || "";
  const issueTitle = process.env.ISSUE_TITLE || "";

  const commands = parseCommands(commentBody);
  if (!commands.length) {
    console.log("No slash commands detected outside code blocks.");
    return;
  }

  const maintainersPath = path.resolve(".github/maintainers.yml");
  const allowlist = fs.existsSync(maintainersPath)
    ? parseMaintainersYaml(fs.readFileSync(maintainersPath, "utf8"))
    : new Set();

  const gh = new GitHubClient(owner, repo, token);
  const authorized = await gh.isMaintainer(actor, allowlist);
  if (!authorized) {
    console.log(`Ignored slash command from non-maintainer @${actor}.`);
    return;
  }

  await gh.reactComment(commentId, "+1");

  for (const cmd of commands) {
    if (cmd.type === "claim") {
      const issue = await gh.getIssue(issueNumber);
      const existing = (issue.assignees || []).map((a) => a.login);
      const others = existing.filter((u) => !sameLogin(u, actor));
      if (others.length > 0 && !cmd.force) {
        await gh.comment(
          issueNumber,
          `⚠️ @${actor} 当前已由 ${others.map((u) => `@${u}`).join(", ")} 跟进中；如需交接接手请发送 \`/claim --force\`。`,
        );
        continue;
      }
      if (cmd.force && others.length > 0) {
        await gh.request("DELETE", `/issues/${issueNumber}/assignees`, { assignees: others }, [422]);
      }
      await gh.request("POST", `/issues/${issueNumber}/assignees`, { assignees: [actor] }, [422]);
      if (isPR) {
        await gh.addLabels(issueNumber, ["reviewing"]);
        if (!sameLogin(actor, issueAuthor)) {
          await gh.request(
            "POST",
            `/pulls/${issueNumber}/requested_reviewers`,
            { reviewers: [actor] },
            [422],
          );
        }
        await gh.comment(issueNumber, `👀 已由 Maintainer @${actor} 接手评审（Reviewing）。`);
      } else {
        await gh.comment(issueNumber, `🛠️ 已由 Maintainer @${actor} 接手跟进。`);
      }
    } else if (cmd.type === "unclaim") {
      const issue = await gh.getIssue(issueNumber);
      const existing = (issue.assignees || []).map((a) => a.login);
      const toRemove = cmd.target
        ? existing.filter((u) => sameLogin(u, cmd.target))
        : existing.some((u) => sameLogin(u, actor))
          ? [actor]
          : existing;
      if (toRemove.length > 0) {
        await gh.request("DELETE", `/issues/${issueNumber}/assignees`, { assignees: toRemove }, [422]);
      }
      if (isPR && toRemove.length > 0) {
        await gh.request(
          "DELETE",
          `/pulls/${issueNumber}/requested_reviewers`,
          { reviewers: toRemove },
          [422],
        );
      }
      if (existing.length <= toRemove.length) {
        await gh.removeLabel(issueNumber, isPR ? "reviewing" : "claimed");
      }
      await gh.comment(
        issueNumber,
        `🔄 已由 @${actor} 释放 #${issueNumber} 的认领状态，欢迎其他同学或 Maintainer 接手。`,
      );
    } else if (cmd.type === "assign") {
      const { status } = await gh.request(
        "POST",
        `/issues/${issueNumber}/assignees`,
        { assignees: cmd.users },
        [422],
      );
      if (!isPR) await gh.addLabels(issueNumber, ["claimed"]);
      const mentions = cmd.users.map((u) => `@${u}`).join(", ");
      if (status === 422) {
        await gh.comment(
          issueNumber,
          `📌 已标记由 ${mentions} 认领（GitHub 需本人在本单下任意评论一次后才可挂上侧边栏 Assignee）。`,
        );
      } else {
        await gh.comment(issueNumber, `✅ 已指派给 ${mentions} 跟进处理。`);
      }
    } else if (cmd.type === "label") {
      await gh.addLabels(issueNumber, cmd.labels);
      await gh.removeLabel(issueNumber, "needs-triage");
    } else if (cmd.type === "unlabel") {
      for (const name of cmd.labels) {
        await gh.removeLabel(issueNumber, name);
      }
    } else if (cmd.type === "need-info") {
      await gh.addLabels(issueNumber, ["needs-info"]);
      await gh.comment(
        issueNumber,
        [
          `你好 @${issueAuthor}，感谢反馈！为了帮我们更快定位问题，麻烦补充以下信息：`,
          "1. **DeepTutor 版本与运行方式**（桌面端 macOS/Windows 版本号、Docker 或源码 `dev` 分支 commit）",
          "2. **最小复现步骤**（具体点击路径或输入内容）",
          "3. **后端终端报错日志 / 浏览器控制台截图**（注意遮挡 API Key）",
          "",
          "补充后我们会第一时间继续跟进～",
        ].join("\n"),
      );
    } else if (cmd.type === "close") {
      const arg = cmd.arg || "";
      const dupMatch = arg.match(/^(?:dup|duplicate)\s+#?(\d+)/i);
      const fixedMatch = arg.match(/^(?:fixed|done)\s*(?:#?(\d+))?/i);
      const notPlanned = /^(?:not-planned|wontfix|stale|invalid)\b/i.exec(arg);

      let stateReason = "completed";
      if (dupMatch) {
        stateReason = "not_planned";
        await gh.addLabels(issueNumber, ["duplicate"]);
        await gh.comment(
          issueNumber,
          `感谢反馈！该问题与 #${dupMatch[1]} 重复，我们将统一在 #${dupMatch[1]} 跟进处理，本单先关闭～`,
        );
      } else if (fixedMatch) {
        stateReason = "completed";
        const refTxt = fixedMatch[1] ? ` #${fixedMatch[1]}` : "近期更新";
        await gh.comment(
          issueNumber,
          `感谢反馈！该问题已在${refTxt}中修复/完成，本单关闭；如更新到最新版本后仍有复现，欢迎随时留言重开。`,
        );
      } else if (notPlanned) {
        stateReason = "not_planned";
        const kw = notPlanned[0].toLowerCase();
        if (kw === "invalid" || kw === "stale" || kw === "wontfix") {
          await gh.addLabels(issueNumber, [kw]);
        }
        await gh.comment(
          issueNumber,
          "感谢反馈与讨论！综合当前维护方向与优先级，本单暂不纳入近期计划，先行关闭；后续如有新的上下文欢迎继续补充。",
        );
      }

      const patchBody = isPR ? { state: "closed" } : { state: "closed", state_reason: stateReason };
      await gh.request("PATCH", `/issues/${issueNumber}`, patchBody);
    } else if (cmd.type === "reopen") {
      await gh.request("PATCH", `/issues/${issueNumber}`, { state: "open" });
    } else if (cmd.type === "ci") {
      if (!isPR) {
        await gh.comment(issueNumber, `ℹ️ \`/ci\` 仅在 Pull Request 下可用。`);
        continue;
      }
      const { data: pr } = await gh.request("GET", `/pulls/${issueNumber}`);
      const headSha = pr?.head?.sha;
      const { data: runsData } = await gh.request(
        "GET",
        `/actions/runs?head_sha=${encodeURIComponent(headSha)}&per_page=30`,
      );
      const pendingRuns = (runsData?.workflow_runs || []).filter(
        (r) => r.status === "action_required",
      );
      if (pendingRuns.length === 0) {
        await gh.comment(
          issueNumber,
          `ℹ️ 当前 commit (\`${(headSha || "").slice(0, 7)}\`) 没有处于等待审批（\`action_required\`）状态的 CI 流水线。`,
        );
        continue;
      }
      let approved = 0;
      let forbidden = false;
      for (const run of pendingRuns) {
        const { status } = await gh.request(
          "POST",
          `/actions/runs/${run.id}/approve`,
          undefined,
          [403, 404, 422],
        );
        if (status >= 200 && status < 300) approved += 1;
        else if (status === 403) forbidden = true;
      }
      if (approved > 0) {
        await gh.comment(issueNumber, `🚀 已由 @${actor} 放行 ${approved} 条待审批 CI 流水线。`);
      } else if (forbidden) {
        const links = pendingRuns.map((r) => `[${r.name}](${r.html_url})`).join("、");
        await gh.comment(
          issueNumber,
          `ℹ️ 默认 \`GITHUB_TOKEN\` 无权代点首次贡献者审批，请拥有 Maintain 权限的同学直接点开流水线点击 **Approve and run**：${links}`,
        );
      }
    } else if (cmd.type === "pancake") {
      await gh.addLabels(issueNumber, ["needs-pancake"]);
      const noteLine = cmd.note ? `\n> **初审说明**：${cmd.note}` : "";
      await gh.comment(
        issueNumber,
        `🔔 @pancacake 本单由 Maintainer @${actor} 标记为需拍板（\`needs-pancake\`）。${noteLine}`,
      );
      const webhook = (process.env.FEISHU_ESCALATE_WEBHOOK || "").trim();
      if (webhook) {
        await fetch(webhook, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            msg_type: "text",
            content: {
              text: `🔔 [GitHub 需拍板] #${issueNumber} ${issueTitle}\n提交 Maintainer: @${actor}${cmd.note ? `\n说明: ${cmd.note}` : ""}\n链接: ${issueUrl}`,
            },
          }),
        }).catch(() => {});
      }
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
