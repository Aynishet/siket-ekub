# database.py
import aiosqlite
import os
import logging
import asyncio
from datetime import datetime

# Get the absolute directory of the current script file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'instance', 'siket_ekub.db')

async def init_db():
    """Initialize database with all tables and default data"""
    # Ensure instance folder exists
    os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Enable WAL mode for better concurrency
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        
        # =====================================================
        # TABLE: users
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                phone_number TEXT NOT NULL,
                address TEXT NOT NULL,
                full_name TEXT,
                registration_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                is_blocked BOOLEAN DEFAULT 0,
                language TEXT DEFAULT 'en',
                balance REAL DEFAULT 0.0,
                total_spent REAL DEFAULT 0.0
            )
        """)
        
        # =====================================================
        # TABLE: ticket_types
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_types (
                type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                total_slots INTEGER NOT NULL DEFAULT 20000,
                price DECIMAL(10, 2) NOT NULL DEFAULT 3000.00,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # =====================================================
        # TABLE: tickets
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                ticket_code TEXT NOT NULL UNIQUE,
                ticket_number INTEGER NOT NULL,
                status TEXT DEFAULT 'available' CHECK(status IN ('available', 'pending', 'sold', 'refunded')),
                user_id INTEGER,
                telegram_id INTEGER,
                phone_number TEXT,
                assigned_at DATETIME,
                refunded_at DATETIME,
                refund_reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (type_id) REFERENCES ticket_types(type_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """)
        
        # =====================================================
        # TABLE: payments
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                ticket_id INTEGER NOT NULL,
                ticket_number INTEGER NOT NULL,
                raw_sms TEXT,
                extracted_ref TEXT,
                extracted_amount DECIMAL(10, 2),
                extracted_date TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'refunded')),
                verified_by INTEGER,
                verified_at DATETIME,
                refunded_at DATETIME,
                refund_reason TEXT,
                admin_notes TEXT,
                is_underpayment BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE
            )
        """)
        
        # =====================================================
        # TABLE: prizes
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS prizes (
                prize_id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                prize_position INTEGER,
                prize_name TEXT NOT NULL,
                prize_description TEXT,
                prize_value DECIMAL(10, 2),
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (type_id) REFERENCES ticket_types(type_id) ON DELETE CASCADE
            )
        """)
        
        # =====================================================
        # TABLE: refunds
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS refunds (
                refund_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                ticket_id INTEGER NOT NULL,
                ticket_number INTEGER NOT NULL,
                payment_id INTEGER NOT NULL,
                refund_amount DECIMAL(10, 2) NOT NULL,
                refund_reason TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'failed')),
                processed_by INTEGER,
                processed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                FOREIGN KEY (payment_id) REFERENCES payments(payment_id) ON DELETE CASCADE
            )
        """)
        
        # =====================================================
        # TABLE: winner_history
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS winner_history (
                winner_id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                prize_id INTEGER NOT NULL,
                ticket_id INTEGER NOT NULL,
                ticket_number INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                winning_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                claim_status TEXT DEFAULT 'pending' CHECK(claim_status IN ('pending', 'claimed', 'expired')),
                claimed_at DATETIME,
                notes TEXT,
                FOREIGN KEY (type_id) REFERENCES ticket_types(type_id) ON DELETE CASCADE,
                FOREIGN KEY (prize_id) REFERENCES prizes(prize_id) ON DELETE CASCADE,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # =====================================================
        # TABLE: user_activity
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                activity_details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # =====================================================
        # TABLE: bot_settings
        # =====================================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT,
                setting_type TEXT DEFAULT 'string',
                description TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # =====================================================
        # CREATE INDEXES
        # =====================================================
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone_number)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_telegram ON tickets(telegram_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_ref ON payments(extracted_ref)")
        
        await db.commit()
        
        # =====================================================
        # CHECK AND CREATE DEFAULT DATA (ONLY IF EMPTY)
        # =====================================================
        async with db.execute("SELECT type_id FROM ticket_types LIMIT 1") as cursor:
            existing = await cursor.fetchone()
        
        if not existing:
            print("🎮 Creating default lottery game...")
            
            await db.execute("""
                INSERT INTO ticket_types (name, description, total_slots, price, is_active) 
                VALUES (?, ?, ?, ?, ?)
            """, ("Siket Ekub Main Draw", "Main lottery draw with 10 exciting prizes", 20000, 3000.00, 1))
            
            cursor = await db.execute("SELECT last_insert_rowid()")
            type_id = (await cursor.fetchone())[0]
            
            print(f"🎫 Generating 20,000 tickets for game {type_id}...")
            tickets = [(type_id, f"{type_id}_{i}", i, 'available', None, None, None, None) for i in range(1, 20001)]
            
            batch_size = 1000
            for i in range(0, len(tickets), batch_size):
                batch = tickets[i:i+batch_size]
                await db.executemany(
                    """INSERT INTO tickets 
                       (type_id, ticket_code, ticket_number, status, user_id, telegram_id, phone_number, assigned_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    batch
                )
                print(f"   Generated {min(i+batch_size, 20000)} tickets...")
            
            prizes = [
                (type_id, 1, 'BWD Leopard 3', 'Brand new BWD Leopard 3 car', 4500000.00),
                (type_id, 2, 'Hyundai Bayon', 'Brand new Hyundai Bayon car', 3200000.00),
                (type_id, 3, 'Bole Dema Hop – Shop Space', 'Commercial shop space at Bole Dema Hop', 2000000.00),
                (type_id, 4, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                (type_id, 5, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                (type_id, 6, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                (type_id, 7, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                (type_id, 8, '500,000 ETB Cash', 'Cash prize', 500000.00),
                (type_id, 9, '300,000 ETB Cash', 'Cash prize', 300000.00),
                (type_id, 10, '200,000 ETB Cash', 'Cash prize', 200000.00),
            ]
            
            await db.executemany(
                "INSERT INTO prizes (type_id, prize_position, prize_name, prize_description, prize_value) VALUES (?, ?, ?, ?, ?)",
                prizes
            )
            
            await db.commit()
            print("✅ Default data created successfully with 20,000 tickets!")
        
        print("✅ Database is ready!")

# =====================================================
# BACKUP FUNCTION
# =====================================================
async def backup_database():
    """Create a daily backup of the database"""
    backup_dir = os.path.join(BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"siket_ekub_backup_{timestamp}.db")
    
    try:
        async with aiosqlite.connect(DB_NAME) as src:
            async with aiosqlite.connect(backup_path) as dst:
                await src.backup(dst)
        
        logging.info(f"✅ Database backup created: {backup_path}")
        return True
    except Exception as e:
        logging.error(f"❌ Database backup failed: {e}")
        return False

# =====================================================
# REFUND FUNCTIONS
# =====================================================
async def process_refund(payment_id: int, reason: str = "Refund requested") -> dict:
    """Process a refund for a payment"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT p.payment_id, p.user_id, p.telegram_id, p.phone_number, 
                   p.ticket_id, p.ticket_number, p.extracted_amount,
                   t.status as ticket_status
            FROM payments p
            LEFT JOIN tickets t ON p.ticket_id = t.ticket_id
            WHERE p.payment_id = ? AND p.status = 'approved'
        """, (payment_id,)) as cursor:
            payment = await cursor.fetchone()
            
        if not payment:
            return {"success": False, "error": "Payment not found or not approved"}
        
        payment_id, user_id, telegram_id, phone_number, ticket_id, ticket_number, amount, ticket_status = payment
        
        if ticket_status == 'refunded':
            return {"success": False, "error": "Ticket already refunded"}
        
        async with db.execute("BEGIN EXCLUSIVE"):
            await db.execute("""
                UPDATE payments 
                SET status = 'refunded', 
                    refunded_at = CURRENT_TIMESTAMP,
                    refund_reason = ?
                WHERE payment_id = ?
            """, (reason, payment_id))
            
            await db.execute("""
                UPDATE tickets 
                SET status = 'refunded', 
                    refunded_at = CURRENT_TIMESTAMP,
                    refund_reason = ?
                WHERE ticket_id = ?
            """, (reason, ticket_id))
            
            await db.execute("""
                UPDATE users 
                SET balance = COALESCE(balance, 0) + ?
                WHERE user_id = ?
            """, (amount, user_id))
            
            cursor = await db.execute("""
                INSERT INTO refunds 
                (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
                 payment_id, refund_amount, refund_reason, status, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', CURRENT_TIMESTAMP)
            """, (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
                  payment_id, amount, reason))
            
            refund_id = cursor.lastrowid
            await db.commit()
        
        return {
            "success": True,
            "refund_id": refund_id,
            "amount": amount,
            "ticket_number": ticket_number,
            "message": f"Refund of {amount:,.2f} ETB processed for ticket #{ticket_number}"
        }

# =====================================================
# HELPER FUNCTIONS
# =====================================================
async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            return await cursor.fetchone()

async def get_user_tickets(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT t.ticket_id, t.ticket_code, t.ticket_number, tt.name, t.status, t.assigned_at
            FROM tickets t
            JOIN ticket_types tt ON t.type_id = tt.type_id
            WHERE t.telegram_id = ?
            ORDER BY t.assigned_at DESC
        """, (telegram_id,)) as cursor:
            return await cursor.fetchall()

async def get_pending_payments():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT p.payment_id, p.telegram_id, p.phone_number, p.ticket_number,
                   p.extracted_ref, p.extracted_amount, p.created_at, u.full_name,
                   p.is_underpayment, p.admin_notes
            FROM payments p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at ASC
        """) as cursor:
            return await cursor.fetchall()

async def get_payment_accounts():
    """Get payment account details"""
    return [
        {"name": "CBE", "account": "1000786684491"},
        {"name": "Abyssinia", "account": "264517826"},
        {"name": "Telebirr", "account": "0979774444"}
    ]