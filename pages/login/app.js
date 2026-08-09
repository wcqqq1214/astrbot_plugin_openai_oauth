const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();

const isEnglish = String(context?.locale || bridge.getLocale()).startsWith("en");
const text = isEnglish
  ? {
      title: "OpenAI subscription login",
      intro: "Authorize with a ChatGPT device code. Credentials stay on the AstrBot server.",
      warning:
        "This Dashboard is using plain HTTP. The Dashboard session may be intercepted; HTTPS, a VPN, or an SSH tunnel is recommended.",
      start: "Start login",
      restart: "Try again",
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
    }
  : {
      title: "OpenAI 订阅登录",
      intro: "使用 ChatGPT 设备码完成授权，凭据会由 AstrBot 服务端保存。",
      warning:
        "当前 Dashboard 使用明文 HTTP，会话可能被网络窃听；建议为整个 Dashboard 使用 HTTPS、VPN 或 SSH 隧道。",
      start: "开始登录",
      restart: "重新登录",
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
    };

const byId = (id) => document.getElementById(id);
const startButton = byId("start");
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
let consecutivePollFailures = 0;

document.documentElement.lang = isEnglish ? "en" : "zh-CN";
document.title = text.title;
byId("title").textContent = text.title;
byId("intro").textContent = text.intro;
byId("instructions-title").textContent = text.instructions;
byId("open-label").textContent = text.open;
byId("code-label").textContent = text.code;
copyUrlButton.textContent = text.copyUrl;
copyCodeButton.textContent = text.copyCode;
startButton.textContent = text.start;

if (window.location.protocol === "http:") {
  const warning = byId("transport-warning");
  warning.hidden = false;
  warning.querySelector("span").textContent = text.warning;
}

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

function showError(message) {
  clearPollTimer();
  status.textContent = "";
  error.hidden = false;
  error.textContent = message || text.failed;
  startButton.disabled = false;
  startButton.textContent = text.restart;
}

function finishSuccess() {
  clearPollTimer();
  setStatus(text.success);
  startButton.disabled = false;
  startButton.textContent = text.restart;
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
      showError(reason?.message || text.failed);
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
    instructions.hidden = false;
    verifyUrl.value = result.verify_url;
    userCode.value = result.user_code;
    setStatus(text.waiting);
    await poll(result.session_id, Math.max(2, Number(result.interval) || 5));
  } catch (reason) {
    showError(reason?.message || text.failed);
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
copyUrlButton.addEventListener("click", () => void copyField(verifyUrl));
copyCodeButton.addEventListener("click", () => void copyField(userCode));
