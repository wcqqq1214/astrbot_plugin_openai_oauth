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
  getAttribute(key) {
    return key in this.attributes ? this.attributes[key] : null;
  }
  removeAttribute(key) {
    delete this.attributes[key];
  }
  focus() {
    document.activeElement = this;
    this.focusCount = (this.focusCount || 0) + 1;
  }
  select() {
    this.selected = true;
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
let startResponse = null;
let contextHandler = null;
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
let initialLocale = "zh-CN";
const bridge = {
  ready: async () => ({ locale: initialLocale }),
  onContext: (handler) => { contextHandler = handler; },
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
      if (startResponse) return startResponse;
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
  body: new Element("body"),
  activeElement: null,
  addEventListener() {},
  // Records what a synchronous copy would place on the clipboard.
  execCommand(command) {
    if (command !== "copy") return false;
    copyCommands.push(document.activeElement?.value);
    return execCopyResult;
  },
};
const copyCommands = [];
let execCopyResult = true;
const clipboardWrites = [];
let clipboardResult = "reject";
let clipboardHold = null;
const window = {
  AstrBotPluginPage: bridge,
  setInterval() {},
  setTimeout() {
    return 1;
  },
  clearTimeout() {},

};
const navigator = {
  clipboard: {
    writeText: async (value) => {
      clipboardWrites.push(value);
      if (clipboardResult === "reject") throw new Error("Blocked by permissions policy");
      if (clipboardResult === "hold") await clipboardHold.promise;
    },
  },
};
const source = readFileSync(
  new URL("../pages/providers/app.js", import.meta.url),
  "utf8",
);
const page = await vm.runInNewContext(
  `(async () => {${source}\n await queryUsage(); return {queryUsage, startLogin, cancelLogin, closeLogin, poll, selectProvider, openProvider, loadProviders, queryProvider, rowNodes, openLogin};})()`,
  { window, document, navigator, console, URL },
);
// Existing form/login scenarios inspect one named provider's panel at a time.
// Navigation in those scenarios explicitly opens a row; toggle behavior is
// covered separately below, without restoring the old exclusive selection.
let inspectedProvider = "local";
const panelElement = (key, sourceId = inspectedProvider) => page.rowNodes.get(sourceId).panel.elements[key];
const originalGet = ids.get.bind(ids);
ids.get = (id) => originalGet(id) || panelElement(id);
const inspectProvider = async (id) => {
  inspectedProvider = id;
  await page.loadProviders();
  await page.openProvider(id);
};
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
await inspectProvider("device");
assert.match(read("usage-result"), /40%/);
assert.equal(read("source-name"), "Work");
// Without a confirmed Pro plan, a lone weekly window keeps its caveat.
assert.equal(ids.get("quota-policy").hidden, false);
assert.match(read("quota-policy"), /不代表无限额度/);
resolveOld({status: "success", account, usage: {windows: [{label_seconds: 604800, used_percent: 1}]}});
await oldQuery;
assert.match(read("usage-result"), /40%/);
assert.equal(read("source-name"), "Work");
slowUsage = null;
account.status = "not_logged_in";
await inspectProvider("local");
assert.match(read("providers"), /本地 Codex/);
assert.match(read("usage-result"), /未检测到本地登录/);
page.openLogin();
ids.get("login-name").value = "Personal";
const pendingLogin = page.startLogin();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(deviceBody.name, "Personal");
assert.equal(deviceBody.source_id, undefined);
await page.cancelLogin();
pollResult({ status: "success" });
await pendingLogin;
assert.equal(read("status"), "已取消登录");
assert.equal(ids.get("device-panel").hidden, true);
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
assert.match(read("status"), /登录会话已失效/);
assert.equal(ids.get("error").hidden, true, "an expired session is not reported as a failure");
assert.equal(ids.get("device-panel").hidden, true);
assert.equal(ids.get("user-code").value, "");
assert.equal(ids.get("verify-url").value, "");
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
// The session may still be authorized, so its code stays and the form does not return.
assert.equal(ids.get("device-panel").hidden, false);
assert.equal(ids.get("login-intro").hidden, true);
assert.equal(ids.get("login-name-field").hidden, true);
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

// ---------- Row controls and the settings dialog ----------
const tick = () => new Promise((resolve) => setImmediate(resolve));
const visibleText = (node) =>
  node.hidden ? "" : [node._text, ...node.children.map(visibleText)].join(" ");
const rowFor = (name) =>
  ids.get("providers").children.find(
    (child) => String(child.className).startsWith("provider-row") &&
      child.children[0].textContent.includes(name),
  );
const partOf = (name, className) =>
  rowFor(name).children.find((child) => String(child.className).split(" ").includes(className));
const switchFor = (name) => partOf(name, "switch");
const gearFor = (name) => partOf(name, "row-settings");
const mainFor = (name) => partOf(name, "provider-main");
const checked = (name) => switchFor(name).attributes["aria-checked"];
const click = async (node) => { node.handlers.click(); await tick(); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return {promise, resolve, reject};
};
const settingsBox = ids.get("settings-dialog");
const nameInput = ids.get("settings-name");
const saveButton = ids.get("settings-save");
const typeName = (value) => { nameInput.value = value; nameInput.handlers.input(); };
const openSettings = async (name) => { await click(gearFor(name)); assert.equal(settingsBox.open, true); };
const escape = () => settingsBox.handlers.cancel({ preventDefault() {} });

await page.closeLogin();
assert.equal(ids.get("login-dialog").open, false);
await page.queryUsage();
// The gear has its own accessible name and only opens the dialog.
assert.equal(gearFor("本地 Codex").attributes["aria-label"], "设置 本地 Codex");
assert.equal(gearFor("Work").attributes["aria-label"], "设置 Work");
assert.equal(gearFor("Work").attributes["aria-haspopup"], "dialog");
assert.ok(rowFor("Work").children.every((child) => child.tag === "button"), "row controls are sibling buttons");
const expandedBefore = mainFor("Work").attributes["aria-expanded"];
const updatesBeforeGear = providerUpdates.length;
await openSettings("Work");
assert.equal(read("settings-title"), "Work");
assert.equal(nameInput.value, "Work");
assert.equal(document.activeElement, nameInput, "the name field takes initial focus");
assert.equal(mainFor("Work").attributes["aria-expanded"], expandedBefore, "the gear never expands the row");
assert.equal(providerUpdates.length, updatesBeforeGear);
assert.equal(saveButton.disabled, true, "an untouched draft cannot be saved");

// Confirming an IME candidate must not save an unfinished provider name.
typeName("gongzuo");
nameInput.handlers.keydown({ key: "Enter", isComposing: true, keyCode: 13 });
nameInput.handlers.keydown({ key: "Enter", isComposing: false, keyCode: 229 });
assert.equal(providerUpdates.length, 0);
typeName("工作");
nameInput.handlers.keydown({ key: "Enter", isComposing: false, keyCode: 13 });
await tick();
assert.equal(providerUpdates.length, 1);
// Rename sends only the ID and the edited field, then closes the dialog.
assert.deepEqual({...providerUpdates[0]}, {source_id: "device", name: "工作"});
assert.equal(settingsBox.open, false);
assert.equal(document.activeElement, gearFor("工作"), "focus returns to the row's gear");
assert.match(read("providers"), /工作/);
document.activeElement = null;
account.status = "ready";
device.status = "ready";
await page.queryUsage();

// Legacy sources without the new fields read as enabled and fixed.
assert.equal(switchFor("本地 Codex").attributes.role, "switch");
assert.equal(checked("本地 Codex"), "true");
assert.equal(checked("工作"), "true");
await openSettings("本地 Codex");
assert.equal(ids.get("settings-routing-fixed").attributes["aria-pressed"], "true");
assert.match(read("settings-routing-help"), /仅使用此 Provider/);
await click(ids.get("settings-cancel"));

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
inspectedProvider = "device";
await click(switchFor("工作"));
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", enabled: false});
await page.queryUsage();
assert.equal(checked("工作"), "false");
assert.match(read("usage-result"), /40%/);
await openSettings("工作");
assert.equal(ids.get("settings-account").hidden, false);
assert.equal(ids.get("settings-reauth").disabled, false);
assert.equal(ids.get("settings-remove").disabled, false);
await click(ids.get("settings-cancel"));
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
await page.closeLogin();

// Routing mode is a per-provider choice; only the changed field is sent.
await openSettings("工作");
await click(ids.get("settings-routing-auto"));
assert.equal(ids.get("settings-routing-auto").attributes["aria-pressed"], "true");
assert.equal(ids.get("settings-routing-fixed").attributes["aria-pressed"], "false");
assert.match(read("settings-routing-help"), /先用它.*列表顺序.*已启用且可用.*同一账号只尝试一次.*开始输出后不再切换/);
// Switching back to the starting mode is not a change.
await click(ids.get("settings-routing-fixed"));
assert.equal(saveButton.disabled, true, "returning to the starting values is not a change");
await click(ids.get("settings-routing-auto"));
await click(saveButton);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", routing_mode: "auto"});
assert.equal(settingsBox.open, false);
assert.match(visibleText(rowFor("工作")), /自动回退/);
assert.doesNotMatch(visibleText(rowFor("本地 Codex")), /自动回退/);

// The exhausted notice follows the selected provider's routing mode.
deviceUsage = {limit_reached: true, windows: [{label_seconds: 604800, used_percent: 100}]};
await page.queryUsage();
assert.match(read("notice-text"), /已开启自动回退/);
await openSettings("工作");
await click(ids.get("settings-routing-fixed"));
assert.match(read("notice-text"), /已开启自动回退/, "an unsaved draft changes nothing on the page");
await click(saveButton);
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
assert.equal(providerUpdates.length, 1);
assert.deepEqual({...providerUpdates[0]}, {source_id: "device", enabled: true});
assert.equal(switchFor("工作").disabled, true);
assert.equal(switchFor("工作").attributes["aria-busy"], "true");
assert.equal(checked("工作"), "true", "the switch shows the requested value while saving");
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
updateHandler = null;

// The server's provider object wins over the requested value, and names are
// trimmed the way the server stores them.
updateHandler = (body) => ({status: "success", provider: {...device, name: "Server Name"}});
await openSettings("工作");
typeName(" 新名称 ");
await click(saveButton);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", name: "新名称"});
assert.equal(read("source-name"), "Server Name");
assert.match(read("providers"), /Server Name/);
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

// A success without a provider object is unclear: the dialog reloads, stays
// open with its draft and never claims success. A field the reload shows
// as stored is no longer pending, so it is not sent again.
listsBefore = listCalls;
updateHandler = (body) => { device.routing_mode = body.routing_mode; return {status: "success"}; };
await openSettings("Server Name");
await click(ids.get("settings-routing-auto"));
await click(saveButton);
await tick();
assert.equal(listCalls, listsBefore + 1);
assert.equal(settingsBox.open, true);
assert.match(read("settings-error"), /保存结果未知/);
assert.equal(ids.get("settings-routing-auto").attributes["aria-pressed"], "true");
assert.equal(saveButton.disabled, true, "a change confirmed by the reload is not re-sent");
assert.doesNotMatch(read("save-error"), /保存结果未知/, "dialog saves report inside the dialog");
assert.match(visibleText(rowFor("Server Name")), /自动回退/);
await click(ids.get("settings-cancel"));
assert.equal(settingsBox.open, false);
updateHandler = null;

// A later successful save clears the earlier error.
await click(switchFor("Server Name"));
assert.equal(ids.get("save-error").hidden, true);
assert.equal(checked("Server Name"), "true");

// Deleting sends only the ID.
const removeButton = ids.get("settings-remove");
const removeFromSettings = async (name) => {
  await openSettings(name);
  await click(removeButton);
  await click(removeButton);
};
const bodies = [];
const originalPost = bridge.apiPost;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/delete") { bodies.push(body); return {status: "success"}; }
  return originalPost(endpoint, body);
};
await removeFromSettings("Server Name");
assert.deepEqual({...bodies[0]}, {source_id: "device"});
assert.equal(settingsBox.open, false);
bridge.apiPost = originalPost;

// A reconciliation started after a failed save must not replace a newer view.
await inspectProvider("device");
updateHandler = () => { throw new Error("Network Error"); };
listGate = deferred();
await click(switchFor("Server Name"));
const oldReconcile = listGate;
listGate = null;
device.name = "Newer device";
await inspectProvider("local");
assert.ok(rowFor("Newer device"));
oldReconcile.resolve();
await tick();
assert.ok(rowFor("Newer device"), "a stale reconciliation must not overwrite the newer list");
updateHandler = null;

// A local account may change while saving controls. Never relabel its old quota.
await inspectProvider("device");
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
await openSettings("Newer device");
await click(ids.get("settings-routing-auto"));
await click(saveButton);
assert.equal(settingsBox.open, false);
assert.doesNotMatch(visibleText(rowFor("Newer device")), /自动回退/);
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
await removeFromSettings("Newer device");
assert.equal(rowFor("Newer device"), undefined);
delayedRecovery.resolve();
await tick();
assert.equal(rowFor("Newer device"), undefined, "a stale recovery read must not resurrect a deleted provider");
bridge.apiPost = originalPost;
updateHandler = null;

// ---------- Device login dialog ----------
const shown = (id) => !ids.get(id).hidden;
const dialog = ids.get("login-dialog");
const startDevice = async (sourceId) => {
  page.openLogin(sourceId);
  const pending = page.startLogin();
  await tick();
  return [pending];
};
device.status = "ready";
device.email = "old@example.com";
device.plan_type = "plus";
cancelResponse = null;
await page.queryUsage();
assert.ok(rowFor("Newer device"));

// The add form keeps the optional name with its default; an empty name
// lets the server apply its own default.
page.openLogin();
assert.equal(read("instructions-title"), "新增 Provider");
assert.equal(ids.get("login-name").value, "ChatGPT");
assert.ok(shown("login-name-field") && shown("login-intro"));
assert.equal(read("start"), "获取设备码");
assert.equal(shown("device-panel"), false);
ids.get("login-name").value = "   ";
ids.get("start").focus();
let waitingLogin = page.startLogin();
await tick();
assert.deepEqual({...deviceBody}, {});
// Waiting: both copy actions and the browser instructions replace the form.
assert.ok(shown("device-panel"));
assert.equal(ids.get("user-code").value, "test-code");
assert.equal(read("copy-code"), "复制设备码");
assert.equal(read("copy-url"), "复制授权链接");
assert.equal(read("device-hint"), "在浏览器中打开链接，输入设备码完成授权。");
assert.equal(ids.has("open-verify"), false);
assert.equal(document.activeElement, ids.get("copy-code"), "focus moves to the code copy action");
assert.equal(ids.get("verify-url").value, "https://example.com/");
assert.equal(shown("login-name-field") || shown("login-intro"), false);
assert.match(read("status"), /等待授权/);
assert.equal(ids.get("status-dots").hidden, false);
assert.ok(shown("cancel") && !shown("start") && !shown("done"));

// Copying the code or the link reports which one was copied.
await ids.get("copy-code").handlers.click();
await tick();
assert.equal(copyCommands.at(-1), "test-code");
assert.equal(read("copy-code"), "已复制");
assert.equal(read("copy-status"), "设备码已复制。");
await ids.get("copy-url").handlers.click();
await tick();
assert.equal(copyCommands.at(-1), "https://example.com/");
assert.match(read("copy-status"), /链接已复制/);
// Without a synchronous copy the Clipboard API is the fallback; when both
// fail the value is selected for manual copying.
execCopyResult = false;
clipboardResult = "resolve";
await ids.get("copy-code").handlers.click();
await tick();
assert.equal(clipboardWrites.at(-1), "test-code");
assert.equal(read("copy-status"), "设备码已复制。");
clipboardResult = "reject";
ids.get("user-code").selected = false;
await ids.get("copy-code").handlers.click();
await tick();
assert.match(read("copy-status"), /复制失败/);
assert.equal(ids.get("user-code").selected, true);
execCopyResult = true;
// A copy that settles after the code was replaced reports nothing.
execCopyResult = false;
clipboardResult = "hold";
clipboardHold = deferred();
const slowCopy = ids.get("copy-code").handlers.click();
await tick();
pollResult({status: "pending"});
await waitingLogin;
startResponse = {status: "pending", session_id: "device-fresh", interval: 5, user_code: "fresh-code", verify_url: "https://example.com"};
waitingLogin = page.startLogin();
await tick();
startResponse = null;
assert.equal(ids.get("user-code").value, "fresh-code");
assert.equal(read("copy-status"), "");
clipboardHold.resolve();
await slowCopy;
await tick();
assert.equal(read("copy-status"), "", "a late copy result must not describe the new code");
assert.equal(read("copy-code"), "复制设备码");
execCopyResult = true;
clipboardResult = "reject";
// Continue with the fresh session, as the server would.
pollResult({status: "pending"});
await waitingLogin;
waitingLogin = page.poll("device-fresh", 5);

// A transient poll failure keeps the code and says it is retrying.
pollFailure(new Error("Network unavailable"));
await waitingLogin;
assert.ok(shown("device-panel"));
assert.match(read("status"), /连接暂时中断，正在重试/);
// Saving: the code and the cancel action go away, closing is held back
// because the server refuses to cancel now, and no cancel is sent.
let savingPoll = page.poll("device-fresh", 5);
pollResult({status: "saving"});
await savingPoll;
assert.match(read("status"), /已授权，正在保存 Provider/);
assert.equal(shown("device-panel"), false);
assert.equal(shown("cancel") || shown("start") || shown("done"), false);
assert.equal(ids.get("close-login").disabled, true);
let cancelCalls = 0;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "device/cancel") cancelCalls += 1;
  return originalPost(endpoint, body);
};
await page.closeLogin();
assert.equal(dialog.open, true);
assert.equal(cancelCalls, 0);
// Native dialog dismissal (for example repeated Escape) must not hide saving.
dialog.close();
await dialog.handlers.close();
assert.equal(dialog.open, true);
assert.equal(cancelCalls, 0, "a known saving session cannot be cancelled");

// Repeated poll failures while saving never bring back an obsolete code.
for (let attempt = 0; attempt < 5; attempt += 1) {
  const failedPoll = page.poll("device-fresh", 5);
  pollFailure(new Error("Network unavailable"));
  await failedPoll;
}
assert.match(read("error"), /Network unavailable/);
assert.equal(shown("device-panel") || shown("cancel"), false);
assert.equal(shown("start"), true, "saving failures need a retry action");
assert.equal(read("start"), "重试查询");
// Closing now asks the server; a refused cancel (409) keeps the session.
cancelResponse = Promise.reject(new Error("授权已完成，正在保存或已保存 Provider，请等待登录结果。"));
await page.closeLogin();
assert.equal(dialog.open, true);
assert.equal(cancelCalls, 1);
assert.match(read("error"), /正在保存或已保存/);
// Retry checks the same session without cancelling or starting another login.
const startsBeforeStatusRetry = loginStarts;
const cancelsBeforeStatusRetry = cancelCalls;
const statusRetry = page.startLogin();
await tick();
assert.equal(loginStarts, startsBeforeStatusRetry);
assert.equal(cancelCalls, cancelsBeforeStatusRetry);
pollFailure(new Error("Still offline"));
await statusRetry;
assert.equal(ids.get("error").hidden, true, "retry resets the poll failure budget");
assert.match(read("status"), /正在重试/);
cancelResponse = null;
bridge.apiPost = originalPost;

// Success: the saved provider comes from a list requested after the login,
// never from the list already on the page.
device.email = "work@example.com";
listGate = deferred();
savingPoll = page.poll("device-fresh", 5);
pollResult({status: "success", source_id: "device"});
await savingPoll;
assert.equal(read("status"), "Provider 已保存");
assert.match(read("status-detail"), /模型配置/);
assert.equal(ids.get("error").hidden, true);
assert.ok(shown("done") && !shown("start") && !shown("cancel"));
assert.equal(ids.get("close-login").disabled, false);
assert.equal(shown("saved-provider"), false, "no provider is shown from a list older than the login");
const savedGate = listGate;
listGate = null;
savedGate.resolve();
await tick();
await tick();
assert.ok(shown("saved-provider"));
assert.equal(read("saved-name"), "Newer device");
assert.equal(read("saved-sub"), "work@example.com · ChatGPT Plus");
// Done closes the dialog and reveals the saved provider.
await inspectProvider("local");
ids.get("done").handlers.click();
await tick();
await tick();
assert.equal(dialog.open, false);
assert.equal(panelElement("source-name", "device").textContent, "Newer device");
assert.match(rowFor("Newer device").className, /open/);
assert.equal(mainFor("本地 Codex").attributes["aria-expanded"], "true");
assert.equal(document.activeElement, rowFor("Newer device").children[0]);

// Missing account details are not guessed.
const savedEmail = device.email;
delete device.email;
device.plan_type = "mystery";
[waitingLogin] = await startDevice("device");
assert.match(read("login-intro"), /为「Newer device」重新登录 ChatGPT/);
assert.equal(shown("login-name-field"), false);
assert.deepEqual({...deviceBody}, {source_id: "device"});
pollResult({status: "success", source_id: "device"});
await waitingLogin;
await tick();
assert.equal(read("status-detail"), "登录凭据已更新。");
assert.ok(shown("saved-provider"));
assert.equal(shown("saved-sub"), false);
await page.closeLogin();
assert.equal(dialog.open, false, "closing after success completes the login");
device.email = savedEmail;
device.plan_type = "plus";

// An expired device code offers a new code; a server error offers a retry.
[waitingLogin] = await startDevice();
pollResult({status: "timeout"});
await waitingLogin;
assert.equal(read("status"), "设备码已过期");
assert.equal(read("start"), "重新获取设备码");
assert.ok(shown("start") && !shown("cancel") && !shown("device-panel"));
assert.equal(ids.get("error").hidden, true);
waitingLogin = page.startLogin();
await tick();
pollResult({status: "error", error: "OpenAI rejected the code"});
await waitingLogin;
assert.match(read("error"), /OpenAI rejected the code/);
assert.equal(read("start"), "重新登录");
assert.ok(shown("start") && shown("login-name-field") && !shown("cancel") && !shown("device-panel"));
// A rejected start request is recoverable from the same form.
startResponse = {status: "error", message: "设备登录会话已达上限，请稍后重试"};
await page.startLogin();
assert.match(read("error"), /会话已达上限/);
assert.equal(ids.get("start").disabled, false);
assert.equal(ids.get("login-name").disabled, false);
startResponse = null;
waitingLogin = page.startLogin();
await tick();
assert.equal(ids.get("error").hidden, true);
assert.ok(shown("device-panel"));
// An unsafe verification URL is never displayed or offered for copying.
pollResult({status: "pending"});
await waitingLogin;
startResponse = {status: "pending", session_id: "device-two", interval: 5, user_code: "next-code", verify_url: "javascript:alert(1)"};
cancelResponse = {status: "cancelled"};
waitingLogin = page.startLogin();
await tick();
assert.equal(ids.get("user-code").value, "next-code");
assert.equal(ids.get("verify-url").value, "");
assert.equal(shown("verify-row"), false);
// The previous session's late result cannot affect the new one.
startResponse = null;
const latePoll = page.poll("device-one", 5);
pollResult({status: "success", source_id: "device"});
await latePoll;
assert.equal(ids.get("user-code").value, "next-code");
assert.match(read("status"), /等待授权/);

// Labels and states follow a locale change while the dialog is open.
page.openLogin();
[waitingLogin] = await startDevice();
contextHandler({locale: "en-US"});
assert.equal(read("device-hint"), "Open the link in your browser and enter the device code to authorize.");
assert.equal(read("copy-code"), "Copy device code");
assert.equal(read("code-label"), "Device code");
assert.equal(read("copy-url"), "Copy authorization link");
assert.equal(read("cancel"), "Cancel login");
assert.match(read("status"), /Waiting for authorization/);
assert.equal(ids.get("verify-url").attributes["aria-label"], "OpenAI authorization link");
contextHandler({locale: "zh-CN"});
assert.match(read("status"), /等待授权/);
await page.closeLogin();
assert.equal(dialog.open, false);
cancelResponse = null;
// A forced close while obtaining a code must not orphan the arriving session.
page.openLogin();
const startingGate = deferred();
startResponse = startingGate.promise;
const requestingLogin = page.startLogin();
await tick();
dialog.close();
await dialog.handlers.close();
assert.equal(dialog.open, true);
startingGate.resolve({status: "pending", session_id: "last-session", interval: 5, user_code: "last-code", verify_url: "https://example.com"});
await tick();
pollResult({status: "pending"});
await requestingLogin;
startResponse = null;

// If cancelling a natively closed dialog fails, keep the session visible.
cancelResponse = Promise.reject(new Error("Cancellation unavailable"));
dialog.close();
await dialog.handlers.close();
assert.equal(dialog.open, true);
assert.match(read("error"), /Cancellation unavailable/);
// A queued close event from an earlier dismissal cannot cancel a reopened dialog.
cancelResponse = {status: "cancelled"};
await dialog.handlers.close();
assert.equal(shown("cancel"), true);
// Once cancellation is confirmed, native dismissal stays closed.
dialog.close();
await dialog.handlers.close();
assert.equal(dialog.open, false);
assert.equal(shown("cancel"), false);
cancelResponse = null;

// ---------- Settings dialog drafts ----------
Object.assign(device, {name: "Work", routing_mode: "fixed", enabled: true, status: "ready"});
Object.assign(account, {routing_mode: "fixed", enabled: true, status: "ready"});
updateHandler = null;
usage = {status: "success", account, usage: {windows: [{label_seconds: 604800, used_percent: 10}]}};
await page.queryUsage();
const settingsError = ids.get("settings-error");
const pressed = (mode) => ids.get(`settings-routing-${mode}`).attributes["aria-pressed"];

// Cancel, the close button and Escape all discard the draft without a request.
for (const dismiss of [
  () => click(ids.get("settings-cancel")),
  () => click(ids.get("close-settings")),
  async () => { escape(); await tick(); },
]) {
  const sent = providerUpdates.length;
  await openSettings("Work");
  typeName("Draft only");
  await click(ids.get("settings-routing-auto"));
  assert.equal(saveButton.disabled, false);
  await dismiss();
  assert.equal(settingsBox.open, false);
  assert.equal(providerUpdates.length, sent, "dismissing never saves");
  await openSettings("Work");
  assert.equal(nameInput.value, "Work", "a reopened dialog starts from the saved state");
  assert.equal(pressed("fixed"), "true");
  assert.equal(saveButton.disabled, true);
  await click(ids.get("settings-cancel"));
}
assert.doesNotMatch(read("providers"), /Draft only/);

// A queued native close event belongs to the dismissed dialog, not a
// settings session reopened before the browser dispatches that event.
await openSettings("Work");
await click(ids.get("settings-cancel"));
await openSettings("本地 Codex");
typeName("New session draft");
await settingsBox.handlers.close();
assert.equal(settingsBox.open, true, "an old close event must not dismiss a reopened settings dialog");
assert.equal(nameInput.value, "New session draft");
assert.equal(read("settings-title"), "本地 Codex");
await click(ids.get("settings-cancel"));

// Blank names cannot be saved, even with another change pending.
await openSettings("Work");
await click(ids.get("settings-routing-auto"));
typeName("   ");
assert.equal(saveButton.disabled, true);
assert.equal(nameInput.attributes["aria-invalid"], "true");
assert.equal(ids.get("settings-name-hint").hidden, false);
assert.match(read("settings-name-hint"), /请输入名称/);
const sentBeforeBlank = providerUpdates.length;
nameInput.handlers.keydown({key: "Enter", isComposing: false, keyCode: 13});
await click(saveButton);
assert.equal(providerUpdates.length, sentBeforeBlank);

// Name and routing changed together go out as one request for the bound ID.
typeName("  Both  ");
assert.equal(ids.get("settings-name-hint").hidden, true);
assert.equal(nameInput.attributes["aria-invalid"], "false");
await click(saveButton);
assert.equal(providerUpdates.length, sentBeforeBlank + 1);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", name: "Both", routing_mode: "auto"});
assert.equal(settingsBox.open, false);
assert.match(visibleText(rowFor("Both")), /自动回退/);

// While saving, the dialog is busy: no duplicate submit, no dismissal.
let heldSave = deferred();
updateHandler = () => heldSave.promise;
await openSettings("Both");
typeName("Held");
await click(saveButton);
const sentWhileHeld = providerUpdates.length;
assert.equal(saveButton.disabled, true);
assert.equal(saveButton.attributes["aria-busy"], "true");
assert.match(read("settings-save"), /正在保存/);
assert.equal(nameInput.disabled, true);
assert.equal(ids.get("settings-routing-fixed").disabled, true);
assert.equal(ids.get("settings-cancel").disabled, true);
assert.equal(ids.get("close-settings").disabled, true);
await click(saveButton);
nameInput.handlers.keydown({key: "Enter", isComposing: false, keyCode: 13});
await click(ids.get("settings-cancel"));
escape();
await tick();
assert.equal(settingsBox.open, true, "a save in flight keeps the dialog open");
assert.equal(providerUpdates.length, sentWhileHeld);
// The list shows the requested name while the write is in flight.
assert.match(read("providers"), /Held/);
device.name = "Held";
heldSave.resolve({status: "success", provider: {...device}});
await tick();
assert.equal(settingsBox.open, false);
assert.match(read("providers"), /Held/);
updateHandler = null;

// A rejected save keeps the draft and the dialog, reloads, and can be retried.
listsBefore = listCalls;
updateHandler = () => { throw new Error("Provider name must contain 1–80 characters."); };
await openSettings("Held");
typeName("Rejected");
await click(ids.get("settings-routing-fixed"));
await click(saveButton);
await tick();
assert.equal(settingsBox.open, true);
assert.equal(listCalls, listsBefore + 1);
assert.match(read("settings-error"), /保存「Held」失败.*1–80/);
assert.equal(settingsError.hidden, false);
assert.equal(nameInput.value, "Rejected", "the draft survives a failed save");
assert.equal(pressed("fixed"), "true");
assert.equal(saveButton.disabled, false, "a failed save can be retried");
assert.match(read("providers"), /Held/);
assert.doesNotMatch(read("providers"), /Rejected/);
updateHandler = null;
await click(saveButton);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", name: "Rejected", routing_mode: "fixed"});
assert.equal(settingsBox.open, false);
assert.match(read("providers"), /Rejected/);

// Background refreshes update the header but never the draft. Only fields
// the user touched are sent, so a concurrent server change elsewhere stays.
await openSettings("Rejected");
typeName("Mine");
Object.assign(device, {name: "Remote", routing_mode: "auto"});
await page.queryUsage();
assert.equal(read("settings-title"), "Remote");
assert.equal(nameInput.value, "Mine");
assert.equal(pressed("fixed"), "true");
assert.equal(saveButton.disabled, false);
await click(saveButton);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "device", name: "Mine"});
assert.match(visibleText(rowFor("Mine")), /自动回退/);

// The gear, the row and the switch never trigger each other.
const sentBeforeEntries = providerUpdates.length;
const wasExpanded = mainFor("本地 Codex").attributes["aria-expanded"];
await click(switchFor("本地 Codex"));
assert.equal(settingsBox.open, false, "the switch never opens settings");
assert.equal(mainFor("本地 Codex").attributes["aria-expanded"], wasExpanded, "the switch never expands the row");
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "local", enabled: false});
await click(mainFor("Mine"));
await tick();
assert.equal(settingsBox.open, false, "the row never opens settings");
assert.equal(providerUpdates.length, sentBeforeEntries + 1, "expanding never saves");
const deviceExpanded = mainFor("Mine").attributes["aria-expanded"];
await click(mainFor("Mine"));
assert.notEqual(mainFor("Mine").attributes["aria-expanded"], deviceExpanded, "the row still folds and unfolds");
await openSettings("Mine");
assert.equal(mainFor("Mine").attributes["aria-expanded"], deviceExpanded === "true" ? "false" : "true");
await click(ids.get("settings-cancel"));
await click(switchFor("本地 Codex"));

// A provider that disappears while edited ends the session without a write.
let hideDevice = true;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/list" && hideDevice) {
    listCalls += 1;
    return {providers: [{...account}]};
  }
  return originalPost(endpoint, body);
};
const sentBeforeGone = providerUpdates.length;
await openSettings("Mine");
typeName("Orphan");
await page.queryUsage();
assert.equal(settingsBox.open, false);
assert.match(read("page-error"), /该 Provider 已不存在/);
assert.equal(document.activeElement, ids.get("add-provider"));
assert.equal(providerUpdates.length, sentBeforeGone);
hideDevice = false;
await page.queryUsage();

// A late reply for an ended session cannot touch the next provider's dialog.
heldSave = deferred();
updateHandler = (body) => body.source_id === "device" ? heldSave.promise : {status: "success", provider: {...account}};
await openSettings("Mine");
typeName("Late");
await click(saveButton);
hideDevice = true;
await page.queryUsage();
assert.equal(settingsBox.open, false, "a vanished provider ends even a busy session");
hideDevice = false;
await openSettings("本地 Codex");
typeName("Local draft");
device.name = "Late";
heldSave.resolve({status: "success", provider: {...device}});
await tick();
await tick();
assert.equal(settingsBox.open, true, "the late reply must not close another provider's dialog");
assert.equal(read("settings-title"), "本地 Codex");
assert.equal(nameInput.value, "Local draft");
assert.equal(settingsError.hidden, true);
assert.ok(providerUpdates.filter((b) => b.name === "Late").every((b) => b.source_id === "device"));
assert.ok(!providerUpdates.some((b) => b.source_id === "local" && "name" in b), "nothing was written to the other provider");
await click(ids.get("settings-cancel"));
bridge.apiPost = originalPost;
updateHandler = null;
await page.queryUsage();

// ---------- Account actions in the settings dialog ----------
// Local Codex follows the host login: no renew, no removal.
device.name = "Mine";
await page.queryUsage();
await openSettings("本地 Codex");
assert.equal(ids.get("settings-account").hidden, true);
await click(ids.get("settings-cancel"));
await openSettings("Mine");
assert.equal(ids.get("settings-account").hidden, false);
assert.match(read("settings-reauth"), /重新授权/);
assert.match(read("settings-remove"), /^移除$/);
await click(ids.get("settings-cancel"));

// Renewing from settings saves nothing, targets the dialog's provider, keeps
// a disabled provider disabled and brings the draft back afterwards.
device.enabled = false;
await page.queryUsage();
await inspectProvider("local");
assert.equal(checked("Mine"), "false");
const sentBeforeRenew = providerUpdates.length;
await openSettings("Mine");
typeName("Unsaved draft");
await click(ids.get("settings-routing-auto"));
await click(ids.get("settings-reauth"));
assert.equal(settingsBox.open, false, "only one modal is open at a time");
assert.equal(ids.get("login-dialog").open, true);
assert.equal(read("instructions-title"), "重新授权");
const renewal = page.startLogin();
await tick();
assert.deepEqual({...deviceBody}, {source_id: "device"}, "the renewal targets the dialog's provider, not the selected row");
pollResult({status: "success", source_id: "device"});
await renewal;
await tick();
await page.closeLogin();
assert.equal(ids.get("login-dialog").open, false);
assert.equal(settingsBox.open, true, "settings return after the login dialog closes");
assert.equal(read("settings-title"), "Mine");
assert.equal(nameInput.value, "Unsaved draft");
assert.equal(pressed("auto"), "true");
assert.equal(saveButton.disabled, false);
assert.equal(document.activeElement, ids.get("settings-reauth"));
assert.equal(providerUpdates.length, sentBeforeRenew, "renewing never saves the draft");
assert.equal(checked("Mine"), "false", "renewing never enables a disabled provider");
// Leaving the login dialog without starting also returns to settings,
// including when the browser closes it without a cancel event.
await click(ids.get("settings-reauth"));
await page.closeLogin();
assert.equal(settingsBox.open, true);
assert.equal(nameInput.value, "Unsaved draft");
await click(ids.get("settings-reauth"));
const loginBox = ids.get("login-dialog");
loginBox.open = false;
await loginBox.handlers.close();
assert.equal(settingsBox.open, true);
assert.equal(nameInput.value, "Unsaved draft");
await click(ids.get("settings-cancel"));
assert.equal(providerUpdates.length, sentBeforeRenew);

// Removal needs a second click; Keep and Escape back out without losing the draft.
const deletes = [];
let deleteHandler = () => ({status: "success"});
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/delete") { deletes.push(body); return deleteHandler(body); }
  return originalPost(endpoint, body);
};
await openSettings("Mine");
typeName("Kept draft");
await click(removeButton);
assert.equal(deletes.length, 0);
assert.match(read("settings-remove"), /确认移除/);
assert.match(read("settings-remove-hint"), /再次点击即永久删除/);
assert.equal(ids.get("settings-remove-keep").hidden, false);
await click(ids.get("settings-remove-keep"));
assert.match(read("settings-remove"), /^移除$/);
assert.equal(ids.get("settings-remove-keep").hidden, true);
assert.equal(nameInput.value, "Kept draft");
await click(removeButton);
escape();
await tick();
assert.equal(settingsBox.open, true, "Escape first backs out of an armed removal");
assert.match(read("settings-remove"), /^移除$/);
assert.equal(nameInput.value, "Kept draft");
assert.equal(deletes.length, 0);

// A failed removal keeps the dialog, the provider and the draft.
deleteHandler = () => { throw new Error("Remove this provider's model bindings in AstrBot first."); };
await click(removeButton);
await click(removeButton);
await tick();
assert.equal(deletes.length, 1);
assert.equal(settingsBox.open, true);
assert.match(read("settings-error"), /移除「Mine」失败.*model bindings/);
assert.equal(nameInput.value, "Kept draft");
assert.ok(rowFor("Mine"));

// A busy removal blocks the other dialog actions.
let heldDelete = deferred();
deleteHandler = () => heldDelete.promise;
await click(removeButton);
await click(removeButton);
assert.match(read("settings-remove"), /正在移除/);
assert.equal(saveButton.disabled, true);
assert.equal(ids.get("settings-reauth").disabled, true);
assert.equal(ids.get("settings-cancel").disabled, true);
escape();
await tick();
assert.equal(settingsBox.open, true);
// Success closes the dialog, removes the row and never saves the draft.
let deviceRemoved = false;
const removalPost = bridge.apiPost;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/list" && deviceRemoved) {
    listCalls += 1;
    return {providers: [{...account}]};
  }
  return removalPost(endpoint, body);
};
deviceRemoved = true;
const sentBeforeRemove = providerUpdates.length;
heldDelete.resolve({status: "success"});
await tick();
await tick();
assert.deepEqual({...deletes.at(-1)}, {source_id: "device"});
assert.equal(settingsBox.open, false);
assert.equal(rowFor("Mine"), undefined);
assert.equal(document.activeElement, ids.get("add-provider"));
assert.doesNotMatch(visibleText(ids.get("page-error")), /已不存在/, "a removal from settings is not reported as a vanished provider");
assert.equal(providerUpdates.length, sentBeforeRemove);
bridge.apiPost = originalPost;

// The default local name has one localized presentation in every surface.
const savedLocalName = account.name;
const savedLocalRouting = account.routing_mode;
account.name = "Local Codex";
account.routing_mode = "fixed";
await page.queryUsage();
await openSettings("本地 Codex");
assert.equal(nameInput.value, "本地 Codex");
assert.equal(read("settings-title"), nameInput.value);
assert.equal(saveButton.disabled, true);
contextHandler({locale: "en-US"});
assert.equal(nameInput.value, "Local Codex");
assert.equal(read("settings-title"), nameInput.value);
assert.equal(saveButton.disabled, true, "changing locale is not a rename");
contextHandler({locale: "zh-CN"});
assert.equal(nameInput.value, "本地 Codex");
const beforeLocalRouting = providerUpdates.length;
await click(ids.get("settings-routing-auto"));
await click(saveButton);
assert.equal(providerUpdates.length, beforeLocalRouting + 1);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "local", routing_mode: "auto"});
assert.equal(account.name, "Local Codex", "routing edits preserve the canonical default");

await openSettings("本地 Codex");
typeName("我的工作账号");
contextHandler({locale: "en-US"});
assert.equal(nameInput.value, "我的工作账号", "locale changes preserve an edited draft");
assert.equal(saveButton.disabled, false);
await click(saveButton);
assert.deepEqual({...providerUpdates.at(-1)}, {source_id: "local", name: "我的工作账号"});
await openSettings("我的工作账号");
contextHandler({locale: "zh-CN"});
assert.equal(read("settings-title"), "我的工作账号");
assert.equal(nameInput.value, "我的工作账号");
assert.equal(saveButton.disabled, true);
await click(ids.get("settings-cancel"));

// An unclear rename that landed must adopt the custom baseline, so subsequent
// renders cannot translate it back or resend it with an unrelated setting.
account.name = "Local Codex";
await page.queryUsage();
await openSettings("本地 Codex");
typeName("已保存的新名称");
updateHandler = (body) => { account.name = body.name; return {status: "success"}; };
await click(saveButton);
await tick();
assert.equal(settingsBox.open, true);
assert.equal(nameInput.value, "已保存的新名称");
assert.equal(saveButton.disabled, true);
contextHandler({locale: "en-US"});
assert.equal(nameInput.value, "已保存的新名称");
assert.equal(saveButton.disabled, true);
await click(ids.get("settings-cancel"));
updateHandler = null;

// A custom OpenAI provider called Local Codex is not the built-in default.
const savedDeviceName = device.name;
device.name = "Local Codex";
await page.queryUsage();
contextHandler({locale: "zh-CN"});
await openSettings("Local Codex");
assert.equal(nameInput.value, "Local Codex");
assert.equal(read("settings-title"), "Local Codex");
await click(ids.get("settings-cancel"));
account.name = savedLocalName;
account.routing_mode = savedLocalRouting;
device.name = savedDeviceName;
await page.queryUsage();
console.log("Localized default name regressions passed: matching title/input, locale changes, routing-only saves, custom drafts/names and unclear-save reconciliation.");

console.log("View regressions passed: device login dialog (copy instructions, copy, saving, success, done, failure recovery), quota windows, provider selection, stale-result isolation, login and cancellation races, settings dialog drafts and entry points, renew and removal from settings, IME-safe rename, enable switch, routing mode, serialized saves, stale-list protection, failed and unclear saves, reconciliation after navigation/deletion, account identity changes, confirmed routing notices.");

// Independent panels: exercise the public row buttons and refresh behavior in
// a fresh page instance, including more providers than the request limit.
let fixtures = Array.from({length: 6}, (_, index) => ({
  id: `p${index}`, name: `Provider ${index}`, status: "ready",
  credential_mode: index ? "device_oauth" : "local_codex",
  account_revision: `revision-${index}`,
}));
const quotaCalls = [];
let quotaGate = null;
let liveRequests = 0;
let peakRequests = 0;
let failingProvider = null;
bridge.apiPost = async (endpoint, body) => {
  if (endpoint === "providers/list") return {providers: fixtures.map((p) => ({...p}))};
  assert.equal(endpoint, "account/usage");
  quotaCalls.push(body.source_id);
  const snapshot = {...fixtures.find((p) => p.id === body.source_id)};
  const gate = quotaGate;
  ++liveRequests;
  peakRequests = Math.max(peakRequests, liveRequests);
  try {
    if (gate) await gate.promise;
    if (body.source_id === failingProvider) throw new Error("Offline");
    return {status: "success", account: snapshot, usage: {
      plan_type: "pro", windows: [{label_seconds: 604800, used_percent: Number(body.source_id.slice(1)) * 10}],
    }};
  } finally { --liveRequests; }
};
const freshPage = () => vm.runInNewContext(
  `(async () => {${source}\n await queryUsage(); return {queryUsage, selectProvider, loadProviders, rowNodes, strings, resolveLanguage, formatAbsolute, formatRelative, windowLabel, openSettings, openLogin, failLogin};})()`,
  {window, document, navigator, console, URL},
);
const multi = await freshPage();
const panelFor = (id) => multi.rowNodes.get(id).panel;
const rowMain = (id) => multi.rowNodes.get(id).main;
const panelText = (id) => panelFor(id).usageResult.textContent;
assert.deepEqual(quotaCalls, ["p0"], "only the first provider fetches on page load");
assert.equal(rowMain("p0").getAttribute("aria-expanded"), "true");
assert.equal(rowMain("p1").getAttribute("aria-expanded"), "false");
assert.equal(panelFor("p1").detail.hidden, true);
const controlIds = [...multi.rowNodes.values()].map(({main}) => main.getAttribute("aria-controls"));
assert.equal(new Set(controlIds).size, 6, "each row controls a distinct panel");
for (const {main, panel} of multi.rowNodes.values()) {
  assert.equal(main.getAttribute("aria-controls"), panel.detail.id);
  assert.equal(panel.detail.getAttribute("aria-labelledby"), panel.elements["source-name"].id);
}
await click(rowMain("p1"));
assert.equal(panelFor("p0").detail.hidden, false);
assert.equal(panelFor("p1").detail.hidden, false);
assert.match(panelText("p0"), /100%/);
assert.match(panelText("p1"), /90%/);
await click(rowMain("p0"));
quotaCalls.length = 0;
await multi.queryUsage();
assert.deepEqual(quotaCalls, ["p1"], "refresh skips collapsed providers");
assert.equal(panelFor("p0").detail.hidden, true, "refresh never reopens the default row");
contextHandler({locale: "en-US"});
assert.equal(panelFor("p0").detail.hidden, true);
assert.match(panelText("p1"), /Weekly.*90%/);
contextHandler({locale: "zh-CN"});
fixtures[1].name = "Renamed";
await multi.queryUsage();
assert.equal(panelFor("p1").detail.hidden, false, "renaming preserves expansion by ID");
assert.equal(panelFor("p0").detail.hidden, true);

await click(rowMain("p0"));
failingProvider = "p1";
await multi.queryUsage();
assert.match(panelText("p0"), /100%/);
assert.match(panelText("p1"), /暂时无法获取/);
assert.equal(ids.get("page-error").hidden, true, "a quota failure is scoped to its own panel");
failingProvider = null;

// A pending request from a collapsed row cannot overwrite its fresh result.
quotaGate = deferred();
const oldRefresh = multi.queryUsage();
await tick();
await click(rowMain("p1"));
const oldGate = quotaGate;
quotaGate = null;
fixtures[1].account_revision = "replacement";
await click(rowMain("p1"));
assert.match(panelText("p1"), /90%/);
assert.equal(panelFor("p1").account.account_revision, "replacement");
oldGate.resolve();
await oldRefresh;
assert.equal(panelFor("p1").account.account_revision, "replacement");
assert.equal(panelFor("p0").detail.hidden, false);

// Opening many rows shares the same bounded request queue. Collapsing a
// queued row cancels its lookup without consuming another API request.
quotaGate = deferred();
peakRequests = 0;
quotaCalls.length = 0;
const refreshMany = multi.queryUsage();
await tick();
const openings = ["p2", "p3", "p4", "p5"].map((id) => multi.selectProvider(id));
await tick();
assert.equal(liveRequests, 3);
assert.equal(quotaCalls.length, 3);
await multi.selectProvider("p4");
const manyGate = quotaGate;
quotaGate = null;
manyGate.resolve();
await Promise.all([refreshMany, ...openings]);
assert.equal(peakRequests, 3, "overlapping refreshes and row clicks stay bounded");
assert.ok(!quotaCalls.includes("p4"), "a collapsed queued panel does not fetch");
assert.equal(panelFor("p4").detail.hidden, true);
assert.match(panelText("p5"), /50%/);

// Removing a provider discards its in-flight response and keeps other panels.
quotaGate = deferred();
const beforeRemoval = multi.queryUsage();
await tick();
fixtures = fixtures.filter((p) => p.id !== "p1");
const removalGate = quotaGate;
quotaGate = null;
await multi.loadProviders();
assert.equal(multi.rowNodes.has("p1"), false);
removalGate.resolve();
await beforeRemoval;
assert.equal(multi.rowNodes.has("p1"), false, "a late result cannot resurrect a removed provider");
assert.equal(panelFor("p0").detail.hidden, false);
assert.equal(panelFor("p5").detail.hidden, false);

// A full page reload restores the default, regardless of the previous panels.
quotaCalls.length = 0;
const reloaded = await freshPage();
assert.deepEqual(quotaCalls, ["p0"]);
assert.equal(reloaded.rowNodes.get("p0").panel.detail.hidden, false);
assert.equal(reloaded.rowNodes.get("p5").panel.detail.hidden, true);
console.log("Independent provider panel regressions passed: defaults, concurrent expansion, collapsed refresh, locale/rename preservation, isolated errors, stale responses, bounded queue, removal and page reload.");

// All AstrBot locales must be complete, selectable at startup, and live-switchable.
const shape = (object) => Object.fromEntries(Object.entries(object).sort().map(([key, value]) =>
  [key, typeof value === "object" ? shape(value) : typeof value],
));
for (const dictionary of Object.values(reloaded.strings)) {
  assert.deepEqual(shape(dictionary), shape(reloaded.strings.en));
  const checkText = (object) => {
    for (const value of Object.values(object)) {
      if (typeof value === "object") checkText(value);
      else if (typeof value === "string") assert.ok(value.trim());
      else assert.equal(typeof value("Example", "h"), "string");
    }
  };
  checkText(dictionary);
}
fixtures[0].name = "Local Codex";
const cases = [
  ["zh-CN", "zh", "本地 Codex"],
  ["en-US", "en", "Local Codex"],
  ["ru-RU", "ru", "Локальный Codex"],
  ["ja-JP", "ja", "ローカル Codex"],
];
for (const [locale, key, localName] of cases) {
  initialLocale = locale;
  const translated = await freshPage();
  const dictionary = translated.strings[key];
  assert.equal(document.documentElement.lang, locale);
  assert.equal(document.title, dictionary.title);
  assert.equal(read("title"), dictionary.title);
  assert.equal(ids.get("providers").getAttribute("aria-label"), dictionary.title);
  assert.equal(translated.rowNodes.get("p0").name.textContent, localName);
  assert.equal(translated.rowNodes.get("p1")?.name.textContent, fixtures.find((p) => p.id === "p1")?.name);
  assert.equal(ids.get("usage").getAttribute("aria-label"), dictionary.refresh);
  assert.ok(translated.rowNodes.get("p0").panel.usageResult.textContent.includes(dictionary.shortWindows[604800]));
  assert.ok(read("updated").startsWith(dictionary.updated));
  const date = new Date(2030, 9, 22, 14, 13);
  assert.equal(translated.formatAbsolute(date.getTime() / 1000),
    date.toLocaleDateString(locale, {month: "short", day: "numeric"}) + " " +
    date.toLocaleTimeString(locale, {hour: "2-digit", minute: "2-digit", hour12: false}));
  assert.equal(translated.formatRelative(Date.now() / 1000 + 7200), dictionary.resetIn(2, "h"));
  assert.equal(translated.windowLabel(9000), dictionary.windowHours(new Intl.NumberFormat(locale).format(2.5)));
  translated.openSettings("p0");
  assert.equal(nameInput.value, localName);
  assert.equal(read("settings-title"), localName);
  assert.equal(read("settings-kicker"), dictionary.settingsTitle);
  assert.equal(saveButton.disabled, true);
  for (const [otherLocale, otherKey, otherName] of cases) {
    contextHandler({locale: otherLocale});
    assert.equal(nameInput.value, otherName);
    assert.equal(read("settings-title"), otherName);
    assert.equal(saveButton.disabled, true);
    assert.equal(document.documentElement.lang, otherLocale);
    assert.equal(translated.rowNodes.get("p0").main.getAttribute("aria-expanded"), "true");
    assert.equal(read("settings-routing-help"), translated.strings[otherKey].routingFixedHelp);
  }
  typeName("My Custom 名称");
  contextHandler({locale});
  assert.equal(nameInput.value, "My Custom 名称");
  await click(ids.get("settings-cancel"));
  translated.openLogin();
  assert.equal(read("instructions-title"), dictionary.add);
  assert.equal(read("login-intro"), dictionary.intro);
  assert.equal(read("start"), dictionary.start);
  assert.equal(read("copy-code"), dictionary.copyCode);
  translated.failLogin(null, false);
  assert.equal(read("error"), dictionary.failedLogin);
  contextHandler({locale: "ru-RU"});
  assert.equal(read("error"), translated.strings.ru.failedLogin, "an existing fallback error follows locale changes");
  contextHandler({locale: "ja-JP"});
  assert.equal(read("error"), translated.strings.ja.failedLogin);
  await click(ids.get("close-login"));
  const native = JSON.parse(readFileSync(new URL(`../.astrbot-plugin/i18n/${locale}.json`, import.meta.url), "utf8"));
  assert.equal(native.pages.providers.title, dictionary.title);
  assert.ok(native.metadata.display_name && native.metadata.desc && native.metadata.short_desc);
  assert.ok(native.config.codex_auth_path.description);
  assert.ok(native.config.codex_auth_path.hint.includes("$CODEX_HOME/auth.json"));
}
assert.equal(reloaded.resolveLanguage("RU_ru"), "ru");
assert.equal(reloaded.resolveLanguage("ja"), "ja");
assert.equal(reloaded.resolveLanguage("en-GB"), "en");
assert.equal(reloaded.resolveLanguage("fr-FR"), "en");
assert.equal(reloaded.resolveLanguage("__proto__"), "en");
console.log("Four-language regressions passed: complete dictionaries, startup/context locales, dates/windows, default/custom names, dialogs/errors, ARIA labels and AstrBot plugin metadata.");
