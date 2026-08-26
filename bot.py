# =====================================================
# BOT.PY - SIKET EKUB COMPLETE
# =====================================================

import sys
import os
import logging
import asyncio
import random
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

import asyncpg
from dotenv import load_dotenv

# =====================================================
# ENV SETUP
# =====================================================
ssl._create_default_https_context = ssl._create_unverified_context
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

TOKEN = os.getenv("BOT_TOKEN", "").strip()
admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]

if not TOKEN or not ADMIN_IDS:
    raise ValueError("BOT_TOKEN and ADMIN_IDS required!")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing!")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://siket-ekub-webapp.onrender.com")
SUPPORT_CHANNEL_LINK = os.getenv("SUPPORT_CHANNEL_LINK", "https://t.me/siketekub")
TICKET_CHANNEL_LINK = os.getenv("TICKET_CHANNEL_LINK", "https://t.me/siketekubtiketo")
TICKET_CHANNEL_ID = os.getenv("TICKET_CHANNEL_ID", "@siketekubtiketo")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =====================================================
# BOT INITIALIZATION
# =====================================================
storage = MemoryStorage()
telegram_bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
router = Router()

# =====================================================
# POSTGRESQL CONNECTION
# =====================================================
db_pool = None

async def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        logger.info("✅ PostgreSQL connected")
    return db_pool

# =====================================================
# DATABASE HELPER
# =====================================================
class DatabaseHelper:
    @staticmethod
    async def fetch_one(query: str, *params):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if params:
                return await conn.fetchrow(query, *params)
            return await conn.fetchrow(query)
    
    @staticmethod
    async def fetch(query: str, *params):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if params:
                return await conn.fetch(query, *params)
            return await conn.fetch(query)
    
    @staticmethod
    async def execute(query: str, *params):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if params and params[0] is not None:
                return await conn.execute(query, *params)
            return await conn.execute(query)
    
    @staticmethod
    async def execute_transaction(queries: list):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for item in queries:
                    if isinstance(item, tuple):
                        query, *params = item
                        if params:
                            await conn.execute(query, *params)
                        else:
                            await conn.execute(query)
                    else:
                        await conn.execute(item)
                return True

# =====================================================
# INIT DATABASE
# =====================================================
async def init_db_postgres():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                full_name VARCHAR(255),
                phone_number VARCHAR(20),
                address TEXT,
                balance DECIMAL(15,2) DEFAULT 0,
                total_spent DECIMAL(15,2) DEFAULT 0,
                language VARCHAR(10) DEFAULT 'en',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tickets table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id SERIAL PRIMARY KEY,
                ticket_number INTEGER UNIQUE NOT NULL,
                type_id INTEGER DEFAULT 1,
                ticket_code VARCHAR(50),
                status VARCHAR(20) DEFAULT 'available',
                user_id INTEGER REFERENCES users(user_id),
                telegram_id BIGINT,
                phone_number VARCHAR(20),
                full_name VARCHAR(255),
                assigned_at TIMESTAMP
            )
        """)
        
        # Payments table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(user_id),
                telegram_id BIGINT,
                phone_number VARCHAR(20),
                full_name VARCHAR(255),
                ticket_id INTEGER REFERENCES tickets(ticket_id),
                ticket_number INTEGER,
                amount DECIMAL(15,2) DEFAULT 3000,
                raw_sms TEXT,
                extracted_ref VARCHAR(100),
                extracted_amount DECIMAL(15,2),
                extracted_date VARCHAR(50),
                status VARCHAR(20) DEFAULT 'pending',
                screenshot_data TEXT,
                admin_notes TEXT,
                verified_by INTEGER,
                verified_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Refunds table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS refunds (
                refund_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(user_id),
                telegram_id BIGINT,
                phone_number VARCHAR(20),
                refund_amount DECIMAL(15,2),
                refund_reason TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                processed_by INTEGER,
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_telegram_id ON payments(telegram_id)")
        logger.info("✅ PostgreSQL tables ready")

async def generate_tickets():
    """Generate 20000 tickets"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Fix columns if needed
            try:
                await conn.execute("ALTER TABLE tickets ALTER COLUMN type_id DROP NOT NULL")
            except:
                pass
            try:
                await conn.execute("ALTER TABLE tickets ALTER COLUMN ticket_code DROP NOT NULL")
            except:
                pass
            
            count = await conn.fetchval("SELECT COUNT(*) FROM tickets")
            if count and count > 0:
                logger.info(f"✅ {count} tickets already exist")
                available = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE status = 'available'")
                logger.info(f"🎫 Available tickets: {available}")
                
                if available == 0 and count > 0:
                    logger.info("🔄 Resetting tickets to available...")
                    await conn.execute("""
                        UPDATE tickets 
                        SET status = 'available', user_id = NULL, telegram_id = NULL, 
                        phone_number = NULL, full_name = NULL, assigned_at = NULL 
                        WHERE status != 'available'
                    """)
                    logger.info("✅ Reset tickets to available")
                return
            
            logger.info("🎫 Generating 20000 tickets...")
            batch_size = 500
            for start in range(1, 20001, batch_size):
                end = min(start + batch_size - 1, 20000)
                values = []
                for i in range(start, end + 1):
                    ticket_code = f"TKT-{i:05d}"
                    values.append(f"({i}, 1, '{ticket_code}', 'available')")
                query = f"INSERT INTO tickets (ticket_number, type_id, ticket_code, status) VALUES {','.join(values)}"
                await conn.execute(query)
                logger.info(f"✅ Generated tickets {start}-{end}")
            
            final_count = await conn.fetchval("SELECT COUNT(*) FROM tickets")
            logger.info(f"✅ All {final_count} tickets generated successfully!")
    except Exception as e:
        logger.error(f"❌ Error generating tickets: {e}")
        import traceback
        traceback.print_exc()

# =====================================================
# LANGUAGE TEXTS
# =====================================================
TEXTS = {
    "en": {
        "welcome": "🎰 Welcome to Siket Ekub!",
        "menu": "📋 Main Menu",
        "buy": "🎯 Buy Ticket",
        "tickets": "🎫 My Tickets",
        "prizes": "🏆 Prizes",
        "balance": "💰 Balance",
        "support": "💬 Support",
        "lang": "🌍 Language",
        "reg_phone": "📱 Share your phone number:",
        "reg_address": "📍 Enter your address:",
        "reg_name": "📝 Enter your full name:",
        "registered": "✅ Registration complete!",
        "pick_ticket": "🎫 Choose how to pick your ticket:",
        "random_pick": "🎲 Random Ticket",
        "type_number": "✏️ Type Number",
        "choose_block": "📦 Choose Block (50 tickets)",
        "back": "🔙 Back",
        "pay": "💰 Pay 3,000 ETB to:\nCBE: 1000786684491\nAbyssinia: 264517826\nTelebirr: 0979774444\n\n📸 Send payment screenshot:",
        "pay_submitted": "✅ Payment submitted! Waiting for admin verification.",
        "pay_approved": "✅ Ticket #{ticket} approved!",
        "pay_rejected": "❌ Payment rejected.",
        "no_tickets": "📭 No tickets available.",
        "no_tickets_owned": "📭 You have no tickets yet.",
        "prize_list": "🏆 10 PRIZES:\n1st: BWD Leopard 3 (8,000,000 ETB)\n2nd: Hyundai Bayon (5,000,000 ETB)\n3rd: Shop Space (4,000,000 ETB)\n4th-7th: 1,000,000 ETB each\n8th: 500,000 ETB\n9th: 300,000 ETB\n10th: 200,000 ETB",
        "balance_info": "💰 Balance: {balance} ETB\n🎫 Tickets: {tickets}\n💸 Total Spent: {spent} ETB",
        "admin": "🛠️ Admin",
        "verify": "✅ Verify Payments",
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
        "support_info": "💬 Support Channel: {channel}",
        "your_tickets": "🎫 Your Tickets ({count}):\n",
        "choose_interface": "🎰 Choose how to play:",
        "use_telegram": "🤖 Use Telegram",
        "open_web": "🌐 Open Web",
        "about": "ℹ️ About",
        "sold": "SOLD",
        "select_block": "📦 Select a block (50 tickets each):",
        "enter_number": "✏️ Enter ticket number (1-20000):",
        "invalid_number": "❌ Invalid number. Please enter 1-20000.",
        "ticket_not_found": "❌ Ticket not found or already taken.",
        "ticket_taken": "❌ Ticket already taken.",
        "admin_panel": "🛠️ Admin Panel",
        "back_user": "🔙 Back to User",
        "no_users": "📭 No users found.",
        "registration_required": "❌ Please /start first to register.",
        "your_ticket_list": "🎫 Your Tickets:\n",
        "ticket_info": "🎫 Ticket #{num}\n📅 {date}\n",
        "total_paid": "💰 Total Paid: {amount} ETB",
        "pending_payments": "⏳ Pending Payments: {count}",
        "user_profile": "👤 User Profile\n\n🆔 ID: {id}\n📝 Name: {name}\n📱 Phone: {phone}\n📍 Address: {address}\n💰 Balance: {balance} ETB\n🎫 Tickets: {tickets}\n💸 Total Spent: {spent} ETB",
        "user_not_found": "❌ User not found!",
        "user_already_registered": "✅ User is already registered!",
        "user_added": "✅ User added successfully!",
        "enter_user_id": "📝 Enter Telegram ID of the user:",
        "enter_ticket_number": "📝 Enter ticket number to assign:",
        "ticket_assigned": "✅ Ticket #{ticket} assigned to user!",
        "ticket_already_sold": "❌ Ticket already sold!",
        "user_info": "👤 User Info\n\n🆔 ID: {id}\n📝 Name: {name}\n📱 Phone: {phone}\n📍 Address: {address}\n💰 Balance: {balance} ETB\n🎫 Tickets: {tickets}\n💸 Total Spent: {spent} ETB",
    },
    "am": {
        "welcome": "🎰 እንኳን ወደ ስኬት እቁብ በደህና መጡ!",
        "menu": "📋 ዋና ምናሌ",
        "buy": "🎯 ቲኬት ግዛ",
        "tickets": "🎫 ቲኬቶቼ",
        "prizes": "🏆 ሽልማቶች",
        "balance": "💰 ቀሪ",
        "support": "💬 ድጋፍ",
        "lang": "🌍 ቋንቋ",
        "reg_phone": "📱 ስልክ ቁጥርዎን ያጋሩ:",
        "reg_address": "📍 አድራሻዎን ያስገቡ:",
        "reg_name": "📝 ሙሉ ስምዎን ያስገቡ:",
        "registered": "✅ ምዝገባ ተጠናቋል!",
        "pick_ticket": "🎫 ቲኬት ለመምረጥ ይምረጡ:",
        "random_pick": "🎲 በዘፈቀደ",
        "type_number": "✏️ ቁጥር ይጻፉ",
        "choose_block": "📦 ብሎክ ምረጥ (50 ቲኬቶች)",
        "back": "🔙 ወደ ኋላ",
        "pay": "💰 3,000 ብር ክፈሉ:\nCBE: 1000786684491\nአቢሲኒያ: 264517826\nተሌብር: 0979774444\n\n📸 የክፍያ ስክሪንሾት ይላኩ:",
        "pay_submitted": "✅ ክፍያ ተልኳል! አስተዳዳሪ እየጠበቀ ነው።",
        "pay_approved": "✅ ቲኬት #{ticket} ጸድቋል!",
        "pay_rejected": "❌ ክፍያ ውድቅ ተደርጓል።",
        "no_tickets": "📭 ምንም ቲኬት የለም።",
        "no_tickets_owned": "📭 እስካሁን ምንም ቲኬት የለዎትም።",
        "prize_list": "🏆 10 ሽልማቶች:\n1ኛ: BWD Leopard 3 (8,000,000 ብር)\n2ኛ: Hyundai Bayon (5,000,000 ብር)\n3ኛ: የሱቅ ቦታ (4,000,000 ብር)\n4ኛ-7ኛ: 1,000,000 ብር\n8ኛ: 500,000 ብር\n9ኛ: 300,000 ብር\n10ኛ: 200,000 ብር",
        "balance_info": "💰 ቀሪ: {balance} ብር\n🎫 ቲኬቶች: {tickets}\n💸 አጠቃላይ: {spent} ብር",
        "admin": "🛠️ አስተዳዳሪ",
        "verify": "✅ ክፍያዎችን አረጋግጥ",
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
        "support_info": "💬 የድጋፍ ቻናል: {channel}",
        "your_tickets": "🎫 ቲኬቶችዎ ({count}):\n",
        "choose_interface": "🎰 እንዴት መጫወት ይፈልጋሉ?",
        "use_telegram": "🤖 በቴሌግራም",
        "open_web": "🌐 በድረ-ገጽ",
        "about": "ℹ️ መረጃ",
        "sold": "ተሽጧል",
        "select_block": "📦 ብሎክ ምረጥ (50 ቲኬቶች):",
        "enter_number": "✏️ ቲኬት ቁጥር ያስገቡ (1-20000):",
        "invalid_number": "❌ ልክ ያልሆነ ቁጥር። እባክዎ 1-20000 ያስገቡ።",
        "ticket_not_found": "❌ ቲኬቱ አልተገኘም ወይም ተወስዷል።",
        "ticket_taken": "❌ ቲኬቱ ተወስዷል።",
        "admin_panel": "🛠️ የአስተዳዳሪ ፓነል",
        "back_user": "🔙 ወደ ተጠቃሚ",
        "no_users": "📭 ምንም ተጠቃሚ የለም።",
        "registration_required": "❌ እባክዎ ለመመዝገብ /start ይጫኑ።",
        "your_ticket_list": "🎫 ቲኬቶችዎ:\n",
        "ticket_info": "🎫 ቲኬት #{num}\n📅 {date}\n",
        "total_paid": "💰 አጠቃላይ ክፍያ: {amount} ብር",
        "pending_payments": "⏳ በመጠባበቅ ላይ: {count}",
        "user_profile": "👤 የተጠቃሚ መገለጫ\n\n🆔 መታወቂያ: {id}\n📝 ስም: {name}\n📱 ስልክ: {phone}\n📍 አድራሻ: {address}\n💰 ቀሪ: {balance} ብር\n🎫 ቲኬቶች: {tickets}\n💸 አጠቃላይ: {spent} ብር",
        "user_not_found": "❌ ተጠቃሚ አልተገኘም!",
        "user_already_registered": "✅ ተጠቃሚው ቀድሞውኑ ተመዝግቧል!",
        "user_added": "✅ ተጠቃሚ ተጨምሯል!",
        "enter_user_id": "📝 የተጠቃሚውን ቴሌግራም መታወቂያ ያስገቡ:",
        "enter_ticket_number": "📝 ለመመደብ የቲኬት ቁጥር ያስገቡ:",
        "ticket_assigned": "✅ ቲኬት #{ticket} ለተጠቃሚ ተመድቧል!",
        "ticket_already_sold": "❌ ቲኬቱ ቀድሞውኑ ተሽጧል!",
        "user_info": "👤 የተጠቃሚ መረጃ\n\n🆔 መታወቂያ: {id}\n📝 ስም: {name}\n📱 ስልክ: {phone}\n📍 አድራሻ: {address}\n💰 ቀሪ: {balance} ብር\n🎫 ቲኬቶች: {tickets}\n💸 አጠቃላይ: {spent} ብር",
    }
}

# =====================================================
# LANGUAGE CACHE
# =====================================================
class LangCache:
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

def get_text(user_id: int, key: str, **kwargs) -> str:
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
            [KeyboardButton(text=get_text(uid, "verify")), KeyboardButton(text=get_text(uid, "users"))],
            [KeyboardButton(text=get_text(uid, "refund")), KeyboardButton(text=get_text(uid, "broadcast"))],
            [KeyboardButton(text=get_text(uid, "reports")), KeyboardButton(text=get_text(uid, "buy_for_user"))],
            [KeyboardButton(text=get_text(uid, "manual_ticket")), KeyboardButton(text=get_text(uid, "back_user"))],
        ],
        resize_keyboard=True
    )

# =====================================================
# STATES
# =====================================================
class RegState(StatesGroup):
    name = State()
    phone = State()
    address = State()

class BuyState(StatesGroup):
    block = State()
    payment = State()

class AdminState(StatesGroup):
    broadcast_msg = State()
    buy_user_id = State()
    buy_ticket_num = State()
    manual_ticket = State()
    add_user_id = State()

# =====================================================
# DATABASE HELPERS
# =====================================================

async def get_user(tid: int):
    return await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = $1", tid)

async def get_user_by_id(user_id: int):
    return await DatabaseHelper.fetch_one("SELECT * FROM users WHERE user_id = $1", user_id)

async def get_available_ticket():
    return await DatabaseHelper.fetch_one(
        "SELECT ticket_id, ticket_number FROM tickets WHERE status = 'available' LIMIT 1"
    )

async def get_ticket_by_number(num: int):
    return await DatabaseHelper.fetch_one(
        "SELECT ticket_id, ticket_number FROM tickets WHERE ticket_number = $1 AND status = 'available'",
        num
    )

async def get_tickets_in_block(start: int, end: int):
    return await DatabaseHelper.fetch(
        "SELECT ticket_id, ticket_number FROM tickets WHERE ticket_number BETWEEN $1 AND $2 AND status = 'available'",
        start, end
    )

async def lock_ticket(ticket_id: int, user_id: int, telegram_id: int, phone: str, name: str):
    return await DatabaseHelper.execute(
        "UPDATE tickets SET status = 'pending', user_id = $1, telegram_id = $2, phone_number = $3, full_name = $4 WHERE ticket_id = $5 AND status = 'available'",
        user_id, telegram_id, phone, name, ticket_id
    )

async def assign_ticket(ticket_id: int, user_id: int, telegram_id: int, phone: str, name: str):
    return await DatabaseHelper.execute(
        "UPDATE tickets SET status = 'sold', user_id = $1, telegram_id = $2, phone_number = $3, full_name = $4, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = $5 AND status = 'pending'",
        user_id, telegram_id, phone, name, ticket_id
    )

async def get_user_tickets(telegram_id: int):
    return await DatabaseHelper.fetch(
        "SELECT ticket_number, assigned_at, status FROM tickets WHERE telegram_id = $1 ORDER BY ticket_number",
        telegram_id
    )

async def get_all_users():
    return await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, full_name, phone_number, address, balance, total_spent, created_at FROM users ORDER BY created_at DESC"
    )

async def get_pending_payments():
    return await DatabaseHelper.fetch(
        "SELECT p.payment_id, p.telegram_id, p.ticket_number, p.full_name, p.phone_number, p.created_at, u.user_id FROM payments p LEFT JOIN users u ON p.telegram_id = u.telegram_id WHERE p.status = 'pending' ORDER BY p.created_at DESC"
    )

async def get_all_tickets_with_users():
    return await DatabaseHelper.fetch(
        "SELECT t.ticket_number, t.telegram_id, t.full_name, t.phone_number, t.assigned_at, t.status, u.balance FROM tickets t LEFT JOIN users u ON t.telegram_id = u.telegram_id WHERE t.status != 'available' ORDER BY t.assigned_at DESC"
    )

async def get_user_ticket_count(telegram_id: int):
    result = await DatabaseHelper.fetch_one(
        "SELECT COUNT(*) FROM tickets WHERE telegram_id = $1 AND status = 'sold'",
        telegram_id
    )
    return result[0] if result else 0

async def get_user_total_spent(telegram_id: int):
    result = await DatabaseHelper.fetch_one(
        "SELECT total_spent FROM users WHERE telegram_id = $1",
        telegram_id
    )
    return result[0] if result else 0

# =====================================================
# START COMMAND
# =====================================================

@router.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    
    user = await get_user(uid)
    
    if user:
        lang = user[8] if len(user) > 8 else "en"
        LangCache.set(uid, lang)
        await message.answer(
            f"{get_text(uid, 'welcome')}\n\n{get_text(uid, 'choose_interface')}",
            reply_markup=choice_menu(),
            parse_mode="Markdown"
        )
        return
    
    # New user - registration
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="reg_lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="reg_lang_am")],
    ])
    
    await message.answer(
        "🌍 **Welcome!**\n\nPlease choose your language to register:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# =====================================================
# REGISTRATION
# =====================================================

@router.callback_query(F.data.startswith("reg_lang_"))
async def reg_lang(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    lang = callback.data.split("_")[2]
    LangCache.set(uid, lang)
    await callback.message.delete()
    
    await callback.message.answer(
        get_text(uid, "reg_name"),
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RegState.name)
    await callback.answer()

@router.message(RegState.name, F.text)
async def reg_name(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(name=message.text)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text(uid, "reg_phone"), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer(get_text(uid, "reg_phone"), reply_markup=kb)
    await state.set_state(RegState.phone)

@router.message(RegState.phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(phone=message.contact.phone_number)
    await message.answer(get_text(uid, "reg_address"), reply_markup=ReplyKeyboardRemove())
    await state.set_state(RegState.address)

@router.message(RegState.address, F.text)
async def reg_address(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    name = data.get("name")
    phone = data.get("phone")
    address = message.text
    lang = LangCache.get(uid)
    
    await DatabaseHelper.execute(
        "INSERT INTO users (telegram_id, full_name, phone_number, address, language) VALUES ($1, $2, $3, $4, $5)",
        uid, name, phone, address, lang
    )
    await state.clear()
    await message.answer(
        f"✅ {get_text(uid, 'registered')}\n\n{get_text(uid, 'choose_interface')}",
        reply_markup=choice_menu(),
        parse_mode="Markdown"
    )

# =====================================================
# CHOICE MENU
# =====================================================

@router.message(F.text == "🤖 Use Telegram")
async def use_telegram(message: Message):
    uid = message.from_user.id
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    lang = user[8] if len(user) > 8 else "en"
    LangCache.set(uid, lang)
    await message.answer(get_text(uid, "menu"), reply_markup=user_menu(uid))

@router.message(F.text == "🌐 Open Web")
async def open_web(message: Message):
    uid = message.from_user.id
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    phone = user[3] or "N/A"
    balance = user[5] or 0
    name = user[2] or str(uid)
    tickets = await get_user_tickets(uid)
    spent = await get_user_total_spent(uid)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Open Web Interface", web_app=WebAppInfo(url=f"{WEBAPP_URL}?telegram_id={uid}"))]
    ])
    
    await message.answer(
        get_text(uid, "user_profile", 
            id=uid,
            name=name,
            phone=phone,
            address=user[4] or "N/A",
            balance=balance,
            tickets=len(tickets),
            spent=spent
        ),
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.message(F.text == "ℹ️ About")
async def about(message: Message):
    uid = message.from_user.id
    await message.answer(
        "🎰 **Siket Ekub**\n\n"
        "💰 Price: 3,000 ETB\n\n"
        "🏆 **10 PRIZES:**\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "3rd: Shop Space (4,000,000 ETB)\n"
        "4th: 1,000,000 ETB\n"
        "5th: 1,000,000 ETB\n"
        "6th: 1,000,000 ETB\n"
        "7th: 1,000,000 ETB\n"
        "8th: 500,000 ETB\n"
        "9th: 300,000 ETB\n"
        "10th: 200,000 ETB\n\n"
        f"📞 Support: {SUPPORT_CHANNEL_LINK}\n"
        f"🎟️ Tickets: {TICKET_CHANNEL_LINK}\n\n"
        "📌 Register > Pick Ticket > Pay > Win!",
        reply_markup=choice_menu(),
        parse_mode="Markdown"
    )

# =====================================================
# LANGUAGE TOGGLE
# =====================================================

@router.message(F.text.in_(["🌍 Language", "🌍 ቋንቋ"]))
async def lang_toggle(message: Message):
    uid = message.from_user.id
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="toggle_lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="toggle_lang_am")],
    ])
    await message.answer(get_text(uid, "choose_lang"), reply_markup=kb)

@router.callback_query(F.data.startswith("toggle_lang_"))
async def toggle_lang(callback: CallbackQuery):
    uid = callback.from_user.id
    lang = callback.data.split("_")[2]
    await DatabaseHelper.execute("UPDATE users SET language = $1 WHERE telegram_id = $2", lang, uid)
    LangCache.set(uid, lang)
    await callback.message.delete()
    await callback.message.answer(get_text(uid, "lang_changed"), reply_markup=user_menu(uid))
    await callback.answer()

# =====================================================
# BUY TICKET
# =====================================================

@router.message(F.text.in_(["🎯 Buy Ticket", "🎯 ቲኬት ግዛ"]))
async def buy_ticket(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    count = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM tickets WHERE status = 'available'")
    if not count or count[0] == 0:
        await message.answer(get_text(uid, "no_tickets"), reply_markup=user_menu(uid))
        return
    
    await message.answer(
        get_text(uid, "pick_ticket"),
        reply_markup=buy_menu(uid)
    )

# RANDOM TICKET
@router.message(F.text.in_(["🎲 Random Ticket", "🎲 በዘፈቀደ"]))
async def random_ticket(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    ticket = await get_available_ticket()
    if not ticket:
        await message.answer(get_text(uid, "no_tickets"), reply_markup=buy_menu(uid))
        return
    
    ticket_id, ticket_num = ticket
    await state.update_data(ticket_id=ticket_id, ticket_num=ticket_num)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=get_text(uid, "back"))]], resize_keyboard=True)
    await message.answer(f"🎫 Ticket #{ticket_num}\n\n{get_text(uid, 'pay')}", reply_markup=kb)
    await state.set_state(BuyState.payment)

# TYPE NUMBER
@router.message(F.text.in_(["✏️ Type Number", "✏️ ቁጥር ይጻፉ"]))
async def type_number(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=get_text(uid, "back"))]], resize_keyboard=True)
    await message.answer(get_text(uid, "enter_number"), reply_markup=kb)
    await state.set_state(BuyState.block)

# CHOOSE BLOCK - Creates the block selection menu
@router.message(F.text.in_(["📦 Choose Block (50 tickets)", "📦 ብሎክ ምረጥ (50 ቲኬቶች)"]))
async def choose_block(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    kb_rows = []
    row = []
    for i in range(1, 20001, 50):
        start = i
        end = min(i + 49, 20000)
        row.append(KeyboardButton(text=f"{start}-{end}"))
        if len(row) == 4:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([KeyboardButton(text=get_text(uid, "back"))])
    
    await message.answer(
        get_text(uid, "select_block"),
        reply_markup=ReplyKeyboardMarkup(keyboard=kb_rows, resize_keyboard=True)
    )
    await state.set_state(BuyState.block)

# PROCESS BLOCK SELECTION OR TICKET NUMBER
@router.message(BuyState.block, F.text)
async def process_block_selection(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    if message.text == get_text(uid, "back"):
        await message.answer(get_text(uid, "pick_ticket"), reply_markup=buy_menu(uid))
        await state.clear()
        return
    
    # Check if it's a block range (contains '-')
    if '-' in message.text:
        try:
            start, end = map(int, message.text.split('-'))
            
            if start < 1 or end > 20000 or start > end:
                await message.answer(get_text(uid, "invalid_number"))
                return
            
            tickets = await get_tickets_in_block(start, end)
            
            if not tickets:
                kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=get_text(uid, "back"))]], resize_keyboard=True)
                await message.answer("❌ No tickets available in this block.", reply_markup=kb)
                return
            
            kb_rows = []
            row = []
            for ticket_id, ticket_num in tickets[:50]:
                row.append(KeyboardButton(text=str(ticket_num)))
                if len(row) == 5:
                    kb_rows.append(row)
                    row = []
            if row:
                kb_rows.append(row)
            if len(tickets) > 50:
                kb_rows.append([KeyboardButton(text=f"📊 {len(tickets)-50} more tickets")])
            kb_rows.append([KeyboardButton(text=get_text(uid, "back"))])
            
            await message.answer(
                f"🎫 Available tickets in {start}-{end}:\n({len(tickets)} tickets)\n\nSelect a ticket number:",
                reply_markup=ReplyKeyboardMarkup(keyboard=kb_rows, resize_keyboard=True)
            )
            return
            
        except ValueError:
            await message.answer(get_text(uid, "invalid_number"))
            return
    
    # Single ticket number
    try:
        ticket_num = int(message.text.strip())
        if ticket_num < 1 or ticket_num > 20000:
            raise ValueError
    except:
        await message.answer(get_text(uid, "invalid_number"))
        return
    
    ticket = await get_ticket_by_number(ticket_num)
    if not ticket:
        await message.answer(get_text(uid, "ticket_not_found"))
        return
    
    await state.update_data(ticket_id=ticket[0], ticket_num=ticket_num)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=get_text(uid, "back"))]], resize_keyboard=True)
    await message.answer(f"🎫 Ticket #{ticket_num}\n\n{get_text(uid, 'pay')}", reply_markup=kb)
    await state.set_state(BuyState.payment)

# =====================================================
# PAYMENT PROCESSING
# =====================================================

@router.message(BuyState.payment, F.photo | F.text)
async def process_payment(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    if message.text == get_text(uid, "back"):
        await message.answer(get_text(uid, "pick_ticket"), reply_markup=buy_menu(uid))
        await state.clear()
        return
    
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    ticket_num = data.get("ticket_num")
    
    if not ticket_id:
        await message.answer("❌ No ticket selected.", reply_markup=user_menu(uid))
        await state.clear()
        return
    
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    user_id = user[0]
    phone = user[3] or "N/A"
    name = user[2] or "User"
    
    # LOCK TICKET
    locked = await lock_ticket(ticket_id, user_id, uid, phone, name)
    
    if "UPDATE 0" in str(locked):
        await message.answer("❌ Ticket just got taken! Please try another.", reply_markup=buy_menu(uid))
        await state.clear()
        return
    
    screenshot = ""
    if message.photo:
        photo = message.photo[-1]
        file = await telegram_bot.get_file(photo.file_id)
        downloaded = await telegram_bot.download_file(file.file_path)
        screenshot = base64.b64encode(downloaded.read()).decode('utf-8')
    
    result = await DatabaseHelper.execute(
        "INSERT INTO payments (user_id, telegram_id, phone_number, full_name, ticket_id, ticket_number, amount, status, screenshot_data) VALUES ($1, $2, $3, $4, $5, $6, 3000, 'pending', $7) RETURNING payment_id",
        user_id, uid, phone, name, ticket_id, ticket_num, screenshot
    )
    payment_id = result[0] if result else None
    
    await state.clear()
    await message.answer(get_text(uid, "pay_submitted"), reply_markup=user_menu(uid))
    
    # Notify admins
    for admin in ADMIN_IDS:
        try:
            msg = f"🔔 New Payment\n🎫 Ticket #{ticket_num}\n👤 {name}\n📱 {phone}\n🆔 {payment_id}"
            if screenshot:
                img = base64.b64decode(screenshot)
                await telegram_bot.send_photo(admin, BufferedInputFile(img, filename="pay.jpg"), caption=msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
                    [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")]
                ]))
            else:
                await telegram_bot.send_message(admin, msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
                    [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")]
                ]))
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")

# =====================================================
# APPROVE/REJECT PAYMENTS
# =====================================================

@router.callback_query(F.data.startswith("approve_"))
async def approve_pay(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[1])
    payment = await DatabaseHelper.fetch_one(
        "SELECT telegram_id, ticket_id, ticket_number, full_name, phone_number FROM payments WHERE payment_id = $1 AND status = 'pending'",
        payment_id
    )
    if not payment:
        await callback.answer("❌ Payment not found!", show_alert=True)
        return
    
    tg_id, ticket_id, ticket_num, name, phone = payment
    
    user = await get_user(tg_id)
    if not user:
        await callback.answer("❌ User not found!", show_alert=True)
        return
    
    user_id = user[0]
    
    # Assign ticket
    assigned = await assign_ticket(ticket_id, user_id, tg_id, phone, name)
    
    if "UPDATE 0" in str(assigned):
        await DatabaseHelper.execute("UPDATE payments SET status = 'rejected', admin_notes = 'Ticket no longer pending' WHERE payment_id = $1", payment_id)
        await callback.message.edit_text(f"❌ Ticket #{ticket_num} is no longer available!")
        await callback.answer()
        return
    
    # Update payment and user
    await DatabaseHelper.execute_transaction([
        ("UPDATE payments SET status = 'approved', verified_by = $1, verified_at = CURRENT_TIMESTAMP WHERE payment_id = $2", uid, payment_id),
        ("UPDATE users SET balance = COALESCE(balance, 0) + 3000, total_spent = COALESCE(total_spent, 0) + 3000 WHERE telegram_id = $1", tg_id)
    ])
    
    # Notify channel
    try:
        await telegram_bot.send_message(
            TICKET_CHANNEL_ID,
            f"✅ Ticket #{ticket_num}\n👤 {name}\n📱 {phone}\n💰 3,000 ETB\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
    except:
        pass
    
    # Notify user
    try:
        await telegram_bot.send_message(tg_id, get_text(tg_id, "pay_approved", ticket=ticket_num))
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
        "SELECT telegram_id, ticket_id, ticket_number FROM payments WHERE payment_id = $1 AND status = 'pending'",
        payment_id
    )
    if payment:
        await DatabaseHelper.execute("UPDATE tickets SET status = 'available', user_id = NULL, telegram_id = NULL, phone_number = NULL, full_name = NULL WHERE ticket_id = $1", payment[1])
        await DatabaseHelper.execute("UPDATE payments SET status = 'rejected', verified_by = $1, verified_at = CURRENT_TIMESTAMP WHERE payment_id = $2", uid, payment_id)
        try:
            await telegram_bot.send_message(payment[0], get_text(payment[0], "pay_rejected"))
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
    user = await get_user(uid)
    if user:
        lang = user[8] if len(user) > 8 else "en"
        LangCache.set(uid, lang)
    await message.answer(get_text(uid, "menu"), reply_markup=user_menu(uid))

@router.message(F.text == "🔙 Back to User")
async def back_to_user(message: Message):
    uid = message.from_user.id
    user = await get_user(uid)
    if user:
        lang = user[8] if len(user) > 8 else "en"
        LangCache.set(uid, lang)
    await message.answer(get_text(uid, "menu"), reply_markup=user_menu(uid))

# =====================================================
# USER COMMANDS
# =====================================================

@router.message(F.text.in_(["🎫 My Tickets", "🎫 ቲኬቶቼ"]))
async def my_tickets_cmd(message: Message):
    uid = message.from_user.id
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    tickets = await get_user_tickets(uid)
    if not tickets:
        await message.answer(get_text(uid, "no_tickets_owned"), reply_markup=user_menu(uid))
        return
    
    total = len(tickets)
    sold = sum(1 for t in tickets if t[2] == 'sold')
    pending = sum(1 for t in tickets if t[2] == 'pending')
    
    text = get_text(uid, "your_tickets", count=total)
    text += f"📊 Sold: {sold}, Pending: {pending}\n\n"
    
    for ticket in tickets[:20]:
        num, date, status = ticket
        status_icon = "✅" if status == "sold" else "⏳"
        text += f"{status_icon} #{num} - {date[:10] if date else 'N/A'}\n"
    
    if len(tickets) > 20:
        text += f"\n... and {len(tickets)-20} more"
    
    await message.answer(text, reply_markup=user_menu(uid))

@router.message(F.text.in_(["💰 Balance", "💰 ቀሪ"]))
async def balance_cmd(message: Message):
    uid = message.from_user.id
    user = await get_user(uid)
    if not user:
        await message.answer(get_text(uid, "registration_required"))
        return
    
    balance = user[5] or 0
    spent = user[6] or 0
    tickets = await get_user_ticket_count(uid)
    pending = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM payments WHERE telegram_id = $1 AND status = 'pending'", uid)
    pending_count = pending[0] if pending else 0
    
    text = get_text(uid, "balance_info", balance=balance, tickets=tickets, spent=spent)
    if pending_count > 0:
        text += f"\n\n⏳ {get_text(uid, 'pending_payments', count=pending_count)}"
    
    await message.answer(text, reply_markup=user_menu(uid))

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
    await message.answer(get_text(uid, "support_info", channel=SUPPORT_CHANNEL_LINK), reply_markup=kb)

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
    await message.answer(get_text(uid, "admin_panel"), reply_markup=admin_menu(uid))

# VERIFY PAYMENTS
@router.message(F.text.in_(["✅ Verify Payments", "✅ ክፍያዎችን አረጋግጥ"]))
async def admin_verify(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    payments = await get_pending_payments()
    if not payments:
        await message.answer("📭 No pending payments.", reply_markup=admin_menu(uid))
        return
    
    text = f"⏳ Pending Payments ({len(payments)}):\n\n"
    for p in payments[:10]:
        text += f"🆔 {p[0]} | #{p[2]} | {p[3]} | {p[4]}\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in payments[:10]:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"View #{p[0]}", callback_data=f"view_pay_{p[0]}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")])
    
    await message.answer(text, reply_markup=kb)

@router.callback_query(F.data.startswith("view_pay_"))
async def view_payment(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[2])
    payment = await DatabaseHelper.fetch_one(
        "SELECT payment_id, telegram_id, ticket_number, full_name, phone_number, screenshot_data, created_at FROM payments WHERE payment_id = $1",
        payment_id
    )
    if not payment:
        await callback.answer("❌ Not found!", show_alert=True)
        return
    
    _, tg_id, ticket_num, name, phone, screenshot, created = payment
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{payment_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{payment_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
    ])
    
    msg = f"🔍 Payment #{payment_id}\n🎫 Ticket: #{ticket_num}\n👤 {name}\n📱 {phone}\n📅 {created}"
    
    if screenshot:
        try:
            img = base64.b64decode(screenshot)
            await callback.message.answer_photo(BufferedInputFile(img, filename="payment.jpg"), caption=msg, reply_markup=kb)
            await callback.message.delete()
        except:
            await callback.message.edit_text(msg + "\n\n📸 Screenshot attached", reply_markup=kb)
    else:
        await callback.message.edit_text(msg, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    uid = callback.from_user.id
    await callback.message.delete()
    await callback.message.answer(get_text(uid, "admin_panel"), reply_markup=admin_menu(uid))
    await callback.answer()

# USERS
@router.message(F.text.in_(["👤 Users", "👤 ተጠቃሚዎች"]))
async def admin_users(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    users = await get_all_users()
    if not users:
        await message.answer(get_text(uid, "no_users"), reply_markup=admin_menu(uid))
        return
    
    text = "👤 **All Users:**\n\n"
    for u in users[:20]:
        user_id, tg_id, name, phone, address, balance, spent, created = u
        text += f"🆔 {tg_id}\n👤 {name or 'N/A'}\n📱 {phone or 'N/A'}\n💰 {balance or 0} ETB\n💸 {spent or 0} ETB\n📅 {created[:10]}\n\n"
    
    if len(users) > 20:
        text += f"... and {len(users)-20} more"
    
    await message.answer(text, reply_markup=admin_menu(uid), parse_mode="Markdown")

# REFUND
@router.message(F.text.in_(["🔄 Refund", "🔄 መመለስ"]))
async def admin_refund(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, full_name, balance FROM users WHERE balance > 0 ORDER BY balance DESC"
    )
    if not users:
        await message.answer(get_text(uid, "no_refund"), reply_markup=admin_menu(uid))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for u in users[:10]:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"{u[2] or u[1]} - {u[3]:,.0f} ETB", callback_data=f"refund_user_{u[0]}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔄 Process All", callback_data="refund_all")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")])
    
    await message.answer("🔄 Select user to refund:", reply_markup=kb)

@router.callback_query(F.data.startswith("refund_user_"))
async def refund_user(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    user = await DatabaseHelper.fetch_one("SELECT telegram_id, full_name, balance FROM users WHERE user_id = $1", user_id)
    if not user or user[2] <= 0:
        await callback.answer("❌ No balance!", show_alert=True)
        return
    
    tg_id, name, balance = user
    
    await DatabaseHelper.execute_transaction([
        ("INSERT INTO refunds (user_id, telegram_id, refund_amount, refund_reason, status, processed_by, processed_at) VALUES ($1, $2, $3, 'Admin refund', 'completed', $4, CURRENT_TIMESTAMP)", user_id, tg_id, balance, uid),
        ("UPDATE users SET balance = 0 WHERE user_id = $1", user_id)
    ])
    
    try:
        await telegram_bot.send_message(tg_id, get_text(tg_id, "refund_complete", amount=balance))
    except:
        pass
    
    await callback.message.edit_text(f"✅ Refunded {balance:,.0f} ETB to {name}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
    ]))
    await callback.answer()

@router.callback_query(F.data == "refund_all")
async def refund_all(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    users = await DatabaseHelper.fetch("SELECT user_id, telegram_id, balance FROM users WHERE balance > 0")
    if not users:
        await callback.answer("No users with balance!", show_alert=True)
        return
    
    total = 0
    for user_id, tg_id, balance in users:
        await DatabaseHelper.execute_transaction([
            ("INSERT INTO refunds (user_id, telegram_id, refund_amount, refund_reason, status, processed_by, processed_at) VALUES ($1, $2, $3, 'Bulk refund', 'completed', $4, CURRENT_TIMESTAMP)", user_id, tg_id, balance, uid),
            ("UPDATE users SET balance = 0 WHERE user_id = $1", user_id)
        ])
        total += balance
        try:
            await telegram_bot.send_message(tg_id, get_text(tg_id, "refund_complete", amount=balance))
        except:
            pass
        await asyncio.sleep(0.05)
    
    await callback.message.edit_text(get_text(uid, "refund_all", total=total, count=len(users)), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]
    ]))
    await callback.answer()

# BROADCAST
@router.message(F.text.in_(["📢 Broadcast", "📢 ማስታወቂያ"]))
async def admin_broadcast(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer("📢 Enter message to broadcast:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Back to User")]], resize_keyboard=True
    ))
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
    
    msg = message.text
    sent = 0
    for user in users:
        try:
            await telegram_bot.send_message(user[0], f"📢 {msg}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await state.clear()
    await message.answer(get_text(uid, "broadcast_sent", sent=sent, total=len(users)), reply_markup=admin_menu(uid))

# REPORTS
@router.message(F.text.in_(["📊 Reports", "📊 ሪፖርቶች"]))
async def admin_reports(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    total = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM tickets")
    available = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM tickets WHERE status = 'available'")
    pending_tickets = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM tickets WHERE status = 'pending'")
    sold = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM tickets WHERE status = 'sold'")
    total_users = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM users")
    total_revenue = await DatabaseHelper.fetch_one("SELECT COALESCE(SUM(total_spent), 0) FROM users")
    pending = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
    approved = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM payments WHERE status = 'approved'")
    rejected = await DatabaseHelper.fetch_one("SELECT COUNT(*) FROM payments WHERE status = 'rejected'")
    
    text = (
        f"📊 **System Reports**\n\n"
        f"👤 Users: {total_users[0] or 0}\n"
        f"📊 Total Tickets: {total[0] or 0}\n"
        f"🎫 Available: {available[0] or 0}\n"
        f"⏳ Pending: {pending_tickets[0] or 0}\n"
        f"💰 Sold: {sold[0] or 0}\n"
        f"💵 Revenue: {total_revenue[0] or 0:,.0f} ETB\n\n"
        f"📋 Payments:\n"
        f"⏳ Pending: {pending[0] or 0}\n"
        f"✅ Approved: {approved[0] or 0}\n"
        f"❌ Rejected: {rejected[0] or 0}"
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
    
    tickets = await get_all_tickets_with_users()
    
    csv = "Ticket,User ID,Name,Phone,Date,Status,Balance\n"
    for t in tickets:
        num, tg_id, name, phone, date, status, balance = t
        csv += f"{num},{tg_id or 'N/A'},{name or 'N/A'},{phone or 'N/A'},{date or 'N/A'},{status},{balance or 0}\n"
    
    file = io.BytesIO(csv.encode('utf-8'))
    await callback.message.answer_document(BufferedInputFile(file.getvalue(), filename="tickets_report.csv"), caption="📊 Tickets Report")
    await callback.answer()

# BUY FOR USER - Allows buying for unregistered users too
@router.message(F.text.in_(["🎯 Buy for User", "🎯 ለሌላ ግዛ"]))
async def admin_buy_user(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer(get_text(uid, "enter_user_id"), reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Back to User")]], resize_keyboard=True
    ))
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
    
    # Check if user exists, if not create them
    user = await get_user(target_id)
    if not user:
        # Register user with default values
        await DatabaseHelper.execute(
            "INSERT INTO users (telegram_id, full_name, phone_number, address, language) VALUES ($1, 'User', 'N/A', 'N/A', 'en')",
            target_id
        )
        user = await get_user(target_id)
        await message.answer(f"✅ User {target_id} created automatically!")
    
    await state.update_data(target_user=target_id)
    await message.answer(get_text(uid, "enter_ticket_number"))
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
        ticket = await DatabaseHelper.fetch_one("SELECT ticket_id, ticket_number FROM tickets WHERE status = 'available' LIMIT 1")
    else:
        try:
            num = int(ticket_input)
            ticket = await DatabaseHelper.fetch_one("SELECT ticket_id, ticket_number FROM tickets WHERE ticket_number = $1 AND status = 'available'", num)
        except:
            await message.answer("❌ Invalid number.")
            return
    
    if not ticket:
        await message.answer("❌ No available ticket.")
        return
    
    ticket_id, ticket_num = ticket
    user = await get_user(target_id)
    if not user:
        await message.answer(get_text(uid, "user_not_found"))
        return
    
    user_id = user[0]
    phone = user[3] or "N/A"
    name = user[2] or "User"
    
    await DatabaseHelper.execute("UPDATE tickets SET status = 'sold', user_id = $1, telegram_id = $2, phone_number = $3, full_name = $4, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = $5", user_id, target_id, phone, name, ticket_id)
    await DatabaseHelper.execute("INSERT INTO payments (user_id, telegram_id, phone_number, full_name, ticket_id, ticket_number, amount, status, admin_notes) VALUES ($1, $2, $3, $4, $5, $6, 3000, 'approved', $7)", user_id, target_id, phone, name, ticket_id, ticket_num, "Admin purchase")
    await DatabaseHelper.execute("UPDATE users SET total_spent = COALESCE(total_spent, 0) + 3000 WHERE telegram_id = $1", target_id)
    
    await state.clear()
    await message.answer(f"✅ Ticket #{ticket_num} assigned to user {target_id}!\n👤 {name}\n📱 {phone}", reply_markup=admin_menu(uid))
    
    try:
        await telegram_bot.send_message(target_id, f"🎉 Admin purchased ticket #{ticket_num} for you!")
    except:
        pass

# MANUAL TICKET
@router.message(F.text.in_(["📝 Manual Ticket", "📝 በእጅ አስገባ"]))
async def admin_manual(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await message.answer("📝 Enter ticket number to mark as sold:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Back to User")]], resize_keyboard=True
    ))
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
    
    result = await DatabaseHelper.execute("UPDATE tickets SET status = 'sold', assigned_at = CURRENT_TIMESTAMP WHERE ticket_number = $1 AND status = 'available'", num)
    
    if "UPDATE 1" in str(result):
        await message.answer(f"✅ Ticket #{num} marked as sold!", reply_markup=admin_menu(uid))
    else:
        await message.answer(f"❌ Ticket #{num} not available.", reply_markup=admin_menu(uid))
    
    await state.clear()

# =====================================================
# MAIN
# =====================================================

async def set_commands():
    await telegram_bot.set_my_commands([
        BotCommand(command="start", description="🏠 Start"),
        BotCommand(command="admin", description="🛠️ Admin"),
    ])

async def main():
    await init_db_postgres()
    await generate_tickets()
    await set_commands()
    
    try:
        await telegram_bot.delete_webhook(drop_pending_updates=True)
    except:
        pass
    
    await asyncio.sleep(1)
    dp.include_router(router)
    
    logger.info("🚀 Bot started with PostgreSQL!")
    logger.info(f"👤 Admins: {ADMIN_IDS}")
    logger.info(f"🌐 WebApp: {WEBAPP_URL}")
    
    await dp.start_polling(telegram_bot, allowed_updates=["message", "callback_query"], skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Stopped")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
