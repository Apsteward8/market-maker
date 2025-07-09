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
from app.services.bet_monitoring_service import bet_monitoring_service
from app.services.odds_change_handler import odds_change_handler
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
        """
        ENHANCED market making loop with real bet placement, monitoring, and updates
        
        This replaces the existing _market_making_loop method in MarketMakerService
        """
        from app.services.event_matching_service import event_matching_service
        from app.services.market_matching_service import market_matching_service
        from app.services.market_making_strategy import market_making_strategy
        from app.services.odds_api_service import odds_api_service
        
        # Import the new services
        from app.services.bet_monitoring_service import bet_monitoring_service
        from app.services.odds_change_handler import odds_change_handler
        
        print("🚀 Starting Enhanced Market Making Loop with Real Bet Placement")
        
        # Start bet monitoring in background
        monitoring_task = asyncio.create_task(bet_monitoring_service.start_monitoring())
        
        while self.is_running:
            try:
                cycle_start = datetime.now(timezone.utc)
                print(f"\n🔄 Market Making Cycle - {cycle_start.strftime('%H:%M:%S')}")
                
                # ===============================
                # STEP 1: GET LATEST ODDS
                # ===============================
                print("📊 Step 1: Fetching latest Pinnacle odds...")
                try:
                    latest_odds_events = await odds_api_service.get_events()
                    print(f"   ✅ Fetched {len(latest_odds_events)} events from Pinnacle")
                except Exception as e:
                    print(f"   ❌ Failed to fetch odds: {e}")
                    await asyncio.sleep(30)
                    continue
                
                if not latest_odds_events:
                    print("   ⚠️  No events available, waiting...")
                    await asyncio.sleep(60)
                    continue
                
                # ===============================
                # STEP 2: DETECT ODDS CHANGES
                # ===============================
                print("📈 Step 2: Detecting odds changes...")
                significant_changes = await odds_change_handler.process_odds_update(latest_odds_events)
                
                if significant_changes:
                    print(f"   📊 Detected {len(significant_changes)} significant odds changes")
                    # Bet cancellations and wait period clears happen automatically in odds_change_handler
                else:
                    print("   ✅ No significant odds changes detected")
                
                # ===============================
                # STEP 3: GET MATCHED EVENTS
                # ===============================
                print("🔗 Step 3: Getting matched events...")
                try:
                    matched_events = await event_matching_service.get_matched_events()
                    
                    if not matched_events:
                        print("   ⚠️  No matched events. Running event matching...")
                        odds_events_subset = latest_odds_events[:10]  # Process first 10 to avoid timeouts
                        matching_attempts = await event_matching_service.find_matches_for_events(odds_events_subset)
                        matched_events = [attempt.best_match for attempt in matching_attempts if attempt.best_match]
                    
                    print(f"   ✅ Found {len(matched_events)} matched events")
                    
                except Exception as e:
                    print(f"   ❌ Error in event matching: {e}")
                    await asyncio.sleep(30)
                    continue
                
                # ===============================
                # STEP 4: PROCESS EACH EVENT
                # ===============================
                print(f"🎯 Step 4: Processing {len(matched_events)} matched events...")
                
                events_processed = 0
                new_bets_placed = 0
                
                for event_match in matched_events:
                    try:
                        result = await self._process_single_event_complete(event_match, latest_odds_events)
                        
                        if result["processed"]:
                            events_processed += 1
                            new_bets_placed += result["new_bets_placed"]
                            
                    except Exception as e:
                        print(f"   ❌ Error processing event {event_match.odds_api_event.display_name}: {e}")
                        continue
                
                # ===============================
                # STEP 5: ADD INCREMENTAL LIQUIDITY
                # ===============================
                print("📈 Step 5: Adding incremental liquidity...")
                incremental_bets_added = await self._add_incremental_liquidity_to_existing_lines()
                
                if incremental_bets_added > 0:
                    print(f"   ✅ Added {incremental_bets_added} incremental bets")
                    new_bets_placed += incremental_bets_added
                
                # ===============================
                # STEP 6: CLEANUP AND RISK CHECK
                # ===============================
                print("🧹 Step 6: Cleanup and risk management...")
                await self._cleanup_expired_events()
                await self._check_risk_limits()
                
                # ===============================
                # CYCLE SUMMARY
                # ===============================
                cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
                
                print(f"\n✅ Cycle Complete:")
                print(f"   Duration: {cycle_duration:.1f}s")
                print(f"   Events processed: {events_processed}")
                print(f"   New bets placed: {new_bets_placed}")
                print(f"   Total active bets: {sum(1 for bet in self.all_bets.values() if bet.is_active)}")
                print(f"   Total exposure: ${self.total_exposure:.2f}")
                
                # ===============================
                # WAIT FOR NEXT CYCLE
                # ===============================
                wait_time = max(5, self.settings.odds_poll_interval_seconds - cycle_duration)
                print(f"⏱️  Waiting {wait_time:.0f}s until next cycle...")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                print(f"💥 Unexpected error in market making loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(30)  # Wait before retrying
        
        # Cleanup when loop ends
        bet_monitoring_service.stop_monitoring()
        await monitoring_task

    async def _process_single_event_complete(self, event_match, latest_odds_events):
        """
        Complete processing of a single event including bet placement
        ADD this method to MarketMakerService class
        """
        from app.services.market_matching_service import market_matching_service
        from app.services.market_making_strategy import market_making_strategy
        
        odds_event = event_match.odds_api_event
        prophetx_event = event_match.prophetx_event
        event_id = str(prophetx_event.event_id)
        
        print(f"   🎯 Processing: {odds_event.display_name}")
        
        # Get or create managed event
        if event_id not in self.managed_events:
            from app.models.market_models import ManagedEvent, MarketStatus
            managed_event = ManagedEvent(
                event_id=event_id,
                sport=prophetx_event.sport_name,
                home_team=prophetx_event.home_team,
                away_team=prophetx_event.away_team,
                commence_time=prophetx_event.commence_time,
                max_exposure=self.settings.max_exposure_per_event,
                status=MarketStatus.PENDING
            )
            self.managed_events[event_id] = managed_event
            print(f"      📝 Created managed event for {managed_event.display_name}")
        else:
            managed_event = self.managed_events[event_id]
        
        # Check if event is too close to start
        if managed_event.should_stop_making_markets:
            print(f"      ⏰ Event starting soon, stopping markets")
            managed_event.status = "closed"
            return {"processed": True, "new_bets_placed": 0}
        
        # Get current odds for this event from latest_odds_events
        current_odds_event = None
        for event in latest_odds_events:
            if event.event_id == odds_event.event_id:
                current_odds_event = event
                break
        
        if not current_odds_event:
            print(f"      ⚠️  No current odds found for event")
            return {"processed": False, "new_bets_placed": 0}
        
        # Run market matching
        try:
            market_match_result = await market_matching_service.match_event_markets(event_match)
            
            if not market_match_result.ready_for_trading:
                print(f"      ❌ Not ready for trading: {market_match_result.issues}")
                return {"processed": True, "new_bets_placed": 0}
            
        except Exception as e:
            print(f"      ❌ Market matching failed: {e}")
            return {"processed": False, "new_bets_placed": 0}
        
        # Create betting plan
        try:
            plan = market_making_strategy.create_market_making_plan(event_match, market_match_result)
            
            if not plan or not plan.is_profitable:
                print(f"      ❌ No profitable opportunities")
                return {"processed": True, "new_bets_placed": 0}
            
        except Exception as e:
            print(f"      ❌ Strategy creation failed: {e}")
            return {"processed": False, "new_bets_placed": 0}
        
        # Execute betting plan with duplicate prevention
        print(f"      💰 Executing {len(plan.betting_instructions)} betting instructions...")
        
        new_bets_placed = 0
        for instruction in plan.betting_instructions:
            try:
                # Get comprehensive betting summary for this line
                line_summary = self._get_line_betting_summary(instruction.line_id)
                
                print(f"         📊 Line {instruction.line_id[-8:]}: {line_summary['reason']}")
                
                if not line_summary["should_place_bet"]:
                    # Don't place bet - we already have coverage
                    if line_summary["active_count"] > 0:
                        print(f"         ✅ Active coverage: {instruction.selection_name} (${line_summary['unmatched_stake']:.2f} unmatched)")
                    else:
                        print(f"         ⏱️  Too recent: {instruction.selection_name} (last bet {line_summary['minutes_since_last']:.1f}min ago)")
                    continue
                
                # Check incremental betting rules
                current_position = self.position_tracker.get_current_position(instruction.line_id)
                
                if current_position == 0:
                    # First bet on this line
                    bet_amount = instruction.stake
                    bet_reason = "Initial bet"
                else:
                    # Check if we can add incremental liquidity
                    from app.services.market_making_strategy import market_making_strategy
                    bet_amount = market_making_strategy.betting_manager.get_next_increment(
                        instruction.line_id, current_position, instruction.max_position, instruction.increment_size
                    )
                    bet_reason = f"Incremental bet (position: ${current_position:.2f})"
                    
                    if bet_amount <= 0:
                        print(f"         ⏱️  Skipping {instruction.selection_name}: in wait period or at max position")
                        continue
                
                # Final safety check - don't place if we just placed recently
                if self._has_recent_bet_for_line(instruction.line_id, minutes=2):
                    print(f"         ⏸️  Skipping {instruction.selection_name}: recent bet detected (safety check)")
                    continue
                
                # Place the bet
                print(f"         🎯 Placing: {instruction.selection_name} {instruction.odds:+d} ${bet_amount:.2f}")
                success = await self._place_bet_with_retry(instruction, bet_amount, managed_event)
                
                if success:
                    new_bets_placed += 1
                    print(f"         ✅ Placed: {instruction.selection_name} {instruction.odds:+d} ${bet_amount:.2f} ({bet_reason})")
                else:
                    print(f"         ❌ Failed: {instruction.selection_name}")
                    
            except Exception as e:
                print(f"         ❌ Error processing bet for {instruction.selection_name}: {e}")
                continue
        
        if new_bets_placed == 0:
            print(f"      ✅ No new bets needed - all lines already have coverage")
        else:
            print(f"      🎉 Placed {new_bets_placed} new bets")
        
        # Update managed event status
        managed_event.status = "active"
        managed_event.last_odds_update = datetime.now(timezone.utc)
        
        return {"processed": True, "new_bets_placed": new_bets_placed}
    
    async def _place_bet_with_retry(self, instruction, bet_amount: float, managed_event, max_retries: int = 3):
        """
        Place bet with retry logic and proper error handling
        ADD this method to MarketMakerService class
        """
        from app.services.prophetx_service import prophetx_service
        from app.models.market_models import ProphetXBet, BetStatus
        
        for attempt in range(max_retries):
            try:
                external_id = f"{managed_event.event_id}_{instruction.line_id}_{int(time.time())}_{attempt}"
                
                # Place bet on ProphetX
                result = await prophetx_service.place_bet(
                    line_id=instruction.line_id,
                    odds=instruction.odds,
                    stake=bet_amount,
                    external_id=external_id
                )
                
                if result["success"]:
                    # Create bet tracking object
                    bet = ProphetXBet(
                        bet_id=result.get("bet_id"),
                        external_id=external_id,
                        line_id=instruction.line_id,
                        selection_name=instruction.selection_name,
                        odds=instruction.odds,
                        stake=bet_amount,
                        status=BetStatus.PLACED,
                        unmatched_stake=bet_amount,
                        placed_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    
                    # Store bet and update tracking
                    self.all_bets[external_id] = bet
                    self.position_tracker.record_new_bet(instruction.line_id, bet_amount, external_id)
                    
                    return True
                    
                else:
                    print(f"            ⚠️  Attempt {attempt + 1} failed: {result.get('error', 'Unknown error')}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
            except Exception as e:
                print(f"            ❌ Attempt {attempt + 1} exception: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        return False

    async def _add_incremental_liquidity_to_existing_lines(self):
        """
        Add incremental liquidity to lines that can accept more (not in wait period)
        ADD this method to MarketMakerService class
        """
        from app.services.market_making_strategy import market_making_strategy
        
        incremental_bets_added = 0
        
        for line_id, position_info in self.position_tracker.line_positions.items():
            try:
                # Check if this line can accept more liquidity
                if not market_making_strategy.betting_manager.can_add_liquidity(line_id):
                    continue  # Still in wait period
                
                # Find the original betting instruction for this line
                # This is simplified - you might want to store instructions with positions
                original_instruction = self._find_instruction_for_line(line_id)
                if not original_instruction:
                    continue
                
                # Calculate increment amount
                current_position = position_info['total_stake']
                increment_amount = market_making_strategy.betting_manager.get_next_increment(
                    line_id, current_position, original_instruction.max_position, original_instruction.increment_size
                )
                
                if increment_amount > 0:
                    # Find the managed event for this line
                    managed_event = self._find_managed_event_for_line(line_id)
                    if not managed_event:
                        continue
                    
                    # Place incremental bet
                    success = await self._place_bet_with_retry(original_instruction, increment_amount, managed_event)
                    
                    if success:
                        incremental_bets_added += 1
                        print(f"      📈 Added ${increment_amount:.2f} to {original_instruction.selection_name}")
                    
            except Exception as e:
                print(f"      ❌ Error adding incremental liquidity to {line_id}: {e}")
                continue
        
        return incremental_bets_added

    def _find_instruction_for_line(self, line_id: str):
        """
        Helper method to find original betting instruction for a line
        ADD this method to MarketMakerService class
        
        This is a simplified version - you might want to store this information better
        """
        # For now, we'll return a mock instruction
        # In a real implementation, you'd store the instructions with the positions
        return None  # This needs proper implementation

    def _find_managed_event_for_line(self, line_id: str):
        """
        Helper method to find managed event that contains a specific line
        ADD this method to MarketMakerService class
        """
        # For now, we'll return the first managed event
        # In a real implementation, you'd map line_ids to events properly
        if self.managed_events:
            return next(iter(self.managed_events.values()))
        return None
    
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
        """Place a bet for a specific line with incremental tracking - ENHANCED VERSION"""
        try:
            if not self.settings.dry_run_mode:
                from app.services.prophetx_service import prophetx_service
                
                external_id = f"{managed_event.event_id}_{instruction.line_id}_{int(time.time())}"
                
                # ACTUALLY place the bet on ProphetX (not dry run anymore!)
                result = await prophetx_service.place_bet(
                    line_id=instruction.line_id,
                    odds=instruction.odds,
                    stake=bet_amount,
                    external_id=external_id
                )
                
                if result["success"]:
                    # Create bet tracking object
                    bet = ProphetXBet(
                        bet_id=result.get("bet_id"),
                        external_id=external_id,
                        line_id=instruction.line_id,
                        selection_name=instruction.selection_name,
                        odds=instruction.odds,
                        stake=bet_amount,
                        status=BetStatus.PLACED,  # Real bet placed
                        unmatched_stake=bet_amount,
                        placed_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    
                    # Store bet and update tracking
                    self.all_bets[external_id] = bet
                    self.position_tracker.record_new_bet(instruction.line_id, bet_amount, external_id)
                    
                    print(f"💰 ✅ REAL BET PLACED: {instruction.selection_name} {instruction.odds:+d} for ${bet_amount:.2f}")
                    return True
                else:
                    print(f"❌ Real bet placement failed: {result.get('error')}")
                    return False
            else:
                # DRY RUN mode (your existing logic)
                external_id = f"{managed_event.event_id}_{instruction.line_id}_{int(time.time())}"
                
                bet = ProphetXBet(
                    external_id=external_id,
                    line_id=instruction.line_id,
                    selection_name=instruction.selection_name,
                    odds=instruction.odds,
                    stake=bet_amount,
                    status=BetStatus.PENDING,  # Simulated
                    unmatched_stake=bet_amount,
                    placed_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                
                # Store bet and update tracking
                self.all_bets[external_id] = bet
                self.position_tracker.record_new_bet(instruction.line_id, bet_amount, external_id)
                
                mode_indicator = '[DRY RUN] '
                print(f"💰 {mode_indicator}Bet placed: {instruction.selection_name} {instruction.odds:+d} for ${bet_amount:.2f}")
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

    def _has_active_bet_for_line(self, line_id: str) -> bool:
        """
        Check if we already have an active bet for a specific line
        
        Args:
            line_id: ProphetX line ID to check
            
        Returns:
            True if we have an active bet for this line
        """
        for bet in self.all_bets.values():
            if bet.line_id == line_id and bet.is_active:
                return True
        return False

    def _get_active_bet_for_line(self, line_id: str) -> Optional[ProphetXBet]:
        """
        Get the active bet for a specific line
        
        Args:
            line_id: ProphetX line ID
            
        Returns:
            Active ProphetXBet object or None
        """
        for bet in self.all_bets.values():
            if bet.line_id == line_id and bet.is_active:
                return bet
        return None
    
    def _has_recent_bet_for_line(self, line_id: str, minutes: int = 2) -> bool:
        """
        Check if we placed a bet for this line recently (within X minutes)
        This prevents duplicate bets even if monitoring is delayed
        
        Args:
            line_id: ProphetX line ID to check
            minutes: How recent to check (default 2 minutes)
            
        Returns:
            True if we have a recent bet for this line
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        
        for bet in self.all_bets.values():
            if (bet.line_id == line_id and 
                bet.placed_at >= cutoff_time and
                bet.status not in ["cancelled", "expired", "rejected"]):
                return True
        return False

    def _get_line_betting_summary(self, line_id: str) -> Dict[str, Any]:
        """
        Get comprehensive summary of our betting activity for a line
        
        Args:
            line_id: ProphetX line ID
            
        Returns:
            Summary dictionary with betting stats
        """
        line_bets = [bet for bet in self.all_bets.values() if bet.line_id == line_id]
        
        if not line_bets:
            return {
                "has_bets": False,
                "active_count": 0,
                "total_stake": 0.0,
                "unmatched_stake": 0.0,
                "latest_bet_time": None,
                "should_place_bet": True,
                "reason": "No existing bets for this line"
            }
        
        # Sort by placement time
        line_bets.sort(key=lambda x: x.placed_at, reverse=True)
        latest_bet = line_bets[0]
        
        # Count active bets
        active_bets = [bet for bet in line_bets if bet.is_active]
        total_stake = sum(bet.stake for bet in line_bets)
        total_unmatched = sum(bet.unmatched_stake for bet in active_bets)
        
        # Check if we should place a new bet
        should_place = True
        reason = "Ready to place bet"
        
        # Don't place if we have active bets
        if active_bets:
            should_place = False
            reason = f"Already have {len(active_bets)} active bet(s)"
        
        # Don't place if we placed a bet very recently (even if not showing as active yet)
        minutes_since_last = (datetime.now(timezone.utc) - latest_bet.placed_at).total_seconds() / 60
        if minutes_since_last < 2:  # Within last 2 minutes
            should_place = False
            reason = f"Bet placed {minutes_since_last:.1f} minutes ago - too recent"
        
        return {
            "has_bets": True,
            "active_count": len(active_bets),
            "total_bets": len(line_bets),
            "total_stake": total_stake,
            "unmatched_stake": total_unmatched,
            "latest_bet_time": latest_bet.placed_at,
            "minutes_since_last": minutes_since_last,
            "should_place_bet": should_place,
            "reason": reason,
            "latest_odds": latest_bet.odds if latest_bet else None
        }
    
    async def shutdown(self):
        """Graceful shutdown"""
        await self.stop_market_making()
        print("🛑 Market maker service shutdown complete")

# Global market maker service instance
market_maker_service = MarketMakerService()

# Import after class definition to avoid circular imports
from app.services.market_making_strategy import market_making_strategy