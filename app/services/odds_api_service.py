#!/usr/bin/env python3
"""
Odds API Service
Handles integration with The Odds API for getting Pinnacle odds
"""

import asyncio
import aiohttp
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import HTTPException

from app.core.config import get_settings
from app.models.odds_models import (
    OddsApiRequest, OddsApiResponse, OddsEvent, Bookmaker, BookmakerMarket, BookmakerOutcome,
    ProcessedEvent, ProcessedMarket, ProcessedOutcome, 
    SportKey, MarketType, Region, OddsFormat
)

class OddsApiService:
    """Service for interacting with The Odds API"""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.odds_api_base_url
        self.api_key = self.settings.odds_api_key
        
        # Usage tracking
        self.total_credits_used = 0
        self.requests_made = 0
        self.last_request_time = 0
        
        # Rate limiting
        self.min_request_interval = 1.0  # Minimum seconds between requests
        
        # Cache for recent data
        self.events_cache: Dict[str, ProcessedEvent] = {}
        self.cache_ttl = 300  # 5 minutes cache TTL
        
    async def get_events(
        self, 
        sport: SportKey = SportKey.BASEBALL,
        regions: List[Region] = None,
        markets: List[MarketType] = None,
        bookmakers: List[str] = None
    ) -> List[ProcessedEvent]:
        """
        Get events and odds from The Odds API
        
        Args:
            sport: Sport to get events for
            regions: Regions to include (defaults to US)
            markets: Markets to include (defaults to h2h, spreads, totals)
            bookmakers: Specific bookmakers (defaults to pinnacle)
            
        Returns:
            List of processed events with odds data
        """
        if regions is None:
            regions = [Region.US]
        if markets is None:
            markets = [MarketType.H2H, MarketType.SPREADS, MarketType.TOTALS]
        if bookmakers is None:
            bookmakers = [self.settings.target_bookmaker]
        
        # Create request configuration
        request_config = OddsApiRequest(
            sport=sport,
            regions=regions,
            markets=markets,
            bookmakers=bookmakers
        )
        
        print(f"🔍 Fetching {sport} odds from The Odds API...")
        print(f"   Markets: {', '.join([m.value for m in markets])}")
        print(f"   Bookmakers: {', '.join(bookmakers)}")
        print(f"   Estimated credits: {request_config.calculate_credits()}")
        
        # Build request URL
        url = self.settings.get_odds_api_url("sports/baseball_mlb/odds")
        params = {
            "apiKey": self.api_key,
            "regions": ",".join([r.value for r in regions]),
            "markets": ",".join([m.value for m in markets]),
            "oddsFormat": OddsFormat.AMERICAN.value,
            "dateFormat": "iso",
            "bookmakers": ",".join(bookmakers)
        }
        
        # Make API request with rate limiting
        await self._wait_for_rate_limit()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    self.requests_made += 1
                    self.last_request_time = time.time()
                    
                    if response.status == 200:
                        raw_data = await response.json()
                        
                        # Track API usage
                        credits_used = request_config.calculate_credits()
                        self.total_credits_used += credits_used
                        
                        print(f"✅ Successfully fetched {len(raw_data)} events")
                        print(f"   Credits used: {credits_used} (Total: {self.total_credits_used:,})")
                        
                        # Process raw data into our models
                        events = await self._process_raw_events(raw_data)
                        
                        # Update cache
                        for event in events:
                            self.events_cache[event.event_id] = event
                        
                        return events
                        
                    elif response.status == 429:
                        # Rate limit exceeded
                        retry_after = response.headers.get('Retry-After', 60)
                        raise HTTPException(
                            status_code=429, 
                            detail=f"Rate limit exceeded. Retry after {retry_after} seconds."
                        )
                    elif response.status == 401:
                        raise HTTPException(status_code=401, detail="Invalid API key")
                    elif response.status == 402:
                        raise HTTPException(status_code=402, detail="Insufficient API credits")
                    else:
                        error_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"Odds API error: {error_text}"
                        )
                        
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
    async def _process_raw_events(self, raw_events: List[Dict[str, Any]]) -> List[ProcessedEvent]:
        """Process raw API response into ProcessedEvent models"""
        processed_events = []
        
        for raw_event in raw_events:
            try:
                # Parse raw event data
                odds_event = OddsEvent(**raw_event)
                
                # Find our target bookmaker (Pinnacle)
                target_bookmaker = None
                for bookmaker in odds_event.bookmakers:
                    if bookmaker.key == self.settings.target_bookmaker:
                        target_bookmaker = bookmaker
                        break
                
                if not target_bookmaker:
                    print(f"⚠️  No {self.settings.target_bookmaker} odds found for {odds_event.home_team} vs {odds_event.away_team}")
                    continue
                
                # Process markets from target bookmaker
                processed_event = await self._process_bookmaker_markets(odds_event, target_bookmaker)
                
                if processed_event:
                    processed_events.append(processed_event)
                    
            except Exception as e:
                print(f"❌ Error processing event: {e}")
                continue
        
        print(f"📊 Processed {len(processed_events)} events with {self.settings.target_bookmaker} odds")
        return processed_events
    
    async def _process_bookmaker_markets(self, odds_event: OddsEvent, bookmaker: Bookmaker) -> Optional[ProcessedEvent]:
        """Process markets from a specific bookmaker into ProcessedEvent"""
        try:
            # Initialize processed event
            processed_event = ProcessedEvent(
                event_id=odds_event.id,
                sport=odds_event.sport_title,
                commence_time=odds_event.commence_time,
                home_team=odds_event.home_team,
                away_team=odds_event.away_team,
                last_update=datetime.now(timezone.utc),
                source_bookmaker=bookmaker.key
            )
            
            # Process each market type
            for market in bookmaker.markets:
                if market.key == MarketType.H2H.value:
                    processed_event.moneyline = await self._process_market(market, MarketType.H2H)
                elif market.key == MarketType.SPREADS.value:
                    processed_event.spreads = await self._process_market(market, MarketType.SPREADS)
                elif market.key == MarketType.TOTALS.value:
                    processed_event.totals = await self._process_market(market, MarketType.TOTALS)
            
            # Only return if we have at least one market
            if processed_event.moneyline or processed_event.spreads or processed_event.totals:
                return processed_event
            
            return None
            
        except Exception as e:
            print(f"❌ Error processing markets for {odds_event.home_team} vs {odds_event.away_team}: {e}")
            return None
    
    async def _process_market(self, market: BookmakerMarket, market_type: MarketType) -> ProcessedMarket:
        """Process a single market into ProcessedMarket"""
        processed_outcomes = []
        
        for outcome in market.outcomes:
            try:
                # Convert to ProcessedOutcome
                processed_outcome = ProcessedOutcome(
                    name=outcome.name,
                    american_odds=int(outcome.price),
                    decimal_odds=self._american_to_decimal(int(outcome.price)),
                    implied_probability=self._american_to_probability(int(outcome.price)),
                    point=outcome.point
                )
                processed_outcomes.append(processed_outcome)
                
            except Exception as e:
                print(f"⚠️  Error processing outcome {outcome.name}: {e}")
                continue
        
        return ProcessedMarket(
            market_type=market_type,
            outcomes=processed_outcomes,
            last_update=market.last_update
        )
    
    def _american_to_decimal(self, american_odds: int) -> float:
        """Convert American odds to decimal odds"""
        if american_odds > 0:
            return (american_odds / 100) + 1
        else:
            return (100 / abs(american_odds)) + 1
    
    def _american_to_probability(self, american_odds: int) -> float:
        """Convert American odds to implied probability"""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)
    
    async def _wait_for_rate_limit(self):
        """Wait if necessary to respect rate limits"""
        if self.last_request_time > 0:
            time_since_last = time.time() - self.last_request_time
            if time_since_last < self.min_request_interval:
                wait_time = self.min_request_interval - time_since_last
                await asyncio.sleep(wait_time)
    
    def get_cached_event(self, event_id: str) -> Optional[ProcessedEvent]:
        """Get event from cache if available and fresh"""
        if event_id in self.events_cache:
            event = self.events_cache[event_id]
            age = (datetime.now(timezone.utc) - event.last_update).total_seconds()
            if age < self.cache_ttl:
                return event
            else:
                # Remove stale cache entry
                del self.events_cache[event_id]
        return None
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get API usage statistics"""
        return {
            "total_credits_used": self.total_credits_used,
            "total_requests": self.requests_made,
            "credits_remaining": 15_000_000 - self.total_credits_used,  # Assuming 15M plan
            "cached_events": len(self.events_cache),
            "last_request_time": datetime.fromtimestamp(self.last_request_time).isoformat() if self.last_request_time else None
        }
    
    async def get_specific_event(self, event_id: str) -> Optional[ProcessedEvent]:
        """Get a specific event by ID (check cache first)"""
        # Check cache first
        cached_event = self.get_cached_event(event_id)
        if cached_event:
            return cached_event
        
        # If not in cache, we'd need to fetch all events (Odds API doesn't support single event lookup)
        # For now, return None - in practice you'd call get_events() and filter
        return None
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to The Odds API"""
        try:
            url = self.settings.get_odds_api_url("sports")
            params = {"apiKey": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        sports = await response.json()
                        return {
                            "success": True,
                            "message": "Successfully connected to The Odds API",
                            "available_sports": len(sports),
                            "baseball_available": any(sport.get("group") == "Baseball" for sport in sports)
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "message": f"API connection failed: HTTP {response.status}",
                            "error": error_text
                        }
        except Exception as e:
            return {
                "success": False,
                "message": "Connection test failed",
                "error": str(e)
            }
    
    def clear_cache(self):
        """Clear the events cache"""
        self.events_cache.clear()
        print("🗑️  Events cache cleared")

# Global odds API service instance
odds_api_service = OddsApiService()