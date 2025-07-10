#!/usr/bin/env python3
"""
ProphetX Debug & Management Router
Comprehensive endpoints for diagnosing and managing ProphetX operations
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import time

# You'll need to import your enhanced service
from app.services.prophetx_service import prophetx_service
from app.services.prophetx_wager_service import prophetx_wager_service
from app.services.prophetx_wager_api import ProphetXWagerAPI

router = APIRouter()

prophetx_wager_api = ProphetXWagerAPI(prophetx_service)

# ============================================================================
# DIAGNOSTIC ENDPOINTS
# ============================================================================

@router.get("/diagnostics/full", response_model=Dict[str, Any])
async def run_full_prophetx_diagnostics():
    """
    Run comprehensive ProphetX API diagnostics
    
    This endpoint tests:
    - Authentication status
    - API endpoint connectivity
    - Data retrieval capabilities
    - Current wager status
    
    Use this first to identify any basic connectivity issues.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        diagnostics = await prophetx_service.run_diagnostics()
        
        return {
            "success": True,
            "message": "ProphetX diagnostics completed",
            "data": diagnostics,
            "recommendations": diagnostics.get("recommendations", [])
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running diagnostics: {str(e)}")

@router.get("/diagnostics/auth", response_model=Dict[str, Any])
async def check_prophetx_auth():
    """
    Check ProphetX authentication status
    
    Returns current token status and expiration times.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        # Force re-authentication to test
        auth_result = await prophetx_service.authenticate()
        
        return {
            "success": True,
            "message": "Authentication check completed",
            "data": auth_result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication check failed: {str(e)}")

@router.get("/diagnostics/endpoints", response_model=Dict[str, Any])
async def test_prophetx_endpoints():
    """
    Test individual ProphetX API endpoints
    
    Checks each critical endpoint to identify which ones are working.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        # Test key endpoints individually
        test_results = {}
        
        # Test wager histories
        try:
            wagers = await prophetx_service.get_all_my_wagers(include_matched=False, days_back=1)
            test_results["get_active_wagers"] = {
                "success": True,
                "count": len(wagers),
                "message": f"Retrieved {len(wagers)} active wagers"
            }
        except Exception as e:
            test_results["get_active_wagers"] = {
                "success": False,
                "error": str(e)
            }
        
        # Test matched bets
        try:
            matched = await prophetx_service.get_all_my_wagers(include_matched=True, days_back=1)
            matched_count = len([w for w in matched if w.get('matching_status') in ['fully_matched', 'partially_matched']])
            test_results["get_matched_bets"] = {
                "success": True,
                "count": matched_count,
                "message": f"Retrieved {matched_count} matched bets"
            }
        except Exception as e:
            test_results["get_matched_bets"] = {
                "success": False,
                "error": str(e)
            }
        
        return {
            "success": True,
            "message": "Endpoint testing completed",
            "data": test_results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing endpoints: {str(e)}")

# ============================================================================
# LINE MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/lines/{line_id}/details", response_model=Dict[str, Any])
async def get_line_details(line_id: str):
    """
    Get detailed information about a specific betting line
    
    - **line_id**: ProphetX line ID
    
    Returns current odds, status, and availability for the line.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        line_details = await prophetx_service.get_line_details(line_id)
        
        if line_details:
            return {
                "success": True,
                "message": f"Line details retrieved for {line_id}",
                "data": line_details
            }
        else:
            return {
                "success": False,
                "message": f"Line {line_id} not found",
                "line_id": line_id
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting line details: {str(e)}")

@router.get("/lines/{line_id}/our-bets", response_model=Dict[str, Any])
async def get_our_bets_for_line(line_id: str):
    """
    Get all of our bets (active and inactive) for a specific line
    
    - **line_id**: ProphetX line ID
    
    This is crucial for understanding our current position on each line.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        our_bets = await prophetx_service.get_my_bets_for_line(line_id)
        
        # Calculate summary statistics
        total_stake = sum(bet.get('stake', 0) for bet in our_bets)
        matched_stake = sum(bet.get('matched_stake', 0) for bet in our_bets if bet.get('matched_stake'))
        unmatched_stake = total_stake - matched_stake
        
        active_bets = [bet for bet in our_bets if bet.get('status') == 'open']
        
        return {
            "success": True,
            "message": f"Found {len(our_bets)} bets for line {line_id}",
            "data": {
                "line_id": line_id,
                "total_bets": len(our_bets),
                "active_bets": len(active_bets),
                "total_stake": total_stake,
                "matched_stake": matched_stake,
                "unmatched_stake": unmatched_stake,
                "bets": our_bets
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting bets for line: {str(e)}")

@router.get("/events/{event_id}/lines", response_model=Dict[str, Any])
async def get_lines_for_event(event_id: int):
    """
    Get all betting lines for a specific event
    
    - **event_id**: ProphetX event ID
    
    Returns all available lines across all markets for this event.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        lines = await prophetx_service.get_lines_for_event(event_id)
        
        # Group lines by market type
        lines_by_market = {}
        for line in lines:
            market_type = line.get('market_type', 'unknown')
            if market_type not in lines_by_market:
                lines_by_market[market_type] = []
            lines_by_market[market_type].append(line)
        
        return {
            "success": True,
            "message": f"Found {len(lines)} lines for event {event_id}",
            "data": {
                "event_id": event_id,
                "total_lines": len(lines),
                "lines_by_market": lines_by_market,
                "all_lines": lines
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting lines for event: {str(e)}")

# ============================================================================
# POSITION MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/events/{event_id}/position", response_model=Dict[str, Any])
async def get_position_for_event(event_id: int):
    """
    Get complete position summary for a specific event
    
    - **event_id**: ProphetX event ID
    
    Shows all our bets, stakes, and exposure for this event across all markets.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        position_summary = await prophetx_service.get_position_summary_for_event(event_id)
        
        return {
            "success": True,
            "message": f"Position summary for event {event_id}",
            "data": position_summary
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting position summary: {str(e)}")

@router.get("/events/{event_id}/liquidity-needs", response_model=Dict[str, Any])
async def get_liquidity_needs_for_event(
    event_id: int,
    max_position_per_line: float = Query(500.0, description="Maximum stake per line")
):
    """
    Identify lines that need more liquidity for a specific event
    
    - **event_id**: ProphetX event ID
    - **max_position_per_line**: Maximum total stake allowed per line
    
    Returns lines that are under the position limit and can accept more bets.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        lines_needing_liquidity = await prophetx_service.get_lines_needing_liquidity(
            event_id, max_position_per_line
        )
        
        return {
            "success": True,
            "message": f"Found {len(lines_needing_liquidity)} lines needing more liquidity",
            "data": {
                "event_id": event_id,
                "max_position_per_line": max_position_per_line,
                "lines_needing_liquidity": lines_needing_liquidity,
                "total_available_liquidity": sum(line["available_liquidity"] for line in lines_needing_liquidity)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting liquidity needs: {str(e)}")

# ============================================================================
# WAGER MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/wagers/all", response_model=Dict[str, Any])
async def get_all_our_wagers(
    include_matched: bool = Query(True, description="Include matched/settled bets"),
    days_back: int = Query(7, description="How many days back to look")
):
    """
    Get all of our wagers with comprehensive filtering
    
    - **include_matched**: Whether to include matched/settled bets
    - **days_back**: How many days back to retrieve
    
    This is the master endpoint for understanding all our betting activity.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        all_wagers = await prophetx_service.get_all_my_wagers(include_matched, days_back)
        
        # Categorize wagers
        active_wagers = [w for w in all_wagers if w.get('matching_status') == 'unmatched']
        matched_wagers = [w for w in all_wagers if w.get('matching_status') in ['fully_matched', 'partially_matched']]
        other_wagers = [w for w in all_wagers if w not in active_wagers and w not in matched_wagers]
        
        # Calculate totals
        total_stake = sum(w.get('stake', 0) for w in all_wagers)
        total_matched_stake = sum(w.get('matched_stake', 0) for w in all_wagers if w.get('matched_stake'))
        
        return {
            "success": True,
            "message": f"Retrieved {len(all_wagers)} wagers from last {days_back} days",
            "data": {
                "total_wagers": len(all_wagers),
                "active_wagers": len(active_wagers),
                "matched_wagers": len(matched_wagers),
                "other_wagers": len(other_wagers),
                "total_stake": total_stake,
                "total_matched_stake": total_matched_stake,
                "unmatched_stake": total_stake - total_matched_stake,
                "wagers_by_category": {
                    "active": active_wagers,
                    "matched": matched_wagers,
                    "other": other_wagers
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting all wagers: {str(e)}")

@router.get("/wagers/{wager_id}/comprehensive", response_model=Dict[str, Any])
async def get_wager_comprehensive_details(wager_id: str):
    """
    Get comprehensive details for a specific wager with multiple lookup methods
    
    - **wager_id**: ProphetX wager ID or external ID
    
    Uses multiple methods to find the wager and determine its current status.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        wager_details = await prophetx_service.get_wager_details_comprehensive(wager_id)
        
        return {
            "success": True,
            "message": f"Comprehensive lookup for wager {wager_id}",
            "data": wager_details
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting comprehensive wager details: {str(e)}")

# ============================================================================
# BULK OPERATIONS ENDPOINTS
# ============================================================================

@router.post("/events/{event_id}/cancel-all-bets", response_model=Dict[str, Any])
async def cancel_all_bets_for_event(event_id: int):
    """
    Cancel all our active bets for a specific event
    
    - **event_id**: ProphetX event ID
    
    **WARNING**: This cancels ALL active bets for the event. Use with caution.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        result = await prophetx_service.cancel_all_bets_for_event(event_id)
        
        return {
            "success": result.get("success", False),
            "message": f"Cancelled bets for event {event_id}",
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling bets for event: {str(e)}")

# ============================================================================
# DEBUGGING HELPERS
# ============================================================================

@router.get("/debug/bet-monitoring", response_model=Dict[str, Any])
async def debug_bet_monitoring_issues():
    """
    Diagnose common bet monitoring issues
    
    This endpoint checks for typical problems that prevent proper bet monitoring:
    - Data format inconsistencies
    - Missing external_id mappings
    - Timing issues with bet status updates
    """
    try:
        from app.services.prophetx_service import prophetx_service
        from app.services.market_maker_service import market_maker_service
        
        debug_info = {
            "our_system_bets": {},
            "prophetx_data": {},
            "matching_analysis": {},
            "recommendations": []
        }
        
        # Get our system's view of bets
        our_bets = list(market_maker_service.all_bets.values())
        active_our_bets = [bet for bet in our_bets if bet.is_active]
        
        debug_info["our_system_bets"] = {
            "total_bets": len(our_bets),
            "active_bets": len(active_our_bets),
            "sample_external_ids": [bet.external_id for bet in our_bets[:5]]
        }
        
        # Get ProphetX's view of our bets
        prophetx_active = await prophetx_service.get_all_my_wagers(include_matched=False, days_back=1)
        prophetx_matched = await prophetx_service.get_all_my_wagers(include_matched=True, days_back=1)
        prophetx_matched_only = [w for w in prophetx_matched if w.get('matching_status') in ['fully_matched', 'partially_matched']]
        
        debug_info["prophetx_data"] = {
            "active_wagers": len(prophetx_active),
            "matched_wagers": len(prophetx_matched_only),
            "sample_external_ids": [w.get('external_id') for w in prophetx_active[:5] if w.get('external_id')]
        }
        
        # Analyze matching
        our_external_ids = set(bet.external_id for bet in our_bets)
        prophetx_external_ids = set(w.get('external_id') for w in prophetx_active + prophetx_matched if w.get('external_id'))
        
        matched_ids = our_external_ids.intersection(prophetx_external_ids)
        our_missing = our_external_ids - prophetx_external_ids
        prophetx_extra = prophetx_external_ids - our_external_ids
        
        debug_info["matching_analysis"] = {
            "matched_external_ids": len(matched_ids),
            "our_missing_from_prophetx": len(our_missing),
            "prophetx_extra_not_ours": len(prophetx_extra),
            "match_rate": len(matched_ids) / len(our_external_ids) if our_external_ids else 0
        }
        
        # Generate recommendations
        if len(matched_ids) == 0:
            debug_info["recommendations"].append("No external_id matches found - check external_id format consistency")
        
        if len(our_missing) > len(matched_ids):
            debug_info["recommendations"].append("Many of our bets missing from ProphetX - check if bets are actually being placed")
        
        if debug_info["matching_analysis"]["match_rate"] < 0.8:
            debug_info["recommendations"].append("Low match rate - investigate external_id inconsistencies")
        
        if len(active_our_bets) > 0 and len(prophetx_active) == 0:
            debug_info["recommendations"].append("We think we have active bets but ProphetX shows none - check bet placement")
        
        return {
            "success": True,
            "message": "Bet monitoring diagnosis completed",
            "data": debug_info
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error debugging bet monitoring: {str(e)}")

@router.get("/debug/compare-bet-data/{external_id}", response_model=Dict[str, Any])
async def compare_bet_data(external_id: str):
    """
    Compare our system's view of a bet with ProphetX's view
    
    - **external_id**: External bet ID to compare
    
    Helps identify discrepancies between our tracking and ProphetX data.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        from app.services.market_maker_service import market_maker_service
        
        comparison = {
            "external_id": external_id,
            "our_system_data": None,
            "prophetx_data": None,
            "discrepancies": [],
            "status_analysis": {}
        }
        
        # Get our system's data
        if external_id in market_maker_service.all_bets:
            our_bet = market_maker_service.all_bets[external_id]
            comparison["our_system_data"] = {
                "bet_id": our_bet.bet_id,
                "line_id": our_bet.line_id,
                "selection_name": our_bet.selection_name,
                "odds": our_bet.odds,
                "stake": our_bet.stake,
                "status": our_bet.status.value,
                "matched_stake": our_bet.matched_stake,
                "unmatched_stake": our_bet.unmatched_stake,
                "is_active": our_bet.is_active,
                "placed_at": our_bet.placed_at.isoformat()
            }
        else:
            comparison["discrepancies"].append("Bet not found in our system")
        
        # Get ProphetX data
        prophetx_details = await prophetx_service.get_wager_details_comprehensive(external_id)
        comparison["prophetx_data"] = prophetx_details
        
        # Analyze discrepancies
        if comparison["our_system_data"] and prophetx_details.get("details"):
            our_data = comparison["our_system_data"]
            px_data = prophetx_details["details"]
            
            # Check stake
            if our_data["stake"] != px_data.get("stake", 0):
                comparison["discrepancies"].append(f"Stake mismatch: Our {our_data['stake']} vs ProphetX {px_data.get('stake', 'N/A')}")
            
            # Check odds
            if our_data["odds"] != px_data.get("odds", 0):
                comparison["discrepancies"].append(f"Odds mismatch: Our {our_data['odds']} vs ProphetX {px_data.get('odds', 'N/A')}")
            
            # Status analysis
            comparison["status_analysis"] = {
                "our_status": our_data["status"],
                "our_is_active": our_data["is_active"],
                "prophetx_status": px_data.get("status", "unknown"),
                "prophetx_matching_status": px_data.get("matching_status", "unknown"),
                "status_consistent": our_data["is_active"] == (px_data.get("status") == "open")
            }
        
        if not comparison["discrepancies"]:
            comparison["discrepancies"].append("No major discrepancies found")
        
        return {
            "success": True,
            "message": f"Bet comparison for {external_id}",
            "data": comparison
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing bet data: {str(e)}")

@router.get("/wagers/histories", response_model=Dict[str, Any])
async def get_wager_histories(
    days_back: int = Query(1, description="How many days back to look"),
    matching_status: Optional[str] = Query(None, description="Filter by matching status", regex="^(unmatched|fully_matched|partially_matched)$"),
    status: Optional[str] = Query(None, description="Filter by status", regex="^(void|closed|canceled|manually_settled|inactive|wiped|open|invalid|settled)$"),
    event_id: Optional[str] = Query(None, description="Filter by specific event ID"),
    limit: int = Query(100, description="Maximum results", le=1000)
):
    """
    Get wager histories with filtering options
    
    **Key filters:**
    - **matching_status**: 
      - `unmatched` = Still waiting for someone to bet against us
      - `fully_matched` = Someone bet against us (fully filled)  
      - `partially_matched` = Someone bet against us (partially filled)
    - **status**:
      - `open` = Active bet
      - `closed` = Bet closed/settled
      - `canceled` = Bet was cancelled
    - **days_back**: How far back to look for wagers
    
    This is your primary endpoint for understanding all your betting activity.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        
        # Calculate timestamp range
        now_timestamp = int(time.time())
        from_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
        
        result = await prophetx_wager_service.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status=matching_status,
            status=status,
            event_id=event_id,
            limit=limit
        )
        
        if result["success"]:
            # Add some summary statistics
            wagers = result["wagers"]
            
            summary = {
                "total_wagers": len(wagers),
                "by_matching_status": {},
                "by_status": {},
                "total_stake": 0,
                "total_matched_stake": 0,
                "total_unmatched_stake": 0
            }
            
            for wager in wagers:
                # Count by matching status
                match_status = wager.get("matching_status", "unknown")
                summary["by_matching_status"][match_status] = summary["by_matching_status"].get(match_status, 0) + 1
                
                # Count by status
                wager_status = wager.get("status", "unknown")
                summary["by_status"][wager_status] = summary["by_status"].get(wager_status, 0) + 1
                
                # Sum stakes
                summary["total_stake"] += wager.get("stake", 0)
                summary["total_matched_stake"] += wager.get("matched_stake", 0)
                summary["total_unmatched_stake"] += wager.get("unmatched_stake", 0)
            
            return {
                "success": True,
                "message": f"Retrieved {len(wagers)} wagers from last {days_back} days",
                "data": {
                    "wagers": wagers,
                    "summary": summary,
                    "filters_applied": {
                        "days_back": days_back,
                        "matching_status": matching_status,
                        "status": status,
                        "event_id": event_id,
                        "limit": limit
                    },
                    "next_cursor": result.get("next_cursor"),
                    "last_synced_at": result.get("last_synced_at")
                }
            }
        else:
            return {
                "success": False,
                "message": "Failed to retrieve wager histories",
                "error": result.get("error", "Unknown error")
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting wager histories: {str(e)}")

@router.get("/wagers/active", response_model=Dict[str, Any])
async def get_active_wagers(
    days_back: int = Query(1, description="How many days back to look"),
    event_id: Optional[str] = Query(None, description="Filter by specific event ID")
):
    """
    Get all active (unmatched, open) wagers
    
    These are bets we placed that are still waiting for someone to bet against us.
    This is what you want to monitor for fills.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        
        # Calculate timestamp range
        now_timestamp = int(time.time())
        from_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
        
        result = await prophetx_wager_service.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status="unmatched",
            status="open",
            event_id=event_id,
            limit=1000
        )
        
        if result["success"]:
            wagers = result["wagers"]
            
            # Group by event for better organization
            by_event = {}
            total_unmatched_stake = 0
            
            for wager in wagers:
                event_id = wager.get("sport_event_id", "unknown")
                if event_id not in by_event:
                    by_event[event_id] = []
                by_event[event_id].append(wager)
                total_unmatched_stake += wager.get("unmatched_stake", 0)
            
            return {
                "success": True,
                "message": f"Found {len(wagers)} active wagers",
                "data": {
                    "total_active_wagers": len(wagers),
                    "total_unmatched_stake": total_unmatched_stake,
                    "events_with_active_bets": len(by_event),
                    "wagers": wagers,
                    "wagers_by_event": by_event
                }
            }
        else:
            return {
                "success": False,
                "message": "Failed to retrieve active wagers",
                "error": result.get("error", "Unknown error")
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting active wagers: {str(e)}")

@router.get("/wagers/matched", response_model=Dict[str, Any])
async def get_matched_wagers(
    days_back: int = Query(1, description="How many days back to look"),
    event_id: Optional[str] = Query(None, description="Filter by specific event ID")
):
    """
    Get all matched wagers (fully_matched + partially_matched)
    
    These are bets where someone bet against us. This is what you want to check
    to see which of your bets got filled.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        
        # Calculate timestamp range  
        now_timestamp = int(time.time())
        from_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
        
        all_matched = []
        
        # Get fully matched
        fully_matched_result = await prophetx_wager_service.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status="fully_matched",
            event_id=event_id,
            limit=1000
        )
        
        if fully_matched_result["success"]:
            all_matched.extend(fully_matched_result["wagers"])
        
        # Get partially matched
        partially_matched_result = await prophetx_wager_service.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status="partially_matched",
            event_id=event_id,
            limit=1000
        )
        
        if partially_matched_result["success"]:
            all_matched.extend(partially_matched_result["wagers"])
        
        # Calculate summary statistics
        total_matched_stake = sum(w.get("matched_stake", 0) for w in all_matched)
        fully_matched_count = sum(1 for w in all_matched if w.get("matching_status") == "fully_matched")
        partially_matched_count = sum(1 for w in all_matched if w.get("matching_status") == "partially_matched")
        
        # Group by event
        by_event = {}
        for wager in all_matched:
            event_id = wager.get("sport_event_id", "unknown")
            if event_id not in by_event:
                by_event[event_id] = []
            by_event[event_id].append(wager)
        
        return {
            "success": True,
            "message": f"Found {len(all_matched)} matched wagers",
            "data": {
                "total_matched_wagers": len(all_matched),
                "fully_matched_count": fully_matched_count,
                "partially_matched_count": partially_matched_count,
                "total_matched_stake": total_matched_stake,
                "events_with_matched_bets": len(by_event),
                "wagers": all_matched,
                "wagers_by_event": by_event
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting matched wagers: {str(e)}")

@router.get("/wagers/{wager_id}", response_model=Dict[str, Any])
async def get_wager_by_id(wager_id: str):
    """
    Get a specific wager by its ProphetX wager ID
    
    - **wager_id**: The ProphetX wager ID (from the wager_id field)
    
    Use this to get detailed information about a specific bet.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        
        result = await prophetx_wager_service.get_wager_by_id(wager_id)
        
        if result["success"]:
            wager = result["wager"]
            
            # Also get matching details for this wager
            matching_result = await prophetx_wager_service.get_wager_matching_detail(wager_id=wager_id)
            
            return {
                "success": True,
                "message": f"Retrieved wager {wager_id}",
                "data": {
                    "wager": wager,
                    "matching_details": matching_result.get("matching_details", []) if matching_result["success"] else [],
                    "last_synced_at": result.get("last_synced_at")
                }
            }
        else:
            return {
                "success": False,
                "message": f"Wager {wager_id} not found",
                "error": result.get("error", "Wager not found")
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting wager by ID: {str(e)}")

@router.get("/wagers/search/external/{external_id}", response_model=Dict[str, Any])
async def search_wager_by_external_id(external_id: str):
    """
    Search for a wager by its external_id (our system's ID)
    
    - **external_id**: The external_id we assigned when placing the bet
    
    This is crucial for linking our system's bets with ProphetX's data.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        
        wager = await prophetx_wager_service.get_wager_by_external_id(external_id)
        
        if wager:
            # Also get matching details if available
            wager_id = wager.get("wager_id")
            matching_details = []
            
            if wager_id:
                matching_result = await prophetx_wager_service.get_wager_matching_detail(wager_id=wager_id)
                if matching_result["success"]:
                    matching_details = matching_result["matching_details"]
            
            return {
                "success": True,
                "message": f"Found wager with external_id {external_id}",
                "data": {
                    "wager": wager,
                    "matching_details": matching_details
                }
            }
        else:
            return {
                "success": False,
                "message": f"No wager found with external_id {external_id}",
                "external_id": external_id
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching by external_id: {str(e)}")

@router.get("/wagers/comprehensive/{identifier}", response_model=Dict[str, Any])
async def get_comprehensive_wager_status(identifier: str):
    """
    Get comprehensive status for a wager using multiple lookup methods
    
    - **identifier**: Could be either a ProphetX wager_id or our external_id
    
    This endpoint tries multiple methods to find the wager and gives you
    the most complete picture of its current status.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        
        result = await prophetx_wager_service.get_comprehensive_wager_status(identifier)
        
        return {
            "success": True,
            "message": f"Comprehensive lookup for {identifier}",
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting comprehensive wager status: {str(e)}")

# ============================================================================
# DEBUGGING AND COMPARISON ENDPOINTS
# ============================================================================

@router.get("/debug/compare-our-bets", response_model=Dict[str, Any])
async def compare_our_bets_with_prophetx():
    """
    Compare our system's bets with what ProphetX shows
    
    This is the key debugging endpoint for fixing your bet monitoring issues.
    It shows:
    1. What bets our system thinks are active
    2. What ProphetX says about those same bets
    3. Discrepancies between the two
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        from app.services.market_maker_service import market_maker_service
        
        comparison = {
            "our_system_bets": {},
            "prophetx_data": {},
            "matching_analysis": {},
            "discrepancies": [],
            "recommendations": []
        }
        
        # Get our system's view of active bets
        our_bets = list(market_maker_service.all_bets.values())
        our_active_bets = [bet for bet in our_bets if bet.is_active]
        
        comparison["our_system_bets"] = {
            "total_bets": len(our_bets),
            "active_bets": len(our_active_bets),
            "external_ids": [bet.external_id for bet in our_bets]
        }
        
        # Get ProphetX's view of our bets
        prophetx_active = await prophetx_wager_service.get_all_active_wagers(days_back=1)
        prophetx_matched = await prophetx_wager_service.get_all_matched_wagers(days_back=1)
        
        comparison["prophetx_data"] = {
            "active_wagers": len(prophetx_active),
            "matched_wagers": len(prophetx_matched),
            "active_external_ids": [w.get("external_id") for w in prophetx_active if w.get("external_id")],
            "matched_external_ids": [w.get("external_id") for w in prophetx_matched if w.get("external_id")]
        }
        
        # Analyze matching
        our_external_ids = set(bet.external_id for bet in our_bets)
        prophetx_all_external_ids = set(
            [w.get("external_id") for w in prophetx_active + prophetx_matched if w.get("external_id")]
        )
        prophetx_active_external_ids = set(
            [w.get("external_id") for w in prophetx_active if w.get("external_id")]
        )
        prophetx_matched_external_ids = set(
            [w.get("external_id") for w in prophetx_matched if w.get("external_id")]
        )
        
        matched_ids = our_external_ids.intersection(prophetx_all_external_ids)
        our_missing_from_prophetx = our_external_ids - prophetx_all_external_ids
        prophetx_extra = prophetx_all_external_ids - our_external_ids
        
        # Check for status mismatches
        status_mismatches = []
        for bet in our_active_bets:
            if bet.external_id in prophetx_matched_external_ids:
                status_mismatches.append({
                    "external_id": bet.external_id,
                    "our_status": "active",
                    "prophetx_status": "matched",
                    "issue": "We think it's active but ProphetX shows it as matched"
                })
        
        comparison["matching_analysis"] = {
            "total_matches": len(matched_ids),
            "our_missing_from_prophetx": len(our_missing_from_prophetx),
            "prophetx_extra": len(prophetx_extra),
            "status_mismatches": len(status_mismatches),
            "match_rate": len(matched_ids) / len(our_external_ids) if our_external_ids else 0
        }
        
        comparison["discrepancies"] = status_mismatches
        
        # Generate recommendations
        if len(matched_ids) == 0:
            comparison["recommendations"].append("❌ NO MATCHES FOUND - Check external_id format or bet placement")
        
        if len(our_missing_from_prophetx) > 0:
            comparison["recommendations"].append(f"⚠️ {len(our_missing_from_prophetx)} of our bets not found on ProphetX - Check if bets are actually being placed")
        
        if len(status_mismatches) > 0:
            comparison["recommendations"].append(f"🎯 {len(status_mismatches)} STATUS MISMATCHES - These bets got filled but our system doesn't know!")
        
        if comparison["matching_analysis"]["match_rate"] < 0.8:
            comparison["recommendations"].append("📊 Low match rate - Investigate external_id consistency")
        
        if not comparison["recommendations"]:
            comparison["recommendations"].append("✅ No major issues detected")
        
        return {
            "success": True,
            "message": "Bet comparison completed",
            "data": comparison
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing bets: {str(e)}")

@router.get("/debug/find-filled-bets", response_model=Dict[str, Any])
async def find_filled_bets():
    """
    Find bets that got filled but our system doesn't know about it
    
    This is the smoking gun endpoint for your bet monitoring issues.
    It finds bets that are matched on ProphetX but still marked as active in our system.
    """
    try:
        from app.services.prophetx_wager_service import prophetx_wager_service
        from app.services.market_maker_service import market_maker_service
        
        print("🔍 Looking for filled bets that our system missed...")
        
        # Get our active bets
        our_active_bets = [bet for bet in market_maker_service.all_bets.values() if bet.is_active]
        our_active_external_ids = [bet.external_id for bet in our_active_bets]
        
        if not our_active_external_ids:
            return {
                "success": True,
                "message": "No active bets in our system to check",
                "data": {"filled_bets_found": []}
            }
        
        # Get matched bets from ProphetX
        prophetx_matched = await prophetx_wager_service.get_all_matched_wagers(days_back=1)
        
        # Find our bets that are matched on ProphetX but active in our system
        filled_bets_found = []
        
        for matched_wager in prophetx_matched:
            external_id = matched_wager.get("external_id")
            
            if external_id in our_active_external_ids:
                # Found a mismatch!
                our_bet = next(bet for bet in our_active_bets if bet.external_id == external_id)
                
                filled_bets_found.append({
                    "external_id": external_id,
                    "our_system_status": {
                        "status": our_bet.status.value,
                        "is_active": our_bet.is_active,
                        "matched_stake": our_bet.matched_stake,
                        "unmatched_stake": our_bet.unmatched_stake
                    },
                    "prophetx_status": {
                        "status": matched_wager.get("status"),
                        "matching_status": matched_wager.get("matching_status"),
                        "matched_stake": matched_wager.get("matched_stake"),
                        "unmatched_stake": matched_wager.get("unmatched_stake"),
                        "odds": matched_wager.get("odds"),
                        "stake": matched_wager.get("stake")
                    },
                    "action_needed": "Update our system to mark this bet as matched"
                })
        
        return {
            "success": True,
            "message": f"Found {len(filled_bets_found)} bets that got filled but our system doesn't know",
            "data": {
                "total_active_bets_checked": len(our_active_bets),
                "filled_bets_found": filled_bets_found,
                "action_needed": len(filled_bets_found) > 0
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error finding filled bets: {str(e)}")
    
@router.get("/wager-histories", response_model=Dict[str, Any])
async def get_wager_histories(
    from_days_back: int = Query(7, description="How many days back to start from"),
    to_days_back: int = Query(0, description="How many days back to end (0 = now)"),
    limit: int = Query(100, description="Max wagers to return (max 1000)"),
    matching_status: Optional[str] = Query(None, description="Filter by matching status: unmatched, fully_matched, partially_matched"),
    status: Optional[str] = Query(None, description="Filter by status: void, closed, canceled, manually_settled, inactive, wiped, open, invalid, settled"),
    event_id: Optional[str] = Query(None, description="Filter by specific event ID"),
    market_id: Optional[str] = Query(None, description="Filter by specific market ID"),
    next_cursor: Optional[str] = Query(None, description="Pagination cursor")
):
    """
    Get wager histories using ProphetX official API
    
    This is a direct wrapper around ProphetX's /v2/mm/get_wager_histories endpoint.
    
    **Parameters:**
    - **from_days_back**: How many days back to start from (7 = last week)
    - **to_days_back**: How many days back to end (0 = now)
    - **limit**: Maximum wagers to return (max 1000)
    - **matching_status**: Filter by matching status
    - **status**: Filter by wager status
    - **event_id**: Filter by specific event
    - **market_id**: Filter by specific market
    - **next_cursor**: For pagination
    
    **Example usage:**
    - Get all active wagers: `?matching_status=unmatched&status=open`
    - Get matched wagers from yesterday: `?matching_status=fully_matched&from_days_back=1`
    - Get all wagers for specific event: `?event_id=12345`
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        # Initialize the wager API
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        # Calculate timestamps
        now = int(time.time())
        from_timestamp = now - (from_days_back * 24 * 60 * 60)
        to_timestamp = now - (to_days_back * 24 * 60 * 60)
        
        result = await wager_api.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            limit=limit,
            matching_status=matching_status,
            status=status,
            event_id=event_id,
            market_id=market_id,
            next_cursor=next_cursor
        )
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Retrieved {result['total_retrieved']} wagers",
                "data": {
                    "wagers": result["wagers"],
                    "next_cursor": result["next_cursor"],
                    "last_synced_at": result["last_synced_at"],
                    "total_retrieved": result["total_retrieved"],
                    "query_params": {
                        "from_days_back": from_days_back,
                        "to_days_back": to_days_back,
                        "matching_status": matching_status,
                        "status": status,
                        "event_id": event_id
                    }
                }
            }
        else:
            return {
                "success": False,
                "message": "Failed to retrieve wager histories",
                "error": result.get("error", "Unknown error"),
                "status_code": result.get("status_code")
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting wager histories: {str(e)}")

@router.get("/wager/{wager_id}", response_model=Dict[str, Any])
async def get_wager_by_id(wager_id: str):
    """
    Get specific wager by wager ID
    
    This uses ProphetX's /mm/get_wager/{id} endpoint to get detailed information
    about a specific wager.
    
    - **wager_id**: ProphetX wager ID (e.g., "wager_id_123_xyz")
    
    **Returns:**
    - Complete wager information including matching status, stakes, odds, etc.
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        result = await wager_api.get_wager_by_id(wager_id)
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Retrieved wager {wager_id}",
                "data": {
                    "wager": result["wager"],
                    "last_synced_at": result["last_synced_at"]
                }
            }
        else:
            status_code = result.get("status_code", 500)
            if status_code == 404:
                raise HTTPException(status_code=404, detail=f"Wager {wager_id} not found")
            else:
                return {
                    "success": False,
                    "message": f"Failed to retrieve wager {wager_id}",
                    "error": result.get("error", "Unknown error")
                }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting wager: {str(e)}")

@router.get("/wager/{wager_id}/matching-details", response_model=Dict[str, Any])
async def get_wager_matching_details(
    wager_id: str,
    limit: int = Query(100, description="Max details to return (max 100)"),
    next_cursor: Optional[str] = Query(None, description="Pagination cursor")
):
    """
    Get detailed matching information for a specific wager
    
    This uses ProphetX's /v2/mm/get_wager_matching_detail endpoint to get
    granular information about how a wager was matched.
    
    - **wager_id**: ProphetX wager ID
    - **limit**: Maximum details to return (max 100)
    - **next_cursor**: For pagination
    
    **Use this when:**
    - A wager shows as matched and you want to see the exact matching details
    - You need to understand profit/loss breakdown for a matched wager
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        result = await wager_api.get_wager_matching_detail(wager_id, limit, next_cursor)
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Retrieved {result['total_details']} matching details",
                "data": {
                    "matching_details": result["matching_details"],
                    "next_cursor": result["next_cursor"],
                    "last_synced_at": result["last_synced_at"],
                    "total_details": result["total_details"]
                }
            }
        else:
            return {
                "success": False,
                "message": f"Failed to retrieve matching details for {wager_id}",
                "error": result.get("error", "Unknown error")
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting matching details: {str(e)}")

# ============================================================================
# CONVENIENCE ENDPOINTS (Common Use Cases)
# ============================================================================

@router.get("/wagers/active", response_model=Dict[str, Any])
async def get_active_wagers(days_back: int = Query(7, description="How many days back to look")):
    """
    Get all active (unmatched, open) wagers
    
    This is a convenience endpoint that filters for wagers that are:
    - matching_status = "unmatched"
    - status = "open"
    
    These are wagers that are currently live and waiting to be matched.
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        active_wagers = await wager_api.get_all_active_wagers(days_back)
        
        # Calculate summary statistics
        total_stake = sum(wager.get('stake', 0) for wager in active_wagers)
        total_unmatched_stake = sum(wager.get('unmatched_stake', 0) for wager in active_wagers)
        
        return {
            "success": True,
            "message": f"Retrieved {len(active_wagers)} active wagers",
            "data": {
                "active_wagers": active_wagers,
                "summary": {
                    "total_active_wagers": len(active_wagers),
                    "total_stake": total_stake,
                    "total_unmatched_stake": total_unmatched_stake,
                    "days_back": days_back
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting active wagers: {str(e)}")

@router.get("/wagers/matched", response_model=Dict[str, Any])
async def get_matched_wagers(days_back: int = Query(7, description="How many days back to look")):
    """
    Get all matched wagers (both fully and partially matched)
    
    This retrieves wagers that have been matched with other users' bets.
    These are the wagers where we've actually taken positions.
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        matched_wagers = await wager_api.get_all_matched_wagers(days_back)
        
        # Categorize and calculate statistics
        fully_matched = [w for w in matched_wagers if w.get('matching_status') == 'fully_matched']
        partially_matched = [w for w in matched_wagers if w.get('matching_status') == 'partially_matched']
        
        total_matched_stake = sum(wager.get('matched_stake', 0) for wager in matched_wagers)
        total_profit = sum(wager.get('profit', 0) for wager in matched_wagers)
        
        return {
            "success": True,
            "message": f"Retrieved {len(matched_wagers)} matched wagers",
            "data": {
                "matched_wagers": matched_wagers,
                "summary": {
                    "total_matched_wagers": len(matched_wagers),
                    "fully_matched_count": len(fully_matched),
                    "partially_matched_count": len(partially_matched),
                    "total_matched_stake": total_matched_stake,
                    "total_profit": total_profit,
                    "days_back": days_back
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting matched wagers: {str(e)}")

@router.get("/wagers/event/{event_id}", response_model=Dict[str, Any])
async def get_wagers_for_event(
    event_id: str,
    days_back: int = Query(7, description="How many days back to look")
):
    """
    Get all our wagers for a specific event
    
    - **event_id**: ProphetX event ID
    - **days_back**: How many days back to look
    
    This shows all our betting activity (active and matched) for a specific event.
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        event_wagers = await wager_api.get_wagers_for_event(event_id, days_back)
        
        # Categorize wagers
        active_wagers = [w for w in event_wagers if w.get('matching_status') == 'unmatched']
        matched_wagers = [w for w in event_wagers if w.get('matching_status') in ['fully_matched', 'partially_matched']]
        
        # Calculate totals
        total_stake = sum(w.get('stake', 0) for w in event_wagers)
        total_matched_stake = sum(w.get('matched_stake', 0) for w in event_wagers)
        total_unmatched_stake = sum(w.get('unmatched_stake', 0) for w in event_wagers)
        
        return {
            "success": True,
            "message": f"Retrieved {len(event_wagers)} wagers for event {event_id}",
            "data": {
                "event_id": event_id,
                "all_wagers": event_wagers,
                "active_wagers": active_wagers,
                "matched_wagers": matched_wagers,
                "summary": {
                    "total_wagers": len(event_wagers),
                    "active_count": len(active_wagers),
                    "matched_count": len(matched_wagers),
                    "total_stake": total_stake,
                    "total_matched_stake": total_matched_stake,
                    "total_unmatched_stake": total_unmatched_stake,
                    "days_back": days_back
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting wagers for event: {str(e)}")

# ============================================================================
# LOOKUP AND SEARCH ENDPOINTS
# ============================================================================

@router.get("/wagers/find-by-external-id/{external_id}", response_model=Dict[str, Any])
async def find_wager_by_external_id(
    external_id: str,
    days_back: int = Query(7, description="How many days back to search")
):
    """
    Find a wager by our external ID
    
    - **external_id**: Our external ID for the wager
    - **days_back**: How many days back to search
    
    This is useful when you know your external ID but need to find the corresponding
    ProphetX wager data.
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        wager_data = await wager_api.find_wager_by_external_id(external_id, days_back)
        
        if wager_data:
            return {
                "success": True,
                "message": f"Found wager with external_id {external_id}",
                "data": {
                    "external_id": external_id,
                    "wager": wager_data,
                    "prophetx_wager_id": wager_data.get("wager_id"),
                    "matching_status": wager_data.get("matching_status"),
                    "status": wager_data.get("status")
                }
            }
        else:
            return {
                "success": False,
                "message": f"No wager found with external_id {external_id}",
                "external_id": external_id,
                "searched_days_back": days_back
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error finding wager by external ID: {str(e)}")

@router.get("/wagers/comprehensive-status/{wager_identifier}", response_model=Dict[str, Any])
async def get_comprehensive_wager_status(wager_identifier: str):
    """
    Get comprehensive status of a wager using multiple lookup methods
    
    - **wager_identifier**: Either ProphetX wager_id or our external_id
    
    This endpoint tries multiple methods to find and analyze a wager:
    1. Direct lookup by ProphetX wager_id
    2. Search by external_id
    3. Get matching details if the wager is matched
    
    **Use this when:**
    - You're not sure if you have a wager_id or external_id
    - You want complete information about a wager's status
    - You're debugging why a wager isn't showing up as expected
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        result = await wager_api.get_comprehensive_wager_status(wager_identifier)
        
        return {
            "success": result["status"] != "not_found",
            "message": f"Comprehensive lookup for {wager_identifier}",
            "data": {
                "identifier": wager_identifier,
                "found_via": result["found_via"],
                "status": result["status"],
                "wager_data": result["wager_data"],
                "matching_details": result["matching_details"],
                "analysis": {
                    "is_active": result["wager_data"].get("matching_status") == "unmatched" if result["wager_data"] else False,
                    "is_matched": result["wager_data"].get("matching_status") in ["fully_matched", "partially_matched"] if result["wager_data"] else False,
                    "has_matching_details": result["matching_details"] is not None,
                    "current_status": result["wager_data"].get("status") if result["wager_data"] else None
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting comprehensive wager status: {str(e)}")

# ============================================================================
# TESTING AND COMPARISON ENDPOINTS
# ============================================================================

@router.get("/wagers/compare-with-our-system", response_model=Dict[str, Any])
async def compare_wagers_with_our_system(days_back: int = Query(1, description="How many days back to compare")):
    """
    Compare ProphetX wager data with our internal system
    
    This endpoint helps identify discrepancies between what we think we have
    and what ProphetX actually shows.
    
    **Use this for debugging:**
    - Bets that we think are active but ProphetX shows as matched
    - Missing bets that we placed but can't find on ProphetX
    - Status inconsistencies
    """
    try:
        from app.services.prophetx_wager_api import ProphetXWagerAPI
        from app.services.prophetx_service import prophetx_service
        from app.services.market_maker_service import market_maker_service
        
        wager_api = ProphetXWagerAPI(prophetx_service)
        
        # Get all wagers from ProphetX
        now = int(time.time())
        from_timestamp = now - (days_back * 24 * 60 * 60)
        
        prophetx_result = await wager_api.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now,
            limit=1000
        )
        
        if not prophetx_result["success"]:
            raise HTTPException(status_code=500, detail="Failed to get ProphetX wager data")
        
        prophetx_wagers = prophetx_result["wagers"]
        
        # Get our system's view of bets
        our_bets = list(market_maker_service.all_bets.values())
        
        # Filter our bets to the same time range
        cutoff_time = datetime.now() - timedelta(days=days_back)
        recent_our_bets = [bet for bet in our_bets if bet.placed_at >= cutoff_time]
        
        # Create comparison data
        comparison = {
            "our_system": {
                "total_bets": len(recent_our_bets),
                "active_bets": len([bet for bet in recent_our_bets if bet.is_active]),
                "external_ids": [bet.external_id for bet in recent_our_bets]
            },
            "prophetx": {
                "total_wagers": len(prophetx_wagers),
                "active_wagers": len([w for w in prophetx_wagers if w.get('matching_status') == 'unmatched']),
                "matched_wagers": len([w for w in prophetx_wagers if w.get('matching_status') in ['fully_matched', 'partially_matched']]),
                "external_ids": [w.get('external_id') for w in prophetx_wagers if w.get('external_id')]
            },
            "analysis": {},
            "discrepancies": []
        }
        
        # Analyze matches
        our_external_ids = set(comparison["our_system"]["external_ids"])
        prophetx_external_ids = set(comparison["prophetx"]["external_ids"])
        
        matched_ids = our_external_ids.intersection(prophetx_external_ids)
        missing_from_prophetx = our_external_ids - prophetx_external_ids
        extra_on_prophetx = prophetx_external_ids - our_external_ids
        
        comparison["analysis"] = {
            "matched_external_ids": len(matched_ids),
            "missing_from_prophetx": len(missing_from_prophetx),
            "extra_on_prophetx": len(extra_on_prophetx),
            "match_rate": len(matched_ids) / len(our_external_ids) if our_external_ids else 0
        }
        
        # Identify specific discrepancies
        if missing_from_prophetx:
            comparison["discrepancies"].append(f"{len(missing_from_prophetx)} of our bets missing from ProphetX")
        
        if extra_on_prophetx:
            comparison["discrepancies"].append(f"{len(extra_on_prophetx)} extra wagers on ProphetX not in our system")
        
        if comparison["analysis"]["match_rate"] < 0.9:
            comparison["discrepancies"].append(f"Low match rate: {comparison['analysis']['match_rate']:.1%}")
        
        return {
            "success": True,
            "message": f"Comparison completed for last {days_back} day(s)",
            "data": comparison
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing wager data: {str(e)}")