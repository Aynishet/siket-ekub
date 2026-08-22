# run.py - Production Launcher for Siket Ekub
import os
import sys
import time
import threading
import asyncio
import signal
import traceback
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

# =====================================================
# RUN DASHBOARD IN BACKGROUND THREAD
# =====================================================

def start_dashboard():
    """Start the dashboard in a background thread"""
    print("🌐 Starting Dashboard...")
    
    def run_dashboard():
        try:
            from dashboard_server import app
            from waitress import serve
            
            port = int(os.environ.get('PORT', 10000))
            print(f"📡 Dashboard binding to port {port}")
            serve(app, host='0.0.0.0', port=port, threads=4)
        except Exception as e:
            print(f"❌ Dashboard failed to start: {e}")
            traceback.print_exc()
            while True:
                time.sleep(60)
    
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    print("✅ Dashboard thread started!")
    return dashboard_thread

# =====================================================
# RUN BOT IN MAIN THREAD
# =====================================================

def start_bot():
    """Start the Telegram bot in the main thread"""
    print("🤖 Starting Telegram Bot...")
    
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
        
        os.makedirs("logs", exist_ok=True)
        with open("logs/bot_crash.log", "w") as f:
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write(f"Error: {e}\n")
            traceback.print_exc(file=f)

# =====================================================
# MAIN
# =====================================================

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
    
    # Start dashboard in background thread
    dashboard_thread = start_dashboard()
    
    # Give dashboard a moment to start
    time.sleep(2)
    
    # Run bot in main thread (this blocks)
    start_bot()

if __name__ == "__main__":
    main()
