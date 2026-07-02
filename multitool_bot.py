"""
Arbitrage Multitool Bot
"""
import asyncio
import json
import os
import random
import re
import string
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import io
import struct

from faker import Faker
from PIL import Image, ImageFilter
import piexif
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("MULTITOOL_TOKEN", "8616805879:AAHTQps2FGnHWlBBqzywsPS_dIPwb-3iB3E")
STORAGE_FILE = "multitool_data.json"
TG_MAX_BYTES = 45 * 1024 * 1024
NOTIFY_USER_ID = int(os.environ.get("NOTIFY_USER_ID", "7593291117"))
DOMAIN_CHECK_INTERVAL_SEC = 30 * 60  # проверять доменлист раз в 30 минут

# ── Conversation states ────────────────────────────────────────────────────────
(
    WAITING_PREFIX, WAITING_COUNT,          # ID generator
    WAITING_URL,                            # Video download
    WAITING_IP,                             # IP checker
    WAITING_DOMAIN,                          # FB domain checker
    WAITING_ROI_SPENT, WAITING_ROI_EARNED,  # ROI
    WAITING_PASS_LEN,                       # Password
    WAITING_FAKE_COUNTRY,                   # Fake data
    WAITING_SHORT_URL,                      # URL shortener
    WAITING_UTM_URL, WAITING_UTM_SOURCE,    # UTM
    WAITING_UTM_MEDIUM, WAITING_UTM_CAMPAIGN,
    WAITING_ACC_PLATFORM, WAITING_ACC_LOGIN, WAITING_ACC_STATUS,  # Accounts
    WAITING_CAMP_NAME, WAITING_CAMP_SPENT, WAITING_CAMP_EARNED,   # Campaigns
    WAITING_CAMP_UPDATE_SPENT, WAITING_CAMP_UPDATE_EARNED,
    WAITING_UNIQUE_MEDIA,                   # Uniqualizer
    WAITING_WATCH_DOMAIN,                   # Domain monitor: add domain
) = range(24)

MENU_BUTTONS = {
    "🆔 ID компании", "📥 Скачать видео", "🌍 IP / Прокси", "🕐 Тайм-зоны",
    "🔐 Пароль", "📝 Фейк-данные", "🚫 Чекер домена FB", "🧮 ROI",
    "🔗 Укоротить ссылку", "📋 UTM-метки", "📊 Аккаунты", "📈 Кампании",
    "🗂 История ID", "🎨 Уникализатор", "📡 Мониторинг доменов",
}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🆔 ID компании"),      KeyboardButton("🔐 Пароль")],
        [KeyboardButton("📥 Скачать видео"),     KeyboardButton("🌍 IP / Прокси")],
        [KeyboardButton("🕐 Тайм-зоны"),         KeyboardButton("🚫 Чекер домена FB")],
        [KeyboardButton("🧮 ROI"),               KeyboardButton("📈 Кампании")],
        [KeyboardButton("📝 Фейк-данные"),       KeyboardButton("📊 Аккаунты")],
        [KeyboardButton("🔗 Укоротить ссылку"),  KeyboardButton("📋 UTM-метки")],
        [KeyboardButton("🎨 Уникализатор"),      KeyboardButton("📡 Мониторинг доменов")],
        [KeyboardButton("🗂 История ID")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# ── Storage ────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save(data: dict):
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _user(uid: int) -> dict:
    d = _load()
    return d.get(str(uid), {})

def _set_user(uid: int, udata: dict):
    d = _load()
    d[str(uid)] = udata
    _save(d)

def _now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _fetch(url: str, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        raw = r.read().decode()
    try:
        return json.loads(raw)
    except Exception:
        return raw

async def fetch(url: str, timeout=10):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch, url, timeout)

# ── Helpers ────────────────────────────────────────────────────────────────────

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="cancel")]])

async def _menu_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перехват нажатия кнопки меню внутри диалога."""
    return await handle_menu(update, context)

def is_menu(text: str) -> bool:
    return text in MENU_BUTTONS

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1 — ID генератор
# ══════════════════════════════════════════════════════════════════════════════

def _gen_id(prefix: str) -> str:
    """Префикс (буквы) + случайный числовой суффикс, сгруппированный блоками по 4."""
    digits_needed = 16 - len(prefix)
    suffix = "".join(random.choices(string.digits, k=digits_needed))
    # группируем цифры по 4 через дефис для читаемости
    groups = [suffix[i:i + 4] for i in range(0, len(suffix), 4)]
    return prefix + "-" + "-".join(groups)

def _validate_prefix(text: str):
    c = text.strip().upper()
    return c if c.isalpha() and 1 <= len(c) <= 4 else None

def _save_ids(uid: int, ids: list, prefix: str):
    u = _user(uid)
    u.setdefault("company_ids", [])
    for i in ids:
        u["company_ids"].append({"id": i, "prefix": prefix, "created_at": _now()})
    _set_user(uid, u)

def _del_id(uid: int, idx: int):
    u = _user(uid)
    recs = u.get("company_ids", [])
    if 0 <= idx < len(recs):
        recs.pop(idx)
    u["company_ids"] = recs
    _set_user(uid, u)

def _fmt_ids(ids: list, prefix: str) -> str:
    lines = [f"🆔 *{len(ids)} ID для* `{prefix}`", "_Нажми чтобы скопировать:_", ""]
    lines += [f"`{i}`" for i in ids]
    lines += ["", "💾 _Сохранено в историю_"]
    return "\n".join(lines)

def _fmt_history_page(records: list, page: int, per=5):
    total = len(records)
    pages = max(1, -(-total // per))
    chunk = list(reversed(records))[page*per:(page+1)*per]
    real_idx = list(reversed(range(total)))[page*per:(page+1)*per]
    lines = [f"📋 *История ID* ({total} шт) · стр {page+1}/{pages}", ""]
    for rec, _ in zip(chunk, real_idx):
        lines += [f"*{rec['prefix']}* · _{rec['created_at']}_", f"`{rec['id']}`", ""]
    btns = [[InlineKeyboardButton(f"🗑 {rec['id'][:12]}…", callback_data=f"del_{ri}_{page}")]
            for rec, ri in zip(chunk, real_idx)]
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"hist_{page-1}"))
    if page < pages-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"hist_{page+1}"))
    if nav: btns.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(btns) if btns else None

async def tool_id_start(update: Update, context):
    await update.message.reply_text(
        "🆔 *Генератор ID*\n\nВведи префикс (1–4 латинских буквы):",
        parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_PREFIX

async def receive_prefix(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    prefix = _validate_prefix(update.message.text)
    if not prefix:
        await update.message.reply_text("⚠️ Только латиница, 1–4 буквы:", reply_markup=cancel_keyboard())
        return WAITING_PREFIX
    context.user_data["prefix"] = prefix
    await update.message.reply_text(
        f"🔢 Сколько ID сгенерировать для `{prefix}`?\n_Введи число (1–50):_",
        parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_COUNT

async def receive_count(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip()
    if not t.isdigit() or not 1 <= int(t) <= 50:
        await update.message.reply_text("⚠️ Число от 1 до 50:", reply_markup=cancel_keyboard())
        return WAITING_COUNT
    prefix = context.user_data.get("prefix", "")
    ids = [_gen_id(prefix) for _ in range(int(t))]
    _save_ids(update.effective_user.id, ids, prefix)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "🔄 Ещё с тем же префиксом", callback_data=f"regen_{prefix}_{t}")]])
    await update.message.reply_text(_fmt_ids(ids, prefix), parse_mode="Markdown", reply_markup=kb)
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2 — Скачивание видео
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED = ("youtube.com", "youtu.be", "tiktok.com", "facebook.com", "fb.watch", "instagram.com")

def _has_ffmpeg():
    import shutil; return bool(shutil.which("ffmpeg"))

async def _download_video(url, out_dir):
    import yt_dlp
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": os.path.join(out_dir, "%(title).50s.%(ext)s"),
        "quiet": True, "no_warnings": True,
        "merge_output_format": "mp4", "noplaylist": True,
    }
    def _dl():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "видео")
            files = list(Path(out_dir).glob("*.mp4")) + list(Path(out_dir).glob("*.webm"))
            if not files: raise FileNotFoundError("файл не найден")
            return str(files[0]), title
    return await asyncio.get_event_loop().run_in_executor(None, _dl)

async def _split_video(src, out_dir):
    import subprocess
    def _split():
        probe = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1", src],
            capture_output=True, text=True, check=True)
        total = float(probe.stdout.strip())
        n = int(os.path.getsize(src) / TG_MAX_BYTES) + 1
        step = total / n
        parts = []
        for i in range(n):
            p = os.path.join(out_dir, f"part{i+1:02d}.mp4")
            subprocess.run(["ffmpeg","-y","-ss",str(i*step),"-i",src,
                "-t",str(step),"-c","copy","-avoid_negative_ts","make_zero",p],
                capture_output=True, check=True)
            parts.append(p)
        return parts
    return await asyncio.get_event_loop().run_in_executor(None, _split)

async def tool_video_start(update: Update, context):
    await update.message.reply_text(
        "📥 *Скачать видео*\n\nОтправь ссылку:\n• YouTube\n• TikTok\n• Facebook\n• Instagram",
        parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_URL

async def receive_url(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    url = update.message.text.strip()
    if not url.startswith("http") or not any(h in url for h in SUPPORTED):
        await update.message.reply_text("⚠️ Неподдерживаемая ссылка. Попробуй ещё:", reply_markup=cancel_keyboard())
        return WAITING_URL
    msg = await update.message.reply_text("⏳ Скачиваю...")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            path, title = await _download_video(url, tmp)
            size = os.path.getsize(path)
            if size <= TG_MAX_BYTES:
                await msg.edit_text(f"📤 Загружаю: _{title}_", parse_mode="Markdown")
                with open(path, "rb") as f:
                    await update.message.reply_video(f, caption=f"🎬 {title}", supports_streaming=True)
                await msg.delete()
            elif not _has_ffmpeg():
                await msg.edit_text(f"❌ Видео {size//1024//1024} МБ — слишком большое, ffmpeg не установлен.")
            else:
                n = size // TG_MAX_BYTES + 1
                await msg.edit_text(f"✂️ Видео {size//1024//1024} МБ — режу на {n} части...")
                parts_dir = os.path.join(tmp, "p"); os.makedirs(parts_dir)
                parts = await _split_video(path, parts_dir)
                for i, p in enumerate(parts, 1):
                    await msg.edit_text(f"📤 Часть {i}/{len(parts)}: _{title}_", parse_mode="Markdown")
                    with open(p, "rb") as f:
                        await update.message.reply_video(f, caption=f"🎬 {title} · {i}/{len(parts)}", supports_streaming=True)
                await msg.delete()
        except Exception as e:
            err = str(e)
            if "Private" in err or "login" in err.lower(): txt = "❌ Видео приватное."
            elif "Unsupported" in err: txt = "❌ Ссылка не поддерживается."
            else: txt = f"❌ Ошибка:\n`{err[:200]}`"
            await msg.edit_text(txt, parse_mode="Markdown")
    await update.message.reply_text("📥 Отправь ещё ссылку или выбери инструмент:", reply_markup=MAIN_KEYBOARD)
    return WAITING_URL

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3 — IP / Прокси checker
# ══════════════════════════════════════════════════════════════════════════════

async def tool_ip_start(update: Update, context):
    await update.message.reply_text(
        "🌍 *IP / Прокси чекер*\n\nВведи IP-адрес или домен:",
        parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_IP

async def receive_ip(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    target = update.message.text.strip()
    msg = await update.message.reply_text("🔍 Проверяю...")
    try:
        data = await fetch(f"http://ip-api.com/json/{urllib.parse.quote(target)}?fields=status,message,country,countryCode,regionName,city,isp,org,proxy,hosting,query")
        if data.get("status") == "fail":
            await msg.edit_text(f"❌ Ошибка: {data.get('message', 'неизвестно')}")
        else:
            flags = []
            if data.get("proxy"): flags.append("🔴 Прокси")
            if data.get("hosting"): flags.append("🟠 Хостинг/VPN")
            if not flags: flags.append("🟢 Чистый")
            lines = [
                f"🌍 *Результат для* `{data.get('query')}`",
                "",
                f"🏳️ Страна: *{data.get('country')} ({data.get('countryCode')})*",
                f"📍 Регион: {data.get('regionName')} · {data.get('city')}",
                f"🏢 ISP: {data.get('isp')}",
                f"🏗 Орг: {data.get('org')}",
                "",
                f"Тип: {' / '.join(flags)}",
            ]
            await msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_keyboard())
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка запроса: `{e}`", parse_mode="Markdown")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 4 — Тайм-зоны
# ══════════════════════════════════════════════════════════════════════════════

TIMEZONES = [
    ("🇺🇸 Нью-Йорк",   "America/New_York"),
    ("🇺🇸 Лос-Анджелес","America/Los_Angeles"),
    ("🇬🇧 Лондон",      "Europe/London"),
    ("🇩🇪 Берлин",      "Europe/Berlin"),
    ("🇵🇱 Варшава",     "Europe/Warsaw"),
    ("🇺🇦 Киев",        "Europe/Kyiv"),
    ("🇹🇷 Стамбул",     "Europe/Istanbul"),
    ("🇦🇪 Дубай",       "Asia/Dubai"),
    ("🇹🇭 Бангкок",     "Asia/Bangkok"),
    ("🇸🇬 Сингапур",    "Asia/Singapore"),
    ("🇯🇵 Токио",       "Asia/Tokyo"),
    ("🇦🇺 Сидней",      "Australia/Sydney"),
]

async def tool_tz(update: Update, context):
    now_utc = datetime.utcnow()
    lines = ["🕐 *Текущее время по зонам:*", ""]
    for label, tz in TIMEZONES:
        local = datetime.now(ZoneInfo(tz))
        lines.append(f"{label}: *{local.strftime('%H:%M')}* _{local.strftime('%d.%m')}_")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data="tz_refresh")]])
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 5 — Генератор паролей
# ══════════════════════════════════════════════════════════════════════════════

def _gen_password(length: int, symbols: bool, digits: bool) -> str:
    pool = string.ascii_letters
    if digits: pool += string.digits
    if symbols: pool += "!@#$%^&*()-_=+[]"
    pwd = list(random.choices(pool, k=length))
    if digits: pwd[random.randint(0,length-1)] = random.choice(string.digits)
    if symbols: pwd[random.randint(0,length-1)] = random.choice("!@#$%^&*")
    random.shuffle(pwd)
    return "".join(pwd)

def _pass_keyboard(length=16, sym=True, dig=True):
    sym_lbl = f"{'✅' if sym else '☐'} Символы"
    dig_lbl = f"{'✅' if dig else '☐'} Цифры"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("8",  callback_data=f"pass_8_{int(sym)}_{int(dig)}"),
         InlineKeyboardButton("12", callback_data=f"pass_12_{int(sym)}_{int(dig)}"),
         InlineKeyboardButton("16", callback_data=f"pass_16_{int(sym)}_{int(dig)}"),
         InlineKeyboardButton("24", callback_data=f"pass_24_{int(sym)}_{int(dig)}"),
         InlineKeyboardButton("32", callback_data=f"pass_32_{int(sym)}_{int(dig)}")],
        [InlineKeyboardButton(sym_lbl, callback_data=f"pass_{length}_{int(not sym)}_{int(dig)}"),
         InlineKeyboardButton(dig_lbl, callback_data=f"pass_{length}_{int(sym)}_{int(not dig)}")],
        [InlineKeyboardButton("🎲 Сгенерировать", callback_data=f"pass_gen_{length}_{int(sym)}_{int(dig)}")],
    ])

async def tool_pass(update: Update, context):
    await update.message.reply_text(
        "🔐 *Генератор паролей*\n\nВыбери длину и параметры:",
        parse_mode="Markdown", reply_markup=_pass_keyboard())
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 6 — Фейк-данные для регистрации
# ══════════════════════════════════════════════════════════════════════════════

FAKE_LOCALES = {
    "🇺🇦 Украина": "uk_UA",
    "🇵🇱 Польша":  "pl_PL",
    "🇺🇸 США":     "en_US",
    "🇬🇧 Великобритания": "en_GB",
    "🇩🇪 Германия":"de_DE",
    "🇫🇷 Франция": "fr_FR",
}

def _fake_keyboard():
    btns = [[InlineKeyboardButton(k, callback_data=f"fake_{v}")] for k, v in FAKE_LOCALES.items()]
    return InlineKeyboardMarkup(btns)

def _gen_fake(locale: str) -> str:
    f = Faker(locale)
    dob = f.date_of_birth(minimum_age=18, maximum_age=45)
    lines = [
        "📝 *Фейк-данные для регистрации:*", "",
        f"👤 Имя: `{f.first_name()}`",
        f"👤 Фамилия: `{f.last_name()}`",
        f"🎂 Дата рождения: `{dob.strftime('%d.%m.%Y')}`",
        f"📍 Город: `{f.city()}`",
        f"🏠 Адрес: `{f.street_address()}`",
        f"📮 Индекс: `{f.postcode()}`",
        f"📞 Телефон: `{f.phone_number()}`",
        f"📧 Email: `{f.email()}`",
        "",
        "_Нажми на поле чтобы скопировать_",
    ]
    return "\n".join(lines)

async def tool_fake(update: Update, context):
    await update.message.reply_text(
        "📝 *Фейк-данные*\n\nВыбери страну:",
        parse_mode="Markdown", reply_markup=_fake_keyboard())
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 7 — Чекер домена (риск бана Facebook)
# ══════════════════════════════════════════════════════════════════════════════
#
# ВАЖНО: у Facebook нет публичного API "забанен домен или нет".
# Graph API scrape без App-токена всегда возвращает одну и ту же generic-ошибку
# независимо от статуса, а l.facebook.com/l.php показывает interstitial-предупреждение
# ДЛЯ ЛЮБОГО внешнего домена — это не сигнал бана.
# Поэтому чекер работает по best-effort принципу: собирает публичные сигналы риска
# (возраст домена, SSL, редиректы, доступность) и даёт оценку риска, а не факт бана.
# 100% точный ответ даёт только реальный тест в Ads Manager / Business Manager.

import ssl
import socket
import http.client

def _clean_domain(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"^https?://", "", t)
    t = t.split("/")[0]
    return t

def _check_dns(domain: str) -> bool:
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False

def _check_domain_age_days(domain: str):
    try:
        req = urllib.request.Request(f"https://rdap.org/domain/{domain}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        for ev in data.get("events", []):
            if ev.get("eventAction") == "registration":
                reg_date = datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))
                age = (datetime.now(reg_date.tzinfo) - reg_date).days
                return age
        return None
    except Exception:
        return None

def _check_https(domain: str) -> bool:
    try:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(domain, timeout=6, context=ctx)
        conn.request("HEAD", "/")
        conn.getresponse()
        return True
    except Exception:
        return False

def _check_redirects(domain: str) -> int:
    """Считает цепочку редиректов — много редиректов = типичный паттерн cloaking-страниц."""
    try:
        url = f"https://{domain}/"
        count = 0
        for _ in range(6):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=6)
            if r.geturl() != url:
                count += 1
                url = r.geturl()
            else:
                break
        return count
    except Exception:
        return 0

async def _run_domain_check(domain: str) -> dict:
    loop = asyncio.get_event_loop()
    dns_ok = await loop.run_in_executor(None, _check_dns, domain)
    if not dns_ok:
        return {"dns": False}

    age_days, https_ok, redirects = await asyncio.gather(
        loop.run_in_executor(None, _check_domain_age_days, domain),
        loop.run_in_executor(None, _check_https, domain),
        loop.run_in_executor(None, _check_redirects, domain),
    )
    return {"dns": True, "age_days": age_days, "https": https_ok, "redirects": redirects}

def _score_domain(r: dict):
    """Возвращает (risk_points, level) где level: down / low / medium / high."""
    if not r.get("dns"):
        return None, "down"
    risk_points = 0
    age = r.get("age_days")
    if age is not None:
        if age < 14: risk_points += 2
        elif age < 60: risk_points += 1
    else:
        risk_points += 1
    if not r.get("https"): risk_points += 2
    redirects = r.get("redirects", 0)
    if redirects >= 2: risk_points += 2
    elif redirects == 1: risk_points += 1

    if risk_points >= 4: level = "high"
    elif risk_points >= 2: level = "medium"
    else: level = "low"
    return risk_points, level

LEVEL_LABEL = {"down": "❌ Не резолвится", "high": "🔴 Высокий риск", "medium": "🟡 Средний риск", "low": "🟢 Низкий риск"}

def _format_domain_report(domain: str, r: dict) -> str:
    if not r.get("dns"):
        return f"🚫 *Чекер домена: FB*\n\n`{domain}`\n\n❌ Домен не резолвится (не существует или DNS недоступен)."

    risk_points = 0
    lines = [f"🚫 *Чекер домена: FB*", f"`{domain}`", ""]

    age = r.get("age_days")
    if age is not None:
        if age < 14:
            lines.append(f"📅 Возраст: *{age} дн.* 🔴 (очень новый — высокий риск для рекламы)")
            risk_points += 2
        elif age < 60:
            lines.append(f"📅 Возраст: *{age} дн.* 🟡 (молодой домен)")
            risk_points += 1
        else:
            years = age // 365
            lines.append(f"📅 Возраст: *{age} дн.* (~{years} г.) 🟢")
    else:
        lines.append("📅 Возраст: не удалось определить (WHOIS скрыт)")
        risk_points += 1

    if r.get("https"):
        lines.append("🔒 HTTPS: 🟢 работает")
    else:
        lines.append("🔒 HTTPS: 🔴 недоступен")
        risk_points += 2

    redirects = r.get("redirects", 0)
    if redirects >= 2:
        lines.append(f"🔀 Редиректы: *{redirects}* 🔴 (похоже на cloaking)")
        risk_points += 2
    elif redirects == 1:
        lines.append(f"🔀 Редиректы: *{redirects}* 🟡")
        risk_points += 1
    else:
        lines.append("🔀 Редиректы: 0 🟢")

    if risk_points >= 4:
        verdict = "🔴 *Высокий риск* — вероятность блокировки/флага у Facebook повышена"
    elif risk_points >= 2:
        verdict = "🟡 *Средний риск* — стоит тестировать осторожно"
    else:
        verdict = "🟢 *Низкий риск* — явных красных флагов не найдено"

    lines += ["", f"📊 Итог: {verdict}", "",
              "⚠️ _Это эвристическая оценка по публичным данным, НЕ официальная проверка бана в FB._\n"
              "_Facebook не даёт публичного API для проверки статуса домена — 100% точный ответ даёт только реальный тест в Ads Manager._"]
    return "\n".join(lines)

async def tool_domain_start(update: Update, context):
    await update.message.reply_text(
        "🚫 *Чекер домена (риск для Facebook)*\n\n"
        "Введи домен без https:// (например: `mysite.com`):\n\n"
        "_Проверяю: возраст домена, HTTPS, цепочку редиректов._",
        parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_DOMAIN

async def receive_domain(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    domain = _clean_domain(update.message.text)
    if not domain or "." not in domain:
        await update.message.reply_text("⚠️ Введи корректный домен, например `mysite.com`:", parse_mode="Markdown", reply_markup=cancel_keyboard())
        return WAITING_DOMAIN

    msg = await update.message.reply_text(f"🔍 Проверяю `{domain}`...", parse_mode="Markdown")
    try:
        result = await _run_domain_check(domain)
        text = _format_domain_report(domain, result)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 Добавить в мониторинг", callback_data=f"watch_add_{domain}")],
            [InlineKeyboardButton("🔄 Проверить ещё", callback_data="domain_again")],
        ])
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка проверки: `{e}`", parse_mode="Markdown")
    return ConversationHandler.END

# ── Мониторинг доменов (уведомления при ухудшении статуса) ─────────────────────

def _get_watched(uid=NOTIFY_USER_ID) -> list:
    return _user(uid).get("watched_domains", [])

def _set_watched(domains: list, uid=NOTIFY_USER_ID):
    u = _user(uid)
    u["watched_domains"] = domains
    _set_user(uid, u)

def _watch_keyboard(domains: list):
    btns = [[InlineKeyboardButton(f"🗑 {d['domain']} ({LEVEL_LABEL.get(d['level'],'?')})",
                                   callback_data=f"watch_del_{i}")]
            for i, d in enumerate(domains)]
    btns.append([InlineKeyboardButton("➕ Добавить домен", callback_data="watch_add_menu")])
    return InlineKeyboardMarkup(btns)

def _fmt_watch_list(domains: list) -> str:
    if not domains:
        return "📡 *Мониторинг доменов*\n\nСписок пуст. Добавь домен для отслеживания."
    lines = [f"📡 *Мониторинг доменов* ({len(domains)} шт)",
              f"_Проверка каждые {DOMAIN_CHECK_INTERVAL_SEC // 60} мин, уведомления при ухудшении статуса._", ""]
    for d in domains:
        lines.append(f"`{d['domain']}` — {LEVEL_LABEL.get(d['level'], '?')}  _(добавлен {d['added_at']})_")
    return "\n".join(lines)

async def tool_watch_list(update: Update, context):
    domains = _get_watched()
    await update.message.reply_text(_fmt_watch_list(domains), parse_mode="Markdown", reply_markup=_watch_keyboard(domains))
    return ConversationHandler.END

async def receive_watch_domain(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    domain = _clean_domain(update.message.text)
    if not domain or "." not in domain:
        await update.message.reply_text("⚠️ Введи корректный домен:", reply_markup=cancel_keyboard())
        return WAITING_WATCH_DOMAIN

    msg = await update.message.reply_text(f"🔍 Проверяю `{domain}` перед добавлением...", parse_mode="Markdown")
    result = await _run_domain_check(domain)
    _, level = _score_domain(result)

    domains = _get_watched()
    if any(d["domain"] == domain for d in domains):
        await msg.edit_text(f"⚠️ `{domain}` уже в мониторинге.", parse_mode="Markdown")
    else:
        domains.append({"domain": domain, "level": level, "added_at": _now()})
        _set_watched(domains)
        await msg.edit_text(
            f"✅ `{domain}` добавлен в мониторинг.\nТекущий статус: {LEVEL_LABEL.get(level,'?')}",
            parse_mode="Markdown",
        )
    await update.message.reply_text(_fmt_watch_list(domains), parse_mode="Markdown", reply_markup=_watch_keyboard(domains))
    return ConversationHandler.END

async def check_watched_domains_job(context: ContextTypes.DEFAULT_TYPE):
    """Фоновая задача: раз в N минут проверяет все домены и шлёт уведомление при ухудшении."""
    domains = _get_watched()
    if not domains:
        return
    changed = False
    for d in domains:
        try:
            result = await _run_domain_check(d["domain"])
            _, new_level = _score_domain(result)
        except Exception:
            continue

        old_level = d.get("level", "low")
        rank = {"low": 0, "medium": 1, "high": 2, "down": 3}
        if rank.get(new_level, 0) > rank.get(old_level, 0):
            try:
                await context.bot.send_message(
                    chat_id=NOTIFY_USER_ID,
                    text=(
                        f"⚠️ *Статус домена ухудшился!*\n\n"
                        f"`{d['domain']}`\n"
                        f"Было: {LEVEL_LABEL.get(old_level,'?')}\n"
                        f"Стало: {LEVEL_LABEL.get(new_level,'?')}\n\n"
                        f"Рекомендуется проверить домен вручную."
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        d["level"] = new_level
        changed = True
    if changed:
        _set_watched(domains)

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 8 — ROI калькулятор
# ══════════════════════════════════════════════════════════════════════════════

async def tool_roi(update: Update, context):
    await update.message.reply_text(
        "🧮 *ROI калькулятор*\n\nСколько вложено? (в любой валюте):",
        parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_ROI_SPENT

async def receive_roi_spent(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip().replace(",", ".")
    try:
        context.user_data["roi_spent"] = float(t)
    except ValueError:
        await update.message.reply_text("⚠️ Введи число:", reply_markup=cancel_keyboard())
        return WAITING_ROI_SPENT
    await update.message.reply_text("💰 Сколько получено?", reply_markup=cancel_keyboard())
    return WAITING_ROI_EARNED

async def receive_roi_earned(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip().replace(",", ".")
    try:
        earned = float(t)
    except ValueError:
        await update.message.reply_text("⚠️ Введи число:", reply_markup=cancel_keyboard())
        return WAITING_ROI_EARNED
    spent = context.user_data.get("roi_spent", 0)
    profit = earned - spent
    roi = (profit / spent * 100) if spent else 0
    margin = (profit / earned * 100) if earned else 0
    emoji = "🟢" if profit > 0 else "🔴"
    lines = [
        "🧮 *Результат ROI*", "",
        f"💸 Вложено:   `{spent:,.2f}`",
        f"💰 Получено:  `{earned:,.2f}`",
        f"{emoji} Профит:    `{profit:+,.2f}`",
        "",
        f"📊 ROI:       *{roi:.1f}%*",
        f"📐 Маржа:     *{margin:.1f}%*",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_keyboard())
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 9 — Укорачиватель ссылок
# ══════════════════════════════════════════════════════════════════════════════

async def tool_short(update: Update, context):
    await update.message.reply_text(
        "🔗 *Укоротить ссылку*\n\nОтправь URL:", parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_SHORT_URL

async def receive_short_url(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("⚠️ Ссылка должна начинаться с http://", reply_markup=cancel_keyboard())
        return WAITING_SHORT_URL
    msg = await update.message.reply_text("⏳ Сокращаю...")
    try:
        enc = urllib.parse.quote(url, safe="")
        short = await fetch(f"https://is.gd/create.php?format=simple&url={enc}", timeout=10)
        if isinstance(short, str) and short.startswith("http"):
            await msg.edit_text(
                f"🔗 *Короткая ссылка:*\n`{short}`\n\n_Оригинал: {url[:60]}{'…' if len(url)>60 else ''}_",
                parse_mode="Markdown", reply_markup=back_keyboard())
        else:
            await msg.edit_text("❌ Сервис недоступен. Попробуй позже.")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: `{e}`", parse_mode="Markdown")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 10 — UTM-метки
# ══════════════════════════════════════════════════════════════════════════════

async def tool_utm(update: Update, context):
    context.user_data.pop("utm", None)
    await update.message.reply_text(
        "📋 *UTM-генератор*\n\nВведи базовый URL:", parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_UTM_URL

async def receive_utm_url(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("⚠️ Должно начинаться с http://", reply_markup=cancel_keyboard())
        return WAITING_UTM_URL
    context.user_data["utm"] = {"url": url}
    await update.message.reply_text("📋 utm_source (например: facebook):", reply_markup=cancel_keyboard())
    return WAITING_UTM_SOURCE

async def receive_utm_source(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    context.user_data["utm"]["source"] = update.message.text.strip()
    await update.message.reply_text("📋 utm_medium (например: cpc):", reply_markup=cancel_keyboard())
    return WAITING_UTM_MEDIUM

async def receive_utm_medium(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    context.user_data["utm"]["medium"] = update.message.text.strip()
    await update.message.reply_text("📋 utm_campaign (название кампании):", reply_markup=cancel_keyboard())
    return WAITING_UTM_CAMPAIGN

async def receive_utm_campaign(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    utm = context.user_data.get("utm", {})
    utm["campaign"] = update.message.text.strip()
    params = urllib.parse.urlencode({
        "utm_source": utm.get("source",""),
        "utm_medium": utm.get("medium",""),
        "utm_campaign": utm.get("campaign",""),
    })
    base = utm.get("url","")
    sep = "&" if "?" in base else "?"
    full = f"{base}{sep}{params}"
    await update.message.reply_text(
        f"📋 *UTM-ссылка готова:*\n\n`{full}`\n\n_Нажми чтобы скопировать_",
        parse_mode="Markdown", reply_markup=back_keyboard())
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 11 — Трекер аккаунтов
# ══════════════════════════════════════════════════════════════════════════════

ACC_PLATFORMS = ["Facebook", "TikTok", "Instagram", "Google", "Twitter/X", "Другое"]
ACC_STATUSES  = ["🟢 Живой", "🟡 В работе", "🔴 Забанен", "⚫ Удалён"]

def _acc_list_keyboard(accounts: list, page=0, per=5):
    total = len(accounts)
    pages = max(1, -(-total // per))
    chunk = accounts[page*per:(page+1)*per]
    btns = []
    for i, acc in enumerate(chunk):
        real_i = page*per + i
        s = acc['status']
        btns.append([InlineKeyboardButton(
            f"{s} · {acc['platform']} · {acc['login'][:20]}",
            callback_data=f"acc_view_{real_i}_{page}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"acc_page_{page-1}"))
    if page < pages-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"acc_page_{page+1}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data="acc_add")])
    return InlineKeyboardMarkup(btns)

def _acc_detail_keyboard(idx: int, page: int):
    btns = [
        [InlineKeyboardButton(s, callback_data=f"acc_status_{idx}_{s}_{page}")]
        for s in ACC_STATUSES
    ]
    btns.append([
        InlineKeyboardButton("🗑 Удалить", callback_data=f"acc_del_{idx}_{page}"),
        InlineKeyboardButton("◀️ Назад", callback_data=f"acc_page_{page}"),
    ])
    return InlineKeyboardMarkup(btns)

async def tool_accounts(update: Update, context):
    uid = update.effective_user.id
    accounts = _user(uid).get("accounts", [])
    if not accounts:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить аккаунт", callback_data="acc_add")]])
        await update.message.reply_text("📊 *Трекер аккаунтов*\n\nСписок пуст.", parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(
            f"📊 *Трекер аккаунтов* ({len(accounts)} шт)",
            parse_mode="Markdown",
            reply_markup=_acc_list_keyboard(accounts))
    return ConversationHandler.END

async def acc_add_platform(update: Update, context):
    """Вызывается из callback acc_add."""
    btns = [[InlineKeyboardButton(p, callback_data=f"acc_plat_{p}")] for p in ACC_PLATFORMS]
    return InlineKeyboardMarkup(btns)

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 12 — Трекер кампаний
# ══════════════════════════════════════════════════════════════════════════════

def _camp_list_keyboard(camps: list, page=0, per=5):
    total = len(camps)
    pages = max(1, -(-total // per))
    chunk = camps[page*per:(page+1)*per]
    btns = []
    for i, c in enumerate(chunk):
        real_i = page*per + i
        roi = (c['earned']-c['spent'])/c['spent']*100 if c['spent'] else 0
        btns.append([InlineKeyboardButton(
            f"{'🟢' if roi>=0 else '🔴'} {c['name'][:20]} · ROI {roi:.0f}%",
            callback_data=f"camp_view_{real_i}_{page}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"camp_page_{page-1}"))
    if page < pages-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"camp_page_{page+1}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton("➕ Новая кампания", callback_data="camp_add")])
    return InlineKeyboardMarkup(btns)

async def tool_campaigns(update: Update, context):
    uid = update.effective_user.id
    camps = _user(uid).get("campaigns", [])
    if not camps:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Новая кампания", callback_data="camp_add")]])
        await update.message.reply_text("📈 *Трекер кампаний*\n\nСписок пуст.", parse_mode="Markdown", reply_markup=kb)
    else:
        total_spent  = sum(c["spent"] for c in camps)
        total_earned = sum(c["earned"] for c in camps)
        total_roi = (total_earned-total_spent)/total_spent*100 if total_spent else 0
        header = (f"📈 *Трекер кампаний* ({len(camps)} шт)\n"
                  f"Итого: вложено `{total_spent:,.0f}` · получено `{total_earned:,.0f}` · ROI *{total_roi:.1f}%*")
        await update.message.reply_text(header, parse_mode="Markdown", reply_markup=_camp_list_keyboard(camps))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 13 — Уникализатор фото / видео
# ══════════════════════════════════════════════════════════════════════════════

FAKE_CAMERAS = [
    "Apple iPhone 14 Pro", "Apple iPhone 15", "Samsung Galaxy S23 Ultra",
    "Samsung Galaxy A54", "Google Pixel 7", "Xiaomi 13 Pro",
    "OnePlus 11", "Sony Xperia 1 V", "Huawei P60 Pro",
]
FAKE_SOFTWARE = [
    "Adobe Lightroom 7.0", "Snapseed 2.19", "VSCO 310", "Camera+ 2",
    "ProCamera 16", "Halide Mark III", "Instagram 280.0",
]


def _rand_exif() -> dict:
    """Генерирует случайные EXIF-данные."""
    now = datetime.now()
    days_back = random.randint(0, 60)
    minutes_shift = random.randint(0, 1440)
    fake_dt = now.replace(
        day=max(1, now.day - days_back % 28),
        hour=minutes_shift // 60,
        minute=minutes_shift % 60,
        second=random.randint(0, 59),
    )
    dt_str = fake_dt.strftime("%Y:%m:%d %H:%M:%S").encode()

    camera = random.choice(FAKE_CAMERAS)
    make, model = camera.split(" ", 1)

    # случайные GPS-координаты в диапазоне реальных городов
    cities_gps = [
        (52.2297, 21.0122),  # Варшава
        (50.0647, 19.9450),  # Краков
        (48.8566, 2.3522),   # Париж
        (51.5074, -0.1278),  # Лондон
        (50.4501, 30.5234),  # Киев
        (53.9045, 27.5615),  # Минск
        (52.5200, 13.4050),  # Берлин
        (40.7128, -74.0060), # Нью-Йорк
    ]
    lat, lon = random.choice(cities_gps)
    lat += random.uniform(-0.05, 0.05)
    lon += random.uniform(-0.05, 0.05)

    def _to_dms(val):
        d = int(abs(val))
        m = int((abs(val) - d) * 60)
        s = round(((abs(val) - d) * 60 - m) * 60 * 100)
        return ((d, 1), (m, 1), (s, 100))

    exif = {
        "0th": {
            piexif.ImageIFD.Make: make.encode(),
            piexif.ImageIFD.Model: model.encode(),
            piexif.ImageIFD.Software: random.choice(FAKE_SOFTWARE).encode(),
            piexif.ImageIFD.DateTime: dt_str,
            piexif.ImageIFD.XResolution: (72, 1),
            piexif.ImageIFD.YResolution: (72, 1),
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: dt_str,
            piexif.ExifIFD.DateTimeDigitized: dt_str,
            piexif.ExifIFD.ExposureTime: (1, random.choice([30, 60, 125, 250, 500, 1000])),
            piexif.ExifIFD.FNumber: (random.choice([18, 20, 22, 28]), 10),
            piexif.ExifIFD.ISOSpeedRatings: random.choice([50, 100, 200, 400, 800]),
            piexif.ExifIFD.FocalLength: (random.choice([26, 35, 50, 77]), 1),
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _to_dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _to_dms(lon),
        },
        "1st": {},
        "thumbnail": None,
    }
    return exif


def _uniqualize_photo(data: bytes) -> tuple:
    """Возвращает (bytes, info_str). Меняет пиксели + EXIF."""
    img = Image.open(io.BytesIO(data)).convert("RGB")

    # 1. Лёгкий шум — меняет хеш файла
    import numpy as np
    arr = np.array(img, dtype=np.int16)
    noise = np.random.randint(-3, 4, arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 2. Минимальное изменение насыщенности
    from PIL import ImageEnhance
    img = ImageEnhance.Color(img).enhance(random.uniform(0.98, 1.02))
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.99, 1.01))

    # 3. Новые EXIF
    exif_dict = _rand_exif()
    exif_bytes = piexif.dump(exif_dict)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=95, exif=exif_bytes)
    out.seek(0)

    camera = exif_dict["0th"][piexif.ImageIFD.Model].decode()
    dt = exif_dict["0th"][piexif.ImageIFD.DateTime].decode()
    info = f"📷 {camera}\n📅 {dt}"
    return out.read(), info


async def _uniqualize_video_ffmpeg(src: str, out_path: str) -> dict:
    """Подменяет метаданные видео и делает минимальный re-encode через ffmpeg."""
    import subprocess
    camera = random.choice(FAKE_CAMERAS)
    now = datetime.now()
    fake_dt = now.replace(
        day=max(1, now.day - random.randint(0, 20)),
        hour=random.randint(0, 23),
        minute=random.randint(0, 59),
    )

    meta = {
        "title": "",
        "comment": "",
        "description": "",
        "author": "",
        "artist": "",
        "album": "",
        "encoder": random.choice(["Lavf58.45.100", "Lavf59.27.100", "Lavf60.3.100"]),
        "creation_time": fake_dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "com.apple.quicktime.make": camera.split()[0],
        "com.apple.quicktime.model": " ".join(camera.split()[1:]),
    }

    cmd = ["ffmpeg", "-y", "-i", src]
    # Сброс всех тегов
    cmd += ["-map_metadata", "-1"]
    # Запись новых
    for k, v in meta.items():
        cmd += ["-metadata", f"{k}={v}"]
    # Минимальный re-encode видеопотока (меняет хеш)
    cmd += [
        "-c:v", "libx264", "-crf", str(random.randint(22, 26)),
        "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k",
        "-vf", f"eq=brightness={random.uniform(-0.02, 0.02):.4f}:saturation={random.uniform(0.97, 1.03):.4f}",
        out_path,
    ]

    loop = asyncio.get_event_loop()
    def _run():
        subprocess.run(cmd, capture_output=True, check=True)
    await loop.run_in_executor(None, _run)
    return {"camera": camera, "date": fake_dt.strftime("%d.%m.%Y %H:%M")}


async def tool_unique_start(update: Update, context):
    await update.message.reply_text(
        "🎨 *Уникализатор*\n\n"
        "Отправь *фото* или *видео* — я подменю метаданные и немного изменю файл "
        "так чтобы платформы не определили дубликат.\n\n"
        "_Что меняется:_\n"
        "• EXIF: камера, дата, GPS\n"
        "• Пиксели: невидимый шум ±3 ед.\n"
        "• Видео: re-encode + brightness/saturation\n"
        "• Хеш файла: полностью новый",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return WAITING_UNIQUE_MEDIA


async def receive_unique_media(update: Update, context):
    if update.message.text and is_menu(update.message.text):
        return await _menu_redirect(update, context)

    # ── Фото ──────────────────────────────────────────────────────────────────
    if update.message.photo:
        msg = await update.message.reply_text("⚙️ Уникализирую фото...")
        photo = update.message.photo[-1]  # наибольшее разрешение
        file = await context.bot.get_file(photo.file_id)
        data = bytes(await file.download_as_bytearray())
        try:
            loop = asyncio.get_event_loop()
            unique_bytes, info = await loop.run_in_executor(None, _uniqualize_photo, data)
            await msg.edit_text(f"📤 Загружаю результат...")
            await update.message.reply_document(
                document=io.BytesIO(unique_bytes),
                filename="unique_photo.jpg",
                caption=f"✅ *Фото уникализировано*\n\n{info}",
                parse_mode="Markdown",
            )
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: `{e}`", parse_mode="Markdown")
        await update.message.reply_text("🎨 Отправь ещё файл или выбери инструмент:", reply_markup=MAIN_KEYBOARD)
        return WAITING_UNIQUE_MEDIA

    # ── Видео ──────────────────────────────────────────────────────────────────
    if update.message.video or update.message.document:
        if not _has_ffmpeg():
            await update.message.reply_text(
                "❌ ffmpeg не установлен — уникализация видео недоступна.",
                reply_markup=MAIN_KEYBOARD,
            )
            return WAITING_UNIQUE_MEDIA

        media = update.message.video or update.message.document
        size = media.file_size or 0
        if size > 50 * 1024 * 1024:
            await update.message.reply_text("❌ Файл больше 50 МБ — Telegram не даёт скачать.", reply_markup=MAIN_KEYBOARD)
            return WAITING_UNIQUE_MEDIA

        msg = await update.message.reply_text("⏳ Скачиваю видео...")
        file = await context.bot.get_file(media.file_id)
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "input.mp4")
            out = os.path.join(tmp, "unique.mp4")
            await file.download_to_drive(src)
            try:
                await msg.edit_text("⚙️ Уникализирую видео (re-encode)...")
                meta = await _uniqualize_video_ffmpeg(src, out)
                await msg.edit_text("📤 Загружаю результат...")
                with open(out, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename="unique_video.mp4",
                        caption=(
                            f"✅ *Видео уникализировано*\n\n"
                            f"📷 {meta['camera']}\n"
                            f"📅 {meta['date']}\n"
                            f"🔄 Хеш изменён, метаданные подменены"
                        ),
                        parse_mode="Markdown",
                    )
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ Ошибка ffmpeg: `{str(e)[:300]}`", parse_mode="Markdown")
        await update.message.reply_text("🎨 Отправь ещё файл или выбери инструмент:", reply_markup=MAIN_KEYBOARD)
        return WAITING_UNIQUE_MEDIA

    await update.message.reply_text(
        "⚠️ Отправь фото или видео (не ссылку).", reply_markup=cancel_keyboard()
    )
    return WAITING_UNIQUE_MEDIA


# ══════════════════════════════════════════════════════════════════════════════
# Main menu dispatcher
# ══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 *Arbitrage Multitool*\n\nВыбери инструмент кнопками внизу:",
        parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "🆔 ID компании":        return await tool_id_start(update, context)
    if t == "📥 Скачать видео":      return await tool_video_start(update, context)
    if t == "🌍 IP / Прокси":        return await tool_ip_start(update, context)
    if t == "🕐 Тайм-зоны":          return await tool_tz(update, context)
    if t == "🔐 Пароль":             return await tool_pass(update, context)
    if t == "📝 Фейк-данные":        return await tool_fake(update, context)
    if t == "🚫 Чекер домена FB":     return await tool_domain_start(update, context)
    if t == "🧮 ROI":                return await tool_roi(update, context)
    if t == "🔗 Укоротить ссылку":   return await tool_short(update, context)
    if t == "📋 UTM-метки":          return await tool_utm(update, context)
    if t == "📊 Аккаунты":           return await tool_accounts(update, context)
    if t == "📈 Кампании":           return await tool_campaigns(update, context)
    if t == "🎨 Уникализатор":        return await tool_unique_start(update, context)
    if t == "📡 Мониторинг доменов":  return await tool_watch_list(update, context)
    if t == "🗂 История ID":
        uid = update.effective_user.id
        recs = _user(uid).get("company_ids", [])
        if not recs:
            await update.message.reply_text("📋 История пуста.")
            return ConversationHandler.END
        text, kb = _fmt_history_page(recs, 0)
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# Callback handler (inline кнопки)
# ══════════════════════════════════════════════════════════════════════════════

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = q.from_user.id

    # ── Cancel / back
    if d == "cancel":
        await q.edit_message_text("✅ Отменено. Выбери инструмент кнопками внизу.")
        return ConversationHandler.END

    # ── ID history
    if d.startswith("hist_"):
        page = int(d[5:])
        recs = _user(uid).get("company_ids", [])
        if not recs:
            await q.edit_message_text("📋 История пуста.")
            return ConversationHandler.END
        text, kb = _fmt_history_page(recs, page)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END

    if d.startswith("del_"):
        _, idx, page = d.split("_")
        _del_id(uid, int(idx))
        recs = _user(uid).get("company_ids", [])
        if not recs:
            await q.edit_message_text("📋 История пуста.")
            return ConversationHandler.END
        p = min(int(page), max(0, -(-len(recs)//5)-1))
        text, kb = _fmt_history_page(recs, p)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END

    if d.startswith("regen_"):
        parts = d[6:].rsplit("_", 1)
        prefix, n = parts[0], int(parts[1])
        ids = [_gen_id(prefix) for _ in range(n)]
        _save_ids(uid, ids, prefix)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Ещё", callback_data=d)]])
        await q.edit_message_text(_fmt_ids(ids, prefix), parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END

    # ── Timezone refresh
    if d == "tz_refresh":
        lines = ["🕐 *Текущее время по зонам:*", ""]
        for label, tz in TIMEZONES:
            local = datetime.now(ZoneInfo(tz))
            lines.append(f"{label}: *{local.strftime('%H:%M')}* _{local.strftime('%d.%m')}_")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data="tz_refresh")]])
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END

    # ── Password
    if d.startswith("pass_"):
        parts = d[5:].split("_")
        if parts[0] == "gen":
            length, sym, dig = int(parts[1]), bool(int(parts[2])), bool(int(parts[3]))
            pwd = _gen_password(length, sym, dig)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Ещё раз", callback_data=d)],
                [InlineKeyboardButton("⚙️ Настройки", callback_data=f"pass_{length}_{int(sym)}_{int(dig)}_menu")],
            ])
            await q.edit_message_text(
                f"🔐 *Пароль* ({length} симв.):\n\n`{pwd}`\n\n_Нажми чтобы скопировать_",
                parse_mode="Markdown", reply_markup=kb)
        else:
            length, sym, dig = int(parts[0]), bool(int(parts[1])), bool(int(parts[2]))
            await q.edit_message_text(
                "🔐 *Генератор паролей*\n\nВыбери длину и параметры:",
                parse_mode="Markdown", reply_markup=_pass_keyboard(length, sym, dig))
        return ConversationHandler.END

    # ── Fake data
    if d.startswith("fake_"):
        locale = d[5:]
        text = _gen_fake(locale)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Ещё раз", callback_data=d)],
            [InlineKeyboardButton("🌍 Другая страна", callback_data="fake_menu")],
        ])
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END

    if d == "fake_menu":
        await q.edit_message_text(
            "📝 *Фейк-данные*\n\nВыбери страну:",
            parse_mode="Markdown", reply_markup=_fake_keyboard())
        return ConversationHandler.END

    # ── Domain checker: проверить ещё раз
    if d == "domain_again":
        await q.edit_message_text(
            "🚫 *Чекер домена (риск для Facebook)*\n\n"
            "Введи домен без https:// (например: `mysite.com`):",
            parse_mode="Markdown", reply_markup=cancel_keyboard())
        return WAITING_DOMAIN

    # ── Domain monitor: добавить домен из результата чекера
    if d.startswith("watch_add_") and d != "watch_add_menu":
        domain = d[len("watch_add_"):]
        domains = _get_watched()
        if any(x["domain"] == domain for x in domains):
            await q.answer("Уже в мониторинге", show_alert=True)
            return ConversationHandler.END
        result = await _run_domain_check(domain)
        _, level = _score_domain(result)
        domains.append({"domain": domain, "level": level, "added_at": _now()})
        _set_watched(domains)
        await q.answer(f"✅ {domain} добавлен в мониторинг", show_alert=True)
        return ConversationHandler.END

    if d == "watch_add_menu":
        await q.edit_message_text("📡 Введи домен для добавления в мониторинг:", reply_markup=cancel_keyboard())
        return WAITING_WATCH_DOMAIN

    if d.startswith("watch_del_"):
        idx = int(d[len("watch_del_"):])
        domains = _get_watched()
        if 0 <= idx < len(domains):
            removed = domains.pop(idx)
            _set_watched(domains)
            await q.answer(f"🗑 {removed['domain']} удалён", show_alert=False)
        await q.edit_message_text(_fmt_watch_list(domains), parse_mode="Markdown", reply_markup=_watch_keyboard(domains))
        return ConversationHandler.END

    # ── Accounts
    if d == "acc_add":
        btns = [[InlineKeyboardButton(p, callback_data=f"acc_plat_{p}")] for p in ACC_PLATFORMS]
        await q.edit_message_text("📊 Выбери платформу:", reply_markup=InlineKeyboardMarkup(btns))
        return WAITING_ACC_PLATFORM

    if d.startswith("acc_plat_"):
        context.user_data["acc_platform"] = d[9:]
        await q.edit_message_text(
            f"📊 Платформа: *{d[9:]}*\n\nВведи логин / email аккаунта:",
            parse_mode="Markdown")
        return WAITING_ACC_LOGIN

    if d.startswith("acc_page_"):
        page = int(d[9:])
        accounts = _user(uid).get("accounts", [])
        await q.edit_message_text(
            f"📊 *Аккаунты* ({len(accounts)} шт)",
            parse_mode="Markdown", reply_markup=_acc_list_keyboard(accounts, page))
        return ConversationHandler.END

    if d.startswith("acc_view_"):
        parts = d[9:].split("_")
        idx, page = int(parts[0]), int(parts[1])
        accounts = _user(uid).get("accounts", [])
        if idx >= len(accounts):
            await q.edit_message_text("❌ Аккаунт не найден.")
            return ConversationHandler.END
        acc = accounts[idx]
        lines = [
            f"📊 *{acc['platform']}*",
            f"👤 `{acc['login']}`",
            f"Статус: {acc['status']}",
            f"Добавлен: {acc['created_at']}",
            "",
            "_Выбери новый статус или удали:_",
        ]
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                   reply_markup=_acc_detail_keyboard(idx, page))
        return ConversationHandler.END

    if d.startswith("acc_status_"):
        parts = d[11:].rsplit("_", 2)
        idx, status, page = int(parts[0]), parts[1], int(parts[2])
        u = _user(uid)
        if idx < len(u.get("accounts", [])):
            u["accounts"][idx]["status"] = status
            _set_user(uid, u)
        accounts = u.get("accounts", [])
        await q.edit_message_text(
            f"✅ Статус обновлён → {status}\n\n📊 *Аккаунты* ({len(accounts)} шт)",
            parse_mode="Markdown", reply_markup=_acc_list_keyboard(accounts, page))
        return ConversationHandler.END

    if d.startswith("acc_del_"):
        parts = d[8:].split("_")
        idx, page = int(parts[0]), int(parts[1])
        u = _user(uid)
        accs = u.get("accounts", [])
        if idx < len(accs): accs.pop(idx)
        u["accounts"] = accs
        _set_user(uid, u)
        if not accs:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить", callback_data="acc_add")]])
            await q.edit_message_text("📊 Список аккаунтов пуст.", reply_markup=kb)
        else:
            p = min(page, max(0, -(-len(accs)//5)-1))
            await q.edit_message_text(f"✅ Удалено.\n\n📊 *Аккаунты* ({len(accs)} шт)",
                parse_mode="Markdown", reply_markup=_acc_list_keyboard(accs, p))
        return ConversationHandler.END

    # ── Campaigns
    if d == "camp_add":
        await q.edit_message_text("📈 Введи название кампании:")
        return WAITING_CAMP_NAME

    if d.startswith("camp_page_"):
        page = int(d[10:])
        camps = _user(uid).get("campaigns", [])
        await q.edit_message_text(
            f"📈 *Кампании* ({len(camps)} шт)",
            parse_mode="Markdown", reply_markup=_camp_list_keyboard(camps, page))
        return ConversationHandler.END

    if d.startswith("camp_view_"):
        parts = d[10:].split("_")
        idx, page = int(parts[0]), int(parts[1])
        camps = _user(uid).get("campaigns", [])
        if idx >= len(camps):
            await q.edit_message_text("❌ Кампания не найдена.")
            return ConversationHandler.END
        c = camps[idx]
        profit = c["earned"] - c["spent"]
        roi = profit / c["spent"] * 100 if c["spent"] else 0
        lines = [
            f"📈 *{c['name']}*",
            f"💸 Потрачено: `{c['spent']:,.2f}`",
            f"💰 Получено:  `{c['earned']:,.2f}`",
            f"{'🟢' if profit>=0 else '🔴'} Профит: `{profit:+,.2f}`",
            f"📊 ROI: *{roi:.1f}%*",
            f"📅 {c['created_at']}",
        ]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Обновить цифры", callback_data=f"camp_upd_{idx}_{page}")],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"camp_del_{idx}_{page}"),
             InlineKeyboardButton("◀️ Назад", callback_data=f"camp_page_{page}")],
        ])
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
        return ConversationHandler.END

    if d.startswith("camp_upd_"):
        parts = d[9:].split("_")
        context.user_data["camp_upd_idx"] = int(parts[0])
        context.user_data["camp_upd_page"] = int(parts[1])
        await q.edit_message_text("✏️ Новая сумма затрат:")
        return WAITING_CAMP_UPDATE_SPENT

    if d.startswith("camp_del_"):
        parts = d[9:].split("_")
        idx, page = int(parts[0]), int(parts[1])
        u = _user(uid)
        camps = u.get("campaigns", [])
        if idx < len(camps): camps.pop(idx)
        u["campaigns"] = camps
        _set_user(uid, u)
        if not camps:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Новая", callback_data="camp_add")]])
            await q.edit_message_text("📈 Кампаний нет.", reply_markup=kb)
        else:
            p = min(page, max(0, -(-len(camps)//5)-1))
            await q.edit_message_text(f"✅ Удалено.\n\n📈 *Кампании* ({len(camps)} шт)",
                parse_mode="Markdown", reply_markup=_camp_list_keyboard(camps, p))
        return ConversationHandler.END

    return ConversationHandler.END

# ── Account text handlers ──────────────────────────────────────────────────────

async def receive_acc_login(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    login = update.message.text.strip()
    platform = context.user_data.get("acc_platform", "Другое")
    context.user_data["acc_login"] = login
    btns = [[InlineKeyboardButton(s, callback_data=f"acc_save_status_{s}")] for s in ACC_STATUSES]
    await update.message.reply_text(
        f"📊 *{platform}* · `{login}`\n\nВыбери начальный статус:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))
    return WAITING_ACC_STATUS

async def receive_acc_status_text(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    return WAITING_ACC_STATUS

# ── Campaign text handlers ─────────────────────────────────────────────────────

async def receive_camp_name(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    context.user_data["camp_name"] = update.message.text.strip()
    await update.message.reply_text("💸 Сколько потрачено?", reply_markup=cancel_keyboard())
    return WAITING_CAMP_SPENT

async def receive_camp_spent(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip().replace(",",".")
    try: context.user_data["camp_spent"] = float(t)
    except ValueError:
        await update.message.reply_text("⚠️ Введи число:", reply_markup=cancel_keyboard())
        return WAITING_CAMP_SPENT
    await update.message.reply_text("💰 Сколько получено?", reply_markup=cancel_keyboard())
    return WAITING_CAMP_EARNED

async def receive_camp_earned(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip().replace(",",".")
    try: earned = float(t)
    except ValueError:
        await update.message.reply_text("⚠️ Введи число:", reply_markup=cancel_keyboard())
        return WAITING_CAMP_EARNED
    uid = update.effective_user.id
    u = _user(uid)
    u.setdefault("campaigns", []).append({
        "name": context.user_data.get("camp_name","Кампания"),
        "spent": context.user_data.get("camp_spent", 0),
        "earned": earned,
        "created_at": _now(),
    })
    _set_user(uid, u)
    camps = u["campaigns"]
    await update.message.reply_text(
        f"✅ Кампания сохранена!\n\n📈 *Кампании* ({len(camps)} шт)",
        parse_mode="Markdown", reply_markup=_camp_list_keyboard(camps))
    return ConversationHandler.END

async def receive_camp_update_spent(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip().replace(",",".")
    try: context.user_data["camp_upd_spent"] = float(t)
    except ValueError:
        await update.message.reply_text("⚠️ Введи число:", reply_markup=cancel_keyboard())
        return WAITING_CAMP_UPDATE_SPENT
    await update.message.reply_text("💰 Новая сумма дохода?", reply_markup=cancel_keyboard())
    return WAITING_CAMP_UPDATE_EARNED

async def receive_camp_update_earned(update: Update, context):
    if is_menu(update.message.text): return await _menu_redirect(update, context)
    t = update.message.text.strip().replace(",",".")
    try: earned = float(t)
    except ValueError:
        await update.message.reply_text("⚠️ Введи число:", reply_markup=cancel_keyboard())
        return WAITING_CAMP_UPDATE_EARNED
    uid = update.effective_user.id
    idx = context.user_data.get("camp_upd_idx", 0)
    page = context.user_data.get("camp_upd_page", 0)
    u = _user(uid)
    camps = u.get("campaigns", [])
    if idx < len(camps):
        camps[idx]["spent"] = context.user_data.get("camp_upd_spent", camps[idx]["spent"])
        camps[idx]["earned"] = earned
        _set_user(uid, u)
    await update.message.reply_text(
        f"✅ Обновлено!\n\n📈 *Кампании* ({len(camps)} шт)",
        parse_mode="Markdown", reply_markup=_camp_list_keyboard(camps, page))
    return ConversationHandler.END

# ── Save account status via callback (inside acc_save_status_) ────────────────

async def button_save_acc_status(update: Update, context):
    """Отдельный handler для сохранения аккаунта — вызывается из callback."""
    q = update.callback_query
    await q.answer()
    status = q.data[len("acc_save_status_"):]
    uid = q.from_user.id
    u = _user(uid)
    u.setdefault("accounts", []).append({
        "platform": context.user_data.get("acc_platform","?"),
        "login": context.user_data.get("acc_login","?"),
        "status": status,
        "created_at": _now(),
    })
    _set_user(uid, u)
    accounts = u["accounts"]
    await q.edit_message_text(
        f"✅ Аккаунт сохранён!\n\n📊 *Аккаунты* ({len(accounts)} шт)",
        parse_mode="Markdown", reply_markup=_acc_list_keyboard(accounts))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu),
            CallbackQueryHandler(button_handler),
        ],
        states={
            WAITING_PREFIX:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prefix)],
            WAITING_COUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_count)],
            WAITING_URL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)],
            WAITING_IP:      [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ip)],
            WAITING_DOMAIN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_domain),
                              CallbackQueryHandler(button_handler)],
            WAITING_ROI_SPENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_roi_spent)],
            WAITING_ROI_EARNED: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_roi_earned)],
            WAITING_SHORT_URL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_short_url)],
            WAITING_UTM_URL:      [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utm_url)],
            WAITING_UTM_SOURCE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utm_source)],
            WAITING_UTM_MEDIUM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utm_medium)],
            WAITING_UTM_CAMPAIGN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utm_campaign)],
            WAITING_ACC_PLATFORM: [CallbackQueryHandler(button_handler)],
            WAITING_ACC_LOGIN:    [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_acc_login),
                                   CallbackQueryHandler(button_handler)],
            WAITING_ACC_STATUS:   [CallbackQueryHandler(button_save_acc_status)],
            WAITING_CAMP_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_camp_name)],
            WAITING_CAMP_SPENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_camp_spent)],
            WAITING_CAMP_EARNED: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_camp_earned)],
            WAITING_CAMP_UPDATE_SPENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_camp_update_spent)],
            WAITING_CAMP_UPDATE_EARNED: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_camp_update_earned)],
            WAITING_UNIQUE_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, receive_unique_media),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_unique_media),
            ],
            WAITING_WATCH_DOMAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_watch_domain)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        per_chat=True,
    )

    app.add_handler(conv)

    if app.job_queue:
        app.job_queue.run_repeating(
            check_watched_domains_job,
            interval=DOMAIN_CHECK_INTERVAL_SEC,
            first=60,
        )

    print("🛠 Arbitrage Multitool запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
