# =====================================================
# BOT.PY - SIKET EKUB LOTTERY BOT (FIXED)
# Fixed: lang_cache error, all features working
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
from threading import Lock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

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
from database import init_db, DB_NAME

# =====================================================
# ENV
# =====================================================
ssl._create_default_https_context = ssl._create_unverified_context
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

TOKEN = os.getenv("BOT_TOKEN")
admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]

if not TOKEN or not ADMIN_IDS:
    raise ValueError("BOT_TOKEN and ADMIN_IDS required!")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://siket-ekub-webapp.onrender.com")
SUPPORT_CHANNEL_LINK = os.getenv("SUPPORT_CHANNEL_LINK", "https://t.me/siketekub")
TICKET_CHANNEL_LINK = os.getenv("TICKET_CHANNEL_LINK", "https://t.me/siketekubtiketo")
TICKET_CHANNEL_ID = os.getenv("TICKET_CHANNEL_ID", "@siketekubtiketo")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
router = Router()

# =====================================================
# DATABASE HELPER
# =====================================================
DB_LOCK = Lock()

class DatabaseHelper:
    @staticmethod
    async def execute(query: str, params: tuple = None):
        with DB_LOCK:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                cursor = await db.execute(query, params or ())
                await db.commit()
                return cursor
    
    @staticmethod
    async def execute_transaction(queries: list):
        with DB_LOCK:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                try:
                    await db.execute("BEGIN EXCLUSIVE")
                    for query, params in queries:
                        await db.execute(query, params or ())
                    await db.commit()
                    return True
                except:
                    await db.rollback()
                    raise
    
    @staticmethod
    async def fetch(query: str, params: tuple = None):
        with DB_LOCK:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                cursor = await db.execute(query, params or ())
                return await cursor.fetchall()
    
    @staticmethod
    async def fetch_one(query: str, params: tuple = None):
        with DB_LOCK:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                cursor = await db.execute(query, params or ())
                return await cursor.fetchone()
    
    @staticmethod
    async def executemany(query: str, params_list: list):
        with DB_LOCK:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                await db.executemany(query, params_list)
                await db.commit()

# =====================================================
# LANGUAGE CACHE - FIXED
# =====================================================
class LangCache:
    """Simple language cache per user"""
    _cache = {}
    _lock = Lock()
    
    @classmethod
    def get(cls, user_id: int) -> str:
        with cls._lock:
            return cls._cache.get(user_id, "en")
    
    @classmethod
    def set(cls, user_id: int, lang: str):
        with cls._lock:
            cls._cache[user_id] = lang
    
    @classmethod
    def clear(cls, user_id: int):
        with cls._lock:
            if user_id in cls._cache:
                del cls._cache[user_id]

# =====================================================
# LANGUAGE TEXTS
# =====================================================
TEXTS = {
    "en": {
        "welcome": "🎰 Welcome to Siket Ekub Lottery!\n💰 Price: 3,000 ETB",
        "menu": "📋 Menu",
        "buy": "🎯 Buy Ticket",
        "tickets": "🎫 My Tickets",
        "prizes": "🏆 Prizes",
        "balance": "💰 Balance",
        "support": "💬 Support",
        "lang": "🌍 Language",
        "reg_phone": "📱 Share Phone",
        "reg_address": "📍 Enter your address:",
        "registered": "✅ Registered!",
        "pick_ticket": "🎫 Choose ticket:",
        "random_pick": "🎲 Random",
        "type_number": "✏️ Type Number",
        "choose_block": "📦 Choose Block",
        "back": "🔙 Back",
        "pay": "💰 Pay 3,000 ETB to:\nCBE: 1000786684491\nAbyssinia: 264517826\nTelebirr: 0979774444\n\n📸 Send screenshot:",
        "pay_submitted": "✅ Payment sent! Waiting for admin.",
        "pay_approved": "✅ Ticket #{ticket} approved!",
        "pay_rejected": "❌ Payment rejected.",
        "no_tickets": "📭 No tickets yet.",
        "prize_list": "🏆 10 PRIZES:\n1st: BWD Leopard 3 (8M ETB)\n2nd: Hyundai Bayon (5M ETB)\n3rd: Shop Space (4M ETB)\n4th-7th: 1M ETB each\n8th: 500K ETB\n9th: 300K ETB\n10th: 200K ETB",
        "balance_info": "💰 Balance: {balance} ETB\n🎫 Tickets: {tickets}\n💸 Spent: {spent} ETB",
        "admin": "🛠️ Admin",
        "verify": "✅ Verify",
        "create": "📝 Create Game",
        "users": "👤 Users",
        "refund": "🔄 Refund",
        "broadcast": "📢 Broadcast",
        "reports": "📊 Reports",
        "buy_for_user": "🎯 Buy for User",
        "manual_ticket": "📝 Manual Ticket",
        "choose_lang": "🌍 Choose language:",
        "lang_changed": "✅ Language changed!",
        "refund_complete": "✅ Refunded {amount} ETB.",
        "refund_all": "✅ Refunded {total} ETB to {count} users.",
        "no_refund": "✅ No users with balance.",
        "broadcast_sent": "✅ Sent to {sent}/{total} users.",
        "game_created": "✅ Game '{name}' with {slots} tickets!",
        "support_info": "💬 Support: {channel}",
        "your_tickets": "🎫 Your tickets:\n",
        "choose_interface": "🎰 Choose how to play:",
        "use_telegram": "🤖 Use Telegram",
        "open_web": "🌐 Open Web",
        "about": "ℹ️ About",
        "sold": "SOLD",
        "select_block": "📦 Select block:",
        "enter_number": "✏️ Enter ticket number:",
        "invalid_number": "❌ Invalid number.",
        "ticket_not_found": "❌ Ticket not found.",
        "ticket_taken": "❌ Ticket taken.",
        "admin_panel": "🛠️ Admin Panel",
        "back_user": "🔙 Back to User",
        "no_users": "📭 No users found.",
    },
    "am": {
        "welcome": "🎰 እንኳን ወደ ሲኬት ዕቁብ በደህና መጡ!\n💰 ዋጋ: 3,000 ብር",
        "menu": "📋 ምናሌ",
        "buy": "🎯 ቲኬት ግዛ",
        "tickets": "🎫 ቲኬቶቼ",
        "prizes": "🏆 ሽልማቶች",
        "balance": "💰 ቀሪ",
        "support": "💬 ድጋፍ",
        "lang": "🌍 ቋንቋ",
        "reg_phone": "📱 ስልክ አጋሩ",
        "reg_address": "📍 አድራሻ አስገባ:",
        "registered": "✅ ተመዝግበዋል!",
        "pick_ticket": "🎫 ቲኬት ምረጥ:",
        "random_pick": "🎲 በዘፈቀደ",
        "type_number": "✏️ ቁጥር ጻፍ",
        "choose_block": "📦 ብሎክ ምረጥ",
        "back": "🔙 ወደ ኋላ",
        "pay": "💰 3,000 ብር ክፈሉ:\nCBE: 1000786684491\nአቢሲኒያ: 264517826\nተሌብር: 0979774444\n\n📸 ስክሪንሾት ላኩ:",
        "pay_submitted": "✅ ክፍያ ተልኳል! እየተጠበቀ ነው።",
        "pay_approved": "✅ ቲኬት #{ticket} ጸድቋል!",
        "pay_rejected": "❌ ክፍያ ውድቅ ተደርጓል።",
        "no_tickets": "📭 ምንም ቲኬት የለም።",
        "prize_list": "🏆 10 ሽልማቶች:\n1ኛ: BWD Leopard 3 (8M ብር)\n2ኛ: Hyundai Bayon (5M ብር)\n3ኛ: የሱቅ ቦታ (4M ብር)\n4ኛ-7ኛ: 1M ብር\n8ኛ: 500K ብር\n9ኛ: 300K ብር\n10ኛ: 200K ብር",
        "balance_info": "💰 ቀሪ: {balance} ብር\n🎫 ቲኬቶች: {tickets}\n💸 አጠቃላይ: {spent} ብር",
        "admin": "🛠️ አስተዳዳሪ",
        "verify": "✅ አረጋግጥ",
        "create": "📝 ጨዋታ ፍጠር",
        "users": "👤 ተጠቃሚዎች",
        "refund": "🔄 መመለስ",
        "broadcast": "📢 ማስታወቂያ",
        "reports": "📊 ሪፖርቶች",
        "buy_for_user": "🎯 ለሌላ ግዛ",
        "manual_ticket": "📝 በእጅ አስገባ",
        "choose_lang": "🌍 ቋንቋ ምረጥ:",
        "lang_changed": "✅ ቋንቋ ተቀይሯል!",
        "refund_complete": "✅ {amount} ብር ተመልሷል።",
        "refund_all": "✅ {total} ብር ለ {count} ተጠቃሚዎች ተመልሷል።",
        "no_refund": "✅ ቀሪ ያላቸው ተጠቃሚዎች የሉም።",
        "broadcast_sent": "✅ ለ {sent}/{total} ተልኳል።",
        "game_created": "✅ '{name}' ጨዋታ በ {slots} ቲኬቶች ተፈጥሯል!",
        "support_info": "💬 ድጋፍ: {channel}",
        "your_tickets": "🎫 ቲኬቶችዎ:\n",
        "choose_interface": "🎰 እንዴት መጫወት ይፈልጋሉ?",
        "use_telegram": "🤖 በቴሌግራም",
        "open_web": "🌐 በድር",
        "about": "ℹ️ መረጃ",
        "sold": "ተሽጧል",
        "select_block": "📦 ብሎክ ምረጥ:",
        "enter_number": "✏️ ቲኬት ቁጥር አስገባ:",
        "invalid_number": "❌ ልክ ያልሆነ ቁጥር።",
        "ticket_not_found": "❌ ቲኬት አልተገኘም።",
        "ticket_taken": "❌ ቲኬቱ ተወስዷል።",
        "admin_panel": "🛠️ የአስተዳዳሪ ፓነል",
        "back_user": "🔙 ወደ ተጠቃሚ",
        "no_users": "📭 ምንም ተጠቃሚ የለም።",
    }
}

def get_text(user_id: int, key: str, **kwargs) -> str:
    """Get text in user's language"""
    lang = LangCache.get(user_id)
    text = TEXTS.get(lang, TEXTS['en']).get(key, key)
    return text.format(**kwargs) if kwargs else text

# =====================================================
# KEYBOARDS
# =====================================================

def choice_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Use Telegram")],
            [KeyboardButton(text="🌐 Open Web")],
            [KeyboardButton(text="ℹ️ About")],
        ],
        resize_keyboard=True
    )

def user_menu(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_text(uid, "buy")), KeyboardButton(text=get_text(uid, "tickets"))],
            [KeyboardButton(text=get_text(uid, "balance")), KeyboardButton(text=get_text(uid, "prizes"))],
            [KeyboardButton(text=get_text(uid, "support")), KeyboardButton(text=get_text(uid, "lang"))],
        ],
        resize_keyboard=True
    )

def buy_menu(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_text(uid, "random_pick"))],
            [KeyboardButton(text=get_text(uid, "type_number"))],
            [KeyboardButton(text=get_text(uid, "choose_block"))],
            [KeyboardButton(text=get_text(uid, "back"))],
        ],
        resize_keyboard=True
    )

def admin_menu(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛠️ Admin Panel")],
            [KeyboardButton(text=get_text(uid, "verify")), KeyboardButton(text=get_text(uid, "create"))],
            [KeyboardButton(text=get_text(uid, "users")), KeyboardButton(text=get_text(uid, "refund"))],
            [KeyboardButton(text=get_text(uid, "broadcast")), KeyboardButton(text=get_text(uid, "reports"))],
            [KeyboardButton(text=get_text(uid, "buy_for_user")), KeyboardButton(text=get_text(uid, "manual_ticket"))],
            [KeyboardButton(text=get_text(uid, "back_user"))],
        ],
        resize_keyboard=True
    )

# =====================================================
# STATES
# =====================================================
class RegState(StatesGroup):
    phone = State()
    address = State()

class BuyState(StatesGroup):
    block = State()
    payment = State()

class AdminState(StatesGroup):
    game_name = State()
    game_prizes = State()
    game_slots = State()
    broadcast_msg = State()
    buy_user_id = State()
    buy_ticket_num = State()
    manual_ticket = State()

# =====================================================
# START
# =====================================================

@router.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    
    if user:
        lang = user[8] if len(user) > 8 else "en"
        LangCache.set(uid, lang)
        await message.answer(
            "🎰 **Siket Ekub Lottery**\n\nChoose how to play:",
            reply_markup=choice_menu(),
            parse_mode="Markdown"
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")],
    ])
    
    await message.answer(
        "🌍 Welcome! Choose your language:\n\n🌍 ቋንቋ ምረጥ:",
        reply_markup=kb
    )

# =====================================================
# LANGUAGE
# =====================================================

@router.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    lang = callback.data.split("_")[1]
    LangCache.set(uid, lang)
    
    await callback.message.delete()
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text(uid, "reg_phone"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await callback.message.answer(
        f"📱 {get_text(uid, 'reg_phone')}",
        reply_markup=kb
    )
    await state.set_state(RegState.phone)
    await callback.answer()

@router.message(RegState.phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(phone=message.contact.phone_number)
    await message.answer(
        get_text(uid, "reg_address"),
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RegState.address)

@router.message(RegState.address, F.text)
async def reg_address(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    phone = data.get("phone")
    address = message.text
    lang = LangCache.get(uid)
    
    await DatabaseHelper.execute(
        "INSERT INTO users (telegram_id, phone_number, address, language) VALUES (?, ?, ?, ?)",
        (uid, phone, address, lang)
    )
    await state.clear()
    
    await message.answer(
        get_text(uid, "registered"),
        reply_markup=choice_menu()
    )

# =====================================================
# CHOICE MENU
# =====================================================

@router.message(F.text == "🤖 Use Telegram")
async def use_telegram(message: Message):
    uid = message.from_user.id
    await message.answer(
        get_text(uid, "menu"),
        reply_markup=user_menu(uid)
    )

@router.message(F.text == "🌐 Open Web")
async def open_web(message: Message):
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Open Web", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer(
        "🌐 Click to open web interface:",
        reply_markup=kb
    )

@router.message(F.text == "ℹ️ About")
async def about(message: Message):
    uid = message.from_user.id
    await message.answer(
        "🎰 **Siket Ekub Lottery**\n\n"
        "💰 Price: 3,000 ETB\n\n"
        "🏆 **10 PRIZES:**\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "3rd: Shop Space (4,000,000 ETB)\n"
        "4th-7th: 1,000,000 ETB each\n"
        "8th: 500,000 ETB\n"
        "9th: 300,000 ETB\n"
        "10th: 200,000 ETB\n\n"
        "📌 Register > Pick Ticket > Pay > Win!",
        reply_markup=choice_menu(),
        parse_mode="Markdown"
    )

# =====================================================
# BUY TICKET
# =====================================================

@router.message(F.text.in_(["🎯 Buy Ticket", "🎯 ቲኬት ግዛ"]))
async def buy_ticket(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    game = await DatabaseHelper.fetch_one(
        "SELECT type_id FROM ticket_types WHERE is_active = 1 LIMIT 1"
    )
    if not game:
        await message.answer(
            "❌ No active game. Contact admin.",
            reply_markup=user_menu(uid)
        )
        return
    
    await state.update_data(game_id=game[0])
    await message.answer(
        get_text(uid, "pick_ticket"),
        reply_markup=buy_menu(uid)
    )

# Random
@router.message(F.text.in_(["🎲 Random", "🎲 በዘፈቀደ"]))
async def random_ticket(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    type_id = data.get("game_id")
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_id, ticket_number FROM tickets WHERE type_id = ? AND status = 'available' LIMIT 1",
        (type_id,)
    )
    
    if not ticket:
        await message.answer(
            get_text(uid, "no_tickets"),
            reply_markup=buy_menu(uid)
        )
        return
    
    ticket_id, ticket_num = ticket
    await state.update_data(ticket_id=ticket_id, ticket_num=ticket_num)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text(uid, "back"))]],
        resize_keyboard=True
    )
    
    await message.answer(
        f"🎫 Ticket #{ticket_num}\n\n{get_text(uid, 'pay')}",
        reply_markup=kb
    )
    await state.set_state(BuyState.payment)

# Type Number
@router.message(F.text.in_(["✏️ Type Number", "✏️ ቁጥር ጻፍ"]))
async def type_number(message: Message, state: FSMContext):
    uid = message.from_user.id
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text(uid, "back"))]],
        resize_keyboard=True
    )
    await message.answer(
        get_text(uid, "enter_number"),
        reply_markup=kb
    )
    await state.set_state(BuyState.block)

@router.message(BuyState.block, F.text)
async def process_ticket_number(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    if message.text == get_text(uid, "back"):
        await message.answer(
            get_text(uid, "pick_ticket"),
            reply_markup=buy_menu(uid)
        )
        await state.clear()
        return
    
    try:
        ticket_num = int(message.text.strip())
    except:
        await message.answer(get_text(uid, "invalid_number"))
        return
    
    data = await state.get_data()
    type_id = data.get("game_id")
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_id FROM tickets WHERE type_id = ? AND ticket_number = ? AND status = 'available'",
        (type_id, ticket_num)
    )
    
    if not ticket:
        await message.answer(get_text(uid, "ticket_not_found"))
        return
    
    await state.update_data(ticket_id=ticket[0], ticket_num=ticket_num)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text(uid, "back"))]],
        resize_keyboard=True
    )
    
    await message.answer(
        f"🎫 Ticket #{ticket_num}\n\n{get_text(uid, 'pay')}",
        reply_markup=kb
    )
    await state.set_state(BuyState.payment)

# Choose Block
@router.message(F.text.in_(["📦 Choose Block", "📦 ብሎክ ምረጥ"]))
async def choose_block(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1-1000"), KeyboardButton(text="1001-2000")],
            [KeyboardButton(text="2001-3000"), KeyboardButton(text="3001-4000")],
            [KeyboardButton(text="4001-5000"), KeyboardButton(text="5001-6000")],
            [KeyboardButton(text="6001-7000"), KeyboardButton(text="7001-8000")],
            [KeyboardButton(text="8001-9000"), KeyboardButton(text="9001-10000")],
            [KeyboardButton(text="10001-11000"), KeyboardButton(text="11001-12000")],
            [KeyboardButton(text="12001-13000"), KeyboardButton(text="13001-14000")],
            [KeyboardButton(text="14001-15000"), KeyboardButton(text="15001-16000")],
            [KeyboardButton(text="16001-17000"), KeyboardButton(text="17001-18000")],
            [KeyboardButton(text="18001-19000"), KeyboardButton(text="19001-20000")],
            [KeyboardButton(text=get_text(uid, "back"))],
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        get_text(uid, "select_block"),
        reply_markup=kb
    )

@router.message(F.text.regexp(r'^\d+-\d+$'))
async def process_block(message: Message, state: FSMContext):
    uid = message.from_user.id
    start, end = map(int, message.text.split('-'))
    data = await state.get_data()
    type_id = data.get("game_id")
    
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_id, ticket_number FROM tickets WHERE type_id = ? AND ticket_number BETWEEN ? AND ? AND status = 'available' LIMIT 50",
        (type_id, start, end)
    )
    
    if not tickets:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=get_text(uid, "back"))]],
            resize_keyboard=True
        )
        await message.answer("❌ No tickets in this block.", reply_markup=kb)
        return
    
    kb_rows = []
    row = []
    for ticket_id, ticket_num in tickets:
        row.append(KeyboardButton(text=str(ticket_num)))
        if len(row) == 5:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([KeyboardButton(text=get_text(uid, "back"))])
    
    await message.answer(
        f"🎫 Available tickets in {start}-{end}:",
        reply_markup=ReplyKeyboardMarkup(keyboard=kb_rows, resize_keyboard=True)
    )
    await state.set_state(BuyState.block)

# =====================================================
# PAYMENT
# =====================================================

@router.message(BuyState.payment, F.photo | F.text)
async def process_payment(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    if message.text == get_text(uid, "back"):
        await message.answer(
            get_text(uid, "pick_ticket"),
            reply_markup=buy_menu(uid)
        )
        await state.clear()
        return
    
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    ticket_num = data.get("ticket_num")
    
    if not ticket_id:
        await message.answer("❌ No ticket.", reply_markup=user_menu(uid))
        await state.clear()
        return
    
    user = await DatabaseHelper.fetch_one("SELECT user_id FROM users WHERE telegram_id = ?", (uid,))
    if not user:
        await message.answer("❌ Please /start first.")
        return
    
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
    await message.answer(
        get_text(uid, "pay_submitted"),
        reply_markup=user_menu(uid)
    )
    
    for admin in ADMIN_IDS:
        try:
            msg = f"🔔 New Payment\n🎫 #{ticket_num}\n👤 {uid}\n🆔 {payment_id}"
            if screenshot:
                img = base64.b64decode(screenshot)
                await bot.send_photo(
                    admin,
                    BufferedInputFile(img, filename="pay.jpg"),
                    caption=msg,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
                        [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")]
                    ])
                )
            else:
                await bot.send_message(
                    admin,
                    msg,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
                        [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")]
                    ])
                )
        except:
            pass

# =====================================================
# APPROVE/REJECT
# =====================================================

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
        await callback.answer("❌ Not found!", show_alert=True)
        return
    
    tg_id, ticket_id, ticket_num = payment
    
    cursor = await DatabaseHelper.execute(
        "UPDATE tickets SET status = 'sold', telegram_id = ?, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = ? AND status = 'available'",
        (tg_id, ticket_id)
    )
    
    if cursor.rowcount == 0:
        await DatabaseHelper.execute(
            "UPDATE payments SET status = 'rejected', admin_notes = 'Ticket already sold' WHERE payment_id = ?",
            (payment_id,)
        )
        await callback.message.edit_text(f"❌ Ticket #{ticket_num} already sold!")
        await callback.answer()
        return
    
    await DatabaseHelper.execute_transaction([
        ("UPDATE payments SET status = 'approved', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE payment_id = ?", (uid, payment_id)),
        ("UPDATE users SET balance = COALESCE(balance, 0) + 3000, total_spent = COALESCE(total_spent, 0) + 3000 WHERE telegram_id = ?", (tg_id,))
    ])
    
    try:
        user = await DatabaseHelper.fetch_one("SELECT phone_number FROM users WHERE telegram_id = ?", (tg_id,))
        phone = user[0] if user else "N/A"
        await bot.send_message(
            TICKET_CHANNEL_ID,
            f"🎟️ Verified Ticket\n#{ticket_num}\n👤 {phone}\n💰 3,000 ETB\n✅ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
    except:
        pass
    
    try:
        await bot.send_message(tg_id, get_text(tg_id, "pay_approved", ticket=ticket_num))
    except:
        pass
    
    await callback.message.edit_text(f"✅ Payment #{payment_id} approved!\n🎫 Ticket #{ticket_num}")
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
            "UPDATE payments SET status = 'rejected', verified_by = ? WHERE payment_id = ?",
            (uid, payment_id)
        )
        try:
            await bot.send_message(payment[0], get_text(payment[0], "pay_rejected"))
        except:
            pass
    
    await callback.message.edit_text(f"❌ Payment #{payment_id} rejected.")
    await callback.answer()

# =====================================================
# BACK
# =====================================================

@router.message(F.text.in_(["🔙 Back", "🔙 ወደ ኋላ"]))
async def go_back(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    await message.answer(
        get_text(uid, "menu"),
        reply_markup=user_menu(uid)
    )

@router.message(F.text == "🔙 Back to User")
async def back_to_user(message: Message):
    uid = message.from_user.id
    await message.answer(
        get_text(uid, "menu"),
        reply_markup=user_menu(uid)
    )

# =====================================================
# USER COMMANDS
# =====================================================

@router.message(F.text.in_(["🎫 My Tickets", "🎫 ቲኬቶቼ"]))
async def my_tickets(message: Message):
    uid = message.from_user.id
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_number, assigned_at FROM tickets WHERE telegram_id = ? AND status = 'sold'",
        (uid,)
    )
    if not tickets:
        await message.answer(get_text(uid, "no_tickets"), reply_markup=user_menu(uid))
        return
    
    lines = [get_text(uid, "your_tickets")]
    for num, date in tickets[:10]:
        lines.append(f"#{num} - {date[:10] if date else 'N/A'}")
    if len(tickets) > 10:
        lines.append(f"... {len(tickets)-10} more")
    
    await message.answer("\n".join(lines), reply_markup=user_menu(uid))

@router.message(F.text.in_(["💰 Balance", "💰 ቀሪ"]))
async def balance_cmd(message: Message):
    uid = message.from_user.id
    user = await DatabaseHelper.fetch_one(
        "SELECT balance, total_spent FROM users WHERE telegram_id = ?",
        (uid,)
    )
    if not user:
        await message.answer("❌ Please /start first.")
        return
    
    tickets = await DatabaseHelper.fetch_one(
        "SELECT COUNT(*) FROM tickets WHERE telegram_id = ? AND status = 'sold'",
        (uid,)
    )
    await message.answer(
        get_text(uid, "balance_info", balance=user[0] or 0, tickets=tickets[0] or 0, spent=user[1] or 0),
        reply_markup=user_menu(uid)
    )

@router.message(F.text.in_(["🏆 Prizes", "🏆 ሽልማቶች"]))
async def prizes_cmd(message: Message):
    uid = message.from_user.id
    await message.answer(get_text(uid, "prize_list"), reply_markup=user_menu(uid))

@router.message(F.text.in_(["💬 Support", "💬 ድጋፍ"]))
async def support_cmd(message: Message):
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Support", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton(text="🎟️ Tickets", url=TICKET_CHANNEL_LINK)],
    ])
    await message.answer(
        get_text(uid, "support_info", channel=SUPPORT_CHANNEL_LINK),
        reply_markup=kb
    )

@router.message(F.text.in_(["🌍 Language", "🌍 ቋንቋ"]))
async def lang_cmd(message: Message):
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")],
    ])
    await message.answer(get_text(uid, "choose_lang"), reply_markup=kb)

@router.callback_query(F.data.startswith("lang_"))
async def change_lang(callback: CallbackQuery):
    uid = callback.from_user.id
    lang = callback.data.split("_")[1]
    LangCache.set(uid, lang)
    
    await DatabaseHelper.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?",
        (lang, uid)
    )
    
    await callback.message.delete()
    await callback.message.answer(
        get_text(uid, "lang_changed"),
        reply_markup=user_menu(uid)
    )
    await callback.answer()

# =====================================================
# ADMIN COMMANDS
# =====================================================

@router.message(F.text == "🛠️ Admin Panel")
@router.message(Command("admin"))
async def admin_cmd(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!", reply_markup=user_menu(uid))
        return
    await message.answer(
        get_text(uid, "admin_panel"),
        reply_markup=admin_menu(uid)
    )

# =====================================================
# ADMIN: CREATE GAME
# =====================================================

@router.message(F.text.in_(["📝 Create Game", "📝 ጨዋታ ፍጠር"]))
async def admin_create_game(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer(
        "📝 Enter game name:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Back to User")]],
            resize_keyboard=True
        )
    )
    await state.set_state(AdminState.game_name)

@router.message(AdminState.game_name, F.text)
async def create_game_name(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    if message.text == "🔙 Back to User":
        await back_to_user(message)
        await state.clear()
        return
    
    await state.update_data(name=message.text)
    await message.answer("📝 Enter prizes (one per line):\n1st: Prize 1\n2nd: Prize 2\n...")
    await state.set_state(AdminState.game_prizes)

@router.message(AdminState.game_prizes, F.text)
async def create_game_prizes(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await state.update_data(prizes=message.text)
    await message.answer("📝 Enter total slots (default: 20000):")
    await state.set_state(AdminState.game_slots)

@router.message(AdminState.game_slots, F.text)
async def create_game_slots(message: Message, state: FSMContext):
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
    
    cursor = await DatabaseHelper.execute(
        "INSERT INTO ticket_types (name, price, total_slots, is_active, prizes) VALUES (?, 3000, ?, 1, ?)",
        (name, slots, prizes)
    )
    type_id = cursor.lastrowid
    
    batch_size = 1000
    for start in range(1, slots + 1, batch_size):
        end = min(start + batch_size - 1, slots)
        values = [(type_id, i, 'available') for i in range(start, end + 1)]
        await DatabaseHelper.executemany(
            "INSERT INTO tickets (type_id, ticket_number, status) VALUES (?, ?, ?)",
            values
        )
        logger.info(f"Created tickets {start}-{end}")
    
    await state.clear()
    await message.answer(
        get_text(uid, "game_created", name=name, slots=slots),
        reply_markup=admin_menu(uid)
    )

# =====================================================
# ADMIN: VERIFY
# =====================================================

@router.message(F.text.in_(["✅ Verify", "✅ አረጋግጥ"]))
async def admin_verify(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    payments = await DatabaseHelper.fetch(
        "SELECT payment_id, telegram_id, ticket_number, created_at FROM payments WHERE status = 'pending'"
    )
    if not payments:
        await message.answer("📭 No pending payments.", reply_markup=admin_menu(uid))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"#{p[0]} - #{p[2]} - {p[3][:10]}",
            callback_data=f"view_pay_{p[0]}"
        )] for p in payments[:10]
    ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]])
    
    await message.answer(f"📋 Pending Payments ({len(payments)})", reply_markup=kb)

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
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
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
            await callback.message.edit_text(text + "\n\n📸 Screenshot attached", reply_markup=kb)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    uid = callback.from_user.id
    await callback.message.delete()
    await callback.message.answer(
        get_text(uid, "admin_panel"),
        reply_markup=admin_menu(uid)
    )
    await callback.answer()

# =====================================================
# ADMIN: USERS
# =====================================================

@router.message(F.text.in_(["👤 Users", "👤 ተጠቃሚዎች"]))
async def admin_users(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT telegram_id, full_name, phone_number, balance FROM users ORDER BY created_at DESC LIMIT 20"
    )
    if not users:
        await message.answer(get_text(uid, "no_users"), reply_markup=admin_menu(uid))
        return
    
    lines = ["👤 **Recent Users:**\n"]
    for tg, name, phone, balance in users:
        lines.append(f"🆔 {tg} | {name or phone or 'N/A'}\n💰 {balance or 0} ETB")
    
    await message.answer(
        "\n".join(lines),
        reply_markup=admin_menu(uid),
        parse_mode="Markdown"
    )

# =====================================================
# ADMIN: REFUND
# =====================================================

@router.message(F.text.in_(["🔄 Refund", "🔄 መመለስ"]))
async def admin_refund(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC"
    )
    if not users:
        await message.answer(get_text(uid, "no_refund"), reply_markup=admin_menu(uid))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{u[1]} - {u[2]:,.0f} ETB",
            callback_data=f"refund_user_{u[0]}"
        )] for u in users[:10]
    ] + [[InlineKeyboardButton(text="🔄 Process All", callback_data="refund_all")],
         [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]])
    
    await message.answer("🔄 Select user to refund:", reply_markup=kb)

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
    
    await DatabaseHelper.execute_transaction([
        ("INSERT INTO refunds (user_id, amount, reason, status, processed_by, processed_at) VALUES (?, ?, 'Admin refund', 'completed', ?, CURRENT_TIMESTAMP)", (user_id, balance, uid)),
        ("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    ])
    
    try:
        await bot.send_message(tg_id, get_text(tg_id, "refund_complete", amount=balance))
    except:
        pass
    
    await callback.message.edit_text(
        f"✅ Refunded {balance:,.0f} ETB",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "refund_all")
async def refund_all(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    users = await DatabaseHelper.fetch("SELECT user_id, telegram_id, balance FROM users WHERE balance > 0")
    if not users:
        await callback.answer(get_text(uid, "no_refund"), show_alert=True)
        return
    
    total = 0
    for user_id, tg_id, balance in users:
        await DatabaseHelper.execute_transaction([
            ("INSERT INTO refunds (user_id, amount, reason, status, processed_by, processed_at) VALUES (?, ?, 'Bulk refund', 'completed', ?, CURRENT_TIMESTAMP)", (user_id, balance, uid)),
            ("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
        ])
        total += balance
        try:
            await bot.send_message(tg_id, get_text(tg_id, "refund_complete", amount=balance))
        except:
            pass
        await asyncio.sleep(0.05)
    
    await callback.message.edit_text(
        get_text(uid, "refund_all", total=total, count=len(users)),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
        ])
    )
    await callback.answer()

# =====================================================
# ADMIN: BROADCAST
# =====================================================

@router.message(F.text.in_(["📢 Broadcast", "📢 ማስታወቂያ"]))
async def admin_broadcast(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer(
        "📢 Enter message to broadcast:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Back to User")]],
            resize_keyboard=True
        )
    )
    await state.set_state(AdminState.broadcast_msg)

@router.message(AdminState.broadcast_msg, F.text)
async def send_broadcast(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    if message.text == "🔙 Back to User":
        await back_to_user(message)
        await state.clear()
        return
    
    users = await DatabaseHelper.fetch("SELECT telegram_id FROM users")
    if not users:
        await message.answer("❌ No users.", reply_markup=admin_menu(uid))
        await state.clear()
        return
    
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
    await message.answer(
        get_text(uid, "broadcast_sent", sent=sent, total=len(users)),
        reply_markup=admin_menu(uid)
    )

# =====================================================
# ADMIN: REPORTS
# =====================================================

@router.message(F.text.in_(["📊 Reports", "📊 ሪፖርቶች"]))
async def admin_reports(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    total_users = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM users")
    total_tickets = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM tickets WHERE status = 'sold'")
    total_revenue = await DatabaseHelper.fetch_one("SELECT SUM(total_spent) FROM users")
    pending = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
    
    text = (
        f"📊 **Reports**\n\n"
        f"👤 Users: {total_users[0] or 0}\n"
        f"🎫 Sold: {total_tickets[0] or 0}\n"
        f"💰 Revenue: {total_revenue[0] or 0:,.0f} ETB\n"
        f"⏳ Pending: {pending[0] or 0}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Download Report", callback_data="download_report")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "download_report")
async def download_report(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_number, telegram_id, assigned_at FROM tickets WHERE status = 'sold'"
    )
    
    csv = "Ticket,User ID,Date\n"
    for t in tickets:
        csv += f"{t[0]},{t[1] or 'N/A'},{t[2] or ''}\n"
    
    file = io.BytesIO(csv.encode('utf-8'))
    await callback.message.answer_document(
        BufferedInputFile(file.getvalue(), filename="tickets_report.csv"),
        caption="📊 Tickets Report"
    )
    await callback.answer()

# =====================================================
# ADMIN: BUY FOR USER
# =====================================================

@router.message(F.text.in_(["🎯 Buy for User", "🎯 ለሌላ ግዛ"]))
async def admin_buy_user(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer(
        "📝 Enter user Telegram ID:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Back to User")]],
            resize_keyboard=True
        )
    )
    await state.set_state(AdminState.buy_user_id)

@router.message(AdminState.buy_user_id, F.text)
async def admin_buy_user_id(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    if message.text == "🔙 Back to User":
        await back_to_user(message)
        await state.clear()
        return
    
    try:
        target_id = int(message.text.strip())
    except:
        await message.answer("❌ Invalid ID. Enter number:")
        return
    
    user = await DatabaseHelper.fetch_one("SELECT user_id FROM users WHERE telegram_id = ?", (target_id,))
    if not user:
        await message.answer("❌ User not found!")
        return
    
    await state.update_data(target_user=target_id)
    await message.answer("📝 Enter ticket number (or 'random'):")
    await state.set_state(AdminState.buy_ticket_num)

@router.message(AdminState.buy_ticket_num, F.text)
async def admin_buy_ticket(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    target_id = data.get("target_user")
    
    ticket_input = message.text.strip().lower()
    
    if ticket_input == 'random':
        ticket = await DatabaseHelper.fetch_one(
            "SELECT ticket_id, ticket_number FROM tickets WHERE status = 'available' LIMIT 1"
        )
    else:
        try:
            num = int(ticket_input)
            ticket = await DatabaseHelper.fetch_one(
                "SELECT ticket_id, ticket_number FROM tickets WHERE ticket_number = ? AND status = 'available'",
                (num,)
            )
        except:
            await message.answer("❌ Invalid number.")
            return
    
    if not ticket:
        await message.answer("❌ No available ticket.")
        return
    
    ticket_id, ticket_num = ticket
    
    user = await DatabaseHelper.fetch_one("SELECT user_id, phone_number FROM users WHERE telegram_id = ?", (target_id,))
    user_id, phone = user
    
    await DatabaseHelper.execute_transaction([
        ("UPDATE tickets SET status = 'sold', user_id = ?, telegram_id = ?, phone_number = ?, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = ?", (user_id, target_id, phone, ticket_id)),
        ("INSERT INTO payments (user_id, telegram_id, ticket_id, ticket_number, extracted_amount, status, admin_notes) VALUES (?, ?, ?, ?, 3000.0, 'approved', ?)", (user_id, target_id, ticket_id, ticket_num, "Admin purchase"))
    ])
    
    await state.clear()
    await message.answer(
        f"✅ Ticket #{ticket_num} assigned to user {target_id}!",
        reply_markup=admin_menu(uid)
    )
    
    try:
        await bot.send_message(target_id, f"🎉 Admin purchased ticket #{ticket_num} for you!")
    except:
        pass

# =====================================================
# ADMIN: MANUAL TICKET
# =====================================================

@router.message(F.text.in_(["📝 Manual Ticket", "📝 በእጅ አስገባ"]))
async def admin_manual(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer(
        "📝 Enter ticket number to mark as sold:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Back to User")]],
            resize_keyboard=True
        )
    )
    await state.set_state(AdminState.manual_ticket)

@router.message(AdminState.manual_ticket, F.text)
async def admin_manual_process(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    if message.text == "🔙 Back to User":
        await back_to_user(message)
        await state.clear()
        return
    
    try:
        num = int(message.text.strip())
    except:
        await message.answer("❌ Invalid number.")
        return
    
    cursor = await DatabaseHelper.execute(
        "UPDATE tickets SET status = 'sold', assigned_at = CURRENT_TIMESTAMP WHERE ticket_number = ? AND status = 'available'",
        (num,)
    )
    
    if cursor.rowcount > 0:
        await message.answer(f"✅ Ticket #{num} marked as sold!", reply_markup=admin_menu(uid))
    else:
        await message.answer(f"❌ Ticket #{num} not available.", reply_markup=admin_menu(uid))
    
    await state.clear()

# =====================================================
# MAIN
# =====================================================

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Start"),
        BotCommand(command="admin", description="🛠️ Admin"),
    ])

async def main():
    await init_db()
    await set_commands()
    dp.include_router(router)
    logger.info("🚀 Bot started!")
    logger.info(f"👤 Admins: {ADMIN_IDS}")
    logger.info(f"🌐 WebApp: {WEBAPP_URL}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Stopped")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
