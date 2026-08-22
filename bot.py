# =====================================================
# BOT.PY - SIKET EKUB LOTTERY BOT
# Complete Production Bot - NO OCR (Manual Verification Only)
# Fixed for Render Deployment
# =====================================================

import sys
import os
import logging
import asyncio
import threading
import random
import re
import io
import ssl
import signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Lock
from logging.handlers import RotatingFileHandler

# =====================================================
# FIX: Prevent signal handler errors
# =====================================================

_original_add_signal_handler = None

def patch_signal_handlers():
    """Patch signal handlers to work in background threads"""
    global _original_add_signal_handler
    
    try:
        loop = asyncio.get_running_loop()
        
        if _original_add_signal_handler is None:
            _original_add_signal_handler = loop.add_signal_handler
        
        def patched_add_signal_handler(sig, callback, *args, **kwargs):
            try:
                return _original_add_signal_handler(sig, callback, *args, **kwargs)
            except (RuntimeError, ValueError) as e:
                if "set_wakeup_fd only works in main thread" in str(e):
                    print(f"⚠️ Ignoring signal handler for signal {sig} (background thread)")
                    return None
                raise
        
        loop.add_signal_handler = patched_add_signal_handler
    except RuntimeError:
        # No running loop yet
        pass

# =====================================================
# NO OCR - REMOVED: cv2, numpy, easyocr
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
from database import init_db, backup_database, DB_NAME, process_refund

# =====================================================
# FIX: Windows Encoding
# =====================================================
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# =====================================================
# LOGGING
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# =====================================================
# SSL & ENV
# =====================================================
ssl._create_default_https_context = ssl._create_unverified_context
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# =====================================================
# ENVIRONMENT VARIABLES
# =====================================================
TOKEN = os.getenv("BOT_TOKEN")
admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in admin_ids_raw.split(",") if admin_id.strip()]

if not TOKEN:
    raise ValueError("BOT_TOKEN is missing!")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS cannot be empty!")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://siket-ekub-webapp.onrender.com")

SUPPORT_CHANNEL_LINK = os.getenv("SUPPORT_CHANNEL_LINK", "https://t.me/siketekub")
SUPPORT_CHANNEL_ID = os.getenv("SUPPORT_CHANNEL_ID", "@siketekub")
SUPPORT_CHANNEL_NAME = "Siket Ekub Support"
TICKET_CHANNEL_LINK = os.getenv("TICKET_CHANNEL_LINK", "https://t.me/siketekubtiketo")
TICKET_CHANNEL_ID = os.getenv("TICKET_CHANNEL_ID", "@siketekubtiketo")
TICKET_CHANNEL_NAME = "Siket Ekub Tickets"

# =====================================================
# THREAD POOLS
# =====================================================
class ThreadPools:
    CPU = ThreadPoolExecutor(max_workers=4)
    IO = ThreadPoolExecutor(max_workers=8)
    OCR = ThreadPoolExecutor(max_workers=2)  # Kept for compatibility
    
    @classmethod
    def shutdown_all(cls):
        cls.CPU.shutdown(wait=False)
        cls.IO.shutdown(wait=False)
        cls.OCR.shutdown(wait=False)

# =====================================================
# SHARED STATE
# =====================================================
class SharedState:
    def __init__(self):
        self._lock = Lock()
        self._user_languages = {}
        self._task_queue = Queue()
        self._processed_tasks = 0
    
    def get_language(self, user_id: int) -> str:
        with self._lock:
            return self._user_languages.get(user_id, "en")
    
    def set_language(self, user_id: int, lang: str):
        with self._lock:
            self._user_languages[user_id] = lang
    
    def add_task(self, task):
        self._task_queue.put(task)
    
    def get_task(self):
        return self._task_queue.get() if not self._task_queue.empty() else None
    
    def increment_tasks(self):
        with self._lock:
            self._processed_tasks += 1
    
    def get_stats(self):
        with self._lock:
            return {
                'queue_size': self._task_queue.qsize(),
                'processed': self._processed_tasks
            }

shared_state = SharedState()
DB_LOCK = Lock()

# =====================================================
# SETUP LOGGING
# =====================================================
def setup_logging():
    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        "logs/bot.log",
        maxBytes=10*1024*1024,
        backupCount=5
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
    return logging.getLogger(__name__)

logger = setup_logging()

# =====================================================
# DATABASE HELPER
# =====================================================
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
                except Exception as e:
                    await db.rollback()
                    raise e
    
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

# =====================================================
# BOT INITIALIZATION
# =====================================================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
router = Router()

# =====================================================
# EASYOCR INITIALIZATION (DISABLED)
# =====================================================
reader = None
logger.info("ℹ️ OCR disabled - manual payment verification only")

# =====================================================
# BOT COMMANDS
# =====================================================
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🏠 ቦት ጀምር / Start Bot"),
        BotCommand(command="admin", description="🛠️ የአስተዳዳሪ ፓነል / Admin Panel"),
        BotCommand(command="menu", description="📋 ዋና ምናሌ / Main Menu"),
        BotCommand(command="balance", description="💰 ቀሪ ሂሳብ / Balance"),
        BotCommand(command="mytickets", description="🎟️ ቲኬቶቼ / My Tickets"),
        BotCommand(command="prizes", description="🏆 ሽልማቶች / Prizes"),
        BotCommand(command="support", description="💬 ድጋፍ / Support"),
    ]
    await bot.set_my_commands(commands)
    logger.info("✅ Left side menu commands set")

# =====================================================
# COMMAND HANDLERS
# =====================================================
@router.message(Command("menu"))
async def cmd_menu(message: Message):
    uid = message.from_user.id
    await message.answer(
        Localization.get_text(uid, "main_menu"),
        reply_markup=KeyboardBuilder.main_menu(uid)
    )

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    await show_balance(message)

@router.message(Command("mytickets"))
async def cmd_mytickets(message: Message):
    await my_tickets_button(message)

@router.message(Command("prizes"))
async def cmd_prizes(message: Message):
    await view_prizes_button(message)

@router.message(Command("support"))
async def cmd_support(message: Message):
    await support_channels_menu(message)

# =====================================================
# BACKGROUND WORKERS
# =====================================================
async def background_worker():
    while True:
        try:
            task = shared_state.get_task()
            if task:
                task_type = task.get('type')
                if task_type == 'backup':
                    await backup_database()
                elif task_type == 'expire_payments':
                    await expire_pending_payments()
                shared_state.increment_tasks()
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Background worker error: {e}")
            await asyncio.sleep(5)

async def expire_pending_payments():
    while True:
        try:
            await asyncio.sleep(3600)
            await DatabaseHelper.execute("""
                UPDATE payments 
                SET status = 'rejected', 
                    admin_notes = 'ከ24 ሰዓት በኋላ እራስ-ሰር ተሰርዟል'
                WHERE status = 'pending' 
                AND created_at < datetime('now', '-24 hours')
            """)
            logger.info("✅ Checked for expired payments")
        except Exception as e:
            logger.error(f"Payment expiry failed: {e}")
            await asyncio.sleep(60)

async def start_background_tasks():
    asyncio.create_task(background_worker())
    asyncio.create_task(expire_pending_payments())
    logger.info("✅ Background tasks started")

# =====================================================
# POST TICKET TO CHANNEL
# =====================================================
async def post_ticket_to_channel(user_id: int, ticket_code: str, phone_number: str, amount: float, payment_ref: str = None):
    try:
        user = await DatabaseHelper.fetch_one(
            "SELECT full_name, address, balance, total_spent FROM users WHERE telegram_id = ?",
            (user_id,)
        )
        full_name = user[0] if user else "Unknown"
        address = user[1] if user else "N/A"
        balance = user[2] if user else 0.0
        total_spent = user[3] if user else 0.0
        
        ticket_count = await DatabaseHelper.fetch_one(
            "SELECT COUNT(*) FROM tickets WHERE telegram_id = ? AND status = 'sold'",
            (user_id,)
        )
        ticket_count = ticket_count[0] if ticket_count else 0
        
        masked_phone = f"{phone_number[:4]}***{phone_number[-2:]}" if phone_number and len(phone_number) > 6 else "Hidden"
        
        message = (
            f"🎯 NEW TICKET PURCHASED!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Customer Profile:\n"
            f"   Name: {full_name}\n"
            f"   Phone: {masked_phone}\n"
            f"   Address: {address}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎟️ Ticket Details:\n"
            f"   Ticket Number: #{ticket_code}\n"
            f"   Amount Paid: {amount:,.2f} ETB\n"
            f"   Reference: {payment_ref or 'N/A'}\n"
            f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 User Statistics:\n"
            f"   Total Tickets: {ticket_count}\n"
            f"   Total Spent: {total_spent:,.2f} ETB\n"
            f"   Balance: {balance:,.2f} ETB\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ This ticket has been VERIFIED and CONFIRMED."
        )
        
        await bot.send_message(TICKET_CHANNEL_ID, message)
        logger.info(f"✅ Posted ticket #{ticket_code} for user {full_name} to {TICKET_CHANNEL_NAME}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to post ticket to channel: {e}")
        return False

# =====================================================
# OCR FUNCTIONS (DISABLED - Manual Verification Only)
# =====================================================

def parse_etb_receipt(img):
    """OCR is disabled - manual verification only"""
    return {"reference": None, "amount": 0.0, "date": None, "raw_text": "", "account": None}

def parse_payment_sms(text: str) -> dict:
    """Parse payment SMS text"""
    result = {"reference": None, "amount": 0.0, "date": None, "raw_text": text}
    if not text:
        return result
    
    # Amount patterns
    amount_patterns = [
        r'(?:ETB|Birr|ብር)\s*([\d,]+\.?\d*)',
        r'([\d,]+\.?\d*)\s*(?:ETB|Birr|ብር)',
        r'(?:Amount|Total)\s*[:;]?\s*(?:ETB|Birr)?\s*([\d,]+\.?\d*)',
        r'([\d,]+\.\d{2})',
        r'([\d,]+\.\d{1,2})'
    ]
    
    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                num_str = match.group(1).replace(",", "").replace(" ", "")
                val = float(num_str)
                if 100 <= val <= 1000000:
                    result["amount"] = val
                    break
            except:
                continue
    
    # Reference patterns
    ref_patterns = [
        r'Transaction\s*Reference\s*[:.]?\s*([A-Z0-9]+)',
        r'Reference\s*[:.]?\s*([A-Z0-9]+)',
        r'Ref\s*[:.]?\s*([A-Z0-9]+)',
        r'FT[A-Z0-9]{8,12}',
        r'DGO[A-Z0-9]{8,12}',
        r'\b([A-Z]{2}[0-9A-Z]{8,12})\b',
        r'\b([A-Z0-9]{10,15})\b',
        r'(?:Ref|Txn|ID)[:,\s]*([A-Z0-9]{8,15})'
    ]
    
    for pattern in ref_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["reference"] = match.group(1) if match.groups() else match.group(0)
            if result["reference"]:
                result["reference"] = result["reference"].strip()
            break
    
    # Date patterns
    date_patterns = [
        r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
        r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})',
        r'(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})',
        r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b'
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            result["date"] = match.group(1)
            break
    
    return result

# =====================================================
# LOCALIZATION
# =====================================================
class Localization:
    EN = {
        "lang_prompt": "🌍 Please choose your language:",
        "welcome": "🎰 SIKET EKUB LOTTERY\n\nWelcome to Siket Ekub Lottery!",
        "share_phone": "📱 Share Phone Number",
        "address_prompt": "📍 Please enter your physical address:",
        "reg_success": "✅ Registration successful! You can now buy tickets.",
        "main_menu": "📋 Main Menu - Select an option:",
        "buy_ticket": "🎯 Buy Ticket (3,000 ETB)",
        "my_tickets": "📊 My Tickets",
        "view_prizes": "🏆 View Prizes",
        "support": "💬 Support & Channels",
        "lang_toggle": "አማርኛ / EN",
        "balance": "💰 Balance",
        "support_channel": "📞 Support Channel",
        "ticket_channel": "🎟️ View Tickets Channel",
        "channels_description": "📌 Your verified tickets are automatically posted to the ticket channel.",
        "support_channels": "💬 Support & Channels",
        "support_team": "👨‍💻 Support Team",
        "verified_tickets": "✅ Verified Tickets Posted Here",
        "prize_header": "🏆 10 GRAND PRIZES:",
        "prize_list": "1st: BWD Leopard 3 (8,000,000 ETB)\n2nd: Hyundai Bayon (5,000,000 ETB)\n3rd: Shop Space (4,000,000 ETB)\n4th: 1,000,000 ETB Cash\n5th: 1,000,000 ETB Cash\n6th: 1,000,000 ETB Cash\n7th: 1,000,000 ETB Cash\n8th: 500,000 ETB Cash\n9th: 300,000 ETB Cash\n10th: 200,000 ETB Cash",
        "how_to_play": "📌 Register > Pick Ticket > Pay 3,000 ETB > Win!",
        "good_luck": "🚀 GOOD LUCK!",
        "select_game": "Select Lottery Draw:",
        "quick_random": "⚡ Random Pick",
        "type_ticket_number": "⌨️ Type Ticket Number",
        "back": "← Go Back",
        "cancel": "✖ Cancel",
        "Available": "Available",
        "Sold": "SOLD",
        "Pending": "Pending",
        "Status": "Status",
        "No active tickets found": "No tickets found.",
        "Price": "Price",
        "Game": "Game",
        "Per Slot": "Per Ticket",
        "Range": "Range",
        "blocks": "Blocks",
        "Select Ticket": "Select Your Ticket",
        "Selected Slot": "Selected Ticket",
        "Transfer payment to accounts": "📤 Transfer 3,000 ETB to:",
        "Send screenshot or paste bank SMS text receipt below": "📸 Send screenshot or SMS receipt:",
        "Payment submitted successfully": "✅ Payment submitted! Waiting for verification.",
        "Payment Approved": "✅ Payment Approved",
        "admin_panel": "🛠️ Admin Panel",
        "Create Game": "Create Game",
        "Verify Payments": "Verify Payments",
        "Edit Prizes": "Edit Prizes",
        "Broadcast Notification": "Broadcast",
        "Excel Reports": "Excel Reports",
        "Buy Ticket for User": "🎯 Buy Ticket for User",
        "Manual Ticket Input": "📝 Manual Ticket Input",
        "User Management": "👤 User Management",
        "Refund Management": "🔄 Refund Management",
        "Add User": "➕ Add User",
        "Delete User": "➖ Delete User",
        "List Users": "📋 List All Users",
        "User Added Successfully": "✅ User Added Successfully!",
        "User Deleted Successfully": "✅ User Deleted Successfully!",
        "User not found": "❌ User not found!",
        "User already exists": "⚠️ User already exists!",
        "Confirm delete user": "⚠️ Confirm deleting this user?",
        "Delete warning": "⚠️ This action cannot be undone!",
        "Enter Telegram ID": "📝 Enter Telegram ID:",
        "Enter Phone Number": "📝 Enter Phone Number:",
        "Enter Address": "📍 Enter Address:",
        "Invalid Phone": "❌ Invalid phone number! Please use 09XXXXXXXX format.",
        "User Info": "👤 User Info",
        "User ID": "🆔 User ID",
        "Phone": "📱 Phone",
        "Address": "📍 Address",
        "Balance": "💰 Balance",
        "Tickets": "🎫 Tickets",
        "Total Spent": "💸 Total Spent",
        "Registration Date": "📅 Registration Date",
        "Language": "🌍 Language",
        "Status": "📊 Status",
        "Active": "Active",
        "Blocked": "Blocked",
        "No users found": "📭 No users found.",
        "Are you sure": "⚠️ Are you sure?",
        "Process Refund": "🔄 Process Refund",
        "User has no positive balance": "❌ User has no positive balance.",
        "Refund processed successfully": "✅ Refund processed successfully!",
        "Refund failed": "❌ Refund failed!",
        "Refund Request": "🔄 Refund Request",
        "Example": "Example",
        "Or type": "Or type",
        "for a random available ticket": "for a random available ticket",
        "No available tickets found": "No available tickets found",
        "Ticket": "Ticket",
        "is not available": "is not available",
        "Ticket Assigned Successfully": "Ticket Assigned Successfully",
        "User": "User",
        "Telegram": "Telegram",
        "Amount": "Amount",
        "Payment": "Payment",
        "The user has been notified": "The user has been notified",
        "Ticket Purchased For You": "Ticket Purchased For You",
        "An admin has purchased ticket": "An admin has purchased ticket",
        "on your behalf": "on your behalf",
        "Use": "Use",
        "to see your tickets": "to see your tickets",
        "Manual Ticket Input": "Manual Ticket Input",
        "Enter the ticket number to manually mark as sold": "Enter the ticket number to manually mark as sold",
        "This will mark the ticket as sold without payment verification": "This will mark the ticket as sold without payment verification",
        "Get help from our support team": "Get help from our support team",
        "View all verified tickets": "View all verified tickets",
        "You don't have any tickets yet": "You don't have any tickets yet",
        "Join a game to purchase your first ticket": "Join a game to purchase your first ticket",
        "Total Tickets": "Total Tickets",
        "Your Tickets": "Your Tickets",
        "Total": "Total",
        "to": "to",
        "refunds": "refunds",
        "Processed": "Processed",
        "Refund not found or already processed": "Refund not found or already processed",
        "User no longer has sufficient balance": "User no longer has sufficient balance",
        "Refund Approved": "Refund Approved",
        "Your refund has been processed": "Your refund has been processed",
        "Refund approved": "Refund approved",
        "Please register first": "Please register first",
        "You have no positive balance to refund": "You have no positive balance to refund",
        "You already have a pending refund request": "You already have a pending refund request",
        "Request Refund": "Request Refund",
        "Your Current Balance": "Your Current Balance",
        "This will request a refund of your entire positive balance": "This will request a refund of your entire positive balance",
        "Admin will review and process your request": "Admin will review and process your request",
        "Confirm refund request": "Confirm refund request",
        "No positive balance to refund": "No positive balance to refund",
        "Please enter the reason for refund": "Please enter the reason for refund",
        "Invalid request": "Invalid request",
        "Refund request submitted": "Refund request submitted",
        "New Refund Request": "New Refund Request",
        "to process": "to process",
        "Users with Positive Balance": "Users with Positive Balance",
        "Eligible for Refund": "Eligible for Refund",
        "Process All Positive Balances": "Process All Positive Balances",
        "No users with positive balance": "No users with positive balance",
        "Pending Refund Requests": "Pending Refund Requests",
        "No pending refund requests": "No pending refund requests",
        "Completed Refunds": "Completed Refunds",
        "Total Refunded": "Total Refunded",
        "Positive balance refunded by admin": "Positive balance refunded by admin",
        "Your balance has been cleared": "Your balance has been cleared",
        "Refunded": "Refunded",
        "Positive balance refunded": "Positive balance refunded",
        "Broadcast Notification": "Broadcast Notification",
        "Send a message/announcement to all registered bot users": "Send a message/announcement to all registered bot users",
        "No users found to broadcast": "No users found to broadcast",
        "Broadcasting to": "Broadcasting to",
        "users": "users",
        "Announcement": "Announcement",
        "Broadcast complete": "Broadcast complete",
        "Sent": "Sent",
        "Failed": "Failed",
        "Total users": "Total users",
        "Success": "Success",
        "Select an option": "Select an option",
        "Language changed to": "Language changed to",
    }
    AM = {
        "lang_prompt": "🌍 እባክዎ የሚፈልጉትን ቋንቋ ይምረጡ:",
        "welcome": "🎰 ሲኬት ዕቁብ ሎተሪ\n\nወደ ሲኬት ዕቁብ ሎተሪ እንኳን በደህና መጡ! እድልዎን ለመሞከር ዝግጁ ነዎት?",
        "share_phone": "📱 ስልክ ቁጥር አጋሩ",
        "address_prompt": "📍 እባክዎ አድራሻዎን ያስገቡ (ለምሳሌ: አዲስ አበባ ቦሌ):",
        "reg_success": "✅ ምዝገባዎ በተሳካ ሁኔታ ተጠናቅቋል! አሁን ቲኬት መግዛት ይችላሉ።",
        "main_menu": "📋 ዋና ምናሌ - እባክዎ አማራጭ ይምረጡ:",
        "buy_ticket": "🎯 ቲኬት ግዛ (3,000 ብር)",
        "my_tickets": "📊 የኔ ቲኬቶች",
        "view_prizes": "🏆 ሽልማቶችን ተመልከት",
        "support": "💬 ድጋፍ እና ሰርጦች",
        "lang_toggle": "EN / አማርኛ",
        "balance": "💰 ቀሪ ሂሳብ",
        "support_channel": "📞 የድጋፍ ሰርጥ",
        "ticket_channel": "🎟️ የቲኬት ሰርጥ",
        "channels_description": "📌 የተረጋገጡ ቲኬቶችዎ በራስ-ሰር ወደ ቲኬት ሰርጥ ይለጠፋሉ።",
        "support_channels": "💬 ድጋፍ እና ሰርጦች",
        "support_team": "👨‍💻 የድጋፍ ቡድን",
        "verified_tickets": "✅ የተረጋገጡ ቲኬቶች እዚህ ይታተማሉ",
        "prize_header": "🏆 10 ዋና ሽልማቶች:",
        "prize_list": "1ኛ: BWD Leopard 3 (8,000,000 ብር)\n2ኛ: Hyundai Bayon (5,000,000 ብር)\n3ኛ: የሱቅ ቦታ (4,000,000 ብር)\n4ኛ: 1,000,000 ብር ጥሬ ገንዘብ\n5ኛ: 1,000,000 ብር ጥሬ ገንዘብ\n6ኛ: 1,000,000 ብር ጥሬ ገንዘብ\n7ኛ: 1,000,000 ብር ጥሬ ገንዘብ\n8ኛ: 500,000 ብር ጥሬ ገንዘብ\n9ኛ: 300,000 ብር ጥሬ ገንዘብ\n10ኛ: 200,000 ብር ጥሬ ገንዘብ",
        "how_to_play": "📌 ይመዝገቡ > ቲኬት ይምረጡ > 3,000 ብር ይክፈሉ > ያሸንፉ!",
        "good_luck": "🚀 መልካም እድል!",
        "select_game": "የሎተሪ ውድድር ይምረጡ:",
        "quick_random": "⚡ በዘፈቀደ ቁጥር ምረጥ",
        "type_ticket_number": "⌨️ የቲኬት ቁጥር አስገባ",
        "back": "← ወደ ኋላ",
        "cancel": "✖ ሰርዝ",
        "Available": "ይገኛል",
        "Sold": "ተሽጧል",
        "Pending": "በመጠባበቅ ላይ",
        "Status": "ሁኔታ",
        "No active tickets found": "ምንም ቲኬት አልተገኘም።",
        "Price": "ዋጋ",
        "Game": "ውድድር",
        "Per Slot": "በአንድ ቲኬት",
        "Range": "ክልል",
        "blocks": "ብሎኮች",
        "Select Ticket": "ቲኬት ይምረጡ",
        "Selected Slot": "የተመረጠ ቲኬት",
        "Transfer payment to accounts": "📤 እባክዎ 3,000 ብር ወደ ታች ወደተዘረዘሩት አካውንቶች ያስተላልፉ:",
        "Send screenshot or paste bank SMS text receipt below": "📸 የባንክ SMS ወይም የክፍያ ማረጋገጫ ስክሪንሾት ይላኩ:",
        "Payment submitted successfully": "✅ ክፍያዎ ተልኳል! ማረጋገጫ በመጠባበቅ ላይ።",
        "Payment Approved": "✅ ክፍያዎ ጸድቋል!",
        "admin_panel": "🛠️ የአስተዳዳሪ ፓነል",
        "Create Game": "ውድድር ፍጠር",
        "Verify Payments": "ክፍያዎችን አረጋግጥ",
        "Edit Prizes": "ሽልማቶችን አስተካክል",
        "Broadcast Notification": "ማስታወቂያ ላክ",
        "Excel Reports": "Excel ሪፖርቶች",
        "Buy Ticket for User": "🎯 ለተጠቃሚ ቲኬት ግዛ",
        "Manual Ticket Input": "📝 በእጅ ቲኬት አስገባ",
        "User Management": "👤 የተጠቃሚ አመራር",
        "Refund Management": "🔄 የገንዘብ መመለሻ አመራር",
        "Add User": "➕ ተጠቃሚ ጨምር",
        "Delete User": "➖ ተጠቃሚ ሰርዝ",
        "List Users": "📋 ሁሉንም ተጠቃሚዎች ይመልከቱ",
        "User Added Successfully": "✅ ተጠቃሚው በተሳካ ሁኔታ ተጨምሯል!",
        "User Deleted Successfully": "✅ ተጠቃሚው በተሳካ ሁኔታ ተሰርዟል!",
        "User not found": "❌ ተጠቃሚ አልተገኘም!",
        "User already exists": "⚠️ ተጠቃሚው አስቀድሞ አለ!",
        "Confirm delete user": "⚠️ ይህን ተጠቃሚ ማስወገድ ያረጋግጣሉ?",
        "Delete warning": "⚠️ ይህ እርምጃ ሊቀለበስ አይችልም!",
        "Enter Telegram ID": "📝 የተጠቃሚውን Telegram ID ያስገቡ:",
        "Enter Phone Number": "📝 የተጠቃሚውን ስልክ ቁጥር ያስገቡ:",
        "Enter Address": "📍 የተጠቃሚውን አድራሻ ያስገቡ:",
        "Invalid Phone": "❌ ልክ ያልሆነ የስልክ ቁጥር! እባክዎ 09XXXXXXXX ቅርጸት ይጠቀሙ።",
        "User Info": "👤 የተጠቃሚ መረጃ",
        "User ID": "🆔 User ID",
        "Phone": "📱 ስልክ",
        "Address": "📍 አድራሻ",
        "Balance": "💰 ቀሪ ሂሳብ",
        "Tickets": "🎫 ቲኬቶች",
        "Total Spent": "💸 አጠቃላይ ወጪ",
        "Registration Date": "📅 የተመዘገበበት ቀን",
        "Language": "🌍 ቋንቋ",
        "Status": "📊 ሁኔታ",
        "Active": "ንቁ",
        "Blocked": "ታግዷል",
        "No users found": "📭 ምንም ተጠቃሚዎች አልተገኙም።",
        "Are you sure": "⚠️ እርግጠኛ ነዎት?",
        "Process Refund": "🔄 ገንዘብ መመለሻ አስኬድ",
        "User has no positive balance": "❌ ተጠቃሚው ሊመለስ የሚችል አዎንታዊ ቀሪ ሂሳብ የለውም።",
        "Refund processed successfully": "✅ የገንዘብ መመለሻ በተሳካ ሁኔታ ተጠናቅቋል!",
        "Refund failed": "❌ የገንዘብ መመለሻ አልተሳካም!",
        "Refund Request": "🔄 የገንዘብ መመለሻ ጥያቄ",
        "Example": "ለምሳሌ",
        "Or type": "ወይም ይተይቡ",
        "for a random available ticket": "በዘፈቀደ ለሚገኝ ቲኬት",
        "No available tickets found": "ምንም የሚገኝ ቲኬት አልተገኘም",
        "Ticket": "ቲኬት",
        "is not available": "አይገኝም",
        "Ticket Assigned Successfully": "ቲኬት በተሳካ ሁኔታ ተመድቧል",
        "User": "ተጠቃሚ",
        "Telegram": "Telegram",
        "Amount": "መጠን",
        "Payment": "ክፍያ",
        "The user has been notified": "ተጠቃሚው ተነግሯል",
        "Ticket Purchased For You": "ቲኬት ለእርስዎ ተገዝቷል",
        "An admin has purchased ticket": "አስተዳዳሪ ቲኬት ገዝቷል",
        "on your behalf": "በእርስዎ ስም",
        "Use": "ተጠቀሙ",
        "to see your tickets": "ቲኬቶችዎን ለማየት",
        "Manual Ticket Input": "በእጅ ቲኬት ማስገቢያ",
        "Enter the ticket number to manually mark as sold": "በእጅ ለመሸጥ የቲኬት ቁጥር ያስገቡ",
        "This will mark the ticket as sold without payment verification": "ይህ ክፍያ ሳይረጋገጥ ቲኬቱን እንደተሸጠ ያደርገዋል",
        "Get help from our support team": "ከድጋፍ ቡድናችን እርዳታ ያግኙ",
        "View all verified tickets": "ሁሉንም የተረጋገጡ ቲኬቶች ይመልከቱ",
        "You don't have any tickets yet": "ገና ምንም ቲኬት የለዎትም",
        "Join a game to purchase your first ticket": "የመጀመሪያ ቲኬትዎን ለመግዛት ውድድር ይቀላቀሉ",
        "Total Tickets": "አጠቃላይ ቲኬቶች",
        "Your Tickets": "ቲኬቶችዎ",
        "Total": "አጠቃላይ",
        "to": "ለ",
        "refunds": "ገንዘብ መመለሻ",
        "Processed": "ተሰርቷል",
        "Refund not found or already processed": "ገንዘብ መመለሻ አልተገኘም ወይም አስቀድሞ ተሰርቷል",
        "User no longer has sufficient balance": "ተጠቃሚው በቂ ቀሪ ሂሳብ የለውም",
        "Refund Approved": "ገንዘብ መመለሻ ጸድቋል",
        "Your refund has been processed": "ገንዘብ መመለሻዎ ተሰርቷል",
        "Refund approved": "ገንዘብ መመለሻ ጸድቋል",
        "Please register first": "እባክዎ መጀመሪያ ይመዝገቡ",
        "You have no positive balance to refund": "ሊመለስልዎ የሚችል አዎንታዊ ቀሪ ሂሳብ የለዎትም",
        "You already have a pending refund request": "አስቀድመው በመጠባበቅ ላይ ያለ የገንዘብ መመለሻ ጥያቄ አለዎት",
        "Request Refund": "ገንዘብ መመለስ ይጠይቁ",
        "Your Current Balance": "የአሁኑ ቀሪ ሂሳብዎ",
        "This will request a refund of your entire positive balance": "ይህ አጠቃላይ አዎንታዊ ቀሪ ሂሳብዎን መመለስ ይጠይቃል",
        "Admin will review and process your request": "አስተዳዳሪ ጥያቄዎን ይገመግማል እና ያስኬዳል",
        "Confirm refund request": "የገንዘብ መመለሻ ጥያቄ ያረጋግጡ",
        "No positive balance to refund": "ሊመለስ የሚችል አዎንታዊ ቀሪ ሂሳብ የለም",
        "Please enter the reason for refund": "እባክዎ የገንዘብ መመለሻ ምክንያት ያስገቡ",
        "Invalid request": "ልክ ያልሆነ ጥያቄ",
        "Refund request submitted": "የገንዘብ መመለሻ ጥያቄ ቀርቧል",
        "New Refund Request": "አዲስ የገንዘብ መመለሻ ጥያቄ",
        "to process": "ለማስኬድ",
        "Users with Positive Balance": "አዎንታዊ ቀሪ ሂሳብ ያላቸው ተጠቃሚዎች",
        "Eligible for Refund": "ገንዘብ መመለሻ ብቁ",
        "Process All Positive Balances": "ሁሉንም አዎንታዊ ቀሪ ሂሳቦች አስኬድ",
        "No users with positive balance": "አዎንታዊ ቀሪ ሂሳብ ያላቸው ተጠቃሚዎች የሉም",
        "Pending Refund Requests": "በመጠባበቅ ላይ ያሉ የገንዘብ መመለሻ ጥያቄዎች",
        "No pending refund requests": "በመጠባበቅ ላይ ያሉ የገንዘብ መመለሻ ጥያቄዎች የሉም",
        "Completed Refunds": "የተጠናቀቁ ገንዘብ መመለሻዎች",
        "Total Refunded": "አጠቃላይ የተመለሰ ገንዘብ",
        "Positive balance refunded by admin": "አዎንታዊ ቀሪ ሂሳብ በአስተዳዳሪ ተመልሷል",
        "Your balance has been cleared": "ቀሪ ሂሳብዎ ተጠርጓል",
        "Refunded": "ተመልሷል",
        "Positive balance refunded": "አዎንታዊ ቀሪ ሂሳብ ተመልሷል",
        "Broadcast Notification": "ማስታወቂያ ላክ",
        "Send a message/announcement to all registered bot users": "ለሁሉም በቦት ለተመዘገቡ ተጠቃሚዎች መልእክት/ማስታወቂያ ይላኩ",
        "No users found to broadcast": "ማስታወቂያ ለመላክ ተጠቃሚዎች አልተገኙም",
        "Broadcasting to": "ለሚከተሉት ተጠቃሚዎች እየተላከ:",
        "users": "ተጠቃሚዎች",
        "Announcement": "ማስታወቂያ",
        "Broadcast complete": "ማስታወቂያ ተጠናቀቀ",
        "Sent": "ተልኳል",
        "Failed": "አልተሳካም",
        "Total users": "አጠቃላይ ተጠቃሚዎች",
        "Success": "ተሳክቷል",
        "Select an option": "አማራጭ ይምረጡ",
        "Language changed to": "ቋንቋ ወደ ተቀየረ",
    }
    
    @classmethod
    def get_text(cls, user_id: int, key: str) -> str:
        lang = shared_state.get_language(user_id)
        texts = cls.AM if lang == "am" else cls.EN
        return texts.get(key, cls.EN.get(key, key))

# =====================================================
# KEYBOARD BUILDER
# =====================================================
class KeyboardBuilder:
    @staticmethod
    def main_menu(user_id: int) -> ReplyKeyboardMarkup:
        t = Localization.get_text
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=t(user_id, "buy_ticket")), KeyboardButton(text=t(user_id, "balance"))],
                [KeyboardButton(text=t(user_id, "my_tickets")), KeyboardButton(text=t(user_id, "view_prizes"))],
                [KeyboardButton(text=t(user_id, "support")), KeyboardButton(text=t(user_id, "lang_toggle"))]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    def admin_menu(user_id: int) -> InlineKeyboardMarkup:
        t = Localization.get_text
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(user_id, "Create Game"), callback_data="admin_create_game"),
             InlineKeyboardButton(text=t(user_id, "Verify Payments"), callback_data="admin_pending_payments")],
            [InlineKeyboardButton(text=t(user_id, "Refund Management"), callback_data="admin_refunds"),
             InlineKeyboardButton(text=t(user_id, "User Management"), callback_data="admin_user_management")],
            [InlineKeyboardButton(text=t(user_id, "Buy Ticket for User"), callback_data="admin_buy_for_user"),
             InlineKeyboardButton(text=t(user_id, "Manual Ticket Input"), callback_data="admin_manual_ticket")],
            [InlineKeyboardButton(text=t(user_id, "Broadcast Notification"), callback_data="admin_broadcast"),
             InlineKeyboardButton(text=t(user_id, "Excel Reports"), callback_data="admin_export_excel")]
        ])

# =====================================================
# STATES
# =====================================================
class RegStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_address = State()

class BuyStates(StatesGroup):
    waiting_for_sms_or_photo = State()
    waiting_for_user_ticket_input = State()

class AdminGameStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_num_prizes = State()
    waiting_for_prize_item = State()
    waiting_for_total_slots = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class RefundStates(StatesGroup):
    waiting_for_reason = State()

class AdminBuyStates(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    waiting_for_ticket_input = State()

class AdminUserStates(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    waiting_for_delete_id = State()

# =====================================================
# START COMMAND - CHOICE MENU UNDER INPUT TEXT
# =====================================================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Start command - show choice menu as reply keyboard under input"""
    await state.clear()
    uid = message.from_user.id
    
    # Check if user exists
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    
    # Get webapp URL from environment
    webapp_url = os.getenv("WEBAPP_URL", "https://siket-ekub-webapp.onrender.com")
    
    # Create choice menu as ReplyKeyboardMarkup (appears under input text)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Use Telegram Bot")],
            [KeyboardButton(text="🌐 Open Web Interface")],
            [KeyboardButton(text="ℹ️ About Siket Ekub")]
        ],
        resize_keyboard=True
    )
    
    # Welcome message with choice
    welcome_msg = (
        "🎰 **Siket Ekub Lottery**\n\n"
        "Welcome to Siket Ekub! Choose how you want to play:\n\n"
        "🤖 **Telegram Bot** - Use menus directly in Telegram\n"
        "🌐 **Web Interface** - Open in your browser\n\n"
        "Both interfaces share the same account and tickets!"
    )
    
    await message.answer(welcome_msg, reply_markup=kb, parse_mode="Markdown")

# =====================================================
# CHOICE HANDLERS - Using Message Text (Under Input)
# =====================================================

@router.message(F.text == "🤖 Use Telegram Bot")
async def choice_telegram(message: Message, state: FSMContext):
    """User chose Telegram interface - show language selection"""
    uid = message.from_user.id
    
    # Check if user already registered
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    
    if user:
        # User exists - go to main menu
        lang = user[8] if len(user) > 8 else "en"
        shared_state.set_language(uid, lang)
        
        # Remove choice keyboard
        await message.answer(
            Localization.get_text(uid, "welcome"),
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        return
    
    # New user - show language selection as inline buttons
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")]
    ])
    
    await message.answer(
        "🌍 **Welcome! Please choose your language:**\n\n"
        "🌍 **እንኳን ደህና መጡ! ቋንቋዎን ይምረጡ:**",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.message(F.text == "🌐 Open Web Interface")
async def choice_web(message: Message):
    """User chose Web Interface - send webapp link"""
    uid = message.from_user.id
    webapp_url = os.getenv("WEBAPP_URL", "https://siket-ekub-webapp.onrender.com")
    
    # Check if user exists
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    
    if user:
        lang = user[8] if len(user) > 8 else "en"
        shared_state.set_language(uid, lang)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Open Web Interface", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="choice_back")]
    ])
    
    await message.answer(
        "🌐 **Siket Ekub Web Interface**\n\n"
        "Click the button below to open the web interface in your browser.\n\n"
        "You can also access it directly at:\n"
        f"`{webapp_url}`",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.message(F.text == "ℹ️ About Siket Ekub")
async def choice_about(message: Message):
    """Show about information"""
    uid = message.from_user.id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="choice_back")]
    ])
    
    await message.answer(
        "🎰 **Siket Ekub Lottery**\n\n"
        "Ticket Price: 3,000 ETB\n\n"
        "🏆 **10 Grand Prizes:**\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "3rd: Shop Space (4,000,000 ETB)\n"
        "4th-7th: 1,000,000 ETB Cash each\n"
        "8th: 500,000 ETB Cash\n"
        "9th: 300,000 ETB Cash\n"
        "10th: 200,000 ETB Cash\n\n"
        "📌 Register > Pick Ticket > Pay 3,000 ETB > Win!\n\n"
        "🚀 GOOD LUCK!",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "choice_back")
async def choice_back(callback: CallbackQuery):
    """Go back to choice menu"""
    uid = callback.from_user.id
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Use Telegram Bot")],
            [KeyboardButton(text="🌐 Open Web Interface")],
            [KeyboardButton(text="ℹ️ About Siket Ekub")]
        ],
        resize_keyboard=True
    )
    
    welcome_msg = (
        "🎰 **Siket Ekub Lottery**\n\n"
        "Choose how you want to play:\n\n"
        "🤖 **Telegram Bot** - Use menus directly in Telegram\n"
        "🌐 **Web Interface** - Open in your browser\n\n"
        "Both interfaces share the same account and tickets!"
    )
    
    await callback.message.edit_text(welcome_msg, parse_mode="Markdown")
    await callback.message.answer(
        "Please choose an option:",
        reply_markup=kb
    )
    await callback.answer()

# =====================================================
# LANGUAGE SELECTION (Modified to handle callback)
# =====================================================

@router.callback_query(F.data.startswith("lang_"))
async def select_language(callback: CallbackQuery, state: FSMContext):
    """User selected language - start registration"""
    uid = callback.from_user.id
    lang = callback.data.split("_")[1]  # "en" or "am"
    
    shared_state.set_language(uid, lang)
    t = Localization.get_text
    
    # Show registration prompt with phone number request
    share_button = KeyboardButton(text=t(uid, "share_phone"), request_contact=True)
    kb = ReplyKeyboardMarkup(
        keyboard=[[share_button]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    
    welcome_text = (
        f"{t(uid, 'welcome')}\n\n"
        f"Ticket Price: 3,000 ETB\n\n"
        f"{t(uid, 'prize_header')}\n"
        f"{t(uid, 'prize_list')}\n\n"
        f"{t(uid, 'how_to_play')}\n\n"
        f"{t(uid, 'good_luck')}"
    )
    
    await callback.message.edit_text(welcome_text)
    await callback.message.answer(
        f"📱 {t(uid, 'share_phone')}\n\nShare your phone number to register and start playing!",
        reply_markup=kb
    )
    await state.set_state(RegStates.waiting_for_phone)
    await callback.answer()

# =====================================================
# REGISTRATION
# =====================================================
@router.message(RegStates.waiting_for_phone, F.contact)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone_number=message.contact.phone_number)
    uid = message.from_user.id
    await message.answer(
        Localization.get_text(uid, "address_prompt"),
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RegStates.waiting_for_address)

@router.message(RegStates.waiting_for_address, F.text)
async def process_address(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    phone = data.get("phone_number")
    address = message.text
    lang = shared_state.get_language(uid)
    
    existing = await DatabaseHelper.fetch_one("SELECT user_id FROM users WHERE telegram_id = ?", (uid,))
    if existing:
        await DatabaseHelper.execute(
            "UPDATE users SET phone_number = ?, address = ?, language = ? WHERE telegram_id = ?",
            (phone, address, lang, uid)
        )
    else:
        await DatabaseHelper.execute(
            "INSERT INTO users (telegram_id, phone_number, address, language) VALUES (?, ?, ?, ?)",
            (uid, phone, address, lang)
        )
    
    await state.clear()
    await message.answer(Localization.get_text(uid, "reg_success"))
    await message.answer(
        Localization.get_text(uid, "main_menu"),
        reply_markup=KeyboardBuilder.main_menu(uid)
    )

# =====================================================
# BUY TICKET
# =====================================================
@router.message(F.text.in_({"🎯 Buy Ticket (3,000 ETB)", "🎯 ቲኬት ግዛ (3,000 ብር)"}))
async def buy_ticket_direct(message: Message):
    uid = message.from_user.id
    t = Localization.get_text
    
    game = await DatabaseHelper.fetch_one(
        "SELECT type_id, name, total_slots, price FROM ticket_types WHERE is_active = 1 LIMIT 1"
    )
    if not game:
        await message.answer(
            "❌ No active game available. Please contact admin.",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        return
    
    type_id, game_name, total_slots, ticket_price = game
    
    main_ranges = [
        [(1, 1000), (5001, 6000), (10001, 11000), (15001, 16000)],
        [(1001, 2000), (6001, 7000), (11001, 12000), (16001, 17000)],
        [(2001, 3000), (7001, 8000), (12001, 13000), (17001, 18000)],
        [(3001, 4000), (8001, 9000), (13001, 14000), (18001, 19000)],
        [(4001, 5000), (9001, 10000), (14001, 15000), (19001, 20000)]
    ]
    
    kb_rows = [
        [
            InlineKeyboardButton(text=t(uid, "quick_random"), callback_data=f"random_tkt_{type_id}"),
            InlineKeyboardButton(text=t(uid, "type_ticket_number"), callback_data=f"prompt_type_tkt_{type_id}")
        ]
    ]
    
    for col_ranges in main_ranges:
        row_buttons = []
        for start, end in col_ranges:
            row_buttons.append(
                InlineKeyboardButton(
                    text=f"{start:,} - {end:,}",
                    callback_data=f"tkt_block_{type_id}_{start}_{end}"
                )
            )
        kb_rows.append(row_buttons)
    
    kb_rows.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    header = (
        f"🚨 {t(uid, 'Price')} {t(uid, 'Notification')} 🚨\n"
        f"{t(uid, 'Game')}: {game_name}\n"
        f"{t(uid, 'Price')} {t(uid, 'Per Slot')}: {ticket_price:,.0f} ETB\n\n"
        f"{t(uid, 'Select Ticket')}:"
    )
    await message.answer(header, reply_markup=kb)

# =====================================================
# TICKET SELECTION HANDLERS
# =====================================================
@router.callback_query(F.data.startswith("tkt_block_"))
async def handle_block_selection(callback: CallbackQuery):
    uid = callback.from_user.id
    parts = callback.data.split("_")
    type_id = int(parts[2])
    block_start = int(parts[3])
    block_end = int(parts[4])
    
    kb_rows = []
    row = []
    step = 100
    
    for sub_start in range(block_start, block_end, step):
        sub_end = sub_start + step - 1
        row.append(
            InlineKeyboardButton(
                text=f"{sub_start} - {sub_end}",
                callback_data=f"tkt_subrange_{type_id}_{sub_start}_{sub_end}"
            )
        )
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    
    if row:
        kb_rows.append(row)
    
    kb_rows.append([
        InlineKeyboardButton(
            text=Localization.get_text(uid, "back"),
            callback_data=f"type_{type_id}"
        )
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(
        f"📂 Block Selected: {block_start:,} - {block_end:,}\nSelect a 100-ticket range:",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("tkt_subrange_"))
async def handle_subrange_selection(callback: CallbackQuery):
    uid = callback.from_user.id
    parts = callback.data.split("_")
    type_id = int(parts[2])
    range_start = int(parts[3])
    range_end = int(parts[4])
    
    tickets = await DatabaseHelper.fetch(
        """SELECT ticket_id, ticket_number, status 
           FROM tickets 
           WHERE type_id = ? AND ticket_number BETWEEN ? AND ? 
           ORDER BY ticket_number ASC""",
        (type_id, range_start, range_end)
    )
    
    kb_rows = []
    row = []
    
    for t_id, t_num, status in tickets:
        if status == 'available':
            row.append(
                InlineKeyboardButton(
                    text=f"{t_num}",
                    callback_data=f"select_tkt_{type_id}_{t_id}"
                )
            )
        else:
            row.append(
                InlineKeyboardButton(
                    text="SOLD",
                    callback_data="tkt_taken_alert"
                )
            )
        
        if len(row) == 5:
            kb_rows.append(row)
            row = []
    
    if row:
        kb_rows.append(row)
    
    parent_block_start = ((range_start - 1) // 1000) * 1000 + 1
    parent_block_end = parent_block_start + 999
    
    kb_rows.append([
        InlineKeyboardButton(
            text=Localization.get_text(uid, "back"),
            callback_data=f"tkt_block_{type_id}_{parent_block_start}_{parent_block_end}"
        )
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(
        f"🎫 Tickets Range: {range_start} - {range_end}\nChoose an individual ticket number:",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("random_tkt_"))
@router.callback_query(F.data.startswith("select_tkt_"))
async def select_ticket(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    try:
        if callback.data.startswith("random_tkt_"):
            type_id = int(callback.data.split("_")[2])
            avail = await DatabaseHelper.fetch(
                "SELECT ticket_id FROM tickets WHERE type_id = ? AND status = 'available'",
                (type_id,)
            )
            if not avail:
                await callback.answer(
                    Localization.get_text(uid, "All slots are currently sold out"),
                    show_alert=True
                )
                return
            ticket_id = random.choice(avail)[0]
        else:
            parts = callback.data.split("_")
            ticket_id = int(parts[3])
        
        await state.update_data(selected_ticket_id=ticket_id)
        
        ticket = await DatabaseHelper.fetch_one(
            "SELECT ticket_number, type_id FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        )
        if not ticket:
            await callback.answer("Invalid ticket", show_alert=True)
            return
        
        code, type_id = ticket
        price_row = await DatabaseHelper.fetch_one(
            "SELECT price FROM ticket_types WHERE type_id = ?",
            (type_id,)
        )
        ticket_price = price_row[0] if price_row else 3000.0
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=Localization.get_text(uid, "cancel"), callback_data="menu_buy")]
        ])
        
        instructions = (
            f"{Localization.get_text(uid, 'Selected Slot')}: #{code} | "
            f"{Localization.get_text(uid, 'Price')}: {ticket_price:,.0f} ETB\n\n"
            f"{Localization.get_text(uid, 'Transfer payment to accounts')}:\n"
            "• CBE: 1000786684491\n"
            "• Abyssinia: 264517826\n"
            "• Telebirr: 0979774444\n\n"
            f"📸 {Localization.get_text(uid, 'Send screenshot or paste bank SMS text receipt below')}:"
        )
        
        await callback.message.edit_text(instructions, reply_markup=kb)
        await state.set_state(BuyStates.waiting_for_sms_or_photo)
        await callback.answer()
    except Exception as e:
        logger.error(f"Select ticket error: {e}")
        await callback.answer("❌ An error occurred. Please try again.", show_alert=True)

@router.callback_query(F.data.startswith("prompt_type_tkt_"))
async def prompt_user_ticket_number(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    type_id = int(callback.data.split("_")[3])
    await state.update_data(buying_type_id=type_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=Localization.get_text(uid, "cancel"), callback_data="menu_buy")]
    ])
    await callback.message.edit_text(
        f"⌨️ Type Ticket Number\n\nPlease enter your desired ticket number (e.g., 150):",
        reply_markup=kb
    )
    await state.set_state(BuyStates.waiting_for_user_ticket_input)
    await callback.answer()

@router.message(BuyStates.waiting_for_user_ticket_input, F.text)
async def process_user_ticket_number_input(message: Message, state: FSMContext):
    uid = message.from_user.id
    text_input = message.text.strip()
    
    try:
        ticket_num = int(text_input)
    except ValueError:
        await message.answer("❌ Invalid number format. Please enter a valid ticket number.")
        return
    
    data = await state.get_data()
    type_id = data.get("buying_type_id")
    
    if not type_id:
        game = await DatabaseHelper.fetch_one(
            "SELECT type_id FROM ticket_types WHERE is_active = 1 ORDER BY type_id ASC LIMIT 1"
        )
        if game:
            type_id = game[0]
        else:
            await message.answer("❌ No active game found.")
            await state.clear()
            return
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_id, status FROM tickets WHERE type_id = ? AND ticket_number = ?",
        (type_id, ticket_num)
    )
    
    if not ticket:
        await message.answer(f"❌ Ticket #{ticket_num} does not exist. Try another number:")
        return
    
    ticket_id, status = ticket
    if status != 'available':
        await message.answer(f"⚠️ Ticket #{ticket_num} is {status.upper()}. Please choose another:")
        return
    
    await state.update_data(selected_ticket_id=ticket_id)
    
    price_row = await DatabaseHelper.fetch_one(
        "SELECT price FROM ticket_types WHERE type_id = ?",
        (type_id,)
    )
    ticket_price = price_row[0] if price_row else 3000.0
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=Localization.get_text(uid, "cancel"), callback_data="menu_buy")]
    ])
    
    instructions = (
        f"{Localization.get_text(uid, 'Selected Slot')}: #{ticket_num} | "
        f"{Localization.get_text(uid, 'Price')}: {ticket_price:,.0f} ETB\n\n"
        f"{Localization.get_text(uid, 'Transfer payment to accounts')}:\n"
        "• CBE: 1000786684491\n"
        "• Abyssinia: 264517826\n"
        "• Telebirr: 0979774444\n\n"
        f"📸 {Localization.get_text(uid, 'Send screenshot or paste bank SMS text receipt below')}:"
    )
    
    await message.answer(instructions, reply_markup=kb)
    await state.set_state(BuyStates.waiting_for_sms_or_photo)

@router.callback_query(F.data == "tkt_taken_alert")
async def tkt_taken_alert(callback: CallbackQuery):
    uid = callback.from_user.id
    await callback.answer(
        Localization.get_text(uid, "This slot is already taken"),
        show_alert=True
    )

# =====================================================
# PAYMENT HANDLER - NO OCR (Manual Verification Only)
# =====================================================
@router.message(BuyStates.waiting_for_sms_or_photo, F.text | F.photo)
async def process_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("selected_ticket_id")
    uid = message.from_user.id
    
    if not ticket_id:
        await message.answer(
            "❌ No ticket selected. Please start over.",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        await state.clear()
        return
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_number, type_id FROM tickets WHERE ticket_id = ?",
        (ticket_id,)
    )
    if not ticket:
        await message.answer(
            "❌ Ticket not found!",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        await state.clear()
        return
    
    ticket_number, type_id = ticket
    price_row = await DatabaseHelper.fetch_one(
        "SELECT price FROM ticket_types WHERE type_id = ?",
        (type_id,)
    )
    required_price = price_row[0] if price_row else 3000.0
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, phone_number FROM users WHERE telegram_id = ?",
        (uid,)
    )
    if not user:
        await message.answer(
            "❌ Please register first using /start",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        await state.clear()
        return
    
    user_id, phone = user
    raw_text, amount, ref_code, date = "", 0.0, None, None
    screenshot_data = ""
    
    if message.photo:
        # Handle screenshot
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file_info.file_path)
        import base64
        screenshot_data = base64.b64encode(downloaded.read()).decode('utf-8')
        
        # Try to parse SMS from caption
        if message.caption:
            parsed = parse_payment_sms(message.caption)
            amount = parsed.get("amount", 0.0)
            ref_code = parsed.get("reference")
            date = parsed.get("date")
            raw_text = message.caption
        
        if amount == 0:
            await message.answer(
                "📸 Could not read amount from caption.\n\n"
                "Please type the amount and reference manually:\n"
                "Amount: [number] ETB\n"
                "Ref: [reference code]"
            )
            return
    else:
        # Text message (SMS)
        raw_text = message.text
        parsed = parse_payment_sms(raw_text)
        amount = parsed.get("amount", 0.0)
        ref_code = parsed.get("reference")
        date = parsed.get("date")
        logger.info(f"SMS parsed - Amount: {amount}, Ref: {ref_code}, Date: {date}")
    
    # Underpayment check
    if amount < required_price:
        await DatabaseHelper.execute("""
            INSERT INTO payments 
            (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
             raw_sms, extracted_ref, extracted_amount, extracted_date, status, admin_notes, screenshot_data) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'rejected', ?, ?)
        """, (
            user_id, uid, phone, ticket_id, ticket_number,
            raw_text, ref_code, amount, date,
            f"Underpayment: {amount:,.2f} ETB paid, {required_price:,.0f} ETB required",
            screenshot_data
        ))
        
        await message.answer(
            f"⚠️ Underpayment detected!\n\n"
            f"Required: {required_price:,.0f} ETB\n"
            f"Paid: {amount:,.2f} ETB\n"
            f"Shortfall: {required_price - amount:,.2f} ETB\n\n"
            f"❌ Payment automatically rejected. Please pay the full amount.",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        await state.clear()
        return
    
    # Duplicate reference check
    if ref_code:
        existing_ref = await DatabaseHelper.fetch_one(
            "SELECT payment_id FROM payments WHERE extracted_ref = ? AND status != 'rejected'",
            (ref_code,)
        )
        if existing_ref:
            await DatabaseHelper.execute("""
                INSERT INTO payments 
                (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
                 raw_sms, extracted_ref, extracted_amount, extracted_date, status, admin_notes, screenshot_data) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'rejected', ?, ?)
            """, (
                user_id, uid, phone, ticket_id, ticket_number,
                raw_text, ref_code, amount, date,
                f"Duplicate reference: {ref_code} already used",
                screenshot_data
            ))
            
            await message.answer(
                f"❌ Duplicate reference detected!\n\n"
                f"🔖 Reference: {ref_code}\n\n"
                f"This reference code has already been used for another payment.\n"
                f"Please use a new transaction reference.",
                reply_markup=KeyboardBuilder.main_menu(uid)
            )
            await state.clear()
            return
    
    # PASSED ALL CHECKS: Insert into pending payments
    cursor = await DatabaseHelper.execute("""
        INSERT INTO payments 
        (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
         raw_sms, extracted_ref, extracted_amount, extracted_date, status, screenshot_data) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user_id, uid, phone, ticket_id, ticket_number,
        raw_text, ref_code, amount, date,
        screenshot_data
    ))
    payment_id = cursor.lastrowid
    
    await state.clear()
    await message.answer(
        f"✅ Payment submitted!\n\n"
        f"📌 Reference: {ref_code or 'Not Detected'}\n"
        f"💰 Amount: {amount:,.2f} ETB\n"
        f"🎫 Ticket: #{ticket_number}\n\n"
        f"⏳ Waiting for admin verification...",
        reply_markup=KeyboardBuilder.main_menu(uid)
    )
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 View Payment", callback_data=f"match_pay_{payment_id}")]
    ])
    admin_msg = (
        f"🔔 New Payment!\n"
        f"👤 Phone: {phone}\n"
        f"🎫 Ticket: #{ticket_number}\n"
        f"💰 Amount: {amount:,.2f} ETB\n"
        f"🔖 Ref: {ref_code or 'NOT DETECTED'}\n"
        f"🆔 Payment: {payment_id}"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=admin_msg, reply_markup=admin_kb)
            else:
                await bot.send_message(admin_id, admin_msg, reply_markup=admin_kb)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

# =====================================================
# ADMIN COMMANDS
# =====================================================
@router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!")
        return
    await state.clear()
    await message.answer(
        f"🛠️ {Localization.get_text(uid, 'admin_panel')}",
        reply_markup=KeyboardBuilder.admin_menu(uid)
    )

@router.callback_query(F.data == "admin_menu")
async def admin_panel_callback(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        f"🛠️ {Localization.get_text(uid, 'admin_panel')}",
        reply_markup=KeyboardBuilder.admin_menu(uid)
    )
    await callback.answer()

# =====================================================
# ADMIN: PENDING PAYMENTS
# =====================================================
@router.callback_query(F.data == "admin_pending_payments")
async def pending_payments(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payments = await DatabaseHelper.fetch("""
        SELECT p.payment_id, u.phone_number, p.extracted_ref, p.extracted_amount, 
               p.ticket_number, p.created_at, p.screenshot_data
        FROM payments p 
        JOIN users u ON p.user_id = u.user_id 
        WHERE p.status = 'pending'
        ORDER BY p.created_at DESC
    """)
    
    if not payments:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=Localization.get_text(uid, "back"), callback_data="admin_menu")]
        ])
        await callback.message.edit_text("📭 No pending payments.", reply_markup=kb)
        await callback.answer()
        return
    
    kb_rows = []
    for p_id, phone, ref, amount, ticket_num, created, screenshot in payments:
        has_screenshot = "📸" if screenshot else "📝"
        kb_rows.append([
            InlineKeyboardButton(
                text=f"{has_screenshot} {phone} | #{ticket_num} | {amount:,.2f} ETB",
                callback_data=f"match_pay_{p_id}"
            )
        ])
    
    kb_rows.append([
        InlineKeyboardButton(text=Localization.get_text(uid, "back"), callback_data="admin_menu")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(f"📋 Pending Verification Queue:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("match_pay_"))
async def match_payment(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[2])
    await state.update_data(matching_payment_id=payment_id)
    
    payment = await DatabaseHelper.fetch_one("""
        SELECT p.payment_id, p.ticket_id, p.user_id, p.telegram_id, p.phone_number,
               p.ticket_number, p.extracted_ref, p.extracted_amount,
               p.extracted_date, tt.price, u.full_name, p.screenshot_data
        FROM payments p
        JOIN tickets t ON p.ticket_id = t.ticket_id
        JOIN ticket_types tt ON t.type_id = tt.type_id
        JOIN users u ON p.user_id = u.user_id
        WHERE p.payment_id = ? AND p.status = 'pending'
    """, (payment_id,))
    
    if not payment:
        await callback.answer("Payment not found", show_alert=True)
        return
    
    (pay_id, ticket_id, user_id, telegram_id, phone, ticket_num, ref, amount, date, required_price, name, screenshot) = payment
    
    # Show screenshot if available
    screenshot_text = ""
    if screenshot:
        screenshot_text = "📸 Screenshot attached to this payment"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_pay_{payment_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_pay_{payment_id}")
        ],
        [
            InlineKeyboardButton(text=Localization.get_text(uid, "back"), callback_data="admin_pending_payments")
        ]
    ])
    
    text = (
        f"🔍 Verify Payment\n\n"
        f"👤 User: {name or 'N/A'}\n"
        f"📞 Phone: {phone}\n"
        f"🎫 Ticket: #{ticket_num}\n"
        f"💰 Amount: {amount:,.2f} ETB\n"
        f"🔖 Ref: {ref or 'Not Detected'}\n"
        f"📅 Date: {date or 'N/A'}\n\n"
        f"Required: {required_price:,.0f} ETB\n"
        f"{screenshot_text}"
    )
    
    try:
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
        try:
            await callback.message.delete()
        except:
            pass
    
    await callback.answer()

# =====================================================
# ADMIN: APPROVE PAYMENT
# =====================================================
@router.callback_query(F.data.startswith("approve_pay_"))
async def approve_payment(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[2])
    payment = await DatabaseHelper.fetch_one("""
        SELECT p.payment_id, p.ticket_id, p.user_id, p.telegram_id, p.phone_number,
               p.ticket_number, p.extracted_ref, p.extracted_amount,
               p.extracted_date, tt.price, u.full_name,
               t.status
        FROM payments p
        JOIN tickets t ON p.ticket_id = t.ticket_id
        JOIN ticket_types tt ON t.type_id = tt.type_id
        JOIN users u ON p.user_id = u.user_id
        WHERE p.payment_id = ? AND p.status = 'pending'
    """, (payment_id,))
    
    if not payment:
        await callback.answer("Payment not found", show_alert=True)
        return
    
    (pay_id, ticket_id, user_id, telegram_id, phone, ticket_num, ref, amount, date, required_price, name, ticket_status) = payment
    
    # Prevent selling the same ticket twice
    if ticket_status == 'sold':
        await callback.answer("❌ This ticket is already sold! Rejecting payment.", show_alert=True)
        await DatabaseHelper.execute(
            "UPDATE payments SET status = 'rejected', admin_notes = 'Ticket already sold' WHERE payment_id = ?",
            (payment_id,)
        )
        await callback.message.edit_text(
            f"❌ Payment #{payment_id} rejected - ticket already sold!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Back to Admin", callback_data="admin_menu")]
            ])
        )
        return
    
    await DatabaseHelper.execute_transaction([
        (
            "UPDATE payments SET status = 'approved', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
            (uid, payment_id)
        ),
        (
            "UPDATE tickets SET status = 'sold', user_id = ?, telegram_id = ?, phone_number = ?, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
            (user_id, telegram_id, phone, ticket_id)
        ),
        (
            "UPDATE users SET balance = COALESCE(balance, 0) + ?, total_spent = COALESCE(total_spent, 0) + ? WHERE user_id = ?",
            (amount, amount, user_id)
        )
    ])
    
    await post_ticket_to_channel(telegram_id, str(ticket_num), phone, amount, ref)
    
    try:
        await bot.send_message(
            telegram_id,
            f"🎉 Payment Approved!\n\n"
            f"🎫 Ticket: #{ticket_num}\n"
            f"💰 Amount: {amount:,.2f} ETB\n"
            f"📌 Reference: {ref or 'N/A'}\n\n"
            f"✅ Your ticket has been verified and posted to the ticket channel.\n"
            f"🔗 {TICKET_CHANNEL_LINK}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎟️ View Ticket Channel", url=TICKET_CHANNEL_LINK)]
            ])
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    
    await callback.answer("✅ Payment approved!")
    await callback.message.edit_text(
        f"✅ Payment #{payment_id} approved!\n"
        f"🎟️ Ticket: #{ticket_num}\n"
        f"📌 Posted to: {TICKET_CHANNEL_NAME}\n"
        f"🔗 {TICKET_CHANNEL_LINK}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Back to Admin", callback_data="admin_menu")]
        ])
    )

# =====================================================
# ADMIN: REJECT PAYMENT
# =====================================================
@router.callback_query(F.data.startswith("reject_pay_"))
async def reject_payment(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    payment_id = int(callback.data.split("_")[2])
    payment = await DatabaseHelper.fetch_one(
        """SELECT telegram_id, ticket_number, extracted_amount 
           FROM payments WHERE payment_id = ? AND status = 'pending'""",
        (payment_id,)
    )
    
    if not payment:
        await callback.answer("Payment not found", show_alert=True)
        return
    
    telegram_id, ticket_num, amount = payment
    
    await DatabaseHelper.execute(
        "UPDATE payments SET status = 'rejected', admin_notes = 'Rejected by admin', verified_by = ? WHERE payment_id = ?",
        (uid, payment_id)
    )
    
    try:
        await bot.send_message(
            telegram_id,
            f"❌ Payment Rejected\n\n"
            f"🎫 Ticket: #{ticket_num}\n"
            f"💰 Amount: {amount:,.2f} ETB\n\n"
            f"Please contact support for assistance.\n"
            f"📞 {SUPPORT_CHANNEL_LINK}"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    
    await callback.answer("❌ Payment rejected!")
    await callback.message.edit_text(
        f"❌ Payment #{payment_id} rejected!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Back to Admin", callback_data="admin_menu")]
        ])
    )

# =====================================================
# ADMIN: USER MANAGEMENT
# =====================================================
@router.callback_query(F.data == "admin_user_management")
async def admin_user_management(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(uid, "Add User"), callback_data="admin_add_user"),
            InlineKeyboardButton(text=t(uid, "Delete User"), callback_data="admin_delete_user")
        ],
        [
            InlineKeyboardButton(text=t(uid, "List Users"), callback_data="admin_list_users"),
            InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_menu")
        ]
    ])
    
    await callback.message.edit_text(
        f"👤 {t(uid, 'User Management')}\n\n{t(uid, 'Select an option')}:",
        reply_markup=kb
    )
    await callback.answer()

# =====================================================
# ADMIN: ADD USER
# =====================================================
@router.callback_query(F.data == "admin_add_user")
async def admin_add_user(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_user_management")]
    ])
    
    await callback.message.edit_text(
        f"📝 {t(uid, 'Add User')}\n\n{t(uid, 'Enter Telegram ID')}\n\n{t(uid, 'Example')}: `123456789`",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminUserStates.waiting_for_telegram_id)
    await callback.answer()

@router.message(AdminUserStates.waiting_for_telegram_id, F.text)
async def admin_add_user_get_telegram(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    try:
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid Telegram ID. Please enter a valid number.")
        return
    
    existing = await DatabaseHelper.fetch_one(
        "SELECT user_id FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    
    if existing:
        t = Localization.get_text
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_user_management")]
        ])
        await message.answer(f"⚠️ {t(uid, 'User already exists')}", reply_markup=kb)
        await state.clear()
        return
    
    await state.update_data(target_telegram_id=telegram_id)
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_user_management")]
    ])
    
    await message.answer(
        f"📝 {t(uid, 'Enter Phone Number')}\n\n{t(uid, 'Example')}: `0912345678`",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminUserStates.waiting_for_phone)

@router.message(AdminUserStates.waiting_for_phone, F.text)
async def admin_add_user_get_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    phone = message.text.strip()
    if not re.match(r'^09\d{8}$', phone):
        t = Localization.get_text
        await message.answer(f"❌ {t(uid, 'Invalid Phone')}")
        return
    
    await state.update_data(target_phone=phone)
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_user_management")]
    ])
    
    await message.answer(
        f"📝 {t(uid, 'Enter Address')}\n\n{t(uid, 'Example')}: Addis Ababa, Bole",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminUserStates.waiting_for_address)

@router.message(AdminUserStates.waiting_for_address, F.text)
async def admin_add_user_get_address(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    address = message.text.strip()
    data = await state.get_data()
    telegram_id = data.get("target_telegram_id")
    phone = data.get("target_phone")
    
    await DatabaseHelper.execute(
        "INSERT INTO users (telegram_id, phone_number, address, language) VALUES (?, ?, ?, ?)",
        (telegram_id, phone, address, "en")
    )
    await state.clear()
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_user_management")]
    ])
    
    await message.answer(
        f"✅ {t(uid, 'User Added Successfully')}\n\n"
        f"🆔 Telegram ID: {telegram_id}\n"
        f"📱 Phone: {phone}\n"
        f"📍 Address: {address}",
        reply_markup=kb
    )

# =====================================================
# ADMIN: DELETE USER
# =====================================================
@router.callback_query(F.data == "admin_delete_user")
async def admin_delete_user(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_user_management")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ {t(uid, 'Delete User')}\n\n{t(uid, 'Enter Telegram ID')}",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminUserStates.waiting_for_delete_id)
    await callback.answer()

@router.message(AdminUserStates.waiting_for_delete_id, F.text)
async def admin_delete_user_confirm(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    try:
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid Telegram ID. Please enter a valid number.")
        return
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, full_name, phone_number FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    
    if not user:
        t = Localization.get_text
        await message.answer(f"❌ {t(uid, 'User not found')}")
        await state.clear()
        return
    
    user_id, name, phone = user
    
    await DatabaseHelper.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    await state.clear()
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_user_management")]
    ])
    
    await message.answer(
        f"✅ {t(uid, 'User Deleted Successfully')}\n\n"
        f"🆔 Telegram ID: {telegram_id}\n"
        f"👤 Name: {name or 'N/A'}\n"
        f"📱 Phone: {phone}",
        reply_markup=kb
    )

# =====================================================
# ADMIN: LIST USERS
# =====================================================
@router.callback_query(F.data == "admin_list_users")
async def admin_list_users(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    users = await DatabaseHelper.fetch("""
        SELECT user_id, telegram_id, full_name, phone_number, address, 
               balance, total_spent, registration_date, language, is_active 
        FROM users 
        ORDER BY registration_date DESC
    """)
    
    t = Localization.get_text
    if not users:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_user_management")]
        ])
        await callback.message.edit_text(f"📭 {t(uid, 'No users found')}", reply_markup=kb)
        await callback.answer()
        return
    
    text = f"📋 {t(uid, 'List Users')} ({len(users)})\n\n"
    for user in users[:15]:
        user_id, telegram_id, name, phone, address, balance, total_spent, reg_date, lang, active = user
        status = "🟢 Active" if active else "🔴 Blocked"
        text += (
            f"👤 {name or 'User'}\n"
            f"  🆔 `{telegram_id}`\n"
            f"  📱 {phone}\n"
            f"  💰 {balance:,.2f} ETB\n"
            f"  {status}\n"
            f"─" * 20 + "\n"
        )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_user_management")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

# =====================================================
# ADMIN: BUY TICKET FOR USER
# =====================================================
@router.callback_query(F.data == "admin_buy_for_user")
async def admin_buy_for_user(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(
        f"🎯 {t(uid, 'Buy Ticket for User')}\n\n{t(uid, 'Enter Telegram ID')}\n\n{t(uid, 'Example')}: `123456789`",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminBuyStates.waiting_for_telegram_id)
    await callback.answer()

@router.message(AdminBuyStates.waiting_for_telegram_id, F.text)
async def admin_buy_get_telegram(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    try:
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid Telegram ID. Please enter a valid number.")
        return
    
    user = await DatabaseHelper.fetch_one(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    
    if not user:
        await state.update_data(target_telegram_id=telegram_id, is_new_user=True)
        t = Localization.get_text
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
        ])
        await message.answer(
            f"ℹ️ User with Telegram ID {telegram_id} not found.\n\n"
            f"{t(uid, 'Enter Phone Number')}\n\n"
            f"{t(uid, 'Example')}: `0912345678`",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await state.set_state(AdminBuyStates.waiting_for_phone)
    else:
        await state.update_data(target_telegram_id=telegram_id, is_new_user=False, user_data=user)
        await admin_buy_ask_ticket(message, state, uid)

@router.message(AdminBuyStates.waiting_for_phone, F.text)
async def admin_buy_get_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    phone = message.text.strip()
    if not re.match(r'^09\d{8}$', phone):
        t = Localization.get_text
        await message.answer(f"❌ {t(uid, 'Invalid Phone')}")
        return
    
    await state.update_data(target_phone=phone)
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"📍 {t(uid, 'Enter Address')}\n\n{t(uid, 'Example')}: Addis Ababa, Bole",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminBuyStates.waiting_for_address)

@router.message(AdminBuyStates.waiting_for_address, F.text)
async def admin_buy_get_address(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    address = message.text.strip()
    await state.update_data(target_address=address)
    
    data = await state.get_data()
    telegram_id = data.get('target_telegram_id')
    phone = data.get('target_phone')
    
    await DatabaseHelper.execute(
        "INSERT INTO users (telegram_id, phone_number, address, language) VALUES (?, ?, ?, ?)",
        (telegram_id, phone, address, "en")
    )
    
    await admin_buy_ask_ticket(message, state, uid)

async def admin_buy_ask_ticket(message: Message, state: FSMContext, uid: int):
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"🎫 {t(uid, 'Enter Ticket Number')}\n\n"
        f"{t(uid, 'Example')}: `1234`\n"
        f"{t(uid, 'Or type')} `random` {t(uid, 'for a random available ticket')}.",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminBuyStates.waiting_for_ticket_input)

@router.message(AdminBuyStates.waiting_for_ticket_input, F.text)
async def admin_buy_get_ticket(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    telegram_id = data.get('target_telegram_id')
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, phone_number, full_name FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    
    if not user:
        t = Localization.get_text
        await message.answer(f"❌ {t(uid, 'User not found')}. Please try again.")
        await state.clear()
        return
    
    user_id = user[0]
    phone = user[1]
    name = user[2] or f"User_{telegram_id}"
    
    ticket_input = message.text.strip().lower()
    
    if ticket_input == 'random':
        ticket = await DatabaseHelper.fetch_one(
            "SELECT ticket_id, ticket_number FROM tickets WHERE status = 'available' LIMIT 1"
        )
        if not ticket:
            t = Localization.get_text
            await message.answer(f"❌ {t(uid, 'No available tickets found')}!")
            await state.clear()
            return
        ticket_id = ticket[0]
        ticket_number = ticket[1]
    else:
        try:
            ticket_number = int(ticket_input)
        except ValueError:
            t = Localization.get_text
            await message.answer(
                f"❌ {t(uid, 'Invalid ticket number')}. Please enter a valid number or 'random'."
            )
            return
        
        ticket = await DatabaseHelper.fetch_one(
            "SELECT ticket_id FROM tickets WHERE ticket_number = ? AND status = 'available'",
            (ticket_number,)
        )
        if not ticket:
            t = Localization.get_text
            await message.answer(
                f"❌ {t(uid, 'Ticket')} #{ticket_number} {t(uid, 'is not available')}. Please choose another."
            )
            return
        ticket_id = ticket[0]
    
    await DatabaseHelper.execute_transaction([
        (
            "UPDATE tickets SET status = 'sold', user_id = ?, telegram_id = ?, phone_number = ?, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
            (user_id, telegram_id, phone, ticket_id)
        ),
        (
            "INSERT INTO payments (user_id, telegram_id, phone_number, ticket_id, ticket_number, extracted_amount, status, admin_notes) VALUES (?, ?, ?, ?, ?, 3000.0, 'approved', ?)",
            (user_id, telegram_id, phone, ticket_id, ticket_number, f"Admin purchase for {name}")
        )
    ])
    
    await state.clear()
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "admin_panel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"✅ {t(uid, 'Ticket Assigned Successfully')}!\n\n"
        f"👤 {t(uid, 'User')}: {name}\n"
        f"🆔 {t(uid, 'Telegram')}: {telegram_id}\n"
        f"📱 {t(uid, 'Phone')}: {phone}\n"
        f"🎫 {t(uid, 'Ticket')}: #{ticket_number}\n"
        f"💰 {t(uid, 'Amount')}: 3,000 ETB\n\n"
        f"{t(uid, 'The user has been notified')}.",
        reply_markup=kb
    )
    
    try:
        await bot.send_message(
            telegram_id,
            f"🎉 *{t(uid, 'Ticket Purchased For You')}!*\n\n"
            f"{t(uid, 'An admin has purchased ticket')} #{ticket_number} {t(uid, 'on your behalf')}.\n\n"
            f"🎫 {t(uid, 'Ticket')}: #{ticket_number}\n"
            f"💰 {t(uid, 'Amount')}: 3,000 ETB\n\n"
            f"{t(uid, 'Use')} /start {t(uid, 'to see your tickets')}!",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

# =====================================================
# ADMIN: MANUAL TICKET INPUT
# =====================================================
@router.callback_query(F.data == "admin_manual_ticket")
async def admin_manual_ticket(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(
        f"📝 {t(uid, 'Manual Ticket Input')}\n\n"
        f"{t(uid, 'Enter the ticket number to manually mark as sold')}:\n"
        f"{t(uid, 'Example')}: `1234`\n\n"
        f"⚠️ {t(uid, 'This will mark the ticket as sold without payment verification')}.",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.set_state(AdminBuyStates.waiting_for_ticket_input)
    await callback.answer()

# =====================================================
# SUPPORT CHANNELS
# =====================================================
@router.message(F.text.in_({"💬 Support & Channels", "💬 ድጋፍ እና ሰርጦች"}))
async def support_channels_menu(message: Message):
    uid = message.from_user.id
    t = Localization.get_text
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📞 {t(uid, 'support_channel')}", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton(text=f"🎟️ {t(uid, 'ticket_channel')}", url=TICKET_CHANNEL_LINK)],
        [InlineKeyboardButton(text=f"📋 {t(uid, 'my_tickets')}", callback_data="my_tickets_callback")],
        [InlineKeyboardButton(text=f"⬅️ {t(uid, 'back')}", callback_data="main_menu_callback")]
    ])
    
    await message.answer(
        f"💬 {t(uid, 'support_channels')}\n\n"
        f"📞 {t(uid, 'support_channel')}:\n"
        f"{t(uid, 'Get help from our support team')}.\n"
        f"{SUPPORT_CHANNEL_LINK}\n\n"
        f"🎟️ {t(uid, 'ticket_channel')}:\n"
        f"{t(uid, 'View all verified tickets')}.\n"
        f"{TICKET_CHANNEL_LINK}\n\n"
        f"📌 {t(uid, 'channels_description')}",
        reply_markup=kb
    )

@router.message(F.text.in_({"💬 Support", "💬 ድጋፍ"}))
async def legacy_support_handler(message: Message):
    await support_channels_menu(message)

# =====================================================
# MY TICKETS
# =====================================================
@router.callback_query(F.data == "my_tickets_callback")
async def my_tickets_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    t = Localization.get_text
    
    tickets = await DatabaseHelper.fetch("""
        SELECT t.ticket_number, tt.name, t.status, t.assigned_at 
        FROM tickets t
        JOIN ticket_types tt ON t.type_id = tt.type_id
        WHERE t.telegram_id = ? AND t.status = 'sold'
        ORDER BY t.ticket_number ASC
    """, (uid,))
    
    if not tickets:
        await callback.message.edit_text(
            "🎟️ " + t(uid, 'my_tickets') + "\n\n" +
            t(uid, 'You don\'t have any tickets yet') + ".\n\n" +
            "🎮 " + t(uid, 'Join a game to purchase your first ticket') + "!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Buy Ticket", callback_data="menu_buy")],
                [InlineKeyboardButton(text=f"🎟️ {t(uid, 'ticket_channel')}", url=TICKET_CHANNEL_LINK)],
                [InlineKeyboardButton(text=f"⬅️ {t(uid, 'back')}", callback_data="main_menu_callback")]
            ])
        )
        await callback.answer()
        return
    
    ticket_list = ""
    for ticket_num, game, status, assigned_at in tickets:
        ticket_list += f"  #{ticket_num} - {game} ({status})\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎟️ {t(uid, 'ticket_channel')}", url=TICKET_CHANNEL_LINK)],
        [InlineKeyboardButton(text=f"📞 {t(uid, 'support_channel')}", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton(text=f"⬅️ {t(uid, 'back')}", callback_data="main_menu_callback")]
    ])
    
    await callback.message.edit_text(
        f"🎟️ {t(uid, 'my_tickets')}\n\n"
        f"📊 {t(uid, 'Total Tickets')}: {len(tickets)}\n\n"
        f"{t(uid, 'Your Tickets')}:\n{ticket_list}\n\n"
        f"📌 {t(uid, 'channels_description')}",
        reply_markup=kb
    )
    await callback.answer()

# =====================================================
# BALANCE
# =====================================================
@router.message(F.text.in_({"💰 Balance", "💰 ቀሪ ሂሳብ"}))
async def show_balance(message: Message):
    uid = message.from_user.id
    t = Localization.get_text
    
    user = await DatabaseHelper.fetch_one(
        "SELECT full_name, phone_number, balance, total_spent FROM users WHERE telegram_id = ?",
        (uid,)
    )
    
    if not user:
        await message.answer(
            "❌ Please register first using /start",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        return
    
    full_name, phone, balance, total_spent = user
    tickets = await DatabaseHelper.fetch_one(
        "SELECT COUNT(*) FROM tickets WHERE telegram_id = ? AND status = 'sold'",
        (uid,)
    )
    ticket_count = tickets[0] if tickets else 0
    
    text = (
        f"💰 {t(uid, 'balance')}\n\n"
        f"👤 {full_name or 'User'}\n"
        f"📱 {phone}\n"
        f"🎫 {t(uid, 'my_tickets')}: {ticket_count}\n\n"
        f"💳 {t(uid, 'balance')}: {balance:,.2f} ETB\n"
        f"💸 {t(uid, 'total_spent')}: {total_spent:,.2f} ETB"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")]
    ])
    
    await message.answer(text, reply_markup=kb)

@router.message(F.text.in_({"📊 My Tickets", "📊 የኔ ቲኬቶች"}))
async def my_tickets_button(message: Message):
    uid = message.from_user.id
    t = Localization.get_text
    
    tickets = await DatabaseHelper.fetch("""
        SELECT t.ticket_number, tt.name, t.status, t.assigned_at 
        FROM tickets t
        JOIN ticket_types tt ON t.type_id = tt.type_id
        WHERE t.telegram_id = ? AND t.status = 'sold'
        ORDER BY t.ticket_number ASC
    """, (uid,))
    
    if not tickets:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Buy Ticket", callback_data="menu_buy")],
            [InlineKeyboardButton(text=f"🎟️ {t(uid, 'ticket_channel')}", url=TICKET_CHANNEL_LINK)],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")]
        ])
        await message.answer(
            "🎟️ " + t(uid, 'my_tickets') + "\n\n" +
            t(uid, 'You don\'t have any tickets yet') + ".",
            reply_markup=kb
        )
        return
    
    ticket_list = ""
    for ticket_num, game, status, assigned_at in tickets:
        ticket_list += f"  #{ticket_num} - {game} ({status})\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎟️ {t(uid, 'ticket_channel')}", url=TICKET_CHANNEL_LINK)],
        [InlineKeyboardButton(text=f"📞 {t(uid, 'support_channel')}", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")]
    ])
    
    await message.answer(
        f"🎟️ {t(uid, 'my_tickets')}\n\n"
        f"📊 {t(uid, 'Total Tickets')}: {len(tickets)}\n\n"
        f"{t(uid, 'Your Tickets')}:\n{ticket_list}",
        reply_markup=kb
    )

# =====================================================
# VIEW PRIZES
# =====================================================
@router.message(F.text.in_({"🏆 View Prizes", "🏆 ሽልማቶችን ተመልከት"}))
async def view_prizes_button(message: Message):
    uid = message.from_user.id
    t = Localization.get_text
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "view_prizes"), web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")]
    ])
    
    await message.answer(
        f"🏆 {t(uid, 'view_prizes')}\n\n"
        f"{t(uid, 'prize_header')}\n"
        f"{t(uid, 'prize_list')}",
        reply_markup=kb
    )

# =====================================================
# TOGGLE LANGUAGE
# =====================================================
@router.message(F.text.in_({"አማርኛ / EN", "EN / አማርኛ"}))
async def toggle_language(message: Message):
    uid = message.from_user.id
    current = shared_state.get_language(uid)
    new_lang = "am" if current == "en" else "en"
    shared_state.set_language(uid, new_lang)
    await DatabaseHelper.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?",
        (new_lang, uid)
    )
    t = Localization.get_text
    await message.answer(
        f"✅ {t(uid, 'Language changed to')} {'Amharic' if new_lang == 'am' else 'English'}",
        reply_markup=KeyboardBuilder.main_menu(uid)
    )

# =====================================================
# MAIN MENU CALLBACK
# =====================================================
@router.callback_query(F.data == "main_menu_callback")
async def main_menu_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    t = Localization.get_text
    await callback.message.delete()
    await callback.message.answer(
        t(uid, "main_menu"),
        reply_markup=KeyboardBuilder.main_menu(uid)
    )
    await callback.answer()

@router.callback_query(F.data == "menu_buy")
async def menu_buy_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    t = Localization.get_text
    await callback.message.edit_text(
        f"🎯 {t(uid, 'buy_ticket')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")]
        ])
    )
    await callback.answer()
    await buy_ticket_direct(callback.message)

# =====================================================
# ADMIN: BROADCAST
# =====================================================
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(
        f"📢 {t(uid, 'Broadcast Notification')}\n\n"
        f"{t(uid, 'Send a message/announcement to all registered bot users')}:",
        reply_markup=kb
    )
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()

@router.message(BroadcastStates.waiting_for_message, F.text)
async def execute_broadcast(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    broadcast_text = message.text
    await state.clear()
    
    users = await DatabaseHelper.fetch("SELECT telegram_id FROM users")
    if not users:
        t = Localization.get_text
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "admin_panel"), callback_data="admin_menu")]
        ])
        await message.answer(f"❌ {t(uid, 'No users found to broadcast')}.", reply_markup=kb)
        return
    
    success_count, fail_count = 0, 0
    status_msg = await message.answer(
        f"📤 {t(uid, 'Broadcasting to')} {len(users)} {t(uid, 'users')}..."
    )
    
    for (user_id,) in users:
        try:
            await bot.send_message(
                user_id,
                f"📢 {t(uid, 'Announcement')}\n\n{broadcast_text}"
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1
    
    await status_msg.edit_text(
        f"✅ {t(uid, 'Broadcast complete')}!\n\n"
        f"📤 {t(uid, 'Sent')}: {success_count}\n"
        f"❌ {t(uid, 'Failed')}: {fail_count}\n"
        f"👥 {t(uid, 'Total users')}: {len(users)}"
    )
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "admin_panel"), callback_data="admin_menu")]
    ])
    await message.answer(
        f"✅ {t(uid, 'Broadcast complete')}.\n"
        f"• {t(uid, 'Success')}: {success_count}\n"
        f"• {t(uid, 'Failed')}: {fail_count}",
        reply_markup=kb
    )

# =====================================================
# ADMIN: EXPORT EXCEL
# =====================================================
@router.callback_query(F.data == "admin_export_excel")
async def admin_export_excel(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    await callback.message.edit_text("📊 Generating comprehensive report...")
    
    try:
        users_data = await DatabaseHelper.fetch(
            "SELECT * FROM users ORDER BY registration_date DESC"
        )
        payments_data = await DatabaseHelper.fetch("""
            SELECT p.*, u.full_name, u.phone_number 
            FROM payments p 
            LEFT JOIN users u ON p.user_id = u.user_id 
            ORDER BY p.created_at DESC
        """)
        tickets_data = await DatabaseHelper.fetch("""
            SELECT t.*, tt.name as game_name, u.full_name as assigned_to 
            FROM tickets t 
            LEFT JOIN ticket_types tt ON t.type_id = tt.type_id 
            LEFT JOIN users u ON t.user_id = u.user_id 
            ORDER BY t.ticket_number ASC
        """)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if users_data:
                pd.DataFrame(users_data).to_excel(writer, sheet_name='Users', index=False)
            if payments_data:
                pd.DataFrame(payments_data).to_excel(writer, sheet_name='Payments', index=False)
            if tickets_data:
                pd.DataFrame(tickets_data).to_excel(writer, sheet_name='Tickets', index=False)
        
        output.seek(0)
        
        t = Localization.get_text
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "admin_panel"), callback_data="admin_menu")]
        ])
        
        await callback.message.delete()
        await callback.message.answer_document(
            BufferedInputFile(
                output.getvalue(),
                filename=f"comprehensive_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            ),
            caption=f"📊 Comprehensive System Report\n\n"
                    f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=kb
        )
        await callback.answer("✅ Report generated successfully!")
    except Exception as e:
        logger.error(f"Export Excel error: {e}")
        await callback.message.edit_text(f"❌ Failed to generate report: {str(e)}")
        await callback.answer("❌ Export failed!", show_alert=True)

# =====================================================
# ADMIN: REFUND MANAGEMENT
# =====================================================
@router.callback_query(F.data == "admin_refunds")
async def admin_refund_management(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    
    users_with_balance = await DatabaseHelper.fetch("""
        SELECT u.user_id, u.telegram_id, u.full_name, u.phone_number, u.balance, 
               u.total_spent, 
               (SELECT COUNT(*) FROM tickets WHERE telegram_id = u.telegram_id AND status = 'sold') as ticket_count 
        FROM users u 
        WHERE u.balance > 0 
        ORDER BY u.balance DESC
    """)
    
    pending_refunds = await DatabaseHelper.fetch("""
        SELECT r.refund_id, r.telegram_id, r.phone_number, r.refund_amount, 
               r.refund_reason, r.created_at, u.full_name 
        FROM refunds r 
        JOIN users u ON r.user_id = u.user_id 
        WHERE r.status = 'pending' 
        ORDER BY r.created_at ASC
    """)
    
    completed_refunds = await DatabaseHelper.fetch("""
        SELECT r.refund_id, r.telegram_id, r.phone_number, r.refund_amount, 
               r.refund_reason, r.created_at, r.processed_at, u.full_name 
        FROM refunds r 
        JOIN users u ON r.user_id = u.user_id 
        WHERE r.status = 'completed' 
        ORDER BY r.created_at DESC 
        LIMIT 10
    """)
    
    total_refunded = (await DatabaseHelper.fetch_one(
        "SELECT COALESCE(SUM(refund_amount), 0) FROM refunds WHERE status = 'completed'"
    ))[0] or 0
    
    text = (
        f"🔄 {t(uid, 'Refund Management')}\n\n"
        f"💰 {t(uid, 'Total Refunded')}: {total_refunded:,.2f} ETB\n\n"
        f"─" * 30 + "\n\n"
    )
    
    kb_rows = []
    
    if users_with_balance:
        text += f"👤 {t(uid, 'Users with Positive Balance')} ({t(uid, 'Eligible for Refund')})\n\n"
        for user in users_with_balance[:10]:
            user_id, telegram_id, name, phone, balance, total_spent, ticket_count = user
            text += (
                f"• {name or 'User'} - 📱 {phone}\n"
                f"  💰 {t(uid, 'Balance')}: {balance:,.2f} ETB | 🎫 {t(uid, 'Tickets')}: {ticket_count}\n"
            )
            kb_rows.append([
                InlineKeyboardButton(
                    text=f"💳 {name or 'User'} - {balance:,.2f} ETB",
                    callback_data=f"admin_refund_user_{telegram_id}"
                )
            ])
        kb_rows.append([
            InlineKeyboardButton(
                text=f"📥 {t(uid, 'Process All Positive Balances')}",
                callback_data="admin_refund_all_balances"
            )
        ])
    else:
        text += f"✅ {t(uid, 'No users with positive balance')}.\n"
    
    text += "\n" + "─" * 30 + "\n\n"
    
    if pending_refunds:
        text += f"⏳ {t(uid, 'Pending Refund Requests')}\n\n"
        for refund in pending_refunds[:10]:
            refund_id, telegram_id, phone, amount, reason, created, name = refund
            text += f"• {name or 'User'} - {phone}\n  💰 {amount:,.2f} ETB - 📌 {reason[:30]}...\n"
            kb_rows.append([
                InlineKeyboardButton(
                    text=f"✅ #{refund_id} - {amount:,.2f} ETB",
                    callback_data=f"admin_refund_approve_{refund_id}"
                )
            ])
    else:
        text += f"✅ {t(uid, 'No pending refund requests')}.\n"
    
    text += "\n" + "─" * 30 + "\n\n"
    
    if completed_refunds:
        text += f"✅ {t(uid, 'Completed Refunds')}\n\n"
        for refund in completed_refunds[:5]:
            refund_id, telegram_id, phone, amount, reason, created, processed, name = refund
            text += f"• {name or 'User'} - {amount:,.2f} ETB - {created[:10]}\n"
    
    kb_rows.append([
        InlineKeyboardButton(text=t(uid, "back"), callback_data="admin_menu")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("admin_refund_user_"))
async def admin_refund_user_balance(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    telegram_id = int(callback.data.split("_")[3])
    t = Localization.get_text
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, full_name, phone_number, balance FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    
    if not user or user[3] <= 0:
        await callback.answer(f"❌ {t(uid, 'User has no positive balance')}", show_alert=True)
        return
    
    user_id, name, phone, balance = user
    
    await DatabaseHelper.execute(
        "INSERT INTO refunds (user_id, telegram_id, phone_number, refund_amount, refund_reason, status) VALUES (?, ?, ?, ?, ?, 'completed')",
        (user_id, telegram_id, phone, balance, "Admin refunded positive balance")
    )
    await DatabaseHelper.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    
    try:
        await bot.send_message(
            telegram_id,
            f"💰 {t(uid, 'Refund Processed')}!\n\n"
            f"💵 {t(uid, 'Amount')}: {balance:,.2f} ETB\n"
            f"📌 {t(uid, 'Reason')}: {t(uid, 'Positive balance refunded by admin')}.\n\n"
            f"✅ {t(uid, 'Your balance has been cleared')}."
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    
    await callback.answer(
        f"✅ {t(uid, 'Refunded')} {balance:,.2f} ETB {t(uid, 'to')} {name or 'User'}!",
        show_alert=True
    )
    await admin_refund_management(callback)

@router.callback_query(F.data == "admin_refund_all_balances")
async def admin_refund_all_balances(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    users = await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, phone_number, full_name, balance FROM users WHERE balance > 0"
    )
    
    if not users:
        await callback.answer(f"❌ {t(uid, 'No users with positive balance')}", show_alert=True)
        return
    
    processed, total_refunded = 0, 0
    
    for user in users:
        user_id, telegram_id, phone, name, balance = user
        await DatabaseHelper.execute(
            "INSERT INTO refunds (user_id, telegram_id, phone_number, refund_amount, refund_reason, status) VALUES (?, ?, ?, ?, ?, 'completed')",
            (user_id, telegram_id, phone, balance, "Bulk refund of positive balances")
        )
        await DatabaseHelper.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
        try:
            await bot.send_message(
                telegram_id,
                f"💰 {t(uid, 'Refund Processed')}!\n\n"
                f"💵 {t(uid, 'Amount')}: {balance:,.2f} ETB\n"
                f"📌 {t(uid, 'Reason')}: {t(uid, 'Positive balance refunded')}.\n\n"
                f"✅ {t(uid, 'Your balance has been cleared')}."
            )
        except Exception:
            pass
        processed += 1
        total_refunded += balance
        await asyncio.sleep(0.1)
    
    await callback.answer(
        f"✅ {t(uid, 'Processed')} {processed} {t(uid, 'refunds')}! {t(uid, 'Total')}: {total_refunded:,.2f} ETB",
        show_alert=True
    )
    await admin_refund_management(callback)

@router.callback_query(F.data.startswith("admin_refund_approve_"))
async def admin_approve_refund_request(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    refund_id = int(callback.data.split("_")[3])
    t = Localization.get_text
    
    refund = await DatabaseHelper.fetch_one("""
        SELECT r.*, u.user_id FROM refunds r 
        JOIN users u ON r.user_id = u.user_id 
        WHERE r.refund_id = ? AND r.status = 'pending'
    """, (refund_id,))
    
    if not refund:
        await callback.answer(f"❌ {t(uid, 'Refund not found or already processed')}", show_alert=True)
        return
    
    (rid, user_id, telegram_id, phone, ticket_id, ticket_num, refund_amount, 
     refund_reason, status, created, processed_by, processed_at, u_id) = refund
    
    user_balance = await DatabaseHelper.fetch_one(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    )
    
    if not user_balance or user_balance[0] < refund_amount:
        await callback.answer(f"❌ {t(uid, 'User no longer has sufficient balance')}", show_alert=True)
        return
    
    await DatabaseHelper.execute_transaction([
        (
            "UPDATE refunds SET status = 'completed', processed_by = ?, processed_at = CURRENT_TIMESTAMP WHERE refund_id = ?",
            (uid, refund_id)
        ),
        (
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (refund_amount, user_id)
        )
    ])
    
    try:
        await bot.send_message(
            telegram_id,
            f"💰 {t(uid, 'Refund Approved')}!\n\n"
            f"💵 {t(uid, 'Amount')}: {refund_amount:,.2f} ETB\n"
            f"📌 {t(uid, 'Reason')}: {refund_reason}\n\n"
            f"✅ {t(uid, 'Your refund has been processed')}."
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    
    await callback.answer(f"✅ {t(uid, 'Refund approved')}!", show_alert=True)
    await admin_refund_management(callback)

# =====================================================
# REFUND REQUESTS (USER)
# =====================================================
@router.callback_query(F.data == "request_refund")
async def request_refund(callback: CallbackQuery):
    uid = callback.from_user.id
    t = Localization.get_text
    
    user = await DatabaseHelper.fetch_one(
        "SELECT balance, full_name, phone_number FROM users WHERE telegram_id = ?",
        (uid,)
    )
    
    if not user:
        await callback.answer(f"❌ {t(uid, 'Please register first')}!", show_alert=True)
        return
    
    balance, name, phone = user
    
    if balance <= 0:
        await callback.answer(f"❌ {t(uid, 'You have no positive balance to refund')}!", show_alert=True)
        return
    
    existing = await DatabaseHelper.fetch_one(
        "SELECT refund_id FROM refunds WHERE telegram_id = ? AND status = 'pending'",
        (uid,)
    )
    
    if existing:
        await callback.answer(
            f"⚠️ {t(uid, 'You already have a pending refund request')}!",
            show_alert=True
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Refund Request", callback_data="confirm_refund_request")],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu_callback")]
    ])
    
    await callback.message.edit_text(
        f"💰 {t(uid, 'Request Refund')}\n\n"
        f"👤 {t(uid, 'User')}: {name or 'User'}\n"
        f"📱 {t(uid, 'Phone')}: {phone}\n"
        f"💵 {t(uid, 'Your Current Balance')}: {balance:,.2f} ETB\n\n"
        f"⚠️ {t(uid, 'This will request a refund of your entire positive balance')}.\n"
        f"⏳ {t(uid, 'Admin will review and process your request')}.\n\n"
        f"{t(uid, 'Confirm refund request')}?",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_refund_request")
async def confirm_refund_request(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    t = Localization.get_text
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, balance, phone_number FROM users WHERE telegram_id = ?",
        (uid,)
    )
    
    if not user or user[1] <= 0:
        await callback.answer(f"❌ {t(uid, 'No positive balance to refund')}!", show_alert=True)
        return
    
    user_id, balance, phone = user
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="main_menu_callback")]
    ])
    
    await callback.message.edit_text(
        f"🔄 {t(uid, 'Refund Request')}\n\n"
        f"💰 {t(uid, 'Amount')}: {balance:,.2f} ETB\n\n"
        f"{t(uid, 'Please enter the reason for refund')}:",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await state.update_data(refund_amount=balance, refund_user_id=user_id)
    await state.set_state(RefundStates.waiting_for_reason)
    await callback.answer()

@router.message(RefundStates.waiting_for_reason, F.text)
async def process_refund_with_reason(message: Message, state: FSMContext):
    uid = message.from_user.id
    t = Localization.get_text
    
    data = await state.get_data()
    refund_amount = data.get("refund_amount")
    user_id = data.get("refund_user_id")
    reason = message.text.strip()
    
    if not refund_amount or not user_id:
        await state.clear()
        await message.answer(
            f"❌ {t(uid, 'Invalid request')}",
            reply_markup=KeyboardBuilder.main_menu(uid)
        )
        return
    
    user = await DatabaseHelper.fetch_one(
        "SELECT telegram_id, phone_number, full_name FROM users WHERE user_id = ?",
        (user_id,)
    )
    
    if not user:
        await message.answer(f"❌ {t(uid, 'User not found')}")
        await state.clear()
        return
    
    telegram_id, phone, name = user
    
    await DatabaseHelper.execute(
        "INSERT INTO refunds (user_id, telegram_id, phone_number, refund_amount, refund_reason, status) VALUES (?, ?, ?, ?, ?, 'pending')",
        (user_id, telegram_id, phone, refund_amount, reason)
    )
    await state.clear()
    
    await message.answer(
        f"✅ {t(uid, 'Refund request submitted')}!\n\n"
        f"💰 {t(uid, 'Amount')}: {refund_amount:,.2f} ETB\n"
        f"📌 {t(uid, 'Reason')}: {reason}\n\n"
        f"⏳ {t(uid, 'Admin will review and process your request')}.",
        reply_markup=KeyboardBuilder.main_menu(uid)
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔄 {t(uid, 'New Refund Request')}!\n\n"
                f"👤 {t(uid, 'User')}: {name or 'User'} ({phone})\n"
                f"💰 {t(uid, 'Amount')}: {refund_amount:,.2f} ETB\n"
                f"📌 {t(uid, 'Reason')}: {reason}\n\n"
                f"{t(uid, 'Use')} /admin → {t(uid, 'Refund Management')} {t(uid, 'to process')}."
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

# =====================================================
# ADMIN: CREATE GAME
# =====================================================
@router.callback_query(F.data == "admin_create_game")
async def admin_create_game(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(
        f"🎮 {t(uid, 'Create Game')}\n\nEnter game name (e.g., 'Grand Draw 2026'):",
        reply_markup=kb
    )
    await state.set_state(AdminGameStates.waiting_for_name)
    await callback.answer()

@router.message(AdminGameStates.waiting_for_name, F.text)
async def admin_create_game_name(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    await state.update_data(game_name=message.text.strip())
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"🎮 {t(uid, 'Create Game')}\n\nEnter number of prizes (e.g., 10):",
        reply_markup=kb
    )
    await state.set_state(AdminGameStates.waiting_for_num_prizes)

@router.message(AdminGameStates.waiting_for_num_prizes, F.text)
async def admin_create_game_prizes(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    try:
        num_prizes = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Please enter a valid number.")
        return
    await state.update_data(num_prizes=num_prizes)
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"🎮 {t(uid, 'Create Game')}\n\nEnter prize items (comma separated):\n"
        f"Example: '8,000,000 ETB, 5,000,000 ETB, Car'",
        reply_markup=kb
    )
    await state.set_state(AdminGameStates.waiting_for_prize_item)

@router.message(AdminGameStates.waiting_for_prize_item, F.text)
async def admin_create_game_prize_list(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    prizes = [p.strip() for p in message.text.split(",")]
    await state.update_data(prizes=prizes)
    
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "cancel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"🎮 {t(uid, 'Create Game')}\n\nEnter total number of ticket slots (e.g., 20000):",
        reply_markup=kb
    )
    await state.set_state(AdminGameStates.waiting_for_total_slots)

@router.message(AdminGameStates.waiting_for_total_slots, F.text)
async def admin_create_game_slots(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    try:
        total_slots = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Please enter a valid number.")
        return
    
    data = await state.get_data()
    game_name = data.get("game_name")
    num_prizes = data.get("num_prizes")
    prizes = data.get("prizes")
    price = 3000.0
    
    # Insert ticket type
    cursor = await DatabaseHelper.execute(
        "INSERT INTO ticket_types (name, total_slots, price, is_active) VALUES (?, ?, ?, 1)",
        (game_name, total_slots, price)
    )
    type_id = cursor.lastrowid
    
    # Generate tickets
    tickets_to_insert = []
    for i in range(1, total_slots + 1):
        tickets_to_insert.append((type_id, i, 'available'))
    
    if tickets_to_insert:
        await DatabaseHelper.execute(
            "INSERT INTO tickets (type_id, ticket_number, status) VALUES (?, ?, ?)",
            (tickets_to_insert[0][0], tickets_to_insert[0][1], tickets_to_insert[0][2])
        )
        for ticket in tickets_to_insert[1:]:
            await DatabaseHelper.execute(
                "INSERT INTO tickets (type_id, ticket_number, status) VALUES (?, ?, ?)",
                (ticket[0], ticket[1], ticket[2])
            )
    
    await state.clear()
    t = Localization.get_text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "admin_panel"), callback_data="admin_menu")]
    ])
    
    await message.answer(
        f"✅ Game '{game_name}' created successfully!\n\n"
        f"📊 {t(uid, 'Total Tickets')}: {total_slots}\n"
        f"🏆 {t(uid, 'Prizes')}: {num_prizes}\n"
        f"💰 {t(uid, 'Price')}: {price:,.0f} ETB",
        reply_markup=kb
    )

# =====================================================
# MAIN FUNCTION - FIXED FOR RENDER
# =====================================================

async def main():
    """Main entry point for the bot - Fixed for Render deployment"""
    print("=" * 50)
    print("🚀 Initializing Siket Ekub Bot...")
    print("=" * 50)
    print(f"📞 Support Channel: {SUPPORT_CHANNEL_LINK}")
    print(f"🎟️ Ticket Channel: {TICKET_CHANNEL_LINK}")
    print(f"👤 Admins: {ADMIN_IDS}")
    
    # Patch signal handlers to work in any thread
    patch_signal_handlers()
    
    try:
        await init_db()
        print("✅ Database initialized")
        
        await start_background_tasks()
        print("✅ Background tasks started")
        
        await set_bot_commands(bot)
        print("✅ Bot commands set")
        
        dp.include_router(router)
        await bot.delete_webhook(drop_pending_updates=True)
        
        print("✅ Webhook cleared, starting polling...")
        print("🤖 Bot is running and ready!")
        print("   Press Ctrl+C to stop")
        print("=" * 50)
        
        await dp.start_polling(bot)
        
    except Exception as e:
        print(f"❌ Bot error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        print("🔄 Cleaning up...")
        ThreadPools.shutdown_all()
        print("✅ Cleanup complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
