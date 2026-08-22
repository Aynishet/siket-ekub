# render_webapp.py - Complete Single Server for Render
import os
import sys
import asyncio
import threading
import base64
import io
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file
from waitress import serve
from flask_cors import CORS

# Import bot and database
from bot import main as bot_main, DatabaseHelper
from database import init_db

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

# =====================================================
# WEBAPP ROUTES
# =====================================================

@app.route('/')
def index():
    """Serve the main WebApp"""
    return send_from_directory('.', 'index.html')

@app.route('/assets/<path:path>')
def serve_assets(path):
    """Serve static assets"""
    return send_from_directory('assets', path)

# =====================================================
# API ROUTES - WebApp Calls These
# =====================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/api/user/<int:telegram_id>', methods=['GET'])
async def get_user(telegram_id):
    """Get user data including tickets and payments"""
    user = await DatabaseHelper.fetch_one(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    tickets = await DatabaseHelper.fetch(
        """SELECT t.ticket_id, t.ticket_number, t.status, t.assigned_at, tt.name as game_name
           FROM tickets t
           JOIN ticket_types tt ON t.type_id = tt.type_id
           WHERE t.telegram_id = ? AND t.status = 'sold'
           ORDER BY t.assigned_at DESC""",
        (telegram_id,)
    )
    
    payments = await DatabaseHelper.fetch(
        """SELECT payment_id, ticket_number, extracted_amount as amount, 
                  status, created_at as date
           FROM payments 
           WHERE telegram_id = ?
           ORDER BY created_at DESC
           LIMIT 20""",
        (telegram_id,)
    )
    
    return jsonify({
        'success': True,
        'data': {
            'user_id': user[0],
            'telegram_id': user[1],
            'phone_number': user[2],
            'full_name': user[4],
            'balance': user[9] or 0,
            'total_spent': user[10] or 0,
            'tickets': [{'ticket_id': t[0], 'ticket_number': t[1], 'status': t[2]} for t in tickets],
            'payments': [{'payment_id': p[0], 'ticket_number': p[1], 'amount': p[2], 'status': p[3]} for p in payments]
        }
    })

@app.route('/api/user/create', methods=['POST'])
async def create_user():
    """Create new user"""
    data = request.json
    try:
        await DatabaseHelper.execute(
            """INSERT INTO users (telegram_id, phone_number, address, full_name, language)
               VALUES (?, ?, ?, ?, ?)""",
            (data.get('telegram_id'), data.get('phone_number'),
             data.get('address'), data.get('full_name', 'User'), 'en')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/tickets', methods=['GET'])
async def get_tickets():
    """Get all tickets"""
    tickets = await DatabaseHelper.fetch(
        "SELECT ticket_id, ticket_number, status FROM tickets ORDER BY ticket_number"
    )
    return jsonify({
        'success': True,
        'data': {
            'tickets': [{'ticket_id': t[0], 'ticket_number': t[1], 'status': t[2]} for t in tickets]
        }
    })

@app.route('/api/tickets/assign', methods=['POST'])
async def assign_ticket():
    """Assign tickets to a user"""
    data = request.json
    telegram_id = data.get('telegram_id')
    ticket_ids = data.get('ticket_ids', [])
    
    if not ticket_ids:
        return jsonify({'success': False, 'error': 'No tickets selected'})
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, phone_number FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    if not user:
        return jsonify({'success': False, 'error': 'User not found'})
    
    user_id, phone = user[0], user[1]
    assigned = []
    failed = []
    
    for ticket_id in ticket_ids:
        result = await DatabaseHelper.execute(
            """UPDATE tickets 
               SET status = 'sold', user_id = ?, telegram_id = ?, phone_number = ?, assigned_at = CURRENT_TIMESTAMP 
               WHERE ticket_id = ? AND status = 'available'""",
            (user_id, telegram_id, phone, ticket_id)
        )
        if result:
            assigned.append(ticket_id)
        else:
            failed.append(ticket_id)
    
    return jsonify({
        'success': True,
        'assigned': assigned,
        'failed': failed
    })

@app.route('/api/payments/create', methods=['POST'])
async def create_payment():
    """Create pending payment with screenshot"""
    data = request.json
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, phone_number FROM users WHERE telegram_id = ?", (data.get('telegram_id'),)
    )
    if not user:
        return jsonify({'success': False, 'error': 'User not found'})
    
    ticket = await DatabaseHelper.fetch_one(
        "SELECT ticket_number FROM tickets WHERE ticket_id = ?", (data.get('ticket_id'),)
    )
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'})
    
    cursor = await DatabaseHelper.execute(
        """INSERT INTO payments 
           (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
            raw_sms, extracted_ref, extracted_amount, extracted_date, status, screenshot_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (user[0], data.get('telegram_id'), user[1],
         data.get('ticket_id'), ticket[0],
         data.get('raw_sms', ''), data.get('extracted_ref', ''),
         data.get('extracted_amount', 0), datetime.now().isoformat(),
         data.get('screenshot_data', ''))
    )
    
    return jsonify({'success': True, 'payment_id': cursor.lastrowid})

@app.route('/api/payment_accounts', methods=['GET'])
async def get_payment_accounts():
    """Get payment accounts"""
    accounts = [
        {"name": "CBE", "account": "1000786684491"},
        {"name": "Abyssinia", "account": "264517826"},
        {"name": "Telebirr", "account": "0979774444"}
    ]
    return jsonify({'success': True, 'data': accounts})

@app.route('/api/prizes', methods=['GET'])
async def get_prizes():
    """Get all prizes"""
    prizes = await DatabaseHelper.fetch(
        "SELECT prize_position, prize_name, prize_description, prize_value FROM prizes WHERE is_active = 1 ORDER BY prize_position"
    )
    return jsonify({
        'success': True,
        'data': [{'position': p[0], 'name': p[1], 'description': p[2], 'value': p[3]} for p in prizes]
    })

@app.route('/api/refund_request', methods=['POST'])
async def refund_request():
    """Request refund"""
    data = request.json
    telegram_id = data.get('telegram_id')
    reason = data.get('reason', '')
    
    user = await DatabaseHelper.fetch_one(
        "SELECT user_id, balance FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    if not user or user[1] <= 0:
        return jsonify({'success': False, 'error': 'No balance to refund'})
    
    await DatabaseHelper.execute(
        """INSERT INTO refunds (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
            payment_id, refund_amount, refund_reason, status)
           SELECT user_id, telegram_id, phone_number, ticket_id, ticket_number,
                  payment_id, extracted_amount, ?, 'pending'
           FROM payments 
           WHERE telegram_id = ? AND status = 'approved' AND extracted_amount <= ?
           ORDER BY created_at DESC LIMIT 1""",
        (reason, telegram_id, user[1])
    )
    return jsonify({'success': True, 'message': 'Refund request submitted'})

# =====================================================
# START BOT IN BACKGROUND THREAD
# =====================================================

def start_bot():
    """Start the Telegram bot in a background thread"""
    print("🤖 Starting Telegram Bot...")
    
    def run_bot():
        try:
            asyncio.run(bot_main())
        except Exception as e:
            print(f"❌ Bot error: {e}")
            import traceback
            traceback.print_exc()
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Bot thread started!")

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Starting Siket Ekub Complete Server (NO OCR)")
    print("=" * 50)
    print("📊 Initializing database...")
    
    # Initialize database
    asyncio.run(init_db())
    print("✅ Database initialized")
    
    # Start bot in background
    start_bot()
    
    # Start web server
    port = int(os.environ.get('PORT', 10000))
    print(f"📍 WebApp: https://siket-ekub-webapp.onrender.com")
    print("=" * 50)
    serve(app, host='0.0.0.0', port=port, threads=4)
