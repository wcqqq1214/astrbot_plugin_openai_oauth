// Throwaway UI prototype. All account, quota and login data are simulated.
// Three structures share the same state; no credentials, network calls or persistence.
const paths = {
  terminal: '<path d="m5 7 5 5-5 5m8 0h6"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 11-2l3 7M4 12l3 7a7 7 0 0 0 11-2"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
  shield:
    '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  key: '<circle cx="8" cy="9" r="4"/><path d="m11 12 8 8m-3-3 3-3m-6 0 3-3"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  calendar:
    '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M8 3v4m8-4v4M4 11h16"/>',
  offline:
    '<path d="m3 3 18 18M8 6a10 10 0 0 1 13 4M3 10a10 10 0 0 1 2-2m3 6a6 6 0 0 1 8-1m-5 5h2"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
    paths[name] || paths.info
  }</svg>`;
const variants = { A: "分栏概览", B: "紧凑列表", C: "额度优先" };
const params = new URLSearchParams(location.search);
let variant = variants[params.get("variant")] ? params.get("variant") : "B";
let scenario = [
  "pro",
  "weekly_only",
  "weekly_cooling",
  "ready",
  "low",
  "cooling",
  "signedout",
  "backup",
  "error",
  "empty",
].includes(params.get("state"))
  ? params.get("state")
  : "pro";
let backupSaved = false;
let refreshedAt = "刚刚";
let refreshTimer;
let toastTimer;
let dark = params.get("theme") === "dark";
const app = document.getElementById("app");
const dialog = document.getElementById("login-dialog");

function state() {
  const values = {
    pro: {
      status: "ready",
      source: "local_codex",
      short: null,
      week: 64,
      plan: "Pro",
      fiveHourPolicy: "not_applicable",
    },
    weekly_only: {
      status: "ready",
      source: "local_codex",
      short: null,
      week: 64,
    },
    weekly_cooling: {
      status: "cooling",
      source: "local_codex",
      short: null,
      week: 0,
      plan: "Pro",
      fiveHourPolicy: "not_applicable",
    },
    ready: { status: "ready", source: "local_codex", short: 78, week: 64 },
    low: { status: "ready", source: "local_codex", short: 12, week: 36 },
    cooling: { status: "cooling", source: "local_codex", short: 0, week: 64 },
    signedout: {
      status: "not_logged_in",
      source: null,
      short: null,
      week: null,
    },
    backup: { status: "ready", source: "plugin", short: 92, week: 81 },
    error: { status: "ready", source: "local_codex", short: null, week: null },
    empty: { status: "ready", source: "local_codex", short: null, week: null },
  };
  return {
    ...values[scenario],
    backupSaved: backupSaved || scenario === "backup",
    quotaError: scenario === "error",
    noWindows: scenario === "empty",
    variant,
    updated: refreshedAt,
  };
}
function badge(s) {
  const value =
    s.status === "cooling"
      ? ["warning", "已登录 · 额度冷却"]
      : s.status === "not_logged_in"
      ? ["neutral", "尚未登录"]
      : ["", "已登录 · 可用"];
  return `<span class="badge ${value[0]}"><span class="dot"></span>${value[1]}</span>`;
}
const sourceTitle = (s) =>
  s.source === "local_codex"
    ? "本地 Codex"
    : s.source === "plugin"
    ? "Plugin Page 账号"
    : "尚未连接账号";
const sourceCaption = (s) =>
  s.source === "local_codex"
    ? "自动跟随当前激活账号"
    : s.source === "plugin"
    ? "使用插件保存的登录凭据"
    : "登录 Codex，或添加备用账号";
function accountName(s) {
  return `<div class="account-name"><div class="icon-box dark">${icon(
    s.source === "plugin" ? "key" : "terminal",
  )}</div><div><div class="source-name">${sourceTitle(
    s,
  )}</div><div class="source-caption">${sourceCaption(s)}</div>${
    s.plan ? `<span class="plan-tag">${s.plan}</span>` : ""
  }</div></div>`;
}
function notice(s) {
  if (s.status === "cooling")
    return `<div class="notice warning">${icon("clock")}<span>${
      s.week === 0
        ? "每周额度已用完，周日 16:00 重置。"
        : "5 小时额度已用完，约 2 小时 18 分后重置。"
    }当前不会自动切换到备用账号。</span></div>`;
  if (s.status === "not_logged_in")
    return `<div class="notice">${icon(
      "info",
    )}<span>先在 AstrBot 所在机器登录 Codex，或使用下方的备用登录。</span></div>`;
  if (s.quotaError)
    return `<div class="notice warning">${icon(
      "offline",
    )}<span>账号登录状态正常，但暂时无法查询额度。请稍后刷新。</span></div>`;
  if (s.short !== null && s.short <= 15)
    return `<div class="notice warning">${icon("info")}<span>5 小时额度仅剩 ${
      s.short
    }%。约 2 小时 18 分后重置。</span></div>`;
  return `<div class="notice">${icon("check")}<span>${
    s.source === "plugin"
      ? "当前使用备用账号。重新启用本地跟随后，将优先使用 Codex 账号。"
      : "本地切换账号后，下次请求自动跟随。"
  }</span></div>`;
}
function emptyQuota(s) {
  const title =
    s.status === "not_logged_in"
      ? "登录后查看额度"
      : s.quotaError
      ? "暂时无法获取额度"
      : "账号尚未返回额度窗口";
  const copy =
    s.status === "not_logged_in"
      ? "连接账号后，这里会显示可用额度与重置时间。"
      : s.quotaError
      ? "查询失败不代表额度为零，已登录状态保持不变。"
      : "暂无数据不等于没有额度，稍后可再次查询。";
  return `<div class="empty"><div class="icon-box">${icon(
    s.quotaError ? "offline" : "info",
  )}</div><h3>${title}</h3><p>${copy}</p>${
    s.status === "not_logged_in"
      ? '<button data-login class="primary">添加备用登录</button>'
      : `<button data-refresh>${icon("refresh")}重新查询</button>`
  }</div>`;
}
function quota(value, weekly = false, compact = false) {
  const name = weekly ? "每周额度" : "5 小时额度";
  const reset = weekly ? "周日 16:00 重置" : "2 小时 18 分后重置";
  const level = value === 0 ? "exhausted" : value <= 15 ? "low" : "";
  return `<section class="${
    compact ? "compact-quota" : "quota"
  } ${level}"><div class="quota-title">${icon(
    weekly ? "calendar" : "clock",
  )}${name}</div><div class="quota-figure"><strong>${value}<span>%</span></strong><small>剩余</small></div><div class="track" role="progressbar" aria-label="${name}剩余" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${value}"><div class="fill" style="--percent:${value}%"></div></div>${
    compact
      ? ""
      : `<div class="quota-footer"><span>已用 ${
          100 - value
        }%</span><span>剩余 ${value}%</span></div>`
  }<div class="reset">${icon("clock")}${reset}</div></section>`;
}
function hasQuota(s) {
  return s.short !== null || s.week !== null;
}
function quotaWindows(s, compact = false) {
  return (
    (s.short !== null ? quota(s.short, false, compact) : "") +
    (s.week !== null ? quota(s.week, true, compact) : "")
  );
}
function quotaPolicy(s) {
  if (s.fiveHourPolicy === "not_applicable")
    return `<div class="quota-policy">${icon(
      "info",
    )}<span>Pro 当前无 5 小时限额 · 仍受每周额度限制</span></div>`;
  if (s.short === null && s.week !== null)
    return `<div class="quota-policy">${icon(
      "info",
    )}<span>仅显示已返回的额度窗口；未返回不代表无限额。</span></div>`;
  return "";
}
function backup(s) {
  return `<section class="backup panel"><div class="icon-box">${icon(
    "key",
  )}</div><div class="backup-copy"><h3>备用登录 <span class="badge neutral backup-status">${
    s.backupSaved ? (s.source === "plugin" ? "当前使用" : "已保存") : "未添加"
  }</span></h3><p>${
    s.source === "plugin"
      ? "这个账号正在用于模型请求，可重新授权以更新登录。"
      : "通过设备码授权保存另一个账号，不会替换当前本地账号。"
  }</p></div><button data-login>${
    s.backupSaved ? "重新授权" : "添加备用登录"
  } ${icon("arrow")}</button></section>`;
}
function heading(s, compact = false) {
  return `<header class="page-heading"><div><div class="eyebrow">OpenAI subscription</div><h1>${
    compact ? "订阅与账号" : "OpenAI 账号中心"
  }</h1><p>账号从哪里来，还能用多少，一眼看清。</p></div><button data-refresh>${icon(
    "refresh",
  )}刷新状态</button></header>`;
}
function footnote() {
  return `<p class="footnote">${icon(
    "shield",
  )}登录凭据仅由服务端处理，不会在此页面展示。</p>`;
}
function VariantA(s) {
  return `${heading(
    s,
  )}<div class="layout-a"><section class="panel account-panel"><div class="section-top"><span class="small-label">当前账号来源</span>${badge(
    s,
  )}</div>${accountName(
    s,
  )}<div class="account-meta"><div class="meta-row"><span>来源</span><span>${
    s.source === "local_codex"
      ? "Codex 本地登录"
      : s.source === "plugin"
      ? "Plugin Page 授权"
      : "—"
  }</span></div><div class="meta-row"><span>跟随方式</span><span>${
    s.source === "local_codex"
      ? "自动跟随"
      : s.source === "plugin"
      ? "插件保存账号"
      : "等待登录"
  }</span></div></div><div class="divider"></div><h3>请求使用路径</h3><div class="route-line"><span class="route-node">AstrBot</span>${icon(
    "arrow",
  )}<span class="route-node active">${
    s.source === "plugin" ? "备用账号" : s.source ? "本地 Codex" : "待连接"
  }</span></div><p class="source-help">${
    s.source === "plugin"
      ? "可在插件设置中重新开启「跟随本地 Codex」。"
      : "读取 AstrBot 所在机器的登录状态。"
  }</p><div class="sync-line"><span class="dot"></span>状态更新于${
    s.updated
  }</div></section><section class="panel quota-panel"><div class="quota-header"><h2>订阅额度</h2><span class="small-label">显示剩余比例</span></div><div class="quota-grid">${
    hasQuota(s) ? quotaWindows(s) : emptyQuota(s)
  }</div>${quotaPolicy(s)}${notice(s)}</section>${backup(
    s,
  )}</div>${footnote()}`;
}
function VariantB(s) {
  return `<div class="layout-b">${heading(
    s,
    true,
  )}<div class="panel"><div class="list-toolbar"><h3>OpenAI Subscribe</h3>${badge(
    s,
  )}</div><div class="account-list-row ${
    s.short === null ? "single-window" : ""
  }">${accountName(s)}${
    hasQuota(s)
      ? quotaWindows(s, true)
      : '<div class="muted">额度暂不可用</div>'
  }</div>${quotaPolicy(s)}${backup(s)}<div class="list-note">最近更新：${
    s.updated
  } · 本地切换账号，下次请求生效</div></div>${
    !hasQuota(s) ? `<div style="margin-top:18px">${emptyQuota(s)}</div>` : ""
  }${notice(s)}<div class="list-info"><section><h3>当前来源</h3><p>${
    s.source === "local_codex"
      ? "正在跟随 AstrBot 所在机器的 Codex。无需在插件内重复登录。"
      : s.source === "plugin"
      ? "正在使用 Plugin Page 保存的账号。可以在插件设置中开启本地跟随。"
      : "未找到当前登录。登录本地 Codex 后刷新，或添加备用登录。"
  }</p></section><section><h3>备用账号如何使用</h3><p>本地凭据不可用时使用备用登录。额度耗尽不会自动换号；如需手动启用备用账号，可关闭本地跟随。</p></section></div>${footnote()}</div>`;
}
function VariantC(s) {
  const remaining = s.short;
  const title =
    s.status === "cooling"
      ? "稍作休息，等待重置"
      : s.status === "not_logged_in"
      ? "连接你的 Codex 账号"
      : s.quotaError
      ? "额度暂时不可见"
      : s.noWindows
      ? "等待额度信息"
      : s.short <= 15
      ? "接近本轮额度上限"
      : "可以继续你的对话";
  const ring =
    remaining === null
      ? hasQuota(s)
        ? `<div class="weekly-focus">${quotaWindows(s)}</div>`
        : emptyQuota(s)
      : `<div class="focus-body"><div class="ring" style="--percent:${remaining};--ring-color:${
          remaining <= 15 ? "var(--amber)" : "var(--green)"
        }"><div class="ring-inner"><strong>${remaining}<span>%</span></strong><small>5 小时额度剩余</small></div></div><div class="focus-copy"><div class="eyebrow">Your available quota</div><h2>${title}</h2><p>本轮已使用 ${
          100 - remaining
        }%。<br>${
          remaining === 0
            ? "额度重置后，即可重新使用。"
            : "使用当前账号的 Codex 订阅额度。"
        }</p><div class="reset">${icon(
          "clock",
        )}2 小时 18 分后重置</div></div></div><div class="week-strip"><div class="section-top"><span>每周额度</span><strong>剩余 ${
          s.week
        }% <span class="muted">/ 已用 ${
          100 - s.week
        }%</span></strong></div><div class="segments" role="img" aria-label="每周额度剩余 ${
          s.week
        }%">${Array.from(
          { length: 40 },
          (_, i) =>
            `<i class="${i < Math.round(s.week / 2.5) ? "filled" : ""}"></i>`,
        ).join("")}</div><div class="reset">${icon(
          "calendar",
        )}周日 16:00 重置</div></div>`;
  return `<div class="layout-c">${heading(
    s,
  )}<section class="panel focus-panel"><div class="focus-top">${accountName(
    s,
  )}${badge(s)}</div>${
    remaining === null ? '<div class="divider"></div>' : ""
  }${ring}${quotaPolicy(s)}${notice(
    s,
  )}<div class="sync-line"><span class="dot"></span>状态更新于${
    s.updated
  }</div></section>${backup(s)}${footnote()}</div>`;
}
function notes(s) {
  const safe = {
    prototype: true,
    variant,
    scenario,
    credential_source: s.source,
    status: s.status,
    remaining_percent: { five_hour: s.short, weekly: s.week },
    backup_saved: s.backupSaved,
    plan: s.plan ?? null,
    five_hour_policy: s.fiveHourPolicy ?? "unknown",
  };
  return `<details class="review-notes"><summary>原型说明与当前状态</summary><p>示例数据，不代表真实账号。备用授权只演示交互，不发起实际登录。</p><p>A 强调来源与额度分区；B 优先压缩信息密度；C 将短周期额度放在视觉中心。</p><pre>${JSON.stringify(
    safe,
    null,
    2,
  )}</pre></details>`;
}
function render() {
  const s = state();
  app.innerHTML =
    { A: VariantA, B: VariantB, C: VariantC }[variant](s) + notes(s);
  document.getElementById(
    "variant-name",
  ).textContent = `${variant} · ${variants[variant]}`;
  document.getElementById("scenario").value = scenario;
  document.documentElement.classList.toggle("dark", dark);
  app
    .querySelectorAll("[data-login]")
    .forEach((button) => button.addEventListener("click", openLogin));
  app.querySelectorAll("[data-refresh]").forEach((button) =>
    button.addEventListener("click", () => {
      app.querySelectorAll("[data-refresh]").forEach((b) => {
        b.disabled = true;
        b.innerHTML = icon("refresh") + "刷新中…";
      });
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => {
        refreshedAt = "刚刚";
        render();
        toast(
          scenario === "error"
            ? "演示：额度查询失败，登录状态保持不变。"
            : "示例状态已刷新。",
        );
      }, 650);
    }),
  );
}
function updateUrl() {
  const url = new URL(location.href);
  url.searchParams.set("variant", variant);
  url.searchParams.set("state", scenario);
  if (dark) url.searchParams.set("theme", "dark");
  else url.searchParams.delete("theme");
  history.replaceState(null, "", url);
}
function cycle(direction) {
  const keys = Object.keys(variants);
  variant =
    keys[(keys.indexOf(variant) + direction + keys.length) % keys.length];
  clearTimeout(refreshTimer);
  updateUrl();
  render();
  window.scrollTo({ top: 0, behavior: "instant" });
}
function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("visible"), 3200);
}
function openLogin() {
  dialog.innerHTML = `<div class="dialog-top"><h2 id="dialog-title">添加备用登录</h2><button data-close aria-label="关闭对话框">×</button></div><p class="dialog-copy">正式版本会引导你前往 OpenAI 验证页面，用设备码完成授权。</p><div class="device-code">DEMO-ONLY</div><div class="notice">${icon(
    "info",
  )}<span>这是演示设备码，请勿用于真实授权。</span></div><p class="dialog-note">授权后保存为备用账号，本地 Codex 仍然优先。</p><div class="dialog-actions"><button data-close>取消</button><button id="simulate-login" class="primary">模拟授权完成</button></div>`;
  dialog
    .querySelectorAll("[data-close]")
    .forEach((button) =>
      button.addEventListener("click", () => dialog.close()),
    );
  dialog.querySelector("#simulate-login").addEventListener("click", () => {
    backupSaved = true;
    if (scenario === "signedout") scenario = "backup";
    updateUrl();
    render();
    dialog.close();
    toast(
      scenario === "backup"
        ? "演示：已使用备用账号。"
        : "演示：备用账号已保存，本地账号仍优先。",
    );
  });
  dialog.showModal();
}
document.getElementById("previous").addEventListener("click", () => cycle(-1));
document.getElementById("next").addEventListener("click", () => cycle(1));
document.getElementById("scenario").addEventListener("change", (event) => {
  scenario = event.target.value;
  backupSaved = false;
  updateUrl();
  render();
});
document.getElementById("theme-toggle").addEventListener("click", () => {
  dark = !dark;
  updateUrl();
  render();
});
document.addEventListener("keydown", (event) => {
  if (
    dialog.open ||
    event.target.closest("input,textarea,select,button,[contenteditable]")
  )
    return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    cycle(event.key === "ArrowLeft" ? -1 : 1);
  }
});
updateUrl();
render();
