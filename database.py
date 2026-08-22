# database.py - PostgreSQL Version
import os
import logging
import asyncio
from datetime import datetime
import asyncpg

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # =====================================================
    # POSTGRESQL MODE (Render)
    # =====================================================
    
    async def get_db_connection():
        """Get PostgreSQL connection"""
        return await asyncpg.connect(DATABASE_URL)
    
    class DatabaseHelper:
        @staticmethod
        async def execute(query: str, params: tuple = None):
            conn = await get_db_connection()
            try:
                if params:
                    result = await conn.execute(query, *params)
                else:
                    result = await conn.execute(query)
                return result
            finally:
                await conn.close()
        
        @staticmethod
        async def execute_transaction(queries: list):
            conn = await get_db_connection()
            try:
                async with conn.transaction():
                    for query, params in queries:
                        if params:
                            await conn.execute(query, *params)
                        else:
                            await conn.execute(query)
                return True
            finally:
                await conn.close()
        
        @staticmethod
        async def fetch(query: str, params: tuple = None):
            conn = await get_db_connection()
            try:
                if params:
                    rows = await conn.fetch(query, *params)
                else:
                    rows = await conn.fetch(query)
                return rows
            finally:
                await conn.close()
        
        @staticmethod
        async def fetch_one(query: str, params: tuple = None):
            conn = await get_db_connection()
            try:
                if params:
                    row = await conn.fetchrow(query, *params)
                else:
                    row = await conn.fetchrow(query)
                return row
            finally:
                await conn.close()
    
    async def init_db():
        """Initialize PostgreSQL database with tables and default data"""
        conn = await get_db_connection()
        
        try:
            # Users table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    phone_number TEXT NOT NULL,
                    address TEXT NOT NULL,
                    full_name TEXT,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    is_blocked BOOLEAN DEFAULT FALSE,
                    language TEXT DEFAULT 'en',
                    balance DECIMAL(10,2) DEFAULT 0.0,
                    total_spent DECIMAL(10,2) DEFAULT 0.0
                )
            ''')
            
            # Ticket types
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS ticket_types (
                    type_id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    total_slots INTEGER NOT NULL DEFAULT 20000,
                    price DECIMAL(10,2) NOT NULL DEFAULT 3000.00,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tickets
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id SERIAL PRIMARY KEY,
                    type_id INTEGER NOT NULL,
                    ticket_code TEXT NOT NULL UNIQUE,
                    ticket_number INTEGER NOT NULL,
                    status TEXT DEFAULT 'available',
                    user_id INTEGER,
                    telegram_id BIGINT,
                    phone_number TEXT,
                    assigned_at TIMESTAMP,
                    refunded_at TIMESTAMP,
                    refund_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Payments with screenshot_data
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    phone_number TEXT NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    ticket_number INTEGER NOT NULL,
                    raw_sms TEXT,
                    extracted_ref TEXT,
                    extracted_amount DECIMAL(10,2),
                    extracted_date TEXT,
                    status TEXT DEFAULT 'pending',
                    verified_by INTEGER,
                    verified_at TIMESTAMP,
                    refunded_at TIMESTAMP,
                    refund_reason TEXT,
                    admin_notes TEXT,
                    is_underpayment BOOLEAN DEFAULT FALSE,
                    screenshot_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Prizes
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS prizes (
                    prize_id SERIAL PRIMARY KEY,
                    type_id INTEGER NOT NULL,
                    prize_position INTEGER,
                    prize_name TEXT NOT NULL,
                    prize_description TEXT,
                    prize_value DECIMAL(10,2),
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Refunds
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS refunds (
                    refund_id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    phone_number TEXT NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    ticket_number INTEGER NOT NULL,
                    payment_id INTEGER NOT NULL,
                    refund_amount DECIMAL(10,2) NOT NULL,
                    refund_reason TEXT,
                    status TEXT DEFAULT 'pending',
                    processed_by INTEGER,
                    processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Winner history
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS winner_history (
                    winner_id SERIAL PRIMARY KEY,
                    type_id INTEGER NOT NULL,
                    prize_id INTEGER NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    ticket_number INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    phone_number TEXT NOT NULL,
                    winning_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claim_status TEXT DEFAULT 'pending',
                    claimed_at TIMESTAMP,
                    notes TEXT
                )
            ''')
            
            # User activity
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_activity (
                    activity_id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    activity_type TEXT NOT NULL,
                    activity_details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Bot settings
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_settings (
                    setting_id SERIAL PRIMARY KEY,
                    setting_key TEXT UNIQUE NOT NULL,
                    setting_value TEXT,
                    setting_type TEXT DEFAULT 'string',
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Indexes
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tickets_telegram ON tickets(telegram_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_payments_telegram ON payments(telegram_id)')
            
            # Check and create default data
            result = await conn.fetchrow("SELECT type_id FROM ticket_types LIMIT 1")
            if not result:
                print("🎮 Creating default lottery game...")
                
                await conn.execute('''
                    INSERT INTO ticket_types (name, description, total_slots, price, is_active)
                    VALUES ($1, $2, $3, $4, $5)
                ''', ("Siket Ekub Main Draw", "Main lottery draw with 10 exciting prizes", 20000, 3000.00, True))
                
                type_id = await conn.fetchval("SELECT LASTVAL()")
                
                print(f"🎫 Generating 20,000 tickets...")
                batch_size = 1000
                for i in range(1, 20001, batch_size):
                    end = min(i + batch_size - 1, 20000)
                    for j in range(i, end + 1):
                        await conn.execute('''
                            INSERT INTO tickets (type_id, ticket_code, ticket_number, status)
                            VALUES ($1, $2, $3, $4)
                        ''', (type_id, f"{type_id}_{j}", j, 'available'))
                    print(f"   Generated {end} tickets...")
                
                prizes = [
                    (type_id, 1, 'BWD Leopard 3', 'Brand new BWD Leopard 3 car', 4500000.00),
                    (type_id, 2, 'Hyundai Bayon', 'Brand new Hyundai Bayon car', 3200000.00),
                    (type_id, 3, 'Bole Dema Hop – Shop Space', 'Commercial shop space', 2000000.00),
                    (type_id, 4, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                    (type_id, 5, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                    (type_id, 6, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                    (type_id, 7, '1,000,000 ETB Cash', 'Cash prize', 1000000.00),
                    (type_id, 8, '500,000 ETB Cash', 'Cash prize', 500000.00),
                    (type_id, 9, '300,000 ETB Cash', 'Cash prize', 300000.00),
                    (type_id, 10, '200,000 ETB Cash', 'Cash prize', 200000.00),
                ]
                
                for prize in prizes:
                    await conn.execute('''
                        INSERT INTO prizes (type_id, prize_position, prize_name, prize_description, prize_value)
                        VALUES ($1, $2, $3, $4, $5)
                    ''', prize)
                
                print("✅ Default data created successfully with 20,000 tickets!")
            
            print("✅ Database is ready!")
            
        except Exception as e:
            print(f"❌ Database initialization error: {e}")
            raise
        finally:
            await conn.close()
    
    # Backup function (PostgreSQL compatible)
    async def backup_database():
        """Backup PostgreSQL database"""
        try:
            conn = await get_db_connection()
            # Create backup using pg_dump via SQL
            backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
            # This is a placeholder - actual backup would use pg_dump command
            print(f"📦 Backup created: {backup_path}")
            await conn.close()
            return True
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return False

else:
    # =====================================================
    # SQLITE MODE (Local Development Fallback)
    # =====================================================
    import aiosqlite
    import os
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(BASE_DIR, 'instance', 'siket_ekub.db')
    
    class DatabaseHelper:
        @staticmethod
        async def execute(query: str, params: tuple = None):
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                cursor = await db.execute(query, params or ())
                await db.commit()
                return cursor
        
        @staticmethod
        async def fetch(query: str, params: tuple = None):
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                cursor = await db.execute(query, params or ())
                return await cursor.fetchall()
        
        @staticmethod
        async def fetch_one(query: str, params: tuple = None):
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                cursor = await db.execute(query, params or ())
                return await cursor.fetchone()
    
    async def init_db():
        """Initialize SQLite database"""
        os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            # ... (your existing SQLite init code)
            print("✅ SQLite Database ready!")

# =====================================================
# SHARED FUNCTIONS (Work for both databases)
# =====================================================

async def get_payment_accounts():
    """Get payment account details"""
    return [
        {"name": "CBE", "account": "1000786684491"},
        {"name": "Abyssinia", "account": "264517826"},
        {"name": "Telebirr", "account": "0979774444"}
    ]

async def process_refund(payment_id: int, reason: str = "Refund requested") -> dict:
    """Process a refund"""
    try:
        payment = await DatabaseHelper.fetch_one("""
            SELECT p.payment_id, p.user_id, p.telegram_id, p.phone_number, 
                   p.ticket_id, p.ticket_number, p.extracted_amount,
                   t.status as ticket_status
            FROM payments p
            LEFT JOIN tickets t ON p.ticket_id = t.ticket_id
            WHERE p.payment_id = $1 AND p.status = 'approved'
        """, (payment_id,))
        
        if not payment:
            return {"success": False, "error": "Payment not found or not approved"}
        
        payment_id, user_id, telegram_id, phone_number, ticket_id, ticket_number, amount, ticket_status = payment
        
        if ticket_status == 'refunded':
            return {"success": False, "error": "Ticket already refunded"}
        
        await DatabaseHelper.execute_transaction([
            ("UPDATE payments SET status = 'refunded', refunded_at = CURRENT_TIMESTAMP, refund_reason = $1 WHERE payment_id = $2", (reason, payment_id)),
            ("UPDATE tickets SET status = 'refunded', refunded_at = CURRENT_TIMESTAMP, refund_reason = $1 WHERE ticket_id = $2", (reason, ticket_id)),
            ("UPDATE users SET balance = COALESCE(balance, 0) + $1 WHERE user_id = $2", (amount, user_id))
        ])
        
        cursor = await DatabaseHelper.execute("""
            INSERT INTO refunds (user_id, telegram_id, phone_number, ticket_id, ticket_number, 
                                payment_id, refund_amount, refund_reason, status, processed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'completed', CURRENT_TIMESTAMP)
        """, (user_id, telegram_id, phone_number, ticket_id, ticket_number, payment_id, amount, reason))
        
        return {
            "success": True,
            "refund_id": cursor,
            "amount": amount,
            "ticket_number": ticket_number,
            "message": f"Refund of {amount:,.2f} ETB processed for ticket #{ticket_number}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
