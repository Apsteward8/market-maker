#!/usr/bin/env python3
"""
Market Maker Service - UPDATED
Core market making logic with incremental betting, exact Pinnacle replication, and fill management
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
# Import BettingInstruction at the end to avoid circular imports

class PositionTracker:
    """Tracks current positions and fills for each line"""
    
    def __init__(self):
        self.line_positions: Dict[str, Dict] = {}  # line_id -> position info
        
    def get_current_position(self, line_id: str) -> float:
        """Get current total position size for a line"""
        return self.line_positions.get(line_id, {}).get('total_stake', 0.0)
        
    def record_new_bet(self, line_id: str, stake: float, bet_id: str):
        """Record a new bet placement"""
        if line_id not in self.line_positions:
            self.line_positions[line_id] = {
                'total_stake': 0.0,
                'bets': [],
                'last_updated': time.time()
            }
        
        self.line_positions[line_id]['total_stake'] += stake
        self.line_positions[line_id]['bets'].append({
            'bet_id': bet_id,
            'stake': stake,
            'placed_at': time.time(),
            'status': 'placed'
        })
        self.line_positions[line_id]['last_updated'] = time.time()
        
    def record_fill(self, line_id: str, bet_id: str, filled_amount: float):
        """Record when a bet gets filled/matched"""
        if line_id in self.line_positions:
            for bet in self.line_positions[line_id]['bets']:
                if bet['bet_id'] == bet_id:
                    bet['status'] = 'filled'
                    bet['filled_amount'] = filled_amount
                    bet['filled_at'] = time.time()
                    
                    # Notify the betting manager about the fill
                    market_making_strategy.betting_manager.record_fill(
                        line_id, filled_amount, self.get_current_position(line_id)
                    )
                    break

class MarketMakerService:
    """Core service for making markets on ProphetX with incremental betting"""
    
    def __init__(self):
        self.settings = get_settings()
        
        # Portfolio tracking
        self.managed_events: Dict[str, ManagedEvent] = {}
        self.all_bets: Dict[str, ProphetXBet] = {}  # external_id -> bet
        
        # Position and fill tracking
        self.position_tracker = PositionTracker()
        
        # System state
        self.is_running = False
        self.start_time = None
        self.total_markets_created = 0
        self.total_updates_successful = 0
        self.total_updates_failed = 0
        
        # Risk tracking
        self.total_exposure = 0.0
        self.max_exposure_reached = 0.0
        
        # Odds tracking for change detection
        self.last_odds_cache: Dict[str, Dict] = {}  # event_id -> market data
        
    async def start_market_making(self) -> Dict[str, Any]:
        """Start the market making system"""
        if self.is_running:
            return {"success": False, "message": "Market making is already running"}
        
        print("🚀 Starting ProphetX Market Making System - EXACT PINNACLE REPLICATION")
        print(f"   Strategy: Copy Pinnacle odds exactly (no improvement)")
        print(f"   Increments: ${market_making_strategy.base_plus_bet} plus side, arbitrage amounts minus side")
        print(f"   Max position: ${market_making_strategy.max_plus_bet} plus side")
        print(f"   Fill wait period: {market_making_strategy.betting_manager.fill_wait_period}s")
        
        self.is_running = True
        self.start_time = datetime.now(timezone.utc)
        
        # Start main market making loop
        if self.settings.auto_start_polling:
            asyncio.create_task(self._market_making_loop())
        
        return {
            "success": True,
            "message": "Market making system started with exact Pinnacle replication",
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
        """Main market making loop with continuous odds monitoring"""
        while self.is_running:
            try:
                print(f"🔄 Market making cycle starting...")
                
                # 1. Get matched events (events that exist on both platforms)
                from app.services.event_matching_service import event_matching_service
                from app.services.market_matching_service import market_matching_service
                
                matched_events = await event_matching_service.get_matched_events()
                
                if not matched_events:
                    print("⚠️  No matched events found. Run event matching first.")
                    await asyncio.sleep(30)
                    continue
                
                print(f"📊 Found {len(matched_events)} matched events to manage")
                
                # 2. Process each matched event
                for event_match in matched_events:
                    await self._manage_matched_event_with_incremental_betting(event_match)
                
                # 3. Check for and add incremental liquidity where appropriate
                await self._add_incremental_liquidity()
                
                # 4. Clean up expired events
                await self._cleanup_expired_events()
                
                # 5. Check risk limits
                await self._check_risk_limits()
                
                print(f"✅ Market making cycle complete. Managing {len(self.managed_events)} events.")
                
                # Wait before next cycle (60 seconds for odds updates)
                await asyncio.sleep(self.settings.odds_poll_interval_seconds)
                
            except Exception as e:
                print(f"💥 Error in market making loop: {e}")
                await asyncio.sleep(30)  # Wait before retrying
    
    async def _manage_matched_event_with_incremental_betting(self, event_match):
        """
        Manage markets for a matched event with incremental betting strategy
        """
        odds_event = event_match.odds_api_event
        prophetx_event = event_match.prophetx_event
        
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
        
        # Check if Pinnacle odds have changed significantly
        odds_changed = await self._check_odds_changes(event_id, odds_event)
        
        # Get market matching results
        from app.services.market_matching_service import market_matching_service
        market_match_result = await market_matching_service.match_event_markets(event_match)
        
        if not market_match_result.ready_for_trading:
            print(f"⚠️  Event {managed_event.display_name} not ready for trading")
            return
        
        # Create or update market making plan
        plan = market_making_strategy.create_market_making_plan(event_match, market_match_result)
        
        if not plan or not plan.is_profitable:
            print(f"❌ No profitable opportunities for {managed_event.display_name}")
            return
        
        # Execute betting plan with incremental strategy
        await self._execute_betting_plan(managed_event, plan, odds_changed)
        
        # Update tracking
        managed_event.last_odds_update = datetime.now(timezone.utc)
        managed_event.status = MarketStatus.ACTIVE
    
    async def _check_odds_changes(self, event_id: str, odds_event: ProcessedEvent) -> bool:
        """Check if Pinnacle odds have changed significantly since last update"""
        current_odds = self._extract_odds_signature(odds_event)
        
        if event_id not in self.last_odds_cache:
            self.last_odds_cache[event_id] = current_odds
            return True  # First time seeing this event
        
        last_odds = self.last_odds_cache[event_id]
        
        # Compare odds for significant changes
        odds_changed = False
        for market_type, outcomes in current_odds.items():
            if market_type not in last_odds:
                odds_changed = True
                break
            
            for outcome_name, odds in outcomes.items():
                if outcome_name not in last_odds[market_type]:
                    odds_changed = True
                    break
                
                # Check for odds movement
                if abs(odds - last_odds[market_type][outcome_name]) >= 5:  # 5 point movement
                    print(f"📊 Odds change detected: {outcome_name} {last_odds[market_type][outcome_name]:+d} → {odds:+d}")
                    odds_changed = True
                    break
        
        if odds_changed:
            self.last_odds_cache[event_id] = current_odds
            
            # Clear wait periods for lines with significant odds changes
            # This allows immediate liquidity updates when market moves
            print("⚡ Odds changed significantly - clearing wait periods for affected lines")
        
        return odds_changed
    
    def _extract_odds_signature(self, odds_event: ProcessedEvent) -> Dict[str, Dict[str, int]]:
        """Extract odds signature for change detection"""
        signature = {}
        
        if odds_event.moneyline:
            signature['moneyline'] = {
                outcome.name: outcome.american_odds 
                for outcome in odds_event.moneyline.outcomes
            }
        
        if odds_event.spreads:
            signature['spreads'] = {
                f"{outcome.name}_{outcome.point}": outcome.american_odds 
                for outcome in odds_event.spreads.outcomes
            }
        
        if odds_event.totals:
            signature['totals'] = {
                f"{outcome.name}_{outcome.point}": outcome.american_odds 
                for outcome in odds_event.totals.outcomes
            }
        
        return signature
    
    async def _execute_betting_plan(self, managed_event: ManagedEvent, plan, odds_changed: bool):
        """
        Execute betting plan with incremental strategy
        
        Args:
            managed_event: Event being managed
            plan: MarketMakingPlan with betting instructions
            odds_changed: Whether Pinnacle odds changed significantly
        """
        for instruction in plan.betting_instructions:
            line_id = instruction.line_id
            current_position = self.position_tracker.get_current_position(line_id)
            
            # Determine how much to bet
            if current_position == 0:
                # First bet on this line
                bet_amount = instruction.stake
                print(f"🎯 Initial bet: {instruction.selection_name} {instruction.odds:+d} for ${bet_amount:.2f}")
                
            elif odds_changed:
                # Odds changed - cancel existing bets and place new ones at updated odds
                await self._cancel_line_bets(line_id)
                bet_amount = instruction.stake
                print(f"🔄 Odds update bet: {instruction.selection_name} {instruction.odds:+d} for ${bet_amount:.2f}")
                
            else:
                # Check if we can add incremental liquidity
                from app.services.market_making_strategy import market_making_strategy
                bet_amount = market_making_strategy.betting_manager.get_next_increment(
                    line_id, current_position, instruction.max_position, instruction.increment_size
                )
                
                if bet_amount > 0:
                    print(f"📈 Incremental bet: {instruction.selection_name} {instruction.odds:+d} for ${bet_amount:.2f} (total: ${current_position + bet_amount:.2f})")
                else:
                    continue  # No liquidity to add
            
            # Place the bet
            success = await self._place_line_bet(instruction, bet_amount, managed_event)
            
            if success:
                self.total_updates_successful += 1
            else:
                self.total_updates_failed += 1
    
    async def _place_line_bet(self, instruction, bet_amount: float, managed_event: ManagedEvent) -> bool:
        """Place a bet for a specific line with incremental tracking"""
        try:
            if not self.settings.dry_run_mode:
                print(f"🚨 LIVE MODE: Would place real bet here!")
                # In live mode, we'd actually place the bet on ProphetX
            
            # Create bet
            external_id = f"{managed_event.event_id}_{instruction.line_id}_{int(time.time())}"
            
            bet = ProphetXBet(
                external_id=external_id,
                line_id=instruction.line_id,
                selection_name=instruction.selection_name,
                odds=instruction.odds,
                stake=bet_amount,
                status=BetStatus.PLACED if not self.settings.dry_run_mode else BetStatus.PENDING,
                unmatched_stake=bet_amount,
                placed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            # Store bet and update tracking
            self.all_bets[external_id] = bet
            self.position_tracker.record_new_bet(instruction.line_id, bet_amount, external_id)
            
            mode_indicator = '[DRY RUN] ' if self.settings.dry_run_mode else ''
            print(f"💰 {mode_indicator}Bet placed: {instruction.selection_name} {instruction.odds:+d} for ${bet_amount:.2f} (offers {instruction.outcome_offered_to_users})")
            
            return True
            
        except Exception as e:
            print(f"❌ Error placing bet for {instruction.selection_name}: {e}")
            return False
    
    async def _cancel_line_bets(self, line_id: str):
        """Cancel all active bets for a specific line (when odds change)"""
        cancelled_count = 0
        
        for bet in self.all_bets.values():
            if bet.line_id == line_id and bet.is_active:
                bet.status = BetStatus.CANCELLED
                bet.unmatched_stake = 0.0
                cancelled_count += 1
        
        if cancelled_count > 0:
            print(f"❌ Cancelled {cancelled_count} bets for line {line_id} due to odds change")
            
            # Clear wait period for this line
            from app.services.market_making_strategy import market_making_strategy
            market_making_strategy.betting_manager.clear_wait_period(line_id)
    
    async def _add_incremental_liquidity(self):
        """Check all lines and add incremental liquidity where appropriate"""
        for line_id, position_info in self.position_tracker.line_positions.items():
            # This is handled in the main loop for each event
            # Could add additional logic here for standalone liquidity additions
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
            # Clean up odds cache
            if event_id in self.last_odds_cache:
                del self.last_odds_cache[event_id]
    
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
    
    # Simulation of bet fills (in real implementation, this would be triggered by ProphetX API)
    async def simulate_bet_fill(self, bet_id: str, filled_amount: float):
        """Simulate a bet getting filled - for testing purposes"""
        if bet_id in self.all_bets:
            bet = self.all_bets[bet_id]
            bet.status = BetStatus.MATCHED
            bet.matched_stake = filled_amount
            bet.unmatched_stake = bet.stake - filled_amount
            
            # Record the fill in position tracker
            self.position_tracker.record_fill(bet.line_id, bet_id, filled_amount)
            
            print(f"✅ Simulated fill: {bet.selection_name} ${filled_amount:.2f} matched")
            
            return True
        return False
    
    async def get_system_stats(self) -> Dict[str, Any]:
        """Get comprehensive system statistics with incremental betting info"""
        if not self.start_time:
            uptime_hours = 0
        else:
            uptime = datetime.now(timezone.utc) - self.start_time
            uptime_hours = uptime.total_seconds() / 3600
        
        # Count active bets
        active_bets = sum(1 for bet in self.all_bets.values() if bet.is_active)
        
        # Calculate utilization
        utilization = (len(self.managed_events) / self.settings.max_events_tracked) * 100
        
        # Count lines with wait periods
        from app.services.market_making_strategy import market_making_strategy
        lines_in_wait = sum(1 for line_id in market_making_strategy.betting_manager.last_fill_time.keys()
                           if not market_making_strategy.betting_manager.can_add_liquidity(line_id))
        
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
            "incremental_betting": {
                "lines_with_positions": len(self.position_tracker.line_positions),
                "lines_in_wait_period": lines_in_wait,
                "fill_wait_period_seconds": market_making_strategy.betting_manager.fill_wait_period
            },
            "odds_api_stats": odds_api_service.get_usage_stats()
        }
    
    async def get_portfolio_summary(self) -> PortfolioSummary:
        """Get current portfolio summary with incremental betting details"""
        stats = await self.get_system_stats()
        
        # Calculate financial metrics including incremental positions
        total_liquidity = 0.0
        for line_id, position_info in self.position_tracker.line_positions.items():
            total_liquidity += position_info['total_stake']
        
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

# Import after class definition to avoid circular imports
from app.services.market_making_strategy import market_making_strategy