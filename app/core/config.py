#!/usr/bin/env python3
"""
Market Maker Configuration
Application settings for ProphetX market making
"""

import os
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Market maker application settings"""
    
    # =============================================================================
    # The Odds API Configuration
    # =============================================================================
    odds_api_key: str = Field(..., description="The Odds API key")
    odds_api_base_url: str = Field("https://api.the-odds-api.com", description="The Odds API base URL")
    
    # =============================================================================
    # ProphetX Configuration (reused from scanner project)
    # =============================================================================
    prophetx_access_key: str = Field(..., description="ProphetX access key")
    prophetx_secret_key: str = Field(..., description="ProphetX secret key")
    prophetx_sandbox: bool = Field(True, description="Use ProphetX sandbox environment")
    
    # =============================================================================
    # Market Making Strategy Settings
    # =============================================================================
    
    # Target sport and markets
    focus_sport: str = Field("baseball", description="Primary sport to focus on")
    target_markets: str = Field("h2h,spreads,totals", description="Comma-separated list of market types")
    target_bookmaker: str = Field("pinnacle", description="Primary bookmaker to copy odds from")
    
    # Liquidity and risk management
    default_liquidity_amount: float = Field(100.0, description="Default liquidity to provide per market side")
    max_exposure_per_event: float = Field(500.0, description="Maximum total exposure per event")
    max_exposure_total: float = Field(2000.0, description="Maximum total exposure across all events")
    
    # Position sizing and limits
    min_bet_size: float = Field(5.0, description="Minimum bet size")
    max_bet_size: float = Field(200.0, description="Maximum bet size per position")
    
    # =============================================================================
    # Odds Polling and Updates
    # =============================================================================
    odds_poll_interval_seconds: int = Field(60, description="How often to poll for odds updates")
    significant_odds_change_threshold: float = Field(0.02, description="Minimum odds change to trigger update")
    
    # Event filtering
    max_events_tracked: int = Field(30, description="Maximum number of events to track simultaneously")
    events_lookahead_hours: int = Field(24, description="Only track events starting within this many hours")
    min_time_before_start_minutes: int = Field(15, description="Stop making markets this many minutes before start")
    
    # =============================================================================
    # API and Performance Settings
    # =============================================================================
    api_title: str = "ProphetX Market Maker"
    api_version: str = "1.0.0"
    api_debug: bool = Field(False, description="Enable debug mode")
    
    # Rate limiting and performance
    max_concurrent_requests: int = Field(10, description="Maximum concurrent API requests")
    request_timeout_seconds: int = Field(30, description="API request timeout")
    
    # =============================================================================
    # Automation and Scheduling
    # =============================================================================
    auto_start_polling: bool = Field(False, description="Automatically start odds polling on startup")
    auto_create_markets: bool = Field(False, description="Automatically create markets for new events")
    dry_run_mode: bool = Field(True, description="Simulate bets without placing them")
    
    # =============================================================================
    # Database and Logging
    # =============================================================================
    database_url: str = Field("sqlite:///./market_maker.db", description="Database connection string")
    log_level: str = Field("INFO", description="Logging level")
    save_odds_history: bool = Field(True, description="Save historical odds data")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }
    
    @property
    def prophetx_base_url(self) -> str:
        """Get ProphetX API base URL based on environment"""
        if self.prophetx_sandbox:
            return "https://api-ss-sandbox.betprophet.co"
        else:
            return "https://api-ss.betprophet.co"
    
    @property
    def target_markets_list(self) -> List[str]:
        """Parse target markets from comma-separated string"""
        return [market.strip() for market in self.target_markets.split(',') if market.strip()]
    
    @field_validator('odds_poll_interval_seconds')
    @classmethod
    def validate_poll_interval(cls, v):
        if v < 60:
            raise ValueError('Poll interval must be at least 30 seconds to avoid API rate limits')
        return v
    
    @field_validator('default_liquidity_amount')
    @classmethod
    def validate_liquidity_amount(cls, v):
        if v <= 0:
            raise ValueError('Liquidity amount must be positive')
        return v
    
    def get_odds_api_url(self, endpoint: str) -> str:
        """Build complete URL for Odds API endpoint"""
        return f"{self.odds_api_base_url}/v4/{endpoint}"
    
    def to_dict(self) -> dict:
        """Convert settings to dictionary (safe for API responses)"""
        return {
            "focus_sport": self.focus_sport,
            "target_markets": self.target_markets_list,
            "target_bookmaker": self.target_bookmaker,
            "default_liquidity_amount": self.default_liquidity_amount,
            "max_events_tracked": self.max_events_tracked,
            "odds_poll_interval_seconds": self.odds_poll_interval_seconds,
            "dry_run_mode": self.dry_run_mode,
            "prophetx_sandbox": self.prophetx_sandbox,
            "prophetx_base_url": self.prophetx_base_url
        }

@lru_cache()
def get_settings() -> Settings:
    """
    Get application settings (cached)
    This function is cached so settings are loaded once per app lifecycle
    """
    return Settings()

# Global settings instance
settings = get_settings()