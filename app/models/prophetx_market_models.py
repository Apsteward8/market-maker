#!/usr/bin/env python3
"""
ProphetX Market Models
Pydantic models for ProphetX market data structures
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from enum import Enum

# =============================================================================
# ProphetX Market Enums
# =============================================================================

class ProphetXMarketType(str, Enum):
    """ProphetX market types"""
    MONEYLINE = "moneyline"
    SPREAD = "spread" 
    TOTAL = "total"
    # Add more as needed

class ProphetXLineStatus(str, Enum):
    """Status of a ProphetX betting line"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"

# =============================================================================
# ProphetX Market Response Models
# =============================================================================

class ProphetXLine(BaseModel):
    """Individual betting line within a ProphetX market"""
    line_id: str = Field(..., description="Unique ProphetX line identifier for betting")
    selection_name: str = Field(..., description="Name of the selection (e.g., 'Detroit Tigers')")
    odds: Union[int, float] = Field(..., description="Odds in American format")
    point: Optional[float] = Field(None, description="Point value for spreads/totals")
    status: str = Field(default="active", description="Line status")
    
    # Additional ProphetX-specific fields
    max_bet: Optional[float] = Field(None, description="Maximum bet amount allowed")
    min_bet: Optional[float] = Field(None, description="Minimum bet amount")
    
    @property
    def american_odds(self) -> int:
        """Get odds as American format integer"""
        # Handle inactive lines with 0 odds
        if self.status == 'inactive' or self.odds == 0:
            return 0
        return int(self.odds)
    
    @property
    def is_active(self) -> bool:
        """Check if line is available for betting"""
        return self.status.lower() == "active" and self.odds != 0

class ProphetXRawMarket(BaseModel):
    """A complete market from ProphetX (e.g., moneyline, spread, total)"""
    market_id: str = Field(..., description="ProphetX market identifier")
    market_type: str = Field(..., description="Type of market (moneyline, spread, total)")
    event_id: int = Field(..., description="Associated ProphetX event ID")
    
    # Market details
    name: str = Field(..., description="Market display name")
    description: Optional[str] = Field(None, description="Market description")
    status: str = Field(default="active", description="Market status")
    
    # Lines within this market
    lines: List[ProphetXLine] = Field(..., description="All betting lines in this market")
    
    # Metadata
    created_at: Optional[datetime] = Field(None, description="When market was created")
    updated_at: Optional[datetime] = Field(None, description="Last update time")
    
    @property
    def is_active(self) -> bool:
        """Check if market is available for betting"""
        return self.status.lower() == "active"
    
    @property
    def active_lines(self) -> List[ProphetXLine]:
        """Get only active lines"""
        return [line for line in self.lines if line.is_active]
    
    def get_line_by_selection(self, selection_name: str) -> Optional[ProphetXLine]:
        """Find a line by selection name"""
        normalized_name = selection_name.lower().strip()
        for line in self.lines:
            if line.selection_name.lower().strip() == normalized_name:
                return line
        return None
    
    def get_lines_by_point(self, point: float, tolerance: float = 0.1) -> List[ProphetXLine]:
        """Find lines with specific point value (for spreads/totals)"""
        matching_lines = []
        for line in self.lines:
            if line.point is not None and abs(line.point - point) <= tolerance:
                matching_lines.append(line)
        return matching_lines

class ProphetXEventMarkets(BaseModel):
    """All markets for a specific ProphetX event"""
    event_id: int = Field(..., description="ProphetX event ID")
    event_name: str = Field(..., description="Event display name")
    markets: List[ProphetXRawMarket] = Field(..., description="All markets for this event")
    
    # Metadata
    last_updated: datetime = Field(..., description="When market data was last fetched")
    raw_response: Optional[Dict[str, Any]] = Field(None, description="Raw ProphetX API response")
    
    @property
    def active_markets(self) -> List[ProphetXRawMarket]:
        """Get only active markets"""
        return [market for market in self.markets if market.is_active]
    
    def get_market_by_type(self, market_type: str) -> Optional[ProphetXRawMarket]:
        """Get market by type (moneyline, spread, total)"""
        normalized_type = market_type.lower().strip()
        for market in self.markets:
            if market.market_type.lower().strip() == normalized_type:
                return market
        return None
    
    def get_moneyline_market(self) -> Optional[ProphetXRawMarket]:
        """Get moneyline market"""
        return self.get_market_by_type("moneyline")
    
    def get_spread_market(self) -> Optional[ProphetXRawMarket]:
        """Get spread market"""
        return self.get_market_by_type("spread")
    
    def get_total_market(self) -> Optional[ProphetXRawMarket]:
        """Get total (over/under) market"""
        return self.get_market_by_type("total")

# =============================================================================
# Market Matching Models
# =============================================================================

class MarketMatchResult(BaseModel):
    """Result of matching a single market between platforms"""
    odds_api_market_type: str = Field(..., description="Market type from Odds API")
    prophetx_market_id: Optional[str] = Field(None, description="Matched ProphetX market ID")
    prophetx_market_type: Optional[str] = Field(None, description="ProphetX market type")
    
    # Outcome mappings
    outcome_mappings: List[Dict[str, Any]] = Field(default=[], description="Mapped outcomes")
    
    # Match quality
    confidence_score: float = Field(..., description="Confidence in this match")
    match_status: str = Field(..., description="Status: matched, partial, failed")
    issues: List[str] = Field(default=[], description="Any issues with the match")
    
    @property
    def is_matched(self) -> bool:
        """Check if market was successfully matched"""
        return self.match_status == "matched"
    
    @property
    def has_issues(self) -> bool:
        """Check if there are any issues with this match"""
        return len(self.issues) > 0

class OutcomeMapping(BaseModel):
    """Mapping between an Odds API outcome and ProphetX line"""
    # Odds API side
    odds_api_outcome_name: str = Field(..., description="Outcome name from Odds API")
    odds_api_odds: int = Field(..., description="American odds from Odds API")
    odds_api_point: Optional[float] = Field(None, description="Point from Odds API")
    
    # ProphetX side  
    prophetx_line_id: str = Field(..., description="ProphetX line ID for betting")
    prophetx_selection_name: str = Field(..., description="Selection name from ProphetX")
    prophetx_odds: int = Field(..., description="Current ProphetX odds")
    prophetx_point: Optional[float] = Field(None, description="Point from ProphetX")
    
    # Match details
    confidence_score: float = Field(..., description="Confidence in this outcome mapping")
    name_similarity: float = Field(..., description="Name similarity score")
    point_match: bool = Field(default=True, description="Whether points match (for spreads/totals)")
    
    @property
    def odds_difference(self) -> int:
        """Calculate difference in odds"""
        return abs(self.odds_api_odds - self.prophetx_odds)
    
    @property
    def point_difference(self) -> float:
        """Calculate difference in points"""
        if self.odds_api_point is None or self.prophetx_point is None:
            return 0.0
        return abs(self.odds_api_point - self.prophetx_point)

class EventMarketsMatch(BaseModel):
    """Complete market matching result for an event"""
    # Event info
    odds_api_event_id: str = Field(..., description="Odds API event ID")
    prophetx_event_id: int = Field(..., description="ProphetX event ID")
    event_display_name: str = Field(..., description="Event name for display")
    
    # Market matches
    market_matches: List[MarketMatchResult] = Field(..., description="Results for each market type")
    
    # Overall assessment
    overall_confidence: float = Field(..., description="Overall matching confidence")
    ready_for_trading: bool = Field(..., description="Whether this event is ready for market making")
    issues: List[str] = Field(default=[], description="Any blocking issues")
    
    # Metadata
    matched_at: datetime = Field(..., description="When matching was performed")
    
    @property
    def successful_markets(self) -> List[MarketMatchResult]:
        """Get successfully matched markets"""
        return [match for match in self.market_matches if match.is_matched]
    
    @property
    def failed_markets(self) -> List[MarketMatchResult]:
        """Get failed market matches"""
        return [match for match in self.market_matches if not match.is_matched]
    
    @property
    def total_outcome_mappings(self) -> int:
        """Get total number of outcome mappings across all markets"""
        return sum(len(match.outcome_mappings) for match in self.market_matches)
    
    def get_market_match(self, market_type: str) -> Optional[MarketMatchResult]:
        """Get match result for specific market type"""
        normalized_type = market_type.lower()
        for match in self.market_matches:
            if match.odds_api_market_type.lower() == normalized_type:
                return match
        return None