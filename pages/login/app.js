const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();

const isEnglish = String(context?.locale || bridge.getLocale()).startsWith(
  "en",
);
const text = isEnglish
  ? {
      title: "Subscription & account",
      intro:
        "The plugin follows local Codex by default. Device login saves a backup account; disable local following in plugin settings to use it exclusively.",
      localSource: "Using the current local Codex account.",
      pluginSource: "Using the account saved by this plugin.",
      accountTitle: "Account status",
      checkUsage: "Refresh status",
      checkingUsage: "Checking quota…",
      start: "Start login",
      restart: "Log in again",
      cancel: "Cancel login",
      cancelled: "Login was cancelled.",
      instructions: "Complete authorization",
      open: "Copy the verification URL and open it in a new tab:",
      code: "Enter device code:",
      copyUrl: "Copy URL",
      copyCode: "Copy code",
      copied: "Copied. Open a new browser tab to continue.",
      copyFailed: "Copy failed. Select the value and copy it manually.",
      waiting: "Waiting for authorization…",
      retrying: "Connection interrupted. Retrying…",
      success:
        "Backup login saved. Local Codex still takes priority while local following is enabled.",
      failed: "Login failed.",
      expired: "The device code expired. Please start again.",
      states: {
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
      usageUnavailable: "Quota details are unavailable.",
      quotaTitle: "OpenAI subscription quota:",
      noWindows: "No quota windows were returned.",
      limitReached: "Status: quota limit reached.",
      unavailable: "Status: currently unavailable.",
      window: "window",
      remaining: "remaining",
      reset: "resets",
    }
  : {
      title: "订阅与账号",
      intro:
        "默认跟随本地 Codex 账号。设备码登录用于保存备用账号；在插件设置中关闭本地跟随后，可仅使用备用账号。",
      localSource: "当前使用本地 Codex 激活的账号。",
      pluginSource: "当前使用插件保存的账号。",
      accountTitle: "账号状态",
      checkUsage: "刷新状态",
      checkingUsage: "正在查询额度……",
      start: "开始登录",
      restart: "重新登录",
      cancel: "取消登录",
      cancelled: "已取消登录。",
      instructions: "完成授权",
      open: "复制验证网址并在新标签页打开：",
      code: "输入设备码：",
      copyUrl: "复制网址",
      copyCode: "复制设备码",
      copied: "已复制，请在浏览器新标签页中继续。",
      copyFailed: "复制失败，请手动选择并复制。",
      waiting: "等待授权……",
      retrying: "连接暂时中断，正在重试……",
      success: "备用账号已保存。启用本地跟随时，仍会优先使用本地 Codex 账号。",
      failed: "登录失败。",
      expired: "设备码已过期，请重新开始登录。",
      states: {
        ready: "已登录，可以使用。",
        refreshing: "正在刷新凭据……",
        cooling: "订阅额度当前处于冷却状态。",
        degraded: "当前凭据仍可使用，但刷新需要留意。",
        reauth_required: "请重新登录以更新 OpenAI 凭据。",
        not_logged_in: "尚未登录。",
        invalid: "已保存的凭据格式不受支持，请升级插件后重新登录。",
        unknown: "账号状态暂不可用。",
      },
      usageUnavailable: "额度详情暂不可用。",
      quotaTitle: "OpenAI 订阅额度：",
      noWindows: "当前账号暂无可用额度窗口。",
      limitReached: "状态：已达额度上限。",
      unavailable: "状态：当前不可用。",
      window: "窗口",
      remaining: "剩余",
      reset: "重置",
    };

const ui = isEnglish
  ? {
      intro: "Your active account, sign-in health and remaining allowance.",
      local: "Local Codex",
      plugin: "Plugin Page account",
      none: "No connected account",
      follow: "Automatically follows the active account",
      savedSource: "Using the saved plugin login",
      backup: "Backup login",
      add: "Add backup login →",
      renew: "Authorize again →",
      saved: "Saved",
      missing: "Not added",
      invalid: "Needs attention",
      active: "In use",
      backupCopy:
        "Save a device login as backup. Local Codex retains priority when enabled.",
      activeCopy: "This saved account is currently used for model requests.",
      sourceTitle: "Current source",
      fallbackTitle: "How backup login works",
      localHelp:
        "Following Codex on the AstrBot host. Account changes take effect on the next request.",
      pluginHelp:
        "Using the saved Plugin Page account. Enable local following in plugin settings to prioritize Codex.",
      noHelp: "Sign in to Codex on the AstrBot host, or add a backup login.",
      fallbackHelp:
        "A backup is used when local credentials are unavailable. Quota exhaustion does not switch accounts. Disable local following to use the backup explicitly.",
      privacy: "Credentials stay on the server and are never displayed here.",
      updated: "Updated",
      automatic: "Refreshes every 30 seconds while visible",
      loading: "Loading allowance…",
      noWindows:
        "No quota windows returned. This does not mean unlimited usage.",
      failed:
        "Quota is temporarily unavailable. Sign-in status is shown separately.",
      changed: "Account changed. Refreshing its allowance…",
      unknown: "Unavailable",
      fiveHour: "5-hour allowance",
      week: "Weekly allowance",
      month: "30-day allowance",
      hours: "hours",
      proWeekly:
        "Pro · Only the weekly allowance window is currently returned; no separate 5-hour window.",
      weeklyOnly:
        "Showing the returned weekly window. Missing windows do not imply unlimited usage.",
      exhausted:
        "Allowance limit reached. See the window reset time; the account will not switch automatically.",
      denied: "The service reports this allowance is currently unavailable.",
      close: "Close",
      waitBridge: "Waiting for the AstrBot connection…",
    }
  : {
      intro: "当前账号来源、登录状态与剩余额度，一眼看清。",
      local: "本地 Codex",
      plugin: "Plugin Page 账号",
      none: "尚未连接账号",
      follow: "自动跟随当前激活账号",
      savedSource: "使用插件保存的登录凭据",
      backup: "备用登录",
      add: "添加备用登录 →",
      renew: "重新授权 →",
      saved: "已保存",
      missing: "未添加",
      invalid: "需要处理",
      active: "当前使用",
      backupCopy:
        "通过设备码授权保存备用账号。启用本地跟随时，Codex 仍然优先。",
      activeCopy: "这个账号正在用于模型请求，可重新授权以更新登录。",
      sourceTitle: "当前来源",
      fallbackTitle: "备用账号如何使用",
      localHelp:
        "正在跟随 AstrBot 所在机器的 Codex。切换账号后，下次请求自动生效。",
      pluginHelp:
        "正在使用 Plugin Page 保存的账号。可在插件设置中开启本地跟随，优先使用 Codex。",
      noHelp: "先在 AstrBot 所在机器登录 Codex，或添加备用登录。",
      fallbackHelp:
        "本地凭据不可用时使用备用登录。额度耗尽不会自动换号；如需手动启用备用账号，可关闭本地跟随。",
      privacy: "登录凭据仅由服务端处理，不会在此页面展示。",
      updated: "最近更新",
      automatic: "页面可见时每 30 秒更新",
      loading: "正在查询额度…",
      noWindows: "账号尚未返回额度窗口，暂无数据不代表无限额度。",
      failed: "暂时无法获取额度，登录状态单独显示。",
      changed: "账号已切换，正在更新额度…",
      unknown: "暂不可用",
      fiveHour: "5 小时额度",
      week: "每周额度",
      month: "30 天额度",
      hours: "小时",
      proWeekly: "Pro · 当前仅返回每周额度，没有独立的 5 小时窗口。",
      weeklyOnly: "仅显示已返回的每周窗口；未返回不代表无限额。",
      exhausted:
        "已达到额度上限，请查看窗口重置时间。当前不会自动切换到备用账号。",
      denied: "服务端返回当前额度不可用。",
      close: "关闭",
      waitBridge: "正在连接 AstrBot…",
    };
const byId = (id) => document.getElementById(id);
const startButton = byId("start");
const cancelButton = byId("cancel");
const usageButton = byId("usage");
const accountStatus = byId("account-status");
const usageResult = byId("usage-result");
const instructions = byId("instructions");
const verifyUrl = byId("verify-url");
const userCode = byId("user-code");
const copyUrlButton = byId("copy-url");
const copyCodeButton = byId("copy-code");
const copyStatus = byId("copy-status");
const status = byId("status");
const error = byId("error");
const maxConsecutivePollFailures = 5;
let pollTimer = null;
let activeSessionId = null;
let consecutivePollFailures = 0;
let account = {};
let viewGeneration = 0;
let refreshPromise = null;
let cancelling = false;
const loginDialog = byId("login-dialog");
const closeButton = byId("close-login");

document.documentElement.lang = isEnglish ? "en" : "zh-CN";
document.title = text.title;
byId("title").textContent = text.title;
byId("intro").textContent = ui.intro;
byId("account-title").textContent = "OpenAI Subscribe";
for (const [id, value] of Object.entries({
  "backup-title": ui.backup,
  "source-title": ui.sourceTitle,
  "fallback-title": ui.fallbackTitle,
  "fallback-help": ui.fallbackHelp,
  privacy: ui.privacy,
  "login-intro": text.intro,
}))
  byId(id).textContent = value;
closeButton.setAttribute("aria-label", ui.close);
byId("instructions-title").textContent = text.instructions;
byId("open-label").textContent = text.open;
byId("code-label").textContent = text.code;
copyUrlButton.textContent = text.copyUrl;
copyCodeButton.textContent = text.copyCode;
usageButton.textContent = text.checkUsage;
startButton.textContent = text.start;
cancelButton.textContent = text.cancel;

function setStatus(message) {
  status.textContent = message;
  error.hidden = true;
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
}

function showError(message, terminal = true) {
  clearPollTimer();
  status.textContent = "";
  error.hidden = false;
  error.textContent = message || text.failed;
  startButton.disabled = false;
  startButton.textContent = text.restart;
  if (terminal) {
    finishSession();
  }
}

function formatReset(timestamp, after) {
  const seconds =
    typeof timestamp === "number" && Number.isFinite(timestamp) && timestamp > 0
      ? timestamp
      : typeof after === "number" && Number.isFinite(after) && after >= 0
      ? Date.now() / 1000 + after
      : null;
  if (seconds === null) return "";
  const date = new Date(seconds * 1000);
  if (!Number.isFinite(date.getTime())) return "";
  return `${date.toLocaleString(isEnglish ? "en-US" : "zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })} ${text.reset}`;
}

function renderAccountStatus(result) {
  account = result || {};
  const state = String(account.status || "unknown");
  accountStatus.textContent = text.states[state] || text.states.unknown;
  accountStatus.className =
    "badge " +
    (["cooling", "degraded", "reauth_required", "invalid"].includes(state)
      ? "warning"
      : state === "ready"
      ? ""
      : "neutral");
  const local = account.credential_source === "local_codex";
  const plugin = account.credential_source === "plugin";
  byId("source-name").textContent = local
    ? ui.local
    : plugin
    ? ui.plugin
    : ui.none;
  byId("source-caption").textContent = local
    ? ui.follow
    : plugin
    ? ui.savedSource
    : ui.noHelp;
  byId("source-help").textContent = local
    ? ui.localHelp
    : plugin
    ? ui.pluginHelp
    : ui.noHelp;
  byId("backup-copy").textContent = plugin ? ui.activeCopy : ui.backupCopy;
  byId("backup-status").textContent = plugin
    ? ui.active
    : account.backup_status === "saved"
    ? ui.saved
    : account.backup_status === "not_configured"
    ? ui.missing
    : ui.invalid;
  byId("open-login").textContent =
    account.backup_status === "saved" ? ui.renew : ui.add;
}

function windowLabel(seconds) {
  if (seconds === 18000) return ui.fiveHour;
  if (seconds === 604800) return ui.week;
  if (seconds === 2592000) return ui.month;
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0
    ? `${Number((seconds / 3600).toFixed(2))} ${ui.hours} ${text.window}`
    : text.window;
}

function element(tag, className, value) {
  const node = document.createElement(tag);
  node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function clearUsage(message) {
  usageResult.replaceChildren(element("p", "muted", message));
  byId("plan").hidden = true;
  byId("quota-policy").hidden = true;
  byId("notice").hidden = true;
}

function renderUsage(result) {
  if (result?.account) renderAccountStatus(result.account);
  if (result?.status !== "success" || !result.usage) {
    clearUsage(result?.status === "account_changed" ? ui.changed : ui.failed);
    if (["cooling", "reauth_required", "invalid"].includes(result?.status)) {
      renderAccountStatus({ ...account, status: result.status });
    }
    return;
  }
  const usage = result.usage;
  const windows = Array.isArray(usage.windows)
    ? usage.windows.filter((item) => item && typeof item === "object")
    : [];
  usageResult.replaceChildren();
  if (!windows.length) usageResult.append(element("p", "muted", ui.noWindows));
  for (const item of windows) {
    const valid =
      typeof item.used_percent === "number" &&
      Number.isFinite(item.used_percent);
    const remaining = valid
      ? Math.max(0, Math.min(100, 100 - item.used_percent))
      : null;
    const label = windowLabel(item.label_seconds);
    const card = element(
      "section",
      "quota" +
        (remaining !== null && remaining <= 15 ? " low" : "") +
        (remaining === 0 ? " exhausted" : ""),
    );
    card.append(element("div", "quota-title", label));
    const figure = element("div", "quota-figure");
    figure.append(
      element(
        "strong",
        "",
        remaining === null ? "—" : `${Math.round(remaining)}%`,
      ),
      element("small", "", remaining === null ? ui.unknown : text.remaining),
    );
    card.append(figure);
    if (remaining !== null) {
      const track = element("div", "track");
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-label", `${label} ${text.remaining}`);
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(remaining));
      const fill = element("div", "fill");
      fill.style.width = `${remaining}%`;
      track.append(fill);
      card.append(track);
    }
    card.append(
      element(
        "div",
        "reset",
        formatReset(item.reset_at, item.reset_after_seconds),
      ),
    );
    usageResult.append(card);
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
  byId("quota-policy").hidden = !weeklyOnly;
  byId("quota-policy").textContent =
    usage.plan_type === "pro" ? ui.proWeekly : ui.weeklyOnly;
  const notice = byId("notice");
  notice.hidden =
    !usage.limit_reached &&
    usage.allowed !== false &&
    account.status !== "cooling";
  notice.className = "notice warning";
  notice.textContent = usage.limit_reached
    ? ui.exhausted
    : account.status === "cooling"
    ? `${text.states.cooling} ${formatReset(account.cooldown_until)}`
    : ui.denied;
}

async function queryUsage() {
  if (refreshPromise) return refreshPromise;
  const generation = ++viewGeneration;
  refreshPromise = (async () => {
    usageButton.disabled = true;
    usageButton.textContent = text.checkingUsage;
    clearUsage(ui.loading);
    try {
      const latest = await bridge.apiPost("account/status", {});
      if (generation !== viewGeneration) return;
      renderAccountStatus(latest);
      if (["not_logged_in", "invalid"].includes(latest.status)) {
        clearUsage(ui.noHelp);
        return;
      }
      let result = await bridge.apiPost("account/usage", {});
      if (result?.status === "account_changed")
        result = await bridge.apiPost("account/usage", {});
      if (generation !== viewGeneration) return;
      renderUsage(result);
      byId("updated").textContent = `${
        ui.updated
      }: ${new Date().toLocaleTimeString(isEnglish ? "en-US" : "zh-CN", {
        hour12: isEnglish,
      })} · ${ui.automatic}`;
    } catch {
      if (generation === viewGeneration) clearUsage(ui.failed);
    } finally {
      usageButton.disabled = false;
      usageButton.textContent = text.checkUsage;
    }
  })();
  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

function finishSuccess() {
  clearPollTimer();
  finishSession();
  setStatus(text.success);
  startButton.disabled = false;
  startButton.textContent = text.restart;
  instructions.hidden = true;
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
      showError(text.expired);
      return;
    }
    if (result.status === "error") {
      showError(result.error || text.failed);
      return;
    }
    schedulePoll(sessionId, intervalSeconds);
  } catch (reason) {
    if (activeSessionId !== sessionId || cancelling) return;
    consecutivePollFailures += 1;
    if (consecutivePollFailures >= maxConsecutivePollFailures) {
      showError(reason?.message || text.failed, false);
      return;
    }
    setStatus(text.retrying);
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
  startButton.textContent = text.start;
  error.hidden = true;
  instructions.hidden = true;
  copyStatus.textContent = "";
  setStatus(text.waiting);

  try {
    const result = await bridge.apiPost("device/start", {});
    if (result.status !== "pending") {
      throw new Error(result.message || text.failed);
    }
    activeSessionId = result.session_id;
    cancelButton.hidden = false;
    instructions.hidden = false;
    verifyUrl.value = result.verify_url;
    userCode.value = result.user_code;
    setStatus(text.waiting);
    closeButton.disabled = false;
    await poll(result.session_id, Math.max(2, Number(result.interval) || 5));
  } catch (reason) {
    showError(reason?.message || text.failed, false);
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
    instructions.hidden = true;
    setStatus(text.cancelled);
    startButton.disabled = false;
    startButton.textContent = text.restart;
  } catch (reason) {
    showError(reason?.message || text.failed, false);
  } finally {
    cancelButton.disabled = false;
    cancelling = false;
  }
}

async function copyField(field) {
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
    copyStatus.textContent = text.copied;
  } catch {
    field.focus();
    field.select();
    copyStatus.textContent = text.copyFailed;
  }
}

startButton.addEventListener("click", () => void startLogin());
cancelButton.addEventListener("click", () => void cancelLogin());
usageButton.addEventListener("click", () => void queryUsage());
copyUrlButton.addEventListener("click", () => void copyField(verifyUrl));
copyCodeButton.addEventListener("click", () => void copyField(userCode));
byId("open-login").addEventListener("click", () => loginDialog.showModal());
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
