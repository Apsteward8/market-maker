#!/usr/bin/env python3
"""
Markets Router - UPDATED
FastAPI endpoints for market making operations with incremental betting support
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Optional, Dict, Any
from datetime import datetime
import time

from app.models.odds_models import ProcessedEvent, SportKey, MarketType
from app.models.market_models import ManagedEvent, ProphetXMarket, PortfolioSummary
from app.services.odds_api_service import odds_api_service
from app.services.market_maker_service import market_maker_service

router = APIRouter()

@router.post("/start", response_model=Dict[str, Any])
async def start_market_making():
    """
    Start the automated market making system with exact Pinnacle replication
    
    This begins the core market making loop that will:
    1. Poll Pinnacle odds via The Odds API  
    2. Create markets on ProphetX copying those odds EXACTLY (no improvement)
    3. Use incremental betting with arbitrage position sizing
    4. Manage position risk and exposure with 5-minute fill wait periods
    5. Update markets when odds change
    
    **New Strategy**: Exact Pinnacle replication with incremental liquidity
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
    - Generate final statistics including incremental betting performance
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
    - Incremental betting status (lines in wait periods, position counts)
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

# NEW INCREMENTAL BETTING ENDPOINTS

@router.get("/positions", response_model=Dict[str, Any])
async def get_current_positions():
    """
    Get current positions across all lines with incremental betting details
    
    Shows:
    - Total stake per line
    - Number of bets per line
    - Lines currently in wait periods
    - Position limits and utilization
    """
    try:
        positions_data = {
            "total_lines": len(market_maker_service.position_tracker.line_positions),
            "total_stake_across_all_lines": 0.0,
            "lines_detail": {},
            "wait_periods": {},
            "summary": {
                "lines_with_positions": 0,
                "lines_in_wait_period": 0,
                "total_bets_placed": 0
            }
        }
        
        # Get position details
        for line_id, position_info in market_maker_service.position_tracker.line_positions.items():
            total_stake = position_info['total_stake']
            positions_data["total_stake_across_all_lines"] += total_stake
            positions_data["summary"]["lines_with_positions"] += 1
            positions_data["summary"]["total_bets_placed"] += len(position_info['bets'])
            
            # Check if in wait period
            from app.services.market_making_strategy import market_making_strategy
            can_add_liquidity = market_making_strategy.betting_manager.can_add_liquidity(line_id)
            if not can_add_liquidity:
                positions_data["summary"]["lines_in_wait_period"] += 1
                wait_remaining = (market_making_strategy.betting_manager.fill_wait_period - 
                                (time.time() - market_making_strategy.betting_manager.last_fill_time.get(line_id, 0)))
                positions_data["wait_periods"][line_id] = {
                    "wait_remaining_seconds": max(0, wait_remaining),
                    "can_add_liquidity": False
                }
            
            positions_data["lines_detail"][line_id] = {
                "total_stake": total_stake,
                "number_of_bets": len(position_info['bets']),
                "last_updated": datetime.fromtimestamp(position_info['last_updated']).isoformat(),
                "can_add_liquidity": can_add_liquidity,
                "bets": position_info['bets']
            }
        
        return {
            "success": True,
            "message": f"Current positions across {positions_data['total_lines']} lines",
            "data": positions_data,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting positions: {str(e)}")

@router.post("/simulate-fill", response_model=Dict[str, Any])
async def simulate_bet_fill(
    bet_id: str = Query(..., description="External bet ID to simulate fill for"),
    fill_amount: float = Query(..., description="Amount that got filled/matched")
):
    """
    Simulate a bet getting filled/matched - for testing incremental betting
    
    This endpoint simulates what happens when one of our bets gets matched on ProphetX:
    - Records the fill in position tracking
    - Starts the 5-minute wait period for that line
    - Updates bet status to matched
    
    **Use for testing**: In production, this would be triggered by ProphetX API callbacks
    """
    try:
        success = await market_maker_service.simulate_bet_fill(bet_id, fill_amount)
        
        if success:
            return {
                "success": True,
                "message": f"Simulated fill: {bet_id} for ${fill_amount:.2f}",
                "data": {
                    "bet_id": bet_id,
                    "fill_amount": fill_amount,
                    "note": "5-minute wait period started for this line",
                    "next_action": "System will wait 5 minutes before adding more liquidity to this line"
                }
            }
        else:
            return {
                "success": False,
                "message": f"Bet {bet_id} not found or already filled"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error simulating fill: {str(e)}")

@router.post("/clear-wait-period", response_model=Dict[str, Any])
async def clear_wait_period(
    line_id: str = Query(..., description="Line ID to clear wait period for")
):
    """
    Manually clear wait period for a specific line
    
    Allows immediate addition of more liquidity to a line that's currently
    in a wait period. Useful when odds change significantly or for manual management.
    """
    try:
        from app.services.market_making_strategy import market_making_strategy
        market_making_strategy.betting_manager.clear_wait_period(line_id)
        
        return {
            "success": True,
            "message": f"Wait period cleared for line {line_id}",
            "data": {
                "line_id": line_id,
                "note": "Can now add liquidity immediately to this line"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing wait period: {str(e)}")

@router.get("/strategy-info", response_model=Dict[str, Any])
async def get_strategy_info():
    """
    Get current strategy configuration and settings
    
    Shows the key parameters for the exact Pinnacle replication strategy:
    - Commission rate (3%)
    - Position sizing limits 
    - Incremental betting amounts
    - Wait period duration
    """
    try:
        from app.services.market_making_strategy import market_making_strategy
        
        strategy_info = {
            "strategy_type": "Exact Pinnacle Replication with Arbitrage Position Sizing",
            "commission_rate": market_making_strategy.commission_rate,
            "position_limits": {
                "max_plus_bet": market_making_strategy.max_plus_bet,
                "base_plus_bet": market_making_strategy.base_plus_bet,
                "position_multiplier": market_making_strategy.position_multiplier
            },
            "incremental_betting": {
                "fill_wait_period_seconds": market_making_strategy.betting_manager.fill_wait_period,
                "increment_plus": market_making_strategy.base_plus_bet,
                "increment_minus": "Calculated based on arbitrage (varies per market)"
            },
            "odds_improvement": "NONE - Copy Pinnacle exactly",
            "risk_management": {
                "max_exposure_per_event": market_maker_service.settings.max_exposure_per_event,
                "max_exposure_total": market_maker_service.settings.max_exposure_total,
                "unbalanced_positions": "Allowed - considered +EV bets"
            }
        }
        
        return {
            "success": True,
            "message": "Current strategy configuration",
            "data": strategy_info
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting strategy info: {str(e)}")

@router.get("/events", response_model=List[ManagedEvent])
async def get_managed_events():
    """
    Get all events currently being managed with incremental betting details
    
    Returns detailed information about each event including:
    - Event details (teams, start time)
    - Markets being made
    - Current positions and exposure
    - Market status
    - Incremental betting activity
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
    but existing bets will remain active. Wait periods continue normally.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        
        managed_event = market_maker_service.managed_events[event_id]
        managed_event.status = "paused"
        
        return {
            "success": True,
            "message": f"Market making paused for {managed_event.display_name}",
            "event_id": event_id,
            "note": "Existing positions and wait periods remain active"
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
    Get comprehensive portfolio summary with incremental betting metrics
    
    Returns detailed financial and risk metrics across all markets including:
    - Total exposure and liquidity
    - Number of active positions
    - Performance statistics
    - Risk utilization metrics
    - Incremental betting performance
    """
    try:
        return await market_maker_service.get_portfolio_summary()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting portfolio summary: {str(e)}")

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
    liquidity_amount: Optional[float] = Query(None, description="Base liquidity amount per increment"),
    poll_interval: Optional[int] = Query(None, description="Odds polling interval in seconds"),
    fill_wait_period: Optional[int] = Query(None, description="Wait period after fills in seconds")
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
            # Update base bet amount in strategy
            from app.services.market_making_strategy import market_making_strategy
            market_making_strategy.base_plus_bet = liquidity_amount
            updates["base_plus_bet"] = liquidity_amount
        
        if poll_interval is not None:
            if poll_interval < 30:
                raise HTTPException(status_code=400, detail="poll_interval must be at least 30 seconds")
            market_maker_service.settings.odds_poll_interval_seconds = poll_interval
            updates["odds_poll_interval_seconds"] = poll_interval
        
        if fill_wait_period is not None:
            if fill_wait_period < 60:
                raise HTTPException(status_code=400, detail="fill_wait_period must be at least 60 seconds")
            # Update wait period in betting manager
            from app.services.market_making_strategy import market_making_strategy
            market_making_strategy.betting_manager.fill_wait_period = fill_wait_period
            updates["fill_wait_period_seconds"] = fill_wait_period
        
        if not updates:
            return {
                "success": False,
                "message": "No configuration updates provided",
                "current_config": {
                    "max_events_tracked": market_maker_service.settings.max_events_tracked,
                    "base_plus_bet": market_making_strategy.base_plus_bet,
                    "odds_poll_interval_seconds": market_maker_service.settings.odds_poll_interval_seconds,
                    "fill_wait_period_seconds": market_making_strategy.betting_manager.fill_wait_period
                }
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