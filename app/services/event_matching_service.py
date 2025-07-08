#!/usr/bin/env python3
"""
Event Matching Service - UPDATED for 0.7 Confidence Threshold
Matches events between The Odds API (Pinnacle) and ProphetX with improved filtering
"""

import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models.odds_models import ProcessedEvent
from app.services.prophetx_events_service import ProphetXEvent, prophetx_events_service
from app.services.odds_api_service import odds_api_service

@dataclass
class EventMatch:
    """Represents a matched event between Odds API and ProphetX"""
    odds_api_event: ProcessedEvent
    prophetx_event: ProphetXEvent
    confidence_score: float
    match_reasons: List[str]
    created_at: datetime
    
    @property
    def display_summary(self) -> str:
        """Get a summary of this match"""
        return (f"Match: {self.odds_api_event.display_name} ↔ {self.prophetx_event.display_name} "
                f"(confidence: {self.confidence_score:.2f})")

@dataclass
class MatchingAttempt:
    """Result of an attempt to match an event"""
    odds_api_event: ProcessedEvent
    prophetx_matches: List[Tuple[ProphetXEvent, float]]  # (event, confidence)
    best_match: Optional[EventMatch]
    no_match_reason: Optional[str]

class EventMatchingService:
    """Service for matching events between The Odds API and ProphetX"""
    
    def __init__(self):
        # Store successful matches
        self.confirmed_matches: Dict[str, EventMatch] = {}  # odds_api_event_id -> match
        
        # Manual overrides for difficult matches
        self.manual_overrides: Dict[str, int] = {}  # odds_api_event_id -> prophetx_event_id
        
        # Name variations cache
        self.name_variations: Dict[str, List[str]] = {}
        
        # **UPDATED**: Changed back to 0.7 confidence threshold
        self.min_confidence_threshold = 0.7    # Raised back to 0.7
        self.display_threshold = 0.7           # NEW: Only show matches above this in prophetx_matches
        self.time_tolerance_minutes = 15.0     # 15 minutes tolerance
        
    async def find_matches_for_events(self, odds_api_events: List[ProcessedEvent]) -> List[MatchingAttempt]:
        """
        Find ProphetX matches for a list of Odds API events
        
        Args:
            odds_api_events: Events from The Odds API (Pinnacle)
            
        Returns:
            List of matching attempts with results
        """
        print(f"🔗 Finding ProphetX matches for {len(odds_api_events)} Odds API events...")
        print(f"   Confidence threshold: {self.min_confidence_threshold}")
        
        # Get all upcoming ProphetX events
        prophetx_events = await prophetx_events_service.get_all_upcoming_events()
        print(f"📋 Found {len(prophetx_events)} upcoming ProphetX events to match against")
        
        matching_attempts = []
        
        for odds_event in odds_api_events:
            attempt = await self._match_single_event(odds_event, prophetx_events)
            matching_attempts.append(attempt)
            
            if attempt.best_match:
                # Store the successful match
                self.confirmed_matches[odds_event.event_id] = attempt.best_match
                print(f"✅ {attempt.best_match.display_summary}")
            else:
                print(f"❌ No match found for: {odds_event.display_name}")
                print(f"   Reason: {attempt.no_match_reason}")
                if attempt.prophetx_matches:
                    best_confidence = attempt.prophetx_matches[0][1]
                    print(f"   Best confidence: {best_confidence:.3f} (threshold: {self.min_confidence_threshold})")
        
        successful_matches = sum(1 for attempt in matching_attempts if attempt.best_match)
        print(f"🎯 Successfully matched {successful_matches}/{len(odds_api_events)} events")
        
        return matching_attempts
    
    async def _match_single_event(
        self, 
        odds_event: ProcessedEvent, 
        prophetx_events: List[ProphetXEvent]
    ) -> MatchingAttempt:
        """
        Match a single Odds API event to ProphetX events
        
        Args:
            odds_event: Event from Odds API
            prophetx_events: List of available ProphetX events
            
        Returns:
            Matching attempt result
        """
        # Check for manual override first
        if odds_event.event_id in self.manual_overrides:
            override_id = self.manual_overrides[odds_event.event_id]
            for px_event in prophetx_events:
                if px_event.event_id == override_id:
                    match = EventMatch(
                        odds_api_event=odds_event,
                        prophetx_event=px_event,
                        confidence_score=1.0,
                        match_reasons=["Manual override"],
                        created_at=datetime.now()
                    )
                    return MatchingAttempt(
                        odds_api_event=odds_event,
                        prophetx_matches=[(px_event, 1.0)],
                        best_match=match,
                        no_match_reason=None
                    )
        
        # Find potential matches
        potential_matches = []
        
        for px_event in prophetx_events:
            confidence, reasons = self._calculate_match_confidence(odds_event, px_event)
            
            # **UPDATED**: Only include matches above display threshold in prophetx_matches
            if confidence >= self.display_threshold:
                potential_matches.append((px_event, confidence))
        
        # Sort by confidence
        potential_matches.sort(key=lambda x: x[1], reverse=True)
        
        # Check if we have a good enough match for actual matching
        best_match = None
        no_match_reason = None
        
        if potential_matches and potential_matches[0][1] >= self.min_confidence_threshold:
            px_event, confidence = potential_matches[0]
            
            # Create the match
            best_match = EventMatch(
                odds_api_event=odds_event,
                prophetx_event=px_event,
                confidence_score=confidence,
                match_reasons=self._get_match_reasons(odds_event, px_event),
                created_at=datetime.now()
            )
        else:
            # Determine why no match was found
            if not potential_matches:
                no_match_reason = f"No matches found above {self.display_threshold:.1f} confidence threshold"
            else:
                best_confidence = potential_matches[0][1]
                no_match_reason = f"Best confidence {best_confidence:.3f} below required {self.min_confidence_threshold:.1f}"
        
        return MatchingAttempt(
            odds_api_event=odds_event,
            prophetx_matches=potential_matches,  # Now only includes matches >= 0.7
            best_match=best_match,
            no_match_reason=no_match_reason
        )
    
    def _calculate_match_confidence(
        self, 
        odds_event: ProcessedEvent, 
        px_event: ProphetXEvent
    ) -> Tuple[float, List[str]]:
        """
        Calculate confidence score for an event match
        
        Args:
            odds_event: Event from Odds API
            px_event: Event from ProphetX
            
        Returns:
            Tuple of (confidence_score, reasons)
        """
        confidence = 0.0
        reasons = []
        
        # **TIME PROXIMITY CHECK** - with minutes tolerance
        time_diff_minutes = abs((odds_event.commence_time - px_event.commence_time).total_seconds() / 60)
        if time_diff_minutes > self.time_tolerance_minutes:
            return 0.0, [f"Time difference {time_diff_minutes:.1f}min exceeds {self.time_tolerance_minutes}min tolerance"]
        
        # **TIME SCORE** (closer = better) - 40% weight
        if time_diff_minutes <= 5:  # Perfect if within 5 minutes
            time_score = 1.0
        elif time_diff_minutes <= 10:  # Good if within 10 minutes  
            time_score = 0.9
        else:  # Acceptable up to 15 minutes
            time_score = 0.7
        
        confidence += time_score * 0.4  # 40% weight for time
        reasons.append(f"Time match: {time_score:.2f} (diff: {time_diff_minutes:.1f}min)")
        
        # **TEAM NAME MATCHING** - 60% weight
        team_score = self._calculate_team_name_score(odds_event, px_event)
        confidence += team_score * 0.6  # 60% weight for team names
        reasons.append(f"Team names: {team_score:.2f}")
        
        return min(confidence, 1.0), reasons
    
    def _calculate_team_name_score(self, odds_event: ProcessedEvent, px_event: ProphetXEvent) -> float:
        """Calculate team name similarity score"""
        
        # Normalize all team names
        odds_home = self._normalize_team_name(odds_event.home_team)
        odds_away = self._normalize_team_name(odds_event.away_team)
        px_home = self._normalize_team_name(px_event.home_team)
        px_away = self._normalize_team_name(px_event.away_team)
        
        # Try both orientations (home/away might be swapped)
        score1 = (self._team_similarity(odds_home, px_home) + 
                 self._team_similarity(odds_away, px_away)) / 2
        
        score2 = (self._team_similarity(odds_home, px_away) + 
                 self._team_similarity(odds_away, px_home)) / 2
        
        final_score = max(score1, score2)
        
        return final_score
    
    def _normalize_team_name(self, name: str) -> str:
        """Normalize a team name for comparison"""
        if not name:
            return ""
        
        # Convert to lowercase
        normalized = name.lower().strip()
        
        # Remove special characters and extra spaces
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized
    
    def _team_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two normalized team names"""
        if not name1 or not name2:
            return 0.0
        
        # Exact match
        if name1 == name2:
            return 1.0
        
        # One contains the other (handles "tigers" vs "detroit tigers")
        if name1 in name2 or name2 in name1:
            return 0.95
        
        # **IMPROVED**: Word overlap for team names
        words1 = set(name1.split())
        words2 = set(name2.split())
        
        if words1 and words2:
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            jaccard = len(intersection) / len(union) if union else 0
            
            # **BONUS**: If any significant words match (like team name), boost score
            if intersection:
                return min(0.95, jaccard + 0.2)
            else:
                return jaccard
        
        # Fuzzy string matching as fallback
        return SequenceMatcher(None, name1, name2).ratio()
    
    def _get_match_reasons(self, odds_event: ProcessedEvent, px_event: ProphetXEvent) -> List[str]:
        """Get detailed reasons for why events match"""
        reasons = []
        
        # Time analysis
        time_diff = abs((odds_event.commence_time - px_event.commence_time).total_seconds() / 60)
        reasons.append(f"Time difference: {time_diff:.1f} minutes")
        
        # Team name analysis
        reasons.append(f"Odds API teams: {odds_event.home_team} vs {odds_event.away_team}")
        reasons.append(f"ProphetX teams: {px_event.home_team} vs {px_event.away_team}")
        
        return reasons
    
    async def get_matched_events(self) -> List[EventMatch]:
        """Get all confirmed event matches"""
        return list(self.confirmed_matches.values())
    
    async def get_unmatched_odds_events(self) -> List[ProcessedEvent]:
        """Get Odds API events that don't have ProphetX matches"""
        odds_events = await odds_api_service.get_events()
        unmatched = []
        
        for event in odds_events:
            if event.event_id not in self.confirmed_matches:
                unmatched.append(event)
        
        return unmatched
    
    async def add_manual_override(self, odds_api_event_id: str, prophetx_event_id: int) -> bool:
        """
        Manually map an Odds API event to a ProphetX event
        
        Args:
            odds_api_event_id: Event ID from Odds API
            prophetx_event_id: Event ID from ProphetX
            
        Returns:
            True if override was added successfully
        """
        self.manual_overrides[odds_api_event_id] = prophetx_event_id
        print(f"✅ Added manual override: {odds_api_event_id} → {prophetx_event_id}")
        return True
    
    async def remove_manual_override(self, odds_api_event_id: str) -> bool:
        """Remove a manual override"""
        if odds_api_event_id in self.manual_overrides:
            del self.manual_overrides[odds_api_event_id]
            print(f"❌ Removed manual override for: {odds_api_event_id}")
            return True
        return False
    
    async def get_matching_summary(self) -> Dict[str, Any]:
        """Get comprehensive matching summary"""
        odds_events = await odds_api_service.get_events()
        prophetx_events = await prophetx_events_service.get_all_upcoming_events()
        
        matched_count = len(self.confirmed_matches)
        total_odds_events = len(odds_events)
        
        return {
            "total_odds_api_events": total_odds_events,
            "total_prophetx_events": len(prophetx_events),
            "successful_matches": matched_count,
            "match_rate": matched_count / total_odds_events if total_odds_events > 0 else 0,
            "manual_overrides": len(self.manual_overrides),
            "confidence_threshold": self.min_confidence_threshold,
            "display_threshold": self.display_threshold,
            "last_updated": datetime.now().isoformat()
        }
    
    async def refresh_all_matches(self) -> Dict[str, Any]:
        """
        Refresh all event matches
        
        Clears existing matches and re-runs matching for all current events
        """
        print("🔄 Refreshing all event matches...")
        print(f"   Using confidence threshold: {self.min_confidence_threshold}")
        
        # Clear existing matches (except manual overrides)
        self.confirmed_matches.clear()
        
        # Get fresh events from both sources
        odds_events = await odds_api_service.get_events()
        
        # Run matching
        attempts = await self.find_matches_for_events(odds_events)
        
        successful = sum(1 for attempt in attempts if attempt.best_match)
        failed = len(attempts) - successful
        
        return {
            "total_events_processed": len(attempts),
            "successful_matches": successful,
            "failed_matches": failed,
            "match_rate": successful / len(attempts) if attempts else 0,
            "confidence_threshold": self.min_confidence_threshold,
            "refresh_timestamp": datetime.now().isoformat()
        }
    
    def update_confidence_threshold(self, new_threshold: float) -> Dict[str, Any]:
        """
        Update the confidence threshold for matching
        
        Args:
            new_threshold: New minimum confidence threshold (0.0 - 1.0)
            
        Returns:
            Result of the update
        """
        if not 0.0 <= new_threshold <= 1.0:
            return {
                "success": False,
                "message": "Threshold must be between 0.0 and 1.0"
            }
        
        old_threshold = self.min_confidence_threshold
        self.min_confidence_threshold = new_threshold
        self.display_threshold = new_threshold  # Also update display threshold
        
        # Clear existing matches since criteria changed
        cleared_matches = len(self.confirmed_matches)
        self.confirmed_matches.clear()
        
        return {
            "success": True,
            "message": f"Confidence threshold updated from {old_threshold} to {new_threshold}",
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
            "cleared_matches": cleared_matches,
            "note": "Existing matches cleared - run refresh to re-match with new threshold"
        }

# Global event matching service instance  
event_matching_service = EventMatchingService()