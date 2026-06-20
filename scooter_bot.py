import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)

TOKEN = os.environ.get("TOKEN", "8807803061:AAEv70H91fLaCgbCGulfaNftJFafHzq_I6o")
DATA_FILE = "scooter_data.json"
ALLOWED_USERS = []

ACTIONS = {
    "charge":  {"label": "⚡ Зарядить",   "price": 4.5, "emoji": "🟡"},
    "move":    {"label": "🔄 Переставить", "price": 6.0, "emoji": "🟢"},
    "battery": {"label": "🔋 Батарейка",   "price": 3.0, "emoji": "🔵"},
    "broken":  {"label": "🔧 Сломан",      "price": 5.0, "emoji": "🔴"},
    "deploy":  {"label": "📍 Выставить",   "price": 1.5, "emoji": "⚪"},
}

GOAL = 250.0

# ConversationHandler state
WAITING_MANUAL = 1


# ─── DATA ────────────────────────────────────────────────────────────────────

def load_all() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_user_store(all_data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in all_data:
        all_data[uid] = {"today": {k: 0 for k in ACTIONS}, "history": {}}
    if "today" not in all_data[uid]:
        all_data[uid]["today"] = {k: 0 for k in ACTIONS}
    if "history" not in all_data[uid]:
        all_data[uid]["history"] = {}
    return all_data[uid]


def save_all(all_data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def auto_rollover(store: dict):
    """Если последняя запись была не сегодня — сохраняем вчера в историю и сбрасываем today."""
    key = today_key()
    today_data = store["today"]
    history = store["history"]

    # Ищем последний день в истории или today
    last_saved = max(history.keys()) if history else None

    total_today = sum(today_data.values())
    if total_today > 0 and last_saved != key:
        # Нашли данные за другой день — сохраняем их под вчерашней датой
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if yesterday not in history:
            history[yesterday] = dict(today_data)
        store["today"] = {k: 0 for k in ACTIONS}


def save_today_to_history(store: dict, date_key: str = None):
    key = date_key or today_key()
    store["history"][key] = dict(store["today"])


# ─── BUILD UI ─────────────────────────────────────────────────────────────────

def build_progress_bar(current: float, goal: float, length: int = 14) -> str:
    ratio = min(current / goal, 1.0)
    filled = int(ratio * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {ratio*100:.0f}%"


def calc_money(data: dict) -> float:
    return sum(data[k] * ACTIONS[k]["price"] for k in ACTIONS if k in data)


def build_message(store: dict) -> str:
    data = store["today"]
    total_count = sum(data.values())
    total_money = calc_money(data)
    remaining = max(GOAL - total_money, 0)

    # Недельная сумма
    week_total = weekly_total(store)

    lines = [f"📊 *Статистика — {datetime.now().strftime('%d.%m.%Y')}*", ""]
    for key, info in ACTIONS.items():
        count = data.get(key, 0)
        earned = count * info["price"]
        lines.append(f"{info['emoji']} {info['label'][2:].strip()}: *{count}* шт → *{earned:.2f} zl*")

    lines += [
        "",
        "━━━━━━━━━━━━━━━",
        f"🔢 Всего действий: *{total_count}*",
        f"💰 Заработано сегодня: *{total_money:.2f} zl*",
        f"📅 За неделю: *{week_total:.2f} zl*",
        "",
        f"🎯 Цель на день: *{GOAL:.0f} zl*",
        f"`{build_progress_bar(total_money, GOAL)}`",
        f"{'✅ Цель достигнута!' if total_money >= GOAL else f'⬇️ Осталось: *{remaining:.2f} zl*'}",
        "",
        f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}",
    ]
    return "\n".join(lines)


def weekly_total(store: dict) -> float:
    today = datetime.now().date()
    # Начало текущей недели (понедельник)
    monday = today - timedelta(days=today.weekday())
    total = calc_money(store["today"])  # сегодняшние
    for day_str, data in store["history"].items():
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
            if monday <= day <= today:
                total += calc_money(data)
        except Exception:
            pass
    return total


def build_week_message(store: dict) -> str:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())

    lines = [f"📅 *Неделя {monday.strftime('%d.%m')} — {today.strftime('%d.%m.%Y')}*", ""]

    week_days = {}
    # История
    for day_str, data in store["history"].items():
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
            if monday <= day <= today:
                week_days[day] = data
        except Exception:
            pass
    # Сегодня
    week_days[today] = store["today"]

    week_total = 0.0
    for day in sorted(week_days.keys()):
        data = week_days[day]
        money = calc_money(data)
        week_total += money
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()]
        marker = " ← сегодня" if day == today else ""
        lines.append(f"*{day_name} {day.strftime('%d.%m')}*: {money:.2f} zl{marker}")

    lines += ["", f"💰 *Итого за неделю: {week_total:.2f} zl*"]
    return "\n".join(lines)


def build_report(store: dict) -> str:
    data = store["today"]
    date_str = datetime.now().strftime("%d.%m.%Y")
    total_money = calc_money(data)
    week_total = weekly_total(store)

    lines = [f"Отчёт за {date_str}"]
    for key, info in ACTIONS.items():
        count = data.get(key, 0)
        if count == 0:
            continue
        earned = count * info["price"]
        name = info["label"][2:].strip()
        lines.append(f"{name}: {count} шт × {info['price']} zl = {earned:.2f} zl")
    lines.append(f"Итого за день: {total_money:.2f} zl")
    lines.append(f"Итого за неделю: {week_total:.2f} zl")
    return "\n".join(lines)


def build_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🟡 Зарядить +4.5zl",    callback_data="charge"),
            InlineKeyboardButton("🟢 Переставить +6zl",   callback_data="move"),
        ],
        [
            InlineKeyboardButton("🔵 Батарейка +3zl",     callback_data="battery"),
            InlineKeyboardButton("🔴 Сломан +5zl",        callback_data="broken"),
        ],
        [
            InlineKeyboardButton("⚪ Выставить +1.5zl",   callback_data="deploy"),
        ],
        [
            InlineKeyboardButton("✏️ Ввести вручную",     callback_data="manual"),
            InlineKeyboardButton("↩️ Отменить",           callback_data="undo"),
        ],
        [
            InlineKeyboardButton("📅 Неделя",             callback_data="week"),
            InlineKeyboardButton("🗑 Сброс дня",          callback_data="reset"),
        ],
        [
            InlineKeyboardButton("📋 Скопировать отчёт",  callback_data="export"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def manual_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа при ручном вводе."""
    buttons = [
        [
            InlineKeyboardButton("🟡 Зарядить",    callback_data="manual_charge"),
            InlineKeyboardButton("🟢 Переставить", callback_data="manual_move"),
        ],
        [
            InlineKeyboardButton("🔵 Батарейка",   callback_data="manual_battery"),
            InlineKeyboardButton("🔴 Сломан",      callback_data="manual_broken"),
        ],
        [
            InlineKeyboardButton("⚪ Выставить",   callback_data="manual_deploy"),
        ],
        [
            InlineKeyboardButton("❌ Отмена",      callback_data="manual_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


# ─── HANDLERS ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ У тебя нет доступа к этому боту.")
        return

    all_data = load_all()
    store = get_user_store(all_data, user_id)
    auto_rollover(store)
    save_all(all_data)

    msg = await update.message.reply_text(
        build_message(store),
        parse_mode="Markdown",
        reply_markup=build_keyboard(),
    )
    context.user_data["history"] = context.user_data.get("history", [])
    context.user_data["msg_id"] = msg.message_id


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    action = query.data
    all_data = load_all()
    store = get_user_store(all_data, user_id)
    auto_rollover(store)
    data = store["today"]
    history: list = context.user_data.get("history", [])

    # ── Сброс дня ──────────────────────────────
    if action == "reset":
        save_today_to_history(store)
        store["today"] = {k: 0 for k in ACTIONS}
        history.clear()
        context.user_data["history"] = history
        save_all(all_data)
        await query.edit_message_text(build_message(store), parse_mode="Markdown", reply_markup=build_keyboard())
        return

    # ── Отмена последнего ──────────────────────
    if action == "undo":
        if history:
            last = history.pop()
            data[last] = max(0, data[last] - 1)
            context.user_data["history"] = history
            save_all(all_data)
        await query.edit_message_text(build_message(store), parse_mode="Markdown", reply_markup=build_keyboard())
        return

    # ── Отчёт ──────────────────────────────────
    if action == "export":
        await query.message.reply_text(f"`{build_report(store)}`", parse_mode="Markdown")
        return

    # ── Неделя ─────────────────────────────────
    if action == "week":
        await query.message.reply_text(build_week_message(store), parse_mode="Markdown")
        return

    # ── Ручной ввод — шаг 1: выбор типа ───────
    if action == "manual":
        await query.message.reply_text(
            "Выбери тип действия для ручного ввода:",
            reply_markup=manual_keyboard(),
        )
        return

    # ── Ручной ввод — шаг 2: выбран тип ───────
    if action.startswith("manual_"):
        if action == "manual_cancel":
            await query.message.delete()
            return
        key = action.replace("manual_", "")
        if key in ACTIONS:
            context.user_data["manual_key"] = key
            context.user_data["manual_msg_id"] = query.message.message_id
            label = ACTIONS[key]["label"]
            await query.edit_message_text(
                f"Введи количество для *{label}*\n_(например: 5)_",
                parse_mode="Markdown",
            )
            return ConversationHandler.END  # не используем ConvHandler, ждём текст

    # ── Обычное нажатие ────────────────────────
    if action in ACTIONS:
        data[action] = data.get(action, 0) + 1
        history.append(action)
        if len(history) > 100:
            history.pop(0)
        context.user_data["history"] = history
        save_all(all_data)

    await query.edit_message_text(build_message(store), parse_mode="Markdown", reply_markup=build_keyboard())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод количества при ручном вводе."""
    manual_key = context.user_data.get("manual_key")
    if not manual_key:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        count = int(text)
        if count <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Введи целое положительное число, например: *5*", parse_mode="Markdown")
        return

    all_data = load_all()
    store = get_user_store(all_data, user_id)
    data = store["today"]
    data[manual_key] = data.get(manual_key, 0) + count

    history: list = context.user_data.get("history", [])
    for _ in range(count):
        history.append(manual_key)
    if len(history) > 100:
        history = history[-100:]
    context.user_data["history"] = history
    context.user_data.pop("manual_key", None)

    save_all(all_data)

    label = ACTIONS[manual_key]["label"]
    earned = count * ACTIONS[manual_key]["price"]

    # Удаляем сообщение с вопросом и ответ пользователя
    try:
        mid = context.user_data.pop("manual_msg_id", None)
        if mid:
            await context.bot.delete_message(update.effective_chat.id, mid)
        await update.message.delete()
    except Exception:
        pass

    msg = await update.message.reply_text(
        f"✅ Добавлено *{count}* × {label} = *{earned:.2f} zl*\n\n" + build_message(store),
        parse_mode="Markdown",
        reply_markup=build_keyboard(),
    )
    context.user_data["msg_id"] = msg.message_id


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен! Нажми /start в Telegram.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
