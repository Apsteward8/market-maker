#!/usr/bin/env python3
"""
ProphetX Market Maker Startup Script
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",  # Fixed: was "main:app", now "app.main:app"
        host="127.0.0.1",
        port=8001,
        reload=True,
        log_level="info"
    )