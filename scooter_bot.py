import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

TOKEN = os.environ.get("TOKEN", "8807803061:AAEv70H91fLaCgbCGulfaNftJFafHzq_I6o")
DATA_FILE = "scooter_data.json"
ALLOWED_USERS = []

ACTIONS = {
    "charge":  {"label": "Зарядить",   "price": 4.5, "emoji": "🟡"},
    "move":    {"label": "Переставить", "price": 6.0, "emoji": "🟢"},
    "battery": {"label": "Батарейка",   "price": 3.0, "emoji": "🔵"},
    "broken":  {"label": "Сломан",      "price": 5.0, "emoji": "🔴"},
    "deploy":  {"label": "Выставить",   "price": 1.5, "emoji": "⚪"},
}

GOAL = 250.0


# ─── DATA ─────────────────────────────────────────────────────────────────────

def load_all() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_store(all_data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in all_data:
        all_data[uid] = {"history": {}}
    if "history" not in all_data[uid]:
        all_data[uid]["history"] = {}
    return all_data[uid]


def save_all(all_data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_day(store: dict, key: str) -> dict:
    if key not in store["history"]:
        store["history"][key] = {k: 0 for k in ACTIONS}
    return store["history"][key]


def calc_money(data: dict) -> float:
    return sum(data.get(k, 0) * ACTIONS[k]["price"] for k in ACTIONS)


def weekly_total(store: dict) -> float:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    total = 0.0
    for day_str, data in store["history"].items():
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
            if monday <= day <= today:
                total += calc_money(data)
        except Exception:
            pass
    return total


# ─── KEYBOARDS ────────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Сегодня",           callback_data="view_today")],
        [InlineKeyboardButton("✏️ Добавить вручную",  callback_data="manual_start")],
        [InlineKeyboardButton("📋 Отчёт",             callback_data="view_report")],
        [InlineKeyboardButton("📅 Неделя",            callback_data="view_week")],
    ])


def kb_today() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟡 Зарядить +4.5",  callback_data="act_charge"),
            InlineKeyboardButton("🟢 Перестав. +6",   callback_data="act_move"),
        ],
        [
            InlineKeyboardButton("🔵 Батарейка +3",   callback_data="act_battery"),
            InlineKeyboardButton("🔴 Сломан +5",      callback_data="act_broken"),
        ],
        [
            InlineKeyboardButton("⚪ Выставить +1.5", callback_data="act_deploy"),
        ],
        [
            InlineKeyboardButton("↩️ Отменить",       callback_data="act_undo"),
            InlineKeyboardButton("🗑 Сброс дня",      callback_data="act_reset"),
        ],
        [InlineKeyboardButton("🏠 Главное меню",      callback_data="go_main")],
    ])


def kb_manual_date() -> InlineKeyboardMarkup:
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📅 Сегодня ({today.strftime('%d.%m')})",         callback_data=f"mdate_{today.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton(f"📅 Вчера ({yesterday.strftime('%d.%m')})",        callback_data=f"mdate_{yesterday.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton(f"📅 Позавчера ({day_before.strftime('%d.%m')})",   callback_data=f"mdate_{day_before.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton("📝 Ввести дату вручную",                           callback_data="mdate_custom")],
        [InlineKeyboardButton("🏠 Главное меню",                                  callback_data="go_main")],
    ])


def kb_manual_action() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟡 Зарядить",    callback_data="mact_charge"),
            InlineKeyboardButton("🟢 Переставить", callback_data="mact_move"),
        ],
        [
            InlineKeyboardButton("🔵 Батарейка",   callback_data="mact_battery"),
            InlineKeyboardButton("🔴 Сломан",      callback_data="mact_broken"),
        ],
        [InlineKeyboardButton("⚪ Выставить",      callback_data="mact_deploy")],
        [InlineKeyboardButton("🏠 Главное меню",   callback_data="go_main")],
    ])


# ─── MESSAGES ─────────────────────────────────────────────────────────────────

def build_progress_bar(current: float, goal: float, length: int = 14) -> str:
    ratio = min(current / goal, 1.0)
    filled = int(ratio * length)
    return f"[{'█' * filled}{'░' * (length - filled)}] {ratio*100:.0f}%"


def msg_main(store: dict) -> str:
    today = get_day(store, today_key())
    today_money = calc_money(today)
    week_money = weekly_total(store)
    return (
        "👋 *Привет! Выбери раздел:*\n\n"
        f"💰 Сегодня: *{today_money:.2f} zl*\n"
        f"📅 За неделю: *{week_money:.2f} zl*"
    )


def msg_today(store: dict) -> str:
    data = get_day(store, today_key())
    total_count = sum(data.get(k, 0) for k in ACTIONS)
    total_money = calc_money(data)
    remaining = max(GOAL - total_money, 0)

    lines = [f"📊 *Сегодня — {datetime.now().strftime('%d.%m.%Y')}*", ""]
    for key, info in ACTIONS.items():
        count = data.get(key, 0)
        earned = count * info["price"]
        lines.append(f"{info['emoji']} {info['label']}: *{count}* шт → *{earned:.2f} zl*")
    lines += [
        "",
        "━━━━━━━━━━━━━━━",
        f"🔢 Всего: *{total_count}* действий",
        f"💰 Заработано: *{total_money:.2f} zl*",
        "",
        f"🎯 Цель: *{GOAL:.0f} zl*",
        f"`{build_progress_bar(total_money, GOAL)}`",
        f"{'✅ Цель достигнута!' if total_money >= GOAL else f'⬇️ Осталось: *{remaining:.2f} zl*'}",
        "",
        f"🕐 {datetime.now().strftime('%H:%M:%S')}",
    ]
    return "\n".join(lines)


def msg_week(store: dict) -> str:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    lines = [f"📅 *Неделя {monday.strftime('%d.%m')} — {today.strftime('%d.%m.%Y')}*", ""]
    week_total = 0.0
    for i in range(7):
        day = monday + timedelta(days=i)
        if day > today:
            break
        key = day.strftime("%Y-%m-%d")
        data = store["history"].get(key, {})
        money = calc_money(data)
        week_total += money
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()]
        marker = " ← сегодня" if day == today else ""
        bar = "█" * int(money / 20) if money > 0 else "·"
        lines.append(f"*{day_name} {day.strftime('%d.%m')}*: {money:.2f} zl {bar}{marker}")
    lines += ["", f"💰 *Итого за неделю: {week_total:.2f} zl*"]
    return "\n".join(lines)


def msg_report(store: dict) -> str:
    data = get_day(store, today_key())
    date_str = datetime.now().strftime("%d.%m.%Y")
    total_money = calc_money(data)
    week_money = weekly_total(store)
    lines = [f"Отчёт за {date_str}"]
    for key, info in ACTIONS.items():
        count = data.get(key, 0)
        if count == 0:
            continue
        lines.append(f"{info['label']}: {count} шт × {info['price']} zl = {count * info['price']:.2f} zl")
    lines.append(f"Итого за день: {total_money:.2f} zl")
    lines.append(f"Итого за неделю: {week_money:.2f} zl")
    return "\n".join(lines)


# ─── HANDLERS ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ У тебя нет доступа.")
        return
    all_data = load_all()
    store = get_store(all_data, user_id)
    save_all(all_data)
    context.user_data.clear()
    await update.message.reply_text(msg_main(store), parse_mode="Markdown", reply_markup=kb_main())


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    data_cb = query.data
    all_data = load_all()
    store = get_store(all_data, user_id)

    # ── Главное меню ───────────────────────────
    if data_cb == "go_main":
        context.user_data.clear()
        await query.edit_message_text(msg_main(store), parse_mode="Markdown", reply_markup=kb_main())
        return

    # ── Сегодня ────────────────────────────────
    if data_cb == "view_today":
        await query.edit_message_text(msg_today(store), parse_mode="Markdown", reply_markup=kb_today())
        return

    # ── Действия сегодня ───────────────────────
    if data_cb.startswith("act_"):
        action = data_cb.replace("act_", "")
        today = get_day(store, today_key())
        history: list = context.user_data.get("history", [])

        if action == "reset":
            store["history"][today_key()] = {k: 0 for k in ACTIONS}
            history.clear()
            context.user_data["history"] = history
            save_all(all_data)
            await query.edit_message_text(msg_today(store), parse_mode="Markdown", reply_markup=kb_today())
            return

        if action == "undo":
            if history:
                last = history.pop()
                today[last] = max(0, today.get(last, 0) - 1)
                context.user_data["history"] = history
                save_all(all_data)
            await query.edit_message_text(msg_today(store), parse_mode="Markdown", reply_markup=kb_today())
            return

        if action in ACTIONS:
            today[action] = today.get(action, 0) + 1
            history.append(action)
            if len(history) > 100:
                history = history[-100:]
            context.user_data["history"] = history
            save_all(all_data)
        await query.edit_message_text(msg_today(store), parse_mode="Markdown", reply_markup=kb_today())
        return

    # ── Отчёт ──────────────────────────────────
    if data_cb == "view_report":
        report = msg_report(store)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(
            f"📋 *Отчёт — скопируй и отправь:*\n\n`{report}`",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # ── Неделя ─────────────────────────────────
    if data_cb == "view_week":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(msg_week(store), parse_mode="Markdown", reply_markup=kb)
        return

    # ── Ручной ввод — шаг 1: выбор даты ───────
    if data_cb == "manual_start":
        await query.edit_message_text(
            "✏️ *Добавить вручную*\n\nВыбери дату:",
            parse_mode="Markdown",
            reply_markup=kb_manual_date(),
        )
        return

    if data_cb == "mdate_custom":
        context.user_data["waiting"] = "date"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(
            "📝 Введи дату в формате *ДД.ММ.ГГГГ*\nНапример: `15.06.2026`",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data_cb.startswith("mdate_"):
        date_key = data_cb.replace("mdate_", "")
        context.user_data["manual_date"] = date_key
        context.user_data["waiting"] = None
        try:
            d = datetime.strptime(date_key, "%Y-%m-%d")
            date_label = d.strftime("%d.%m.%Y")
        except Exception:
            date_label = date_key
        await query.edit_message_text(
            f"✏️ *Дата: {date_label}*\n\nВыбери тип действия:",
            parse_mode="Markdown",
            reply_markup=kb_manual_action(),
        )
        return

    # ── Ручной ввод — шаг 2: выбор типа ───────
    if data_cb.startswith("mact_"):
        key = data_cb.replace("mact_", "")
        if key not in ACTIONS:
            return
        context.user_data["manual_key"] = key
        context.user_data["waiting"] = "count"
        date_key = context.user_data.get("manual_date", today_key())
        try:
            d = datetime.strptime(date_key, "%Y-%m-%d")
            date_label = d.strftime("%d.%m.%Y")
        except Exception:
            date_label = date_key
        info = ACTIONS[key]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(
            f"✏️ *{info['emoji']} {info['label']}* — {date_label}\n\n"
            f"Введи количество _(например: 5)_:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    waiting = context.user_data.get("waiting")
    if not waiting:
        return

    text = update.message.text.strip()

    # ── Ожидаем дату ───────────────────────────
    if waiting == "date":
        try:
            d = datetime.strptime(text, "%d.%m.%Y")
            date_key = d.strftime("%Y-%m-%d")
        except ValueError:
            await update.message.reply_text("⚠️ Неверный формат. Введи дату как *ДД.ММ.ГГГГ*, например: `15.06.2026`", parse_mode="Markdown")
            return
        context.user_data["manual_date"] = date_key
        context.user_data["waiting"] = None
        await update.message.delete()
        await update.message.reply_text(
            f"✏️ *Дата: {d.strftime('%d.%m.%Y')}*\n\nВыбери тип действия:",
            parse_mode="Markdown",
            reply_markup=kb_manual_action(),
        )
        return

    # ── Ожидаем количество ─────────────────────
    if waiting == "count":
        try:
            count = int(text)
            if count <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Введи целое положительное число, например: *5*", parse_mode="Markdown")
            return

        manual_key = context.user_data.get("manual_key")
        date_key = context.user_data.get("manual_date", today_key())
        context.user_data["waiting"] = None
        context.user_data.pop("manual_key", None)
        context.user_data.pop("manual_date", None)

        all_data = load_all()
        store = get_store(all_data, user_id)
        day_data = get_day(store, date_key)
        day_data[manual_key] = day_data.get(manual_key, 0) + count
        save_all(all_data)

        info = ACTIONS[manual_key]
        earned = count * info["price"]
        try:
            d = datetime.strptime(date_key, "%Y-%m-%d")
            date_label = d.strftime("%d.%m.%Y")
        except Exception:
            date_label = date_key

        try:
            await update.message.delete()
        except Exception:
            pass

        await update.message.reply_text(
            f"✅ Добавлено *{count}* × {info['emoji']} {info['label']} за {date_label}\n"
            f"= *{earned:.2f} zl*",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
        return


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
