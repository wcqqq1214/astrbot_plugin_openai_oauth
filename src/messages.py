"""Chat replies in the language chosen in the plugin settings.

AstrBot has no server-side locale, so chat commands follow the plugin's
``chat_language`` setting; the Plugin View follows the dashboard instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DEFAULT_LANGUAGE = "zh-CN"
LANGUAGES = ("zh-CN", "en-US", "ru-RU", "ja-JP")
_language = DEFAULT_LANGUAGE

_CATALOG: dict[str, dict[str, str]] = {
    "zh-CN": {
        "usage.title": "OpenAI 订阅额度：",
        "usage.no_windows": "当前账号暂无可用额度窗口。",
        "usage.remaining": "剩余 {percent}%",
        "usage.unavailable": "额度暂不可用",
        "usage.line": "· {label}：{remaining}{reset}",
        "usage.limit_reached": "状态：已达额度上限，等待窗口重置。",
        "usage.not_allowed": "状态：当前不可用。",
        "usage.reset": "，重置 {when}",
        "usage.cooldown": "OpenAI 订阅额度当前处于冷却状态{reset}。",
        "usage.reauth_required": "凭据已失效，请在插件详情页重新登录。",
        "usage.unsupported": "凭据配置格式不受支持，请升级插件后重新登录。",
        "usage.invalid": "无法读取 OpenAI 凭据，请在插件详情页重新登录。",
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
        "effort.not_subscribe": "当前会话未使用 OpenAI Subscribe 模型，无法设置推理强度。",
        "effort.override": "当前会话推理强度：{effort}（会话覆盖）。",
        "effort.model_default": "当前会话未设置覆盖，模型默认推理强度：{effort}。",
        "effort.unset": "当前会话未设置推理强度，将使用模型默认行为。",
        "effort.help": "{message}\n可用值：{levels}\n用法：/effort <值>；/effort default 恢复模型默认值。",
        "effort.reset_failed": "恢复模型默认值失败，请稍后重试。",
        "effort.reset": "已恢复当前会话的模型默认推理强度，下一次 OpenAI 请求生效。",
        "effort.unsupported": "不支持的推理强度：{value}\n可用值：{levels}，或使用 default。",
        "effort.save_failed": "保存推理强度失败，请稍后重试。",
        "effort.saved": "已将当前会话推理强度设为 {effort}，下一次 OpenAI 请求生效。",
        "login.private_only": "为保护设备码，/openai_login 仅允许在管理员私聊中使用。",
        "login.in_progress": "当前私聊已有一个 OpenAI 登录流程，请先完成或等待它结束。",
        "login.start_failed": "无法启动设备登录：{reason}",
        "login.start_unavailable": "无法启动设备登录，请稍后重试。",
        "login.instructions": (
            "请在当前私聊中打开以下 OpenAI 验证网址并输入设备码：\n{url}\n"
            "设备码：{code}\n"
            "授权完成后，AstrBot 会在服务端自动交换并保存凭据；令牌不会发送到聊天。"
        ),
        "login.expired": "设备码已过期，请重新发送 /openai_login。",
        "login.failed": "OpenAI 登录失败：{reason}",
        "login.cancelled": "已取消当前私聊中的 OpenAI 登录。",
        "login.nothing_to_cancel": "当前私聊没有进行中的 OpenAI 登录。",
        "login.usage": "用法：/openai_login 开始设备码登录；/openai_login cancel 取消进行中的登录。",
        "login.save_failed": "OpenAI 登录或保存失败，请重试。",
        "login.success": "OpenAI 登录成功，已新增账号 {name}（{id}）。请在模型配置中选择此来源。",
        "device.device_login_disabled": "设备码登录未启用：请先在 ChatGPT 安全设置中开启“为 Codex 启用设备代码授权”",
        "device.device_code_missing": "OpenAI 未返回设备码",
        "device.device_poll_failed": "查询授权状态失败",
        "device.login_failed": "登录失败",
        "stream.interrupted": "回复在输出后中断，未重新发送请求。",
    },
    "en-US": {
        "usage.title": "OpenAI subscription allowance:",
        "usage.no_windows": "This account has no allowance windows right now.",
        "usage.remaining": "{percent}% left",
        "usage.unavailable": "allowance unavailable",
        "usage.line": "· {label}: {remaining}{reset}",
        "usage.limit_reached": "Status: the allowance is used up until a window resets.",
        "usage.not_allowed": "Status: currently unavailable.",
        "usage.reset": ", resets {when}",
        "usage.cooldown": "The OpenAI subscription allowance is cooling down{reset}.",
        "usage.reauth_required": "The login has expired. Sign in again on the plugin page.",
        "usage.unsupported": "The saved login format is not supported. Update the plugin and sign in again.",
        "usage.invalid": "The OpenAI login can't be read. Sign in again on the plugin page.",
        "usage.failed": "The allowance couldn't be checked. Try again later.",
        "usage.select_model": "Select an OpenAI Subscribe model first.",
        "window.5h": "5-hour window",
        "window.7d": "7-day window",
        "window.30d": "30-day window",
        "window.days": "{count}-day window",
        "window.hours": "{count}-hour window",
        "window.generic": "Allowance window",
        "effort.no_session": "This conversation is unavailable.",
        "effort.provider_unknown": "The conversation's model couldn't be identified.",
        "effort.not_subscribe": "This conversation doesn't use an OpenAI Subscribe model, so its reasoning effort can't be set.",
        "effort.override": "Reasoning effort for this conversation: {effort} (conversation override).",
        "effort.model_default": "No conversation override; the model's default reasoning effort is {effort}.",
        "effort.unset": "No reasoning effort is set; the model's default behavior applies.",
        "effort.help": "{message}\nLevels: {levels}\nUsage: /effort <level>; /effort default restores the model default.",
        "effort.reset_failed": "The model default couldn't be restored. Try again later.",
        "effort.reset": "Restored the model's default reasoning effort for this conversation from the next OpenAI request.",
        "effort.unsupported": "Unsupported reasoning effort: {value}\nLevels: {levels}, or default.",
        "effort.save_failed": "The reasoning effort couldn't be saved. Try again later.",
        "effort.saved": "Set this conversation's reasoning effort to {effort} from the next OpenAI request.",
        "login.private_only": "To protect the device code, /openai_login works only in an administrator's private chat.",
        "login.in_progress": "An OpenAI login is already in progress in this chat. Finish it or wait for it to end.",
        "login.start_failed": "Device login couldn't start: {reason}",
        "login.start_unavailable": "Device login couldn't start. Try again later.",
        "login.instructions": (
            "Open this OpenAI verification page and enter the device code:\n{url}\n"
            "Device code: {code}\n"
            "After you authorize, AstrBot exchanges and saves the credentials on the "
            "server; tokens are never sent to the chat."
        ),
        "login.expired": "The device code expired. Send /openai_login again.",
        "login.failed": "OpenAI login failed: {reason}",
        "login.cancelled": "Cancelled the OpenAI login in this chat.",
        "login.nothing_to_cancel": "No OpenAI login is in progress in this chat.",
        "login.usage": "Usage: /openai_login starts a device-code login; /openai_login cancel stops one in progress.",
        "login.save_failed": "OpenAI login or saving failed. Try again.",
        "login.success": "Signed in to OpenAI and added the account {name} ({id}). Select it in the model settings.",
        "device.device_login_disabled": "device code login is off. Turn on “Enable device code authentication for Codex” in ChatGPT's security settings",
        "device.device_code_missing": "OpenAI didn't return a device code",
        "device.device_poll_failed": "checking the authorization failed",
        "device.login_failed": "login failed",
        "stream.interrupted": "The reply was interrupted after output began; the request was not sent again.",
    },
    "ru-RU": {
        "usage.title": "Квота подписки OpenAI:",
        "usage.no_windows": "Для этого аккаунта сейчас нет окон квоты.",
        "usage.remaining": "осталось {percent}%",
        "usage.unavailable": "квота недоступна",
        "usage.line": "· {label}: {remaining}{reset}",
        "usage.limit_reached": "Статус: квота исчерпана до сброса окна.",
        "usage.not_allowed": "Статус: сейчас недоступно.",
        "usage.reset": ", сброс {when}",
        "usage.cooldown": "Квота подписки OpenAI восстанавливается{reset}.",
        "usage.reauth_required": "Вход истёк. Войдите снова на странице плагина.",
        "usage.unsupported": "Формат сохранённого входа не поддерживается. Обновите плагин и войдите снова.",
        "usage.invalid": "Не удаётся прочитать вход OpenAI. Войдите снова на странице плагина.",
        "usage.failed": "Не удалось проверить квоту. Повторите попытку позже.",
        "usage.select_model": "Сначала выберите модель OpenAI Subscribe.",
        "window.5h": "Окно 5 ч",
        "window.7d": "Окно 7 дн.",
        "window.30d": "Окно 30 дн.",
        "window.days": "Окно {count} дн.",
        "window.hours": "Окно {count} ч",
        "window.generic": "Окно квоты",
        "effort.no_session": "Этот диалог недоступен.",
        "effort.provider_unknown": "Не удалось определить модель диалога.",
        "effort.not_subscribe": "В этом диалоге не используется модель OpenAI Subscribe, поэтому уровень рассуждений задать нельзя.",
        "effort.override": "Уровень рассуждений для диалога: {effort} (переопределение диалога).",
        "effort.model_default": "Переопределения нет; уровень рассуждений модели по умолчанию: {effort}.",
        "effort.unset": "Уровень рассуждений не задан; действует поведение модели по умолчанию.",
        "effort.help": "{message}\nУровни: {levels}\nИспользование: /effort <уровень>; /effort default возвращает значение модели.",
        "effort.reset_failed": "Не удалось вернуть значение модели. Повторите попытку позже.",
        "effort.reset": "Для диалога восстановлен уровень рассуждений модели со следующего запроса OpenAI.",
        "effort.unsupported": "Неподдерживаемый уровень рассуждений: {value}\nУровни: {levels} или default.",
        "effort.save_failed": "Не удалось сохранить уровень рассуждений. Повторите попытку позже.",
        "effort.saved": "Уровень рассуждений диалога установлен на {effort} со следующего запроса OpenAI.",
        "login.private_only": "Чтобы защитить код устройства, /openai_login работает только в личном чате администратора.",
        "login.in_progress": "В этом чате уже идёт вход OpenAI. Завершите его или дождитесь окончания.",
        "login.start_failed": "Не удалось начать вход по коду устройства: {reason}",
        "login.start_unavailable": "Не удалось начать вход по коду устройства. Повторите попытку позже.",
        "login.instructions": (
            "Откройте страницу проверки OpenAI и введите код устройства:\n{url}\n"
            "Код устройства: {code}\n"
            "После подтверждения AstrBot сам обменяет и сохранит учётные данные на "
            "сервере; токены не отправляются в чат."
        ),
        "login.expired": "Срок действия кода устройства истёк. Отправьте /openai_login снова.",
        "login.failed": "Не удалось войти в OpenAI: {reason}",
        "login.cancelled": "Вход OpenAI в этом чате отменён.",
        "login.nothing_to_cancel": "В этом чате нет текущего входа OpenAI.",
        "login.usage": "Использование: /openai_login начинает вход по коду устройства; /openai_login cancel отменяет текущий вход.",
        "login.save_failed": "Не удалось войти в OpenAI или сохранить данные. Повторите попытку.",
        "login.success": "Вход в OpenAI выполнен, добавлен аккаунт {name} ({id}). Выберите его в настройках модели.",
        "device.device_login_disabled": "вход по коду устройства выключен. Включите «Enable device code authentication for Codex» в настройках безопасности ChatGPT",
        "device.device_code_missing": "OpenAI не вернул код устройства",
        "device.device_poll_failed": "не удалось проверить авторизацию",
        "device.login_failed": "вход не выполнен",
        "stream.interrupted": "Ответ прервался после начала вывода; запрос не отправлялся повторно.",
    },
    "ja-JP": {
        "usage.title": "OpenAI サブスクリプションの利用枠：",
        "usage.no_windows": "このアカウントには現在利用枠のウィンドウがありません。",
        "usage.remaining": "残り {percent}%",
        "usage.unavailable": "利用枠を取得できません",
        "usage.line": "・{label}：{remaining}{reset}",
        "usage.limit_reached": "状態：利用枠の上限に達しました。ウィンドウのリセットを待っています。",
        "usage.not_allowed": "状態：現在利用できません。",
        "usage.reset": "、{when} にリセット",
        "usage.cooldown": "OpenAI サブスクリプションの利用枠はクールダウン中です{reset}。",
        "usage.reauth_required": "ログインの有効期限が切れました。プラグインページで再度ログインしてください。",
        "usage.unsupported": "保存されたログインの形式に対応していません。プラグインを更新して再度ログインしてください。",
        "usage.invalid": "OpenAI のログインを読み取れません。プラグインページで再度ログインしてください。",
        "usage.failed": "利用枠を確認できませんでした。後で再試行してください。",
        "usage.select_model": "先に OpenAI Subscribe のモデルを選択してください。",
        "window.5h": "5時間枠",
        "window.7d": "7日間枠",
        "window.30d": "30日間枠",
        "window.days": "{count}日間枠",
        "window.hours": "{count}時間枠",
        "window.generic": "利用枠",
        "effort.no_session": "この会話は利用できません。",
        "effort.provider_unknown": "会話のモデルを特定できませんでした。",
        "effort.not_subscribe": "この会話は OpenAI Subscribe のモデルを使っていないため、推論強度を設定できません。",
        "effort.override": "この会話の推論強度：{effort}（会話ごとの上書き）。",
        "effort.model_default": "会話ごとの上書きはありません。モデルの既定の推論強度：{effort}。",
        "effort.unset": "推論強度は未設定です。モデルの既定の動作を使います。",
        "effort.help": "{message}\n指定できる値：{levels}\n使い方：/effort <値>、/effort default でモデルの既定値に戻します。",
        "effort.reset_failed": "モデルの既定値に戻せませんでした。後で再試行してください。",
        "effort.reset": "次の OpenAI リクエストから、この会話の推論強度をモデルの既定値に戻しました。",
        "effort.unsupported": "対応していない推論強度：{value}\n指定できる値：{levels}、または default。",
        "effort.save_failed": "推論強度を保存できませんでした。後で再試行してください。",
        "effort.saved": "次の OpenAI リクエストから、この会話の推論強度を {effort} にしました。",
        "login.private_only": "デバイスコードを守るため、/openai_login は管理者の個人チャットでのみ使えます。",
        "login.in_progress": "このチャットでは OpenAI のログインが進行中です。完了するか終了をお待ちください。",
        "login.start_failed": "デバイスログインを開始できません：{reason}",
        "login.start_unavailable": "デバイスログインを開始できませんでした。後で再試行してください。",
        "login.instructions": (
            "次の OpenAI 確認ページを開き、デバイスコードを入力してください：\n{url}\n"
            "デバイスコード：{code}\n"
            "認証後、AstrBot がサーバー上で認証情報を交換して保存します。トークンはチャットに送信されません。"
        ),
        "login.expired": "デバイスコードの有効期限が切れました。/openai_login をもう一度送信してください。",
        "login.failed": "OpenAI へのログインに失敗しました：{reason}",
        "login.cancelled": "このチャットの OpenAI ログインを取り消しました。",
        "login.nothing_to_cancel": "このチャットで進行中の OpenAI ログインはありません。",
        "login.usage": "使い方：/openai_login でデバイスコードログインを開始、/openai_login cancel で進行中のログインを取り消します。",
        "login.save_failed": "OpenAI へのログインまたは保存に失敗しました。再試行してください。",
        "login.success": "OpenAI にログインし、アカウント {name}（{id}）を追加しました。モデル設定で選択してください。",
        "device.device_login_disabled": "デバイスコードログインがオフです。ChatGPT のセキュリティ設定で「Enable device code authentication for Codex」をオンにしてください",
        "device.device_code_missing": "OpenAI がデバイスコードを返しませんでした",
        "device.device_poll_failed": "認証状態を確認できませんでした",
        "device.login_failed": "ログインに失敗しました",
        "stream.interrupted": "出力の開始後に応答が中断されました。リクエストは再送信していません。",
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


def set_language(language: Any) -> None:
    """Choose the chat language; unknown values fall back to Chinese."""
    global _language
    _language = language if language in _CATALOG else DEFAULT_LANGUAGE


def language() -> str:
    return _language


def text(key: str, **values: Any) -> str:
    template = _CATALOG[_language].get(key) or _CATALOG[DEFAULT_LANGUAGE][key]
    return template.format(**values) if values else template


def format_datetime(moment: datetime, now: datetime) -> str:
    """Write a reset time the way each chat language usually does."""
    same_year = moment.year == now.year
    clock = f"{moment:%H:%M}"
    if _language == "en-US":
        date = f"{_MONTHS_EN[moment.month - 1]} {moment.day}"
        return f"{date} {clock}" if same_year else f"{date}, {moment.year} {clock}"
    if _language == "ru-RU":
        date = f"{moment.day} {_MONTHS_RU[moment.month - 1]}"
        return f"{date} {clock}" if same_year else f"{date} {moment.year} г. {clock}"
    date = f"{moment.month}月{moment.day}日"
    return f"{date} {clock}" if same_year else f"{moment.year}年{date} {clock}"
