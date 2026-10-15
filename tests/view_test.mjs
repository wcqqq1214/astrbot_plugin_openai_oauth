// Exercise the production page with a minimal DOM and a controlled bridge.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this._text = "";
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((x) => x.textContent).join(" ");
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this._text = "";
    this.children = children;
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  addEventListener() {}
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
}
const html = readFileSync(
  new URL("../pages/login/index.html", import.meta.url),
  "utf8",
);
const ids = new Map(
  [...html.matchAll(/id="([^"]+)"/g)].map((x) => [x[1], new Element()]),
);
const account = {
  status: "ready",
  credential_source: "local_codex",
  backup_status: "saved",
  account_revision: "one",
};
let usage = {
  status: "success",
  account,
  usage: {
    plan_type: "pro",
    allowed: true,
    windows: [{ label_seconds: 604800, used_percent: 4, reset_at: 1792649624 }],
  },
};
let pollResult;
const bridge = {
  ready: async () => ({ locale: "zh-CN" }),
  getLocale: () => "zh-CN",
  apiPost: async (endpoint) => {
    if (endpoint === "account/status") return account;
    if (endpoint === "account/usage") {
      if (usage instanceof Error) throw usage;
      return usage;
    }
    if (endpoint === "device/start")
      return {
        status: "pending",
        session_id: "device-one",
        interval: 5,
        user_code: "test-code",
        verify_url: "https://example.com",
      };
    if (endpoint === "device/poll")
      return new Promise((resolve) => {
        pollResult = resolve;
      });
    if (endpoint === "device/cancel") return { status: "cancelled" };
    throw new Error("Unexpected endpoint");
  },
};
const document = {
  getElementById: (id) => {
    assert.ok(ids.has(id), `missing element ${id}`);
    return ids.get(id);
  },
  createElement: (tag) => new Element(tag),
  documentElement: new Element(),
  addEventListener() {},
};
const window = {
  AstrBotPluginPage: bridge,
  setInterval() {},
  setTimeout() {
    return 1;
  },
  clearTimeout() {},
};
const source = readFileSync(
  new URL("../pages/login/app.js", import.meta.url),
  "utf8",
);
const page = await vm.runInNewContext(
  `(async () => {${source}\n await queryUsage(); return {queryUsage, startLogin, cancelLogin};})()`,
  { window, document, navigator: {}, console },
);
const read = (id) => ids.get(id).textContent;
assert.match(read("usage-result"), /每周额度.*96%/);
// Relative reset text can legitimately read "5 小时后重置"; only the window
// label must be absent.
assert.doesNotMatch(read("usage-result"), /5 小时额度/);
assert.equal(read("plan"), "Pro");
assert.equal(read("backup-status"), "已保存");
assert.match(read("quota-policy"), /没有独立的 5 小时窗口/);

usage = {
  status: "success",
  account,
  usage: {
    windows: [
      { label_seconds: 18000, used_percent: null },
      { label_seconds: 604800, used_percent: 100 },
    ],
  },
};
await page.queryUsage();
assert.match(read("usage-result"), /5 小时额度.*—.*暂不可用.*每周额度.*0%/);
assert.doesNotMatch(read("usage-result"), /100%/);
assert.equal(ids.get("plan").hidden, true);
assert.equal(ids.get("quota-policy").hidden, true);

// Both exhausted windows must reset before the included allowance recovers.
const laterReset = new Date(Date.now() + 2 * 86400000);
usage = {
  status: "success", account,
  usage: {limit_reached: true, windows: [
    {label_seconds: 18000, used_percent: 100, reset_at: Date.now() / 1000 + 3600},
    {label_seconds: 604800, used_percent: 100, reset_at: laterReset.getTime() / 1000},
  ]},
};
await page.queryUsage();
const expectedReset = laterReset.toLocaleDateString("zh-CN", {month: "short", day: "numeric"}) + " " + laterReset.toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit", hour12: false});
assert.ok(read("notice-text").includes(expectedReset));

// A server-enforced cooldown must not be shortened by a quota-window hint.
account.status = "cooling";
account.cooldown_until = laterReset.getTime() / 1000;
usage.usage.windows[1].used_percent = 40;
await page.queryUsage();
assert.ok(read("notice-text").includes(expectedReset));
// A missing quota reset still uses the server's authoritative cutoff.
usage.usage.windows[0].reset_at = null;
await page.queryUsage();
assert.ok(read("notice-text").includes(expectedReset));
account.status = "ready";
delete account.cooldown_until;

usage = new Error("Network unavailable");
await page.queryUsage();
assert.match(read("usage-result"), /暂时无法获取/);
assert.match(read("account-status"), /已登录/);
assert.doesNotMatch(read("usage-result"), /96%/);

const pendingLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
await page.cancelLogin();
pollResult({ status: "success" });
await pendingLogin;
assert.equal(read("status"), "已取消登录。");
assert.equal(ids.get("instructions").hidden, true);
assert.equal(ids.get("cancel").hidden, true);
console.log(
  "View regressions passed: weekly-only Pro, missing quota, lookup error, cancelled-session race.",
);
