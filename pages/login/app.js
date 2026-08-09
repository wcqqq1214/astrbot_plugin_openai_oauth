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
      open: "Open verification URL:",
      code: "Enter device code:",
      waiting: "Waiting for authorization…",
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
      open: "打开验证网址：",
      code: "输入设备码：",
      waiting: "等待授权……",
      success: "登录成功，凭据已由服务端保存。",
      failed: "登录失败。",
      expired: "设备码已过期，请重新开始登录。",
    };

const $ = (id) => document.getElementById(id);
const startButton = $("start");
const instructions = $("instructions");
const verifyUrl = $("verify-url");
const userCode = $("user-code");
const status = $("status");
const error = $("error");
let pollTimer = null;

document.documentElement.lang = isEnglish ? "en" : "zh-CN";
document.title = text.title;
$("title").textContent = text.title;
$("intro").textContent = text.intro;
$("instructions-title").textContent = text.instructions;
$("open-label").textContent = text.open;
$("code-label").textContent = text.code;
startButton.textContent = text.start;

if (window.location.protocol === "http:") {
  const warning = $("transport-warning");
  warning.hidden = false;
  warning.querySelector("span").textContent = text.warning;
}

function setStatus(message) {
  status.textContent = message;
  error.hidden = true;
}

function showError(message) {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  status.textContent = "";
  error.hidden = false;
  error.textContent = message || text.failed;
  startButton.disabled = false;
  startButton.textContent = text.restart;
}

function finishSuccess() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  setStatus(text.success);
  startButton.disabled = false;
  startButton.textContent = text.restart;
}

async function poll(sessionId, intervalSeconds) {
  try {
    const result = await bridge.apiPost("device/poll", { session_id: sessionId });
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
    pollTimer = window.setTimeout(
      () => void poll(sessionId, intervalSeconds),
      intervalSeconds * 1000,
    );
  } catch (reason) {
    showError(reason?.message || text.failed);
  }
}

async function startLogin() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  startButton.disabled = true;
  startButton.textContent = text.start;
  error.hidden = true;
  instructions.hidden = true;
  setStatus(text.waiting);

  try {
    const result = await bridge.apiPost("device/start", {});
    if (result.status !== "pending") {
      throw new Error(result.message || text.failed);
    }
    instructions.hidden = false;
    verifyUrl.textContent = result.verify_url;
    verifyUrl.href = result.verify_url;
    userCode.textContent = result.user_code;
    setStatus(text.waiting);
    await poll(result.session_id, Math.max(2, Number(result.interval) || 5));
  } catch (reason) {
    showError(reason?.message || text.failed);
  }
}

startButton.addEventListener("click", () => void startLogin());
