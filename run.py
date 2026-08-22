# run.py - Production Launcher for Siket Ekub
import os
import sys
import time
import threading
import asyncio
import traceback
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

# Global flag to track bot status
bot_is_ready = False

def start_bot():
    """Start the Telegram bot in a separate thread with proper error logging"""
    print("🤖 Starting Telegram Bot...")
    
    def run_bot():
        global bot_is_ready
        try:
            from bot import main
            print("✅ Bot module imported, running main()...")
            asyncio.run(main())
            bot_is_ready = True
            print("✅ Bot main() completed successfully")
        except Exception as e:
            print("=" * 60)
            print("❌❌❌ BOT CRASHED ❌❌❌")
            print("=" * 60)
            print(f"Error: {e}")
            traceback.print_exc()
            print("=" * 60)
            
            os.makedirs("logs", exist_ok=True)
            with open("logs/bot_crash.log", "w") as f:
                f.write(f"Time: {datetime.now().isoformat()}\n")
                f.write(f"Error: {e}\n")
                traceback.print_exc(file=f)
            bot_is_ready = False
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Bot thread started!")
    return bot_thread

def start_dashboard():
    """Start the dashboard with Waitress WSGI server"""
    print("🌐 Starting Dashboard...")
    from dashboard_server import app
    from waitress import serve
    
    # IMPORTANT: Use PORT environment variable (Render default is 10000)
    port = int(os.environ.get('PORT', 10000))
    print(f"📡 Dashboard binding to port {port}")
    serve(app, host='0.0.0.0', port=port, threads=4)

def main():
    print("=" * 50)
    print("🚀 Starting Siket Ekub Production Server")
    print("=" * 50)
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Working directory: {os.getcwd()}")
    print(f"🐍 Python version: {sys.version}")
    
    # Create required directories
    os.makedirs("logs", exist_ok=True)
    os.makedirs("instance", exist_ok=True)
    
    # Initialize database
    print("📊 Initializing database...")
    try:
        import asyncio
        from database import init_db
        asyncio.run(init_db())
        print("✅ Database initialized")
    except Exception as e:
        print(f"⚠️ Database initialization warning: {e}")
        print("Continuing with existing database...")
    
    # Start bot in background thread
    bot_thread = start_bot()
    
    # Wait a moment for bot to start, then check status
    print("⏳ Waiting for bot to initialize...")
    time.sleep(5)
    
    if bot_is_ready:
        print("✅ Bot is ready and running!")
    else:
        print("⚠️ Bot may not have started correctly. Check logs above for errors.")
        print("   The dashboard will still run, but bot commands won't work.")
    
    # Start dashboard (this blocks and binds to the port)
    print("🚀 Starting dashboard server...")
    try:
        start_dashboard()
    except KeyboardInterrupt:
        print("\n🛑 Keyboard interrupt received")
    except Exception as e:
        print(f"❌ Dashboard error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
