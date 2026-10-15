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
  addEventListener(name, handler) {
    (this.handlers ||= {})[name] = handler;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
}
const html = readFileSync(
  new URL("../pages/providers/index.html", import.meta.url),
  "utf8",
);
const ids = new Map(
  [...html.matchAll(/id="([^"]+)"/g)].map((x) => [x[1], new Element()]),
);
const account = {
  id: "local",
  name: "Local Codex",
  status: "ready",
  credential_mode: "local_codex",
  credential_source: "local_codex",
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
let pollFailure;
let loginStarts = 0;
let cancelResponse = null;
const device = {id: "device", name: "Work", status: "ready", credential_mode: "device_oauth", account_revision: "device-one"};
let slowUsage = null;
let deviceBody;
const usageBodies = [];
const providerUpdates = [];
// Provider writes and list reads can be held or redirected by a test.
let updateHandler = null;
let listCalls = 0;
let listGate = null;
let deviceUsage = {windows: [{label_seconds: 604800, used_percent: 60}]};
const editable = ["name", "enabled", "routing_mode"];
const bridge = {
  ready: async () => ({ locale: "zh-CN" }),
  getLocale: () => "zh-CN",
  apiPost: async (endpoint, body) => {
    if (endpoint === "providers/update") {
      providerUpdates.push(body);
      if (updateHandler) return updateHandler(body);
      const target = [account, device].find((p) => p.id === body.source_id);
      for (const key of editable) if (key in body) target[key] = body[key];
      return { status: "success", provider: { ...target } };
    }
    if (endpoint === "providers/list") {
      listCalls += 1;
      // Snapshot at request time, so a held response can be stale.
      const snapshot = { providers: [account, device].map((p) => ({ ...p })) };
      if (listGate) await listGate.promise;
      return snapshot;
    }
    if (endpoint === "account/usage") {
      usageBodies.push(body);
      if (body.source_id === "device") return {status: "success", account: {...device}, usage: deviceUsage};
      if (slowUsage) return slowUsage;
      if (usage instanceof Error) throw usage;
      return usage;
    }
    if (endpoint === "device/start") {
      loginStarts += 1;
      deviceBody = body;
      return {
        status: "pending",
        session_id: "device-one",
        interval: 5,
        user_code: "test-code",
        verify_url: "https://example.com",
      };
    }
    if (endpoint === "device/poll")
      return new Promise((resolve, reject) => {
        pollResult = resolve;
        pollFailure = reject;
      });
    if (endpoint === "device/cancel") return cancelResponse || { status: "cancelled" };
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
  new URL("../pages/providers/app.js", import.meta.url),
  "utf8",
);
const page = await vm.runInNewContext(
  `(async () => {${source}\n await queryUsage(); return {queryUsage, startLogin, cancelLogin, closeLogin, poll, selectProvider, openLogin};})()`,
  { window, document, navigator: {}, console },
);
const read = (id) => ids.get(id).textContent;
assert.match(read("usage-result"), /每周.*96%/);
// A weekly-only Pro response renders exactly one compact quota line.
assert.equal(ids.get("usage-result").children.length, 1);
assert.equal(read("plan"), "Pro");
assert.match(read("providers"), /本地 Codex.*Work/);
assert.doesNotMatch(read("providers"), /备用/);
assert.equal(usageBodies.at(-1).source_id, "local");
assert.equal(ids.get("quota-policy").hidden, true);
assert.equal(read("quota-policy"), "");

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
assert.match(read("usage-result"), /5 小时.*—.*暂不可用.*每周.*0%/);
assert.equal(ids.get("usage-result").children.length, 2);
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

// Switching rows while an old lookup is pending must never paint its quota.
let resolveOld;
slowUsage = new Promise((resolve) => { resolveOld = resolve; });
const oldQuery = page.queryUsage();
await new Promise((resolve) => setImmediate(resolve));
await page.selectProvider("device");
assert.match(read("usage-result"), /40%/);
assert.equal(read("source-name"), "Work");
// Without a confirmed Pro plan, a lone weekly window keeps its caveat.
assert.equal(ids.get("quota-policy").hidden, false);
assert.match(read("quota-policy"), /不代表无限额度/);
resolveOld({status: "success", account, usage: {windows: [{label_seconds: 604800, used_percent: 1}]}});
await oldQuery;
assert.match(read("usage-result"), /40%/);
assert.equal(read("source-name"), "Work");
assert.equal(ids.get("open-login").hidden, false);
slowUsage = null;
account.status = "not_logged_in";
await page.selectProvider("local");
assert.match(read("providers"), /本地 Codex/);
assert.match(read("usage-result"), /未检测到本地登录/);
assert.equal(ids.get("open-login").hidden, true);
page.openLogin();
ids.get("login-name").value = "Personal";
const pendingLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(deviceBody.name, "Personal");
assert.equal(deviceBody.source_id, undefined);
await page.cancelLogin();
pollResult({ status: "success" });
await pendingLogin;
assert.equal(read("status"), "已取消登录。");
assert.equal(ids.get("instructions").hidden, true);
assert.equal(ids.get("cancel").hidden, true);
// A successful poll must survive a concurrent cancellation rejected by the server.
page.openLogin("device");
const successfulLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(deviceBody.source_id, "device");
let rejectCancel;
cancelResponse = new Promise((resolve, reject) => { rejectCancel = reject; });
const refusedCancellation = page.cancelLogin();
pollResult({status: "success", source_id: "device"});
await successfulLogin;
rejectCancel(new Error("Already saved"));
await refusedCancellation;
assert.match(read("status"), /Provider 已保存/);
assert.equal(ids.get("error").hidden, true);

// A missing session is terminal: refresh potentially saved providers and allow retry.
cancelResponse = null;
page.openLogin();
const expiredLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
const listsBeforeExpiry = listCalls;
pollResult({status: "expired"});
await expiredLogin;
await new Promise((resolve) => setImmediate(resolve));
assert.match(read("error"), /登录会话已失效/);
assert.equal(ids.get("instructions").hidden, true);
assert.equal(ids.get("cancel").hidden, true);
assert.equal(ids.get("start").hidden, false);
assert.ok(listCalls > listsBeforeExpiry);
await page.closeLogin();
assert.equal(ids.get("login-dialog").open, false);
page.openLogin();
const startsBeforeRetry = loginStarts;
const retriedLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(loginStarts, startsBeforeRetry + 1);
pollResult({status: "pending"});
await retriedLogin;

// Closing before the next poll must also recover an expired session.
cancelResponse = {status: "expired"};
const listsBeforeClose = listCalls;
await page.closeLogin();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(ids.get("login-dialog").open, false);
assert.ok(listCalls > listsBeforeClose);

// Network failure remains nonterminal; retry can recover when cancel confirms expiry.
page.openLogin();
const networkLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
pollFailure(new Error("Network unavailable"));
await networkLogin;
for (let attempt = 1; attempt < 5; attempt += 1) {
  const failedPoll = page.poll("device-one", 5);
  pollFailure(new Error("Network unavailable"));
  await failedPoll;
}
assert.match(read("error"), /Network unavailable/);
assert.equal(ids.get("start").hidden, false);
cancelResponse = Promise.reject(new Error("Still saving or network unavailable"));
await page.closeLogin();
assert.equal(ids.get("login-dialog").open, true);
assert.equal(ids.get("cancel").hidden, false);
cancelResponse = {status: "expired"};
const startsAfterNetwork = loginStarts;
const recoveredLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(loginStarts, startsAfterNetwork + 1);
pollResult({status: "success", source_id: "device"});
await recoveredLogin;

// A late expired cancel response must not overwrite a concurrently received success.
page.openLogin();
const racingLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
let resolveExpiredCancel;
cancelResponse = new Promise((resolve) => { resolveExpiredCancel = resolve; });
const racingCancel = page.cancelLogin();
pollResult({status: "success", source_id: "device"});
await racingLogin;
resolveExpiredCancel({status: "expired"});
await racingCancel;
assert.match(read("status"), /Provider 已保存/);
assert.equal(ids.get("error").hidden, true);
cancelResponse = null;

// Confirming an IME candidate must not save an unfinished provider name.
await page.queryUsage();
const nameInput = ids.get("provider-name");
document.activeElement = nameInput;
nameInput.value = "gongzuo";
nameInput.handlers.input();
nameInput.handlers.keydown({ key: "Enter", isComposing: true, keyCode: 13 });
nameInput.handlers.keydown({ key: "Enter", isComposing: false, keyCode: 229 });
assert.equal(providerUpdates.length, 0);
nameInput.value = "工作";
nameInput.handlers.input();
nameInput.handlers.keydown({ key: "Enter", isComposing: false, keyCode: 13 });
await new Promise((resolve) => setImmediate(resolve));
assert.equal(providerUpdates.length, 1);
assert.equal(providerUpdates[0].source_id, "device");
assert.equal(providerUpdates[0].name, "工作");
// Rename sends only the ID and the edited field.
assert.deepEqual({...providerUpdates[0]}, {source_id: "device", name: "工作"});

// ---------- Enable switch and routing mode ----------
const tick = () => new Promise((resolve) => setImmediate(resolve));
const visibleText = (node) =>
  node.hidden ? "" : [node._text, ...node.children.map(visibleText)].join(" ");
const rowFor = (name) =>
  ids.get("providers").children.find(
    (child) => String(child.className).startsWith("provider-row") &&
      child.children[0].textContent.includes(name),
  );
const switchFor = (name) => rowFor(name).children[1];
const checked = (name) => switchFor(name).attributes["aria-checked"];
const click = async (node) => { node.handlers.click(); await tick(); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return {promise, resolve, reject};
};
document.activeElement = null;
account.status = "ready";
device.status = "ready";
await page.queryUsage();

// Legacy sources without the new fields read as enabled and fixed.
assert.equal(switchFor("本地 Codex").attributes.role, "switch");
assert.equal(checked("本地 Codex"), "true");
assert.equal(checked("工作"), "true");
assert.equal(ids.get("routing-fixed").attributes["aria-pressed"], "true");
assert.match(read("routing-help"), /仅使用此 Provider/);

// Local Codex can be disabled; only the changed field is sent and the
// returned provider is applied. Health is still shown beside the switch.
providerUpdates.length = 0;
await click(switchFor("本地 Codex"));
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "local", enabled: false});
assert.equal(checked("本地 Codex"), "false");
assert.match(visibleText(rowFor("本地 Codex")), /已停用/);
assert.match(visibleText(rowFor("本地 Codex")), /已登录/);
assert.doesNotMatch(visibleText(rowFor("工作")), /已停用/);

// A disabled device source keeps its allowance, rename, login and removal.
await click(switchFor("工作"));
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", enabled: false});
await page.queryUsage();
assert.equal(checked("工作"), "false");
assert.match(read("usage-result"), /40%/);
assert.equal(ids.get("open-login").hidden, false);
assert.equal(ids.get("delete-row").hidden, false);
assert.equal(ids.get("routing-auto").disabled, false);
assert.match(visibleText(rowFor("工作")), /已登录/);

// Reauthorizing a disabled source never enables it.
page.openLogin("device");
const relogin = page.startLogin();
await tick();
assert.deepEqual({...deviceBody}, {source_id: "device"});
pollResult({status: "success", source_id: "device"});
await relogin;
await tick();
assert.equal(checked("工作"), "false");
assert.ok(providerUpdates.every((body) => !("enabled" in body) || body.source_id !== "device" || body.enabled === false));

// Routing mode is a per-provider choice sent on its own.
await click(ids.get("routing-auto"));
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", routing_mode: "auto"});
assert.equal(ids.get("routing-auto").attributes["aria-pressed"], "true");
assert.equal(ids.get("routing-fixed").attributes["aria-pressed"], "false");
assert.match(read("routing-help"), /先用它.*列表顺序.*已启用且可用.*同一账号只尝试一次.*开始输出后不再切换/);
assert.match(visibleText(rowFor("工作")), /自动回退/);
assert.doesNotMatch(visibleText(rowFor("本地 Codex")), /自动回退/);
const sentBefore = providerUpdates.length;
await click(ids.get("routing-auto"));
assert.equal(providerUpdates.length, sentBefore, "choosing the current mode sends nothing");

// The exhausted notice follows the selected provider's routing mode.
deviceUsage = {limit_reached: true, windows: [{label_seconds: 604800, used_percent: 100}]};
await page.queryUsage();
assert.match(read("notice-text"), /已开启自动回退/);
await click(ids.get("routing-fixed"));
assert.match(read("notice-text"), /不会自动切换账号/);
deviceUsage = {windows: [{label_seconds: 604800, used_percent: 60}]};
await page.queryUsage();

// Rapid clicks while a save is in flight send one request; the controls
// for that provider are locked, other providers stay independent.
let held = deferred();
updateHandler = () => held.promise;
providerUpdates.length = 0;
await click(switchFor("工作"));
await click(switchFor("工作"));
await click(ids.get("routing-auto"));
assert.equal(providerUpdates.length, 1);
assert.deepEqual({...providerUpdates[0]}, {source_id: "device", enabled: true});
assert.equal(switchFor("工作").disabled, true);
assert.equal(switchFor("工作").attributes["aria-busy"], "true");
assert.equal(checked("工作"), "true", "the switch shows the requested value while saving");
assert.equal(ids.get("routing-auto").disabled, true);
assert.equal(ids.get("rename-provider").disabled, true);
assert.equal(switchFor("本地 Codex").disabled, false);
const otherHeld = deferred();
updateHandler = (body) => body.source_id === "local" ? otherHeld.promise : held.promise;
await click(switchFor("本地 Codex"));
assert.equal(providerUpdates.length, 2);
device.enabled = true;
held.resolve({status: "success", provider: {...device}});
account.enabled = true;
otherHeld.resolve({status: "success", provider: {...account}});
await tick();
assert.equal(checked("工作"), "true");
assert.equal(checked("本地 Codex"), "true");
assert.equal(switchFor("工作").disabled, false);
assert.equal(ids.get("routing-auto").disabled, false);
updateHandler = null;

// The server's provider object wins over the requested value.
updateHandler = (body) => ({status: "success", provider: {...device, name: "Server Name"}});
const nameField = ids.get("provider-name");
nameField.value = " 新名称 ";
nameField.handlers.input();
await click(ids.get("rename-provider"));
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", name: "新名称"});
assert.equal(read("source-name"), "Server Name");
device.name = "Server Name";
updateHandler = null;

// A list issued before a save settles must not paint the old value back.
listGate = deferred();
const staleRefresh = page.queryUsage();
await tick();
await click(switchFor("本地 Codex"));
assert.equal(checked("本地 Codex"), "false");
const gate = listGate;
listGate = null;
gate.resolve();
await staleRefresh;
assert.equal(checked("本地 Codex"), "false");
assert.equal(account.enabled, false);

// A failed save keeps the previous state, shows the error and reloads.
let listsBefore = listCalls;
updateHandler = () => { throw new Error("enabled must be a boolean."); };
await click(switchFor("Server Name"));
await tick();
assert.equal(checked("Server Name"), "true");
assert.equal(ids.get("save-error").hidden, false);
assert.match(read("save-error"), /Server Name.*enabled must be a boolean/);
assert.equal(listCalls, listsBefore + 1);
assert.equal(switchFor("Server Name").disabled, false);

// When the transport fails after the write landed, the reload shows it.
listsBefore = listCalls;
updateHandler = (body) => { device.enabled = body.enabled; throw new Error("Network Error"); };
await click(switchFor("Server Name"));
await tick();
assert.equal(listCalls, listsBefore + 1);
assert.equal(checked("Server Name"), "false");
assert.match(read("save-error"), /Network Error/);

// A success without a provider object is unclear and also reloads.
listsBefore = listCalls;
updateHandler = (body) => { device.routing_mode = body.routing_mode; return {status: "success"}; };
await click(ids.get("routing-auto"));
await tick();
assert.equal(listCalls, listsBefore + 1);
assert.match(read("save-error"), /保存结果未知/);
assert.equal(ids.get("routing-auto").attributes["aria-pressed"], "true");
updateHandler = null;

// A later successful save clears the earlier error.
await click(switchFor("Server Name"));
assert.equal(ids.get("save-error").hidden, true);
assert.equal(checked("Server Name"), "true");

// Deleting sends only the ID.
const deleteButton = ids.get("delete-provider");
const bodies = [];
const originalPost = bridge.apiPost;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/delete") { bodies.push(body); return {status: "success"}; }
  return originalPost(endpoint, body);
};
await click(deleteButton);
await click(deleteButton);
assert.deepEqual({...bodies[0]}, {source_id: "device"});
bridge.apiPost = originalPost;

// A reconciliation started after a failed save must not replace a newer view.
await page.selectProvider("device");
updateHandler = () => { throw new Error("Network Error"); };
listGate = deferred();
await click(switchFor("Server Name"));
const oldReconcile = listGate;
listGate = null;
device.name = "Newer device";
await page.selectProvider("local");
assert.ok(rowFor("Newer device"));
oldReconcile.resolve();
await tick();
assert.ok(rowFor("Newer device"), "a stale reconciliation must not overwrite the newer list");
updateHandler = null;

// A local account may change while saving controls. Never relabel its old quota.
await page.selectProvider("device");
assert.match(read("usage-result"), /40%/);
const oldAccount = {...device};
const oldDeviceUsage = deviceUsage;
const oldQuota = deferred();
let holdNextQuota = true;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "account/usage" && body.source_id === "device" && holdNextQuota) {
    holdNextQuota = false;
    return oldQuota.promise;
  }
  return originalPost(endpoint, body);
};
const staleQuotaRefresh = page.queryUsage();
await tick();
updateHandler = (body) => {
  Object.assign(device, {enabled: body.enabled, email: "new@example.com", account_revision: "device-two"});
  deviceUsage = {windows: [{label_seconds: 604800, used_percent: 5}]};
  return {status: "success", provider: {...device}};
};
await click(switchFor("Newer device"));
assert.doesNotMatch(read("usage-result"), /40%/, "a new account must clear the previous account's quota");
assert.match(visibleText(rowFor("Newer device")), /new@example.com/);
oldQuota.resolve({status: "success", account: oldAccount, usage: oldDeviceUsage});
await staleQuotaRefresh;
assert.match(visibleText(rowFor("Newer device")), /new@example.com/, "old quota replies must not restore the previous account");
assert.doesNotMatch(read("usage-result"), /40%/);
assert.match(read("usage-result"), /95%/);
bridge.apiPost = originalPost;
updateHandler = null;

// A server-confirmed routing mode must also win in the quota notice.
device.routing_mode = "fixed";
deviceUsage = {limit_reached: true, windows: [{label_seconds: 604800, used_percent: 100}]};
await page.queryUsage();
updateHandler = () => ({status: "success", provider: {...device}});
await click(ids.get("routing-auto"));
assert.equal(ids.get("routing-fixed").attributes["aria-pressed"], "true");
assert.match(read("notice-text"), /不会自动切换账号/, "the notice must use the confirmed mode after pending state is removed");
updateHandler = null;

// A delayed recovery read cannot resurrect a provider deleted in the meantime.
const delayedRecovery = deferred();
let delayRecovery = true;
let removed = false;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/delete") {
    removed = true;
    return {status: "success"};
  }
  if (endpoint === "providers/list") {
    const snapshot = {providers: (removed ? [account] : [account, device]).map((p) => ({...p}))};
    if (delayRecovery) { delayRecovery = false; await delayedRecovery.promise; }
    return snapshot;
  }
  return originalPost(endpoint, body);
};
updateHandler = () => { throw new Error("Network Error"); };
await click(switchFor("Newer device"));
await click(deleteButton);
await click(deleteButton);
assert.equal(rowFor("Newer device"), undefined);
delayedRecovery.resolve();
await tick();
assert.equal(rowFor("Newer device"), undefined, "a stale recovery read must not resurrect a deleted provider");
bridge.apiPost = originalPost;
updateHandler = null;
console.log("View regressions passed: quota windows, provider selection, stale-result isolation, login and cancellation races, IME-safe rename, enable switch, routing mode, serialized saves, stale-list protection, failed and unclear saves, reconciliation after navigation/deletion, account identity changes, confirmed routing notices.");
