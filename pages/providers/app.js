import { strings } from "./strings.js";

const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();
const byId = (id) => document.getElementById(id);
const startButton = byId("start");
const cancelButton = byId("cancel");
const usageButton = byId("usage");
const loginIntro = byId("login-intro");
const loginNameInput = byId("login-name");
const devicePanel = byId("device-panel");
const loginState = byId("login-state");
const stateIcon = byId("state-icon");
const statusDetail = byId("status-detail");
const savedProvider = byId("saved-provider");
const doneButton = byId("done");
const verifyUrl = byId("verify-url");
const userCode = byId("user-code");
const copyUrlButton = byId("copy-url");
const copyCodeButton = byId("copy-code");
const copyStatus = byId("copy-status");
const status = byId("status");
const statusDots = byId("status-dots");
const error = byId("error");
const loginDialog = byId("login-dialog");
const closeButton = byId("close-login");
const providerList = byId("providers");
const saveError = byId("save-error");
const settingsDialog = byId("settings-dialog");
const settingsNameInput = byId("settings-name");
const settingsSave = byId("settings-save");
const settingsCancel = byId("settings-cancel");
const closeSettingsButton = byId("close-settings");
const settingsRouting = {
  fixed: byId("settings-routing-fixed"),
  auto: byId("settings-routing-auto"),
};
const plans = {
  free: "Free",
  go: "Go",
  plus: "Plus",
  pro: "Pro",
  team: "Team",
  business: "Business",
  enterprise: "Enterprise",
  edu: "Edu",
};
const codexIcon =
  '<img class="codex-icon-light" src="./icons/codex-color.svg" alt="" width="34" height="34">' +
  '<img class="codex-icon-dark" src="./icons/codex-color-dark.svg" alt="" width="34" height="34">';
const providerIcons = {
  local_codex: codexIcon,
  device_oauth: '<span class="openai-icon"></span>',
};
const chevronIcon = '<svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>';
const stateIcons = {
  ok: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8.2 12.4l2.6 2.6 5-5.2"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.6v5.2M12 16.4h.01"/></svg>',
};
const gearIcon =
  '<svg viewBox="0 0 24 24"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>';
// Rows persist across refreshes and are updated in place, so focus inside a
// row and the expanded allowance panel survive the 30-second refresh.
const rowNodes = new Map();
const maxConsecutivePollFailures = 5;
const warningStates = ["cooling", "degraded"];
const dangerStates = ["reauth_required", "invalid"];
const signedOutStates = ["not_logged_in", "invalid"];

const locales = { zh: "zh-CN", en: "en-US", ru: "ru-RU", ja: "ja-JP" };
let language = "zh";
let dateLocale = locales.zh;

function resolveLanguage(locale) {
  const key = String(locale || "zh-CN").toLowerCase().split(/[-_]/)[0];
  return Object.hasOwn(locales, key) ? key : "en";
}
let t = strings.zh;
let pollTimer = null;
let activeSessionId = null;
let consecutivePollFailures = 0;
let providers = [];
let loginSourceId = null;
let refreshPromise = null;
let initializedExpansion = false;
let panelSequence = 0;
let activeUsageRequests = 0;
const usageQueue = [];
let cancelling = false;
let lastUpdated = null;
let pageErrorMessage = "";
let saveErrorMessage = "";

// Keep UI-generated messages translatable while preserving server details.
// The server reports its own errors as stable codes, translated here.
function messageText(message) {
  if (typeof message === "function") return message();
  return (typeof message === "string" && Object.hasOwn(t.errors, message) && t.errors[message]) || message;
}

function showPageError(message) {
  pageErrorMessage = message;
  byId("page-error").textContent = messageText(message);
  byId("page-error").hidden = !message;
}
// Login dialog view. `activeSessionId` stays the only signal that a server
// session may still finish; `phase` decides what the dialog shows.
const login = {
  // idle | requesting | waiting | saving | success | timeout | expired | cancelled | failed
  phase: "idle",
  url: "",
  code: "",
  error: "",
  note: "",
  retrying: false,
  // The server reported that authorization finished and is being saved.
  saving: false,
  savedId: null,
  // Provider-list request sequence when the login succeeded. The saved
  // provider is shown only from a list requested after that point.
  listAfter: 0,
};
const formPhases = ["idle", "requesting", "timeout", "expired", "cancelled", "failed"];
const copyTimers = new Map();
let listRequestSeq = 0;
let listedSeq = 0;
// Provider writes. Each source has one promise chain so its updates reach the
// server in order. `pendingChanges` holds the values the user asked for while
// they are queued or in flight; `providers` only holds server-confirmed state.
const saveChains = new Map();
const pendingChanges = new Map();
// A list or usage response issued before a write settled may describe the
// previous state. Every write start and finish bumps the sequence so such a
// response keeps the locally confirmed editable fields instead.
const lastMutation = new Map();
let mutationSeq = 0;
const editableFields = ["name", "enabled", "routing_mode"];
// The open settings dialog. A session is bound to one source ID for its whole
// lifetime and is replaced, never mutated, when the dialog opens again, so a
// late reply can compare identity before touching the dialog. `base` holds
// the values the draft started from: only fields the user changed are sent,
// and refreshes never rewrite what they typed.
let settings = null;

function applyLocale(locale) {
  language = resolveLanguage(locale);
  dateLocale = locales[language];
  t = strings[language];
  document.documentElement.lang = dateLocale;
  document.title = t.title;
  for (const [id, value] of Object.entries({
    title: t.title,
    "add-provider-label": t.add,
    "settings-kicker": t.settingsTitle,
    "settings-name-label": t.nameShort,
    "settings-routing-label": t.routingLabel,
    "settings-routing-fixed": t.routingFixed,
    "settings-routing-auto": t.routingAuto,
    "settings-cancel": t.cancelEdit,
    "settings-save": t.saveName,
    "settings-account-label": t.accountLabel,
    "settings-reauth": t.renew,
    "settings-remove-title": t.removeTitle,
    "settings-remove-keep": t.keep,
    "login-name-label": t.name,
    "login-name-optional": t.optional,
    privacy: t.privacy,
    "code-label": t.codeLabel,
    "device-hint": t.deviceHint,
    "copy-url": t.copyUrl,
    "copy-code": t.copyCode,
  }))
    byId(id).textContent = value;
  closeButton.setAttribute("aria-label", t.close);
  verifyUrl.setAttribute("aria-label", t.verifyLink);
  closeSettingsButton.setAttribute("aria-label", t.close);
  closeSettingsButton.setAttribute("title", t.close);
  setRefreshing(usageButton.disabled);
  providerList.setAttribute("aria-label", t.title);
  usageButton.setAttribute("title", t.refresh);
  byId("updated").setAttribute("title", t.automatic);
}

applyLocale(context?.locale || bridge.getLocale());

function clearPollTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll(sessionId, intervalSeconds) {
  clearPollTimer();
  pollTimer = window.setTimeout(
    () => void poll(sessionId, intervalSeconds),
    intervalSeconds * 1000,
  );
}

function resetSeconds(timestamp, after) {
  if (typeof timestamp === "number" && Number.isFinite(timestamp) && timestamp > 0)
    return timestamp;
  if (typeof after === "number" && Number.isFinite(after) && after >= 0)
    return Date.now() / 1000 + after;
  return null;
}

function formatAbsolute(seconds) {
  if (seconds === null) return "";
  const date = new Date(seconds * 1000);
  if (!Number.isFinite(date.getTime())) return "";
  const locale = dateLocale;
  const time = date.toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  if (date.toDateString() === new Date().toDateString())
    return `${t.today} ${time}`;
  const day = date.toLocaleDateString(locale, { month: "short", day: "numeric" });
  return `${day} ${time}`;
}

function formatRelative(seconds) {
  if (seconds === null) return "";
  const diff = seconds - Date.now() / 1000;
  if (!Number.isFinite(diff)) return "";
  if (diff <= 60) return t.soon;
  if (diff < 3600) return t.resetIn(Math.ceil(diff / 60), "m");
  if (diff < 36 * 3600) return t.resetIn(Math.round(diff / 3600), "h");
  return t.resetIn(Math.round(diff / 86400), "d");
}

function element(tag, className, value) {
  const node = document.createElement(tag);
  node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function statusClass(state) {
  return warningStates.includes(state)
    ? " warning"
    : dangerStates.includes(state)
      ? " danger"
      : state === "ready"
        ? ""
        : " neutral";
}

function renderAccountStatus(panel, result) {
  const previous = panel.account;
  panel.account = result || {};
  const identityChanged =
    (previous.id === panel.account.id &&
      (previous.account_revision ?? null) !== (panel.account.account_revision ?? null)) ||
    (panel.lastUsage && panel.shownRevision !== (panel.account.account_revision ?? null));
  if (identityChanged) {
    clearUsage(panel, "changed");
    invalidatePanel(panel);
  }
  const state = String(panel.account.status || "unknown");
  panel.accountStatus.textContent = t.states[state] || t.states.unknown;
  panel.accountStatus.setAttribute("title", t.details[state] || t.details.unknown);
  panel.accountStatus.className = "badge" + statusClass(state);

  panel.elements["source-name"].textContent = providerName(panel.account);
  updateNotice(panel);
  return Boolean(identityChanged);
}

function isSaving(id) {
  return Boolean(pendingChanges.get(id)?.length);
}

function effective(provider) {
  const changes = pendingChanges.get(provider?.id);
  return changes?.length ? Object.assign({}, provider, ...changes) : provider;
}

// Sources saved before the switch existed migrate to enabled on the server.
function isEnabled(provider) {
  return provider?.enabled !== false;
}

function routingMode(provider) {
  return provider?.routing_mode === "auto" ? "auto" : "fixed";
}

function windowLabel(seconds, short = false) {
  if (short && t.shortWindows[seconds]) return t.shortWindows[seconds];
  if (seconds === 18000) return t.fiveHour;
  if (seconds === 604800) return t.week;
  if (seconds === 2592000) return t.month;
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0
    ? t.windowHours(new Intl.NumberFormat(dateLocale, { maximumFractionDigits: 2 }).format(seconds / 3600))
    : t.window;
}

function showUsageMessage(panel, key) {
  panel.usageMessage = key;
  const busy = key === "loading" || key === "changed";
  const message = element("p", "muted");
  if (busy) {
    const dots = element("span", "quiet-dots");
    dots.setAttribute("aria-hidden", "true");
    dots.append(element("i", ""), element("i", ""), element("i", ""));
    message.append(element("span", "", t[key]), dots);
  } else {
    message.textContent = t[key];
  }
  panel.usageResult.replaceChildren(message);
  panel.elements["plan"].hidden = true;
  panel.quotaPolicy.hidden = true;
}

function clearUsage(panel, key) {
  panel.lastUsage = null;
  panel.shownRevision = null;
  showUsageMessage(panel, key);
  updateNotice(panel);
}

function remainingOf(item) {
  return typeof item.used_percent === "number" &&
    Number.isFinite(item.used_percent)
    ? Math.max(0, Math.min(100, 100 - item.used_percent))
    : null;
}

// One compact line per returned window: a short name, a fixed-width bar,
// the remaining share and when it resets. The bar never stretches with the
// panel, so a single weekly window reads as one line rather than a banner.
function quotaRow(item) {
  const remaining = remainingOf(item);
  const label = windowLabel(item.label_seconds);
  const row = element(
    "div",
    "quota-row" +
      (remaining === null
        ? " unknown"
        : remaining === 0
          ? " exhausted"
          : remaining <= 15
            ? " low"
            : ""),
  );
  row.setAttribute("title", label);
  const track = element("span", "quota-bar");
  if (remaining !== null) {
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", `${label} ${t.remaining}`);
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(remaining));
    const fill = element("span", "quota-fill");
    fill.style.width = `${remaining}%`;
    track.append(fill);
  }
  const value = element(
    "strong",
    "quota-value",
    remaining === null ? "—" : `${Math.round(remaining)}%`,
  );
  value.append(
    element(
      "small",
      "",
      remaining === null ? t.unknown : remaining === 0 ? t.usedUp : t.remaining,
    ),
  );
  const reset = resetSeconds(item.reset_at, item.reset_after_seconds);
  const when = [formatRelative(reset), formatAbsolute(reset)].filter(Boolean);
  row.append(
    element("span", "quota-name", windowLabel(item.label_seconds, true)),
    track,
    value,
    element("span", "quota-reset", when.join(" · ")),
  );
  return row;
}

function usageWindows(usage) {
  return Array.isArray(usage?.windows)
    ? usage.windows.filter((item) => item && typeof item === "object")
    : [];
}

function renderUsage(panel, result) {
  if (result?.account) renderAccountStatus(panel, result.account);
  if (result?.status !== "success" || !result.usage) {
    clearUsage(panel, result?.status === "account_changed" ? "changed" : "failed");
    if (["cooling", "reauth_required", "invalid"].includes(result?.status)) {
      renderAccountStatus(panel, { ...panel.account, status: result.status });
    }
    return;
  }
  panel.lastUsage = result.usage;
  panel.shownRevision = panel.account.account_revision ?? null;
  const usage = result.usage;
  const windows = usageWindows(usage);
  if (!windows.length) {
    showUsageMessage(panel, "noWindows");
  } else {
    panel.usageResult.replaceChildren(...windows.map(quotaRow));
  }
  const plan = plans[usage.plan_type];
  panel.elements["plan"].textContent = plan || "";
  panel.elements["plan"].hidden = !plan;
  const weeklyOnly =
    windows.length === 1 && windows[0].label_seconds === 604800;
  // Pro accounts currently return only a weekly window; that single line
  // needs no caveat. Other plans keep the "missing is not unlimited" note.
  panel.quotaPolicy.hidden = !weeklyOnly || usage.plan_type === "pro";
  panel.quotaPolicy.textContent = panel.quotaPolicy.hidden ? "" : t.weeklyOnly;
  updateNotice(panel);
}

function updateNotice(panel) {
  const usage = panel.lastUsage;
  let message = "";
  if (usage?.limit_reached) {
    const resets = usageWindows(usage)
      .filter((item) => remainingOf(item) === 0)
      .map((item) => resetSeconds(item.reset_at, item.reset_after_seconds))
      .filter((value) => value !== null);
    // The server may enforce a later cooldown than the reported quota windows.
    const cooldown = resetSeconds(panel.account.cooldown_until);
    if (cooldown !== null) resets.push(cooldown);
    message = resets.length
      ? t.exhaustedUntil(formatAbsolute(Math.max(...resets)))
      : t.exhausted;
    message += (["en", "ru"].includes(language) ? " " : "") + (routingMode(effective(panel.account)) === "auto" ? t.willFallback : t.noSwitch);
  } else if (panel.account.status === "cooling") {
    const until = formatAbsolute(resetSeconds(panel.account.cooldown_until));
    message = until ? t.coolingUntil(until) : t.details.cooling;
  } else if (usage && usage.allowed === false) {
    message = t.denied;
  } else if (["degraded", "reauth_required"].includes(panel.account.status)) {
    message = t.details[panel.account.status];
  }
  panel.notice.hidden = !message;
  panel.elements["notice-text"].textContent = message;
}

function renderUpdated() {
  if (!lastUpdated) return;
  byId("updated").textContent = `${t.updated} ${lastUpdated.toLocaleTimeString(
    dateLocale,
    { hour12: false },
  )}`;
}

function setRefreshing(busy) {
  usageButton.disabled = busy;
  usageButton.setAttribute("aria-busy", busy ? "true" : "false");
  usageButton.setAttribute("aria-label", busy ? t.refreshing : t.refresh);
}

function hasDefaultLocalName(provider) {
  return provider.credential_mode === "local_codex" && provider.name === "Local Codex";
}

function providerName(provider) {
  return hasDefaultLocalName(provider) ? t.local : provider.name || provider.id || "—";
}

// Each row owns its allowance DOM, cached result and request generation.
function createPanel() {
  const key = `provider-panel-${++panelSequence}`;
  const elements = {};
  const make = (tag, name, className = "") => {
    const node = element(tag, className);
    node.id = `${key}-${name}`;
    elements[name] = node;
    return node;
  };
  const detail = make("section", "detail", "editor");
  detail.hidden = true;
  detail.setAttribute("aria-labelledby", `${key}-source-name`);
  const heading = element("div", "sr-only");
  heading.append(make("h2", "source-name"), make("span", "plan"), make("span", "account-status"));
  const row = element("div", "editor-row");
  const label = make("span", "quota-label", "editor-label compact");
  const body = element("div", "editor-body");
  const list = element("div", "quota-list");
  list.setAttribute("aria-live", "polite");
  list.append(make("div", "usage-result", "quota-rows"), make("p", "quota-policy", "quota-note"));
  const notice = make("p", "notice", "notice");
  notice.setAttribute("role", "status");
  notice.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>';
  notice.append(make("span", "notice-text"));
  body.append(list, notice);
  row.append(label, body);
  detail.append(heading, row);
  return {
    elements, detail, accountStatus: elements["account-status"],
    usageResult: elements["usage-result"], quotaPolicy: elements["quota-policy"], notice,
    account: {}, expanded: false, lastUsage: null, shownRevision: null,
    usageMessage: "loading", generation: 0, promise: null,
  };
}

function invalidatePanel(panel) {
  ++panel.generation;
  panel.promise = null;
  panel.detail.setAttribute("aria-busy", "false");
}

function providerRow(id) {
  let node = rowNodes.get(id);
  if (node) return node;
  // The row is a container of sibling buttons, never nested: the main button
  // expands the allowance, the gear only opens the settings dialog and the
  // switch only sets `enabled`.
  const row = element("div", "provider-row");
  const main = element("button", "provider-main");
  main.type = "button";
  const panel = createPanel();
  main.setAttribute("aria-controls", panel.detail.id);
  const icon = element("span", "provider-icon");
  icon.setAttribute("aria-hidden", "true");
  const copy = element("span", "provider-copy");
  const title = element("span", "provider-title");
  const name = element("strong", "provider-name");
  const disabledTag = element("span", "row-tag");
  const autoTag = element("span", "row-tag auto");
  title.append(name, disabledTag, autoTag);
  const sub = element("span", "provider-sub");
  copy.append(title, sub);
  // Row summary: a status dot and the plan while healthy, the
  // status itself once something needs attention.
  const meta = element("span", "provider-meta");
  const metaText = element("span", "provider-meta-text");
  meta.append(element("i", "status-dot"), metaText);
  const chevron = element("span", "chevron");
  chevron.setAttribute("aria-hidden", "true");
  chevron.innerHTML = chevronIcon;
  main.append(icon, copy, meta, chevron);
  main.addEventListener("click", () => void selectProvider(id));
  const gear = element("button", "icon-button row-settings");
  gear.type = "button";
  gear.setAttribute("aria-haspopup", "dialog");
  gear.innerHTML = gearIcon;
  gear.addEventListener("click", () => openSettings(id));
  const toggle = element("button", "switch");
  toggle.type = "button";
  toggle.setAttribute("role", "switch");
  toggle.append(element("span", "switch-track"));
  toggle.addEventListener("click", () => void toggleEnabled(id));
  row.append(main, gear, toggle);
  node = { panel, row, main, icon, name, disabledTag, autoTag, sub, meta, metaText, gear, toggle, iconMode: null };
  rowNodes.set(id, node);
  return node;
}

let accountRouting = null;
let routingBusy = false;
let routingRenderKey = "";

function renderAccountRouting() {
  const section = byId("account-routing");
  section.hidden = !accountRouting;
  if (!accountRouting) return;
  byId("account-routing-title").textContent = t.accountRoutingTitle;
  byId("account-routing-help").textContent = t.accountRoutingHelp;
  const signature = JSON.stringify([accountRouting, routingBusy, language, providers.map(p => [p.id, providerName(p)])]);
  if (signature === routingRenderKey) return;
  routingRenderKey = signature;
  const fields = byId("account-routing-fields");
  fields.replaceChildren();
  const addSelect = (labelText, accountId, modelId = null) => {
    const label = element("label", "account-route-field");
    const caption = element("span");
    caption.textContent = labelText;
    const select = element("select", "text-input");
    select.disabled = routingBusy;
    select.setAttribute("aria-label", labelText);
    const addOption = (value, text) => {
      const option = element("option");
      option.value = value;
      option.textContent = text;
      select.append(option);
    };
    if (modelId !== null) addOption("", t.followDefault);
    for (const provider of providers) addOption(provider.id, providerName(provider));
    select.value = accountId || "";
    select.addEventListener("change", () => void saveAccountRouting(select.value || null, modelId));
    label.append(caption, select);
    fields.append(label);
  };
  addSelect(t.defaultAccount, accountRouting.default_account_id);
  for (const model of accountRouting.models || []) addSelect(model.id, model.account_id, model.id);
}

async function saveAccountRouting(accountId, modelId) {
  if (routingBusy) return;
  routingBusy = true;
  renderAccountRouting();
  showSaveError("");
  let error = null;
  try {
    const body = {account_id: accountId};
    if (modelId !== null) body.model_id = modelId;
    const result = await bridge.apiPost("routing/update", body);
    if (result?.status !== "success" || !result.routing) throw new Error(t.saveUnknown);
    accountRouting = result.routing;
  } catch (reason) {
    error = reason;
  } finally {
    // Ignore older list requests that started before this write completed.
    listedSeq = ++listRequestSeq;
    routingBusy = false;
    renderAccountRouting();
  }
  try { await loadProviders(); } catch (reason) { error ||= reason; }
  if (error) showSaveError(() => t.saveFailed(t.accountRoutingTitle, messageText(error.message) || t.saveUnknown));
}

function renderProviders() {
  const order = [];
  for (const confirmed of providers) {
    const provider = effective(confirmed);
    const node = providerRow(provider.id);
    const local = provider.credential_mode === "local_codex";
    const iconMode = local ? "local_codex" : "device_oauth";
    if (node.iconMode !== iconMode) {
      node.iconMode = iconMode;
      node.icon.innerHTML = providerIcons[iconMode];
    }
    const panel = node.panel;
    renderAccountStatus(panel, confirmed);
    panel.detail.hidden = !panel.expanded;
    panel.elements["quota-label"].textContent = t.quotaLabel;
    const state = String(provider.status || "unknown");
    const enabled = isEnabled(provider);
    const busy = isSaving(provider.id);
    node.row.className =
      "provider-row" +
      (panel.expanded ? " open" : "") +
      (enabled ? "" : " disabled");
    node.main.setAttribute("aria-expanded", String(panel.expanded));
    node.name.textContent = providerName(provider);
    node.disabledTag.textContent = t.disabledTag;
    node.disabledTag.hidden = enabled;
    node.autoTag.textContent = t.autoTag;
    node.autoTag.hidden = routingMode(provider) !== "auto";
    node.gear.setAttribute("aria-label", t.settingsFor(providerName(provider)));
    node.gear.setAttribute("title", t.settingsFor(providerName(provider)));
    node.toggle.setAttribute("aria-checked", String(enabled));
    node.toggle.setAttribute("aria-label", t.enable(providerName(provider)));
    node.toggle.setAttribute("title", busy ? t.saving : t.enable(providerName(provider)));
    node.toggle.setAttribute("aria-busy", String(busy));
    node.toggle.disabled = busy;
    const plan = plans[provider.plan_type];
    node.sub.textContent = provider.email || (local ? t.localShort : t.deviceShort);
    const healthy = state === "ready";
    node.metaText.textContent =
      healthy && plan ? `ChatGPT ${plan}` : t.states[state] || t.states.unknown;
    node.meta.className = "provider-meta" + statusClass(state);
    node.meta.setAttribute("title", t.details[state] || t.details.unknown);
    order.push(node.row);
    order.push(panel.detail);
  }
  for (const id of [...rowNodes.keys()])
    if (!providers.some((provider) => provider.id === id)) {
      invalidatePanel(rowNodes.get(id).panel);
      rowNodes.delete(id);
    }
  // Preserve row DOM and focus across background refreshes.
  const current = [...providerList.children];
  if (
    current.length !== order.length ||
    current.some((child, index) => child !== order[index])
  )
    providerList.replaceChildren(...order);
  // The login result card reads the saved provider from this list.
  if (login.phase === "success") renderLogin();
  syncSettings();
  renderAccountRouting();
}

async function selectProvider(id) {
  const panel = rowNodes.get(id)?.panel;
  if (!panel) return;
  if (panel.expanded) {
    panel.expanded = false;
    invalidatePanel(panel);
    renderProviders();
  } else {
    await openProvider(id);
  }
}

async function openProvider(id) {
  const panel = rowNodes.get(id)?.panel;
  if (!panel) return;
  panel.expanded = true;
  renderProviders();
  await queryProvider(id);
}

// Bound concurrency across refreshes, expanding rows and identity changes.
async function usageSlot(task) {
  if (activeUsageRequests >= 3) await new Promise((resolve) => usageQueue.push(resolve));
  else ++activeUsageRequests;
  try { return await task(); }
  finally {
    const next = usageQueue.shift();
    if (next) next();
    else --activeUsageRequests;
  }
}

async function queryProvider(id) {
  const panel = rowNodes.get(id)?.panel;
  if (!panel?.expanded) return;
  if (panel.promise) return panel.promise;
  const latest = providers.find((p) => p.id === id);
  if (!latest) return;
  renderAccountStatus(panel, latest);
  if (signedOutStates.includes(latest.status)) {
    clearUsage(panel, latest.credential_mode === "local_codex" ? "localMissing" : "noHelp");
    return;
  }
  const generation = ++panel.generation;
  const current = () => rowNodes.get(id)?.panel === panel && panel.expanded && panel.generation === generation;
  panel.detail.setAttribute("aria-busy", "true");
  if (!panel.lastUsage) showUsageMessage(panel, "loading");
  const pending = usageSlot(async () => {
    if (!current()) return;
    const since = mutationSeq;
    try {
      const body = { source_id: id };
      let result = await bridge.apiPost("account/usage", body);
      if (!current()) return;
      if (result?.status === "account_changed") result = await bridge.apiPost("account/usage", body);
      if (!current()) return;
      if (result?.account) {
        if (result.account.id !== id) throw new Error(t.failed);
        const kept = keepNewerEdits(result.account, since);
        if (kept.account_revision !== result.account.account_revision) return;
        result = { ...result, account: kept };
      }
      renderUsage(panel, result);
      providers = providers.map((p) => p.id === id ? panel.account : p);
      renderProviders();
      lastUpdated = new Date();
      renderUpdated();
    } catch {
      if (current()) clearUsage(panel, "failed");
    }
  });
  panel.promise = pending;
  try { await pending; }
  finally {
    if (panel.promise === pending) {
      panel.promise = null;
      panel.detail.setAttribute("aria-busy", "false");
    }
  }
}

async function loadProviders() {
  const since = mutationSeq;
  const listed = ++listRequestSeq;
  const list = await bridge.apiPost("providers/list", {});
  if (listed < listedSeq) return;
  if (!Array.isArray(list?.providers)) throw new Error();
  providers = list.providers.map((p) => keepNewerEdits(p, since));
  if (!routingBusy && list.routing) accountRouting = list.routing;
  listedSeq = listed;
  showPageError("");
  renderProviders();
  if (!initializedExpansion && providers.length) {
    initializedExpansion = true;
    rowNodes.get(providers[0].id).panel.expanded = true;
    renderProviders();
  }
}

async function queryUsage(revealId = null) {
  if (refreshPromise) return refreshPromise;
  const pending = (async () => {
    setRefreshing(true);
    try {
      await loadProviders();
      const reveal = rowNodes.get(revealId)?.panel;
      if (reveal) {
        reveal.expanded = true;
        renderProviders();
      }
    } catch (reason) {
      showPageError(reason?.message || (() => t.listFailed));
    }
    await Promise.all(providers.map((p) => queryProvider(p.id)));
  })();
  refreshPromise = pending;
  try { await pending; }
  finally {
    if (refreshPromise === pending) {
      refreshPromise = null;
      setRefreshing(false);
    }
  }
}

function markMutation(id) {
  lastMutation.set(id, ++mutationSeq);
}

// Keep the confirmed editable fields when this response may predate a write.
function keepNewerEdits(next, since) {
  const id = next?.id;
  if (!isSaving(id) && (lastMutation.get(id) ?? 0) <= since) return next;
  const local = providers.find((p) => p.id === id);
  if (!local) return next;
  if (local.account_revision !== next.account_revision) return local;
  const kept = { ...next };
  for (const key of editableFields) if (key in local) kept[key] = local[key];
  return kept;
}

function runInChain(sourceId, task) {
  const previous = saveChains.get(sourceId) || Promise.resolve();
  const next = previous.then(task, task);
  const tail = next.catch(() => {});
  saveChains.set(sourceId, tail);
  void tail.then(() => {
    if (saveChains.get(sourceId) === tail) saveChains.delete(sourceId);
  });
  return next;
}

function renderSourceState(sourceId) {
  renderProviders();
  const panel = rowNodes.get(sourceId)?.panel;
  if (panel) updateNotice(panel);
}

function applyProvider(provider) {
  const index = providers.findIndex((p) => p.id === provider.id);
  if (index < 0) return;
  providers[index] = provider;
  const panel = rowNodes.get(provider.id)?.panel;
  if (panel) return renderAccountStatus(panel, provider);
  return false;
}

function showSaveError(message) {
  saveErrorMessage = message;
  saveError.textContent = messageText(message);
  saveError.hidden = !message;
}

// Send only the fields the user changed. The server's provider object is
// authoritative; a rejected or unclear outcome reloads the list. Resolves
// once the write settles with {status, message, followUp}, where `followUp`
// is the reload or quota refresh that the outcome started.
async function writeProvider(sourceId, changes, { report = true } = {}) {
  const queued = pendingChanges.get(sourceId) || [];
  queued.push(changes);
  pendingChanges.set(sourceId, queued);
  markMutation(sourceId);
  if (report) showSaveError("");
  renderSourceState(sourceId);
  let reconcile = false;
  let refreshIdentity = false;
  let outcome = { status: "success", message: "" };
  try {
    const result = await runInChain(sourceId, () =>
      bridge.apiPost("providers/update", { source_id: sourceId, ...changes }),
    );
    const provider = result?.provider;
    if (result?.status === "success" && provider?.id === sourceId) {
      refreshIdentity = applyProvider(provider);
    } else {
      reconcile = true;
      outcome = { status: "unknown", message: () => t.saveUnknown };
    }
  } catch (reason) {
    // The bridge reports HTTP rejections and transport failures alike, so
    // the write may or may not have landed. Keep the previous state and
    // reload it from the server.
    reconcile = true;
    const local = providers.find((p) => p.id === sourceId);
    outcome = {
      status: "failed",
      message: () => t.saveFailed(
        local ? providerName(local) : sourceId,
        messageText(reason?.message) || t.saveUnknown,
      ),
    };
  } finally {
    const left = (pendingChanges.get(sourceId) || []).filter((c) => c !== changes);
    if (left.length) pendingChanges.set(sourceId, left);
    else pendingChanges.delete(sourceId);
    markMutation(sourceId);
    if (report && outcome.status !== "success") showSaveError(outcome.message);
    renderSourceState(sourceId);
  }
  outcome.followUp = reconcile
    ? reloadProviders()
    : refreshIdentity
      ? queryProvider(sourceId)
      : Promise.resolve();
  return outcome;
}

async function saveProvider(sourceId, changes) {
  const outcome = await writeProvider(sourceId, changes);
  await outcome.followUp;
  return outcome;
}

async function refreshAccountUsage(revealId = null) {
  // A completed login may replace an identity while its lookup is pending.
  for (const { panel } of rowNodes.values()) invalidatePanel(panel);
  refreshPromise = null;
  await queryUsage(revealId);
}

async function reloadProviders() {
  try {
    await loadProviders();
    await Promise.all(providers.filter((p) => {
      const panel = rowNodes.get(p.id)?.panel;
      return panel?.expanded && !panel.lastUsage;
    }).map((p) => queryProvider(p.id)));
  } catch {
    // The save error stays visible; the next refresh retries the list.
  }
}

async function toggleEnabled(sourceId) {
  const provider = providers.find((p) => p.id === sourceId);
  if (!provider || isSaving(sourceId)) return;
  await saveProvider(sourceId, { enabled: !isEnabled(effective(provider)) });
}

// ---------- Settings dialog ----------

function settingsProvider() {
  return settings ? providers.find((p) => p.id === settings.sourceId) : undefined;
}

function openSettings(sourceId) {
  const provider = providers.find((p) => p.id === sourceId);
  if (!provider || settingsDialog.open || loginDialog.open) return;
  // Start from the latest effective state, including queued writes.
  const view = effective(provider);
  const defaultLocalName = hasDefaultLocalName(view);
  const base = {
    name: defaultLocalName ? t.local : String(view.name || ""),
    routing_mode: routingMode(view),
  };
  settings = {
    sourceId,
    base,
    defaultLocalName,
    draft: { ...base },
    // null, "save" or "remove" while a request for this session runs.
    busy: null,
    error: "",
    iconMode: null,
    // Removal needs a second, explicit confirmation.
    removeArmed: false,
    // Hidden while the device login dialog renews this provider.
    suspended: false,
  };
  settingsNameInput.value = base.name;
  renderSettings();
  settingsDialog.showModal();
  settingsNameInput.focus?.();
}

// The fields that differ from where the draft started, normalized the way
// the server stores them.
function settingsChanges(session = settings) {
  const changes = {};
  if (!session) return changes;
  const name = session.draft.name.trim();
  if (name !== session.base.name) changes.name = name;
  if (session.draft.routing_mode !== session.base.routing_mode)
    changes.routing_mode = session.draft.routing_mode;
  return changes;
}

function renderSettings() {
  const session = settings;
  if (!session) return;
  // Translate an untouched default along with the title, without turning a
  // locale change into a rename or replacing a name the user is editing.
  if (session.defaultLocalName && session.base.name !== t.local) {
    if (session.draft.name === session.base.name) {
      session.draft.name = t.local;
      settingsNameInput.value = t.local;
    }
    session.base.name = t.local;
  }
  const provider = settingsProvider();
  if (provider) {
    const view = effective(provider);
    byId("settings-title").textContent = providerName(view);
    const iconMode =
      view.credential_mode === "local_codex" ? "local_codex" : "device_oauth";
    if (session.iconMode !== iconMode) {
      session.iconMode = iconMode;
      byId("settings-icon").innerHTML = providerIcons[iconMode];
    }
  }
  const busy = Boolean(session.busy);
  const nameMissing = !session.draft.name.trim();
  settingsNameInput.disabled = busy;
  settingsNameInput.setAttribute("aria-invalid", String(nameMissing));
  const nameHint = byId("settings-name-hint");
  nameHint.textContent = nameMissing ? t.nameRequired : "";
  nameHint.hidden = !nameMissing;
  const mode = session.draft.routing_mode;
  for (const [key, button] of Object.entries(settingsRouting)) {
    button.setAttribute("aria-pressed", String(key === mode));
    button.disabled = busy;
  }
  byId("settings-routing-help").textContent =
    mode === "auto" ? t.routingAutoHelp : t.routingFixedHelp;
  const dirty = Object.keys(settingsChanges(session)).length > 0;
  const saving = session.busy === "save";
  settingsSave.disabled = busy || !dirty || nameMissing || !provider;
  settingsSave.textContent = saving ? t.saving : t.saveName;
  settingsSave.setAttribute("aria-busy", String(saving));
  settingsCancel.disabled = busy;
  closeSettingsButton.disabled = busy;
  const settingsError = byId("settings-error");
  settingsError.textContent = messageText(session.error);
  settingsError.hidden = !session.error;
  renderSettingsAccount(session, provider ? effective(provider) : null);
}

// Local Codex follows the host login, so it offers no renew or removal.
function renderSettingsAccount(session, view) {
  const custom = Boolean(view) && view.credential_mode !== "local_codex";
  byId("settings-account").hidden = !custom;
  if (!custom) return;
  const state = String(view.status || "unknown");
  byId("settings-account-text").textContent =
    view.email || t.states[state] || t.states.unknown;
  const busy = Boolean(session.busy);
  byId("settings-reauth").disabled = busy;
  const armed = session.removeArmed;
  const remove = byId("settings-remove");
  remove.className = "button small danger" + (armed ? " armed" : "");
  remove.textContent =
    session.busy === "remove" ? t.removing : armed ? t.confirmRemove : t.remove;
  remove.disabled = busy;
  remove.setAttribute("aria-busy", String(session.busy === "remove"));
  byId("settings-remove-keep").hidden = !armed;
  byId("settings-remove-keep").disabled = busy;
  byId("settings-remove-hint").textContent = armed ? t.confirmHint : t.removeHint;
  byId("settings-danger").className = "danger-zone" + (armed ? " armed" : "");
}

// End the session and return focus to the row's gear, or to a stable control
// when that row is gone or about to go.
function endSettings(focusTarget = null) {
  const session = settings;
  settings = null;
  if (settingsDialog.open) settingsDialog.close();
  const gear = session && rowNodes.get(session.sourceId)?.gear;
  const target =
    focusTarget || (gear && gear.isConnected !== false ? gear : byId("add-provider"));
  target.focus?.();
}

// Cancel, the close button and Escape all discard the draft. A save in
// flight cannot be undone, so the dialog stays until it settles.
function closeSettings() {
  if (!settings || settings.busy) return;
  endSettings();
}

// A refresh may reveal that the edited provider is gone. End the session
// rather than let a later save address another account.
function syncSettings() {
  if (!settings) return;
  if (settingsProvider()) {
    renderSettings();
    return;
  }
  endSettings(byId("add-provider"));
  showPageError(() => t.settingsGone);
}

function setSettingsRouting(mode) {
  if (!settings || settings.busy) return;
  settings.draft.routing_mode = mode;
  renderSettings();
}

async function saveSettings() {
  const session = settings;
  if (!session || session.busy || settingsSave.disabled) return;
  const changes = settingsChanges(session);
  if (!Object.keys(changes).length || !session.draft.name.trim()) return;
  session.busy = "save";
  session.error = "";
  session.removeArmed = false;
  renderSettings();
  // One request carries every changed field for the bound source.
  const outcome = await writeProvider(session.sourceId, changes, { report: false });
  if (settings === session && outcome.status === "success") {
    session.busy = null;
    endSettings();
  }
  await outcome.followUp;
  if (settings !== session || outcome.status === "success") return;
  // The outcome is unclear or the write was rejected. Keep the draft, but
  // adopt fields the reloaded server state shows did land, so the dialog
  // never re-sends or claims an unconfirmed result.
  const current = providers.find((p) => p.id === session.sourceId);
  if (current && "name" in changes && current.name === changes.name) {
    session.base.name = changes.name;
    session.defaultLocalName = hasDefaultLocalName(current);
  }
  if (current && "routing_mode" in changes && routingMode(current) === changes.routing_mode)
    session.base.routing_mode = changes.routing_mode;
  session.busy = null;
  session.error = outcome.message;
  renderSettings();
}

// Renewing is independent of the draft: nothing is saved, and the device
// login only sends this session's source ID, so a disabled provider stays
// disabled. The settings dialog steps aside so only one modal is open, and
// comes back with the draft once the login dialog closes.
function reauthorizeFromSettings() {
  const session = settings;
  const provider = settingsProvider();
  if (!session || session.busy || !provider) return;
  if (provider.credential_mode === "local_codex") return;
  session.removeArmed = false;
  session.suspended = true;
  settingsDialog.close();
  openLogin(session.sourceId);
}

function resumeSettings() {
  const session = settings;
  if (!session?.suspended) return;
  session.suspended = false;
  if (!settingsProvider()) {
    syncSettings();
    return;
  }
  renderSettings();
  settingsDialog.showModal();
  byId("settings-reauth").focus?.();
}

function disarmRemoval() {
  if (!settings?.removeArmed || settings.busy) return;
  settings.removeArmed = false;
  renderSettings();
  byId("settings-remove").focus?.();
}

// The first click arms removal and the second deletes. Removing never saves
// the draft, and keeping the provider leaves the draft as it was.
async function removeFromSettings() {
  const session = settings;
  const provider = settingsProvider();
  if (!session || session.busy || !provider) return;
  if (provider.credential_mode === "local_codex") return;
  if (!session.removeArmed) {
    session.removeArmed = true;
    session.error = "";
    renderSettings();
    return;
  }
  const sourceId = session.sourceId;
  const name = providerName(effective(provider));
  session.busy = "remove";
  session.error = "";
  renderSettings();
  try {
    await runInChain(sourceId, () =>
      bridge.apiPost("providers/delete", { source_id: sourceId }),
    );
  } catch (reason) {
    // The removal may still have landed; a reload that no longer lists the
    // provider ends this session instead of showing a stale error.
    await reloadProviders();
    if (settings !== session) return;
    session.busy = null;
    session.removeArmed = false;
    session.error = () => t.removeFailed(name, messageText(reason?.message) || t.saveUnknown);
    renderSettings();
    return;
  }
  if (settings === session) {
    session.busy = null;
    endSettings(byId("add-provider"));
  }
  await refreshAccountUsage();
}

function rerender() {
  showPageError(pageErrorMessage);
  showSaveError(saveErrorMessage);
  renderProviders();
  for (const { panel } of rowNodes.values()) {
    if (panel.lastUsage) renderUsage(panel, { status: "success", usage: panel.lastUsage });
    else showUsageMessage(panel, panel.usageMessage);
  }
  renderUpdated();
  renderLogin();
  renderSettings();
}

bridge.onContext?.((next) => {
  const locale = next?.locale;
  if (!locale || resolveLanguage(locale) === language) return;
  applyLocale(locale);
  rerender();
});

function safeVerifyUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function loginStateView() {
  switch (login.phase) {
    case "requesting":
      return { tone: "busy", title: t.requesting };
    case "waiting":
      return { tone: "busy", title: login.retrying ? t.retrying : t.waiting };
    case "saving":
      return { tone: "busy", title: login.retrying ? t.retrying : t.savingLogin };
    case "success":
      return {
        tone: "ok",
        title: t.success,
        detail: loginSourceId ? t.renewedDetail : t.successDetail,
      };
    case "timeout":
      return { tone: "warn", title: t.expired };
    case "expired":
      return { tone: "warn", title: t.sessionExpired, detail: t.sessionExpiredDetail };
    case "cancelled":
      return { tone: "", title: t.cancelled };
    default:
      return { tone: "", title: "" };
  }
}

function savedLoginProvider() {
  if (login.phase !== "success" || listedSeq <= login.listAfter) return null;
  return providers.find((p) => p.id === login.savedId) || null;
}

// Render the whole dialog from `login` and the session flags.
function renderLogin() {
  const { phase } = login;
  const live = Boolean(activeSessionId);
  const renewing = Boolean(loginSourceId);
  const target = renewing ? providers.find((p) => p.id === loginSourceId) : null;
  byId("instructions-title").textContent = renewing ? t.renew : t.add;
  const showForm = !live && formPhases.includes(phase);
  loginIntro.hidden = !showForm;
  loginIntro.textContent = renewing
    ? t.introRenew(target ? providerName(target) : loginSourceId)
    : t.intro;
  byId("login-name-field").hidden = !showForm || renewing;
  loginNameInput.disabled = phase === "requesting";

  // The code stays visible after a recoverable failure: the session may
  // still be authorized from a tab that is already open.
  const showCode =
    live && !login.saving && ["waiting", "failed"].includes(phase) && Boolean(login.code);
  devicePanel.hidden = !showCode;
  userCode.value = showCode ? login.code : "";
  const url = showCode ? safeVerifyUrl(login.url) : "";
  verifyUrl.value = url;
  byId("verify-row").hidden = !url;
  copyStatus.textContent = showCode ? t[login.note] || "" : "";

  const state = loginStateView();
  loginState.className = "login-state" + (state.tone ? ` ${state.tone}` : "");
  status.textContent = state.title;
  statusDetail.textContent = state.detail || "";
  statusDetail.hidden = !state.detail;
  statusDots.hidden = state.tone !== "busy";
  stateIcon.innerHTML = stateIcons[state.tone] || "";
  stateIcon.hidden = !stateIcons[state.tone];

  const saved = savedLoginProvider();
  savedProvider.hidden = !saved;
  if (saved) {
    byId("saved-name").textContent = providerName(saved);
    const plan = plans[saved.plan_type];
    const sub = [saved.email, plan && `ChatGPT ${plan}`].filter(Boolean).join(" · ");
    byId("saved-sub").textContent = sub;
    byId("saved-sub").hidden = !sub;
  }

  error.textContent = messageText(login.error);
  error.hidden = !login.error;

  // A cancel is refused while the server saves, so it is not offered then.
  cancelButton.textContent = t.cancel;
  cancelButton.hidden = !live || login.saving;
  cancelButton.disabled = cancelling;
  startButton.textContent =
    phase === "idle" || phase === "requesting"
      ? t.start
      : phase === "timeout"
        ? t.restartCode
        : live && login.saving
          ? t.retryStatus
          : t.restart;
  startButton.hidden = !formPhases.includes(phase);
  startButton.disabled = phase === "requesting" || cancelling;
  doneButton.textContent = t.done;
  doneButton.hidden = phase !== "success";
  closeButton.disabled = phase === "requesting" || phase === "saving";
  focusLoginAction();
}

// Keep keyboard focus inside the dialog when the focused control disappears.
function focusLoginAction() {
  if (!loginDialog.open) return;
  const active = document.activeElement;
  const unusable = (node) =>
    !node || node.hidden || node.disabled || Boolean(node.closest?.("[hidden]"));
  if (active && active !== document.body && !unusable(active)) return;
  const next = [!devicePanel.hidden && copyCodeButton, doneButton, startButton].find(
    (node) => !unusable(node),
  );
  next?.focus?.();
}

function resetLogin(phase) {
  for (const [button, key] of [[copyUrlButton, "copyUrl"], [copyCodeButton, "copyCode"]]) {
    window.clearTimeout(copyTimers.get(button));
    button.textContent = t[key];
  }
  Object.assign(login, {
    phase,
    url: "",
    code: "",
    error: "",
    note: "",
    retrying: false,
    saving: false,
  });
}

// A server-reported login failure ends the session; a transport failure
// (`terminal` false) keeps it so a cancel or a later poll can settle it.
function failLogin(message, terminal) {
  clearPollTimer();
  if (terminal) {
    activeSessionId = null;
    login.saving = false;
  }
  login.phase = "failed";
  login.retrying = false;
  login.error = message || (() => t.failedLogin);
  renderLogin();
}

function finishSuccess(sourceId) {
  clearPollTimer();
  activeSessionId = null;
  resetLogin("success");
  login.savedId = sourceId || loginSourceId || null;
  login.listAfter = listRequestSeq;
  renderLogin();
  void refreshAccountUsage(login.savedId);
}

function finishTimeout() {
  clearPollTimer();
  activeSessionId = null;
  resetLogin("timeout");
  renderLogin();
}

function finishExpiredSession() {
  clearPollTimer();
  activeSessionId = null;
  resetLogin("expired");
  renderLogin();
  // A lost terminal response may have followed a successful provider save.
  void refreshAccountUsage();
}

async function poll(sessionId, intervalSeconds) {
  try {
    const result = await bridge.apiPost("device/poll", {
      session_id: sessionId,
    });
    if (activeSessionId !== sessionId) return;
    // A successful poll consumes the server result. Keep it even if a
    // concurrent cancellation is refused because saving already finished.
    if (cancelling && result.status !== "success") return;
    consecutivePollFailures = 0;
    if (result.status === "success") {
      finishSuccess(result.source_id);
      return;
    }
    if (result.status === "expired") {
      finishExpiredSession();
      return;
    }
    if (result.status === "timeout") {
      finishTimeout();
      return;
    }
    if (result.status === "error") {
      failLogin(result.error || (() => t.failedLogin), true);
      return;
    }
    if (result.status === "saving") login.saving = true;
    login.phase = login.saving ? "saving" : "waiting";
    login.retrying = false;
    login.error = "";
    renderLogin();
    schedulePoll(sessionId, intervalSeconds);
  } catch (reason) {
    if (activeSessionId !== sessionId || cancelling) return;
    consecutivePollFailures += 1;
    if (consecutivePollFailures >= maxConsecutivePollFailures) {
      failLogin(reason?.message || (() => t.failedLogin), false);
      return;
    }
    login.phase = login.saving ? "saving" : "waiting";
    login.retrying = true;
    renderLogin();
    schedulePoll(sessionId, intervalSeconds);
  }
}

async function startLogin() {
  if (login.phase === "requesting" || cancelling) return;
  if (activeSessionId && login.saving) {
    // Saving cannot be cancelled. Recover by checking the same session again.
    clearPollTimer();
    consecutivePollFailures = 0;
    login.phase = "saving";
    login.error = "";
    login.retrying = true;
    renderLogin();
    await poll(activeSessionId, 2);
    return;
  }
  if (activeSessionId) {
    await cancelLogin();
    if (activeSessionId) return;
  }
  clearPollTimer();
  consecutivePollFailures = 0;
  resetLogin("requesting");
  login.savedId = null;
  renderLogin();
  const name = loginNameInput.value.trim();
  try {
    // An empty name lets the server apply its default.
    const body = loginSourceId ? { source_id: loginSourceId } : name ? { name } : {};
    const result = await bridge.apiPost("device/start", body);
    if (result?.status !== "pending") {
      throw new Error(result?.message || "");
    }
    activeSessionId = result.session_id;
    Object.assign(login, {
      phase: "waiting",
      url: result.verify_url,
      code: result.user_code,
    });
    renderLogin();
    await poll(result.session_id, Math.max(2, Number(result.interval) || 5));
  } catch (reason) {
    failLogin(reason?.message || (() => t.failedLogin), false);
  }
}

async function cancelLogin() {
  if (!activeSessionId) {
    return;
  }
  cancelling = true;
  renderLogin();
  const sessionId = activeSessionId;
  try {
    const result = await bridge.apiPost("device/cancel", { session_id: sessionId });
    if (activeSessionId !== sessionId) return;
    if (result.status === "expired") {
      finishExpiredSession();
      return;
    }
    clearPollTimer();
    activeSessionId = null;
    resetLogin("cancelled");
  } catch (reason) {
    // Saving may already be under way (HTTP 409) or the request was lost:
    // keep the session and let polling report how it ends.
    if (activeSessionId !== sessionId) return;
    failLogin(reason?.message || (() => t.failedLogin), false);
    schedulePoll(activeSessionId, 2);
  } finally {
    cancelling = false;
    renderLogin();
  }
}

// Copy synchronously first: that keeps the click's user activation, which
// sandboxed plugin pages need, while the async Clipboard API is often
// blocked there by permissions policy.
async function copyText(field) {
  const value = field.value;
  if (!value) return false;
  const previous = document.activeElement;
  let copied = false;
  try {
    field.focus?.({ preventScroll: true });
    field.select?.();
    field.setSelectionRange?.(0, value.length);
    copied = document.execCommand?.("copy") === true;
  } catch {
    copied = false;
  } finally {
    if (previous && previous !== field) previous.focus?.({ preventScroll: true });
  }
  if (!copied && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      copied = true;
    } catch {
      copied = false;
    }
  }
  return copied;
}

function flashCopied(button) {
  const key = button === copyUrlButton ? "copyUrl" : "copyCode";
  button.textContent = t.copiedShort;
  window.clearTimeout(copyTimers.get(button));
  copyTimers.set(
    button,
    window.setTimeout(() => {
      button.textContent = t[key];
    }, 1600),
  );
}

async function copyField(field, button) {
  const sessionId = activeSessionId;
  const copied = await copyText(field);
  // The session may have ended while the clipboard call was pending.
  if (activeSessionId !== sessionId || devicePanel.hidden) return;
  if (copied) {
    login.note = field === userCode ? "copiedCode" : "copiedUrl";
    flashCopied(button);
  } else {
    login.note = "copyFailed";
    field.focus?.();
    field.select?.();
  }
  copyStatus.textContent = t[login.note] || "";
}

// Close after a successful login and reveal the saved provider.
function completeLogin() {
  const id = login.phase === "success" ? login.savedId : null;
  resetLogin("idle");
  login.savedId = null;
  if (loginDialog.open) loginDialog.close();
  const saved = Boolean(id) && providers.some((p) => p.id === id);
  if (saved && !rowNodes.get(id)?.panel.expanded) void openProvider(id);
  // A renewal started from settings returns there; that dialog takes focus.
  if (settings?.suspended) {
    resumeSettings();
    return;
  }
  if (!saved) return;
  const node = rowNodes.get(id);
  node?.row.scrollIntoView?.({ block: "nearest" });
  node?.main.focus?.({ preventScroll: true });
}

function openLogin(sourceId = null) {
  // A session still in progress keeps its own target until it settles.
  if (!activeSessionId) {
    loginSourceId = sourceId;
    resetLogin("idle");
    login.savedId = null;
    loginNameInput.value = "ChatGPT";
  }
  renderLogin();
  if (!loginDialog.open) loginDialog.showModal();
}

startButton.addEventListener("click", () => void startLogin());
cancelButton.addEventListener("click", () => void cancelLogin());
doneButton.addEventListener("click", () => completeLogin());
usageButton.addEventListener("click", () => void queryUsage());
copyUrlButton.addEventListener(
  "click",
  () => void copyField(verifyUrl, copyUrlButton),
);
copyCodeButton.addEventListener(
  "click",
  () => void copyField(userCode, copyCodeButton),
);
loginNameInput.addEventListener("keydown", (event) => {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Enter" && !startButton.hidden && !startButton.disabled) {
    event.preventDefault?.();
    void startLogin();
  }
});
byId("add-provider").addEventListener("click", () => openLogin());
settingsRouting.fixed.addEventListener("click", () => setSettingsRouting("fixed"));
settingsRouting.auto.addEventListener("click", () => setSettingsRouting("auto"));
settingsNameInput.addEventListener("input", () => {
  if (!settings || settings.busy) return;
  settings.draft.name = String(settingsNameInput.value || "");
  renderSettings();
});
settingsNameInput.addEventListener("keydown", (event) => {
  // Some browsers report the composition-ending Enter only as keyCode 229.
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Enter") void saveSettings();
});
settingsSave.addEventListener("click", () => void saveSettings());
settingsCancel.addEventListener("click", closeSettings);
closeSettingsButton.addEventListener("click", closeSettings);
byId("settings-reauth").addEventListener("click", reauthorizeFromSettings);
byId("settings-remove").addEventListener("click", () => void removeFromSettings());
byId("settings-remove-keep").addEventListener("click", disarmRemoval);
// Escape backs out of an armed removal first, then closes the dialog.
settingsDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  if (settings?.removeArmed && !settings.busy) disarmRemoval();
  else closeSettings();
});
// Browsers may close a modal without a cancellable event. Keep a busy
// session on screen; otherwise treat it like Cancel.
settingsDialog.addEventListener("close", () => {
  // Native close events are queued and can arrive after a new session opens
  // or after a suspended session resumes from device login.
  if (settingsDialog.open || !settings || settings.suspended) return;
  if (settings.busy) settingsDialog.showModal();
  else endSettings();
});
async function closeLogin() {
  if (closeButton.disabled || cancelling) return;
  if (login.phase === "success") {
    completeLogin();
    return;
  }
  if (activeSessionId) await cancelLogin();
  if (!activeSessionId) {
    loginDialog.close();
    resumeSettings();
  }
}
closeButton.addEventListener("click", () => void closeLogin());
loginDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  void closeLogin();
});
// The browser may still close the dialog itself (repeated Escape). Treat
// that like the close button so no session keeps running unseen.
loginDialog.addEventListener("close", async () => {
  // The close event is queued: it may arrive after the dialog was reopened.
  if (loginDialog.open) return;
  if (login.phase === "success") {
    completeLogin();
    return;
  }
  if (activeSessionId && !login.saving && !cancelling) await cancelLogin();
  // Browsers can force-close a dialog despite its cancel handler. Keep an
  // unresolved session visible, including a start request still in flight.
  if (!loginDialog.open && (activeSessionId || login.phase === "requesting")) {
    loginDialog.showModal();
    renderLogin();
  }
  if (!loginDialog.open) resumeSettings();
});
window.setInterval(() => {
  if (!document.hidden && !loginDialog.open) void queryUsage();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void queryUsage();
});
renderLogin();
void queryUsage();
