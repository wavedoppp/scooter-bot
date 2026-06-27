import os
import urllib.request
import urllib.error
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

TOKEN    = os.environ.get("TOKEN", "")
API_URL  = os.environ.get("API_URL", "https://scooter-crm-backend-production.up.railway.app")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
ALLOWED_USERS = []
GOAL = 250.0

ACTIONS = {
    "charge":  {"label": "Зарядить",    "price": 4.5, "emoji": "🟡"},
    "move":    {"label": "Переставить",  "price": 6.0, "emoji": "🟢"},
    "battery": {"label": "Батарейка",    "price": 3.0, "emoji": "🔵"},
    "broken":  {"label": "Сломан",       "price": 5.0, "emoji": "🔴"},
    "deploy":  {"label": "Выставить",    "price": 1.5, "emoji": "⚪"},
}


# ─── API HELPERS ──────────────────────────────────────────────────────────────

def api_get(path: str, user_id: int) -> dict:
    url = API_URL + path
    req = urllib.request.Request(url, headers={"x-init-data": f"bot_{user_id}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def api_post(path: str, user_id: int, data: dict) -> dict:
    url = API_URL + path
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"x-init-data": f"bot_{user_id}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def register_user(user_id: int):
    """Регистрирует юзера в базе (просто делает запрос /summary)."""
    try:
        api_get("/summary", user_id)
    except Exception:
        pass


def get_all_registered_users() -> list:
    """Возвращает всех юзеров из CRM базы."""
    try:
        url = API_URL + "/admin/users"
        req = urllib.request.Request(url, headers={"x-admin-id": str(ADMIN_ID)})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return []


# ─── BUILD UI ─────────────────────────────────────────────────────────────────

def build_progress_bar(current: float, goal: float, length: int = 14) -> str:
    ratio = min(current / goal, 1.0)
    filled = int(ratio * length)
    return f"[{'█' * filled}{'░' * (length - filled)}] {ratio*100:.0f}%"


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def calc_money(data: dict) -> float:
    return sum(data.get(k, 0) * ACTIONS[k]["price"] for k in ACTIONS)


def kb_main() -> InlineKeyboardMarkup:
    buttons = []
    if WEBAPP_URL:
        buttons.append([InlineKeyboardButton("🚀 Открыть CRM", web_app=WebAppInfo(url=WEBAPP_URL))])
    buttons += [
        [InlineKeyboardButton("📊 Сегодня",          callback_data="view_today")],
        [InlineKeyboardButton("✏️ Добавить вручную", callback_data="manual_start")],
        [InlineKeyboardButton("📋 Отчёт",            callback_data="view_report")],
        [InlineKeyboardButton("📅 Неделя",           callback_data="view_week")],
    ]
    return InlineKeyboardMarkup(buttons)


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
        [InlineKeyboardButton("⚪ Выставить +1.5",    callback_data="act_deploy")],
        [
            InlineKeyboardButton("↩️ Отменить",       callback_data="act_undo"),
            InlineKeyboardButton("🗑 Сброс дня",      callback_data="act_reset"),
        ],
        [InlineKeyboardButton("🏠 Главное меню",      callback_data="go_main")],
    ])


def kb_manual_date() -> InlineKeyboardMarkup:
    today = datetime.now().date()
    y = today - timedelta(days=1)
    d2 = today - timedelta(days=2)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📅 Сегодня ({today.strftime('%d.%m')})",    callback_data=f"mdate_{today.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton(f"📅 Вчера ({y.strftime('%d.%m')})",          callback_data=f"mdate_{y.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton(f"📅 Позавчера ({d2.strftime('%d.%m')})",     callback_data=f"mdate_{d2.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton("📝 Ввести дату вручную",                     callback_data="mdate_custom")],
        [InlineKeyboardButton("🏠 Главное меню",                            callback_data="go_main")],
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

def msg_main(summary: dict) -> str:
    today_money = summary.get("today_money", 0)
    week_money  = summary.get("week_money", 0)
    return (
        "👋 *Привет! Выбери раздел:*\n\n"
        f"💰 Сегодня: *{today_money:.2f} zl*\n"
        f"📅 За неделю: *{week_money:.2f} zl*"
    )


def msg_today(summary: dict) -> str:
    data        = summary.get("today", {})
    total_count = sum(data.get(k, 0) for k in ACTIONS)
    total_money = summary.get("today_money", 0)
    remaining   = max(GOAL - total_money, 0)

    lines = [f"📊 *Сегодня — {datetime.now().strftime('%d.%m.%Y')}*", ""]
    for key, info in ACTIONS.items():
        count  = data.get(key, 0)
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


def msg_week(days: list) -> str:
    today  = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    lines  = [f"📅 *Неделя {monday.strftime('%d.%m')} — {today.strftime('%d.%m.%Y')}*", ""]

    day_map = {d["date"]: d["total"] for d in days}
    week_total = 0.0
    for i in range(7):
        day = monday + timedelta(days=i)
        if day > today:
            break
        key    = day.strftime("%Y-%m-%d")
        money  = day_map.get(key, 0.0)
        week_total += money
        name   = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()]
        marker = " ← сегодня" if day == today else ""
        bar    = "█" * int(money / 20) if money > 0 else "·"
        lines.append(f"*{name} {day.strftime('%d.%m')}*: {money:.2f} zl {bar}{marker}")

    lines += ["", f"💰 *Итого за неделю: {week_total:.2f} zl*"]
    return "\n".join(lines)


def msg_report(summary: dict, week_money: float) -> str:
    data       = summary.get("today", {})
    date_str   = datetime.now().strftime("%d.%m.%Y")
    total_money = summary.get("today_money", 0)
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
    register_user(user_id)
    context.user_data.clear()
    try:
        summary = api_get("/summary", user_id)
    except Exception:
        summary = {"today": {}, "today_money": 0, "week_money": 0}
    await update.message.reply_text(msg_main(summary), parse_mode="Markdown", reply_markup=kb_main())


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    cb = query.data

    # ── Главное меню ───────────────────────────
    if cb == "go_main":
        context.user_data.clear()
        try:
            summary = api_get("/summary", user_id)
        except Exception:
            summary = {"today": {}, "today_money": 0, "week_money": 0}
        await query.edit_message_text(msg_main(summary), parse_mode="Markdown", reply_markup=kb_main())
        return

    # ── Сегодня ────────────────────────────────
    if cb == "view_today":
        try:
            summary = api_get("/summary", user_id)
        except Exception:
            summary = {"today": {}, "today_money": 0, "week_money": 0}
        await query.edit_message_text(msg_today(summary), parse_mode="Markdown", reply_markup=kb_today())
        return

    # ── Действия сегодня ───────────────────────
    if cb.startswith("act_"):
        action = cb.replace("act_", "")

        if action == "reset":
            # Удаляем все записи за сегодня
            try:
                api_post("/day/reset", user_id, {"date": today_key()})
            except Exception:
                pass
            context.user_data["history"] = []

        elif action == "undo":
            history: list = context.user_data.get("history", [])
            if history:
                last = history.pop()
                try:
                    api_post("/entry/undo", user_id, {"date": today_key(), "action": last})
                except Exception:
                    pass
                context.user_data["history"] = history

        elif action in ACTIONS:
            try:
                api_post("/entry", user_id, {"date": today_key(), "action": action, "count": 1})
                history: list = context.user_data.get("history", [])
                history.append(action)
                context.user_data["history"] = history[-100:]
            except Exception:
                pass

        try:
            summary = api_get("/summary", user_id)
        except Exception:
            summary = {"today": {}, "today_money": 0, "week_money": 0}
        await query.edit_message_text(msg_today(summary), parse_mode="Markdown", reply_markup=kb_today())
        return

    # ── Отчёт ──────────────────────────────────
    if cb == "view_report":
        try:
            summary = api_get("/summary", user_id)
            week_money = summary.get("week_money", 0)
        except Exception:
            summary = {"today": {}, "today_money": 0}
            week_money = 0
        report = msg_report(summary, week_money)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(
            f"📋 *Отчёт — скопируй и отправь:*\n\n`{report}`",
            parse_mode="Markdown", reply_markup=kb,
        )
        return

    # ── Неделя ─────────────────────────────────
    if cb == "view_week":
        today  = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        try:
            days = api_get(f"/days?from_date={monday.strftime('%Y-%m-%d')}&to_date={today.strftime('%Y-%m-%d')}", user_id)
        except Exception:
            days = []
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(msg_week(days), parse_mode="Markdown", reply_markup=kb)
        return

    # ── Ручной ввод — шаг 1 ────────────────────
    if cb == "manual_start":
        await query.edit_message_text(
            "✏️ *Добавить вручную*\n\nВыбери дату:",
            parse_mode="Markdown", reply_markup=kb_manual_date(),
        )
        return

    if cb == "mdate_custom":
        context.user_data["waiting"] = "date"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(
            "📝 Введи дату в формате *ДД.ММ.ГГГГ*\nНапример: `15.06.2026`",
            parse_mode="Markdown", reply_markup=kb,
        )
        return

    if cb.startswith("mdate_"):
        date_key = cb.replace("mdate_", "")
        context.user_data["manual_date"] = date_key
        context.user_data["waiting"] = None
        d = datetime.strptime(date_key, "%Y-%m-%d")
        await query.edit_message_text(
            f"✏️ *Дата: {d.strftime('%d.%m.%Y')}*\n\nВыбери тип действия:",
            parse_mode="Markdown", reply_markup=kb_manual_action(),
        )
        return

    # ── Ручной ввод — шаг 2 ────────────────────
    if cb.startswith("mact_"):
        key = cb.replace("mact_", "")
        if key not in ACTIONS:
            return
        context.user_data["manual_key"] = key
        context.user_data["waiting"] = "count"
        date_key = context.user_data.get("manual_date", today_key())
        d = datetime.strptime(date_key, "%Y-%m-%d")
        info = ACTIONS[key]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_main")]])
        await query.edit_message_text(
            f"✏️ *{info['emoji']} {info['label']}* — {d.strftime('%d.%m.%Y')}\n\nВведи количество _(например: 5)_:",
            parse_mode="Markdown", reply_markup=kb,
        )
        return


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    waiting = context.user_data.get("waiting")
    if not waiting:
        return

    text = update.message.text.strip()

    if waiting == "date":
        try:
            d = datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text("⚠️ Формат: *ДД.ММ.ГГГГ*, например: `15.06.2026`", parse_mode="Markdown")
            return
        context.user_data["manual_date"] = d.strftime("%Y-%m-%d")
        context.user_data["waiting"] = None
        try:
            await update.message.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"✏️ *Дата: {d.strftime('%d.%m.%Y')}*\n\nВыбери тип действия:",
            parse_mode="Markdown", reply_markup=kb_manual_action(),
        )
        return

    if waiting == "count":
        try:
            count = int(text)
            if count <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Введи целое положительное число, например: *5*", parse_mode="Markdown")
            return

        manual_key = context.user_data.pop("manual_key", None)
        date_key   = context.user_data.pop("manual_date", today_key())
        context.user_data["waiting"] = None

        try:
            api_post("/entry", user_id, {"date": date_key, "action": manual_key, "count": count})
        except Exception as e:
            await update.message.reply_text(f"⚠️ Ошибка: {e}")
            return

        info   = ACTIONS[manual_key]
        earned = count * info["price"]
        d      = datetime.strptime(date_key, "%Y-%m-%d")

        try:
            await update.message.delete()
        except Exception:
            pass

        await update.message.reply_text(
            f"✅ Добавлено *{count}* × {info['emoji']} {info['label']} за {d.strftime('%d.%m.%Y')}\n= *{earned:.2f} zl*",
            parse_mode="Markdown", reply_markup=kb_main(),
        )
        return


# ─── ADMIN ────────────────────────────────────────────────────────────────────

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👤 *{name}*\n🆔 Твой ID: `{uid}`\n\nДобавь в Railway → Variables → `ADMIN_ID`",
        parse_mode="Markdown"
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_ID == 0:
        await update.message.reply_text("⚠️ Установи ADMIN_ID в переменных Railway.")
        return
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Только для админа.")
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Использование: `/broadcast Текст`", parse_mode="Markdown")
        return

    users = get_all_registered_users()
    if not users:
        await update.message.reply_text("Нет юзеров в базе.")
        return

    msg  = await update.message.reply_text(f"📤 Отправляю {len(users)} юзерам...")
    sent = failed = 0
    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Новость:*\n\n{text}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1

    await msg.edit_text(f"✅ Отправлено: *{sent}*\n❌ Не доставлено: *{failed}*", parse_mode="Markdown")


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_ID and user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Только для админа.")
        return
    try:
        url = API_URL + "/admin/backup"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        text = (
            f"🗄 *Бекап базы данных*\n\n"
            f"📅 {data['exported_at']}\n"
            f"👥 Юзеров: *{data['total_users']}*\n"
            f"📝 Записей: *{data['total_records']}*\n\n"
            f"Полный JSON:"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

        # Отправляем JSON файлом
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        from io import BytesIO
        await update.message.reply_document(
            document=BytesIO(json_bytes),
            filename=filename,
            caption=f"💾 Бекап от {data['exported_at']}"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {e}")


async def cmd_adminstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    users = get_all_registered_users()
    await update.message.reply_text(
        f"📊 *Статистика бота*\n\n👥 Всего юзеров: *{len(users)}*",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("adminstats", cmd_adminstats))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
