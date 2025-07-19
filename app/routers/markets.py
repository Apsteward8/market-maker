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
from app.services.single_event_tester import single_event_tester
from app.services.line_monitoring_service import line_monitoring_service
from app.services.line_position_service import line_position_service
from app.services.enhanced_prophetx_wager_service import prophetx_wager_service
from app.services.single_event_line_tester import single_event_line_tester


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
            if poll_interval < 60:
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
    
@router.get("/debug/line-summary/{line_id}", response_model=Dict[str, Any])
async def debug_line_summary(line_id: str):
    """
    Debug endpoint to see betting summary for a specific line
    
    Useful for troubleshooting duplicate bet issues
    """
    try:
        summary = market_maker_service._get_line_betting_summary(line_id)
        
        # Add some additional debug info
        line_bets = [bet for bet in market_maker_service.all_bets.values() if bet.line_id == line_id]
        bet_details = []
        
        for bet in line_bets:
            bet_details.append({
                "external_id": bet.external_id,
                "odds": bet.odds,
                "stake": bet.stake,
                "status": bet.status.value,
                "is_active": bet.is_active,
                "placed_at": bet.placed_at.isoformat(),
                "unmatched_stake": bet.unmatched_stake
            })
        
        return {
            "success": True,
            "line_id": line_id,
            "summary": summary,
            "bet_details": bet_details,
            "total_system_bets": len(market_maker_service.all_bets)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting line summary: {str(e)}")
    
# ADD this endpoint to your app/routers/markets.py

@router.get("/debug/matched-bets", response_model=Dict[str, Any])
async def debug_matched_bets():
    """
    Debug endpoint to see raw matched bets data from ProphetX
    
    Useful for troubleshooting matched bet detection issues
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        # Get raw matched bets data
        matched_bets = await prophetx_service.get_matched_bets()
        
        # Also get our active bets for comparison
        active_bets_summary = []
        for bet in market_maker_service.all_bets.values():
            if bet.is_active:
                active_bets_summary.append({
                    "external_id": bet.external_id,
                    "bet_id": bet.bet_id,
                    "selection_name": bet.selection_name,
                    "odds": bet.odds,
                    "stake": bet.stake,
                    "status": bet.status.value
                })
        
        return {
            "success": True,
            "message": f"Retrieved {len(matched_bets)} matched bets from ProphetX",
            "data": {
                "matched_bets_from_prophetx": matched_bets,
                "our_active_bets_count": len(active_bets_summary),
                "our_active_bets_sample": active_bets_summary[:5],  # First 5 for reference
                "analysis": {
                    "prophetx_matched_count": len(matched_bets),
                    "our_active_count": len(active_bets_summary),
                    "expected_matches": "Look for external_id matches between the two lists"
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting matched bets debug info: {str(e)}")

@router.get("/debug/bet-status/{external_id}", response_model=Dict[str, Any])
async def debug_specific_bet_status(external_id: str):
    """
    Debug endpoint to check status of a specific bet
    
    Shows all available information about a bet from both our records and ProphetX
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        # Find our bet
        our_bet = None
        for bet in market_maker_service.all_bets.values():
            if bet.external_id == external_id:
                our_bet = bet
                break
        
        if not our_bet:
            return {
                "success": False,
                "message": f"Bet {external_id} not found in our records"
            }
        
        # Get ProphetX data
        prophetx_active_wagers = await prophetx_service.get_all_active_wagers()
        prophetx_matched_bets = await prophetx_service.get_matched_bets()
        
        # Check if bet is in active wagers
        found_in_active = None
        for wager in prophetx_active_wagers:
            if isinstance(wager, dict) and wager.get('external_id') == external_id:
                found_in_active = wager
                break
        
        # Check if bet is in matched bets
        found_in_matched = None
        for bet in prophetx_matched_bets:
            if isinstance(bet, dict):
                if bet.get('external_id') == external_id:
                    found_in_matched = bet
                    break
                # Also check by ProphetX ID if available
                elif our_bet.bet_id and (bet.get('id') == our_bet.bet_id or 
                                       bet.get('wager_id') == our_bet.bet_id or
                                       bet.get('bet_id') == our_bet.bet_id):
                    found_in_matched = bet
                    break
        
        # Try individual lookup if we have ProphetX bet ID
        individual_lookup = None
        if our_bet.bet_id:
            individual_lookup = await prophetx_service.get_wager_by_id(our_bet.bet_id)
        
        return {
            "success": True,
            "message": f"Debug info for bet {external_id}",
            "data": {
                "our_bet": {
                    "external_id": our_bet.external_id,
                    "bet_id": our_bet.bet_id,
                    "selection_name": our_bet.selection_name,
                    "odds": our_bet.odds,
                    "stake": our_bet.stake,
                    "status": our_bet.status.value,
                    "is_active": our_bet.is_active,
                    "matched_stake": our_bet.matched_stake,
                    "unmatched_stake": our_bet.unmatched_stake
                },
                "prophetx_status": {
                    "found_in_active_wagers": found_in_active is not None,
                    "found_in_matched_bets": found_in_matched is not None,
                    "individual_lookup_success": individual_lookup is not None,
                    "active_wager_data": found_in_active,
                    "matched_bet_data": found_in_matched,
                    "individual_lookup_data": individual_lookup
                },
                "diagnosis": {
                    "likely_status": (
                        "Still active" if found_in_active else
                        "Matched/Filled" if found_in_matched or (individual_lookup and individual_lookup.get('matching_status') in ['fully_matched', 'partially_matched']) else
                        "Completed/Settled" if individual_lookup is None else
                        "Unknown"
                    ),
                    "recommendation": (
                        "Bet is still active - no action needed" if found_in_active else
                        "Bet is matched - should trigger wait period" if found_in_matched else
                        "Bet likely settled - should be marked as matched" if individual_lookup is None else
                        "Check bet status and matching_status fields"
                    )
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error debugging bet status: {str(e)}")
        
@router.post("/test-single-event/start/{odds_api_event_id}", response_model=Dict[str, Any])
async def start_single_event_test(odds_api_event_id: str):
    """
    Start testing market making for a single event
    
    This is perfect for debugging the monitoring/updating/refilling logic
    without the complexity of managing multiple events.
    
    - **odds_api_event_id**: Event ID from The Odds API
    
    **Test Flow:**
    1. Places initial bets using your existing strategy
    2. Monitors those bets for fills
    3. Handles 5-minute wait periods after fills
    4. Adds incremental liquidity when wait period ends
    5. Monitors Pinnacle for odds changes every 60 seconds
    6. Updates bets when odds change significantly
    """
    try:
        # Import the single event tester
        from app.services.single_event_tester import single_event_tester
        
        result = await single_event_tester.start_single_event_test(odds_api_event_id)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting single event test: {str(e)}")

@router.get("/test-single-event/status", response_model=Dict[str, Any])
async def get_single_event_test_status():
    """
    Get current status of the single event test
    
    Shows:
    - Session information
    - Number of bets placed
    - Fill status
    - Wait periods
    - Detailed bet information
    """
    try:
        from app.services.single_event_tester import single_event_tester
        
        status = single_event_tester.get_test_status()
        
        return {
            "success": True,
            "message": "Single event test status",
            "data": status,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting test status: {str(e)}")

@router.post("/test-single-event/stop", response_model=Dict[str, Any])
async def stop_single_event_test():
    """
    Stop the single event test
    
    Generates a final report showing:
    - Session duration
    - Total bets placed
    - Number of fills detected
    - Incremental bets added
    - Odds updates performed
    """
    try:
        from app.services.single_event_tester import single_event_tester
        
        result = await single_event_tester.stop_test()
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping single event test: {str(e)}")

@router.get("/test-single-event/bet-details", response_model=Dict[str, Any])
async def get_single_event_bet_details():
    """
    Get detailed information about all bets placed in the single event test
    
    Shows for each bet:
    - Selection name and odds
    - Stake amount
    - Current status
    - Fill history
    - Wait period status
    - Position size information
    """
    try:
        from app.services.single_event_tester import single_event_tester
        
        if not single_event_tester.session:
            return {
                "success": False,
                "message": "No active test session"
            }
        
        # Format bet details for easy reading
        formatted_bets = []
        
        for external_id, bet_info in single_event_tester.placed_bets.items():
            wait_remaining = None
            if bet_info["in_wait_period"] and bet_info["wait_period_ends"]:
                wait_remaining = (bet_info["wait_period_ends"] - datetime.now(timezone.utc)).total_seconds()
                wait_remaining = max(0, wait_remaining)
            
            formatted_bet = {
                "external_id": external_id,
                "selection_name": bet_info["selection_name"],
                "odds": bet_info["odds"],
                "stake": bet_info["stake"],
                "status": bet_info["status"],
                "placed_at": bet_info["placed_at"].isoformat(),
                "matched_amount": bet_info["matched_amount"],
                "unmatched_amount": bet_info["unmatched_amount"],
                "fill_count": len(bet_info["fills"]),
                "in_wait_period": bet_info["in_wait_period"],
                "wait_remaining_seconds": wait_remaining,
                "total_position": bet_info["total_position"],
                "max_position": bet_info["max_position"],
                "can_add_incremental": single_event_tester._can_add_incremental_liquidity(bet_info),
                "is_incremental": bet_info.get("is_incremental", False),
                "fill_history": bet_info["fills"]
            }
            
            formatted_bets.append(formatted_bet)
        
        # Sort by placement time
        formatted_bets.sort(key=lambda x: x["placed_at"])
        
        return {
            "success": True,
            "message": f"Bet details for {single_event_tester.session.event_name}",
            "data": {
                "event_name": single_event_tester.session.event_name,
                "session_active": single_event_tester.session.is_active,
                "total_bets": len(formatted_bets),
                "bets": formatted_bets,
                "summary": {
                    "active_bets": sum(1 for bet in formatted_bets if bet["status"] == "placed"),
                    "filled_bets": sum(1 for bet in formatted_bets if bet["matched_amount"] > 0),
                    "in_wait_period": sum(1 for bet in formatted_bets if bet["in_wait_period"]),
                    "can_add_incremental": sum(1 for bet in formatted_bets if bet["can_add_incremental"]),
                    "total_stake": sum(bet["stake"] for bet in formatted_bets),
                    "total_matched": sum(bet["matched_amount"] for bet in formatted_bets)
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting bet details: {str(e)}")

@router.post("/test-single-event/simulate-fill/{external_id}", response_model=Dict[str, Any])
async def simulate_single_event_fill(
    external_id: str,
    fill_amount: float = Query(..., description="Amount to simulate as filled")
):
    """
    Simulate a bet getting filled in the single event test
    
    This is useful for testing the fill detection and wait period logic
    without waiting for actual fills on ProphetX.
    
    - **external_id**: External ID of the bet to simulate fill for
    - **fill_amount**: Amount to simulate as filled/matched
    """
    try:
        from app.services.single_event_tester import single_event_tester
        
        if not single_event_tester.session:
            return {
                "success": False,
                "message": "No active test session"
            }
        
        if external_id not in single_event_tester.placed_bets:
            return {
                "success": False,
                "message": f"Bet {external_id} not found in test session"
            }
        
        bet_info = single_event_tester.placed_bets[external_id]
        
        # Simulate the fill
        previous_matched = bet_info["matched_amount"]
        new_matched = min(previous_matched + fill_amount, bet_info["stake"])
        actual_fill = new_matched - previous_matched
        
        if actual_fill <= 0:
            return {
                "success": False,
                "message": f"No fill possible - bet already matched {previous_matched:.2f}/{bet_info['stake']:.2f}"
            }
        
        # Update bet info
        bet_info["matched_amount"] = new_matched
        bet_info["unmatched_amount"] = bet_info["stake"] - new_matched
        bet_info["status"] = "matched" if new_matched >= bet_info["stake"] else "partially_matched"
        
        # Record fill
        bet_info["fills"].append({
            "amount": actual_fill,
            "timestamp": datetime.now(timezone.utc),
            "total_matched": new_matched,
            "simulated": True
        })
        
        # Start wait period
        await single_event_tester._start_wait_period(bet_info)
        
        single_event_tester.session.total_fills += 1
        
        return {
            "success": True,
            "message": f"Simulated fill of ${actual_fill:.2f} for {bet_info['selection_name']}",
            "data": {
                "external_id": external_id,
                "selection_name": bet_info["selection_name"],
                "fill_amount": actual_fill,
                "total_matched": new_matched,
                "remaining_unmatched": bet_info["unmatched_amount"],
                "wait_period_started": True,
                "wait_period_ends": bet_info["wait_period_ends"].isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error simulating fill: {str(e)}")

@router.post("/test-single-event/force-odds-check", response_model=Dict[str, Any])
async def force_single_event_odds_check():
    """
    Force an immediate odds check for the single event test
    
    Useful for testing the odds change detection logic without waiting
    for the 60-second interval.
    """
    try:
        from app.services.single_event_tester import single_event_tester
        
        if not single_event_tester.session:
            return {
                "success": False,
                "message": "No active test session"
            }
        
        # Get current odds
        current_odds = await single_event_tester._get_current_odds()
        
        if not current_odds:
            return {
                "success": False,
                "message": "Could not retrieve current odds"
            }
        
        # Check for changes
        changes = single_event_tester._detect_odds_changes(current_odds)
        
        if changes:
            print(f"📊 Manual odds check detected {len(changes)} changes")
            await single_event_tester._handle_odds_changes(changes)
            single_event_tester.session.odds_updates += 1
            
            # Update stored odds
            single_event_tester.last_odds_check = current_odds
            
            return {
                "success": True,
                "message": f"Detected and processed {len(changes)} odds changes",
                "data": {
                    "changes_detected": len(changes),
                    "changes": changes,
                    "odds_updates_total": single_event_tester.session.odds_updates
                }
            }
        else:
            # Store current odds for future comparison
            single_event_tester.last_odds_check = current_odds
            
            return {
                "success": True,
                "message": "No significant odds changes detected",
                "data": {
                    "changes_detected": 0,
                    "current_odds": current_odds
                }
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error forcing odds check: {str(e)}")

@router.post("/line-monitoring/start", response_model=Dict[str, Any])
async def start_line_monitoring():
    """
    Start the complete line monitoring and betting workflow
    
    This starts the main service that:
    1. Runs strategy every cycle to identify profitable lines
    2. Monitors positions via ProphetX wager histories
    3. Places initial bets on new profitable lines
    4. Detects fills and manages 5-minute wait periods  
    5. Places incremental bets up to 4x position limits
    6. Repeats every 60 seconds
    
    **This is the main endpoint to start your complete workflow.**
    """
    try:
        # Initialize services if needed
        from app.services.line_monitoring_service import line_monitoring_service
        from app.services.line_position_service import line_position_service
        from app.services.enhanced_prophetx_wager_service import prophetx_wager_service, initialize_wager_service
        from app.services.market_making_strategy import market_making_strategy
        from app.services.prophetx_service import prophetx_service
        
        # Initialize wager service
        initialize_wager_service(prophetx_service)
        
        # Initialize monitoring service
        line_monitoring_service.initialize_services(
            line_position_service,
            prophetx_wager_service,
            market_making_strategy
        )
        
        # Start monitoring
        result = await line_monitoring_service.start_monitoring()
        
        return {
            "success": True,
            "message": "Line monitoring workflow started",
            "data": result,
            "workflow_description": {
                "step_1": "Run strategy to identify profitable lines",
                "step_2": "Check positions via ProphetX wager histories",
                "step_3": "Place initial bets on new lines",
                "step_4": "Monitor for fills every 60 seconds",
                "step_5": "Manage 5-minute wait periods after fills",
                "step_6": "Place incremental bets up to 4x limits"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting line monitoring: {str(e)}")

@router.post("/line-monitoring/stop", response_model=Dict[str, Any])
async def stop_line_monitoring():
    """
    Stop the line monitoring workflow
    
    This stops the monitoring loop but does not cancel existing bets.
    """
    try:
        from app.services.line_monitoring_service import line_monitoring_service
        
        result = await line_monitoring_service.stop_monitoring()
        
        return {
            "success": True,
            "message": "Line monitoring stopped",
            "data": result,
            "note": "Existing bets remain active - use cancel endpoints if needed"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping line monitoring: {str(e)}")

@router.get("/line-monitoring/status", response_model=Dict[str, Any])
async def get_line_monitoring_status():
    """
    Get current status of the line monitoring workflow
    
    Shows:
    - Whether monitoring is active
    - Number of lines being tracked
    - Last strategy run time
    - Last monitoring cycle time
    - Configuration settings
    """
    try:
        from app.services.line_monitoring_service import line_monitoring_service
        
        status = line_monitoring_service.get_status()
        
        return {
            "success": True,
            "message": "Line monitoring status",
            "data": status,
            "current_time": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")

# =============================================================================
# LINE POSITION ENDPOINTS
# =============================================================================

@router.get("/line-positions/summary", response_model=Dict[str, Any])
async def get_line_positions_summary():
    """
    Get summary of all line positions
    
    Shows total stake, matched amounts, and position utilization across all lines.
    This uses real ProphetX data from wager histories.
    """
    try:
        from app.services.line_position_service import line_position_service
        
        summary = line_position_service.get_summary()
        
        return {
            "success": True,
            "message": "Line positions summary",
            "data": summary
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting positions summary: {str(e)}")

@router.get("/line-positions/{line_id}", response_model=Dict[str, Any])
async def get_line_position_detail(line_id: str):
    """
    Get detailed position information for a specific line
    
    Shows:
    - All bets placed on this line
    - Total stake and matched amounts
    - Recent fills and wait period status
    - Whether more liquidity can be added
    - Next bet amount if applicable
    
    **line_id**: ProphetX line ID to get details for
    """
    try:
        from app.services.line_position_service import line_position_service
        
        position = await line_position_service.get_line_position(line_id)
        
        if not position:
            # Try to refresh from ProphetX
            position = await line_position_service.refresh_line_position(line_id)
        
        if not position:
            return {
                "success": False,
                "message": f"No position data found for line {line_id}"
            }
        
        return {
            "success": True,
            "message": f"Position details for line {line_id}",
            "data": {
                "line_id": position.line_id,
                "selection_name": position.selection_name,
                "position_summary": {
                    "total_bets": position.total_bets,
                    "total_stake": position.total_stake,
                    "total_matched": position.total_matched,
                    "total_unmatched": position.total_unmatched,
                    "utilization_percent": (position.total_stake / position.max_position) * 100
                },
                "limits": {
                    "max_position": position.max_position,
                    "increment_size": position.increment_size,
                    "recommended_initial": position.recommended_initial
                },
                "status": {
                    "has_active_bets": position.has_active_bets,
                    "in_wait_period": position.in_wait_period,
                    "wait_period_ends": position.wait_period_ends.isoformat() if position.wait_period_ends else None,
                    "can_add_liquidity": position.can_add_liquidity,
                    "next_bet_amount": position.next_bet_amount
                },
                "activity": {
                    "last_bet_time": position.last_bet_time.isoformat() if position.last_bet_time else None,
                    "last_fill_time": position.last_fill_time.isoformat() if position.last_fill_time else None,
                    "recent_fills": position.recent_fills
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting line position: {str(e)}")

@router.post("/line-positions/{line_id}/refresh", response_model=Dict[str, Any])
async def refresh_line_position(line_id: str):
    """
    Manually refresh position data for a specific line
    
    Forces a fresh fetch from ProphetX wager histories API.
    Useful for debugging or getting real-time updates.
    
    **line_id**: ProphetX line ID to refresh
    """
    try:
        from app.services.line_position_service import line_position_service
        
        position = await line_position_service.refresh_line_position(line_id)
        
        if not position:
            return {
                "success": False,
                "message": f"Failed to refresh position for line {line_id}"
            }
        
        return {
            "success": True,
            "message": f"Position refreshed for line {line_id}",
            "data": {
                "line_id": line_id,
                "total_stake": position.total_stake,
                "total_matched": position.total_matched,
                "can_add_liquidity": position.can_add_liquidity,
                "next_bet_amount": position.next_bet_amount,
                "refreshed_at": datetime.now(timezone.utc).isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing line position: {str(e)}")

# =============================================================================
# WAGER HISTORY ENDPOINTS
# =============================================================================

@router.get("/wager-histories/line/{line_id}", response_model=Dict[str, Any])
async def get_wager_histories_for_line(
    line_id: str,
    days_back: int = Query(7, description="How many days back to search"),
    include_all_statuses: bool = Query(True, description="Include cancelled/expired bets")
):
    """
    Get all wager histories for a specific line
    
    This shows the raw ProphetX wager data that drives position calculations.
    **Parameters:**
    - **line_id**: ProphetX line ID
    - **days_back**: How many days back to search (default 7)
    - **include_all_statuses**: Whether to include cancelled/expired bets
    """
    try:
        # Import the service class and ProphetX service
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService, initialize_wager_service
        from app.services.prophetx_service import prophetx_service
        
        # Create a fresh instance of the wager service (don't rely on global)
        wager_service = ProphetXWagerService(prophetx_service)
        
        # Also initialize the global for other parts of the system that might need it
        initialize_wager_service(prophetx_service)
        
        # Now call the method on our fresh instance
        result = await wager_service.get_all_wagers_for_line(
            line_id, 
            days_back=days_back,
            include_all_statuses=include_all_statuses
        )
        
        return {
            "success": True,
            "message": f"Wager histories for line {line_id}",
            "data": result,
            "debug_info": {
                "wager_service_created": wager_service is not None,
                "service_type": str(type(wager_service)),
                "line_id": line_id,
                "days_back": days_back
            }
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Error getting wager histories: {str(e)}",
            "traceback": traceback.format_exc(),
            "line_id": line_id
        }

# Also fix the get_recent_fills endpoint the same way:

@router.get("/wager-histories/recent-fills", response_model=Dict[str, Any])
async def get_recent_fills(
    minutes_back: int = Query(60, description="How many minutes back to check for fills"),
    line_ids: Optional[str] = Query(None, description="Comma-separated line IDs to check")
):
    """
    Get recent fills across lines
    
    Useful for monitoring fill activity in real-time.
    
    **Parameters:**
    - **minutes_back**: How many minutes back to check (default 60)
    - **line_ids**: Comma-separated line IDs to check (optional - checks all if not provided)
    """
    try:
        # Create fresh service instances
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService, initialize_wager_service
        from app.services.prophetx_service import prophetx_service
        from app.services.line_monitoring_service import line_monitoring_service
        
        # Create a fresh wager service instance
        wager_service = ProphetXWagerService(prophetx_service)
        
        # Initialize global service too
        initialize_wager_service(prophetx_service)
        
        # Get line IDs to check
        if line_ids:
            check_line_ids = [lid.strip() for lid in line_ids.split(",")]
        else:
            # Use all monitored lines
            check_line_ids = list(line_monitoring_service.monitored_lines.keys())
        
        if not check_line_ids:
            return {
                "success": False,
                "message": "No line IDs to check"
            }
        
        # Use our fresh instance
        recent_fills = await wager_service.detect_recent_fills(
            check_line_ids, 
            minutes_back=minutes_back
        )
        
        return {
            "success": True,
            "message": f"Recent fills in last {minutes_back} minutes",
            "data": {
                "fills_detected": len(recent_fills),
                "lines_checked": len(check_line_ids),
                "fills": recent_fills
            }
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Error getting recent fills: {str(e)}",
            "traceback": traceback.format_exc()
        }

# =============================================================================
# SINGLE EVENT TESTING ENDPOINTS
# =============================================================================

@router.post("/line-monitoring/test-single-event/{odds_api_event_id}/start", response_model=Dict[str, Any])
async def start_single_event_line_test(odds_api_event_id: str):
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        from app.services.line_position_service import line_position_service
        from app.services.market_making_strategy import market_making_strategy
        from app.services.prophetx_service import prophetx_service
        
        # IMPORTANT: Import and initialize properly
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService, initialize_wager_service
        
        # Create the wager service instance directly
        actual_wager_service = ProphetXWagerService(prophetx_service)
        
        # Initialize the global service
        initialize_wager_service(prophetx_service)
        
        # Pass the actual instance to the single event tester
        single_event_line_tester.initialize_services(
            line_position_service,
            actual_wager_service,  # Use the actual instance, not the global
            market_making_strategy
        )
        
        # Start single event test
        result = await single_event_line_tester.start_single_event_test(odds_api_event_id)
        
        return {
            "success": result["success"],
            "message": result["message"],
            "data": result.get("data"),
            "debug_info": {
                "wager_service_initialized": actual_wager_service is not None,
                "service_type": str(type(actual_wager_service))
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting single event test: {str(e)}")

@router.post("/line-monitoring/test-single-event/stop", response_model=Dict[str, Any])
async def stop_single_event_line_test():
    """
    Stop the single event line monitoring test
    
    Stops the monitoring loop but leaves any placed bets active.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        result = await single_event_line_tester.stop_single_event_test()
        
        return {
            "success": result["success"],
            "message": result["message"],
            "data": result.get("data")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping single event test: {str(e)}")

@router.get("/line-monitoring/test-single-event/status", response_model=Dict[str, Any])
async def get_single_event_test_status():
    """
    Get status of the single event line monitoring test
    
    Shows current session info, monitoring cycles, bets placed, etc.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        status = single_event_line_tester.get_session_status()
        
        return {
            "success": True,
            "message": "Single event test status",
            "data": status
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting single event test status: {str(e)}")

@router.get("/odds/events", response_model=Dict[str, Any])
async def get_current_odds_events():
    """
    Get current events from The Odds API
    
    Use this to find event IDs for single event testing.
    Shows event_id, teams, and start times.
    """
    try:
        from app.services.odds_api_service import odds_api_service
        
        events = await odds_api_service.get_events()
        
        events_list = []
        for event in events:
            events_list.append({
                "event_id": event.event_id,
                "sport": event.sport,
                "home_team": event.home_team,
                "away_team": event.away_team,
                "commence_time": event.commence_time.isoformat(),
                "display_name": f"{event.away_team} vs {event.home_team}"
            })
        
        return {
            "success": True,
            "message": f"Found {len(events_list)} current events",
            "data": {
                "events": events_list,
                "note": "Use event_id for single event testing"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting odds events: {str(e)}")

# =============================================================================
# MANUAL CONTROL ENDPOINTS
# =============================================================================

@router.post("/line-positions/{line_id}/clear-wait-period", response_model=Dict[str, Any])
async def clear_line_wait_period(line_id: str):
    """
    Manually clear the 5-minute wait period for a specific line
    
    Useful when odds change significantly or for manual intervention.
    After clearing, the line will be eligible for immediate liquidity addition.
    
    **line_id**: ProphetX line ID to clear wait period for
    """
    try:
        from app.services.line_position_service import line_position_service
        
        # Get current position
        position = await line_position_service.get_line_position(line_id)
        
        if not position:
            return {
                "success": False,
                "message": f"No position found for line {line_id}"
            }
        
        if not position.in_wait_period:
            return {
                "success": False,
                "message": f"Line {line_id} is not in wait period"
            }
        
        # Clear the wait period (simplified - you'd implement this in line_position_service)
        # For now, just refresh the position which will recalculate status
        await line_position_service.refresh_line_position(line_id)
        
        return {
            "success": True,
            "message": f"Wait period cleared for line {line_id}",
            "data": {
                "line_id": line_id,
                "note": "Line is now eligible for immediate liquidity addition"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing wait period: {str(e)}")

@router.post("/line-monitoring/force-strategy-run", response_model=Dict[str, Any])
async def force_strategy_run():
    """
    Force an immediate strategy run outside of the normal cycle
    
    Useful for testing or when you want to check for new profitable lines immediately.
    """
    try:
        from app.services.line_monitoring_service import line_monitoring_service
        
        if not line_monitoring_service.monitoring_active:
            return {
                "success": False,
                "message": "Line monitoring is not active - start it first"
            }
        
        # Trigger strategy run
        await line_monitoring_service._run_main_strategy()
        
        return {
            "success": True,
            "message": "Strategy run completed",
            "data": {
                "lines_identified": len(line_monitoring_service.monitored_lines),
                "triggered_at": datetime.now(timezone.utc).isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error forcing strategy run: {str(e)}")

@router.get("/line-monitoring/monitored-lines", response_model=Dict[str, Any])
async def get_monitored_lines():
    """
    Get list of currently monitored lines with their strategies
    
    Shows which lines the system identified as profitable and is actively monitoring.
    """
    try:
        from app.services.line_monitoring_service import line_monitoring_service
        
        lines_data = {}
        
        for line_id, strategy in line_monitoring_service.monitored_lines.items():
            lines_data[line_id] = {
                "selection_name": strategy.selection_name,
                "odds": strategy.odds,
                "recommended_initial_stake": strategy.recommended_initial_stake,
                "max_position": strategy.max_position,
                "increment_size": strategy.increment_size,
                "event_id": strategy.event_id,
                "market_type": strategy.market_type
            }
        
        return {
            "success": True,
            "message": f"Currently monitoring {len(lines_data)} lines",
            "data": {
                "total_lines": len(lines_data),
                "lines": lines_data,
                "last_strategy_run": line_monitoring_service.last_strategy_run.isoformat() if line_monitoring_service.last_strategy_run else None
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting monitored lines: {str(e)}")
    
@router.post("/debug/test-single-event-matching/{event_id}", response_model=Dict[str, Any])
async def test_single_event_matching(event_id: str):
    """
    Test event matching for a single event (minimal version)
    
    This tests just the event matching part to make sure the method calls work.
    """
    try:
        # Get the specific event from Odds API
        from app.services.odds_api_service import odds_api_service
        from app.services.event_matching_service import event_matching_service
        
        print(f"🎯 Testing event matching for {event_id}")
        
        # Step 1: Get the event
        odds_events = await odds_api_service.get_events()
        target_event = None
        
        for event in odds_events:
            if event.event_id == event_id:
                target_event = event
                break
        
        if not target_event:
            return {
                "success": False,
                "message": f"Event {event_id} not found in current Odds API events",
                "available_events": [
                    {
                        "event_id": e.event_id,
                        "display_name": f"{e.away_team} vs {e.home_team}"
                    } for e in odds_events[:5]
                ]
            }
        
        print(f"✅ Found event: {target_event.away_team} vs {target_event.home_team}")
        
        # Step 2: Test event matching with CORRECT method
        print("🔗 Testing event matching...")
        
        # ✅ CORRECT: Use find_matches_for_events with a list
        matching_attempts = await event_matching_service.find_matches_for_events([target_event])
        
        if not matching_attempts:
            return {
                "success": False,
                "message": "No matching attempts returned"
            }
        
        matching_attempt = matching_attempts[0]
        
        if not matching_attempt.best_match:
            return {
                "success": False,
                "message": f"Could not match event to ProphetX",
                "details": {
                    "no_match_reason": matching_attempt.no_match_reason,
                    "potential_matches_count": len(matching_attempt.prophetx_matches),
                    "best_confidence": matching_attempt.prophetx_matches[0][1] if matching_attempt.prophetx_matches else "N/A"
                }
            }
        
        event_match = matching_attempt.best_match
        
        return {
            "success": True,
            "message": f"Successfully matched event!",
            "data": {
                "odds_api_event": {
                    "event_id": target_event.event_id,
                    "display_name": f"{target_event.away_team} vs {target_event.home_team}",
                    "commence_time": target_event.commence_time.isoformat()
                },
                "prophetx_event": {
                    "event_id": event_match.prophetx_event.event_id,
                    "display_name": event_match.prophetx_event.display_name,
                    "commence_time": event_match.prophetx_event.commence_time.isoformat()
                },
                "match_confidence": event_match.confidence_score,
                "match_reasons": event_match.match_reasons
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error testing event matching: {str(e)}",
            "error_type": type(e).__name__
        }

# ALSO: Add this helper endpoint to get available events for testing

@router.get("/debug/available-events", response_model=Dict[str, Any])
async def get_available_events_for_testing():
    """
    Get list of available events for testing
    
    Returns current events from Odds API that you can use for testing.
    """
    try:
        from app.services.odds_api_service import odds_api_service
        
        events = await odds_api_service.get_events()
        
        events_list = []
        for event in events:
            events_list.append({
                "event_id": event.event_id,
                "display_name": f"{event.away_team} vs {event.home_team}",
                "commence_time": event.commence_time.isoformat(),
                "sport": event.sport
            })
        
        return {
            "success": True,
            "message": f"Found {len(events_list)} events available for testing",
            "events": events_list,
            "usage": "Use event_id with /debug/test-single-event-matching/{event_id}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error getting events: {str(e)}"
        }

@router.get("/debug/test-market-object/{event_id}", response_model=Dict[str, Any])
async def test_market_object_structure(event_id: str):
    """
    Test market object structure to debug the len() error
    
    This will show you exactly what type of object market_matches is 
    and what properties it has.
    """
    try:
        from app.services.odds_api_service import odds_api_service
        from app.services.event_matching_service import event_matching_service
        from app.services.market_matching_service import market_matching_service
        
        # Get the event
        odds_events = await odds_api_service.get_events()
        target_event = None
        
        for event in odds_events:
            if event.event_id == event_id:
                target_event = event
                break
        
        if not target_event:
            return {"success": False, "message": "Event not found"}
        
        # Match event
        matching_attempts = await event_matching_service.find_matches_for_events([target_event])
        if not matching_attempts or not matching_attempts[0].best_match:
            return {"success": False, "message": "No event match"}
        
        event_match = matching_attempts[0].best_match
        
        # Get market matches
        market_matches = await market_matching_service.match_event_markets(event_match)
        
        # Debug the object structure
        return {
            "success": True,
            "debug_info": {
                "object_type": str(type(market_matches)),
                "has_len": hasattr(market_matches, '__len__'),
                "properties": dir(market_matches),
                "market_matches_type": str(type(market_matches.market_matches)),
                "market_matches_length": len(market_matches.market_matches),
                "ready_for_trading": market_matches.ready_for_trading,
                "sample_structure": {
                    "total_markets": len(market_matches.market_matches),
                    "ready": market_matches.ready_for_trading,
                    "issues": market_matches.issues
                }
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

# Also add this debug endpoint to test service creation:
@router.get("/debug/test-wager-service", response_model=Dict[str, Any])
async def test_wager_service_creation():
    """Test creating the wager service directly"""
    try:
        from app.services.prophetx_service import prophetx_service
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService
        
        # Create service directly
        wager_service = ProphetXWagerService(prophetx_service)
        
        # Test a simple method
        result = await wager_service.get_wager_histories(limit=1)
        
        return {
            "success": True,
            "message": "Wager service created and tested successfully",
            "data": {
                "service_created": wager_service is not None,
                "service_type": str(type(wager_service)),
                "test_call_success": result.get("success", False),
                "test_result": result
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
    
@router.get("/debug/liquidity-calculation/{line_id}", response_model=Dict[str, Any])
async def debug_liquidity_calculation(
    line_id: str,
    recommended_initial: float = Query(100.0, description="Recommended initial stake"),
    max_position_multiplier: float = Query(4.0, description="Max position multiplier (e.g., 4x)")
):
    """
    Debug liquidity calculation for a specific line
    
    Shows exactly how the liquidity management logic works with current position data.
    """
    try:
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService
        from app.services.prophetx_service import prophetx_service
        
        # Create wager service
        wager_service = ProphetXWagerService(prophetx_service)
        
        # Get current position
        position_result = await wager_service.get_all_wagers_for_line(line_id)
        
        if not position_result["success"]:
            return {
                "success": False,
                "message": f"Could not get position data for line {line_id}",
                "error": position_result.get("error")
            }
        
        summary = position_result["position_summary"]
        
        # Extract current state
        total_stake = summary["total_stake"]
        total_matched = summary["total_matched"]
        current_unmatched = total_stake - total_matched
        max_position = recommended_initial * max_position_multiplier
        
        # Calculate what we would do
        liquidity_shortfall = max(0, recommended_initial - current_unmatched)
        remaining_capacity = max_position - total_stake
        potential_bet_amount = min(liquidity_shortfall, remaining_capacity) if remaining_capacity > 0 else 0
        
        # Determine action
        if liquidity_shortfall == 0:
            action = "✅ No action needed - adequate liquidity"
            action_type = "none"
        elif remaining_capacity <= 0:
            action = "🛑 No action - at maximum position"
            action_type = "blocked_by_limit"
        elif potential_bet_amount > 0:
            action = f"💰 Place ${potential_bet_amount:.2f} bet to restore liquidity"
            action_type = "place_bet"
        else:
            action = "⏸️ No action needed"
            action_type = "none"
        
        # Check wait period
        wait_status = "none"
        wait_message = "No recent fills - no wait period"
        
        if summary.get("last_fill_time"):
            try:
                from datetime import datetime, timezone, timedelta
                last_fill = datetime.fromisoformat(summary["last_fill_time"].replace('Z', '+00:00'))
                wait_until = last_fill + timedelta(seconds=300)  # 5 minutes
                time_remaining = (wait_until - datetime.now(timezone.utc)).total_seconds()
                
                if time_remaining > 0:
                    wait_status = "active"
                    wait_message = f"⏰ Wait period active - {time_remaining:.0f}s remaining"
                    if action_type == "place_bet":
                        action = f"⏰ Would place ${potential_bet_amount:.2f} but waiting {time_remaining:.0f}s"
                        action_type = "waiting"
                else:
                    wait_status = "completed"
                    wait_message = "✅ Wait period completed"
            except:
                wait_message = "⚠️ Could not parse last fill time"
        
        return {
            "success": True,
            "line_id": line_id,
            "liquidity_analysis": {
                "current_state": {
                    "total_stake": total_stake,
                    "total_matched": total_matched,
                    "current_unmatched": current_unmatched,
                    "total_bets": summary["total_bets"],
                    "has_active_bets": summary["has_active_bets"]
                },
                "targets": {
                    "recommended_initial": recommended_initial,
                    "max_position": max_position,
                    "max_multiplier": max_position_multiplier
                },
                "calculations": {
                    "liquidity_shortfall": liquidity_shortfall,
                    "remaining_capacity": remaining_capacity,
                    "potential_bet_amount": potential_bet_amount
                },
                "decision": {
                    "action": action,
                    "action_type": action_type,
                    "wait_status": wait_status,
                    "wait_message": wait_message
                }
            },
            "examples_explanation": {
                "your_case": f"total_stake=${total_stake}, total_matched=${total_matched}, current_unmatched=${current_unmatched}",
                "example_1": "total_stake=25, total_matched=25, unmatched=0 → Need $25 to reach target",
                "example_2": "total_stake=25, total_matched=0, unmatched=25 → Already at target",
                "example_3": "total_stake=25, total_matched=10, unmatched=15 → Need $10 to reach target",
                "example_4": "total_stake=100, total_matched=90, unmatched=10 → At max position, can't add more",
                "example_5": "total_stake=90, total_matched=85, unmatched=5 → Need $20 but limited to $10 by max position"
            }
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Debug calculation failed: {str(e)}",
            "traceback": traceback.format_exc()
        }

# Add this debug endpoint to your markets.py router

@router.get("/debug/system-vs-manual-bets/{line_id}", response_model=Dict[str, Any])
async def debug_system_vs_manual_bets(
    line_id: str,
    show_all_bets: bool = Query(False, description="Show details of all individual bets")
):
    """
    Debug system vs manual bet filtering for a specific line
    
    Shows how the system distinguishes between:
    - System bets (non-empty external_id, counted in position calculations)
    - Manual UI bets (empty external_id, ignored in position calculations)
    """
    try:
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService
        from app.services.prophetx_service import prophetx_service
        
        # Create wager service
        wager_service = ProphetXWagerService(prophetx_service)
        
        # Get ALL bets (including manual ones)
        position_result_all = await wager_service.get_all_wagers_for_line(
            line_id, 
            system_bets_only=False  # Include all bets
        )
        
        # Get SYSTEM bets only
        position_result_system = await wager_service.get_all_wagers_for_line(
            line_id,
            system_bets_only=True,
            external_id_filter="single_test_"
        )
        
        if not position_result_all["success"]:
            return {
                "success": False,
                "message": f"Could not get position data for line {line_id}",
                "error": position_result_all.get("error")
            }
        
        all_wagers = position_result_all["wagers"]
        
        # Categorize bets
        system_bets = []
        manual_bets = []
        
        for wager in all_wagers:
            external_id = wager.get("external_id", "")
            is_system = bool(external_id and external_id.strip())
            
            bet_info = {
                "external_id": external_id or "MANUAL_UI_BET",
                "created_at": wager.get("created_at"),
                "stake": wager.get("stake", 0),
                "matched_stake": wager.get("matched_stake", 0),
                "status": wager.get("status"),
                "matching_status": wager.get("matching_status")
            }
            
            if is_system:
                system_bets.append(bet_info)
            else:
                manual_bets.append(bet_info)
        
        # Compare position calculations
        all_summary = position_result_all["position_summary"]
        system_summary = position_result_system["position_summary"]
        
        return {
            "success": True,
            "line_id": line_id,
            "analysis": {
                "total_bets_found": len(all_wagers),
                "system_bets_count": len(system_bets),
                "manual_bets_count": len(manual_bets),
                "filtering_impact": {
                    "all_bets_calculation": {
                        "total_stake": all_summary.get("total_stake", 0),
                        "total_matched": all_summary.get("total_matched", 0),
                        "total_unmatched": all_summary.get("total_stake", 0) - all_summary.get("total_matched", 0)
                    },
                    "system_only_calculation": {
                        "total_stake": system_summary.get("total_stake", 0),
                        "total_matched": system_summary.get("total_matched", 0),
                        "total_unmatched": system_summary.get("total_stake", 0) - system_summary.get("total_matched", 0)
                    }
                }
            },
            "system_bets": system_bets if show_all_bets else f"{len(system_bets)} system bets (use ?show_all_bets=true to see details)",
            "manual_bets": manual_bets if show_all_bets else f"{len(manual_bets)} manual bets (use ?show_all_bets=true to see details)",
            "position_summary": {
                "using_system_only": system_summary,
                "including_all_bets": all_summary
            },
            "explanation": {
                "system_bets": "Bets with non-empty external_id - counted in position calculations",
                "manual_bets": "Bets with empty external_id (placed via UI) - ignored in calculations",
                "benefit": "You can place manual test bets without affecting automated system limits",
                "external_id_pattern": "Your system uses: single_test_<line_id>_<timestamp>"
            }
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Debug analysis failed: {str(e)}",
            "traceback": traceback.format_exc()
        }
    
# Add this debug endpoint to your markets.py router

@router.get("/debug/liquidity-calculation/{line_id}", response_model=Dict[str, Any])
async def debug_liquidity_calculation(
    line_id: str,
    recommended_initial: float = Query(100.0, description="Recommended initial stake"),
    max_position_multiplier: float = Query(4.0, description="Max position multiplier (e.g., 4x)")
):
    """
    Debug liquidity calculation for a specific line - SYSTEM BETS ONLY
    
    Shows exactly how the liquidity management logic works with current position data.
    Only counts system bets (non-empty external_id) - manual UI bets are ignored.
    """
    try:
        from app.services.enhanced_prophetx_wager_service import ProphetXWagerService
        from app.services.prophetx_service import prophetx_service
        
        # Create wager service
        wager_service = ProphetXWagerService(prophetx_service)
        
        # Get current position (SYSTEM BETS ONLY)
        position_result = await wager_service.get_all_wagers_for_line(
            line_id,
            system_bets_only=True,
            external_id_filter="single_test_"
        )
        
        if not position_result["success"]:
            return {
                "success": False,
                "message": f"Could not get position data for line {line_id}",
                "error": position_result.get("error")
            }
        
        summary = position_result["position_summary"]
        
        # Extract current state (SYSTEM BETS ONLY)
        total_stake = summary["total_stake"]
        total_matched = summary["total_matched"]
        current_unmatched = total_stake - total_matched
        system_bets = summary.get("system_bets", 0)
        manual_bets = summary.get("manual_bets", 0)
        max_position = recommended_initial * max_position_multiplier
        
        # Calculate what we would do
        liquidity_shortfall = max(0, recommended_initial - current_unmatched)
        remaining_capacity = max_position - total_stake
        potential_bet_amount = min(liquidity_shortfall, remaining_capacity) if remaining_capacity > 0 else 0
        
        # Determine action
        if system_bets == 0:
            action = f"💰 Place initial ${recommended_initial:.2f} bet (no system bets found)"
            action_type = "initial_bet"
        elif liquidity_shortfall == 0:
            action = "✅ No action needed - adequate liquidity"
            action_type = "none"
        elif remaining_capacity <= 0:
            action = "🛑 No action - at maximum system position"
            action_type = "blocked_by_limit"
        elif potential_bet_amount > 0:
            action = f"💰 Place ${potential_bet_amount:.2f} bet to restore liquidity"
            action_type = "place_bet"
        else:
            action = "⏸️ No action needed"
            action_type = "none"
        
        # Check wait period
        wait_status = "none"
        wait_message = "No recent fills - no wait period"
        
        if summary.get("last_fill_time"):
            try:
                from datetime import datetime, timezone, timedelta
                last_fill = datetime.fromisoformat(summary["last_fill_time"].replace('Z', '+00:00'))
                wait_until = last_fill + timedelta(seconds=300)  # 5 minutes
                time_remaining = (wait_until - datetime.now(timezone.utc)).total_seconds()
                
                if time_remaining > 0:
                    wait_status = "active"
                    wait_message = f"⏰ Wait period active - {time_remaining:.0f}s remaining"
                    if action_type == "place_bet":
                        action = f"⏰ Would place ${potential_bet_amount:.2f} but waiting {time_remaining:.0f}s"
                        action_type = "waiting"
                else:
                    wait_status = "completed"
                    wait_message = "✅ Wait period completed"
            except:
                wait_message = "⚠️ Could not parse last fill time"
        
        return {
            "success": True,
            "line_id": line_id,
            "filtering_note": "🔥 SYSTEM BETS ONLY - Manual UI bets are ignored",
            "liquidity_analysis": {
                "current_state": {
                    "system_bets": system_bets,
                    "manual_bets": manual_bets,
                    "total_stake": total_stake,
                    "total_matched": total_matched,
                    "current_unmatched": current_unmatched,
                    "note": f"Only counting {system_bets} system bets, ignoring {manual_bets} manual bets"
                },
                "targets": {
                    "recommended_initial": recommended_initial,
                    "max_position": max_position,
                    "max_multiplier": max_position_multiplier
                },
                "calculations": {
                    "liquidity_shortfall": liquidity_shortfall,
                    "remaining_capacity": remaining_capacity,
                    "potential_bet_amount": potential_bet_amount
                },
                "decision": {
                    "action": action,
                    "action_type": action_type,
                    "wait_status": wait_status,
                    "wait_message": wait_message
                }
            },
            "examples_explanation": {
                "your_case": f"system_stake=${total_stake}, system_matched=${total_matched}, system_unmatched=${current_unmatched}",
                "manual_bets_ignored": f"{manual_bets} manual UI bets completely ignored in calculations",
                "example_1": "system_stake=25, system_matched=25, unmatched=0 → Need $25 to reach target",
                "example_2": "system_stake=25, system_matched=0, unmatched=25 → Already at target", 
                "example_3": "Manual bet: $500 + System bet: $25 → Only count the $25 system bet"
            },
            "benefits": [
                "✅ Place manual test bets without affecting system position limits",
                "✅ Manual hedge bets don't interfere with automated liquidity management",
                "✅ System maintains independent control of its own position"
            ]
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Debug calculation failed: {str(e)}",
            "traceback": traceback.format_exc()
        }
    
@router.get("/line-monitoring/test-single-event/metadata", response_model=Dict[str, Any])
async def get_single_event_metadata():
    """
    Get metadata for all lines being monitored in the single event test
    
    This shows ProphetX event IDs and market IDs for each line,
    which will be needed for the cancel_wagers_by_market functionality.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        # Get all metadata
        metadata = single_event_line_tester.get_all_line_metadata()
        
        if not metadata:
            return {
                "success": False,
                "message": "No line metadata available"
            }
        
        # Organize metadata by event and market
        events = {}
        markets = {}
        
        for line_id, meta in metadata.items():
            # Group by event
            event_id = meta.prophetx_event_id
            if event_id:
                if event_id not in events:
                    events[event_id] = {
                        "event_id": event_id,
                        "lines": [],
                        "markets": set()
                    }
                events[event_id]["lines"].append({
                    "line_id": line_id,
                    "selection_name": meta.selection_name,
                    "market_id": meta.prophetx_market_id,
                    "market_type": meta.market_type
                })
                if meta.prophetx_market_id:
                    events[event_id]["markets"].add(meta.prophetx_market_id)
            
            # Group by market
            market_id = meta.prophetx_market_id
            if market_id:
                if market_id not in markets:
                    markets[market_id] = {
                        "market_id": market_id,
                        "market_type": meta.market_type,
                        "event_id": event_id,
                        "lines": []
                    }
                markets[market_id]["lines"].append({
                    "line_id": line_id,
                    "selection_name": meta.selection_name
                })
        
        # Convert sets to lists for JSON serialization
        for event_data in events.values():
            event_data["markets"] = list(event_data["markets"])
        
        return {
            "success": True,
            "message": f"Retrieved metadata for {len(metadata)} lines",
            "data": {
                "total_lines": len(metadata),
                "total_events": len(events),
                "total_markets": len(markets),
                "events": events,
                "markets": markets,
                "line_details": [
                    {
                        "line_id": line_id,
                        "selection_name": meta.selection_name,
                        "prophetx_event_id": meta.prophetx_event_id,
                        "prophetx_market_id": meta.prophetx_market_id,
                        "market_type": meta.market_type,
                        "last_updated": meta.last_updated.isoformat()
                    }
                    for line_id, meta in metadata.items()
                ]
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting metadata: {str(e)}")

@router.get("/line-monitoring/test-single-event/metadata/{line_id}", response_model=Dict[str, Any])
async def get_single_line_metadata(line_id: str):
    """
    Get metadata for a specific line
    
    This shows the ProphetX event ID and market ID for a specific line.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        metadata = single_event_line_tester.get_line_metadata(line_id)
        
        if not metadata:
            return {
                "success": False,
                "message": f"No metadata found for line {line_id}"
            }
        
        return {
            "success": True,
            "message": f"Metadata for line {line_id}",
            "data": {
                "line_id": metadata.line_id,
                "selection_name": metadata.selection_name,
                "prophetx_event_id": metadata.prophetx_event_id,
                "prophetx_market_id": metadata.prophetx_market_id,
                "market_type": metadata.market_type,
                "last_updated": metadata.last_updated.isoformat(),
                "can_cancel_by_market": metadata.prophetx_market_id is not None and metadata.prophetx_event_id is not None
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting line metadata: {str(e)}")

@router.post("/line-monitoring/test-single-event/test-cancel-preparation", response_model=Dict[str, Any])
async def test_cancel_preparation():
    """
    Test preparation for cancel_wagers_by_market calls
    
    This shows what parameters would be used for canceling wagers
    without actually canceling anything.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        metadata = single_event_line_tester.get_all_line_metadata()
        
        if not metadata:
            return {
                "success": False,
                "message": "No line metadata available"
            }
        
        # Prepare cancel parameters by market
        cancel_params = []
        markets_seen = set()
        
        for line_id, meta in metadata.items():
            if meta.prophetx_event_id and meta.prophetx_market_id:
                market_key = (meta.prophetx_event_id, meta.prophetx_market_id)
                
                if market_key not in markets_seen:
                    cancel_params.append({
                        "event_id": meta.prophetx_event_id,
                        "market_id": meta.prophetx_market_id,
                        "market_type": meta.market_type,
                        "lines_affected": []
                    })
                    markets_seen.add(market_key)
        
        # Add lines to each market
        for line_id, meta in metadata.items():
            if meta.prophetx_event_id and meta.prophetx_market_id:
                for param in cancel_params:
                    if (param["event_id"] == meta.prophetx_event_id and 
                        param["market_id"] == meta.prophetx_market_id):
                        param["lines_affected"].append({
                            "line_id": line_id,
                            "selection_name": meta.selection_name
                        })
        
        return {
            "success": True,
            "message": f"Prepared cancel parameters for {len(cancel_params)} markets",
            "data": {
                "total_markets": len(cancel_params),
                "total_lines": len(metadata),
                "cancel_params": cancel_params,
                "note": "These are the parameters that would be used for /mm/cancel_wagers_by_market calls"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error preparing cancel parameters: {str(e)}")

# Add this single endpoint to your markets.py router to test the metadata

@router.get("/line-monitoring/test-single-event/metadata", response_model=Dict[str, Any])
async def get_single_event_metadata():
    """
    Get metadata for all lines being monitored in the single event test
    
    This shows ProphetX event IDs and market IDs for each line.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        # Get all metadata
        metadata = single_event_line_tester.get_all_line_metadata()
        
        return {
            "success": True,
            "message": f"Retrieved metadata for {len(metadata)} lines",
            "data": {
                "total_lines": len(metadata),
                "line_details": [
                    {
                        "line_id": line_id,
                        "selection_name": meta.selection_name,
                        "prophetx_event_id": meta.prophetx_event_id,
                        "prophetx_market_id": meta.prophetx_market_id,
                        "market_type": meta.market_type,
                        "last_updated": meta.last_updated.isoformat(),
                        "ready_for_cancel": meta.prophetx_event_id is not None and meta.prophetx_market_id is not None
                    }
                    for line_id, meta in metadata.items()
                ]
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting metadata: {str(e)}")

@router.get("/line-monitoring/test-single-event/markets", response_model=Dict[str, Any])
async def get_markets_for_cancellation():
    """
    Get list of markets that can be cancelled in the current session
    
    This shows all the markets with their event_id and market_id
    that are available for cancellation.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        markets = single_event_line_tester.get_markets_for_cancellation()
        
        return {
            "success": True,
            "message": f"Found {len(markets)} markets available for cancellation",
            "data": {
                "total_markets": len(markets),
                "markets": markets,
                "note": "These are the parameters that would be used for cancel_wagers_by_market calls"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting markets for cancellation: {str(e)}")

@router.post("/line-monitoring/test-single-event/cancel-market/{market_id}", response_model=Dict[str, Any])
async def test_cancel_market(market_id: int):
    """
    Test cancelling all wagers for a specific market
    
    - **market_id**: ProphetX market ID to cancel (e.g., 251 for moneyline, 256 for spreads, 258 for totals)
    
    **Warning**: This will actually cancel your real bets if not in dry run mode!
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        # Show what would be cancelled before doing it
        affected_lines = []
        for line_id, metadata in single_event_line_tester.line_metadata.items():
            if metadata.prophetx_market_id == market_id:
                affected_lines.append({
                    "line_id": line_id,
                    "selection_name": metadata.selection_name
                })
        
        if not affected_lines:
            return {
                "success": False,
                "message": f"Market {market_id} not found in current session"
            }
        
        result = await single_event_line_tester.cancel_wagers_for_market(market_id)
        
        return {
            "success": result["success"],
            "message": result["message"],
            "data": result.get("data"),
            "affected_lines": affected_lines
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling market: {str(e)}")

@router.post("/line-monitoring/test-single-event/cancel-all-markets", response_model=Dict[str, Any])
async def test_cancel_all_markets():
    """
    Test cancelling all wagers for all markets in the current event
    
    **Warning**: This will cancel ALL your bets for this event if not in dry run mode!
    
    This simulates what would happen when odds change and we need to 
    cancel and replace all bets.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        # Show what markets would be cancelled
        markets = single_event_line_tester.get_markets_for_cancellation()
        
        result = await single_event_line_tester.cancel_all_wagers_for_event()
        
        return {
            "success": result["success"],
            "message": result["message"],
            "data": result.get("data"),
            "markets_before_cancel": markets
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling all markets: {str(e)}")

@router.post("/line-monitoring/test-single-event/simulate-odds-change", response_model=Dict[str, Any])
async def simulate_odds_change():
    """
    Simulate what happens when odds change
    
    This will:
    1. Show current markets and lines
    2. Cancel all wagers (simulating odds change response)
    3. Show the results
    
    **Warning**: This will cancel your real bets if not in dry run mode!
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        # Step 1: Show current state
        markets_before = single_event_line_tester.get_markets_for_cancellation()
        
        print("🎲 SIMULATING ODDS CHANGE")
        print("=" * 40)
        print(f"📊 Current markets: {len(markets_before)}")
        for market in markets_before:
            print(f"   Market {market['market_id']} ({market['market_type']}): {len(market['lines'])} lines")
        
        # Step 2: Cancel all wagers (as if odds changed)
        print("\\n🗑️ Cancelling all wagers due to 'odds change'...")
        cancel_result = await single_event_line_tester.cancel_all_wagers_for_event()
        
        # Step 3: Show results
        print("\\n✅ Odds change simulation complete")
        print(f"   Cancelled: {cancel_result.get('data', {}).get('successful_cancellations', 0)} markets")
        print("   New bets would be placed in next monitoring cycle")
        
        return {
            "success": True,
            "message": "Simulated odds change and cancellation",
            "data": {
                "simulation_type": "odds_change",
                "markets_before": markets_before,
                "cancellation_result": cancel_result,
                "next_step": "New bets will be placed in next monitoring cycle"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error simulating odds change: {str(e)}")

# Also add this utility endpoint to check ProphetX service directly
@router.post("/prophetx/test-cancel-market", response_model=Dict[str, Any])
async def test_prophetx_cancel_market(event_id: int, market_id: int):
    """
    Test the ProphetX cancel_wagers_by_market endpoint directly
    
    - **event_id**: ProphetX event ID
    - **market_id**: ProphetX market ID
    
    **Warning**: This will cancel real bets if not in dry run mode!
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        result = await prophetx_service.cancel_wagers_by_market(event_id, market_id)
        
        return {
            "success": result["success"],
            "message": f"Tested cancel for event {event_id}, market {market_id}",
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing ProphetX cancel: {str(e)}")
    
@router.post("/line-monitoring/test-single-event/check-odds", response_model=Dict[str, Any])
async def manual_odds_check():
    """
    Manually trigger a Pinnacle odds check
    
    Useful for testing the odds monitoring logic without waiting for the monitoring cycle.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        # Manually trigger odds monitoring
        await single_event_line_tester._monitor_pinnacle_odds_changes()
        
        return {
            "success": True,
            "message": "Manual odds check completed",
            "data": {
                "session_id": single_event_line_tester.session.odds_api_event_id,
                "odds_changes_detected_total": getattr(single_event_line_tester, 'odds_changes_detected', 0)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during manual odds check: {str(e)}")
    
# ADD this endpoint to your markets.py router

@router.get("/line-monitoring/test-single-event/debug-odds", response_model=Dict[str, Any])
async def debug_odds_monitoring():
    """
    Debug odds monitoring - shows current vs original odds comparison
    
    This helps troubleshoot odds monitoring issues by showing:
    - What original odds were stored
    - What current odds are being fetched  
    - How they compare
    - Why changes might/might not be detected
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        debug_info = await single_event_line_tester.debug_odds_comparison()
        
        return {
            "success": True,
            "message": "Odds monitoring debug information",
            "data": debug_info
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting debug info: {str(e)}")

@router.post("/line-monitoring/test-single-event/force-odds-check", response_model=Dict[str, Any])
async def force_odds_check():
    """
    Force an immediate odds check (for testing)
    
    This manually triggers the odds monitoring logic without waiting 
    for the next monitoring cycle.
    """
    try:
        from app.services.single_event_line_tester import single_event_line_tester
        
        if not single_event_line_tester.session or not single_event_line_tester.session.is_active:
            return {
                "success": False,
                "message": "No active single event test session"
            }
        
        print("🔄 MANUAL ODDS CHECK TRIGGERED")
        
        # Run the odds monitoring logic manually
        await single_event_line_tester._monitor_pinnacle_odds_changes()
        
        return {
            "success": True,
            "message": "Manual odds check completed",
            "data": {
                "session_id": single_event_line_tester.session.odds_api_event_id,
                "event_name": single_event_line_tester.session.event_name,
                "last_check_time": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during manual odds check: {str(e)}")