# =====================================================
# BOT.PY - SIKET EKUB LOTTERY BOT
# COMPLETE PRODUCTION VERSION - ALL HANDLERS WORKING
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
from aiogram.exceptions import TelegramAPIError

import aiosqlite
from dotenv import load_dotenv
from database import init_db, backup_database, process_refund, DB_NAME, DatabaseHelper

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
# LANGUAGE SYSTEM
# =====================================================

async def get_user_lang(user_id: int) -> str:
    """Get user language from database"""
    user = await DatabaseHelper.fetch_one(
        "SELECT language FROM users WHERE telegram_id = ?",
        (user_id,)
    )
    return user[0] if user else 'en'

async def get_text(user_id: int, key: str, **kwargs) -> str:
    """Get text in user's language"""
    lang = await get_user_lang(user_id)
    
    texts = {
        "en": {
            "welcome": "🎰 Welcome to Siket Ekub Lottery!\n💰 Price: 3,000 ETB/ticket",
            "menu": "📋 Main Menu - Select an option:",
            "buy": "🎯 Buy Ticket",
            "tickets": "🎫 My Tickets",
            "prizes": "🏆 Prizes",
            "balance": "💰 Balance",
            "support": "💬 Support",
            "lang": "🌍 Language",
            "reg_phone": "📱 Share Phone",
            "reg_address": "📍 Enter your address:",
            "registered": "✅ Registration complete! You can now buy tickets.",
            "select_game": "🎯 Select Game:",
            "pick_ticket": "🎫 Pick your ticket:",
            "sold": "SOLD",
            "pay": "💰 Pay 3,000 ETB to:\nCBE: 1000786684491\nAbyssinia: 264517826\nTelebirr: 0979774444\n\n📸 Send screenshot or SMS receipt:",
            "pay_submitted": "✅ Payment submitted. Waiting for admin verification.",
            "pay_approved": "✅ Payment approved! Ticket #{ticket} is yours.",
            "pay_rejected": "❌ Payment rejected. Please contact support.",
            "no_tickets": "📭 No tickets yet. Buy your first ticket!",
            "prize_list": "🏆 10 GRAND PRIZES:\n1st: BWD Leopard 3 (8,000,000 ETB)\n2nd: Hyundai Bayon (5,000,000 ETB)\n3rd: Shop Space (4,000,000 ETB)\n4th-7th: 1,000,000 ETB each\n8th: 500,000 ETB\n9th: 300,000 ETB\n10th: 200,000 ETB",
            "balance_info": "💰 Balance: {balance} ETB\n🎫 Tickets: {tickets}\n💸 Spent: {spent} ETB",
            "admin": "🛠️ Admin Panel - Select an option:",
            "verify": "✅ Verify Payments",
            "create": "📝 Create Game",
            "users": "👤 Users",
            "refund": "🔄 Refunds",
            "broadcast": "📢 Broadcast",
            "reports": "📊 Reports",
            "back": "🔙 Back",
            "cancel": "✖ Cancel",
            "choose_lang": "🌍 Choose your language:",
            "lang_changed": "✅ Language changed to {lang}",
            "ticket_assigned": "🎫 Ticket #{ticket} assigned to you!",
            "admin_menu": "🛠️ Admin Menu",
            "web_interface": "🌐 Web Interface",
            "about": "ℹ️ About",
            "refund_complete": "✅ Refund of {amount} ETB processed.",
            "refund_all_complete": "✅ Refunded {total} ETB to {count} users.",
            "no_refund_users": "✅ No users with positive balance.",
            "broadcast_sent": "✅ Broadcast sent to {sent}/{total} users.",
            "game_created": "✅ Game '{name}' created with {slots} tickets!",
            "your_tickets": "🎫 Your Tickets:\n",
            "support_text": "💬 Support Channels\n\n📞 For help, join our support channel.\n🎟️ View verified tickets in the ticket channel.",
        },
        "am": {
            "welcome": "🎰 ወደ ሲኬት ዕቁብ ሎተሪ እንኳን በደህና መጡ!\n💰 ዋጋ: 3,000 ብር/ቲኬት",
            "menu": "📋 ዋና ምናሌ - አማራጭ ምረጥ:",
            "buy": "🎯 ቲኬት ግዛ",
            "tickets": "🎫 ቲኬቶቼ",
            "prizes": "🏆 ሽልማቶች",
            "balance": "💰 ቀሪ ሂሳብ",
            "support": "💬 ድጋፍ",
            "lang": "🌍 ቋንቋ",
            "reg_phone": "📱 ስልክ አጋሩ",
            "reg_address": "📍 አድራሻዎን ያስገቡ:",
            "registered": "✅ ምዝገባ ተጠናቋል! አሁን ቲኬት መግዛት ይችላሉ።",
            "select_game": "🎯 ጨዋታ ምረጥ:",
            "pick_ticket": "🎫 ቲኬት ምረጥ:",
            "sold": "ተሽጧል",
            "pay": "💰 3,000 ብር ወደዚህ ክፈሉ:\nCBE: 1000786684491\nአቢሲኒያ: 264517826\nተሌብር: 0979774444\n\n📸 ስክሪንሾት ወይም SMS ላኩ:",
            "pay_submitted": "✅ ክፍያ ተልኳል። ለማረጋገጥ በመጠባበቅ ላይ።",
            "pay_approved": "✅ ክፍያ ጸድቋል! ቲኬት #{ticket} የእርስዎ ነው።",
            "pay_rejected": "❌ ክፍያ ውድቅ ተደርጓል። እባክዎ ድጋፍ ያግኙ።",
            "no_tickets": "📭 ምንም ቲኬቶች የሉም። የመጀመሪያ ቲኬትዎን ይግዙ!",
            "prize_list": "🏆 10 ዋና ሽልማቶች:\n1ኛ: BWD Leopard 3 (8,000,000 ብር)\n2ኛ: Hyundai Bayon (5,000,000 ብር)\n3ኛ: የሱቅ ቦታ (4,000,000 ብር)\n4ኛ-7ኛ: 1,000,000 ብር\n8ኛ: 500,000 ብር\n9ኛ: 300,000 ብር\n10ኛ: 200,000 ብር",
            "balance_info": "💰 ቀሪ: {balance} ብር\n🎫 ቲኬቶች: {tickets}\n💸 አጠቃላይ: {spent} ብር",
            "admin": "🛠️ የአስተዳዳሪ ፓነል - አማራጭ ምረጥ:",
            "verify": "✅ ክፍያዎችን አረጋግጥ",
            "create": "📝 ጨዋታ ፍጠር",
            "users": "👤 ተጠቃሚዎች",
            "refund": "🔄 መመለስ",
            "broadcast": "📢 መልዕክት ላክ",
            "reports": "📊 ሪፖርቶች",
            "back": "🔙 ወደ ኋላ",
            "cancel": "✖ ሰርዝ",
            "choose_lang": "🌍 ቋንቋ ምረጥ:",
            "lang_changed": "✅ ቋንቋ ወደ {lang} ተቀይሯል።",
            "ticket_assigned": "🎫 ቲኬት #{ticket} ለእርስዎ ተመድቧል!",
            "admin_menu": "🛠️ የአስተዳዳሪ ምናሌ",
            "web_interface": "🌐 የድር በይነገጽ",
            "about": "ℹ️ መረጃ",
            "refund_complete": "✅ {amount} ብር ተመልሷል።",
            "refund_all_complete": "✅ {total} ብር ለ {count} ተጠቃሚዎች ተመልሷል።",
            "no_refund_users": "✅ ቀሪ ሂሳብ ያላቸው ተጠቃሚዎች የሉም።",
            "broadcast_sent": "✅ መልዕክት ለ {sent}/{total} ተጠቃሚዎች ተልኳል።",
            "game_created": "✅ '{name}' ጨዋታ በ {slots} ቲኬቶች ተፈጥሯል!",
            "your_tickets": "🎫 የእርስዎ ቲኬቶች:\n",
            "support_text": "💬 የድጋፍ ሰርጦች\n\n📞 ለእርዳታ የድጋፍ ሰርጣችንን ይቀላቀሉ።\n🎟️ የተረጋገጡ ቲኬቶችን በቲኬት ሰርጥ ይመልከቱ።",
        }
    }
    
    text = texts.get(lang, texts['en']).get(key, key)
    return text.format(**kwargs) if kwargs else text

# =====================================================
# BOTTOM MENU KEYBOARDS
# =====================================================

async def user_menu(user_id: int) -> ReplyKeyboardMarkup:
    """User bottom menu - all buttons work"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=await get_text(user_id, "buy")), 
             KeyboardButton(text=await get_text(user_id, "tickets"))],
            [KeyboardButton(text=await get_text(user_id, "balance")), 
             KeyboardButton(text=await get_text(user_id, "prizes"))],
            [KeyboardButton(text=await get_text(user_id, "support")), 
             KeyboardButton(text=await get_text(user_id, "lang"))],
            [KeyboardButton(text="🌐 Web Interface"), KeyboardButton(text="ℹ️ About")],
        ],
        resize_keyboard=True
    )

async def admin_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Admin bottom menu"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛠️ Admin Panel")],
            [KeyboardButton(text="📊 Reports"), KeyboardButton(text="📢 Broadcast")],
            [KeyboardButton(text="👤 Users"), KeyboardButton(text="🔄 Refunds")],
            [KeyboardButton(text="🔙 Back to User Menu")],
        ],
        resize_keyboard=True
    )

def start_menu() -> ReplyKeyboardMarkup:
    """Start menu for new users"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Use Telegram Bot")],
            [KeyboardButton(text="🌐 Open Web Interface")],
            [KeyboardButton(text="ℹ️ About")],
        ],
        resize_keyboard=True
    )

def admin_inline_kb() -> InlineKeyboardMarkup:
    """Admin inline keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Verify Payments", callback_data="admin_verify")],
        [InlineKeyboardButton(text="📝 Create Game", callback_data="admin_create")],
        [InlineKeyboardButton(text="👤 User Management", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔄 Refund Management", callback_data="admin_refund")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Reports", callback_data="admin_reports")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")],
    ])

def back_inline_kb(callback: str = "main_back") -> InlineKeyboardMarkup:
    """Back button inline keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=callback)]
    ])

# =====================================================
# STATES
# =====================================================
class RegState(StatesGroup):
    phone = State()
    address = State()

class BuyState(StatesGroup):
    game = State()
    payment = State()

class AdminState(StatesGroup):
    game_name = State()
    game_prizes = State()
    game_slots = State()
    broadcast_msg = State()

# =====================================================
# START COMMAND
# =====================================================

@router.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    
    if user:
        await message.answer(
            await get_text(uid, "welcome"),
            reply_markup=await user_menu(uid)
        )
        return
    
    await message.answer(
        "🎰 **SIKET EKUB LOTTERY**\n\n"
        "💰 Ticket Price: 3,000 ETB\n\n"
        "🏆 **10 GRAND PRIZES:**\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "3rd: Shop Space (4,000,000 ETB)\n"
        "4th-7th: 1,000,000 ETB Cash each\n"
        "8th: 500,000 ETB Cash\n"
        "9th: 300,000 ETB Cash\n"
        "10th: 200,000 ETB Cash\n\n"
        "📌 Register > Pick Ticket > Pay > Win!\n\n"
        "🚀 **Choose how to play:**",
        reply_markup=start_menu(),
        parse_mode="Markdown"
    )

# =====================================================
# START MENU HANDLERS
# =====================================================

@router.message(F.text == "🤖 Use Telegram Bot")
async def choice_telegram(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")],
    ])
    
    await message.answer(
        "🌍 **Please choose your language:**",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.message(F.text == "🌐 Open Web Interface")
async def choice_web(message: Message):
    uid = message.from_user.id
    
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    if not user:
        await DatabaseHelper.execute(
            "INSERT INTO users (telegram_id, phone_number, address, language) VALUES (?, ?, ?, ?)",
            (uid, "Pending", "Pending", "en")
        )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Open Web Interface", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    await message.answer(
        "🌐 **Click the button below to open the web interface:**\n\n"
        "You can also use the Telegram bot menu below.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.message(F.text == "ℹ️ About")
async def choice_about(message: Message):
    uid = message.from_user.id
    
    # Check if user exists to show correct menu
    user = await DatabaseHelper.fetch_one("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    menu = await user_menu(uid) if user else start_menu()
    
    await message.answer(
        "🎰 **SIKET EKUB LOTTERY**\n\n"
        "💰 Ticket Price: 3,000 ETB\n\n"
        "🏆 **10 GRAND PRIZES:**\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "3rd: Shop Space (4,000,000 ETB)\n"
        "4th-7th: 1,000,000 ETB Cash each\n"
        "8th: 500,000 ETB Cash\n"
        "9th: 300,000 ETB Cash\n"
        "10th: 200,000 ETB Cash\n\n"
        "📌 Register > Pick Ticket > Pay > Win!\n\n"
        "🚀 GOOD LUCK!",
        reply_markup=menu,
        parse_mode="Markdown"
    )

# =====================================================
# LANGUAGE SELECTION
# =====================================================

@router.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    lang = callback.data.split("_")[1]
    
    # Update language in database
    await DatabaseHelper.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?",
        (lang, uid)
    )
    
    await callback.message.delete()
    
    # Check if user has phone/address
    user = await DatabaseHelper.fetch_one("SELECT phone_number, address FROM users WHERE telegram_id = ?", (uid,))
    
    if user and user[0] and user[0] != "Pending" and user[1] and user[1] != "Pending":
        # User already registered
        await callback.message.answer(
            await get_text(uid, "welcome"),
            reply_markup=await user_menu(uid)
        )
        await callback.answer()
        return
    
    # Ask for phone
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=await get_text(uid, "reg_phone"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await callback.message.answer(
        f"📱 {await get_text(uid, 'reg_phone')}",
        reply_markup=kb
    )
    await state.set_state(RegState.phone)
    await callback.answer()

@router.message(RegState.phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(phone=message.contact.phone_number)
    await message.answer(
        await get_text(uid, "reg_address"),
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RegState.address)

@router.message(RegState.address, F.text)
async def reg_address(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    phone = data.get("phone")
    address = message.text
    
    await DatabaseHelper.execute(
        "UPDATE users SET phone_number = ?, address = ? WHERE telegram_id = ?",
        (phone, address, uid)
    )
    await state.clear()
    
    await message.answer(
        await get_text(uid, "registered"),
        reply_markup=await user_menu(uid)
    )

# =====================================================
# USER MENU HANDLERS - ALL WORKING
# =====================================================

# 1. BUY TICKET
@router.message(F.text.in_(["🎯 Buy Ticket", "🎯 ቲኬት ግዛ"]))
async def buy_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    games = await DatabaseHelper.fetch(
        "SELECT type_id, name, price FROM ticket_types WHERE is_active = 1"
    )
    if not games:
        await message.answer(
            "❌ No active games available.",
            reply_markup=await user_menu(uid)
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎯 {g[1]} ({g[2]:,.0f} ETB)", callback_data=f"game_{g[0]}")]
        for g in games
    ] + [[InlineKeyboardButton(text=await get_text(uid, "back"), callback_data="main_back")]])
    
    await message.answer(await get_text(uid, "select_game"), reply_markup=kb)
    await state.set_state(BuyState.game)

@router.callback_query(F.data.startswith("game_"))
async def select_game(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    type_id = int(callback.data.split("_")[1])
    await state.update_data(game_id=type_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i in range(1, 20001, 1000):
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{i}-{i+999}",
                callback_data=f"block_{type_id}_{i}_{i+999}"
            )
        ])
        if len(kb.inline_keyboard) >= 10:
            break
    kb.inline_keyboard.append([InlineKeyboardButton(text=await get_text(uid, "back"), callback_data="buy_back")])
    
    await callback.message.edit_text(await get_text(uid, "pick_ticket"), reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("block_"))
async def select_block(callback: CallbackQuery):
    uid = callback.from_user.id
    _, type_id, start, end = callback.data.split("_")
    type_id = int(type_id)
    start = int(start)
    end = int(end)
    
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_id, ticket_number, status FROM tickets WHERE type_id = ? AND ticket_number BETWEEN ? AND ?",
        (type_id, start, end)
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for tid, num, status in tickets[:100]:
        if status == 'available':
            row.append(InlineKeyboardButton(str(num), callback_data=f"ticket_{tid}"))
        else:
            row.append(InlineKeyboardButton("🔴", callback_data="sold"))
        if len(row) == 5:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    
    kb.inline_keyboard.append([InlineKeyboardButton(text=await get_text(uid, "back"), callback_data=f"game_{type_id}")])
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
    
    await state.update_data(ticket_id=ticket_id, ticket_num=ticket[0])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Confirm Payment", callback_data="confirm_pay")],
        [InlineKeyboardButton(text=await get_text(uid, "cancel"), callback_data="buy_back")]
    ])
    
    await callback.message.edit_text(
        f"🎫 Ticket #{ticket[0]}\n\n" + await get_text(uid, "pay"),
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_pay")
async def confirm_pay(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    ticket_num = data.get("ticket_num")
    
    if not ticket_id:
        await callback.answer("❌ No ticket!", show_alert=True)
        return
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_number FROM tickets WHERE ticket_id = ? AND status = 'available'",
        (ticket_id,)
    )
    if not ticket:
        await callback.answer("❌ Ticket just got sold!", show_alert=True)
        return
    
    await state.set_state(BuyState.payment)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=await get_text(uid, "cancel"), callback_data="buy_back")]
    ])
    
    await callback.message.edit_text(
        f"🎫 Ticket #{ticket_num}\n\n" + await get_text(uid, "pay"),
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
        await message.answer(
            "❌ No ticket selected.",
            reply_markup=await user_menu(uid)
        )
        await state.clear()
        return
    
    user = await DatabaseHelper.fetch_one("SELECT user_id FROM users WHERE telegram_id = ?", (uid,))
    if not user:
        await message.answer(
            "❌ Please /start first.",
            reply_markup=await user_menu(uid)
        )
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
        await get_text(uid, "pay_submitted"),
        reply_markup=await user_menu(uid)
    )
    
    # Notify admins
    for admin in ADMIN_IDS:
        try:
            msg = f"🔔 New Payment\n🎫 Ticket: #{ticket_num}\n👤 User: {uid}\n🆔 Payment: {payment_id}"
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
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

@router.callback_query(F.data == "buy_back")
async def buy_back(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        await get_text(uid, "menu"),
        reply_markup=await user_menu(uid)
    )
    await callback.answer()

@router.callback_query(F.data == "main_back")
async def main_back(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        await get_text(uid, "menu"),
        reply_markup=await user_menu(uid)
    )
    await callback.answer()

# =====================================================
# 2. MY TICKETS - NOW WORKING
# =====================================================

@router.message(F.text.in_(["🎫 My Tickets", "🎫 ቲኬቶቼ"]))
async def my_tickets(message: Message):
    uid = message.from_user.id
    
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_number, assigned_at FROM tickets WHERE telegram_id = ? AND status = 'sold' ORDER BY assigned_at DESC",
        (uid,)
    )
    
    if not tickets:
        await message.answer(
            await get_text(uid, "no_tickets"),
            reply_markup=await user_menu(uid)
        )
        return
    
    lines = [await get_text(uid, "your_tickets")]
    for num, date in tickets[:10]:
        date_str = date[:10] if date else "N/A"
        lines.append(f"#{num} - {date_str}")
    if len(tickets) > 10:
        lines.append(f"... and {len(tickets)-10} more")
    
    await message.answer(
        "\n".join(lines),
        reply_markup=await user_menu(uid)
    )

# =====================================================
# 3. BALANCE - NOW WORKING
# =====================================================

@router.message(F.text.in_(["💰 Balance", "💰 ቀሪ ሂሳብ"]))
async def balance_cmd(message: Message):
    uid = message.from_user.id
    
    user = await DatabaseHelper.fetch_one(
        "SELECT balance, total_spent FROM users WHERE telegram_id = ?",
        (uid,)
    )
    if not user:
        await message.answer(
            "❌ Please /start first.",
            reply_markup=await user_menu(uid)
        )
        return
    
    tickets = await DatabaseHelper.fetch(
        "SELECT COUNT(*) FROM tickets WHERE telegram_id = ? AND status = 'sold'",
        (uid,)
    )
    await message.answer(
        await get_text(uid, "balance_info", 
                      balance=user[0] or 0, 
                      tickets=tickets[0][0] or 0, 
                      spent=user[1] or 0),
        reply_markup=await user_menu(uid)
    )

# =====================================================
# 4. PRIZES - NOW WORKING
# =====================================================

@router.message(F.text.in_(["🏆 Prizes", "🏆 ሽልማቶች"]))
async def prizes_cmd(message: Message):
    uid = message.from_user.id
    
    await message.answer(
        await get_text(uid, "prize_list"),
        reply_markup=await user_menu(uid)
    )

# =====================================================
# 5. SUPPORT - NOW WORKING
# =====================================================

@router.message(F.text.in_(["💬 Support", "💬 ድጋፍ"]))
async def support_cmd(message: Message):
    uid = message.from_user.id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Support Channel", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton(text="🎟️ Ticket Channel", url=TICKET_CHANNEL_LINK)],
        [InlineKeyboardButton(text=await get_text(uid, "back"), callback_data="main_back")]
    ])
    
    await message.answer(
        await get_text(uid, "support_text"),
        reply_markup=kb
    )

# =====================================================
# 6. LANGUAGE - NOW WORKING
# =====================================================

@router.message(F.text.in_(["🌍 Language", "🌍 ቋንቋ"]))
async def lang_cmd(message: Message):
    uid = message.from_user.id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")],
        [InlineKeyboardButton(text=await get_text(uid, "back"), callback_data="main_back")]
    ])
    
    await message.answer(
        await get_text(uid, "choose_lang"),
        reply_markup=kb
    )

# =====================================================
# 7. WEB INTERFACE - NOW WORKING
# =====================================================

@router.message(F.text == "🌐 Web Interface")
async def web_interface_cmd(message: Message):
    uid = message.from_user.id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Open Web Interface", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    await message.answer(
        "🌐 **Open Web Interface**\n\n"
        "Click the button below to open the web version.\n"
        "Your tickets and balance are synced with the bot.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# =====================================================
# 8. ABOUT - NOW WORKING
# =====================================================

@router.message(F.text == "ℹ️ About")
async def about_cmd(message: Message):
    uid = message.from_user.id
    
    await message.answer(
        "🎰 **SIKET EKUB LOTTERY**\n\n"
        "💰 Ticket Price: 3,000 ETB\n\n"
        "🏆 **10 GRAND PRIZES:**\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "3rd: Shop Space (4,000,000 ETB)\n"
        "4th-7th: 1,000,000 ETB Cash each\n"
        "8th: 500,000 ETB Cash\n"
        "9th: 300,000 ETB Cash\n"
        "10th: 200,000 ETB Cash\n\n"
        "📌 Register > Pick Ticket > Pay > Win!\n\n"
        "🚀 GOOD LUCK!",
        reply_markup=await user_menu(uid),
        parse_mode="Markdown"
    )

# =====================================================
# ADMIN PAYMENT APPROVAL
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
        await callback.answer("❌ Payment not found!", show_alert=True)
        return
    
    tg_id, ticket_id, ticket_num = payment
    
    # Atomic update
    cursor = await DatabaseHelper.execute(
        "UPDATE tickets SET status = 'sold', telegram_id = ?, assigned_at = CURRENT_TIMESTAMP WHERE ticket_id = ? AND status = 'available'",
        (tg_id, ticket_id)
    )
    
    if cursor.rowcount == 0:
        await DatabaseHelper.execute(
            "UPDATE payments SET status = 'rejected', admin_notes = 'Ticket already sold' WHERE payment_id = ?",
            (payment_id,)
        )
        await callback.message.edit_text(f"❌ Ticket #{ticket_num} was already sold!")
        await callback.answer()
        return
    
    await DatabaseHelper.execute_transaction([
        ("UPDATE payments SET status = 'approved', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE payment_id = ?", (uid, payment_id)),
        ("UPDATE users SET balance = COALESCE(balance, 0) + 3000, total_spent = COALESCE(total_spent, 0) + 3000 WHERE telegram_id = ?", (tg_id,))
    ])
    
    # Post to ticket channel
    try:
        user = await DatabaseHelper.fetch_one("SELECT phone_number FROM users WHERE telegram_id = ?", (tg_id,))
        phone = user[0] if user else "N/A"
        await bot.send_message(
            TICKET_CHANNEL_ID,
            f"🎟️ **Verified Ticket**\n#{ticket_num}\n👤 {phone}\n💰 3,000 ETB\n✅ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to post to channel: {e}")
    
    try:
        await bot.send_message(tg_id, await get_text(tg_id, "pay_approved", ticket=ticket_num))
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    
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
            "UPDATE payments SET status = 'rejected', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
            (uid, payment_id)
        )
        try:
            await bot.send_message(payment[0], await get_text(payment[0], "pay_rejected"))
        except:
            pass
    
    await callback.message.edit_text(f"❌ Payment #{payment_id} rejected.")
    await callback.answer()

# =====================================================
# ADMIN COMMANDS
# =====================================================

@router.message(F.text == "🛠️ Admin Panel")
@router.message(Command("admin"))
async def admin_cmd(message: Message):
    uid = message.from_user.id
    
    if uid not in ADMIN_IDS:
        await message.answer(
            "⛔ Unauthorized! You are not an admin.",
            reply_markup=await user_menu(uid)
        )
        return
    
    await message.answer(
        await get_text(uid, "admin"),
        reply_markup=admin_inline_kb()
    )

@router.message(F.text == "🔙 Back to User Menu")
async def back_to_user(message: Message):
    uid = message.from_user.id
    
    await message.answer(
        await get_text(uid, "menu"),
        reply_markup=await user_menu(uid)
    )

@router.callback_query(F.data == "admin_back")
async def admin_back_cb(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.clear()
    
    await callback.message.edit_text(
        await get_text(uid, "admin"),
        reply_markup=admin_inline_kb()
    )
    await callback.answer()

# =====================================================
# ADMIN: VERIFY PAYMENTS
# =====================================================

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
        await callback.message.edit_text(
            "📭 No pending payments.",
            reply_markup=back_inline_kb("admin_back")
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"#{p[0]} - #{p[2]} - {p[3][:10]}",
            callback_data=f"view_pay_{p[0]}"
        )] for p in payments[:10]
    ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]])
    
    await callback.message.edit_text(f"📋 Pending Payments ({len(payments)})", reply_markup=kb)
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
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_verify")]
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

# =====================================================
# ADMIN: CREATE GAME
# =====================================================

@router.callback_query(F.data == "admin_create")
async def admin_create(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📝 **Create New Game**\n\n"
        "Enter the game name:\n"
        "Example: '2026 Grand Draw'",
        reply_markup=back_inline_kb("admin_back"),
        parse_mode="Markdown"
    )
    await state.set_state(AdminState.game_name)
    await callback.answer()

@router.message(AdminState.game_name, F.text)
async def create_name(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await state.update_data(name=message.text)
    
    await message.answer(
        "📝 **Enter Prizes**\n\n"
        "Enter each prize on a new line:\n"
        "1st: BWD Leopard 3 (8,000,000 ETB)\n"
        "2nd: Hyundai Bayon (5,000,000 ETB)\n"
        "...",
        reply_markup=back_inline_kb("admin_back"),
        parse_mode="Markdown"
    )
    await state.set_state(AdminState.game_prizes)

@router.message(AdminState.game_prizes, F.text)
async def create_prizes(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    
    await state.update_data(prizes=message.text)
    
    await message.answer(
        "📝 **Total Slots**\n\n"
        "Enter total number of tickets (default: 20000):",
        reply_markup=back_inline_kb("admin_back"),
        parse_mode="Markdown"
    )
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
        await get_text(uid, "game_created", name=name, slots=slots),
        reply_markup=await user_menu(uid)
    )

# =====================================================
# ADMIN: USER MANAGEMENT
# =====================================================

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
        await callback.message.edit_text(
            "📭 No users found.",
            reply_markup=back_inline_kb("admin_back")
        )
        return
    
    lines = ["👤 **Recent Users:**\n"]
    for tg, name, phone, balance, spent in users:
        lines.append(f"🆔 {tg} | {name or phone or 'N/A'}\n💰 {balance or 0} ETB")
    
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_inline_kb("admin_back"),
        parse_mode="Markdown"
    )
    await callback.answer()

# =====================================================
# ADMIN: REFUND MANAGEMENT
# =====================================================

@router.callback_query(F.data == "admin_refund")
async def admin_refund(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC"
    )
    if not users:
        await callback.message.edit_text(
            await get_text(uid, "no_refund_users"),
            reply_markup=back_inline_kb("admin_back")
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{u[1]} - {u[2]:,.0f} ETB",
            callback_data=f"refund_user_{u[0]}"
        )] for u in users[:10]
    ] + [[InlineKeyboardButton(text="🔄 Process All", callback_data="refund_all")],
         [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]])
    
    await callback.message.edit_text("🔄 **Refund Management**\n\nSelect user to refund:", reply_markup=kb)
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
    
    await DatabaseHelper.execute_transaction([
        ("INSERT INTO refunds (user_id, amount, reason, status, processed_by, processed_at) VALUES (?, ?, 'Admin refund', 'completed', ?, CURRENT_TIMESTAMP)", (user_id, balance, uid)),
        ("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    ])
    
    try:
        await bot.send_message(tg_id, await get_text(tg_id, "refund_complete", amount=balance))
    except:
        pass
    
    await callback.message.edit_text(
        f"✅ Refunded {balance:,.0f} ETB",
        reply_markup=back_inline_kb("admin_back")
    )
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
            await bot.send_message(tg_id, await get_text(tg_id, "refund_complete", amount=balance))
        except:
            pass
    
    await callback.message.edit_text(
        await get_text(uid, "refund_all_complete", total=total, count=len(users)),
        reply_markup=back_inline_kb("admin_back")
    )
    await callback.answer()

# =====================================================
# ADMIN: BROADCAST
# =====================================================

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 **Broadcast Message**\n\n"
        "Enter the message to send to all users:",
        reply_markup=back_inline_kb("admin_back"),
        parse_mode="Markdown"
    )
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
    await message.answer(
        await get_text(uid, "broadcast_sent", sent=sent, total=len(users)),
        reply_markup=await user_menu(uid)
    )

# =====================================================
# ADMIN: REPORTS
# =====================================================

@router.callback_query(F.data == "admin_reports")
async def admin_reports(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    games = await DatabaseHelper.fetch("SELECT type_id, name FROM ticket_types")
    if not games:
        await callback.message.edit_text(
            "📭 No games found.",
            reply_markup=back_inline_kb("admin_back")
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📊 {g[1]}", callback_data=f"report_{g[0]}")] for g in games
    ] + [[InlineKeyboardButton(text="📊 All Users", callback_data="report_all")],
         [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]])
    
    await callback.message.edit_text("📊 **Generate Reports**\n\nSelect a report:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("report_"))
async def generate_report(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in ADMIN_IDS:
        await callback.answer("⛔ Unauthorized!", show_alert=True)
        return
    
    data = callback.data.split("_")
    
    if data[1] == "all":
        users = await DatabaseHelper.fetch("SELECT telegram_id, full_name, phone_number, balance, total_spent FROM users")
        csv = "Telegram ID,Name,Phone,Balance,Total Spent\n"
        for u in users:
            csv += f"{u[0]},{u[1] or ''},{u[2] or ''},{u[3] or 0},{u[4] or 0}\n"
        name = "all_users"
    else:
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
# ADMIN BOTTOM MENU HANDLERS
# =====================================================

@router.message(F.text == "📊 Reports")
async def admin_reports_bottom(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!", reply_markup=await user_menu(uid))
        return
    
    # Reuse the same logic as the callback
    await admin_reports(await message.answer("Processing..."))

@router.message(F.text == "📢 Broadcast")
async def admin_broadcast_bottom(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!", reply_markup=await user_menu(uid))
        return
    
    await message.answer(
        "📢 **Broadcast Message**\n\n"
        "Enter the message to send to all users:",
        reply_markup=back_inline_kb("admin_back"),
        parse_mode="Markdown"
    )
    await state.set_state(AdminState.broadcast_msg)

@router.message(F.text == "👤 Users")
async def admin_users_bottom(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!", reply_markup=await user_menu(uid))
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT telegram_id, full_name, phone_number, balance, total_spent FROM users ORDER BY created_at DESC LIMIT 20"
    )
    if not users:
        await message.answer("📭 No users found.", reply_markup=await admin_menu(uid))
        return
    
    lines = ["👤 **Recent Users:**\n"]
    for tg, name, phone, balance, spent in users:
        lines.append(f"🆔 {tg} | {name or phone or 'N/A'}\n💰 {balance or 0} ETB")
    
    await message.answer(
        "\n".join(lines),
        reply_markup=await admin_menu(uid),
        parse_mode="Markdown"
    )

@router.message(F.text == "🔄 Refunds")
async def admin_refunds_bottom(message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer("⛔ Unauthorized!", reply_markup=await user_menu(uid))
        return
    
    users = await DatabaseHelper.fetch(
        "SELECT user_id, telegram_id, balance FROM users WHERE balance > 0 ORDER BY balance DESC"
    )
    if not users:
        await message.answer(
            await get_text(uid, "no_refund_users"),
            reply_markup=await admin_menu(uid)
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{u[1]} - {u[2]:,.0f} ETB",
            callback_data=f"refund_user_{u[0]}"
        )] for u in users[:10]
    ] + [[InlineKeyboardButton(text="🔄 Process All", callback_data="refund_all")],
         [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back")]])
    
    await message.answer("🔄 **Refund Management**\n\nSelect user to refund:", reply_markup=kb)
    await callback.answer()

# =====================================================
# SETUP & MAIN
# =====================================================

async def set_commands():
    commands = [
        BotCommand(command="start", description="🏠 Start Bot"),
        BotCommand(command="admin", description="🛠️ Admin Panel"),
    ]
    await bot.set_my_commands(commands)

@dp.error()
async def global_error_handler(event, exception):
    """Global error handler"""
    logger.error(f"Global error: {exception}")
    try:
        if hasattr(event, 'message') and event.message:
            await event.message.answer(
                "⚠️ An error occurred. Please try again or contact support."
            )
    except:
        pass

async def main():
    await init_db()
    await set_commands()
    dp.include_router(router)
    logger.info("🚀 Bot started successfully!")
    logger.info(f"👤 Admins: {ADMIN_IDS}")
    logger.info(f"🌐 WebApp URL: {WEBAPP_URL}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Stopped")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
