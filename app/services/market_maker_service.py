#!/usr/bin/env python3
"""
Market Maker Service
Core market making logic for ProphetX using Pinnacle odds
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from fastapi import HTTPException

from app.core.config import get_settings
from app.models.odds_models import ProcessedEvent, ProcessedMarket, ProcessedOutcome, MarketType
from app.models.market_models import (
    ManagedEvent, ProphetXMarket, MarketSide, ProphetXBet, 
    MarketStatus, BetStatus, PortfolioSummary, RiskReport, RiskLimit
)
from app.services.odds_api_service import odds_api_service

class MarketMakerService:
    """Core service for making markets on ProphetX"""
    
    def __init__(self):
        self.settings = get_settings()
        
        # Portfolio tracking
        self.managed_events: Dict[str, ManagedEvent] = {}
        self.all_bets: Dict[str, ProphetXBet] = {}  # external_id -> bet
        
        # System state
        self.is_running = False
        self.start_time = None
        self.total_markets_created = 0
        self.total_updates_successful = 0
        self.total_updates_failed = 0
        
        # Risk tracking
        self.total_exposure = 0.0
        self.max_exposure_reached = 0.0
        
    async def start_market_making(self) -> Dict[str, Any]:
        """Start the market making system"""
        if self.is_running:
            return {"success": False, "message": "Market making is already running"}
        
        print("🚀 Starting ProphetX Market Making System")
        print(f"   Target: {self.settings.focus_sport} using {self.settings.target_bookmaker} odds")
        print(f"   Liquidity: ${self.settings.default_liquidity_amount} per market side")
        print(f"   Max events: {self.settings.max_events_tracked}")
        
        self.is_running = True
        self.start_time = datetime.now(timezone.utc)
        
        # Start main market making loop
        if self.settings.auto_start_polling:
            asyncio.create_task(self._market_making_loop())
        
        return {
            "success": True,
            "message": "Market making system started",
            "settings": self.settings.to_dict()
        }
    
    async def stop_market_making(self) -> Dict[str, Any]:
        """Stop the market making system"""
        print("🛑 Stopping market making system...")
        self.is_running = False
        
        # Cancel all active bets
        cancelled_count = 0
        for event in self.managed_events.values():
            for market in event.markets:
                for side in market.sides:
                    if side.current_bet and side.current_bet.is_active:
                        # In a real implementation, cancel the bet on ProphetX
                        side.current_bet.status = BetStatus.CANCELLED
                        cancelled_count += 1
        
        return {
            "success": True,
            "message": f"Market making stopped. {cancelled_count} active bets cancelled.",
            "final_stats": await self.get_system_stats()
        }
    
    async def _market_making_loop(self):
        """Main market making loop"""
        while self.is_running:
            try:
                print(f"🔄 Market making cycle starting...")
                
                # 1. Get matched events (events that exist on both platforms)
                from app.services.event_matching_service import event_matching_service
                matched_events = await event_matching_service.get_matched_events()
                
                if not matched_events:
                    print("⚠️  No matched events found. Run event matching first.")
                    await asyncio.sleep(30)
                    continue
                
                print(f"📊 Found {len(matched_events)} matched events to manage")
                
                # 2. Update or create markets for matched events
                for match in matched_events:
                    await self._manage_matched_event(match)
                
                # 3. Clean up expired events
                await self._cleanup_expired_events()
                
                # 4. Check risk limits
                await self._check_risk_limits()
                
                print(f"✅ Market making cycle complete. Managing {len(self.managed_events)} events.")
                
                # Wait before next cycle
                await asyncio.sleep(self.settings.odds_poll_interval_seconds)
                
            except Exception as e:
                print(f"💥 Error in market making loop: {e}")
                await asyncio.sleep(30)  # Wait before retrying
    
    async def _manage_matched_event(self, event_match):
        """
        Manage markets for a matched event (exists on both Odds API and ProphetX)
        
        Args:
            event_match: EventMatch object containing both Odds API and ProphetX event data
        """
        odds_event = event_match.odds_api_event  # Has the pricing data from Pinnacle
        prophetx_event = event_match.prophetx_event  # Has the ProphetX event ID for bet placement
        
        # Use ProphetX event ID as the key for our managed events
        event_id = str(prophetx_event.event_id)
        
        # Get or create managed event
        if event_id not in self.managed_events:
            managed_event = ManagedEvent(
                event_id=event_id,
                sport=prophetx_event.sport_name,
                home_team=prophetx_event.home_team,
                away_team=prophetx_event.away_team,
                commence_time=prophetx_event.commence_time,
                max_exposure=self.settings.max_exposure_per_event
            )
            self.managed_events[event_id] = managed_event
            print(f"📝 Started managing: {managed_event.display_name} (ProphetX ID: {prophetx_event.event_id})")
        else:
            managed_event = self.managed_events[event_id]
        
        # Check if we should stop making markets (too close to start)
        if managed_event.should_stop_making_markets:
            print(f"⏰ Stopping markets for {managed_event.display_name} (starts soon)")
            managed_event.status = MarketStatus.CLOSED
            return
        
        # Update markets based on latest Pinnacle odds, but use ProphetX event details
        await self._update_matched_event_markets(managed_event, odds_event, prophetx_event)
    
    async def _update_matched_event_markets(self, managed_event: ManagedEvent, odds_event, prophetx_event):
        """
        Update markets for a matched event using Pinnacle odds and ProphetX event details
        
        Args:
            managed_event: Our internal event tracking
            odds_event: ProcessedEvent from Odds API with Pinnacle pricing
            prophetx_event: ProphetXEvent with ProphetX-specific details
        """
        try:
            # Handle moneyline market using Pinnacle odds
            if odds_event.moneyline:
                await self._update_or_create_moneyline_market(managed_event, odds_event.moneyline, prophetx_event)
            
            # Handle spreads market using Pinnacle odds
            if odds_event.spreads:
                await self._update_or_create_spreads_market(managed_event, odds_event.spreads, prophetx_event)
            
            # Handle totals market using Pinnacle odds
            if odds_event.totals:
                await self._update_or_create_totals_market(managed_event, odds_event.totals, prophetx_event)
            
            managed_event.last_odds_update = datetime.now(timezone.utc)
            managed_event.status = MarketStatus.ACTIVE
            
        except Exception as e:
            print(f"❌ Error updating markets for {managed_event.display_name}: {e}")
            managed_event.status = MarketStatus.ERROR
    
    async def _update_or_create_moneyline_market(self, managed_event: ManagedEvent, moneyline: ProcessedMarket, prophetx_event=None):
        """Update or create moneyline market"""
        market_type = "moneyline"
        existing_market = managed_event.get_market_by_type(market_type)
        
        if not existing_market:
            # Create new market
            market = await self._create_moneyline_market(managed_event, moneyline, prophetx_event)
            if market:
                managed_event.markets.append(market)
                self.total_markets_created += 1
        else:
            # Update existing market
            await self._update_moneyline_market(existing_market, moneyline, prophetx_event)
    
    async def _create_moneyline_market(self, managed_event: ManagedEvent, moneyline: ProcessedMarket, prophetx_event=None) -> Optional[ProphetXMarket]:
        """Create a new moneyline market"""
        try:
            print(f"🎾 Creating moneyline market for {managed_event.display_name}")
            
            # Get outcomes (should be 2 for baseball: player 1 and player 2)
            if len(moneyline.outcomes) != 2:
                print(f"⚠️  Expected 2 outcomes for moneyline, got {len(moneyline.outcomes)}")
                return None
            
            outcome1, outcome2 = moneyline.outcomes
            
            # Create market sides - we offer the OPPOSITE of what Pinnacle offers
            # If Pinnacle has Player A at -110, we bet Player A at +110 to offer -110 to others
            sides = [
                MarketSide(
                    selection_name=outcome1.name,
                    target_odds=outcome1.american_odds,  # We copy Pinnacle exactly
                    liquidity_amount=self.settings.default_liquidity_amount,
                    max_exposure=self.settings.max_exposure_per_event / 4  # Split across market sides
                ),
                MarketSide(
                    selection_name=outcome2.name,
                    target_odds=outcome2.american_odds,
                    liquidity_amount=self.settings.default_liquidity_amount,
                    max_exposure=self.settings.max_exposure_per_event / 4
                )
            ]
            
            market = ProphetXMarket(
                market_id=f"{managed_event.event_id}_moneyline",
                event_id=managed_event.event_id,
                market_type=market_type,
                event_name=managed_event.display_name,
                commence_time=managed_event.commence_time,
                sides=sides,
                max_exposure=self.settings.max_exposure_per_event / 2,  # Half event exposure for this market
                created_at=datetime.now(timezone.utc),
                last_updated=datetime.now(timezone.utc)
            )
            
            # Place initial bets for each side
            for side in market.sides:
                await self._place_market_side_bet(side, managed_event, prophetx_event)
            
            return market
            
        except Exception as e:
            print(f"❌ Error creating moneyline market: {e}")
            return None
    
    async def _place_market_side_bet(self, side: MarketSide, managed_event: ManagedEvent, prophetx_event=None) -> bool:
        """Place a bet for one side of a market"""
        try:
            if not self.settings.dry_run_mode:
                print(f"🚨 LIVE MODE: Would place real bet here!")
                # In live mode, we'd actually place the bet on ProphetX using prophetx_event details
                # For now, simulate the bet placement
            
            # Calculate the bet we need to place
            # If Pinnacle offers Player A at -110, we bet Player A at +110
            # This means we're offering -110 to other users (copying Pinnacle)
            bet_odds = side.target_odds
            
            # Create simulated bet
            external_id = f"{managed_event.event_id}_{side.selection_name}_{int(time.time())}"
            
            # In a real implementation, we would use prophetx_event.event_id 
            # to get the actual market data from ProphetX and find the correct line_id
            simulated_line_id = f"prophetx_line_{prophetx_event.event_id if prophetx_event else 'unknown'}_{side.selection_name}"
            
            bet = ProphetXBet(
                external_id=external_id,
                line_id=simulated_line_id,
                selection_name=side.selection_name,
                odds=bet_odds,
                stake=side.liquidity_amount,
                status=BetStatus.PLACED if not self.settings.dry_run_mode else BetStatus.PENDING,
                unmatched_stake=side.liquidity_amount,
                placed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            # Store bet
            self.all_bets[external_id] = bet
            side.current_bet = bet
            
            mode_indicator = '[DRY RUN] ' if self.settings.dry_run_mode else ''
            prophetx_id = f"PX:{prophetx_event.event_id}" if prophetx_event else "PX:unknown"
            
            print(f"💰 {mode_indicator}Bet placed: {side.selection_name} {bet_odds:+d} for ${side.liquidity_amount} ({prophetx_id})")
            
            return True
            
        except Exception as e:
            print(f"❌ Error placing bet for {side.selection_name}: {e}")
            return False
    
    async def _update_moneyline_market(self, market: ProphetXMarket, updated_moneyline: ProcessedMarket, prophetx_event=None):
        """Update existing moneyline market with new odds"""
        try:
            # Check if odds have changed significantly
            needs_update = False
            
            for side in market.sides:
                # Find corresponding outcome in updated data
                updated_outcome = None
                for outcome in updated_moneyline.outcomes:
                    if outcome.name.lower() == side.selection_name.lower():
                        updated_outcome = outcome
                        break
                
                if updated_outcome and updated_outcome.american_odds != side.target_odds:
                    print(f"📊 Odds change detected: {side.selection_name} {side.target_odds:+d} → {updated_outcome.american_odds:+d}")
                    side.target_odds = updated_outcome.american_odds
                    needs_update = True
            
            if needs_update:
                # Cancel existing bets and place new ones
                for side in market.sides:
                    if side.current_bet and side.current_bet.is_active:
                        # Cancel existing bet
                        side.current_bet.status = BetStatus.CANCELLED
                        print(f"❌ Cancelled bet: {side.current_bet.external_id}")
                    
                    # Place new bet with updated odds
                    managed_event = self.managed_events[market.event_id]
                    await self._place_market_side_bet(side, managed_event, prophetx_event)
                
                market.last_updated = datetime.now(timezone.utc)
                market.update_count += 1
                self.total_updates_successful += 1
                
                print(f"✅ Updated moneyline market for {market.event_name}")
            
        except Exception as e:
            print(f"❌ Error updating moneyline market: {e}")
            self.total_updates_failed += 1
    
    async def _update_or_create_spreads_market(self, managed_event: ManagedEvent, spreads: ProcessedMarket, prophetx_event=None):
        """Update or create spreads market (placeholder)"""
        # Similar logic to moneyline but for spreads
        # Implementation would be similar but handle point spreads
        print(f"📊 Spreads market for {managed_event.display_name} - implementation pending")
        pass
    
    async def _update_or_create_totals_market(self, managed_event: ManagedEvent, totals: ProcessedMarket, prophetx_event=None):
        """Update or create totals market (placeholder)"""
        # Similar logic to moneyline but for totals
        # Implementation would be similar but handle over/under
        print(f"📊 Totals market for {managed_event.display_name} - implementation pending")
        pass
    
    async def _cleanup_expired_events(self):
        """Remove events that have started or are no longer relevant"""
        to_remove = []
        
        for event_id, managed_event in self.managed_events.items():
            if managed_event.starts_in_hours <= 0:  # Event has started
                print(f"🏁 Removing expired event: {managed_event.display_name}")
                to_remove.append(event_id)
        
        for event_id in to_remove:
            del self.managed_events[event_id]
    
    async def _check_risk_limits(self):
        """Check if we're approaching or exceeding risk limits"""
        # Calculate total exposure
        total_exposure = sum(event.total_exposure for event in self.managed_events.values())
        self.total_exposure = total_exposure
        
        if total_exposure > self.max_exposure_reached:
            self.max_exposure_reached = total_exposure
        
        # Check limits
        if total_exposure > self.settings.max_exposure_total * 0.8:
            print(f"⚠️  WARNING: Total exposure ${total_exposure:,.2f} approaching limit ${self.settings.max_exposure_total:,.2f}")
        
        if total_exposure > self.settings.max_exposure_total:
            print(f"🚨 RISK LIMIT EXCEEDED: Total exposure ${total_exposure:,.2f} exceeds ${self.settings.max_exposure_total:,.2f}")
            # In a real implementation, we'd stop creating new markets or reduce position sizes
    
    async def get_system_stats(self) -> Dict[str, Any]:
        """Get comprehensive system statistics"""
        if not self.start_time:
            uptime_hours = 0
        else:
            uptime = datetime.now(timezone.utc) - self.start_time
            uptime_hours = uptime.total_seconds() / 3600
        
        # Count active bets
        active_bets = sum(1 for bet in self.all_bets.values() if bet.is_active)
        
        # Calculate utilization
        utilization = (len(self.managed_events) / self.settings.max_events_tracked) * 100
        
        return {
            "system_status": "running" if self.is_running else "stopped",
            "uptime_hours": uptime_hours,
            "events_managed": len(self.managed_events),
            "total_markets_created": self.total_markets_created,
            "total_bets": len(self.all_bets),
            "active_bets": active_bets,
            "total_exposure": self.total_exposure,
            "max_exposure_reached": self.max_exposure_reached,
            "updates_successful": self.total_updates_successful,
            "updates_failed": self.total_updates_failed,
            "success_rate": self.total_updates_successful / max(self.total_updates_successful + self.total_updates_failed, 1),
            "capacity_utilization": utilization,
            "odds_api_stats": odds_api_service.get_usage_stats()
        }
    
    async def get_portfolio_summary(self) -> PortfolioSummary:
        """Get current portfolio summary"""
        stats = await self.get_system_stats()
        
        # Calculate financial metrics
        total_liquidity = sum(
            side.liquidity_amount 
            for event in self.managed_events.values()
            for market in event.markets
            for side in market.sides
        )
        
        matched_stake = sum(bet.matched_stake for bet in self.all_bets.values())
        unmatched_stake = sum(bet.unmatched_stake for bet in self.all_bets.values())
        
        return PortfolioSummary(
            total_events=len(self.managed_events),
            active_markets=sum(len(event.markets) for event in self.managed_events.values()),
            total_bets=len(self.all_bets),
            active_bets=stats["active_bets"],
            total_exposure=self.total_exposure,
            total_liquidity_provided=total_liquidity,
            matched_stake=matched_stake,
            unmatched_stake=unmatched_stake,
            successful_market_updates=self.total_updates_successful,
            failed_market_updates=self.total_updates_failed,
            uptime_hours=stats["uptime_hours"],
            max_single_event_exposure=max([event.total_exposure for event in self.managed_events.values()], default=0),
            utilization_percentage=stats["capacity_utilization"]
        )
    
    async def shutdown(self):
        """Graceful shutdown"""
        await self.stop_market_making()
        print("🛑 Market maker service shutdown complete")

# Global market maker service instance
market_maker_service = MarketMakerService()