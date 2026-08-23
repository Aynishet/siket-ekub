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
import base64
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
from database import init_db, backup_database, process_refund, DB_NAME, DatabaseHelper

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
    OCR = ThreadPoolExecutor(max_workers=2)
    
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
# LOCALIZATION (FULL - Both English and Amharic)
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
# LANGUAGE SELECTION
# =====================================================

@router.callback_query(F.data.startswith("lang_"))
async def select_language(callback: CallbackQuery, state: FSMContext):
    """User selected language - start registration"""
    uid = callback.from_user.id
    lang = callback.data.split("_")[1]  # "en" or "am"
    
    shared_state.set_language(uid, lang)
    t = Localization.get_text
    
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
# TICKET SELECTION HANDLERS (Complete)
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
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file_info.file_path)
        screenshot_data = base64.b64encode(downloaded.read()).decode('utf-8')
        
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
        raw_text = message.text
        parsed = parse_payment_sms(raw_text)
        amount = parsed.get("amount", 0.0)
        ref_code = parsed.get("reference")
        date = parsed.get("date")
        logger.info(f"SMS parsed - Amount: {amount}, Ref: {ref_code}, Date: {date}")
    
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
# ADMIN COMMANDS AND ALL ADMIN FEATURES
# =====================================================
# All admin features are already in your bot.py:
# - admin_command
# - admin_panel_callback
# - pending_payments
# - match_payment
# - approve_payment
# - reject_payment
# - admin_user_management
# - admin_add_user (with full flow)
# - admin_delete_user (with full flow)
# - admin_list_users
# - admin_buy_for_user (with full flow)
# - admin_manual_ticket
# - support_channels_menu
# - my_tickets_callback
# - show_balance
# - my_tickets_button
# - view_prizes_button
# - toggle_language
# - main_menu_callback
# - menu_buy_callback
# - admin_broadcast
# - admin_export_excel
# - admin_refund_management
# - admin_refund_user_balance
# - admin_refund_all_balances
# - admin_approve_refund_request
# - request_refund
# - confirm_refund_request
# - process_refund_with_reason
# - admin_create_game (with full flow)

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
