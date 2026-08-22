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

def start_bot():
    """Start the Telegram bot in a separate thread"""
    print("🤖 Starting Telegram Bot...")
    
    def run_bot():
        try:
            from bot import main
            print("✅ Bot module imported, running main()...")
            asyncio.run(main())
            print("✅ Bot main() completed successfully")
        except Exception as e:
            print("=" * 60)
            print("❌❌❌ BOT CRASHED ❌❌❌")
            print("=" * 60)
            print(f"Error: {e}")
            traceback.print_exc()
            print("=" * 60)
            
            # Write to log file
            os.makedirs("logs", exist_ok=True)
            with open("logs/bot_crash.log", "w") as f:
                f.write(f"Time: {datetime.now().isoformat()}\n")
                f.write(f"Error: {e}\n")
                traceback.print_exc(file=f)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Bot thread started!")
    return bot_thread

def start_dashboard():
    """Start the dashboard with Waitress WSGI server"""
    print("🌐 Starting Dashboard...")
    try:
        from dashboard_server import app
        from waitress import serve
        
        port = int(os.environ.get('PORT', 10000))
        print(f"📡 Dashboard binding to port {port}")
        serve(app, host='0.0.0.0', port=port, threads=4)
    except Exception as e:
        print(f"❌ Dashboard failed to start: {e}")
        traceback.print_exc()
        # Keep the process alive so Render doesn't restart
        while True:
            time.sleep(60)

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
    
    # Start bot in background thread (even if it fails, we continue)
    start_bot()
    
    # Give bot a moment to try starting
    time.sleep(2)
    
    # ALWAYS start dashboard - this binds to the port
    print("🚀 Starting dashboard server...")
    start_dashboard()

if __name__ == "__main__":
    main()
