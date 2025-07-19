# run.py (UPDATED VERSION - FastAPI Compatible)
#!/usr/bin/env python3
"""
Run the FastAPI application with enhanced logging
"""

import uvicorn
import sys
import signal
import atexit

def setup_logging():
    """Initialize enhanced logging for the entire application"""
    try:
        from app.utils.enhanced_logging import initialize_enhanced_logging, cleanup_logging
        
        logging_setup = initialize_enhanced_logging(
            log_dir="logs",
            app_name="market_making"
        )
        
        # Setup cleanup on exit
        atexit.register(cleanup_logging)
        
        # Handle CTRL+C gracefully
        def signal_handler(sig, frame):
            print("\n🛑 Shutting down gracefully...")
            cleanup_logging()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        return logging_setup
        
    except Exception as e:
        print(f"❌ Failed to setup logging: {e}")
        return None

def main():
    """Main application entry point"""
    print("🚀 Starting Market Making Application")
    
    # Initialize enhanced logging FIRST (before importing FastAPI)
    logging_setup = setup_logging()
    
    if logging_setup:
        print("📝 All output will be logged to both terminal and file")
        print(f"📁 Log files location: {logging_setup.log_dir.absolute()}")
    
    try:
        # Import FastAPI app after logging is setup
        from app.main import app
        
        # Start the FastAPI application with minimal logging config
        uvicorn.run(
            app,  # Pass the app object directly instead of string
            host="127.0.0.1",
            port=8001,
            reload=False,  # Keep reload disabled to maintain logging
            log_level="info",
            access_log=True,
            # Don't override logging config - let our system handle it
            log_config=None
        )
    except KeyboardInterrupt:
        print("\n🛑 Received shutdown signal")
    except Exception as e:
        print(f"❌ Application failed to start: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup logging on exit
        if logging_setup:
            cleanup_logging()

if __name__ == "__main__":
    main()