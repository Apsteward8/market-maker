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