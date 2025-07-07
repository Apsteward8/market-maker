#!/usr/bin/env python3
"""
Odds Data Models
Pydantic models for The Odds API data structures
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum

# =============================================================================
# Enums
# =============================================================================

class SportKey(str, Enum):
    """Supported sports from The Odds API"""
    BASEBALL = "baseball"
    # Add more sports as needed
    BASKETBALL = "basketball_nba"
    FOOTBALL = "americanfootball_nfl"
    SOCCER = "soccer_epl"

class MarketType(str, Enum):
    """Market types from The Odds API"""
    H2H = "h2h"  # Head-to-head (moneyline)
    SPREADS = "spreads"  # Point spreads
    TOTALS = "totals"  # Over/under totals

class Region(str, Enum):
    """Regions for odds data"""
    US = "us"
    UK = "uk"
    EU = "eu"
    AU = "au"

class OddsFormat(str, Enum):
    """Odds format"""
    AMERICAN = "american"
    DECIMAL = "decimal"
    FRACTIONAL = "fractional"

# =============================================================================
# Odds API Response Models
# =============================================================================

class BookmakerOutcome(BaseModel):
    """Individual outcome within a bookmaker's market"""
    name: str = Field(..., description="Outcome name (e.g., 'Novak Djokovic', 'Over 22.5')")
    price: float = Field(..., description="Odds price (format depends on odds_format)")
    point: Optional[float] = Field(None, description="Point value for spreads/totals")

class BookmakerMarket(BaseModel):
    """Market data from a specific bookmaker"""
    key: str = Field(..., description="Market type key (h2h, spreads, totals)")
    last_update: datetime = Field(..., description="When this market was last updated")
    outcomes: List[BookmakerOutcome] = Field(..., description="All outcomes in this market")

class Bookmaker(BaseModel):
    """Bookmaker data for an event"""
    key: str = Field(..., description="Bookmaker key (e.g., 'pinnacle', 'fanduel')")
    title: str = Field(..., description="Bookmaker display name")
    last_update: datetime = Field(..., description="When this bookmaker was last updated")
    markets: List[BookmakerMarket] = Field(..., description="All markets from this bookmaker")

class OddsEvent(BaseModel):
    """Complete event data from The Odds API"""
    id: str = Field(..., description="Unique event ID")
    sport_key: str = Field(..., description="Sport identifier")
    sport_title: str = Field(..., description="Sport display name")
    commence_time: datetime = Field(..., description="Event start time")
    home_team: str = Field(..., description="Home team/player name")
    away_team: str = Field(..., description="Away team/player name")
    bookmakers: List[Bookmaker] = Field(..., description="All bookmaker data for this event")

# =============================================================================
# Processed Odds Models (our internal representation)
# =============================================================================

class ProcessedOutcome(BaseModel):
    """Processed outcome with standardized pricing"""
    name: str = Field(..., description="Standardized outcome name")
    american_odds: int = Field(..., description="Odds in American format")
    decimal_odds: float = Field(..., description="Odds in decimal format")
    implied_probability: float = Field(..., description="Implied probability (0-1)")
    point: Optional[float] = Field(None, description="Point value for spreads/totals")

class ProcessedMarket(BaseModel):
    """Processed market with standardized data"""
    market_type: MarketType = Field(..., description="Type of market")
    outcomes: List[ProcessedOutcome] = Field(..., description="Processed outcomes")
    last_update: datetime = Field(..., description="When this market was last updated")
    
    def get_outcome_by_name(self, name: str) -> Optional[ProcessedOutcome]:
        """Get outcome by name"""
        for outcome in self.outcomes:
            if outcome.name.lower() == name.lower():
                return outcome
        return None
    
    def get_moneyline_favorite(self) -> Optional[ProcessedOutcome]:
        """Get the favorite in a moneyline market"""
        if self.market_type != MarketType.H2H:
            return None
        
        # Favorite has negative odds (or lowest positive odds)
        favorite = None
        for outcome in self.outcomes:
            if outcome.american_odds < 0:
                if favorite is None or outcome.american_odds > favorite.american_odds:
                    favorite = outcome
            elif favorite is None or (favorite.american_odds > 0 and outcome.american_odds < favorite.american_odds):
                favorite = outcome
        
        return favorite
    
    def get_moneyline_underdog(self) -> Optional[ProcessedOutcome]:
        """Get the underdog in a moneyline market"""
        if self.market_type != MarketType.H2H:
            return None
        
        favorite = self.get_moneyline_favorite()
        if not favorite:
            return None
        
        for outcome in self.outcomes:
            if outcome.name != favorite.name:
                return outcome
        
        return None

class ProcessedEvent(BaseModel):
    """Processed event with standardized market data"""
    event_id: str = Field(..., description="Unique event identifier")
    sport: str = Field(..., description="Sport name")
    commence_time: datetime = Field(..., description="Event start time")
    home_team: str = Field(..., description="Home team/player name")
    away_team: str = Field(..., description="Away team/player name")
    
    # Markets from our target bookmaker (Pinnacle)
    moneyline: Optional[ProcessedMarket] = Field(None, description="Moneyline market")
    spreads: Optional[ProcessedMarket] = Field(None, description="Spread market")
    totals: Optional[ProcessedMarket] = Field(None, description="Totals market")
    
    # Metadata
    last_update: datetime = Field(..., description="When this event was last processed")
    source_bookmaker: str = Field("pinnacle", description="Source bookmaker for odds")
    
    @property
    def display_name(self) -> str:
        """Get display name for this event"""
        return f"{self.away_team} vs {self.home_team}"
    
    @property
    def starts_in_hours(self) -> float:
        """Get hours until event starts"""
        now = datetime.now(self.commence_time.tzinfo)
        delta = self.commence_time - now
        return delta.total_seconds() / 3600
    
    @property
    def is_starting_soon(self) -> bool:
        """Check if event is starting within configured threshold"""
        from app.core.config import get_settings
        settings = get_settings()
        return self.starts_in_hours * 60 <= settings.min_time_before_start_minutes
    
    def get_available_markets(self) -> List[str]:
        """Get list of available market types"""
        markets = []
        if self.moneyline:
            markets.append("moneyline")
        if self.spreads:
            markets.append("spreads")
        if self.totals:
            markets.append("totals")
        return markets
    
    def has_significant_odds_change(self, other: 'ProcessedEvent', threshold: float = 0.02) -> bool:
        """Check if odds have changed significantly compared to another event"""
        if not other:
            return True
        
        # Check moneyline changes
        if self.moneyline and other.moneyline:
            for outcome in self.moneyline.outcomes:
                other_outcome = other.moneyline.get_outcome_by_name(outcome.name)
                if other_outcome:
                    prob_diff = abs(outcome.implied_probability - other_outcome.implied_probability)
                    if prob_diff >= threshold:
                        return True
        
        # Check spreads changes
        if self.spreads and other.spreads:
            for outcome in self.spreads.outcomes:
                other_outcome = other.spreads.get_outcome_by_name(outcome.name)
                if other_outcome:
                    prob_diff = abs(outcome.implied_probability - other_outcome.implied_probability)
                    point_diff = abs((outcome.point or 0) - (other_outcome.point or 0))
                    if prob_diff >= threshold or point_diff >= 0.5:
                        return True
        
        # Check totals changes
        if self.totals and other.totals:
            for outcome in self.totals.outcomes:
                other_outcome = other.totals.get_outcome_by_name(outcome.name)
                if other_outcome:
                    prob_diff = abs(outcome.implied_probability - other_outcome.implied_probability)
                    point_diff = abs((outcome.point or 0) - (other_outcome.point or 0))
                    if prob_diff >= threshold or point_diff >= 0.5:
                        return True
        
        return False

# =============================================================================
# Utility Models
# =============================================================================

class OddsApiRequest(BaseModel):
    """Configuration for an Odds API request"""
    sport: SportKey = Field(..., description="Sport to request")
    regions: List[Region] = Field(default=[Region.US], description="Regions to include")
    markets: List[MarketType] = Field(default=[MarketType.H2H], description="Markets to include")
    odds_format: OddsFormat = Field(default=OddsFormat.AMERICAN, description="Odds format")
    date_format: str = Field(default="iso", description="Date format")
    bookmakers: Optional[List[str]] = Field(None, description="Specific bookmakers to include")
    
    def calculate_credits(self) -> int:
        """Calculate how many API credits this request will cost"""
        return len(self.regions) * len(self.markets)

class OddsApiResponse(BaseModel):
    """Wrapper for Odds API responses"""
    events: List[OddsEvent] = Field(..., description="Event data from API")
    credits_used: int = Field(..., description="Credits consumed by this request")
    remaining_credits: int = Field(..., description="Credits remaining")
    timestamp: datetime = Field(..., description="When this data was fetched")