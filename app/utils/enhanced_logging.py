# app/utils/enhanced_logging.py (UPDATED VERSION)
"""
Enhanced Logging Setup - FastAPI/Uvicorn Compatible

This module sets up logging to both terminal and file simultaneously.
Compatible with FastAPI and uvicorn logging systems.
"""

import logging
import sys
import os
from datetime import datetime
from typing import Optional
import threading
from pathlib import Path

class TeeLogger:
    """Custom logger that writes to both file and terminal"""
    
    def __init__(self, log_file_path: str, terminal_stream=None):
        self.log_file_path = log_file_path
        self.terminal_stream = terminal_stream or sys.stdout
        self.file_handle = None
        self.lock = threading.Lock()
        
        # Create log directory if it doesn't exist
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        
        # Open file handle
        self.file_handle = open(log_file_path, 'a', encoding='utf-8')
    
    def write(self, message):
        """Write to both terminal and file"""
        with self.lock:
            # Write to terminal
            self.terminal_stream.write(message)
            self.terminal_stream.flush()
            
            # Write to file with timestamp
            if self.file_handle:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                if message.strip():  # Only add timestamp to non-empty lines
                    self.file_handle.write(f"[{timestamp}] {message}")
                else:
                    self.file_handle.write(message)
                self.file_handle.flush()
    
    def flush(self):
        """Flush both streams"""
        with self.lock:
            self.terminal_stream.flush()
            if self.file_handle:
                self.file_handle.flush()
    
    def close(self):
        """Close file handle"""
        with self.lock:
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None

class FastAPICompatibleLogging:
    """FastAPI-compatible logging setup that doesn't interfere with uvicorn"""
    
    def __init__(self, 
                 log_dir: str = "logs",
                 app_name: str = "market_making"):
        
        self.log_dir = Path(log_dir)
        self.app_name = app_name
        
        # Create logs directory
        self.log_dir.mkdir(exist_ok=True)
        
        # Generate log file names
        self.session_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.main_log_file = self.log_dir / f"{app_name}_{self.session_timestamp}.log"
        self.latest_log_file = self.log_dir / f"{app_name}_latest.log"
        
        # Store original streams
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
        # Initialize loggers
        self.tee_logger = None
        self.setup_logging()
    
    def setup_logging(self):
        """Setup logging system that's compatible with FastAPI/uvicorn"""
        
        # DON'T modify the root logger - this causes conflicts with uvicorn
        # Instead, just setup stdout/stderr redirection
        
        print(f"✅ Enhanced logging initialized")
        print(f"   📁 Log directory: {self.log_dir.absolute()}")
        print(f"   📄 Current session: {self.main_log_file.name}")
        print(f"   🔗 Latest log: {self.latest_log_file.name}")
        
        # Setup stdout redirection to capture print statements
        self.setup_stdout_redirection()
        
        # Create symlink to latest log
        self.create_latest_symlink()
    
    def setup_stdout_redirection(self):
        """Setup stdout redirection to capture print statements"""
        
        # Create TeeLogger for stdout
        self.tee_logger = TeeLogger(
            str(self.latest_log_file), 
            self.original_stdout
        )
        
        # Redirect stdout
        sys.stdout = self.tee_logger
        
        # Also redirect stderr
        self.tee_stderr = TeeLogger(
            str(self.latest_log_file), 
            self.original_stderr
        )
        sys.stderr = self.tee_stderr
    
    def create_latest_symlink(self):
        """Create symlink to latest log file for easy access"""
        try:
            # Remove existing symlink if it exists
            if self.latest_log_file.is_symlink() or self.latest_log_file.exists():
                self.latest_log_file.unlink()
            
            # Create new symlink (or copy on Windows)
            if os.name == 'nt':  # Windows
                import shutil
                shutil.copy2(self.main_log_file, self.latest_log_file)
            else:  # Unix/Linux/Mac
                self.latest_log_file.symlink_to(self.main_log_file.name)
                
        except Exception as e:
            print(f"⚠️  Could not create latest log symlink: {e}")
    
    def get_log_info(self) -> dict:
        """Get information about current logging setup"""
        return {
            "log_directory": str(self.log_dir.absolute()),
            "current_session_file": str(self.main_log_file),
            "latest_log_file": str(self.latest_log_file),
            "session_timestamp": self.session_timestamp,
            "log_files": [str(f) for f in self.log_dir.glob("*.log")]
        }
    
    def cleanup(self):
        """Restore original stdout/stderr and close file handles"""
        try:
            # Restore original streams
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            
            # Close tee loggers
            if self.tee_logger:
                self.tee_logger.close()
            if hasattr(self, 'tee_stderr'):
                self.tee_stderr.close()
                
            print("✅ Logging cleanup completed")
            
        except Exception as e:
            print(f"⚠️  Error during logging cleanup: {e}")

# Global instance
_logging_setup = None

def initialize_enhanced_logging(
    log_dir: str = "logs",
    app_name: str = "market_making"
) -> FastAPICompatibleLogging:
    """Initialize enhanced logging system (FastAPI-compatible)"""
    global _logging_setup
    
    if _logging_setup is None:
        _logging_setup = FastAPICompatibleLogging(
            log_dir=log_dir,
            app_name=app_name
        )
    
    return _logging_setup

def get_logging_info() -> Optional[dict]:
    """Get current logging setup info"""
    global _logging_setup
    return _logging_setup.get_log_info() if _logging_setup else None

def cleanup_logging():
    """Cleanup logging system"""
    global _logging_setup
    if _logging_setup:
        _logging_setup.cleanup()
        _logging_setup = None