#!/usr/bin/env python3
"""
Markets Router
FastAPI endpoints for market making operations
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.models.odds_models import ProcessedEvent, SportKey, MarketType
from app.models.market_models import ManagedEvent, ProphetXMarket, PortfolioSummary
from app.services.odds_api_service import odds_api_service
from app.services.market_maker_service import market_maker_service

router = APIRouter()

@router.post("/start", response_model=Dict[str, Any])
async def start_market_making():
    """
    Start the automated market making system
    
    This begins the core market making loop that will:
    1. Poll Pinnacle odds via The Odds API
    2. Create markets on ProphetX copying those odds
    3. Manage position risk and exposure
    4. Update markets when odds change
    
    **Note**: System respects dry_run_mode setting for safety
    """
    try:
        result = await market_maker_service.start_market_making()
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting market making: {str(e)}")

@router.post("/stop", response_model=Dict[str, Any])
async def stop_market_making():
    """
    Stop the automated market making system
    
    This will:
    - Stop the odds polling loop
    - Cancel all active bets (if possible)
    - Close all markets
    - Generate final statistics
    """
    try:
        result = await market_maker_service.stop_market_making()
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping market making: {str(e)}")

@router.get("/status", response_model=Dict[str, Any])
async def get_market_making_status():
    """
    Get current status of the market making system
    
    Returns comprehensive statistics including:
    - System status (running/stopped)
    - Number of events being managed
    - Total exposure and risk metrics
    - Performance statistics
    - API usage information
    """
    try:
        stats = await market_maker_service.get_system_stats()
        return {
            "success": True,
            "message": "Market making status retrieved",
            "data": stats,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")

@router.get("/events", response_model=List[ManagedEvent])
async def get_managed_events():
    """
    Get all events currently being managed
    
    Returns detailed information about each event including:
    - Event details (teams, start time)
    - Markets being made
    - Current positions and exposure
    - Market status
    """
    try:
        return list(market_maker_service.managed_events.values())
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting managed events: {str(e)}")

@router.get("/events/{event_id}", response_model=ManagedEvent)
async def get_managed_event(event_id: str):
    """
    Get details for a specific managed event
    
    - **event_id**: The unique identifier for the event
    
    Returns comprehensive information about the event including all markets and positions.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        
        return market_maker_service.managed_events[event_id]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting event: {str(e)}")

@router.post("/events/{event_id}/pause", response_model=Dict[str, Any])
async def pause_event_markets(event_id: str):
    """
    Pause market making for a specific event
    
    This will stop creating new bets and updating odds for this event,
    but existing bets will remain active.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        
        managed_event = market_maker_service.managed_events[event_id]
        managed_event.status = "paused"
        
        return {
            "success": True,
            "message": f"Market making paused for {managed_event.display_name}",
            "event_id": event_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error pausing event: {str(e)}")

@router.post("/events/{event_id}/resume", response_model=Dict[str, Any])
async def resume_event_markets(event_id: str):
    """
    Resume market making for a specific event
    
    This will restart odds updates and market making for the event.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        
        managed_event = market_maker_service.managed_events[event_id]
        managed_event.status = "active"
        
        return {
            "success": True,
            "message": f"Market making resumed for {managed_event.display_name}",
            "event_id": event_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resuming event: {str(e)}")

@router.get("/odds/latest", response_model=List[ProcessedEvent])
async def get_latest_odds(
    limit: Optional[int] = Query(30, description="Maximum number of events to return")
):
    """
    Get latest odds from Pinnacle via The Odds API
    
    This fetches fresh odds data without affecting the market making system.
    Useful for manual analysis or testing.
    """
    try:
        events = await odds_api_service.get_events()
        
        # Sort by start time and limit
        events.sort(key=lambda x: x.commence_time)
        if limit:
            events = events[:limit]
        
        return events
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching odds: {str(e)}")

@router.post("/odds/refresh", response_model=Dict[str, Any])
async def refresh_odds_cache():
    """
    Clear odds cache and fetch fresh data
    
    Forces a refresh of cached odds data. The next market making cycle
    will use completely fresh data from The Odds API.
    """
    try:
        odds_api_service.clear_cache()
        
        # Optionally fetch new data immediately
        events = await odds_api_service.get_events()
        
        return {
            "success": True,
            "message": "Odds cache refreshed",
            "events_fetched": len(events),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing odds: {str(e)}")

@router.get("/portfolio", response_model=PortfolioSummary)
async def get_portfolio_summary():
    """
    Get comprehensive portfolio summary
    
    Returns detailed financial and risk metrics across all markets including:
    - Total exposure and liquidity
    - Number of active positions
    - Performance statistics
    - Risk utilization metrics
    """
    try:
        return await market_maker_service.get_portfolio_summary()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting portfolio summary: {str(e)}")

@router.post("/test/create-market", response_model=Dict[str, Any])
async def test_create_market(
    event_id: str = Query(..., description="Event ID to create test market for")
):
    """
    Test market creation for a specific event
    
    Creates a test market without starting the full market making system.
    Useful for debugging and testing market creation logic.
    
    **Note**: Respects dry_run_mode setting
    """
    try:
        # Get latest odds for this event
        events = await odds_api_service.get_events()
        target_event = None
        
        for event in events:
            if event.event_id == event_id:
                target_event = event
                break
        
        if not target_event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found in current odds")
        
        # Simulate market creation process
        if target_event.moneyline:
            print(f"🧪 TEST: Would create moneyline market for {target_event.display_name}")
            print(f"   Outcomes: {[f'{o.name} {o.american_odds:+d}' for o in target_event.moneyline.outcomes]}")
        
        return {
            "success": True,
            "message": f"Test market creation for {target_event.display_name}",
            "event": {
                "event_id": target_event.event_id,
                "display_name": target_event.display_name,
                "commence_time": target_event.commence_time.isoformat(),
                "available_markets": target_event.get_available_markets()
            },
            "dry_run_mode": market_maker_service.settings.dry_run_mode
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing market creation: {str(e)}")

@router.get("/api-usage", response_model=Dict[str, Any])
async def get_api_usage_stats():
    """
    Get The Odds API usage statistics
    
    Returns information about API credit consumption and remaining quota.
    """
    try:
        stats = odds_api_service.get_usage_stats()
        
        # Calculate burn rate and projections
        if stats["total_requests"] > 0:
            avg_credits_per_request = stats["total_credits_used"] / stats["total_requests"]
            monthly_projection = avg_credits_per_request * stats["total_requests"] * 30  # Rough projection
        else:
            avg_credits_per_request = 0
            monthly_projection = 0
        
        return {
            "success": True,
            "message": "API usage statistics",
            "data": {
                **stats,
                "avg_credits_per_request": avg_credits_per_request,
                "monthly_projection": monthly_projection,
                "plan_limit": 15_000_000,  # Assuming 15M plan
                "utilization_percentage": (stats["total_credits_used"] / 15_000_000) * 100
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting API usage: {str(e)}")

@router.post("/config/update", response_model=Dict[str, Any])
async def update_market_making_config(
    max_events: Optional[int] = Query(None, description="Maximum events to track"),
    liquidity_amount: Optional[float] = Query(None, description="Liquidity amount per market side"),
    poll_interval: Optional[int] = Query(None, description="Odds polling interval in seconds")
):
    """
    Update market making configuration
    
    Allows runtime updates to key configuration parameters.
    Changes take effect on the next market making cycle.
    """
    try:
        updates = {}
        
        if max_events is not None:
            if max_events <= 0 or max_events > 100:
                raise HTTPException(status_code=400, detail="max_events must be between 1 and 100")
            market_maker_service.settings.max_events_tracked = max_events
            updates["max_events_tracked"] = max_events
        
        if liquidity_amount is not None:
            if liquidity_amount <= 0:
                raise HTTPException(status_code=400, detail="liquidity_amount must be positive")
            market_maker_service.settings.default_liquidity_amount = liquidity_amount
            updates["default_liquidity_amount"] = liquidity_amount
        
        if poll_interval is not None:
            if poll_interval < 30:
                raise HTTPException(status_code=400, detail="poll_interval must be at least 30 seconds")
            market_maker_service.settings.odds_poll_interval_seconds = poll_interval
            updates["odds_poll_interval_seconds"] = poll_interval
        
        if not updates:
            return {
                "success": False,
                "message": "No configuration updates provided",
                "current_config": market_maker_service.settings.to_dict()
            }
        
        return {
            "success": True,
            "message": "Configuration updated",
            "updates": updates,
            "note": "Changes take effect on next market making cycle"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating configuration: {str(e)}")