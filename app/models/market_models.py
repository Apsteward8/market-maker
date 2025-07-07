#!/usr/bin/env python3
"""
Market and Position Models
Pydantic models for tracking ProphetX markets and positions
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum

# =============================================================================
# Enums
# =============================================================================

class MarketStatus(str, Enum):
    """Status of a market we're making"""
    PENDING = "pending"        # Market identified but not yet created
    ACTIVE = "active"          # Market is live and we're providing liquidity
    UPDATING = "updating"      # In process of updating odds
    PAUSED = "paused"          # Temporarily stopped (e.g., risk limits hit)
    CLOSED = "closed"          # Event finished or market closed
    ERROR = "error"            # Error state requiring manual intervention

class BetStatus(str, Enum):
    """Status of individual bets we've placed"""
    PENDING = "pending"        # Bet submitted but not confirmed
    PLACED = "placed"          # Bet successfully placed and waiting
    MATCHED = "matched"        # Bet has been matched (we have exposure)
    PARTIALLY_MATCHED = "partially_matched"  # Only part of bet matched
    CANCELLED = "cancelled"    # Bet was cancelled
    EXPIRED = "expired"        # Bet expired unmatched
    ERROR = "error"            # Error placing or managing bet

class PositionSide(str, Enum):
    """Which side of a market we're positioned on"""
    HOME = "home"              # We're exposed to home team/player winning
    AWAY = "away"              # We're exposed to away team/player winning
    OVER = "over"              # We're exposed to over total
    UNDER = "under"            # We're exposed to under total
    BOTH = "both"              # We have exposure on both sides (should be balanced)

# =============================================================================
# ProphetX Bet Models
# =============================================================================

class ProphetXBet(BaseModel):
    """Represents a single bet we've placed on ProphetX"""
    bet_id: Optional[str] = Field(None, description="ProphetX bet ID")
    external_id: str = Field(..., description="Our unique bet identifier")
    line_id: str = Field(..., description="ProphetX line ID")
    
    # Bet details
    selection_name: str = Field(..., description="What we're betting on")
    odds: int = Field(..., description="Odds in American format")
    stake: float = Field(..., description="Amount we're betting")
    
    # Status tracking
    status: BetStatus = Field(default=BetStatus.PENDING, description="Current bet status")
    matched_stake: float = Field(default=0.0, description="Amount of stake that's been matched")
    unmatched_stake: float = Field(default=0.0, description="Amount of stake still unmatched")
    
    # Metadata
    placed_at: datetime = Field(..., description="When we placed this bet")
    updated_at: datetime = Field(..., description="When bet status was last updated")
    error_message: Optional[str] = Field(None, description="Error message if status is ERROR")
    
    @property
    def is_active(self) -> bool:
        """Check if bet is active (placed and unmatched)"""
        return self.status == BetStatus.PLACED and self.unmatched_stake > 0
    
    @property
    def exposure_amount(self) -> float:
        """Calculate our exposure if this bet is matched"""
        if self.odds > 0:
            # Positive odds: we win stake * (odds/100)
            return self.matched_stake * (self.odds / 100)
        else:
            # Negative odds: we risk stake * (100/abs(odds))
            return self.matched_stake

# =============================================================================
# Market Making Models
# =============================================================================

class MarketSide(BaseModel):
    """One side of a market we're making (e.g., home team in moneyline)"""
    selection_name: str = Field(..., description="Name of this selection")
    target_odds: int = Field(..., description="Target odds we want to offer")
    current_bet: Optional[ProphetXBet] = Field(None, description="Current active bet for this side")
    liquidity_amount: float = Field(..., description="How much liquidity to provide")
    
    # Risk tracking
    total_matched_stake: float = Field(default=0.0, description="Total stake matched on this side")
    max_exposure: float = Field(..., description="Maximum exposure we're willing to take")
    
    @property
    def needs_liquidity(self) -> bool:
        """Check if we need to place/refresh liquidity"""
        if not self.current_bet:
            return True
        return not self.current_bet.is_active
    
    @property
    def current_exposure(self) -> float:
        """Calculate current exposure on this side"""
        if not self.current_bet:
            return 0.0
        return self.current_bet.exposure_amount

class ProphetXMarket(BaseModel):
    """Represents a market we're making on ProphetX"""
    market_id: str = Field(..., description="Unique identifier for this market")
    event_id: str = Field(..., description="Associated event ID")
    market_type: str = Field(..., description="Type of market (moneyline, spreads, totals)")
    
    # Event details
    event_name: str = Field(..., description="Display name of the event")
    commence_time: datetime = Field(..., description="When the event starts")
    
    # Market sides
    sides: List[MarketSide] = Field(..., description="All sides of this market")
    
    # Status and risk
    status: MarketStatus = Field(default=MarketStatus.PENDING, description="Current market status")
    total_exposure: float = Field(default=0.0, description="Total exposure across all sides")
    max_exposure: float = Field(..., description="Maximum exposure allowed for this market")
    
    # Tracking
    created_at: datetime = Field(..., description="When we started making this market")
    last_updated: datetime = Field(..., description="When market was last updated")
    update_count: int = Field(default=0, description="Number of times we've updated odds")
    error_message: Optional[str] = Field(None, description="Error message if status is ERROR")
    
    @property
    def is_active(self) -> bool:
        """Check if market is actively being made"""
        return self.status == MarketStatus.ACTIVE
    
    @property
    def needs_update(self) -> bool:
        """Check if any side needs liquidity refresh"""
        return any(side.needs_liquidity for side in self.sides)
    
    @property
    def net_position(self) -> Dict[str, float]:
        """Calculate net position across all sides"""
        position = {}
        for side in self.sides:
            position[side.selection_name] = side.current_exposure
        return position
    
    def get_side_by_name(self, selection_name: str) -> Optional[MarketSide]:
        """Get market side by selection name"""
        for side in self.sides:
            if side.selection_name.lower() == selection_name.lower():
                return side
        return None

# =============================================================================
# Event and Portfolio Models
# =============================================================================

class ManagedEvent(BaseModel):
    """An event we're actively managing markets for"""
    event_id: str = Field(..., description="Unique event identifier")
    sport: str = Field(..., description="Sport name")
    home_team: str = Field(..., description="Home team/player")
    away_team: str = Field(..., description="Away team/player")
    commence_time: datetime = Field(..., description="Event start time")
    
    # Markets we're making
    markets: List[ProphetXMarket] = Field(default=[], description="Markets we're making for this event")
    
    # Risk and exposure
    total_exposure: float = Field(default=0.0, description="Total exposure across all markets")
    max_exposure: float = Field(..., description="Maximum exposure allowed for this event")
    
    # Status
    status: MarketStatus = Field(default=MarketStatus.PENDING, description="Overall event status")
    last_odds_update: Optional[datetime] = Field(None, description="When odds were last updated")
    
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
    def should_stop_making_markets(self) -> bool:
        """Check if we should stop making markets (too close to start)"""
        from app.core.config import get_settings
        settings = get_settings()
        return self.starts_in_hours * 60 <= settings.min_time_before_start_minutes
    
    def get_market_by_type(self, market_type: str) -> Optional[ProphetXMarket]:
        """Get market by type"""
        for market in self.markets:
            if market.market_type == market_type:
                return market
        return None
    
    def calculate_total_exposure(self) -> float:
        """Recalculate total exposure across all markets"""
        total = sum(market.total_exposure for market in self.markets)
        self.total_exposure = total
        return total

class PortfolioSummary(BaseModel):
    """Summary of our entire portfolio"""
    total_events: int = Field(..., description="Number of events being managed")
    active_markets: int = Field(..., description="Number of active markets")
    total_bets: int = Field(..., description="Total number of bets placed")
    active_bets: int = Field(..., description="Number of active (unmatched) bets")
    
    # Financial summary
    total_exposure: float = Field(..., description="Total exposure across all positions")
    total_liquidity_provided: float = Field(..., description="Total liquidity we're providing")
    matched_stake: float = Field(..., description="Total stake that's been matched")
    unmatched_stake: float = Field(..., description="Total stake waiting to be matched")
    
    # Performance
    successful_market_updates: int = Field(..., description="Number of successful market updates")
    failed_market_updates: int = Field(..., description="Number of failed market updates")
    uptime_hours: float = Field(..., description="Hours system has been running")
    
    # Risk metrics
    max_single_event_exposure: float = Field(..., description="Largest exposure on any single event")
    utilization_percentage: float = Field(..., description="Percentage of max capacity being used")
    
    @property
    def success_rate(self) -> float:
        """Calculate market update success rate"""
        total_updates = self.successful_market_updates + self.failed_market_updates
        if total_updates == 0:
            return 1.0
        return self.successful_market_updates / total_updates

# =============================================================================
# Risk Management Models
# =============================================================================

class RiskLimit(BaseModel):
    """Risk limit configuration"""
    limit_type: str = Field(..., description="Type of limit (exposure, event_count, etc.)")
    current_value: float = Field(..., description="Current value")
    limit_value: float = Field(..., description="Maximum allowed value")
    warning_threshold: float = Field(..., description="Warning threshold (percentage of limit)")
    
    @property
    def utilization_percentage(self) -> float:
        """Calculate utilization as percentage of limit"""
        if self.limit_value == 0:
            return 0.0
        return (self.current_value / self.limit_value) * 100
    
    @property
    def is_warning(self) -> bool:
        """Check if we're above warning threshold"""
        return self.utilization_percentage >= self.warning_threshold
    
    @property
    def is_exceeded(self) -> bool:
        """Check if limit is exceeded"""
        return self.current_value >= self.limit_value

class RiskReport(BaseModel):
    """Comprehensive risk report"""
    timestamp: datetime = Field(..., description="When this report was generated")
    limits: List[RiskLimit] = Field(..., description="All risk limits and their status")
    warnings: List[str] = Field(default=[], description="Current risk warnings")
    recommendations: List[str] = Field(default=[], description="Risk management recommendations")
    
    @property
    def has_warnings(self) -> bool:
        """Check if there are any risk warnings"""
        return len(self.warnings) > 0 or any(limit.is_warning for limit in self.limits)
    
    @property
    def has_violations(self) -> bool:
        """Check if any limits are exceeded"""
        return any(limit.is_exceeded for limit in self.limits)