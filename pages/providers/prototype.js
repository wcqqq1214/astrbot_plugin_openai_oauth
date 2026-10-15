// Offline preview of the production page. All accounts and quotas are examples.
const previewProviders = [
  {id: "local-codex", name: "Local Codex", credential_mode: "local_codex", status: "ready", email: "local@example.com", plan_type: "pro", account_revision: "local-one", enabled: true, routing_mode: "auto"},
  {id: "personal", name: "ChatGPT · 个人", credential_mode: "device_oauth", status: "ready", email: "personal@example.com", plan_type: "plus", account_revision: "personal-one", enabled: true, routing_mode: "fixed"},
  {id: "work", name: "ChatGPT · 工作", credential_mode: "device_oauth", status: "not_logged_in", enabled: false, routing_mode: "fixed"},
];
// `?fail=update` rejects every provider update, to preview the error path.
const failUpdates = new URLSearchParams(location.search).get("fail") === "update";
const previewSessions = new Map();
window.AstrBotPluginPage = {
  ready: async () => ({locale: "zh-CN"}),
  getLocale: () => "zh-CN",
  apiPost: async (endpoint, body) => {
    if (endpoint === "providers/list") return {providers: structuredClone(previewProviders)};
    const provider = previewProviders.find((p) => p.id === body.source_id);
    if (endpoint === "account/usage") return {
      status: "success", account: structuredClone(provider),
      usage: {plan_type: provider.plan_type, allowed: true, windows: [
        ...(provider.id === "local-codex" ? [] : [{label_seconds: 18000, used_percent: 28, reset_after_seconds: 3600}]),
        {label_seconds: 604800, used_percent: provider.id === "local-codex" ? 4 : 42, reset_after_seconds: 172800},
      ]},
    };
    if (endpoint === "providers/update") {
      // Mirror the server: partial updates with strict types, then the saved object.
      await new Promise((resolve) => setTimeout(resolve, 600));
      if (failUpdates) throw new Error("离线演示：模拟保存失败");
      if ("enabled" in body && typeof body.enabled !== "boolean") throw new Error("enabled must be a boolean.");
      if ("routing_mode" in body && !["fixed", "auto"].includes(body.routing_mode)) throw new Error("routing_mode must be fixed or auto.");
      for (const key of ["name", "enabled", "routing_mode"]) if (key in body) provider[key] = body[key];
      return {status: "success", provider: structuredClone(provider)};
    } else if (endpoint === "providers/delete") previewProviders.splice(previewProviders.indexOf(provider), 1);
    else if (endpoint === "device/start") {
      const id = "demo-" + Date.now();
      previewSessions.set(id, body);
      return {status: "pending", session_id: id, interval: 2, user_code: "DEMO-ONLY", verify_url: "离线演示，无需前往 OpenAI；数秒后模拟完成"};
    } else if (endpoint === "device/cancel") previewSessions.delete(body.session_id);
    else if (endpoint === "device/poll") {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      const target = previewSessions.get(body.session_id);
      if (!target) return {status: "cancelled"};
      const id = target.source_id || body.session_id;
      const existing = previewProviders.find((p) => p.id === id);
      if (existing) existing.status = "ready";
      else previewProviders.push({id, name: target.name, credential_mode: "device_oauth", status: "ready", account_revision: id, enabled: true, routing_mode: "fixed"});
      previewSessions.delete(body.session_id);
      return {status: "success", source_id: id};
    }
    return {status: "success"};
  },
};
document.addEventListener("DOMContentLoaded", () => {
  const banner = document.createElement("p");
  banner.textContent = "离线预览 · 全部为示例数据，登录操作仅模拟，不访问真实账号。";
  banner.className = "notice";
  document.querySelector("main").prepend(banner);
});
