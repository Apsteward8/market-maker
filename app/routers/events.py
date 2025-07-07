#!/usr/bin/env python3
"""
Events Router
FastAPI endpoints for event management and lifecycle control
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.models.odds_models import ProcessedEvent
from app.models.market_models import ManagedEvent, MarketStatus
from app.services.market_maker_service import market_maker_service
from app.services.odds_api_service import odds_api_service

router = APIRouter()

@router.get("/available", response_model=List[ProcessedEvent])
async def get_available_events(
    limit: Optional[int] = Query(50, description="Maximum number of events to return"),
    hours_ahead: Optional[int] = Query(24, description="Only show events starting within this many hours")
):
    """
    Get all available events from Pinnacle odds
    
    Returns events that could potentially be managed by the market making system.
    Useful for seeing what events are available before starting market making.
    """
    try:
        # Fetch latest events from Odds API
        events = await odds_api_service.get_events()
        
        # Filter by time window
        if hours_ahead:
            cutoff_time = datetime.now() + timedelta(hours=hours_ahead)
            events = [event for event in events if event.commence_time <= cutoff_time]
        
        # Sort by start time
        events.sort(key=lambda x: x.commence_time)
        
        # Apply limit
        if limit:
            events = events[:limit]
        
        return events
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting available events: {str(e)}")

@router.get("/managed", response_model=List[ManagedEvent])
async def get_managed_events():
    """
    Get all events currently being managed
    
    Returns detailed information about each event we're actively making markets for,
    including current positions, exposure, and market status.
    """
    try:
        return list(market_maker_service.managed_events.values())
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting managed events: {str(e)}")

@router.get("/managed/{event_id}", response_model=ManagedEvent)
async def get_managed_event_details(event_id: str):
    """
    Get detailed information for a specific managed event
    
    - **event_id**: Unique identifier for the event
    
    Returns comprehensive details including all markets, positions, and risk metrics.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        
        return market_maker_service.managed_events[event_id]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting event details: {str(e)}")

@router.post("/add/{event_id}", response_model=Dict[str, Any])
async def add_event_to_management(event_id: str):
    """
    Add a specific event to market making management
    
    Manually adds an event to the managed portfolio even if the automatic
    system hasn't picked it up yet. Useful for targeting specific events.
    """
    try:
        # Check if already managed
        if event_id in market_maker_service.managed_events:
            return {
                "success": False,
                "message": f"Event {event_id} is already being managed",
                "event_id": event_id
            }
        
        # Get event details from Odds API
        events = await odds_api_service.get_events()
        target_event = None
        
        for event in events:
            if event.event_id == event_id:
                target_event = event
                break
        
        if not target_event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found in current odds")
        
        # Check if event is suitable for management
        if target_event.is_starting_soon:
            return {
                "success": False,
                "message": f"Event {target_event.display_name} is starting too soon to manage",
                "event_id": event_id
            }
        
        # Create managed event
        managed_event = ManagedEvent(
            event_id=event_id,
            sport=target_event.sport,
            home_team=target_event.home_team,
            away_team=target_event.away_team,
            commence_time=target_event.commence_time,
            max_exposure=market_maker_service.settings.max_exposure_per_event,
            status=MarketStatus.PENDING
        )
        
        # Add to managed events
        market_maker_service.managed_events[event_id] = managed_event
        
        # Trigger market creation for this event
        await market_maker_service._manage_event_markets(target_event)
        
        return {
            "success": True,
            "message": f"Event {target_event.display_name} added to management",
            "data": {
                "event_id": event_id,
                "event_name": target_event.display_name,
                "commence_time": target_event.commence_time.isoformat(),
                "available_markets": target_event.get_available_markets()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding event to management: {str(e)}")

@router.post("/remove/{event_id}", response_model=Dict[str, Any])
async def remove_event_from_management(
    event_id: str,
    cancel_bets: bool = Query(True, description="Whether to cancel active bets for this event")
):
    """
    Remove an event from market making management
    
    Stops making markets for the specified event and optionally cancels active bets.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not being managed")
        
        managed_event = market_maker_service.managed_events[event_id]
        cancelled_bets = 0
        
        if cancel_bets:
            # Cancel all active bets for this event
            for market in managed_event.markets:
                for side in market.sides:
                    if side.current_bet and side.current_bet.is_active:
                        side.current_bet.status = "cancelled"
                        side.current_bet.unmatched_stake = 0.0
                        cancelled_bets += 1
        
        # Remove from managed events
        del market_maker_service.managed_events[event_id]
        
        return {
            "success": True,
            "message": f"Event {managed_event.display_name} removed from management",
            "data": {
                "event_id": event_id,
                "event_name": managed_event.display_name,
                "cancelled_bets": cancelled_bets,
                "cancel_bets_option": cancel_bets
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error removing event from management: {str(e)}")

@router.post("/pause/{event_id}", response_model=Dict[str, Any])
async def pause_event_management(event_id: str):
    """
    Pause market making for a specific event
    
    Temporarily stops updating odds and creating new bets for this event,
    but keeps existing bets active.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not being managed")
        
        managed_event = market_maker_service.managed_events[event_id]
        managed_event.status = MarketStatus.PAUSED
        
        # Update all markets to paused status
        for market in managed_event.markets:
            market.status = MarketStatus.PAUSED
        
        return {
            "success": True,
            "message": f"Market making paused for {managed_event.display_name}",
            "data": {
                "event_id": event_id,
                "event_name": managed_event.display_name,
                "markets_paused": len(managed_event.markets)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error pausing event: {str(e)}")

@router.post("/resume/{event_id}", response_model=Dict[str, Any])
async def resume_event_management(event_id: str):
    """
    Resume market making for a specific event
    
    Restarts odds updates and market making for a previously paused event.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not being managed")
        
        managed_event = market_maker_service.managed_events[event_id]
        
        # Check if event hasn't started yet
        if managed_event.should_stop_making_markets:
            return {
                "success": False,
                "message": f"Cannot resume {managed_event.display_name} - event starts too soon",
                "event_id": event_id
            }
        
        managed_event.status = MarketStatus.ACTIVE
        
        # Update all markets to active status
        for market in managed_event.markets:
            market.status = MarketStatus.ACTIVE
        
        return {
            "success": True,
            "message": f"Market making resumed for {managed_event.display_name}",
            "data": {
                "event_id": event_id,
                "event_name": managed_event.display_name,
                "markets_resumed": len(managed_event.markets)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resuming event: {str(e)}")

@router.get("/upcoming", response_model=List[Dict[str, Any]])
async def get_upcoming_events(
    hours_ahead: int = Query(6, description="Look ahead this many hours"),
    limit: int = Query(20, description="Maximum number of events to return")
):
    """
    Get events starting soon that we should prepare for
    
    Returns events starting within the specified time window that could be
    good candidates for market making.
    """
    try:
        events = await odds_api_service.get_events()
        
        # Filter for upcoming events
        now = datetime.now()
        cutoff_time = now + timedelta(hours=hours_ahead)
        
        upcoming_events = []
        for event in events:
            if now < event.commence_time <= cutoff_time:
                # Check if it has good market coverage
                market_count = len(event.get_available_markets())
                
                upcoming_events.append({
                    "event_id": event.event_id,
                    "display_name": event.display_name,
                    "commence_time": event.commence_time.isoformat(),
                    "starts_in_hours": event.starts_in_hours,
                    "available_markets": event.get_available_markets(),
                    "market_count": market_count,
                    "is_managed": event.event_id in market_maker_service.managed_events,
                    "suitability_score": market_count * 10 + (6 - event.starts_in_hours) * 5  # Simple scoring
                })
        
        # Sort by suitability score
        upcoming_events.sort(key=lambda x: x["suitability_score"], reverse=True)
        
        return upcoming_events[:limit]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting upcoming events: {str(e)}")

@router.get("/statistics", response_model=Dict[str, Any])
async def get_event_statistics():
    """
    Get comprehensive statistics about event management
    
    Returns statistics about how many events we've managed, success rates,
    and other performance metrics.
    """
    try:
        stats = {
            "currently_managed": len(market_maker_service.managed_events),
            "max_capacity": market_maker_service.settings.max_events_tracked,
            "utilization_percentage": (len(market_maker_service.managed_events) / market_maker_service.settings.max_events_tracked) * 100,
            "by_status": {},
            "by_sport": {},
            "by_time_to_start": {
                "within_1_hour": 0,
                "1_to_6_hours": 0,
                "6_to_24_hours": 0,
                "over_24_hours": 0
            }
        }
        
        # Count by status
        for managed_event in market_maker_service.managed_events.values():
            status = managed_event.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            
            # Count by sport
            sport = managed_event.sport
            stats["by_sport"][sport] = stats["by_sport"].get(sport, 0) + 1
            
            # Count by time to start
            hours_to_start = managed_event.starts_in_hours
            if hours_to_start <= 1:
                stats["by_time_to_start"]["within_1_hour"] += 1
            elif hours_to_start <= 6:
                stats["by_time_to_start"]["1_to_6_hours"] += 1
            elif hours_to_start <= 24:
                stats["by_time_to_start"]["6_to_24_hours"] += 1
            else:
                stats["by_time_to_start"]["over_24_hours"] += 1
        
        return {
            "success": True,
            "message": "Event statistics retrieved",
            "data": stats,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting event statistics: {str(e)}")

@router.post("/bulk-add", response_model=Dict[str, Any])
async def bulk_add_events(
    sport: str = Query("baseball", description="Sport to add events for"),
    max_events: int = Query(10, description="Maximum number of events to add"),
    min_hours_ahead: float = Query(1.0, description="Minimum hours until event start"),
    max_hours_ahead: float = Query(24.0, description="Maximum hours until event start")
):
    """
    Bulk add multiple events to management
    
    Automatically selects and adds the best available events based on criteria.
    Useful for quickly scaling up market making operations.
    """
    try:
        # Get available events
        events = await odds_api_service.get_events()
        
        # Filter events by criteria
        suitable_events = []
        for event in events:
            if (event.sport.lower() == sport.lower() and
                min_hours_ahead <= event.starts_in_hours <= max_hours_ahead and
                event.event_id not in market_maker_service.managed_events and
                event.moneyline is not None):  # Must have moneyline
                
                # Score event based on market availability
                score = len(event.get_available_markets()) * 10
                suitable_events.append((event, score))
        
        # Sort by score and take the best ones
        suitable_events.sort(key=lambda x: x[1], reverse=True)
        selected_events = suitable_events[:max_events]
        
        # Add events to management
        added_events = []
        for event, score in selected_events:
            try:
                managed_event = ManagedEvent(
                    event_id=event.event_id,
                    sport=event.sport,
                    home_team=event.home_team,
                    away_team=event.away_team,
                    commence_time=event.commence_time,
                    max_exposure=market_maker_service.settings.max_exposure_per_event,
                    status=MarketStatus.PENDING
                )
                
                market_maker_service.managed_events[event.event_id] = managed_event
                
                # Trigger market creation
                await market_maker_service._manage_event_markets(event)
                
                added_events.append({
                    "event_id": event.event_id,
                    "display_name": event.display_name,
                    "score": score,
                    "available_markets": event.get_available_markets()
                })
                
            except Exception as e:
                print(f"❌ Failed to add event {event.event_id}: {e}")
                continue
        
        return {
            "success": True,
            "message": f"Bulk added {len(added_events)} events for {sport}",
            "data": {
                "sport": sport,
                "events_added": len(added_events),
                "events_evaluated": len(suitable_events),
                "added_events": added_events
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error bulk adding events: {str(e)}")