# run.py - Production Launcher for Siket Ekub
import os
import sys
import subprocess
import time
import threading
import signal
import atexit

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

def start_bot():
    """Start the Telegram bot"""
    print("🤖 Starting Telegram Bot...")
    subprocess.Popen(
        [sys.executable, "bot.py"],
        stdout=open("logs/bot.log", "a"),
        stderr=open("logs/bot_error.log", "a"),
        cwd=PROJECT_DIR
    )
    print("✅ Bot started!")

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
    
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    time.sleep(2)
    start_dashboard()

if __name__ == "__main__":
    main()