const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();

const strings = {
  en: {
    title: "Providers",
    refresh: "Refresh status",
    enable: (name) => `Use ${name} for new requests`,
    disabledTag: "Disabled",
    autoTag: "Fallback",
    routingLabel: "Routing",
    routingFixed: "Fixed provider",
    routingAuto: "Automatic fallback",
    routingFixedHelp:
      "Bound models use only this provider; requests fail if it is disabled or unavailable.",
    routingAutoHelp:
      "Bound models try this provider first, then enabled, available providers in list order. Each account is tried once; no switching after output starts.",
    saving: "Saving…",
    saveFailed: (name, message) => `Could not save ${name}: ${message}`,
    saveUnknown: "The save result is unknown. Reloaded the latest state.",
    name: "Provider name",
    nameShort: "Name",
    saveName: "Save",
    quotaLabel: "Allowance",
    removeHint: "Its saved login is deleted too.",
    confirmHint: "Click again to delete permanently.",
    localShort: "Follows the host Codex login",
    deviceShort: "Device-code login",
    remove: "Remove provider",
    confirmRemove: "Confirm removal",
    listFailed: "Could not load providers. Try refreshing.",
    localMissing: "No local Codex login detected. Sign in to Codex on the AstrBot host.",
    refreshing: "Refreshing…",
    updated: "Updated",
    automatic: "Refreshes every 30 seconds while visible",
    states: {
      ready: "Signed in",
      refreshing: "Refreshing",
      cooling: "Cooling down",
      degraded: "Needs attention",
      reauth_required: "Sign in again",
      not_logged_in: "Signed out",
      invalid: "Invalid credential",
      unknown: "Unknown",
    },
    details: {
      ready: "Signed in and ready to use.",
      refreshing: "Refreshing credentials…",
      cooling: "The subscription quota is temporarily cooling down.",
      degraded:
        "The current credential is usable, but its refresh needs attention.",
      reauth_required: "Sign in again to renew the OpenAI credential.",
      not_logged_in: "Not signed in yet.",
      invalid:
        "The stored credential is unsupported. Update the plugin and sign in again.",
      unknown: "Account status is unavailable.",
    },
    local: "Local Codex",
    add: "Add provider",
    renew: "Authorize again",
    noHelp: "Sign in to this provider to view its allowance.",
    privacy: "Credentials are stored only on the server.",
    loading: "Loading allowance",
    noWindows:
      "No quota windows returned. This does not mean unlimited usage.",
    failed:
      "Could not load allowance. Try refreshing.",
    changed: "Account changed. Refreshing its allowance",
    unknown: "Unavailable",
    remaining: "left",
    usedUp: "used up",
    fiveHour: "5-hour allowance",
    shortWindows: { 18000: "5 hours", 604800: "Weekly", 2592000: "30 days" },
    week: "Weekly allowance",
    month: "30-day allowance",
    hours: "hours",
    window: "window",
    today: "Today",
    soon: "Resets soon",
    resetIn: (n, unit) =>
      `Resets in ${n} ${{ m: "min", h: n === 1 ? "hour" : "hours", d: n === 1 ? "day" : "days" }[unit]}`,
    weeklyOnly:
      "Only the weekly window is returned. Missing windows do not imply unlimited usage.",
    exhausted: "Allowance limit reached. See the window reset time.",
    exhaustedUntil: (when) => `Allowance limit reached. It recovers ${when}.`,
    noSwitch: "Models bound to it will not switch accounts automatically.",
    willFallback:
      "Automatic fallback is on for bound models.",
    coolingUntil: (when) =>
      `The subscription quota is cooling down until ${when}.`,
    denied: "The service reports this allowance is currently unavailable.",
    close: "Close",
    intro: "Sign in to a ChatGPT account with a device code.",
    introRenew: (name) =>
      `Sign in to ChatGPT again for ${name}. Its name and settings stay the same.`,
    optional: "Optional",
    codeLabel: "Device code",
    openVerify: "Open OpenAI authorization page",
    verifyLink: "OpenAI authorization link",
    copyUrl: "Copy link",
    copyCode: "Copy",
    copiedShort: "Copied",
    copiedCode: "Device code copied.",
    copiedUrl: "Link copied. Open it in any browser or account.",
    copyFailed: "Copy failed. Select the text and copy it manually.",
    openBlocked:
      "This page cannot open new tabs. The link was copied; paste it into your browser.",
    openBlockedManual:
      "This page cannot open new tabs. Copy the link and open it in your browser.",
    start: "Get device code",
    restartCode: "Get a new code",
    restart: "Log in again",
    cancel: "Cancel login",
    done: "Done",
    requesting: "Getting a device code",
    waiting: "Enter the code on the OpenAI page and confirm",
    retrying: "Connection interrupted. Retrying",
    savingLogin: "Authorized. Saving the provider",
    success: "Provider saved",
    successDetail: "Select it in AstrBot model settings to use it.",
    renewedDetail: "Its sign-in has been updated.",
    cancelled: "Login cancelled",
    failedLogin: "Login failed.",
    expired: "The device code expired",
    sessionExpired: "The sign-in session expired",
    sessionExpiredDetail:
      "If you already authorized, check the provider list. Otherwise, sign in again.",
  },
  zh: {
    title: "Providers",
    refresh: "刷新状态",
    enable: (name) => `新请求使用 ${name}`,
    disabledTag: "已停用",
    autoTag: "自动回退",
    routingLabel: "路由",
    routingFixed: "固定 Provider",
    routingAuto: "自动回退",
    routingFixedHelp:
      "绑定的模型仅使用此 Provider；停用或不可用时请求失败。",
    routingAutoHelp:
      "绑定的模型先用它，再按列表顺序尝试其他已启用且可用的 Provider。同一账号只尝试一次，开始输出后不再切换。",
    saving: "正在保存…",
    saveFailed: (name, message) => `保存「${name}」失败：${message}`,
    saveUnknown: "保存结果未知，已重新获取最新状态。",
    name: "Provider 名称",
    nameShort: "名称",
    saveName: "保存",
    quotaLabel: "额度",
    removeHint: "会同时删除它保存的登录凭据。",
    confirmHint: "再次点击即永久删除。",
    localShort: "跟随主机上的 Codex 登录",
    deviceShort: "设备码登录",
    remove: "移除此 Provider",
    confirmRemove: "确认移除",
    listFailed: "无法加载 Provider，请刷新重试。",
    localMissing: "未检测到本地登录，请在 AstrBot 所在机器登录 Codex。",
    refreshing: "正在刷新…",
    updated: "更新于",
    automatic: "页面可见时每 30 秒自动刷新",
    states: {
      ready: "已登录",
      refreshing: "刷新中",
      cooling: "冷却中",
      degraded: "需要留意",
      reauth_required: "需重新登录",
      not_logged_in: "未登录",
      invalid: "凭据无效",
      unknown: "状态未知",
    },
    details: {
      ready: "已登录，可以使用。",
      refreshing: "正在刷新凭据……",
      cooling: "订阅额度当前处于冷却状态。",
      degraded: "当前凭据仍可使用，但刷新需要留意。",
      reauth_required: "请重新登录以更新 OpenAI 凭据。",
      not_logged_in: "尚未登录。",
      invalid: "已保存的凭据格式不受支持，请升级插件后重新登录。",
      unknown: "账号状态暂不可用。",
    },
    local: "本地 Codex",
    add: "新增 Provider",
    renew: "重新授权",
    noHelp: "登录此 Provider 后可查看额度。",
    privacy: "登录凭据仅保存在服务端。",
    loading: "正在查询额度",
    noWindows: "账号尚未返回额度窗口，暂无数据不代表无限额度。",
    failed: "暂时无法获取额度，请刷新重试。",
    changed: "账号已切换，正在更新额度",
    unknown: "暂不可用",
    remaining: "剩余",
    usedUp: "已用尽",
    fiveHour: "5 小时额度",
    shortWindows: { 18000: "5 小时", 604800: "每周", 2592000: "30 天" },
    week: "每周额度",
    month: "30 天额度",
    hours: "小时",
    window: "窗口",
    today: "今天",
    soon: "即将重置",
    resetIn: (n, unit) =>
      `${n} ${{ m: "分钟", h: "小时", d: "天" }[unit]}后重置`,
    weeklyOnly: "仅显示已返回的每周窗口；未返回不代表无限额度。",
    exhausted: "已达到额度上限，请查看窗口重置时间。",
    exhaustedUntil: (when) => `已达到额度上限，将于 ${when} 恢复。`,
    noSwitch: "以它为首选的模型不会自动切换账号。",
    willFallback: "绑定的模型已开启自动回退。",
    coolingUntil: (when) => `订阅额度冷却中，预计 ${when} 恢复。`,
    denied: "服务端返回当前额度不可用。",
    close: "关闭",
    intro: "使用设备码登录 ChatGPT 账号。",
    introRenew: (name) => `为「${name}」重新登录 ChatGPT，名称和设置保持不变。`,
    optional: "可选",
    codeLabel: "设备码",
    openVerify: "打开 OpenAI 授权页",
    verifyLink: "授权链接",
    copyUrl: "复制链接",
    copyCode: "复制",
    copiedShort: "已复制",
    copiedCode: "设备码已复制。",
    copiedUrl: "链接已复制，可在其他浏览器或账号中打开。",
    copyFailed: "复制失败，请手动选择并复制。",
    openBlocked: "当前页面无法打开新标签页，已复制链接，请粘贴到浏览器中打开。",
    openBlockedManual: "当前页面无法打开新标签页，请复制链接后在浏览器中打开。",
    start: "获取设备码",
    restartCode: "重新获取设备码",
    restart: "重新登录",
    cancel: "取消登录",
    done: "完成",
    requesting: "正在获取设备码",
    waiting: "在 OpenAI 授权页输入设备码并确认",
    retrying: "连接暂时中断，正在重试",
    savingLogin: "已授权，正在保存 Provider",
    success: "Provider 已保存",
    successDetail: "在 AstrBot 模型配置中选择它即可使用。",
    renewedDetail: "登录凭据已更新。",
    cancelled: "已取消登录",
    failedLogin: "登录失败。",
    expired: "设备码已过期",
    sessionExpired: "登录会话已失效",
    sessionExpiredDetail: "如已完成授权，请在列表中确认；否则请重新登录。",
  },
};

const byId = (id) => document.getElementById(id);
const startButton = byId("start");
const cancelButton = byId("cancel");
const usageButton = byId("usage");
const accountStatus = byId("account-status");
const usageResult = byId("usage-result");
const quotaPolicy = byId("quota-policy");
const notice = byId("notice");
const loginIntro = byId("login-intro");
const loginNameInput = byId("login-name");
const devicePanel = byId("device-panel");
const openVerifyLink = byId("open-verify");
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
const providerDetail = byId("provider-detail");
const providerNameInput = byId("provider-name");
const renameButton = byId("rename-provider");
const routingButtons = { fixed: byId("routing-fixed"), auto: byId("routing-auto") };
const saveError = byId("save-error");
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
// Rows persist across refreshes and are updated in place, so the detail
// editor (and a name being typed in it) is never detached by a re-render.
const rowNodes = new Map();
const maxConsecutivePollFailures = 5;
const warningStates = ["cooling", "degraded"];
const dangerStates = ["reauth_required", "invalid"];
const signedOutStates = ["not_logged_in", "invalid"];

let isEnglish = false;
let t = strings.zh;
let pollTimer = null;
let activeSessionId = null;
let consecutivePollFailures = 0;
let account = {};
let providers = [];
let selectedSourceId = null;
let expanded = true;
let loginSourceId = null;
let deletingSourceId = null;
let viewGeneration = 0;
let refreshPromise = null;
let cancelling = false;
// Last rendered usage, kept so a background refresh never blanks the cards
// and a locale change can re-render without another request.
let lastUsage = null;
let usageMessage = "loading";
let shownRevision = null;
let lastUpdated = null;
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

function applyLocale(locale) {
  isEnglish = String(locale || "zh-CN").startsWith("en");
  t = isEnglish ? strings.en : strings.zh;
  document.documentElement.lang = isEnglish ? "en" : "zh-CN";
  document.title = t.title;
  for (const [id, value] of Object.entries({
    title: t.title,
    "add-provider-label": t.add,
    "rename-label": t.nameShort,
    "rename-provider": t.saveName,
    "quota-label": t.quotaLabel,
    "routing-label": t.routingLabel,
    "routing-fixed": t.routingFixed,
    "routing-auto": t.routingAuto,
    "delete-hint": t.removeHint,
    "delete-provider": t.remove,
    "open-login": t.renew,
    "login-name-label": t.name,
    "login-name-optional": t.optional,
    privacy: t.privacy,
    "code-label": t.codeLabel,
    "open-verify-label": t.openVerify,
    "copy-url": t.copyUrl,
    "copy-code": t.copyCode,
  }))
    byId(id).textContent = value;
  closeButton.setAttribute("aria-label", t.close);
  verifyUrl.setAttribute("aria-label", t.verifyLink);
  usageButton.setAttribute("aria-label", t.refresh);
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
  const locale = isEnglish ? "en-US" : "zh-CN";
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

function renderAccountStatus(result) {
  const previous = account;
  account = result || {};
  const identityChanged =
    (previous.id === account.id &&
      (previous.account_revision ?? null) !== (account.account_revision ?? null)) ||
    (lastUsage && shownRevision !== (account.account_revision ?? null));
  if (identityChanged) {
    clearUsage("changed");
    lastUpdated = null;
    byId("updated").textContent = "";
  }
  const state = String(account.status || "unknown");
  accountStatus.textContent = t.states[state] || t.states.unknown;
  accountStatus.setAttribute("title", t.details[state] || t.details.unknown);
  accountStatus.className = "badge" + statusClass(state);

  const local = account.credential_mode === "local_codex";
  byId("source-name").textContent = providerName(account);
  if (document.activeElement !== providerNameInput)
    providerNameInput.value = account.name || "";
  syncRename();
  byId("open-login").hidden = local;
  byId("delete-provider").hidden = local;
  byId("delete-row").hidden = local;
  renderControls();
  updateNotice();
  return Boolean(identityChanged);
}

// Enabled and routing mode are separate from the health status above: a
// disabled source keeps its login, and enabling it repairs nothing.
function renderControls() {
  const view = effective(account);
  const busy = isSaving(account.id);
  const mode = routingMode(view);
  for (const [key, button] of Object.entries(routingButtons)) {
    button.setAttribute("aria-pressed", String(key === mode));
    button.disabled = busy || !account.id;
  }
  byId("routing-help").textContent =
    mode === "auto" ? t.routingAutoHelp : t.routingFixedHelp;
  syncRename();
}

function syncRename() {
  const value = String(providerNameInput.value || "").trim();
  renameButton.disabled =
    !value || value === (effective(account).name || "") || isSaving(account.id);
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
    ? `${Number((seconds / 3600).toFixed(2))} ${t.hours} ${t.window}`
    : t.window;
}

function showUsageMessage(key) {
  usageMessage = key;
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
  usageResult.replaceChildren(message);
  byId("plan").hidden = true;
  quotaPolicy.hidden = true;
}

function clearUsage(key) {
  lastUsage = null;
  shownRevision = null;
  showUsageMessage(key);
  updateNotice();
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

function renderUsage(result) {
  if (result?.account) renderAccountStatus(result.account);
  if (result?.status !== "success" || !result.usage) {
    clearUsage(result?.status === "account_changed" ? "changed" : "failed");
    if (["cooling", "reauth_required", "invalid"].includes(result?.status)) {
      renderAccountStatus({ ...account, status: result.status });
    }
    return;
  }
  lastUsage = result.usage;
  shownRevision = account.account_revision ?? null;
  const usage = result.usage;
  const windows = usageWindows(usage);
  if (!windows.length) {
    showUsageMessage("noWindows");
  } else {
    usageResult.replaceChildren(...windows.map(quotaRow));
  }
  const plan = plans[usage.plan_type];
  byId("plan").textContent = plan || "";
  byId("plan").hidden = !plan;
  const weeklyOnly =
    windows.length === 1 && windows[0].label_seconds === 604800;
  // Pro accounts currently return only a weekly window; that single line
  // needs no caveat. Other plans keep the "missing is not unlimited" note.
  quotaPolicy.hidden = !weeklyOnly || usage.plan_type === "pro";
  quotaPolicy.textContent = quotaPolicy.hidden ? "" : t.weeklyOnly;
  updateNotice();
}

function updateNotice() {
  const usage = lastUsage;
  let message = "";
  if (usage?.limit_reached) {
    const resets = usageWindows(usage)
      .filter((item) => remainingOf(item) === 0)
      .map((item) => resetSeconds(item.reset_at, item.reset_after_seconds))
      .filter((value) => value !== null);
    // The server may enforce a later cooldown than the reported quota windows.
    const cooldown = resetSeconds(account.cooldown_until);
    if (cooldown !== null) resets.push(cooldown);
    message = resets.length
      ? t.exhaustedUntil(formatAbsolute(Math.max(...resets)))
      : t.exhausted;
    message += (isEnglish ? " " : "") + (routingMode(effective(account)) === "auto" ? t.willFallback : t.noSwitch);
  } else if (account.status === "cooling") {
    const until = formatAbsolute(resetSeconds(account.cooldown_until));
    message = until ? t.coolingUntil(until) : t.details.cooling;
  } else if (usage && usage.allowed === false) {
    message = t.denied;
  } else if (["degraded", "reauth_required"].includes(account.status)) {
    message = t.details[account.status];
  }
  notice.hidden = !message;
  byId("notice-text").textContent = message;
}

function renderUpdated() {
  if (!lastUpdated) return;
  byId("updated").textContent = `${t.updated} ${lastUpdated.toLocaleTimeString(
    isEnglish ? "en-US" : "zh-CN",
    { hour12: false },
  )}`;
}

function setRefreshing(busy) {
  usageButton.disabled = busy;
  usageButton.setAttribute("aria-busy", busy ? "true" : "false");
  usageButton.setAttribute("aria-label", busy ? t.refreshing : t.refresh);
}

function providerName(provider) {
  return provider.credential_mode === "local_codex" && provider.name === "Local Codex"
    ? t.local : provider.name || provider.id || "—";
}

function providerRow(id) {
  let node = rowNodes.get(id);
  if (node) return node;
  // The row is a container: the main button selects the provider for
  // management, and the switch beside it (never nested in it) sets `enabled`.
  const row = element("div", "provider-row");
  const main = element("button", "provider-main");
  main.type = "button";
  main.setAttribute("aria-controls", "provider-detail");
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
  const toggle = element("button", "switch");
  toggle.type = "button";
  toggle.setAttribute("role", "switch");
  toggle.append(element("span", "switch-track"));
  toggle.addEventListener("click", () => void toggleEnabled(id));
  row.append(main, toggle);
  node = { row, main, icon, name, disabledTag, autoTag, sub, meta, metaText, toggle, iconMode: null };
  rowNodes.set(id, node);
  return node;
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
    const selected = provider.id === selectedSourceId;
    const state = String(provider.status || "unknown");
    const enabled = isEnabled(provider);
    const busy = isSaving(provider.id);
    node.row.className =
      "provider-row" +
      (selected ? " selected" : "") +
      (selected && expanded ? " open" : "") +
      (enabled ? "" : " disabled");
    node.main.setAttribute("aria-expanded", String(selected && expanded));
    node.name.textContent = providerName(provider);
    node.disabledTag.textContent = t.disabledTag;
    node.disabledTag.hidden = enabled;
    node.autoTag.textContent = t.autoTag;
    node.autoTag.hidden = routingMode(provider) !== "auto";
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
    if (selected) order.push(providerDetail);
  }
  for (const id of [...rowNodes.keys()])
    if (!providers.some((provider) => provider.id === id)) rowNodes.delete(id);
  if (!order.includes(providerDetail)) order.push(providerDetail);
  // Reorder only when the sequence changed: moving the editor would blur
  // a focused name field during the 30-second refresh.
  const current = [...providerList.children];
  if (
    current.length !== order.length ||
    current.some((child, index) => child !== order[index])
  )
    providerList.replaceChildren(...order);
  // The login result card reads the saved provider from this list.
  if (login.phase === "success") renderLogin();
}

async function selectProvider(id) {
  if (id && id === selectedSourceId) {
    // Clicking the open row folds its editor away.
    expanded = !expanded;
    providerDetail.hidden = !expanded;
    renderProviders();
    return;
  }
  await openProvider(id);
}

async function openProvider(id) {
  expanded = true;
  ++viewGeneration;
  refreshPromise = null;
  selectedSourceId = id;
  deletingSourceId = null;
  byId("delete-provider").textContent = t.remove;
  byId("delete-hint").textContent = t.removeHint;
  byId("page-error").hidden = true;
  lastUpdated = null;
  byId("updated").textContent = "";
  clearUsage("loading");
  const selected = providers.find((p) => p.id === id);
  if (selected) renderAccountStatus(selected);
  renderProviders();
  await queryUsage();
}

async function queryUsage() {
  if (refreshPromise) return refreshPromise;
  const generation = ++viewGeneration;
  const pending = (async () => {
    setRefreshing(true);
    if (!lastUsage) showUsageMessage("loading");
    const since = mutationSeq;
    try {
      const listed = ++listRequestSeq;
      const list = await bridge.apiPost("providers/list", {});
      if (generation !== viewGeneration) return;
      if (!Array.isArray(list?.providers)) throw new Error(t.listFailed);
      providers = list.providers.map((p) => keepNewerEdits(p, since));
      listedSeq = Math.max(listedSeq, listed);
      byId("page-error").hidden = true;
      if (!providers.some((p) => p.id === selectedSourceId)) {
        selectedSourceId = providers[0]?.id || null;
        clearUsage("loading");
      }
      renderProviders();
      const latest = providers.find((p) => p.id === selectedSourceId);
      providerDetail.hidden = !latest || !expanded;
      if (!latest) return;
      renderAccountStatus(latest);
      if (signedOutStates.includes(latest.status)) {
        clearUsage(latest.credential_mode === "local_codex" ? "localMissing" : "noHelp");
        return;
      }
      if (lastUsage && shownRevision !== (latest.account_revision ?? null)) clearUsage("changed");
      const body = { source_id: selectedSourceId };
      let result = await bridge.apiPost("account/usage", body);
      if (generation !== viewGeneration) return;
      if (result?.status === "account_changed") result = await bridge.apiPost("account/usage", body);
      if (generation !== viewGeneration) return;
      if (result?.account) {
        const current = keepNewerEdits(result.account, since);
        // Never attach an old quota payload to a newer confirmed identity.
        if (current.account_revision !== result.account.account_revision) return;
        result.account = current;
      }
      renderUsage(result);
      providers = providers.map((p) => p.id === selectedSourceId ? account : p);
      renderProviders();
      lastUpdated = new Date();
      renderUpdated();
    } catch (reason) {
      if (generation === viewGeneration) {
        clearUsage("failed");
        byId("page-error").textContent = reason?.message || t.listFailed;
        byId("page-error").hidden = false;
      }
    } finally {
      if (generation === viewGeneration) setRefreshing(false);
    }
  })();
  refreshPromise = pending;
  try { await pending; }
  finally { if (refreshPromise === pending) refreshPromise = null; }
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
  if (sourceId === selectedSourceId) {
    renderControls();
    updateNotice();
  }
}

function applyProvider(provider) {
  const index = providers.findIndex((p) => p.id === provider.id);
  if (index < 0) return;
  providers[index] = provider;
  if (provider.id === selectedSourceId) return renderAccountStatus(provider);
  return false;
}

function showSaveError(message) {
  saveError.textContent = message;
  saveError.hidden = !message;
}

// Send only the fields the user changed. The server's provider object is
// authoritative; a rejected or unclear outcome reloads the list.
async function saveProvider(sourceId, changes) {
  const queued = pendingChanges.get(sourceId) || [];
  queued.push(changes);
  pendingChanges.set(sourceId, queued);
  markMutation(sourceId);
  showSaveError("");
  renderSourceState(sourceId);
  let reconcile = false;
  let refreshIdentity = false;
  try {
    const result = await runInChain(sourceId, () =>
      bridge.apiPost("providers/update", { source_id: sourceId, ...changes }),
    );
    const provider = result?.provider;
    if (result?.status === "success" && provider?.id === sourceId) {
      refreshIdentity = applyProvider(provider);
    } else {
      reconcile = true;
      showSaveError(t.saveUnknown);
    }
  } catch (reason) {
    // The bridge reports HTTP rejections and transport failures alike, so
    // the write may or may not have landed. Keep the previous state and
    // reload it from the server.
    reconcile = true;
    const local = providers.find((p) => p.id === sourceId);
    showSaveError(
      t.saveFailed(local ? providerName(local) : sourceId, reason?.message || t.saveUnknown),
    );
  } finally {
    const left = (pendingChanges.get(sourceId) || []).filter((c) => c !== changes);
    if (left.length) pendingChanges.set(sourceId, left);
    else pendingChanges.delete(sourceId);
    markMutation(sourceId);
    renderSourceState(sourceId);
  }
  if (reconcile) await reloadProviders();
  else if (refreshIdentity) await refreshAccountUsage();
}

async function refreshAccountUsage() {
  // A lookup for the previous identity may still be in flight. queryUsage's
  // generation fence will discard it while this new lookup owns the spinner.
  refreshPromise = null;
  await queryUsage();
}

// Refetch the provider list, retaining quota only for the same account identity.
async function reloadProviders() {
  const since = mutationSeq;
  const generation = viewGeneration;
  try {
    const listed = ++listRequestSeq;
    const list = await bridge.apiPost("providers/list", {});
    if (generation !== viewGeneration) return;
    if (!Array.isArray(list?.providers)) return;
    providers = list.providers.map((p) => keepNewerEdits(p, since));
    listedSeq = Math.max(listedSeq, listed);
    const selected = providers.find((p) => p.id === selectedSourceId);
    if (!selected) {
      await queryUsage();
      return;
    }
    renderProviders();
    if (renderAccountStatus(selected)) await refreshAccountUsage();
  } catch {
    // The save error stays visible; the next refresh retries the list.
  }
}

async function toggleEnabled(sourceId) {
  const provider = providers.find((p) => p.id === sourceId);
  if (!provider || isSaving(sourceId)) return;
  await saveProvider(sourceId, { enabled: !isEnabled(effective(provider)) });
}

async function setRoutingMode(mode) {
  const sourceId = selectedSourceId;
  if (!sourceId || isSaving(sourceId)) return;
  if (routingMode(effective(account)) === mode) return;
  await saveProvider(sourceId, { routing_mode: mode });
}

async function renameProvider() {
  const sourceId = selectedSourceId;
  const name = String(providerNameInput.value || "").trim();
  if (!sourceId || renameButton.disabled || !name) return;
  await saveProvider(sourceId, { name });
}

async function deleteProvider() {
  const sourceId = selectedSourceId;
  if (!sourceId) return;
  if (deletingSourceId !== sourceId) {
    deletingSourceId = sourceId;
    byId("delete-provider").textContent = t.confirmRemove;
    byId("delete-hint").textContent = t.confirmHint;
    return;
  }
  const button = byId("delete-provider");
  button.disabled = true;
  try {
    await runInChain(sourceId, () =>
      bridge.apiPost("providers/delete", { source_id: sourceId }),
    );
    if (selectedSourceId === sourceId) await openProvider(null);
    else await queryUsage();
  } catch (reason) {
    byId("page-error").textContent = reason?.message || t.failed;
    byId("page-error").hidden = false;
  } finally { button.disabled = false; }
}

function rerender() {
  renderProviders();
  renderAccountStatus(account);
  if (lastUsage) {
    renderUsage({ status: "success", usage: lastUsage });
  } else {
    showUsageMessage(usageMessage);
  }
  renderUpdated();
  renderLogin();
}

bridge.onContext?.((next) => {
  const locale = next?.locale;
  if (!locale || String(locale).startsWith("en") === isEnglish) return;
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
  if (url) openVerifyLink.setAttribute("href", url);
  else openVerifyLink.removeAttribute("href");
  openVerifyLink.hidden = !url;
  byId("verify-row").hidden = !url;
  copyStatus.textContent = showCode ? login.note : "";

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

  error.textContent = login.error;
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
        : t.restart;
  startButton.hidden = !formPhases.includes(phase) || (live && login.saving);
  startButton.disabled = phase === "requesting";
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
  const next = [openVerifyLink, doneButton, startButton].find(
    (node) => !unusable(node) && (node !== openVerifyLink || node.getAttribute("href")),
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
  login.error = message || t.failedLogin;
  renderLogin();
}

function finishSuccess(sourceId) {
  clearPollTimer();
  activeSessionId = null;
  resetLogin("success");
  login.savedId = sourceId || loginSourceId || null;
  login.listAfter = listRequestSeq;
  renderLogin();
  if (login.savedId) void openProvider(login.savedId);
  else void refreshAccountUsage();
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
      failLogin(result.error || t.failedLogin, true);
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
      failLogin(reason?.message || t.failedLogin, false);
      return;
    }
    login.phase = login.saving ? "saving" : "waiting";
    login.retrying = true;
    renderLogin();
    schedulePoll(sessionId, intervalSeconds);
  }
}

async function startLogin() {
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
      throw new Error(result?.message || t.failedLogin);
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
    failLogin(reason?.message || t.failedLogin, false);
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
    failLogin(reason?.message || t.failedLogin, false);
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

async function copyField(field, button, messages = {}) {
  const sessionId = activeSessionId;
  const copied = await copyText(field);
  // The session may have ended while the clipboard call was pending.
  if (activeSessionId !== sessionId || devicePanel.hidden) return;
  if (copied) {
    login.note = messages.copied || (field === userCode ? t.copiedCode : t.copiedUrl);
    if (button) flashCopied(button);
  } else {
    login.note = messages.failed || t.copyFailed;
    field.focus?.();
    field.select?.();
  }
  copyStatus.textContent = login.note;
}

// Open the server-provided URL from the click itself. A sandboxed plugin
// page without popup permission gets null back, so copy the link instead.
function openVerification(event) {
  const url = openVerifyLink.getAttribute("href");
  if (!url) return;
  // Leave modified clicks (new window, background tab) to the browser.
  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  let opened = null;
  try {
    opened = window.open(url, "_blank");
  } catch {
    opened = null;
  }
  if (opened) {
    try {
      opened.opener = null;
    } catch {
      // Nothing else to do; the tab is already open.
    }
    return;
  }
  void copyField(verifyUrl, null, { copied: t.openBlocked, failed: t.openBlockedManual });
}

// Close after a successful login and reveal the saved provider.
function completeLogin() {
  const id = login.phase === "success" ? login.savedId : null;
  resetLogin("idle");
  login.savedId = null;
  if (loginDialog.open) loginDialog.close();
  if (!id || !providers.some((p) => p.id === id)) return;
  if (selectedSourceId !== id || !expanded) void openProvider(id);
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
openVerifyLink.addEventListener("click", openVerification);
loginNameInput.addEventListener("keydown", (event) => {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Enter" && !startButton.hidden && !startButton.disabled) {
    event.preventDefault?.();
    void startLogin();
  }
});
byId("open-login").addEventListener("click", () => openLogin(selectedSourceId));
byId("add-provider").addEventListener("click", () => openLogin());
byId("rename-provider").addEventListener("click", () => void renameProvider());
routingButtons.fixed.addEventListener("click", () => void setRoutingMode("fixed"));
routingButtons.auto.addEventListener("click", () => void setRoutingMode("auto"));
providerNameInput.addEventListener("input", syncRename);
providerNameInput.addEventListener("keydown", (event) => {
  // Some browsers report the composition-ending Enter only as keyCode 229.
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Enter" && !renameButton.disabled) void renameProvider();
});
byId("delete-provider").addEventListener("click", () => void deleteProvider());
async function closeLogin() {
  if (closeButton.disabled || cancelling) return;
  if (login.phase === "success") {
    completeLogin();
    return;
  }
  if (activeSessionId) await cancelLogin();
  if (!activeSessionId) loginDialog.close();
}
closeButton.addEventListener("click", () => void closeLogin());
loginDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  void closeLogin();
});
// The browser may still close the dialog itself (repeated Escape). Treat
// that like the close button so no session keeps running unseen.
loginDialog.addEventListener("close", () => {
  if (login.phase === "success") completeLogin();
  else if (activeSessionId && !cancelling) void cancelLogin();
});
window.setInterval(() => {
  if (!document.hidden && !loginDialog.open) void queryUsage();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void queryUsage();
});
renderLogin();
void queryUsage();
