#!/usr/bin/env python3
"""
ProphetX Events Service
Handles fetching upcoming events from ProphetX API
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from fastapi import HTTPException

from app.services.prophetx_service import prophetx_service

@dataclass
class ProphetXEvent:
    """ProphetX event structure"""
    event_id: int
    sport_name: str
    tournament_name: str
    home_team: str
    away_team: str
    commence_time: datetime
    status: str
    raw_data: Dict[str, Any]
    
    @property
    def display_name(self) -> str:
        """Get display name for this event"""
        return f"{self.away_team} vs {self.home_team}"
    
    @property
    def starts_in_hours(self) -> float:
        """Get hours until event starts"""
        now = datetime.now(self.commence_time.tzinfo if self.commence_time.tzinfo else timezone.utc)
        delta = self.commence_time - now
        return delta.total_seconds() / 3600

@dataclass
class ProphetXTournament:
    """ProphetX tournament structure"""
    tournament_id: int
    name: str
    sport_name: str
    category_name: Optional[str]
    raw_data: Dict[str, Any]

class ProphetXEventsService:
    """Service for fetching ProphetX events and tournaments"""
    
    def __init__(self):
        # Cache for tournaments and events
        self.tournaments_cache: List[ProphetXTournament] = []
        self.events_cache: Dict[int, List[ProphetXEvent]] = {}
        self.cache_ttl = 300  # 5 minutes
        self.last_cache_update = 0
        
    async def get_tournaments(self, sport_filter: str = "baseball") -> List[ProphetXTournament]:
        """
        Get all available tournaments from ProphetX
        
        Args:
            sport_filter: Filter by sport name (case insensitive)
            
        Returns:
            List of ProphetX tournaments
        """
        print(f"🏆 Fetching ProphetX tournaments (filter: {sport_filter})...")
        
        try:
            headers = await prophetx_service.get_auth_headers()
            url = f"{prophetx_service.base_url}/partner/mm/get_tournaments"
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                tournaments_data = data.get('data', {}).get('tournaments', [])
                
                tournaments = []
                for tournament_data in tournaments_data:
                    sport_name = tournament_data.get('sport', {}).get('name', '').lower()
                    
                    # Filter by sport if specified
                    if sport_filter and sport_filter.lower() not in sport_name:
                        continue
                    
                    tournament = ProphetXTournament(
                        tournament_id=tournament_data.get('id'),
                        name=tournament_data.get('name', 'Unknown Tournament'),
                        sport_name=tournament_data.get('sport', {}).get('name', 'Unknown'),
                        category_name=tournament_data.get('category', {}).get('name'),
                        raw_data=tournament_data
                    )
                    tournaments.append(tournament)
                
                print(f"✅ Found {len(tournaments)} {sport_filter} tournaments on ProphetX")
                
                # Log tournament details for debugging
                for tournament in tournaments[:5]:  # Show first 5
                    print(f"   📋 {tournament.name} (ID: {tournament.tournament_id})")
                
                self.tournaments_cache = tournaments
                return tournaments
                
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error fetching ProphetX tournaments: {response.text}"
                )
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching tournaments: {str(e)}")
    
    async def get_events_for_tournament(self, tournament_id: int) -> List[ProphetXEvent]:
        """
        Get all upcoming events for a specific tournament
        
        Args:
            tournament_id: ProphetX tournament ID
            
        Returns:
            List of ProphetX events
        """
        print(f"📅 Fetching events for ProphetX tournament {tournament_id}...")
        
        try:
            headers = await prophetx_service.get_auth_headers()
            url = f"{prophetx_service.base_url}/partner/mm/get_sport_events"
            params = {"tournament_id": tournament_id}
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                events_data = data.get('data', {}).get('sport_events', [])
                
                events = []
                for event_data in events_data:
                    # Only include upcoming events
                    status = event_data.get('status', '').lower()
                    if status != 'not_started':
                        continue
                    
                    # Parse event details
                    try:
                        # Handle different time formats
                        scheduled_str = event_data.get('scheduled', '')
                        if scheduled_str:
                            try:
                                commence_time = datetime.fromisoformat(scheduled_str.replace('Z', '+00:00'))
                            except:
                                # Fallback parsing
                                commence_time = datetime.now(timezone.utc) + timedelta(hours=24)
                        else:
                            commence_time = datetime.now(timezone.utc) + timedelta(hours=24)
                        
                        # Extract team names - ProphetX might use different fields
                        home_team = event_data.get('home_team', event_data.get('home_competitor', {}).get('name', 'Unknown Home'))
                        away_team = event_data.get('away_team', event_data.get('away_competitor', {}).get('name', 'Unknown Away'))
                        
                        # Some APIs might have different structures
                        if isinstance(home_team, dict):
                            home_team = home_team.get('name', 'Unknown Home')
                        if isinstance(away_team, dict):
                            away_team = away_team.get('name', 'Unknown Away')
                        
                        event = ProphetXEvent(
                            event_id=event_data.get('event_id', event_data.get('id')),
                            sport_name=event_data.get('sport_name', 'Tennis'),
                            tournament_name=event_data.get('tournament_name', 'Unknown Tournament'),
                            home_team=str(home_team),
                            away_team=str(away_team),
                            commence_time=commence_time,
                            status=event_data.get('status', 'not_started'),
                            raw_data=event_data
                        )
                        events.append(event)
                        
                    except Exception as e:
                        print(f"⚠️  Error parsing event: {e}")
                        print(f"   Raw data: {event_data}")
                        continue
                
                print(f"✅ Found {len(events)} upcoming events in tournament {tournament_id}")
                
                # Show sample events for debugging
                for event in events[:3]:
                    print(f"   🎾 {event.display_name} (starts in {event.starts_in_hours:.1f}h)")
                
                # Cache the results
                self.events_cache[tournament_id] = events
                
                return events
                
            else:
                print(f"❌ Error fetching events for tournament {tournament_id}: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Error fetching events for tournament {tournament_id}: {e}")
            return []
    
    async def get_all_upcoming_events(self, hours_ahead: int = 72) -> List[ProphetXEvent]:
        """
        Get all upcoming baseball events from ProphetX
        
        Args:
            hours_ahead: Look ahead this many hours
            
        Returns:
            List of all upcoming ProphetX baseball events
        """
        print(f"🔍 Fetching all upcoming ProphetX baseball events (next {hours_ahead} hours)...")
        
        # Get all baseball tournaments
        tournaments = await self.get_tournaments(sport_filter="baseball")
        
        all_events = []
        cutoff_time = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
        
        for tournament in tournaments:
            try:
                events = await self.get_events_for_tournament(tournament.tournament_id)
                
                # Filter by time window
                for event in events:
                    if event.commence_time <= cutoff_time:
                        all_events.append(event)
                        
            except Exception as e:
                print(f"⚠️  Error fetching events for {tournament.name}: {e}")
                continue
        
        # Sort by start time
        all_events.sort(key=lambda x: x.commence_time)
        
        print(f"✅ Total upcoming ProphetX baseball events: {len(all_events)}")
        
        return all_events
    
    async def get_event_markets(self, event_id: int) -> Optional[Dict[str, Any]]:
        """
        Get available markets for a specific ProphetX event
        
        Args:
            event_id: ProphetX event ID
            
        Returns:
            Market data or None if not available
        """
        try:
            headers = await prophetx_service.get_auth_headers()
            url = f"{prophetx_service.base_url}/partner/v2/mm/get_markets"
            params = {"event_id": event_id}
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Error fetching markets for event {event_id}: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error fetching markets for event {event_id}: {e}")
            return None
    
    async def find_event_by_teams_and_time(
        self, 
        home_team: str, 
        away_team: str, 
        commence_time: datetime,
        time_tolerance_hours: float = 2.0
    ) -> Optional[ProphetXEvent]:
        """
        Find a ProphetX event by team names and start time
        
        Args:
            home_team: Home team name
            away_team: Away team name  
            commence_time: Expected start time
            time_tolerance_hours: How close the times need to be
            
        Returns:
            Matching ProphetX event or None
        """
        all_events = await self.get_all_upcoming_events()
        
        # Normalize team names for comparison
        home_normalized = self._normalize_team_name(home_team)
        away_normalized = self._normalize_team_name(away_team)
        
        for event in all_events:
            # Check time proximity
            time_diff = abs((event.commence_time - commence_time).total_seconds() / 3600)
            if time_diff > time_tolerance_hours:
                continue
            
            # Check team name similarity
            event_home_norm = self._normalize_team_name(event.home_team)
            event_away_norm = self._normalize_team_name(event.away_team)
            
            # Check both orientations (home/away might be swapped)
            match1 = (self._teams_match(home_normalized, event_home_norm) and 
                     self._teams_match(away_normalized, event_away_norm))
            match2 = (self._teams_match(home_normalized, event_away_norm) and 
                     self._teams_match(away_normalized, event_home_norm))
            
            if match1 or match2:
                print(f"✅ Found ProphetX match: {event.display_name} (ID: {event.event_id})")
                return event
        
        return None
    
    def _normalize_team_name(self, name: str) -> str:
        """Normalize team name for comparison"""
        if not name:
            return ""
        
        # Convert to lowercase and remove common variations
        normalized = name.lower().strip()
        
        # Remove common prefixes/suffixes
        normalized = normalized.replace(".", "")
        normalized = normalized.replace(",", "")
        
        # Handle common baseball name variations
        # "Novak Djokovic" -> "djokovic novak"
        parts = normalized.split()
        if len(parts) >= 2:
            # Sort parts to handle "First Last" vs "Last, First" variations
            parts.sort()
            normalized = " ".join(parts)
        
        return normalized
    
    def _teams_match(self, name1: str, name2: str, threshold: float = 0.8) -> bool:
        """Check if two team names match with fuzzy matching"""
        if not name1 or not name2:
            return False
        
        # Exact match
        if name1 == name2:
            return True
        
        # Check if one contains the other
        if name1 in name2 or name2 in name1:
            return True
        
        # Simple word overlap check for baseball players
        words1 = set(name1.split())
        words2 = set(name2.split())
        
        if words1 and words2:
            overlap = len(words1.intersection(words2))
            total_unique = len(words1.union(words2))
            similarity = overlap / total_unique if total_unique > 0 else 0
            return similarity >= threshold
        
        return False

# Global ProphetX events service instance
prophetx_events_service = ProphetXEventsService()