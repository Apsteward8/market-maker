#!/usr/bin/env python3
"""
Event Matching Router
FastAPI endpoints for managing event matching between Odds API and ProphetX
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.models.odds_models import ProcessedEvent
from app.services.prophetx_events_service import ProphetXEvent, prophetx_events_service
from app.services.odds_api_service import odds_api_service
from app.services.event_matching_service import EventMatch, MatchingAttempt, event_matching_service

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