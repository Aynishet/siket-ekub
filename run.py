# run.py - Production Launcher for Siket Ekub
import os
import sys
import time
import threading
import asyncio
import signal
import atexit
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

# Global variables for cleanup
bot_thread = None
shutdown_event = threading.Event()

def start_bot():
    """Start the Telegram bot in a separate thread with proper asyncio event loop"""
    print("🤖 Starting Telegram Bot...")
    
    def run_bot():
        try:
            # Import here to avoid circular imports
            from bot import main
            # Run the async main function
            asyncio.run(main())
        except Exception as e:
            print(f"❌ Bot error: {e}")
            import traceback
            traceback.print_exc()
            # Log the error
            os.makedirs("logs", exist_ok=True)
            with open("logs/bot_error.log", "a") as f:
                f.write(f"{datetime.now()}: {e}\n")
                traceback.print_exc(file=f)
    
    # Create and start the thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Bot started!")
    return bot_thread

def start_dashboard():
    """Start the dashboard with Waitress WSGI server"""
    print("🌐 Starting Dashboard...")
    from dashboard_server import app
    from waitress import serve
    # Use the PORT environment variable if available (for Render)
    port = int(os.environ.get('PORT', 8080))
    serve(app, host='0.0.0.0', port=port, threads=4)

def cleanup():
    """Cleanup function for graceful shutdown"""
    print("🛑 Shutting down...")
    if bot_thread and bot_thread.is_alive():
        print("Waiting for bot to finish...")
        # Give the bot a moment to clean up
        time.sleep(1)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\nReceived signal {signum}")
    cleanup()
    sys.exit(0)

def main():
    print("=" * 50)
    print("🚀 Starting Siket Ekub Production Server")
    print("=" * 50)
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
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
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start bot in background thread
    global bot_thread
    bot_thread = start_bot()
    
    # Wait for bot to initialize
    print("⏳ Waiting for bot to initialize...")
    time.sleep(3)
    
    # Start dashboard (this blocks)
    try:
        start_dashboard()
    except KeyboardInterrupt:
        print("\n🛑 Keyboard interrupt received")
    finally:
        cleanup()

if __name__ == "__main__":
    main()
