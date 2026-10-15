const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();

const strings = {
  en: {
    title: "Subscription & account",
    refresh: "Refresh status",
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
    plugin: "Saved plugin account",
    follow: "Follows the active Codex account on the AstrBot host",
    savedSource: "Uses the credential saved by device login",
    backup: "Backup login",
    deviceLogin: "Device login",
    add: "Add backup login",
    renew: "Authorize again",
    saved: "Saved",
    missing: "Not added",
    needsAction: "Needs attention",
    active: "In use",
    backupCopy:
      "Used when local Codex is unavailable. Local Codex keeps priority while local following is enabled.",
    activeCopy: "This saved account is currently used for model requests.",
    emptyTitle: "No OpenAI account connected",
    invalidTitle: "Sign in again",
    emptyCopy:
      "Sign in to Codex on the AstrBot host and it will be picked up automatically, or sign in here with a device code.",
    emptyAction: "Sign in with device code",
    helpTitle: "How account sources and backup login work",
    sourceTitle: "Current source",
    fallbackTitle: "Backup login",
    localHelp:
      "Following Codex on the AstrBot host. Account changes take effect on the next request.",
    pluginHelp:
      "Using the saved Plugin Page account. Enable local following in plugin settings to prioritize Codex.",
    noHelp: "Sign in to Codex on the AstrBot host, or add a backup login.",
    fallbackHelp:
      "A backup is used when local credentials are unavailable. Quota exhaustion does not switch accounts. Disable local following in plugin settings to use the backup explicitly.",
    privacy: "Credentials stay on the server and are never displayed here.",
    loading: "Loading allowance",
    noWindows:
      "No quota windows returned. This does not mean unlimited usage.",
    failed:
      "Quota is temporarily unavailable. Sign-in status is shown separately.",
    changed: "Account changed. Refreshing its allowance",
    unknown: "Unavailable",
    remaining: "left",
    usedUp: "used up",
    fiveHour: "5-hour allowance",
    week: "Weekly allowance",
    month: "30-day allowance",
    hours: "hours",
    window: "window",
    today: "Today",
    soon: "Resets soon",
    resetIn: (n, unit) =>
      `Resets in ${n} ${{ m: "min", h: n === 1 ? "hour" : "hours", d: n === 1 ? "day" : "days" }[unit]}`,
    proWeekly:
      "Pro · Only the weekly window is returned; there is no separate 5-hour window.",
    weeklyOnly:
      "Only the weekly window is returned. Missing windows do not imply unlimited usage.",
    exhausted:
      "Allowance limit reached. See the window reset time; the account will not switch automatically.",
    exhaustedUntil: (when) =>
      `Allowance limit reached. It recovers ${when}. The account will not switch automatically.`,
    coolingUntil: (when) =>
      `The subscription quota is cooling down until ${when}.`,
    denied: "The service reports this allowance is currently unavailable.",
    close: "Close",
    intro:
      "The plugin follows local Codex by default. Device login saves a backup account; disable local following in plugin settings to use it exclusively.",
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
      "Backup login saved. Local Codex still takes priority while local following is enabled.",
    failedLogin: "Login failed.",
    expired: "The device code expired. Please start again.",
  },
  zh: {
    title: "订阅与账号",
    refresh: "刷新状态",
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
    plugin: "插件保存的账号",
    follow: "自动跟随 AstrBot 主机上当前激活的 Codex 账号",
    savedSource: "使用设备码登录保存的凭据",
    backup: "备用登录",
    deviceLogin: "设备码登录",
    add: "添加备用登录",
    renew: "重新授权",
    saved: "已保存",
    missing: "未添加",
    needsAction: "需要处理",
    active: "当前使用",
    backupCopy: "本地 Codex 不可用时使用。启用本地跟随时，Codex 仍然优先。",
    activeCopy: "这个账号正在用于模型请求，可重新授权以更新登录。",
    emptyTitle: "尚未连接 OpenAI 账号",
    invalidTitle: "需要重新登录",
    emptyCopy:
      "在 AstrBot 所在机器上登录 Codex 后会自动识别；也可以在这里通过设备码登录。",
    emptyAction: "通过设备码登录",
    helpTitle: "账号来源与备用登录的工作方式",
    sourceTitle: "当前来源",
    fallbackTitle: "备用登录",
    localHelp:
      "正在跟随 AstrBot 所在机器的 Codex。切换账号后，下次请求自动生效。",
    pluginHelp:
      "正在使用 Plugin Page 保存的账号。可在插件设置中开启本地跟随，优先使用 Codex。",
    noHelp: "先在 AstrBot 所在机器登录 Codex，或添加备用登录。",
    fallbackHelp:
      "本地凭据不可用时使用备用登录。额度耗尽不会自动换号；如需手动启用备用账号，可在插件设置中关闭本地跟随。",
    privacy: "登录凭据仅由服务端处理，不会在此页面展示。",
    loading: "正在查询额度",
    noWindows: "账号尚未返回额度窗口，暂无数据不代表无限额度。",
    failed: "暂时无法获取额度，登录状态单独显示。",
    changed: "账号已切换，正在更新额度",
    unknown: "暂不可用",
    remaining: "剩余",
    usedUp: "已用尽",
    fiveHour: "5 小时额度",
    week: "每周额度",
    month: "30 天额度",
    hours: "小时",
    window: "窗口",
    today: "今天",
    soon: "即将重置",
    resetIn: (n, unit) =>
      `${n} ${{ m: "分钟", h: "小时", d: "天" }[unit]}后重置`,
    proWeekly: "Pro · 当前仅返回每周额度，没有独立的 5 小时窗口。",
    weeklyOnly: "仅显示已返回的每周窗口；未返回不代表无限额度。",
    exhausted:
      "已达到额度上限，请查看窗口重置时间。当前不会自动切换到备用账号。",
    exhaustedUntil: (when) =>
      `已达到额度上限，将于 ${when} 恢复。当前不会自动切换到备用账号。`,
    coolingUntil: (when) => `订阅额度冷却中，预计 ${when} 恢复。`,
    denied: "服务端返回当前额度不可用。",
    close: "关闭",
    intro:
      "默认跟随本地 Codex 账号。设备码登录用于保存备用账号；在插件设置中关闭本地跟随后，可仅使用备用账号。",
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
    success: "备用账号已保存。启用本地跟随时，仍会优先使用本地 Codex 账号。",
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

function applyLocale(locale) {
  isEnglish = String(locale || "zh-CN").startsWith("en");
  t = isEnglish ? strings.en : strings.zh;
  document.documentElement.lang = isEnglish ? "en" : "zh-CN";
  document.title = t.title;
  for (const [id, value] of Object.entries({
    title: t.title,
    "backup-title": t.backup,
    "empty-login": t.emptyAction,
    "help-title": t.helpTitle,
    "source-title": t.sourceTitle,
    "fallback-title": t.fallbackTitle,
    "fallback-help": t.fallbackHelp,
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

function renderAccountStatus(result) {
  account = result || {};
  const state = String(account.status || "unknown");
  accountStatus.textContent = t.states[state] || t.states.unknown;
  accountStatus.setAttribute("title", t.details[state] || t.details.unknown);
  accountStatus.className =
    "badge" +
    (warningStates.includes(state)
      ? " warning"
      : dangerStates.includes(state)
        ? " danger"
        : state === "ready"
          ? ""
          : " neutral");

  const signedOut = signedOutStates.includes(state);
  byId("account-view").hidden = signedOut;
  byId("empty-view").hidden = !signedOut;
  byId("empty-title").textContent =
    state === "invalid" ? t.invalidTitle : t.emptyTitle;
  byId("empty-copy").textContent =
    state === "invalid" ? t.details.invalid : t.emptyCopy;

  const local = account.credential_source === "local_codex";
  const plugin = account.credential_source === "plugin";
  byId("icon-local").hidden = plugin;
  byId("icon-plugin").hidden = !plugin;
  byId("source-name").textContent = local ? t.local : plugin ? t.plugin : "—";
  byId("source-caption").textContent = local
    ? t.follow
    : plugin
      ? t.savedSource
      : t.noHelp;
  byId("source-help").textContent = local
    ? t.localHelp
    : plugin
      ? t.pluginHelp
      : t.noHelp;

  // The backup row stays hidden until a real status arrives, so the first
  // paint never offers "add backup" for an account that already has one.
  byId("backup-row").hidden = !result;
  const backupStatus = byId("backup-status");
  byId("backup-copy").textContent = plugin ? t.activeCopy : t.backupCopy;
  backupStatus.textContent = plugin
    ? t.active
    : account.backup_status === "saved"
      ? t.saved
      : account.backup_status === "not_configured"
        ? t.missing
        : t.needsAction;
  backupStatus.className =
    "badge" +
    (plugin
      ? ""
      : ["saved", "not_configured"].includes(account.backup_status)
        ? " neutral"
        : " warning");
  byId("open-login").textContent =
    account.backup_status === "saved" || plugin ? t.renew : t.add;
  updateNotice();
}

function windowLabel(seconds) {
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

function quotaCard(item) {
  const remaining = remainingOf(item);
  const label = windowLabel(item.label_seconds);
  const card = element(
    "section",
    "quota" +
      (remaining === null
        ? " unknown"
        : remaining === 0
          ? " exhausted"
          : remaining <= 15
            ? " low"
            : ""),
  );
  const figure = element("div", "quota-figure");
  const value = element(
    "strong",
    "",
    remaining === null ? "—" : `${Math.round(remaining)}%`,
  );
  value.append(
    element(
      "small",
      "",
      remaining === null ? t.unknown : remaining === 0 ? t.usedUp : t.remaining,
    ),
  );
  figure.append(element("span", "quota-title", label), value);
  card.append(figure);
  const track = element("div", "track");
  if (remaining !== null) {
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", `${label} ${t.remaining}`);
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(remaining));
    const fill = element("div", "fill");
    fill.style.width = `${remaining}%`;
    track.append(fill);
  }
  card.append(track);
  const reset = resetSeconds(item.reset_at, item.reset_after_seconds);
  const resetRow = element("div", "reset");
  resetRow.append(
    element("span", "", formatRelative(reset)),
    element("span", "", formatAbsolute(reset)),
  );
  card.append(resetRow);
  return card;
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
    usageResult.replaceChildren(...windows.map(quotaCard));
  }
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
  const plan = plans[usage.plan_type];
  byId("plan").textContent = plan || "";
  byId("plan").hidden = !plan;
  const weeklyOnly =
    windows.length === 1 && windows[0].label_seconds === 604800;
  quotaPolicy.hidden = !weeklyOnly;
  quotaPolicy.textContent =
    usage.plan_type === "pro" ? t.proWeekly : t.weeklyOnly;
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
    message = resets.length
      ? t.exhaustedUntil(formatAbsolute(Math.max(...resets)))
      : t.exhausted;
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

async function queryUsage() {
  if (refreshPromise) return refreshPromise;
  const generation = ++viewGeneration;
  refreshPromise = (async () => {
    setRefreshing(true);
    // Only show a placeholder when there is nothing to keep on screen.
    if (!lastUsage) showUsageMessage("loading");
    try {
      const latest = await bridge.apiPost("account/status", {});
      if (generation !== viewGeneration) return;
      renderAccountStatus(latest);
      if (signedOutStates.includes(latest.status)) {
        clearUsage("noHelp");
        return;
      }
      if (lastUsage && shownRevision !== (latest.account_revision ?? null)) {
        clearUsage("changed");
      }
      let result = await bridge.apiPost("account/usage", {});
      if (result?.status === "account_changed")
        result = await bridge.apiPost("account/usage", {});
      if (generation !== viewGeneration) return;
      renderUsage(result);
      lastUpdated = new Date();
      renderUpdated();
    } catch {
      if (generation === viewGeneration) clearUsage("failed");
    } finally {
      setRefreshing(false);
    }
  })();
  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

function rerender() {
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

function finishSuccess() {
  clearPollTimer();
  finishSession();
  setStatus(t.success);
  startButton.disabled = false;
  setStartLabel("restart");
  showInstructions(false);
  verifyUrl.value = "";
  userCode.value = "";
  void queryUsage();
}

async function poll(sessionId, intervalSeconds) {
  try {
    const result = await bridge.apiPost("device/poll", {
      session_id: sessionId,
    });
    if (activeSessionId !== sessionId || cancelling) return;
    consecutivePollFailures = 0;
    if (result.status === "success") {
      finishSuccess();
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
    const result = await bridge.apiPost("device/start", {});
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
    showError(reason?.message || t.failedLogin, false);
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

function openLogin() {
  byId("instructions-title").textContent = signedOutStates.includes(
    account.status,
  )
    ? t.deviceLogin
    : t.backup;
  if (!activeSessionId) showInstructions(false);
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
byId("open-login").addEventListener("click", openLogin);
byId("empty-login").addEventListener("click", openLogin);
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
