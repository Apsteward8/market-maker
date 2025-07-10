#!/usr/bin/env python3
"""
ProphetX Market Maker
Main FastAPI application for automated market making using Pinnacle odds
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from app.core.config import get_settings
from app.routers import markets, positions, events, auth, matching, prophetx

# Global settings
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print("🏗️  ProphetX Market Maker starting up...")
    print(f"📝 Environment: {'SANDBOX' if settings.prophetx_sandbox else 'PRODUCTION'}")
    print(f"🎾 Focus: MLB market making using Pinnacle odds")
    print(f"💰 Liquidity per market: ${settings.default_liquidity_amount}")
    
    # Initialize core services
    from app.services.odds_api_service import odds_api_service
    from app.services.market_maker_service import market_maker_service
    
    # Start background odds polling if enabled
    if settings.auto_start_polling:
        print("🔄 Starting automated odds polling...")
        # Note: In production, this would be handled by a separate scheduler process
        
    yield
    
    # Shutdown
    print("🛑 ProphetX Market Maker shutting down...")
    await market_maker_service.shutdown()

# Create FastAPI app
app = FastAPI(
    title="ProphetX Market Maker",
    description="""
    Automated market making system for ProphetX betting exchange.
    
    ## Strategy
    
    This system implements a market making strategy that:
    1. **Monitors Pinnacle** - Uses The Odds API to get sharp book prices
    2. **Creates Markets** - Places opposing bets on ProphetX to offer liquidity
    3. **Manages Risk** - Tracks positions and exposure across all markets
    4. **Updates Prices** - Continuously adjusts to match Pinnacle movement
    
    ## Markets Covered
    
    * **MLB** - Moneyline, spread, and totals for professional tournaments
    * **Focus** - Pre-game markets only (no live betting)
    * **Liquidity** - Provides consistent liquidity up to event start
    
    ## Core Features
    
    * Real-time odds synchronization with Pinnacle
    * Automated position management and risk controls
    * Market lifecycle management (create → update → close)
    * Comprehensive position and P&L tracking
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(matching.router, prefix="/matching", tags=["Event Matching"])
app.include_router(markets.router, prefix="/markets", tags=["Market Making"])
app.include_router(positions.router, prefix="/positions", tags=["Position Management"])
app.include_router(events.router, prefix="/events", tags=["Event Management"])
# app.include_router(prophetx.router, prefix="/prophetx", tags=["ProphetX"])

@app.get("/", tags=["Health"])
async def root():
    """API health check"""
    return {
        "status": "healthy",
        "service": "ProphetX Market Maker",
        "version": "1.0.0",
        "strategy": "Pinnacle odds replication",
        "environment": "sandbox" if settings.prophetx_sandbox else "production",
        "docs": "/docs"
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check"""
    from app.services.market_maker_service import market_maker_service
    
    stats = await market_maker_service.get_system_stats()
    
    return {
        "status": "healthy",
        "timestamp": "2024-01-01T00:00:00Z",
        "environment": "sandbox" if settings.prophetx_sandbox else "production",
        "statistics": stats,
        "settings": {
            "default_liquidity": settings.default_liquidity_amount,
            "max_events_tracked": settings.max_events_tracked,
            "odds_poll_interval": settings.odds_poll_interval_seconds,
            "focus_sport": "baseball"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8001,  # Different port from scanner project
        reload=True,
        log_level="info"
    )