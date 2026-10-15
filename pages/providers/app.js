const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();

const strings = {
  en: {
    title: "Providers",
    refresh: "Refresh status",
    providerHelp: "Choose the provider to use in AstrBot model settings.",
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
    claudeLocal: "Local Claude",
    claudeShort: "Follows the host Claude Code login",
    claudeReady: "Local login detected. Select Claude Subscribe in AstrBot model settings. Check allowance with /usage in Claude Code.",
    claudeMissing: "Run claude auth login as the AstrBot host user, then refresh here.",
    claudeCliMissing: "Install Claude Code on the AstrBot host, or set its executable path in plugin settings.",
    claudeWrongAuth: "Claude Code is using an API key or gateway. Sign in with your Claude subscription in the configured directory.",
    claudeUnknown: "Could not check Claude Code login. Check the CLI version and host permissions, then refresh.",
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
      cli_missing: "CLI not found",
      wrong_auth: "Subscription required",
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
    intro:
      "Sign in to ChatGPT with a device code.",
    open: "Open the verification URL in a new tab",
    code: "Enter this device code",
    confirm: "Confirm on the OpenAI page. This dialog updates automatically.",
    copyUrl: "Copy URL",
    copyCode: "Copy",
    copiedShort: "Copied",
    copied: "Copied. Open a new browser tab to continue.",
    copyFailed: "Copy failed. Select the value and copy it manually.",
    start: "Start login",
    restart: "Log in again",
    cancel: "Cancel login",
    cancelled: "Login was cancelled.",
    waiting: "Waiting for authorization",
    retrying: "Connection interrupted. Retrying",
    success:
      "Provider saved. Select this source in AstrBot model settings to use it.",
    failedLogin: "Login failed.",
    expired: "The device code expired. Please start again.",
  },
  zh: {
    title: "Providers",
    refresh: "刷新状态",
    providerHelp: "在 AstrBot 模型配置中选择要使用的 Provider。",
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
    claudeLocal: "本地 Claude",
    claudeShort: "跟随主机上的 Claude Code 登录",
    claudeReady: "已检测到本地登录。请在 AstrBot 模型配置中选择 Claude Subscribe；额度可在 Claude Code 中通过 /usage 查看。",
    claudeMissing: "请以 AstrBot 的运行用户在主机上运行 claude auth login，登录后刷新此页面。",
    claudeCliMissing: "请在 AstrBot 所在环境安装 Claude Code，或在插件设置中指定可执行文件路径。",
    claudeWrongAuth: "Claude Code 当前使用 API Key 或网关，请在指定配置目录中登录 Claude 订阅账号。",
    claudeUnknown: "无法检查 Claude Code 登录，请检查 CLI 版本与主机权限后刷新。",
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
      cli_missing: "未找到 CLI",
      wrong_auth: "需订阅登录",
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
    intro:
      "使用设备码登录 ChatGPT。",
    open: "在新标签页打开验证网址",
    code: "输入下面的设备码",
    confirm: "在 OpenAI 页面确认授权，完成后这里会自动更新。",
    copyUrl: "复制网址",
    copyCode: "复制",
    copiedShort: "已复制",
    copied: "已复制，请在浏览器新标签页中继续。",
    copyFailed: "复制失败，请手动选择并复制。",
    start: "开始登录",
    restart: "重新登录",
    cancel: "取消登录",
    cancelled: "已取消登录。",
    waiting: "等待授权",
    retrying: "连接暂时中断，正在重试",
    success: "Provider 已保存。请在 AstrBot 模型配置中选择此来源。",
    failedLogin: "登录失败。",
    expired: "设备码已过期，请重新开始登录。",
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
const instructions = byId("instructions");
const loginIntro = byId("login-intro");
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
  max: "Max",
  team: "Team",
  business: "Business",
  enterprise: "Enterprise",
  edu: "Edu",
};
const codexIcon =
  '<img class="codex-icon-light" src="./icons/codex-color.svg" alt="" width="34" height="34">' +
  '<img class="codex-icon-dark" src="./icons/codex-color-dark.svg" alt="" width="34" height="34">';
const providerIcons = {
  // Claude mark: LobeHub Icons (MIT); see THIRD_PARTY_NOTICES.md.
  claude:
    '<svg fill="currentColor" fill-rule="evenodd" height="1em" style="flex:none;line-height:1" viewBox="0 0 24 24" width="1em" xmlns="http://www.w3.org/2000/svg"><title>Claude</title><path d="M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z"></path></svg>',
  local_codex: codexIcon,
  device_oauth: '<span class="openai-icon"></span>',
};
const chevronIcon = '<svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>';
// Rows persist across refreshes and are updated in place, so the detail
// editor (and a name being typed in it) is never detached by a re-render.
const rowNodes = new Map();
const maxConsecutivePollFailures = 5;
const warningStates = ["cooling", "degraded"];
const dangerStates = ["reauth_required", "invalid", "cli_missing", "wrong_auth"];
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
let startLabel = "start";
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
    "provider-help": t.providerHelp,
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
    privacy: t.privacy,
    "login-intro": t.intro,
    "open-label": t.open,
    "code-label": t.code,
    "confirm-label": t.confirm,
    "copy-url": t.copyUrl,
    "copy-code": t.copyCode,
    cancel: t.cancel,
    start: t[startLabel],
  }))
    byId(id).textContent = value;
  closeButton.setAttribute("aria-label", t.close);
  usageButton.setAttribute("aria-label", t.refresh);
  usageButton.setAttribute("title", t.refresh);
  byId("updated").setAttribute("title", t.automatic);
}

applyLocale(context?.locale || bridge.getLocale());

function setStartLabel(key) {
  startLabel = key;
  startButton.textContent = t[key];
}

function setStatus(message, busy = false) {
  status.textContent = message;
  statusDots.hidden = !busy;
  error.hidden = true;
}

function showInstructions(visible) {
  instructions.hidden = !visible;
  loginIntro.hidden = visible;
  // The name only matters before a session starts.
  byId("login-name-field").hidden = visible || Boolean(loginSourceId);
}

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

function finishSession() {
  activeSessionId = null;
  byId("login-name").disabled = false;
  cancelButton.hidden = true;
  startButton.hidden = false;
}

function showError(message, terminal = true) {
  clearPollTimer();
  setStatus("");
  error.hidden = false;
  error.textContent = message || t.failedLogin;
  startButton.disabled = false;
  startButton.hidden = false;
  setStartLabel("restart");
  if (terminal) {
    finishSession();
  }
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

  const claude = account.credential_mode === "local_claude";
  const local = claude || account.credential_mode === "local_codex";
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
  byId("routing-row").hidden = account.credential_mode === "local_claude";
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
  if (provider.credential_mode === "local_claude" && provider.name === "Local Claude") return t.claudeLocal;
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
    const claude = provider.credential_mode === "local_claude";
    const local = claude || provider.credential_mode === "local_codex";
    const iconMode = claude ? "claude" : local ? "local_codex" : "device_oauth";
    if (node.iconMode !== iconMode) {
      node.iconMode = iconMode;
      node.icon.className = "provider-icon " + iconMode;
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
    node.toggle.disabled = busy || claude;
    node.toggle.hidden = claude;
    const plan = plans[provider.plan_type];
    node.sub.textContent = provider.email || (claude ? t.claudeShort : local ? t.localShort : t.deviceShort);
    const healthy = state === "ready";
    node.metaText.textContent =
      healthy && plan ? `${claude ? "Claude" : "ChatGPT"} ${plan}` : t.states[state] || t.states.unknown;
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
      const list = await bridge.apiPost("providers/list", {});
      if (generation !== viewGeneration) return;
      if (!Array.isArray(list?.providers)) throw new Error(t.listFailed);
      providers = list.providers.map((p) => keepNewerEdits(p, since));
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
      if (latest.credential_mode === "local_claude") {
        const message = {ready: "claudeReady", not_logged_in: "claudeMissing", cli_missing: "claudeCliMissing", wrong_auth: "claudeWrongAuth"}[latest.status] || "claudeUnknown";
        clearUsage(message);
        lastUpdated = new Date();
        renderUpdated();
        return;
      }
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
    const list = await bridge.apiPost("providers/list", {});
    if (generation !== viewGeneration) return;
    if (!Array.isArray(list?.providers)) return;
    providers = list.providers.map((p) => keepNewerEdits(p, since));
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
  if (!provider || provider.credential_mode === "local_claude" || isSaving(sourceId)) return;
  await saveProvider(sourceId, { enabled: !isEnabled(effective(provider)) });
}

async function setRoutingMode(mode) {
  const sourceId = selectedSourceId;
  if (!sourceId || account.credential_mode === "local_claude" || isSaving(sourceId)) return;
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
}

bridge.onContext?.((next) => {
  const locale = next?.locale;
  if (!locale || String(locale).startsWith("en") === isEnglish) return;
  applyLocale(locale);
  rerender();
});

function finishSuccess(sourceId) {
  clearPollTimer();
  finishSession();
  setStatus(t.success);
  startButton.disabled = false;
  setStartLabel("restart");
  showInstructions(false);
  verifyUrl.value = "";
  userCode.value = "";
  startButton.hidden = true;
  byId("login-name").disabled = false;
  void openProvider(sourceId || selectedSourceId);
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
    if (result.status === "timeout") {
      showError(t.expired);
      return;
    }
    if (result.status === "error") {
      showError(result.error || t.failedLogin);
      return;
    }
    setStatus(t.waiting, true);
    schedulePoll(sessionId, intervalSeconds);
  } catch (reason) {
    if (activeSessionId !== sessionId || cancelling) return;
    consecutivePollFailures += 1;
    if (consecutivePollFailures >= maxConsecutivePollFailures) {
      showError(reason?.message || t.failedLogin, false);
      return;
    }
    setStatus(t.retrying, true);
    schedulePoll(sessionId, intervalSeconds);
  }
}

async function startLogin() {
  if (activeSessionId) {
    await cancelLogin();
    if (activeSessionId) return;
  }
  closeButton.disabled = true;
  clearPollTimer();
  consecutivePollFailures = 0;
  startButton.disabled = true;
  setStartLabel("start");
  error.hidden = true;
  showInstructions(false);
  copyStatus.textContent = "";
  setStatus(t.waiting, true);

  try {
    byId("login-name").disabled = true;
    const result = await bridge.apiPost("device/start", loginSourceId
      ? { source_id: loginSourceId }
      : { name: byId("login-name").value.trim() });
    if (result.status !== "pending") {
      throw new Error(result.message || t.failedLogin);
    }
    activeSessionId = result.session_id;
    startButton.hidden = true;
    startButton.disabled = false;
    cancelButton.hidden = false;
    showInstructions(true);
    verifyUrl.value = result.verify_url;
    userCode.value = result.user_code;
    setStatus(t.waiting, true);
    closeButton.disabled = false;
    await poll(result.session_id, Math.max(2, Number(result.interval) || 5));
  } catch (reason) {
    showError(reason?.message || t.failedLogin, false);
  } finally {
    closeButton.disabled = false;
    if (!activeSessionId) byId("login-name").disabled = false;
  }
}

async function cancelLogin() {
  if (!activeSessionId) {
    return;
  }
  cancelling = true;
  cancelButton.disabled = true;
  try {
    await bridge.apiPost("device/cancel", { session_id: activeSessionId });
    clearPollTimer();
    finishSession();
    showInstructions(false);
    setStatus(t.cancelled);
    startButton.disabled = false;
    setStartLabel("restart");
  } catch (reason) {
    if (!activeSessionId) return;
    showError(reason?.message || t.failedLogin, false);
    schedulePoll(activeSessionId, 2);
  } finally {
    cancelButton.disabled = false;
    cancelling = false;
  }
}

async function copyField(field, button) {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(field.value);
    } else {
      field.focus();
      field.select();
      field.setSelectionRange(0, field.value.length);
      if (!document.execCommand("copy")) {
        throw new Error("Copy command was rejected.");
      }
    }
    copyStatus.textContent = t.copied;
    const label = button === copyUrlButton ? "copyUrl" : "copyCode";
    button.textContent = t.copiedShort;
    window.setTimeout(() => {
      button.textContent = t[label];
    }, 1600);
  } catch {
    field.focus();
    field.select();
    copyStatus.textContent = t.copyFailed;
  }
}

function openLogin(sourceId = null) {
  loginSourceId = sourceId;
  byId("instructions-title").textContent = sourceId ? t.renew : t.add;
  byId("login-name").value = sourceId ? account.name : "ChatGPT";
  byId("login-name").hidden = Boolean(sourceId);
  byId("login-name-label").hidden = Boolean(sourceId);
  byId("login-name-field").hidden = Boolean(sourceId);
  if (!activeSessionId) {
    showInstructions(false);
    setStatus("");
    setStartLabel("start");
    startButton.hidden = false;
    byId("login-name").disabled = false;
  }
  loginDialog.showModal();
}

startButton.addEventListener("click", () => void startLogin());
cancelButton.addEventListener("click", () => void cancelLogin());
usageButton.addEventListener("click", () => void queryUsage());
copyUrlButton.addEventListener(
  "click",
  () => void copyField(verifyUrl, copyUrlButton),
);
copyCodeButton.addEventListener(
  "click",
  () => void copyField(userCode, copyCodeButton),
);
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
  if (activeSessionId) await cancelLogin();
  if (!activeSessionId) loginDialog.close();
}
closeButton.addEventListener("click", () => void closeLogin());
loginDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  void closeLogin();
});
window.setInterval(() => {
  if (!document.hidden && !loginDialog.open) void queryUsage();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void queryUsage();
});
void queryUsage();
