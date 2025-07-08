#!/usr/bin/env python3
"""
Event Matching Router - UPDATED VERSION
FastAPI endpoints for managing event matching between Odds API and ProphetX
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.models.odds_models import ProcessedEvent
from app.services.prophetx_events_service import ProphetXEvent, prophetx_events_service
from app.services.odds_api_service import odds_api_service
from app.services.event_matching_service import EventMatch, MatchingAttempt, event_matching_service
from app.services.market_matching_service import market_matching_service
from app.services.market_making_strategy import market_making_strategy

router = APIRouter()

@router.get("/odds-api-events", response_model=List[ProcessedEvent])
async def get_odds_api_events():
    """
    Get all upcoming events from The Odds API (Pinnacle)
    
    Returns baseball events with odds from Pinnacle that could potentially
    be matched to ProphetX events for market making.
    """
    try:
        events = await odds_api_service.get_events()
        return events
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Odds API events: {str(e)}")

@router.get("/prophetx-events", response_model=List[ProphetXEvent])
async def get_prophetx_events():
    """
    Get all upcoming baseball events from ProphetX
    
    Returns baseball events available on ProphetX that we could potentially
    make markets for.
    """
    try:
        events = await prophetx_events_service.get_all_upcoming_events()
        return events
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ProphetX events: {str(e)}")

@router.post("/find-matches", response_model=List[MatchingAttempt])
async def find_event_matches():
    """
    Find matches between Odds API and ProphetX events
    
    Attempts to automatically match events from The Odds API (Pinnacle)
    with corresponding events on ProphetX based on team names and start times.
    
    This is a critical step before starting market making.
    """
    try:
        print("🔍 Starting event matching process...")
        
        # Get events from Odds API
        odds_events = await odds_api_service.get_events()
        print(f"📊 Found {len(odds_events)} events from Odds API")
        
        if not odds_events:
            return []
        
        # Find matches
        matching_attempts = await event_matching_service.find_matches_for_events(odds_events)
        
        return matching_attempts
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error finding event matches: {str(e)}")

@router.get("/matches", response_model=List[EventMatch])
async def get_confirmed_matches():
    """
    Get all confirmed event matches
    
    Returns events that have been successfully matched between
    The Odds API and ProphetX and are ready for market making.
    """
    try:
        matches = await event_matching_service.get_matched_events()
        return matches
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting matches: {str(e)}")

@router.get("/unmatched", response_model=List[ProcessedEvent])
async def get_unmatched_events():
    """
    Get Odds API events that don't have ProphetX matches
    
    Returns events from The Odds API that couldn't be automatically
    matched to ProphetX events. These may need manual intervention.
    """
    try:
        unmatched = await event_matching_service.get_unmatched_odds_events()
        return unmatched
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting unmatched events: {str(e)}")

@router.get("/summary", response_model=Dict[str, Any])
async def get_matching_summary():
    """
    Get comprehensive matching summary
    
    Returns statistics about the event matching process including
    success rates, total events from each source, and overall status.
    """
    try:
        summary = await event_matching_service.get_matching_summary()
        return {
            "success": True,
            "message": "Event matching summary",
            "data": summary,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting matching summary: {str(e)}")

@router.post("/manual-override", response_model=Dict[str, Any])
async def add_manual_override(
    odds_api_event_id: str = Query(..., description="Event ID from Odds API"),
    prophetx_event_id: int = Query(..., description="Event ID from ProphetX")
):
    """
    Manually map an Odds API event to a ProphetX event
    
    When automatic matching fails, use this endpoint to manually specify
    which ProphetX event corresponds to an Odds API event.
    
    - **odds_api_event_id**: The event ID from The Odds API
    - **prophetx_event_id**: The corresponding event ID from ProphetX
    """
    try:
        success = await event_matching_service.add_manual_override(
            odds_api_event_id, prophetx_event_id
        )
        
        if success:
            return {
                "success": True,
                "message": f"Manual override added: {odds_api_event_id} → {prophetx_event_id}",
                "data": {
                    "odds_api_event_id": odds_api_event_id,
                    "prophetx_event_id": prophetx_event_id
                }
            }
        else:
            return {
                "success": False,
                "message": "Failed to add manual override"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding manual override: {str(e)}")

@router.delete("/manual-override/{odds_api_event_id}", response_model=Dict[str, Any])
async def remove_manual_override(odds_api_event_id: str):
    """
    Remove a manual override
    
    Removes a previously set manual mapping between Odds API and ProphetX events.
    """
    try:
        success = await event_matching_service.remove_manual_override(odds_api_event_id)
        
        if success:
            return {
                "success": True,
                "message": f"Manual override removed for {odds_api_event_id}",
                "odds_api_event_id": odds_api_event_id
            }
        else:
            return {
                "success": False,
                "message": f"No manual override found for {odds_api_event_id}"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error removing manual override: {str(e)}")

@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_all_matches():
    """
    Refresh all event matches
    
    Clears existing matches and re-runs the matching process for all current events.
    Use this when you want to start fresh or when new events become available.
    """
    try:
        result = await event_matching_service.refresh_all_matches()
        
        return {
            "success": True,
            "message": "Event matching refreshed successfully",
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing matches: {str(e)}")

@router.get("/matches-summary", response_model=Dict[str, Any])
async def get_matches_summary():
    """
    Get a clean, readable summary of event matches
    
    Returns a simplified view showing which events were matched and which weren't,
    with just the essential information for easy scanning.
    """
    try:
        print("📋 Generating clean matches summary...")
        
        # Get events from Odds API
        odds_events = await odds_api_service.get_events()
        
        if not odds_events:
            return {
                "success": True,
                "message": "No events available",
                "data": {
                    "matched_events": [],
                    "unmatched_events": [],
                    "summary": {
                        "total_events": 0,
                        "matched_count": 0,
                        "unmatched_count": 0,
                        "match_rate": 0
                    }
                }
            }
        
        # Run matching
        matching_attempts = await event_matching_service.find_matches_for_events(odds_events)
        
        matched_events = []
        unmatched_events = []
        
        for attempt in matching_attempts:
            odds_event = attempt.odds_api_event
            
            if attempt.best_match:
                # Successful match
                px_event = attempt.best_match.prophetx_event
                matched_events.append({
                    "odds_api_event_id": odds_event.event_id,
                    "prophetx_event_id": px_event.event_id,
                    "teams": f"{odds_event.away_team} @ {odds_event.home_team}",
                    "commence_time": odds_event.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
                    "confidence": round(attempt.best_match.confidence_score, 3),
                    "prophetx_teams": f"{px_event.away_team} @ {px_event.home_team}",
                    "time_difference_minutes": round(abs((odds_event.commence_time - px_event.commence_time).total_seconds() / 60), 1)
                })
            else:
                # No match found
                unmatched_events.append({
                    "odds_api_event_id": odds_event.event_id,
                    "teams": f"{odds_event.away_team} @ {odds_event.home_team}",
                    "commence_time": odds_event.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
                    "reason": attempt.no_match_reason,
                    "best_confidence": round(attempt.prophetx_matches[0][1], 3) if attempt.prophetx_matches else 0.0,
                    "closest_prophetx_match": f"{attempt.prophetx_matches[0][0].away_team} @ {attempt.prophetx_matches[0][0].home_team}" if attempt.prophetx_matches else "None"
                })
        
        # Sort by commence time
        matched_events.sort(key=lambda x: x["commence_time"])
        unmatched_events.sort(key=lambda x: x["commence_time"])
        
        summary = {
            "total_events": len(odds_events),
            "matched_count": len(matched_events),
            "unmatched_count": len(unmatched_events),
            "match_rate": round(len(matched_events) / len(odds_events) * 100, 1) if odds_events else 0
        }
        
        return {
            "success": True,
            "message": f"Found {summary['matched_count']} matches out of {summary['total_events']} events ({summary['match_rate']}%)",
            "data": {
                "matched_events": matched_events,
                "unmatched_events": unmatched_events,
                "summary": summary
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating matches summary: {str(e)}")

# NEW MARKET MATCHING ENDPOINTS

@router.get("/prophetx-markets/{event_id}", response_model=Dict[str, Any])
async def get_prophetx_markets(event_id: int):
    """
    Get ProphetX markets for a specific event
    
    Fetches and displays all available markets and betting lines for a ProphetX event.
    Useful for understanding market structure and debugging market matching.
    """
    try:
        markets = await market_matching_service.fetch_prophetx_markets(event_id)
        
        if not markets:
            return {
                "success": False,
                "message": f"No markets found for ProphetX event {event_id}",
                "event_id": event_id
            }
        
        # Format for display
        markets_summary = []
        for market in markets.markets:
            market_info = {
                "market_id": market.market_id,
                "market_type": market.market_type,
                "name": market.name,
                "status": market.status,
                "lines_count": len(market.lines),
                "lines": []
            }
            
            for line in market.lines:
                line_info = {
                    "line_id": line.line_id,
                    "selection_name": line.selection_name,
                    "odds": line.american_odds if line.is_active else "unavailable",
                    "point": line.point,
                    "status": line.status,
                    "is_active": line.is_active
                }
                market_info["lines"].append(line_info)
            
            markets_summary.append(market_info)
        
        return {
            "success": True,
            "message": f"Found {len(markets.markets)} markets for event {event_id}",
            "data": {
                "event_id": event_id,
                "event_name": markets.event_name,
                "markets": markets_summary,
                "last_updated": markets.last_updated.isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ProphetX markets: {str(e)}")

@router.post("/test-market-matching/{odds_api_event_id}", response_model=Dict[str, Any])
async def test_market_matching(odds_api_event_id: str):
    """
    Test market matching for a specific Odds API event
    
    Takes an Odds API event ID, finds its ProphetX match, and attempts to match
    all markets between the platforms. Returns detailed matching results.
    """
    try:
        # Find the event match
        confirmed_matches = await event_matching_service.get_matched_events()
        target_match = None
        
        for match in confirmed_matches:
            if match.odds_api_event.event_id == odds_api_event_id:
                target_match = match
                break
        
        if not target_match:
            return {
                "success": False,
                "message": f"No matched event found for Odds API event {odds_api_event_id}",
                "suggestion": "Run /matching/find-matches first to create event matches"
            }
        
        # Perform market matching
        print(f"🎯 Testing market matching for: {target_match.odds_api_event.display_name}")
        
        market_match_result = await market_matching_service.match_event_markets(target_match)
        
        # Format results for display
        results = {
            "event_info": {
                "odds_api_event_id": market_match_result.odds_api_event_id,
                "prophetx_event_id": market_match_result.prophetx_event_id,
                "event_name": market_match_result.event_display_name,
                "overall_confidence": round(market_match_result.overall_confidence, 3),
                "ready_for_trading": market_match_result.ready_for_trading,
                "issues": market_match_result.issues
            },
            "market_matches": [],
            "summary": {
                "total_markets": len(market_match_result.market_matches),
                "successful_markets": len(market_match_result.successful_markets),
                "failed_markets": len(market_match_result.failed_markets),
                "total_outcome_mappings": market_match_result.total_outcome_mappings
            }
        }
        
        # Add detailed market match results
        for market_match in market_match_result.market_matches:
            match_info = {
                "odds_api_market_type": market_match.odds_api_market_type,
                "prophetx_market_id": market_match.prophetx_market_id,
                "prophetx_market_type": market_match.prophetx_market_type,
                "match_status": market_match.match_status,
                "confidence_score": round(market_match.confidence_score, 3),
                "issues": market_match.issues,
                "outcome_mappings": market_match.outcome_mappings
            }
            results["market_matches"].append(match_info)
        
        return {
            "success": True,
            "message": f"Market matching completed for {target_match.odds_api_event.display_name}",
            "data": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing market matching: {str(e)}")

@router.get("/market-matching-summary", response_model=Dict[str, Any])
async def get_market_matching_summary():
    """
    Get market matching summary for all matched events
    
    Runs market matching for all confirmed event matches and provides a summary
    of which events are ready for market making.
    """
    try:
        # Get all confirmed event matches
        confirmed_matches = await event_matching_service.get_matched_events()
        
        if not confirmed_matches:
            return {
                "success": True,
                "message": "No confirmed event matches found",
                "data": {
                    "ready_for_trading": [],
                    "partial_matches": [],
                    "failed_matches": [],
                    "summary": {
                        "total_events": 0,
                        "ready_count": 0,
                        "partial_count": 0,
                        "failed_count": 0
                    }
                }
            }
        
        print(f"📊 Running market matching for {len(confirmed_matches)} matched events...")
        
        ready_for_trading = []
        partial_matches = []
        failed_matches = []
        
        for event_match in confirmed_matches:
            try:
                market_result = await market_matching_service.match_event_markets(event_match)
                
                event_summary = {
                    "odds_api_event_id": market_result.odds_api_event_id,
                    "prophetx_event_id": market_result.prophetx_event_id,
                    "event_name": market_result.event_display_name,
                    "overall_confidence": round(market_result.overall_confidence, 3),
                    "successful_markets": len(market_result.successful_markets),
                    "total_markets": len(market_result.market_matches),
                    "total_mappings": market_result.total_outcome_mappings,
                    "issues": market_result.issues
                }
                
                if market_result.ready_for_trading:
                    ready_for_trading.append(event_summary)
                elif len(market_result.successful_markets) > 0:
                    partial_matches.append(event_summary)
                else:
                    failed_matches.append(event_summary)
                    
            except Exception as e:
                print(f"❌ Error matching markets for {event_match.odds_api_event.display_name}: {e}")
                failed_matches.append({
                    "odds_api_event_id": event_match.odds_api_event.event_id,
                    "prophetx_event_id": event_match.prophetx_event.event_id,
                    "event_name": event_match.odds_api_event.display_name,
                    "overall_confidence": 0.0,
                    "successful_markets": 0,
                    "total_markets": 0,
                    "total_mappings": 0,
                    "issues": [f"Exception during matching: {str(e)}"]
                })
        
        summary = {
            "total_events": len(confirmed_matches),
            "ready_count": len(ready_for_trading),
            "partial_count": len(partial_matches),
            "failed_count": len(failed_matches),
            "ready_percentage": round(len(ready_for_trading) / len(confirmed_matches) * 100, 1) if confirmed_matches else 0
        }
        
        return {
            "success": True,
            "message": f"Market matching completed for {len(confirmed_matches)} events. {summary['ready_count']} ready for trading.",
            "data": {
                "ready_for_trading": ready_for_trading,
                "partial_matches": partial_matches,
                "failed_matches": failed_matches,
                "summary": summary
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting market matching summary: {str(e)}")

@router.post("/test-strategy/{odds_api_event_id}", response_model=Dict[str, Any])
async def test_market_making_strategy(odds_api_event_id: str):
    """
    Test the market making strategy for a specific event
    
    Shows exactly what bets we would place and what odds we'd offer to users.
    """
    try:
        # Get the event match
        confirmed_matches = await event_matching_service.get_matched_events()
        target_match = None
        
        for match in confirmed_matches:
            if match.odds_api_event.event_id == odds_api_event_id:
                target_match = match
                break
        
        if not target_match:
            return {
                "success": False,
                "message": f"No matched event found for {odds_api_event_id}",
                "suggestion": "Run /matching/find-matches first"
            }
        
        # Get market matching results
        market_match_result = await market_matching_service.match_event_markets(target_match)
        
        # Create market making plan
        plan = market_making_strategy.create_market_making_plan(target_match, market_match_result)
        
        if not plan:
            return {
                "success": False,
                "message": "No profitable market making opportunities found",
                "event_name": target_match.odds_api_event.display_name
            }
        
        # Format response
        betting_instructions = []
        for instruction in plan.betting_instructions:
            betting_instructions.append({
                "line_id": instruction.line_id,
                "selection_name": instruction.selection_name,
                "our_bet": {
                    "odds": instruction.odds,
                    "stake": f"${instruction.stake:.2f}",
                    "expected_return": f"${instruction.expected_return:.2f}"
                },
                "offer_to_users": {
                    "outcome": instruction.outcome_offered_to_users,
                    "liquidity_available": f"${instruction.liquidity_offered:.2f}"
                }
            })
        
        return {
            "success": True,
            "message": f"Market making strategy for {plan.event_name}",
            "data": {
                "event_name": plan.event_name,
                "is_profitable": plan.is_profitable,
                "total_stake_required": f"${plan.total_stake:.2f}",
                "betting_instructions": betting_instructions,
                "profitability_analysis": plan.profitability_analysis,
                "created_at": plan.created_at.isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing strategy: {str(e)}")

@router.get("/debug/{odds_api_event_id}", response_model=Dict[str, Any])
async def debug_event_matching(odds_api_event_id: str):
    """
    Debug matching for a specific Odds API event
    
    Provides detailed information about why an event may or may not have
    been matched, including similarity scores and potential matches.
    """
    try:
        # Get the specific event from Odds API
        odds_events = await odds_api_service.get_events()
        target_event = None
        
        for event in odds_events:
            if event.event_id == odds_api_event_id:
                target_event = event
                break
        
        if not target_event:
            raise HTTPException(status_code=404, detail=f"Event {odds_api_event_id} not found in Odds API")
        
        # Get ProphetX events
        prophetx_events = await prophetx_events_service.get_all_upcoming_events()
        
        # Run matching for this specific event
        matching_attempt = await event_matching_service._match_single_event(target_event, prophetx_events)
        
        debug_info = {
            "odds_api_event": {
                "id": target_event.event_id,
                "display_name": target_event.display_name,
                "home_team": target_event.home_team,
                "away_team": target_event.away_team,
                "commence_time": target_event.commence_time.isoformat(),
                "available_markets": target_event.get_available_markets()
            },
            "matching_results": {
                "best_match_found": matching_attempt.best_match is not None,
                "no_match_reason": matching_attempt.no_match_reason,
                "potential_matches_count": len(matching_attempt.prophetx_matches)
            },
            "potential_matches": []
        }
        
        # Add details about potential matches
        for px_event, confidence in matching_attempt.prophetx_matches[:5]:  # Top 5
            debug_info["potential_matches"].append({
                "prophetx_event_id": px_event.event_id,
                "display_name": px_event.display_name,
                "home_team": px_event.home_team,
                "away_team": px_event.away_team,
                "commence_time": px_event.commence_time.isoformat(),
                "confidence_score": confidence,
                "time_difference_hours": abs((target_event.commence_time - px_event.commence_time).total_seconds() / 3600)
            })
        
        if matching_attempt.best_match:
            debug_info["best_match"] = {
                "prophetx_event_id": matching_attempt.best_match.prophetx_event.event_id,
                "confidence_score": matching_attempt.best_match.confidence_score,
                "match_reasons": matching_attempt.best_match.match_reasons
            }
        
        return {
            "success": True,
            "message": f"Debug information for event {odds_api_event_id}",
            "data": debug_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error debugging event matching: {str(e)}")

@router.get("/prophetx-tournaments", response_model=List[Dict[str, Any]])
async def get_prophetx_tournaments():
    """
    Get all baseball tournaments available on ProphetX
    
    Useful for understanding what tournaments ProphetX covers
    and debugging event availability issues.
    """
    try:
        tournaments = await prophetx_events_service.get_tournaments("baseball")
        
        tournament_data = []
        for tournament in tournaments:
            tournament_data.append({
                "tournament_id": tournament.tournament_id,
                "name": tournament.name,
                "sport_name": tournament.sport_name,
                "category_name": tournament.category_name
            })
        
        return tournament_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ProphetX tournaments: {str(e)}")

        
        return tournament_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ProphetX tournaments: {str(e)}")

@router.get("/test-matching", response_model=Dict[str, Any])
async def test_matching_system():
    """
    Test the event matching system
    
    Runs a comprehensive test of the event matching capabilities
    and returns detailed results for verification.
    """
    try:
        print("🧪 Running event matching system test...")
        
        # Get data from both sources
        odds_events = await odds_api_service.get_events()
        prophetx_events = await prophetx_events_service.get_all_upcoming_events()
        
        test_results = {
            "data_availability": {
                "odds_api_events": len(odds_events),
                "prophetx_events": len(prophetx_events),
                "both_sources_available": len(odds_events) > 0 and len(prophetx_events) > 0
            },
            "sample_data": {
                "sample_odds_event": odds_events[0].dict() if odds_events else None,
                "sample_prophetx_event": {
                    "event_id": prophetx_events[0].event_id,
                    "display_name": prophetx_events[0].display_name,
                    "commence_time": prophetx_events[0].commence_time.isoformat(),
                    "tournament_name": prophetx_events[0].tournament_name
                } if prophetx_events else None
            }
        }
        
        # Run a small matching test if we have data
        if odds_events and prophetx_events:
            test_events = odds_events[:3]  # Test with first 3 events
            matching_attempts = await event_matching_service.find_matches_for_events(test_events)
            
            test_results["matching_test"] = {
                "events_tested": len(test_events),
                "successful_matches": sum(1 for attempt in matching_attempts if attempt.best_match),
                "match_rate": sum(1 for attempt in matching_attempts if attempt.best_match) / len(test_events)
            }
        
        return {
            "success": True,
            "message": "Event matching system test completed",
            "data": test_results,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing matching system: {str(e)}")
    
@router.get("/confidence-config", response_model=Dict[str, Any])
async def get_confidence_configuration():
    """
    Get current confidence threshold configuration
    
    Returns the current settings for event matching confidence thresholds.
    """
    try:
        return {
            "success": True,
            "message": "Current confidence configuration",
            "data": {
                "min_confidence_threshold": event_matching_service.min_confidence_threshold,
                "display_threshold": event_matching_service.display_threshold,
                "time_tolerance_minutes": event_matching_service.time_tolerance_minutes,
                "description": {
                    "min_confidence_threshold": "Minimum confidence required for successful match",
                    "display_threshold": "Minimum confidence to show in prophetx_matches list",
                    "time_tolerance_minutes": "Maximum time difference allowed between events"
                },
                "confidence_calculation": {
                    "time_score_weight": "40%",
                    "team_name_weight": "60%",
                    "perfect_time_match": "≤ 5 minutes = 1.0 score",
                    "good_time_match": "≤ 10 minutes = 0.9 score", 
                    "acceptable_time_match": "≤ 15 minutes = 0.7 score"
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting confidence config: {str(e)}")

@router.post("/update-confidence-threshold", response_model=Dict[str, Any])
async def update_confidence_threshold(
    threshold: float = Query(..., description="New confidence threshold (0.0 - 1.0)", ge=0.0, le=1.0)
):
    """
    Update the confidence threshold for event matching
    
    Changes the minimum confidence score required for events to be considered a match.
    Higher values (0.8-0.9) = stricter matching, fewer but higher quality matches
    Lower values (0.5-0.6) = looser matching, more matches but potentially lower quality
    
    - **threshold**: New minimum confidence threshold between 0.0 and 1.0
    
    **Note**: This clears existing matches and requires re-running event matching.
    """
    try:
        result = event_matching_service.update_confidence_threshold(threshold)
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Confidence threshold updated to {threshold}",
                "data": result,
                "next_steps": [
                    "Run /matching/refresh to re-match events with new threshold",
                    "Check /matching/matches-summary to see results"
                ]
            }
        else:
            return {
                "success": False,
                "message": result["message"]
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating confidence threshold: {str(e)}")

@router.get("/confidence-breakdown/{odds_api_event_id}", response_model=Dict[str, Any])
async def get_confidence_breakdown(odds_api_event_id: str):
    """
    Get detailed confidence breakdown for a specific event
    
    Shows exactly how the confidence score is calculated for debugging purposes.
    
    - **odds_api_event_id**: Event ID from The Odds API
    """
    try:
        # Get the specific event from Odds API
        odds_events = await odds_api_service.get_events()
        target_event = None
        
        for event in odds_events:
            if event.event_id == odds_api_event_id:
                target_event = event
                break
        
        if not target_event:
            raise HTTPException(status_code=404, detail=f"Event {odds_api_event_id} not found")
        
        # Get ProphetX events
        prophetx_events = await prophetx_events_service.get_all_upcoming_events()
        
        # Calculate confidence for each ProphetX event
        confidence_details = []
        
        for px_event in prophetx_events:
            confidence, reasons = event_matching_service._calculate_match_confidence(target_event, px_event)
            
            # Get detailed breakdown
            time_diff_minutes = abs((target_event.commence_time - px_event.commence_time).total_seconds() / 60)
            team_score = event_matching_service._calculate_team_name_score(target_event, px_event)
            
            # Calculate time score
            if time_diff_minutes <= 5:
                time_score = 1.0
            elif time_diff_minutes <= 10:
                time_score = 0.9
            elif time_diff_minutes <= 15:
                time_score = 0.7
            else:
                time_score = 0.0
            
            confidence_details.append({
                "prophetx_event": {
                    "event_id": px_event.event_id,
                    "display_name": px_event.display_name,
                    "commence_time": px_event.commence_time.isoformat()
                },
                "overall_confidence": confidence,
                "breakdown": {
                    "time_component": {
                        "score": time_score,
                        "weight": 0.4,
                        "contribution": time_score * 0.4,
                        "time_difference_minutes": time_diff_minutes
                    },
                    "team_component": {
                        "score": team_score,
                        "weight": 0.6,
                        "contribution": team_score * 0.6
                    }
                },
                "meets_threshold": confidence >= event_matching_service.min_confidence_threshold,
                "shown_in_matches": confidence >= event_matching_service.display_threshold,
                "reasons": reasons
            })
        
        # Sort by confidence
        confidence_details.sort(key=lambda x: x["overall_confidence"], reverse=True)
        
        return {
            "success": True,
            "message": f"Confidence breakdown for {target_event.display_name}",
            "data": {
                "odds_api_event": {
                    "event_id": target_event.event_id,
                    "display_name": target_event.display_name,
                    "commence_time": target_event.commence_time.isoformat(),
                    "home_team": target_event.home_team,
                    "away_team": target_event.away_team
                },
                "thresholds": {
                    "min_confidence_threshold": event_matching_service.min_confidence_threshold,
                    "display_threshold": event_matching_service.display_threshold,
                    "time_tolerance_minutes": event_matching_service.time_tolerance_minutes
                },
                "prophetx_matches_analyzed": len(confidence_details),
                "matches_above_threshold": sum(1 for m in confidence_details if m["meets_threshold"]),
                "matches_shown": sum(1 for m in confidence_details if m["shown_in_matches"]),
                "detailed_analysis": confidence_details[:10]  # Top 10 matches
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting confidence breakdown: {str(e)}")