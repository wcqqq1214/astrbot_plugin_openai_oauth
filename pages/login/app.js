const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();

const isEnglish = String(context?.locale || bridge.getLocale()).startsWith("en");
const text = isEnglish
  ? {
      title: "OpenAI subscription login",
      intro: "Authorize with a ChatGPT device code. Credentials stay on the AstrBot server.",
      accountTitle: "Account status",
      checkUsage: "Check quota",
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
      success: "Login succeeded. Credentials were saved on the server.",
      failed: "Login failed.",
      expired: "The device code expired. Please start again.",
      states: {
        ready: "Signed in and ready to use.",
        refreshing: "Refreshing credentials…",
        cooling: "The subscription quota is temporarily cooling down.",
        degraded: "The current credential is usable, but its refresh needs attention.",
        reauth_required: "Sign in again to renew the OpenAI credential.",
        not_logged_in: "Not signed in yet.",
        invalid: "The stored credential is unsupported. Update the plugin and sign in again.",
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
      title: "OpenAI 订阅登录",
      intro: "使用 ChatGPT 设备码完成授权，凭据会由 AstrBot 服务端保存。",
      accountTitle: "账号状态",
      checkUsage: "查询额度",
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
      success: "登录成功，凭据已由服务端保存。",
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

document.documentElement.lang = isEnglish ? "en" : "zh-CN";
document.title = text.title;
byId("title").textContent = text.title;
byId("intro").textContent = text.intro;
byId("account-title").textContent = text.accountTitle;
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

function formatReset(timestamp) {
  const value = Number(timestamp);
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }
  const date = new Date(value * 1000);
  if (isEnglish) {
    return ` · ${text.reset} ${date.toLocaleString()}`;
  }
  return ` · 将于 ${date.toLocaleString("zh-CN", { hour12: false })} 重置`;
}

function renderAccountStatus(result) {
  const accountState = String(result?.status || "unknown");
  const base = text.states[accountState] || text.states.unknown;
  accountStatus.textContent = `${base}${formatReset(result?.cooldown_until)}`;
}

function windowLabel(seconds) {
  const value = Number(seconds);
  if (value === 18000) {
    return isEnglish ? "5-hour window" : "5 小时窗口";
  }
  if (value === 604800) {
    return isEnglish ? "7-day window" : "7 天窗口";
  }
  if (value === 2592000) {
    return isEnglish ? "30-day window" : "30 天窗口";
  }
  return value > 0 ? `${Math.round(value / 3600)} ${text.window}` : text.window;
}

function renderUsage(result) {
  usageResult.hidden = false;
  if (result?.status === "cooling") {
    renderAccountStatus(result);
    usageResult.textContent = `${text.states.cooling}${formatReset(result.cooldown_until)}`;
    return;
  }
  if (result?.status !== "success" || !result.usage) {
    usageResult.textContent = text.usageUnavailable;
    return;
  }

  const usage = result.usage;
  const lines = [text.quotaTitle];
  const windows = Array.isArray(usage.windows) ? usage.windows : [];
  if (!windows.length) {
    lines.push(text.noWindows);
  }
  for (const item of windows) {
    const remaining = Math.max(0, 100 - Number(item.used_percent || 0));
    const resetAt = item.reset_at || (
      Number.isFinite(Number(item.reset_after_seconds))
        ? Math.floor(Date.now() / 1000) + Number(item.reset_after_seconds)
        : null
    );
    lines.push(
      `· ${windowLabel(item.label_seconds)}: ${text.remaining} ${Math.round(remaining)}%${formatReset(resetAt)}`,
    );
  }
  if (usage.limit_reached) {
    lines.push(text.limitReached);
  } else if (usage.allowed === false) {
    lines.push(text.unavailable);
  }
  usageResult.textContent = lines.join("\n");
}

async function loadAccountStatus() {
  try {
    renderAccountStatus(await bridge.apiPost("account/status", {}));
  } catch {
    renderAccountStatus({ status: "unknown" });
  }
}

async function queryUsage() {
  usageButton.disabled = true;
  usageButton.textContent = text.checkingUsage;
  try {
    renderUsage(await bridge.apiPost("account/usage", {}));
  } catch {
    usageResult.hidden = false;
    usageResult.textContent = text.usageUnavailable;
  } finally {
    usageButton.disabled = false;
    usageButton.textContent = text.checkUsage;
  }
}

function finishSuccess() {
  clearPollTimer();
  finishSession();
  setStatus(text.success);
  startButton.disabled = false;
  startButton.textContent = text.restart;
  void loadAccountStatus();
}

async function poll(sessionId, intervalSeconds) {
  try {
    const result = await bridge.apiPost("device/poll", { session_id: sessionId });
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
    await poll(result.session_id, Math.max(2, Number(result.interval) || 5));
  } catch (reason) {
    showError(reason?.message || text.failed, false);
  }
}

async function cancelLogin() {
  if (!activeSessionId) {
    return;
  }
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
void loadAccountStatus();
