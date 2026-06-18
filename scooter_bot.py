import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ.get("TOKEN", "8807803061:AAEv70H91fLaCgbCGulfaNftJFafHzq_I6o")
DATA_FILE = "scooter_data.json"

# Список разрешённых user_id. Если пустой — бот открыт для всех.
ALLOWED_USERS = []

ACTIONS = {
    "charge":  {"label": "⚡ Зарядить",    "price": 4.5,  "emoji": "🟡"},
    "move":    {"label": "🔄 Переставить",  "price": 6.0,  "emoji": "🟢"},
    "battery": {"label": "🔋 Батарейка",    "price": 3.0,  "emoji": "🔵"},
    "broken":  {"label": "🔧 Сломан",       "price": 5.0,  "emoji": "🔴"},
    "deploy":  {"label": "📍 Выставить",    "price": 1.5,  "emoji": "⚪"},
}

GOAL = 250.0


def load_all() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_data(user_id: int) -> dict:
    all_data = load_all()
    return all_data.get(str(user_id), {key: 0 for key in ACTIONS})


def save_data(user_id: int, data: dict):
    all_data = load_all()
    all_data[str(user_id)] = data
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)


def build_progress_bar(current: float, goal: float, length: int = 14) -> str:
    ratio = min(current / goal, 1.0)
    filled = int(ratio * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {ratio*100:.0f}%"


def build_message(data: dict) -> str:
    total_count = sum(data.values())
    total_money = sum(data[k] * ACTIONS[k]["price"] for k in ACTIONS)
    remaining = max(GOAL - total_money, 0)

    lines = ["📊 *Статистика самокатов*", ""]
    for key, info in ACTIONS.items():
        count = data[key]
        earned = count * info["price"]
        lines.append(f"{info['emoji']} {info['label'][2:].strip()}: *{count}* шт → *{earned:.2f} zl*")

    lines += [
        "",
        "━━━━━━━━━━━━━━━",
        f"🔢 Всего действий: *{total_count}*",
        f"💰 Итого заработано: *{total_money:.2f} zl*",
        "",
        f"🎯 Цель: *{GOAL:.0f} zl*",
        f"`{build_progress_bar(total_money, GOAL)}`",
        f"{'✅ Цель достигнута!' if total_money >= GOAL else f'⬇️ Осталось: *{remaining:.2f} zl*'}",
        "",
        f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}",
    ]
    return "\n".join(lines)


def build_report(data: dict) -> str:
    date_str = datetime.now().strftime("%d.%m.%Y")
    total_money = sum(data[k] * ACTIONS[k]["price"] for k in ACTIONS)

    lines = [f"Отчёт за {date_str}"]
    for key, info in ACTIONS.items():
        count = data[key]
        if count == 0:
            continue
        earned = count * info["price"]
        name = info["label"][2:].strip()
        lines.append(f"{name}: {count} шт × {info['price']} zl = {earned:.2f} zl")

    lines.append(f"Итого: {total_money:.2f} zl")
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
            InlineKeyboardButton("↩️ Отменить последнее", callback_data="undo"),
            InlineKeyboardButton("🗑 Сбросить день",       callback_data="reset"),
        ],
        [
            InlineKeyboardButton("📋 Скопировать отчёт",  callback_data="export"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ У тебя нет доступа к этому боту.")
        return

    data = load_data(user_id)
    msg = await update.message.reply_text(
        build_message(data),
        parse_mode="Markdown",
        reply_markup=build_keyboard(),
    )
    context.user_data["msg_id"] = msg.message_id
    context.user_data["history"] = context.user_data.get("history", [])


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    action = query.data
    data = load_data(user_id)
    history: list = context.user_data.get("history", [])

    if action == "reset":
        history.clear()
        data = {key: 0 for key in ACTIONS}
        save_data(user_id, data)
        context.user_data["history"] = history
        await query.edit_message_text(
            build_message(data),
            parse_mode="Markdown",
            reply_markup=build_keyboard(),
        )
        return

    if action == "undo":
        if history:
            last = history.pop()
            data[last] = max(0, data[last] - 1)
            save_data(user_id, data)
            context.user_data["history"] = history
        await query.edit_message_text(
            build_message(data),
            parse_mode="Markdown",
            reply_markup=build_keyboard(),
        )
        return

    if action == "export":
        report = build_report(data)
        await query.message.reply_text(
            f"`{report}`",
            parse_mode="Markdown",
        )
        return

    if action in ACTIONS:
        data[action] += 1
        history.append(action)
        if len(history) > 50:
            history.pop(0)
        context.user_data["history"] = history
        save_data(user_id, data)

    await query.edit_message_text(
        build_message(data),
        parse_mode="Markdown",
        reply_markup=build_keyboard(),
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    print("Бот запущен! Нажми /start в Telegram.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
