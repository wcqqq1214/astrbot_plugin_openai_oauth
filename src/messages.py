"""Chat replies in the configured language or AstrBot's system locale.

When ``chat_language`` is ``"auto"``, handlers follow AstrBot's server-side
system locale via ``context.get_locale(umo)`` when available and fall back to
``DEFAULT_LANGUAGE``. The Plugin View follows the dashboard locale instead.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

AUTO_LANGUAGE = "auto"
DEFAULT_LANGUAGE = "zh-CN"
LANGUAGES = ("zh-CN", "en-US", "ru-RU", "ja-JP")
_PRIMARY_LANGUAGE_MAP = {
    "zh": "zh-CN",
    "en": "en-US",
    "ru": "ru-RU",
    "ja": "ja-JP",
}
_language = DEFAULT_LANGUAGE
_follow_system_locale = False
_session_language: ContextVar[str | None] = ContextVar(
    "openai_oauth_chat_language", default=None
)

_CATALOG: dict[str, dict[str, str]] = {
    "zh-CN": {
        "image.disabled": "请先在插件设置中开启 GPT Image 生图。",
        "image.prompt": "用法：/draw <提示词>",
        "image.edit_prompt": "请说明要修改的内容，最多 {limit} 个字符。可随消息附上原图，也可在 ChatUI 中继续编辑上一张图。",
        "image.reference_required": "请将一张参考图和修改要求放在同一条消息中发送。",
        "image.reference_unreadable": "无法读取参考图。请重新附上图片，并一起发送修改要求。",
        "image.no_account": "请先在当前对话中发送一条消息，再使用生图功能。",
        "image.account_restricted": "当前对话账号与指定的生图账号不一致。",
        "image.account_changed": "当前对话账号已变更或不可用，请先发送一条消息后再试。",
        "image.forbidden": "当前账号无生图权限。",
        "image.usage_limit": "当前账号额度已用尽，请等待重置后再试。",
        "image.rate_limit": "生图请求过于频繁，请稍后再试。",
        "image.timeout": "生图请求超时。",
        "image.failed": "图片生成失败。",
        "image.sent": "图片已发送给用户。",
        "usage.title": "OpenAI 订阅额度：",
        "usage.no_windows": "暂无额度数据。",
        "usage.remaining": "剩余 {percent}%",
        "usage.unavailable": "暂不可用",
        "usage.line": "· {label}：{remaining}{reset}",
        "usage.limit_reached": "状态：额度已用尽，等待重置。",
        "usage.not_allowed": "状态：当前不可用。",
        "usage.reset": "，重置 {when}",
        "usage.cooldown": "OpenAI 订阅额度冷却中{reset}。",
        "usage.reauth_required": "凭据已失效，请在插件详情页重新登录。",
        "usage.unsupported": "凭据格式不受支持，请升级插件后重新登录。",
        "usage.incompatible": "AstrBot 版本不兼容，账号操作已暂停，请查看启动日志。",
        "usage.invalid": "无法读取登录凭据，请在插件详情页重新登录。",
        "usage.failed": "额度查询失败，请稍后重试。",
        "usage.select_model": "请先选择 OpenAI Subscribe 模型。",
        "window.5h": "5小时窗口",
        "window.7d": "7天窗口",
        "window.30d": "30天窗口",
        "window.days": "{count}天窗口",
        "window.hours": "{count}小时窗口",
        "window.generic": "额度窗口",
        "effort.no_session": "当前会话不可用。",
        "effort.provider_unknown": "无法识别当前会话的模型。",
        "effort.not_subscribe": "当前会话未使用 OpenAI Subscribe 模型，无法设置思考强度。",
        "effort.override": "当前会话思考强度：{effort}。",
        "effort.model_default": "当前使用模型默认思考强度：{effort}。",
        "effort.unset": "当前使用模型默认思考强度。",
        "effort.help": "{message}\n可用值：{levels}\n用法：/effort <值> 或 /effort default",
        "effort.reset_failed": "恢复默认思考强度失败，请稍后重试。",
        "effort.reset": "已恢复默认思考强度。",
        "effort.unsupported": "不支持的思考强度：{value}\n可用值：{levels}（或 default）。",
        "effort.save_failed": "保存思考强度失败，请稍后重试。",
        "effort.saved": "当前会话思考强度已设为 {effort}。",
        "login.private_only": "/openai_login 仅限管理员私聊使用。",
        "login.in_progress": "已有登录正在进行，请先完成或发送 /openai_login cancel 取消。",
        "login.start_failed": "无法启动设备登录：{reason}",
        "login.start_unavailable": "无法启动设备登录，请稍后重试。",
        "login.instructions": (
            "打开链接并输入设备码完成授权：\n{url}\n"
            "设备码：{code}\n"
            "授权后将自动保存账号。"
        ),
        "login.expired": "设备码已过期，请重新发送 /openai_login。",
        "login.failed": "OpenAI 登录失败：{reason}",
        "login.cancelled": "已取消登录。",
        "login.saving": "已授权，正在保存账号，请稍候。",
        "login.nothing_to_cancel": "没有进行中的登录。",
        "login.usage": "用法：/openai_login 开始登录；/openai_login cancel 取消登录。",
        "login.save_failed": "登录失败，请重试。",
        "login.success": "登录成功，已添加账号 {name}（{id}）。",
        "device.device_login_disabled": "设备码登录未启用，请在 ChatGPT 安全设置中开启“为 Codex 启用设备代码授权”",
        "device.device_code_missing": "OpenAI 未返回设备码",
        "device.device_poll_failed": "查询授权状态失败",
        "device.login_failed": "登录失败",
        "stream.interrupted": "回复输出中断，请重试。",
        "search.sources": "来源：",
        "search.running": "搜索中",
        "search.completed": "搜索完成",
        "search.failed": "搜索失败",
        "search.interrupted": "搜索中断",
        "provider.disabled": "当前账号已停用，请在插件详情页启用或切换其他账号。",
        "provider.not_logged_in": "账号未登录，请先在插件详情页登录。",
        "provider.reauth_required": "登录凭据已失效，请在插件详情页重新登录。",
        "provider.local_reauth_required": "本地 Codex 未登录或已失效，请在 AstrBot 所在主机上登录 Codex，或改用设备码账号。",
        "provider.refresh_failed": "刷新登录凭据失败，请稍后重试。",
        "provider.save_failed": "无法保存刷新后的凭据，请检查配置目录写权限。",
        "provider.source_error": "当前账号配置已变更或不可用，请重试或在插件详情页检查账号状态。",
        "provider.no_response": "未收到完整回复，请重试。",
        "provider.routing_exhausted": "当前没有可用的 OpenAI 账号。",
        "provider.routing_timeout": "自动回退超时，暂无可用账号。",
        "provider.routing_attempt_limit": "已达自动回退重试上限，暂无可用账号。",
        "provider.routing_detail": "{summary}（{details}）",
        "provider.reason.disabled": "已停用",
        "provider.reason.cooling": "额度冷却中",
        "provider.reason.reauth_required": "需重新登录",
        "provider.reason.not_logged_in": "未登录",
        "provider.reason.invalid_credentials": "凭据无效",
        "provider.reason.temporary": "临时故障",
        "provider.reason.rate_limit": "请求受限",
        "provider.reason.duplicate_account": "重复账号",
        "provider.reason.attempt_limit": "达到重试上限",
    },
    "en-US": {
        "image.disabled": "Enable GPT Image generation in the plugin settings first.",
        "image.prompt": "Usage: /draw <prompt>",
        "image.edit_prompt": "Describe the changes in up to {limit} characters. Attach the original or, in ChatUI, refer to the image in the previous reply.",
        "image.reference_required": "Send one reference image and the requested changes together in the same message.",
        "image.reference_unreadable": "I couldn’t read the reference image. Please attach it again with your edit instructions.",
        "image.no_account": "Send a message in this conversation before using /draw.",
        "image.account_restricted": "Current chat account does not match the configured image account.",
        "image.account_changed": "The chat account changed or is unavailable. Send a message first, then try again.",
        "image.forbidden": "This account does not have image generation access.",
        "image.usage_limit": "Quota exhausted for this account. Try again after it resets.",
        "image.rate_limit": "Too many image requests. Try again shortly.",
        "image.timeout": "Image generation timed out.",
        "image.failed": "Failed to generate image.",
        "image.sent": "Image sent to the user.",
        "usage.title": "OpenAI subscription allowance:",
        "usage.no_windows": "No quota data available.",
        "usage.remaining": "{percent}% left",
        "usage.unavailable": "unavailable",
        "usage.line": "· {label}: {remaining}{reset}",
        "usage.limit_reached": "Status: allowance used up, waiting for reset.",
        "usage.not_allowed": "Status: currently unavailable.",
        "usage.reset": ", resets {when}",
        "usage.cooldown": "OpenAI subscription allowance is cooling down{reset}.",
        "usage.reauth_required": "Session expired. Sign in again on the plugin page.",
        "usage.unsupported": "Unsupported credential format. Update the plugin and sign in again.",
        "usage.incompatible": "Incompatible AstrBot version; account operations are paused. Check startup logs.",
        "usage.invalid": "Saved credentials could not be read. Sign in again on the plugin page.",
        "usage.failed": "Could not load quota. Try again later.",
        "usage.select_model": "Select an OpenAI Subscribe model first.",
        "window.5h": "5-hour window",
        "window.7d": "7-day window",
        "window.30d": "30-day window",
        "window.days": "{count}-day window",
        "window.hours": "{count}-hour window",
        "window.generic": "Allowance window",
        "effort.no_session": "This conversation is unavailable.",
        "effort.provider_unknown": "Could not identify the model for this conversation.",
        "effort.not_subscribe": "This conversation is not using an OpenAI Subscribe model.",
        "effort.override": "Reasoning effort for this conversation: {effort}.",
        "effort.model_default": "Using model default reasoning effort: {effort}.",
        "effort.unset": "Using model default reasoning effort.",
        "effort.help": "{message}\nAvailable: {levels}\nUsage: /effort <level> or /effort default",
        "effort.reset_failed": "Could not reset reasoning effort. Try again later.",
        "effort.reset": "Restored default reasoning effort.",
        "effort.unsupported": "Unsupported reasoning effort: {value}\nAvailable: {levels} (or default).",
        "effort.save_failed": "Could not save reasoning effort. Try again later.",
        "effort.saved": "Reasoning effort set to {effort}.",
        "login.private_only": "/openai_login can only be used in an admin private chat.",
        "login.in_progress": "A login is already in progress. Finish it or send /openai_login cancel.",
        "login.start_failed": "Could not start device login: {reason}",
        "login.start_unavailable": "Could not start device login. Try again later.",
        "login.instructions": (
            "Open this link and enter the device code to authorize:\n{url}\n"
            "Device code: {code}\n"
            "The account will be saved automatically once authorized."
        ),
        "login.expired": "Device code expired. Send /openai_login again.",
        "login.failed": "OpenAI login failed: {reason}",
        "login.cancelled": "Login cancelled.",
        "login.saving": "Authorized. Saving account, please wait.",
        "login.nothing_to_cancel": "No login in progress.",
        "login.usage": "Usage: /openai_login to start login; /openai_login cancel to cancel.",
        "login.save_failed": "Login failed. Try again.",
        "login.success": "Signed in and added account {name} ({id}).",
        "device.device_login_disabled": "device code login is off. Enable “device code authentication for Codex” in ChatGPT security settings",
        "device.device_code_missing": "OpenAI did not return a device code",
        "device.device_poll_failed": "could not check authorization status",
        "device.login_failed": "login failed",
        "stream.interrupted": "Reply interrupted. Please try again.",
        "search.sources": "Sources:",
        "search.running": "Searching",
        "search.completed": "Search complete",
        "search.failed": "Search failed",
        "search.interrupted": "Search interrupted",
        "provider.disabled": "This account is disabled. Enable it on the plugin page or switch accounts.",
        "provider.not_logged_in": "Account not signed in. Sign in on the plugin page first.",
        "provider.reauth_required": "Session expired. Sign in again on the plugin page.",
        "provider.local_reauth_required": "Local Codex login is missing or expired. Sign in to Codex on the AstrBot host or switch to a device-code account.",
        "provider.refresh_failed": "Could not refresh login credentials. Try again shortly.",
        "provider.save_failed": "Could not save refreshed credentials. Check write permissions for the config directory.",
        "provider.source_error": "The selected account changed or is unavailable. Try again or check the plugin page.",
        "provider.no_response": "Incomplete response from OpenAI. Try again.",
        "provider.routing_exhausted": "No configured OpenAI account is currently available.",
        "provider.routing_timeout": "Automatic fallback timed out with no available OpenAI account.",
        "provider.routing_attempt_limit": "Automatic fallback reached its retry limit with no available OpenAI account.",
        "provider.routing_detail": "{summary} ({details})",
        "provider.reason.disabled": "disabled",
        "provider.reason.cooling": "cooling down",
        "provider.reason.reauth_required": "sign-in expired",
        "provider.reason.not_logged_in": "not signed in",
        "provider.reason.invalid_credentials": "invalid login",
        "provider.reason.temporary": "temporary error",
        "provider.reason.rate_limit": "rate limited",
        "provider.reason.duplicate_account": "duplicate account",
        "provider.reason.attempt_limit": "attempt limit reached",
    },
    "ru-RU": {
        "image.disabled": "Сначала включите генерацию GPT Image в настройках плагина.",
        "image.prompt": "Использование: /draw <описание>",
        "image.edit_prompt": "Опишите изменения, используя не более {limit} символов. Прикрепите исходное изображение или укажите, что нужно изменить изображение из предыдущего ответа в ChatUI.",
        "image.reference_required": "Отправьте одно исходное изображение и описание изменений в одном сообщении.",
        "image.reference_unreadable": "Не удалось прочитать исходное изображение. Прикрепите его ещё раз вместе с описанием изменений.",
        "image.no_account": "Сначала отправьте сообщение в этом диалоге, затем используйте /draw.",
        "image.account_restricted": "Аккаунт диалога не совпадает с аккаунтом, указанным для генерации изображений.",
        "image.account_changed": "Аккаунт диалога изменился или недоступен. Сначала отправьте новое сообщение.",
        "image.forbidden": "У этого аккаунта нет доступа к генерации изображений.",
        "image.usage_limit": "Лимит аккаунта исчерпан. Повторите попытку после сброса.",
        "image.rate_limit": "Слишком много запросов на генерацию. Повторите попытку позже.",
        "image.timeout": "Время ожидания генерации истекло.",
        "image.failed": "Не удалось сгенерировать изображение.",
        "image.sent": "Изображение отправлено пользователю.",
        "usage.title": "Лимит подписки OpenAI:",
        "usage.no_windows": "Нет данных о лимите.",
        "usage.remaining": "осталось {percent}%",
        "usage.unavailable": "недоступно",
        "usage.line": "· {label}: {remaining}{reset}",
        "usage.limit_reached": "Статус: лимит исчерпан, ожидание сброса.",
        "usage.not_allowed": "Статус: сейчас недоступно.",
        "usage.reset": ", сброс {when}",
        "usage.cooldown": "Лимит подписки OpenAI восстанавливается{reset}.",
        "usage.reauth_required": "Сеанс истёк. Войдите снова на странице плагина.",
        "usage.unsupported": "Формат данных входа не поддерживается. Обновите плагин и войдите снова.",
        "usage.incompatible": "Несовместимая версия AstrBot; операции с аккаунтами приостановлены. Проверьте журнал запуска.",
        "usage.invalid": "Не удалось прочитать данные входа. Войдите снова на странице плагина.",
        "usage.failed": "Не удалось загрузить лимит. Повторите попытку позже.",
        "usage.select_model": "Сначала выберите модель OpenAI Subscribe.",
        "window.5h": "Окно 5 ч",
        "window.7d": "Окно 7 дн.",
        "window.30d": "Окно 30 дн.",
        "window.days": "Окно {count} дн.",
        "window.hours": "Окно {count} ч",
        "window.generic": "Окно лимита",
        "effort.no_session": "Этот диалог недоступен.",
        "effort.provider_unknown": "Не удалось определить модель диалога.",
        "effort.not_subscribe": "В этом диалоге не используется модель OpenAI Subscribe.",
        "effort.override": "Уровень рассуждений для диалога: {effort}.",
        "effort.model_default": "Используется уровень рассуждений модели по умолчанию: {effort}.",
        "effort.unset": "Используется уровень рассуждений модели по умолчанию.",
        "effort.help": "{message}\nДоступно: {levels}\nИспользование: /effort <уровень> или /effort default",
        "effort.reset_failed": "Не удалось сбросить уровень рассуждений. Повторите попытку позже.",
        "effort.reset": "Восстановлен уровень рассуждений по умолчанию.",
        "effort.unsupported": "Неподдерживаемый уровень рассуждений: {value}\nДоступно: {levels} (или default).",
        "effort.save_failed": "Не удалось сохранить уровень рассуждений. Повторите попытку позже.",
        "effort.saved": "Уровень рассуждений установлен на {effort}.",
        "login.private_only": "/openai_login доступен только в личном чате администратора.",
        "login.in_progress": "Вход уже выполняется. Завершите его или отправьте /openai_login cancel.",
        "login.start_failed": "Не удалось начать вход по коду устройства: {reason}",
        "login.start_unavailable": "Не удалось начать вход по коду устройства. Повторите попытку позже.",
        "login.instructions": (
            "Откройте ссылку и введите код устройства для авторизации:\n{url}\n"
            "Код устройства: {code}\n"
            "После авторизации аккаунт сохранится автоматически."
        ),
        "login.expired": "Код устройства истёк. Отправьте /openai_login снова.",
        "login.failed": "Не удалось войти в OpenAI: {reason}",
        "login.cancelled": "Вход отменён.",
        "login.saving": "Авторизация выполнена, сохраняем аккаунт.",
        "login.nothing_to_cancel": "Нет активного входа.",
        "login.usage": "Использование: /openai_login — начать вход; /openai_login cancel — отменить.",
        "login.save_failed": "Не удалось войти. Повторите попытку.",
        "login.success": "Вход выполнен, добавлен аккаунт {name} ({id}).",
        "device.device_login_disabled": "вход по коду устройства выключен. Включите «Enable device code authentication for Codex» в настройках безопасности ChatGPT",
        "device.device_code_missing": "OpenAI не вернул код устройства",
        "device.device_poll_failed": "не удалось проверить статус авторизации",
        "device.login_failed": "не удалось войти",
        "stream.interrupted": "Ответ прервался. Повторите попытку.",
        "search.sources": "Источники:",
        "search.running": "Поиск…",
        "search.completed": "Поиск завершён",
        "search.failed": "Ошибка поиска",
        "search.interrupted": "Поиск прерван",
        "provider.disabled": "Этот аккаунт отключён. Включите его на странице плагина или выберите другой.",
        "provider.not_logged_in": "Вход в аккаунт не выполнен. Сначала войдите на странице плагина.",
        "provider.reauth_required": "Сеанс входа истёк. Войдите снова на странице плагина.",
        "provider.local_reauth_required": "Локальный вход Codex отсутствует или истёк. Войдите в Codex на хосте AstrBot или выберите аккаунт с кодом устройства.",
        "provider.refresh_failed": "Не удалось обновить данные входа. Повторите попытку позже.",
        "provider.save_failed": "Не удалось сохранить обновлённые данные входа. Проверьте права на запись в каталог конфигурации.",
        "provider.source_error": "Выбранный аккаунт изменился или недоступен. Повторите запрос или проверьте страницу плагина.",
        "provider.no_response": "Получен неполный ответ. Повторите попытку.",
        "provider.routing_exhausted": "Нет доступных аккаунтов OpenAI.",
        "provider.routing_timeout": "Превышено время ожидания автоперехода: нет доступных аккаунтов.",
        "provider.routing_attempt_limit": "Достигнут лимит попыток автоперехода: нет доступных аккаунтов.",
        "provider.routing_detail": "{summary} ({details})",
        "provider.reason.disabled": "отключён",
        "provider.reason.cooling": "восстановление лимита",
        "provider.reason.reauth_required": "требуется повторный вход",
        "provider.reason.not_logged_in": "не выполнен вход",
        "provider.reason.invalid_credentials": "неверные данные входа",
        "provider.reason.temporary": "временная ошибка",
        "provider.reason.rate_limit": "ограничение частоты",
        "provider.reason.duplicate_account": "дубликат аккаунта",
        "provider.reason.attempt_limit": "лимит попыток",
    },
    "ja-JP": {
        "image.disabled": "先にプラグイン設定で GPT Image 画像生成を有効にしてください。",
        "image.prompt": "使い方: /draw <プロンプト>",
        "image.edit_prompt": "変更内容を{limit}文字以内で書いてください。元の画像を添付するか、ChatUI で直前の返信の画像を指定してください。",
        "image.reference_required": "参考画像を1枚添付し、変更内容と一緒に送信してください。",
        "image.reference_unreadable": "参考画像を読み込めませんでした。画像を添付し直し、変更内容と一緒に送信してください。",
        "image.no_account": "この会話で一度メッセージを送信してから /draw を使用してください。",
        "image.account_restricted": "現在のチャットアカウントが画像生成用の指定アカウントと一致しません。",
        "image.account_changed": "チャットのアカウントが変更されたか利用できません。先にメッセージを送信してください。",
        "image.forbidden": "このアカウントには画像生成の権限がありません。",
        "image.usage_limit": "このアカウントの利用枠を使い切りました。リセット後に再試行してください。",
        "image.rate_limit": "画像生成リクエストが多すぎます。しばらく待ってから再試行してください。",
        "image.timeout": "画像生成がタイムアウトしました。",
        "image.failed": "画像の生成に失敗しました。",
        "image.sent": "画像をユーザーに送信しました。",
        "usage.title": "OpenAI サブスクリプションの利用枠：",
        "usage.no_windows": "利用枠データがありません。",
        "usage.remaining": "残り {percent}%",
        "usage.unavailable": "取得不可",
        "usage.line": "・{label}：{remaining}{reset}",
        "usage.limit_reached": "状態：利用上限に達しました。リセット待ちです。",
        "usage.not_allowed": "状態：現在利用できません。",
        "usage.reset": "、{when} にリセット",
        "usage.cooldown": "OpenAI サブスクリプションの利用枠はクールダウン中です{reset}。",
        "usage.reauth_required": "セッションの有効期限が切れました。プラグインページで再ログインしてください。",
        "usage.unsupported": "認証情報の形式が未対応です。プラグインを更新して再ログインしてください。",
        "usage.incompatible": "AstrBot のバージョンに互換性がないため、アカウント操作を停止しました。起動ログを確認してください。",
        "usage.invalid": "ログイン情報を読み取れません。プラグインページで再ログインしてください。",
        "usage.failed": "利用枠を取得できませんでした。後で再試行してください。",
        "usage.select_model": "先に OpenAI Subscribe のモデルを選択してください。",
        "window.5h": "5時間枠",
        "window.7d": "7日間枠",
        "window.30d": "30日間枠",
        "window.days": "{count}日間枠",
        "window.hours": "{count}時間枠",
        "window.generic": "利用枠",
        "effort.no_session": "この会話は利用できません。",
        "effort.provider_unknown": "この会話のモデルを特定できませんでした。",
        "effort.not_subscribe": "この会話では OpenAI Subscribe モデルを使用していません。",
        "effort.override": "この会話の推論強度：{effort}。",
        "effort.model_default": "モデルの既定の推論強度を使用中：{effort}。",
        "effort.unset": "モデルの既定の推論強度を使用中です。",
        "effort.help": "{message}\n指定可能な値：{levels}\n使い方：/effort <値> または /effort default",
        "effort.reset_failed": "推論強度をリセットできませんでした。後で再試行してください。",
        "effort.reset": "既定の推論強度に戻しました。",
        "effort.unsupported": "未対応の推論強度：{value}\n指定可能な値：{levels}（または default）。",
        "effort.save_failed": "推論強度を保存できませんでした。後で再試行してください。",
        "effort.saved": "推論強度を {effort} に設定しました。",
        "login.private_only": "/openai_login は管理者の個人チャットでのみ使用できます。",
        "login.in_progress": "ログインが進行中です。完了するか /openai_login cancel でキャンセルしてください。",
        "login.start_failed": "デバイスログインを開始できません：{reason}",
        "login.start_unavailable": "デバイスログインを開始できませんでした。後で再試行してください。",
        "login.instructions": (
            "リンクを開き、デバイスコードを入力して認証してください：\n{url}\n"
            "デバイスコード：{code}\n"
            "認証が完了するとアカウントは自動的に保存されます。"
        ),
        "login.expired": "デバイスコードの有効期限が切れました。/openai_login を再送信してください。",
        "login.failed": "OpenAI ログインに失敗しました：{reason}",
        "login.cancelled": "ログインをキャンセルしました。",
        "login.saving": "認証完了。アカウントを保存しています。",
        "login.nothing_to_cancel": "進行中のログインはありません。",
        "login.usage": "使い方：/openai_login でログイン開始、/openai_login cancel でキャンセル。",
        "login.save_failed": "ログインに失敗しました。再試行してください。",
        "login.success": "ログインしました。アカウント {name}（{id}）を追加しました。",
        "device.device_login_disabled": "デバイスコードログインが無効です。ChatGPT のセキュリティ設定で「Enable device code authentication for Codex」を有効にしてください",
        "device.device_code_missing": "OpenAI からデバイスコードが返されませんでした",
        "device.device_poll_failed": "認証状態を確認できませんでした",
        "device.login_failed": "ログインに失敗しました",
        "stream.interrupted": "応答が中断されました。再試行してください。",
        "search.sources": "出典：",
        "search.running": "検索中",
        "search.completed": "検索完了",
        "search.failed": "検索に失敗",
        "search.interrupted": "検索中断",
        "provider.disabled": "このアカウントは無効です。プラグインページで有効にするか、別のアカウントに切り替えてください。",
        "provider.not_logged_in": "ログインしていません。先にプラグインページでログインしてください。",
        "provider.reauth_required": "ログインの有効期限が切れました。プラグインページで再ログインしてください。",
        "provider.local_reauth_required": "ローカル Codex のログインが見つからないか期限切れです。AstrBot のホストで Codex にログインするか、デバイスコードのアカウントに切り替えてください。",
        "provider.refresh_failed": "ログイン情報を更新できませんでした。しばらくしてから再試行してください。",
        "provider.save_failed": "更新した認証情報を保存できませんでした。設定ディレクトリの書き込み権限を確認してください。",
        "provider.source_error": "選択中のアカウントが変更されたか利用できません。再試行するかプラグインページを確認してください。",
        "provider.no_response": "完全な応答が返されませんでした。再試行してください。",
        "provider.routing_exhausted": "利用可能な OpenAI アカウントがありません。",
        "provider.routing_timeout": "自動切替がタイムアウトし、利用可能なアカウントが見つかりませんでした。",
        "provider.routing_attempt_limit": "自動切替の再試行上限に達し、利用可能なアカウントがありません。",
        "provider.routing_detail": "{summary}（{details}）",
        "provider.reason.disabled": "無効",
        "provider.reason.cooling": "クールダウン中",
        "provider.reason.reauth_required": "要再ログイン",
        "provider.reason.not_logged_in": "未ログイン",
        "provider.reason.invalid_credentials": "認証情報無効",
        "provider.reason.temporary": "一時的なエラー",
        "provider.reason.rate_limit": "レート制限",
        "provider.reason.duplicate_account": "重複アカウント",
        "provider.reason.attempt_limit": "再試行上限",
    },
}

_MONTHS_EN = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MONTHS_RU = (
    "янв.",
    "февр.",
    "мар.",
    "апр.",
    "мая",
    "июн.",
    "июл.",
    "авг.",
    "сент.",
    "окт.",
    "нояб.",
    "дек.",
)


def normalize_language(value: Any) -> str:
    """Normalize a locale string to a supported catalog key."""
    if not isinstance(value, str):
        return DEFAULT_LANGUAGE
    cleaned = value.strip()
    if cleaned in _CATALOG:
        return cleaned
    primary = cleaned.replace("_", "-").split("-", 1)[0].lower()
    return _PRIMARY_LANGUAGE_MAP.get(primary, DEFAULT_LANGUAGE)


def set_language(language: Any) -> None:
    """Choose the chat language; ``auto`` tracks AstrBot's system locale."""
    global _language, _follow_system_locale
    if language == AUTO_LANGUAGE:
        _follow_system_locale = True
        _language = DEFAULT_LANGUAGE
        return
    _follow_system_locale = False
    _language = language if language in _CATALOG else DEFAULT_LANGUAGE


def is_auto() -> bool:
    """Return whether replies follow AstrBot's system locale."""
    return _follow_system_locale


def language() -> str:
    return _session_language.get() or _language


@contextmanager
def use_language(lang: str | None) -> Iterator[None]:
    """Scope replies inside the current coroutine/task to ``lang``."""
    if lang is None:
        yield
        return
    token = _session_language.set(normalize_language(lang))
    try:
        yield
    finally:
        _session_language.reset(token)


async def resolve_language(context: Any, umo: Any = None) -> str:
    """Resolve the reply language for a session, respecting ``auto`` mode."""
    if not _follow_system_locale:
        return _language
    getter = getattr(context, "get_locale", None)
    if not callable(getter):
        return _language
    try:
        result = getter(umo) if isinstance(umo, str) and umo else getter()
        if inspect.isawaitable(result):
            result = await result
    except Exception:  # noqa: BLE001 - fall back cleanly on incompatible hosts
        return _language
    return normalize_language(result)


def text(key: str, *, lang: str | None = None, **values: Any) -> str:
    effective = normalize_language(lang) if lang is not None else language()
    template = _CATALOG[effective].get(key) or _CATALOG[DEFAULT_LANGUAGE][key]
    return template.format(**values) if values else template


def format_datetime(moment: datetime, now: datetime, *, lang: str | None = None) -> str:
    """Write a reset time the way each chat language usually does."""
    effective = normalize_language(lang) if lang is not None else language()
    same_year = moment.year == now.year
    clock = f"{moment:%H:%M}"
    if effective == "en-US":
        date = f"{_MONTHS_EN[moment.month - 1]} {moment.day}"
        return f"{date} {clock}" if same_year else f"{date}, {moment.year} {clock}"
    if effective == "ru-RU":
        date = f"{moment.day} {_MONTHS_RU[moment.month - 1]}"
        return f"{date} {clock}" if same_year else f"{date} {moment.year} г. {clock}"
    date = f"{moment.month}月{moment.day}日"
    return f"{date} {clock}" if same_year else f"{moment.year}年{date} {clock}"


def format_cooldown(cooldown_until: float | None, *, lang: str | None = None) -> str:
    """Format a cooldown notice with an optional localized reset timestamp."""
    reset = ""
    if (
        not isinstance(cooldown_until, bool)
        and isinstance(cooldown_until, (int, float))
        and math.isfinite(cooldown_until)
    ):
        try:
            dt = datetime.fromtimestamp(cooldown_until, tz=UTC).astimezone()
            now = datetime.now(UTC).astimezone()
            reset = text(
                "usage.reset", lang=lang, when=format_datetime(dt, now, lang=lang)
            )
        except (OSError, OverflowError, ValueError):
            reset = ""
    return text("usage.cooldown", lang=lang, reset=reset)


def format_routing_exhausted(
    reason: str,
    failures: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    *,
    lang: str | None = None,
) -> str:
    """Format a localized summary when automatic account routing fails."""
    if reason == "startup_timeout":
        summary_key = "provider.routing_timeout"
    elif reason == "attempt_limit":
        summary_key = "provider.routing_attempt_limit"
    else:
        summary_key = "provider.routing_exhausted"
    summary = text(summary_key, lang=lang)
    if not failures:
        return summary
    entries = []
    for source, status in failures:
        reason_key = f"provider.reason.{status}"
        label = (
            text(reason_key, lang=lang)
            if reason_key in _CATALOG[DEFAULT_LANGUAGE]
            else status
        )
        entries.append(f"{source}: {label}")
    return text(
        "provider.routing_detail",
        lang=lang,
        summary=summary,
        details="; ".join(entries),
    )
