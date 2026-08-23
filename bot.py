# =====================================================
# BOT.PY - SIKET EKUB LOTTERY BOT
# Streamlined Version - Minimal Interface, All Functions Working
# =====================================================

import sys
import os
import logging
import asyncio
import random
import re
import io
import ssl
import base64
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler

# =====================================================
# FIXES
# =====================================================
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# =====================================================
# IMPORTS
# =====================================================
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove,
    BufferedInputFile, BotCommand, WebAppInfo
)

import aiosqlite
from dotenv import load_dotenv
from database import init_db, backup_database, process_refund, DB_NAME, DatabaseHelper

ssl._create_default_https_context = ssl._create_unverified_context
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# =====================================================
# ENVIRONMENT
# =====================================================
TOKEN = os.getenv("BOT_TOKEN")
admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]

if not TOKEN or not ADMIN_IDS:
    raise ValueError("BOT_TOKEN and ADMIN_IDS required!")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://siket-ekub-webapp.onrender.com")
SUPPORT_CHANNEL_LINK = os.getenv("SUPPORT_CHANNEL_LINK", "https://t.me/siketekub")
TICKET_CHANNEL_LINK = os.getenv("TICKET_CHANNEL_LINK", "https://t.me/siketekubtiketo")
TICKET_CHANNEL_ID = os.getenv("TICKET_CHANNEL_ID", "@siketekubtiketo")

# =====================================================
# LOGGING
# =====================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =====================================================
# BOT SETUP
# =====================================================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
router = Router()

# =====================================================
# SIMPLE LOCALIZATION
# =====================================================
TEXTS = {
    "en": {
        "welcome": "🎰 Welcome to Siket Ekub Lottery!\nPrice: 3,000 ETB/ticket",
        "menu": "📋 Main Menu",
        "buy": "🎯 Buy Ticket",
        "tickets": "🎫 My Tickets",
        "prizes": "🏆 Prizes",
        "balance": "💰 Balance",
        "support": "💬 Support",
        "lang": "🌍 Language",
        "reg_phone": "📱 Share phone to register:",
        "reg_address": "📍 Enter your address:",
        "registered": "✅ Registered!",
        "select_game": "🎯 Select Game:",
        "pick_ticket": "🎫 Pick your ticket:",
        "sold": "SOLD",
        "pay": "💰 Pay 3,000 ETB to:\nCBE: 1000786684491\nAbyssinia: 264517826\nTelebirr: 0979774444\n\n📸 Send screenshot or SMS receipt:",
        "pay_submitted": "✅ Payment submitted for verification.",
        "pay_approved": "✅ Payment approved! Ticket #{ticket}",
        "pay_rejected": "❌ Payment rejected.",
        "no_tickets": "📭 No tickets yet.",
        "prize_list": "🏆 10 GRAND PRIZES:\n1st: BWD Leopard 3 (8,000,000 ETB)\n2nd: Hyundai Bayon (5,000,000 ETB)\n3rd: Shop Space (4,000,000 ETB)\n4th-7th: 1,000,000 ETB each\n8th: 500,000 ETB\n9th: 300,000 ETB\n10th: 200,000 ETB",
        "balance_info": "💰 Balance: {balance} ETB\n🎫 Tickets: {tickets}\n💸 Spent: {spent} ETB",
        "admin": "🛠️ Admin Panel",
        "verify": "✅ Verify Payments",
        "create": "📝 Create Game",
        "users": "👤 Users",
        "refund": "🔄 Refunds",
        "broadcast": "📢 Broadcast",
        "reports": "📊 Reports",
        "back": "🔙 Back",
        "cancel": "✖ Cancel",
        "confirm": "✅ Confirm",
        "choose_lang": "🌍 Choose language:",
        "lang_changed": "✅ Language changed to {lang}",
    },
    "am": {
        "welcome": "🎰 ወደ ሲኬት ዕቁብ ሎተሪ እንኳን በደህና መጡ!\nዋጋ: 3,000 ብር/ቲኬት",
        "menu": "📋 ዋና ምናሌ",
        "buy": "🎯 ቲኬት ግዛ",
        "tickets": "🎫 ቲኬቶቼ",
        "prizes": "🏆 ሽልማቶች",
        "balance": "💰 ቀሪ ሂሳብ",
        "support": "💬 ድጋፍ",
        "lang": "🌍 ቋንቋ",
        "reg_phone": "📱 ለመመዝገብ ስልክ አጋሩ:",
        "reg_address": "📍 አድራሻዎን ያስገቡ:",
        "registered": "✅ ተመዝግበዋል!",
        "select_game": "🎯 ጨዋታ ምረጥ:",
        "pick_ticket": "🎫 ቲኬት ምረጥ:",
        "sold": "ተሽጧል",
        "pay": "💰 3,000 ብር ወደዚህ ክፈሉ:\nCBE: 1000786684491\nአቢሲኒያ: 264517826\nተሌብር: 0979774444\n\n📸 ስክሪንሾት ወይም SMS ላኩ:",
        "pay_submitted": "✅ ክፍያ ለማረጋገጥ ተልኳል።",
        "pay_approved": "✅ ክፍያ ጸድቋል! ቲኬት #{ticket}",
        "pay_rejected": "❌ ክፍያ ውድቅ ተደርጓል።",
        "no_tickets": "📭 ምንም ቲኬቶች የሉም።",
        "prize_list": "🏆 10 ዋና ሽልማቶች:\n1ኛ: BWD Leopard 3 (8,000,000 ብር)\n2ኛ: Hyundai Bayon (5,000,000 ብር)\n3ኛ: የሱቅ ቦታ (4,000,000 ብር)\n4ኛ-7ኛ: 1,000,000 ብር\n8ኛ: 500,000 ብር\n9ኛ: 300,000 ብር\n10ኛ: 200,000 ብር",
        "balance_info": "💰 ቀሪ: {balance} ብር\n🎫 ቲኬቶች: {tickets}\n💸 አጠቃላይ: {spent} ብር",
        "admin": "🛠️ የአስተዳዳሪ ፓነል",
        "verify": "✅ ክፍያዎችን አረጋግጥ",
        "create": "📝 ጨዋታ ፍጠር",
        "users": "👤 ተጠቃሚዎች",
        "refund": "🔄 መመለስ",
        "broadcast": "📢 መልዕክት ላክ",
        "reports": "📊 ሪፖርቶች",
        "back": "🔙 ወደ ኋላ",
        "cancel": "✖ ሰርዝ",
        "confirm": "✅ አረጋግጥ",
        "choose_lang": "🌍 ቋንቋ ምረጥ:",
        "lang_changed": "✅ ቋንቋ ወደ {lang} ተቀይሯል።",
    }
}

def t(user_id: int, key: str, **kwargs) -> str:
    """Get text in user's language"""
    lang = getattr(t, 'lang_cache', {}).get(user_id, 'en')
    text = TEXTS.get(lang, TEXTS['en']).get(key, key)
    return text.format(**kwargs) if kwargs else text

# =====================================================
# SIMPLE KEYBOARDS
# =====================================================
def main_kb(uid: int):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(uid, "buy")), KeyboardButton(text=t(uid, "tickets"))],
            [KeyboardButton(text=t(uid, "balance")), KeyboardButton(text=t(uid, "prizes"))],
            [KeyboardButton(text=t(uid, "support")), KeyboardButton(text=t(uid, "lang"))],
        ],
        resize_keyboard=True
    )

def admin_kb(uid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "verify"), callback_data="admin_verify")],
        [InlineKeyboardButton(text=t(uid, "create"), callback_data="admin_create")],
        [InlineKeyboardButton(text=t(uid, "users"), callback_data="admin_users")],
        [InlineKeyboardButton(text=t(uid, "refund"), callback_data="admin_refund")],
        [InlineKeyboardButton(text=t(uid, "broadcast"), callback_data="admin_broadcast")],
        [InlineKeyboardButton(text=t(uid, "reports"), callback_data="admin_reports")],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_back")],
    ])

def back_kb(uid: int, callback: str = "main_back"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "back"), callback_data=callback)]
    ])

# =====================================================
# STATES
# =====================================================
class RegState(StatesGroup):
    phone = State()
    address = State()

class BuyState(StatesGroup):
    game = State()
    ticket = State()
    payment = State()

class AdminState(StatesGroup):
    game_name = State()
    game_prizes = State()
    game_slots = State()
    broadcast_msg = State()
    refund_reason = State()

# =====================================================
# START / REGISTRATION
# =====================================================
@router.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    uid = message.from_user.id
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    
    if user:
        t.lang_cache[uid] = user[8] if len(user) > 8 else 'en'
        await message.answer(t(uid, "welcome"), reply_markup=main_kb(uid))
        return
    
    # Language choice
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")],
    ])
    await message.answer(t(uid, "choose_lang"), reply_markup=kb)

@router.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    lang = callback.data.split("_")[1]
    t.lang_cache[uid] = lang
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(uid, "reg_phone"), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await callback.message.delete()
    await callback.message.answer(t(uid, "reg_phone"), reply_markup=kb)
    await state.set_state(RegState.phone)
    await callback.answer()

@router.message(RegState.phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(phone=message.contact.phone_number)
    await message.answer(t(uid, "reg_address"), reply_markup=ReplyKeyboardRemove())
    await state.set_state(RegState.address)

@router.message(RegState.address, F.text)
async def reg_address(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    phone = data.get("phone")
    address = message.text
    lang = t.lang_cache.get(uid, 'en')
    
    await DatabaseHelper.execute(
        "INSERT INTO users (telegram_id, phone_number, address, language) VALUES (?, ?, ?, ?)",
        (uid, phone, address, lang)
    )
    await state.clear()
    await message.answer(t(uid, "registered"), reply_markup=main_kb(uid))

# =====================================================
# MAIN MENU HANDLERS
# =====================================================
@router.message(F.text.in_(["🎯 Buy Ticket", "🎯 ቲኬት ግዛ"]))
async def buy_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    games = await DatabaseHelper.fetch(
        "SELECT type_id, name, price FROM ticket_types WHERE is_active = 1"
    )
    if not games:
        await message.answer("❌ No active games.", reply_markup=main_kb(uid))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{g[1]} ({g[2]:,.0f} ETB)", callback_data=f"game_{g[0]}")]
        for g in games
    ] + [[InlineKeyboardButton(text=t(uid, "back"), callback_data="main_back")]])
    
    await message.answer(t(uid, "select_game"), reply_markup=kb)
    await state.set_state(BuyState.game)

@router.callback_query(F.data.startswith("game_"))
async def select_game(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    type_id = int(callback.data.split("_")[1])
    await state.update_data(game_id=type_id)
    
    # Get ticket blocks (simplified: show 20000 tickets in 20 blocks of 1000)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i in range(1, 20001, 1000):
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{i}-{i+999}",
                callback_data=f"block_{type_id}_{i}_{i+999}"
            )
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="buy_back")])
    
    await callback.message.edit_text(t(uid, "pick_ticket"), reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("block_"))
async def select_block(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    _, type_id, start, end = callback.data.split("_")
    type_id = int(type_id)
    start = int(start)
    end = int(end)
    
    # Show individual tickets (100 per page)
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_id, ticket_number, status FROM tickets WHERE type_id = ? AND ticket_number BETWEEN ? AND ?",
        (type_id, start, end)
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for tid, num, status in tickets:
        if status == 'available':
            row.append(InlineKeyboardButton(str(num), callback_data=f"ticket_{tid}"))
        else:
            row.append(InlineKeyboardButton("🔴", callback_data="sold"))
        if len(row) == 5:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    
    kb.inline_keyboard.append([InlineKeyboardButton(text=t(uid, "back"), callback_data=f"game_{type_id}")])
    await callback.message.edit_text(f"🎫 Tickets {start}-{end}", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "sold")
async def sold_alert(callback: CallbackQuery):
    await callback.answer("❌ Sold out!", show_alert=True)

@router.callback_query(F.data.startswith("ticket_"))
async def select_ticket(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    ticket_id = int(callback.data.split("_")[1])
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_number, type_id FROM tickets WHERE ticket_id = ? AND status = 'available'",
        (ticket_id,)
    )
    if not ticket:
        await callback.answer("❌ Ticket not available!", show_alert=True)
        return
    
    await state.update_data(ticket_id=ticket_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "pay"), callback_data="confirm_pay")],
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="buy_back")]
    ])
    
    await callback.message.edit_text(
        f"🎫 Ticket #{ticket[0]}\n\n" + t(uid, "pay"),
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_pay")
async def confirm_pay(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    
    if not ticket_id:
        await callback.answer("❌ No ticket selected!", show_alert=True)
        return
    
    # Check if still available
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_number, type_id FROM tickets WHERE ticket_id = ? AND status = 'available'",
        (ticket_id,)
    )
    if not ticket:
        await callback.answer("❌ Ticket no longer available!", show_alert=True)
        return
    
    await state.update_data(ticket_num=ticket[0], type_id=ticket[1])
    await state.set_state(BuyState.payment)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="buy_back")]
    ])
    
    await callback.message.edit_text(
        f"🎫 Ticket #{ticket[0]}\n\n" + t(uid, "pay"),
        reply_markup=kb
    )
    await callback.answer()

@router.message(BuyState.payment, F.text | F.photo)
async def process_payment(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    ticket_num = data.get("ticket_num")
    
    if not ticket_id:
        await message.answer("❌ No ticket selected.", reply_markup=main_kb(uid))
        await state.clear()
        return
    
    user = await DatabaseHelper.fetch_one("SELECT user_id FROM users WHERE telegram_id = ?", (uid,))
    if not user:
        await message.answer("❌ Please /start first.")
        return
    
    # Save payment
    screenshot = ""
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        screenshot = base64.b64encode(downloaded.read()).decode('utf-8')
    
    cursor = await DatabaseHelper.execute(
        "INSERT INTO payments (user_id, telegram_id, ticket_id, ticket_number, status, screenshot_data) VALUES (?, ?, ?, ?, 'pending', ?)",
        (user[0], uid, ticket_id, ticket_num, screenshot)
    )
    payment_id = cursor.lastrowid
    
    await state.clear()
    await message.answer(t(uid, "pay_submitted"), reply_markup=main_kb(uid))
    
    # Notify admins
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(
                admin,
                f"🔔 New Payment\n🎫 Ticket: #{ticket_num}\n👤 User: {uid}\n🆔 Payment: {payment_id}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
                    [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")]
                ])
            )
        except:
            pass

@router.callback_query(F.data.startswith("approve_"))
async def approve_pay(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[1])
    payment = await DatabaseHelper.fetch_one(
        "SELECT telegram_id, ticket_id, ticket_number FROM payments WHERE payment_id = ? AND status = 'pending'",
        (payment_id,)
    )
    if not payment:
        await callback.answer("❌ Payment not found!", show_alert=True)
        return
    
    tg_id, ticket_id, ticket_num = payment
    
    # Update payment and ticket
    await DatabaseHelper.execute_transaction([
        ("UPDATE payments SET status = 'approved', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE payment_id = ?", (uid, payment_id)),
        ("UPDATE tickets SET status = 'sold', telegram_id = ?, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = ?", (tg_id, ticket_id)),
        ("UPDATE users SET balance = COALESCE(balance, 0) + 3000, total_spent = COALESCE(total_spent, 0) + 3000 WHERE telegram_id = ?", (tg_id,))
    ])
    
    # Notify user
    try:
        await bot.send_message(tg_id, t(tg_id, "pay_approved", ticket=ticket_num))
    except:
        pass
    
    await callback.message.edit_text(f"✅ Payment #{payment_id} approved!")
    await callback.answer()

@router.callback_query(F.data.startswith("reject_"))
async def reject_pay(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[1])
    payment = await DatabaseHelper.fetch_one(
        "SELECT telegram_id, ticket_number FROM payments WHERE payment_id = ? AND status = 'pending'",
        (payment_id,)
    )
    if payment:
        await DatabaseHelper.execute(
            "UPDATE payments SET status = 'rejected', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
            (uid, payment_id)
        )
        try:
            await bot.send_message(payment[0], t(payment[0], "pay_rejected"))
        except:
            pass
    
    await callback.message.edit_text(f"❌ Payment #{payment_id} rejected.")
    await callback.answer()

@router.callback_query(F.data == "buy_back")
async def buy_back(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(t(uid, "menu"), reply_markup=main_kb(uid))
    await callback.answer()

@router.callback_query(F.data == "main_back")
async def main_back(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(t(uid, "menu"), reply_markup=main_kb(uid))
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back_cb(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.clear()
    await callback.message.edit_text(t(uid, "admin"), reply_markup=admin_kb(uid))
    await callback.answer()

# =====================================================
# USER COMMANDS
# =====================================================
@router.message(F.text.in_(["🎫 My Tickets", "🎫 ቲኬቶቼ"]))
async def my_tickets(message: Message):
    uid = message.from_user.id
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_number, type_id, assigned_at FROM tickets WHERE telegram_id = ? AND status = 'sold' ORDER BY assigned_at DESC",
        (uid,)
    )
    if not tickets:
        await message.answer(t(uid, "no_tickets"), reply_markup=main_kb(uid))
        return
    
    lines = ["🎫 Your Tickets:\n"]
    for num, _, date in tickets[:10]:
        lines.append(f"#{num} - {date[:10]}")
    if len(tickets) > 10:
        lines.append(f"... and {len(tickets)-10} more")
    await message.answer("\n".join(lines), reply_markup=main_kb(uid))

@router.message(F.text.in_(["💰 Balance", "💰 ቀሪ ሂሳብ"]))
async def balance_cmd(message: Message):
    uid = message.from_user.id
    user = await DatabaseHelper.fetch_one(
        "SELECT balance, total_spent FROM users WHERE telegram_id = ?",
        (uid,)
    )
    if not user:
        await message.answer("❌ Please /start first.")
        return
    
    tickets = await DatabaseHelper.fetch("SELECT COUNT(*) FROM tickets WHERE telegram_id = ? AND status = 'sold'", (uid,))
    await message.answer(
        t(uid, "balance_info", balance=user[0] or 0, tickets=tickets[0][0] or 0, spent=user[1] or 0),
        reply_markup=main_kb(uid)
    )

@router.message(F.text.in_(["🏆 Prizes", "🏆 ሽልማቶች"]))
async def prizes_cmd(message: Message):
    uid = message.from_user.id
    await message.answer(t(uid, "prize_list"), reply_markup=main_kb(uid))

@router.message(F.text.in_(["💬 Support", "💬 ድጋፍ"]))
async def support_cmd(message: Message):
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Support", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton(text="🎟️ Tickets", url=TICKET_CHANNEL_LINK)],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_back")]
    ])
    await message.answer("💬 Support Channels", reply_markup=kb)

@router.message(F.text.in_(["🌍 Language", "🌍 ቋንቋ"]))
async def lang_cmd(message: Message):
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")],
    ])
    await message.answer(t(uid, "choose_lang"), reply_markup=kb)

# =====================================================
# ADMIN COMMANDS
# =====================================================
@router.message(Command("admin"))
async def admin_cmd(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!")
        return
    await message.answer(t(uid, "admin"), reply_markup=admin_kb(uid))

@router.callback_query(F.data == "admin_verify")
async def admin_verify(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payments = await DatabaseHelper.fetch(
        "SELECT payment_id, telegram_id, ticket_number, created_at FROM payments WHERE status = 'pending' ORDER BY created_at"
    )
    if not payments:
        await callback.message.edit_text("📭 No pending payments.", reply_markup=back_kb(uid, "admin_back"))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"#{p[0]} - #{p[2]} - {p[3][:10]}",
            callback_data=f"view_pay_{p[0]}"
        )] for p in payments
    ] + [[InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_back")]])
    
    await callback.message.edit_text("📋 Pending Payments:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("view_pay_"))
async def view_payment(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[2])
    payment = await DatabaseHelper.fetch_one(
        "SELECT payment_id, telegram_id, ticket_number, screenshot_data FROM payments WHERE payment_id = ?",
        (payment_id,)
    )
    if not payment:
        await callback.answer("❌ Not found!", show_alert=True)
        return
    
    _, tg_id, ticket_num, screenshot = payment
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_verify")]
    ])
    
    text = f"🔍 Payment #{payment_id}\n🎫 Ticket: #{ticket_num}\n👤 User: {tg_id}"
    
    if screenshot:
        try:
            img = base64.b64decode(screenshot)
            await callback.message.answer_photo(
                BufferedInputFile(img, filename="payment.jpg"),
                caption=text,
                reply_markup=kb
            )
            await callback.message.delete()
        except:
            await callback.message.edit_text(text + "\n\n📸 Screenshot attached (can't display)", reply_markup=kb)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_create")
async def admin_create(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    kb = back_kb(uid, "admin_back")
    await callback.message.edit_text("📝 Enter game name:", reply_markup=kb)
    await state.set_state(AdminState.game_name)
    await callback.answer()

@router.message(AdminState.game_name, F.text)
async def create_name(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await state.update_data(name=message.text)
    await message.answer("📝 Enter prizes (one per line):\n1st: Prize 1\n2nd: Prize 2\n...", reply_markup=back_kb(uid, "admin_back"))
    await state.set_state(AdminState.game_prizes)

@router.message(AdminState.game_prizes, F.text)
async def create_prizes(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await state.update_data(prizes=message.text)
    await message.answer("📝 Enter total slots (default: 20000):", reply_markup=back_kb(uid, "admin_back"))
    await state.set_state(AdminState.game_slots)

@router.message(AdminState.game_slots, F.text)
async def create_slots(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    try:
        slots = int(message.text.strip()) or 20000
    except:
        slots = 20000
    
    data = await state.get_data()
    name = data.get("name")
    prizes = data.get("prizes")
    
    # Create game
    cursor = await DatabaseHelper.execute(
        "INSERT INTO ticket_types (name, price, total_slots, is_active, prizes) VALUES (?, 3000, ?, 1, ?)",
        (name, slots, prizes)
    )
    type_id = cursor.lastrowid
    
    # Generate tickets in batches
    batch_size = 1000
    for start in range(1, slots + 1, batch_size):
        end = min(start + batch_size - 1, slots)
        values = [(type_id, i, 'available') for i in range(start, end + 1)]
        await DatabaseHelper.executemany(
            "INSERT INTO tickets (type_id, ticket_number, status) VALUES (?, ?, ?)",
            values
        )
    
    await state.clear()
    await message.answer(f"✅ Game '{name}' created with {slots} tickets!", reply_markup=main_kb(uid))

@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT telegram_id, full_name, phone_number, balance, total_spent FROM users ORDER BY created_at DESC LIMIT 20"
    )
    if not users:
        await callback.message.edit_text("📭 No users.", reply_markup=back_kb(uid, "admin_back"))
        return
    
    lines = ["👤 Recent Users:\n"]
    for tg, name, phone, balance, spent in users:
        lines.append(f"🆔 {tg} | {name or phone or 'N/A'}\n💰 {balance or 0} ETB")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_kb(uid, "admin_back"))
    await callback.answer()

@router.callback_query(F.data == "admin_refund")
async def admin_refund(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    # Get users with balance
    users = await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC"
    )
    if not users:
        await callback.message.edit_text("✅ No users with balance to refund.", reply_markup=back_kb(uid, "admin_back"))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{u[1]} - {u[2]:,.0f} ETB",
            callback_data=f"refund_user_{u[0]}"
        )] for u in users[:10]
    ] + [[InlineKeyboardButton(text="🔄 Process All", callback_data="refund_all")],
         [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_back")]])
    
    await callback.message.edit_text("🔄 Select user to refund:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("refund_user_"))
async def refund_user(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    user = await DatabaseHelper.fetch_one(
        "SELECT telegram_id, balance FROM users WHERE user_id = ?",
        (user_id,)
    )
    if not user or user[1] <= 0:
        await callback.answer("❌ No balance!", show_alert=True)
        return
    
    tg_id, balance = user
    
    # Process refund
    await DatabaseHelper.execute(
        "INSERT INTO refunds (user_id, amount, reason, status, processed_by, processed_at) VALUES (?, ?, 'Admin refund', 'completed', ?, CURRENT_TIMESTAMP)",
        (user_id, balance, uid)
    )
    await DatabaseHelper.execute(
        "UPDATE users SET balance = 0 WHERE user_id = ?",
        (user_id,)
    )
    
    try:
        await bot.send_message(tg_id, f"✅ Refund of {balance:,.0f} ETB processed.")
    except:
        pass
    
    await callback.message.edit_text(f"✅ Refunded {balance:,.0f} ETB to user.", reply_markup=back_kb(uid, "admin_back"))
    await callback.answer()

@router.callback_query(F.data == "refund_all")
async def refund_all(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    users = await DatabaseHelper.fetch("SELECT user_id, telegram_id, balance FROM users WHERE balance > 0")
    total = 0
    for user_id, tg_id, balance in users:
        await DatabaseHelper.execute_transaction([
            ("INSERT INTO refunds (user_id, amount, reason, status, processed_by, processed_at) VALUES (?, ?, 'Bulk refund', 'completed', ?, CURRENT_TIMESTAMP)", (user_id, balance, uid)),
            ("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
        ])
        total += balance
        try:
            await bot.send_message(tg_id, f"✅ Refund of {balance:,.0f} ETB processed.")
        except:
            pass
    
    await callback.message.edit_text(f"✅ Refunded {total:,.0f} ETB to {len(users)} users.", reply_markup=back_kb(uid, "admin_back"))
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    kb = back_kb(uid, "admin_back")
    await callback.message.edit_text("📢 Enter broadcast message:", reply_markup=kb)
    await state.set_state(AdminState.broadcast_msg)
    await callback.answer()

@router.message(AdminState.broadcast_msg, F.text)
async def send_broadcast(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    users = await DatabaseHelper.fetch("SELECT telegram_id FROM users")
    text = message.text
    
    sent = 0
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 {text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await state.clear()
    await message.answer(f"✅ Broadcast sent to {sent}/{len(users)} users.", reply_markup=main_kb(uid))

@router.callback_query(F.data == "admin_reports")
async def admin_reports(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    games = await DatabaseHelper.fetch("SELECT type_id, name FROM ticket_types")
    if not games:
        await callback.message.edit_text("📭 No games.", reply_markup=back_kb(uid, "admin_back"))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📊 {g[1]}", callback_data=f"report_{g[0]}")] for g in games
    ] + [[InlineKeyboardButton(text="📊 All Users", callback_data="report_all")],
         [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_back")]])
    
    await callback.message.edit_text("📊 Select report:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("report_"))
async def generate_report(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    data = callback.data.split("_")
    
    if data[1] == "all":
        # All users report
        users = await DatabaseHelper.fetch("SELECT telegram_id, full_name, phone_number, balance, total_spent FROM users")
        csv = "Telegram ID,Name,Phone,Balance,Total Spent\n"
        for u in users:
            csv += f"{u[0]},{u[1] or ''},{u[2] or ''},{u[3] or 0},{u[4] or 0}\n"
        name = "all_users"
    else:
        # Game report
        type_id = int(data[1])
        game = await DatabaseHelper.fetch_one("SELECT name FROM ticket_types WHERE type_id = ?", (type_id,))
        tickets = await DatabaseHelper.fetch(
            "SELECT ticket_number, telegram_id, assigned_at FROM tickets WHERE type_id = ? AND status = 'sold'",
            (type_id,)
        )
        csv = f"Game: {game[0]}\nTicket,User ID,Date\n"
        for t in tickets:
            csv += f"{t[0]},{t[1] or 'N/A'},{t[2] or ''}\n"
        name = game[0].replace(" ", "_")
    
    file = io.BytesIO(csv.encode('utf-8'))
    await callback.message.answer_document(
        BufferedInputFile(file.getvalue(), filename=f"{name}_report.csv"),
        caption=f"📊 {name} report"
    )
    await callback.answer()

# =====================================================
# SETUP & MAIN
# =====================================================
async def set_commands():
    commands = [
        BotCommand(command="start", description="🏠 Start"),
        BotCommand(command="admin", description="🛠️ Admin"),
        BotCommand(command="menu", description="📋 Menu"),
    ]
    await bot.set_my_commands(commands)

async def main():
    await init_db()
    await set_commands()
    dp.include_router(router)
    logger.info("🚀 Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Stopped")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
