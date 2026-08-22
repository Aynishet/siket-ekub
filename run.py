# run.py - Updated version
import os
import sys
import time
import threading
import asyncio
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

def start_bot():
    """Start the Telegram bot in a separate thread with asyncio"""
    print("🤖 Starting Telegram Bot...")
    
    def run_bot():
        try:
            from bot import main
            asyncio.run(main())
        except Exception as e:
            print(f"❌ Bot error: {e}")
            os.makedirs("logs", exist_ok=True)
            with open("logs/bot_error.log", "a") as f:
                f.write(f"{datetime.now()}: {e}\n")
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Bot started!")
    return bot_thread

def start_dashboard():
    """Start the dashboard with Waitress WSGI server"""
    print("🌐 Starting Dashboard...")
    from dashboard_server import app
    from waitress import serve
    serve(app, host='0.0.0.0', port=8080, threads=4)

def main():
    print("=" * 50)
    print("🚀 Starting Siket Ekub Production Server")
    print("=" * 50)
    
    os.makedirs("logs", exist_ok=True)
    os.makedirs("instance", exist_ok=True)
    
    print("📊 Initializing database...")
    import asyncio
    from database import init_db
    asyncio.run(init_db())
    print("✅ Database initialized")
    
    # Start bot in background thread
    bot_thread = start_bot()
    
    # Wait a moment for bot to initialize
    time.sleep(3)
    
    # Start dashboard (this blocks)
    start_dashboard()

if __name__ == "__main__":
    main()
