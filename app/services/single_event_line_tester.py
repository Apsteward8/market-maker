"""
Single Event Line Monitoring Tester

This service allows testing the complete line monitoring workflow on just one event,
making it much easier to debug and understand what's happening.

Perfect for debugging the workflow without the complexity of multiple events.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class SingleEventSession:
    """Tracks a single event testing session"""
    odds_api_event_id: str
    event_name: str
    start_time: datetime
    is_active: bool
    lines_identified: Dict[str, Any]  # line_id -> strategy info
    monitoring_cycles: int
    total_bets_placed: int
    total_fills_detected: int
    last_cycle_time: Optional[datetime]

@dataclass
class LineMetadata:
    """Metadata for each monitored line including ProphetX IDs"""
    line_id: str
    prophetx_event_id: Optional[int]
    prophetx_market_id: Optional[int]  # Make sure this stays as int
    market_type: Optional[str]
    selection_name: str
    last_updated: datetime

class SingleEventLineTester:
    """Test line monitoring workflow on a single event"""
    
    def __init__(self):
        self.session: Optional[SingleEventSession] = None
        self.monitoring_active = False
        self.monitored_lines: Dict[str, Any] = {}  # line_id -> strategy info
        self.initial_phase_complete = False
        self.line_metadata: Dict[str, LineMetadata] = {}
        
        # Services (will be injected)
        self.line_position_service = None
        self.prophetx_wager_service = None
        self.market_making_strategy = None

        self.original_pinnacle_odds = {}  # Store original odds for comparison
        self.last_odds_check_time = None
        self.odds_changes_detected = 0
        
        # Settings
        self.monitoring_interval_seconds = 60  # Check every 30 seconds for testing
        self.fill_wait_period_seconds = 300   # 5 minutes
    
    def initialize_services(self, line_position_service, prophetx_wager_service, market_making_strategy):
        """Initialize required services"""
        self.line_position_service = line_position_service
        self.prophetx_wager_service = prophetx_wager_service
        self.market_making_strategy = market_making_strategy
    
    async def start_single_event_test(self, odds_api_event_id: str) -> Dict[str, Any]:
        """
        Start testing the complete workflow on a single event
        
        Args:
            odds_api_event_id: Event ID from The Odds API to test
            
        Returns:
            Result of starting the test
        """
        if self.monitoring_active:
            return {
                "success": False,
                "message": "Single event test already active - stop current test first"
            }
        
        try:
            print(f"🎯 STARTING SINGLE EVENT LINE MONITORING TEST")
            print(f"Event ID: {odds_api_event_id}")
            print("=" * 60)
            
            # Step 1: Get the specific event from Odds API
            from app.services.odds_api_service import odds_api_service
            
            print("📊 Fetching specific event from Odds API...")
            odds_api_events = await odds_api_service.get_events()
            
            target_event = None
            for event in odds_api_events:
                if event.event_id == odds_api_event_id:
                    target_event = event
                    break
            
            if not target_event:
                return {
                    "success": False,
                    "message": f"Event {odds_api_event_id} not found in Odds API"
                }
            
            print(f"✅ Found event: {target_event.away_team} vs {target_event.home_team}")
            self._store_original_pinnacle_odds(target_event)
            
            # Step 2: Match to ProphetX
            from app.services.event_matching_service import event_matching_service
            
            print("🔗 Matching to ProphetX...")
            matching_attempts = await event_matching_service.find_matches_for_events([target_event])
            
            if not matching_attempts or not matching_attempts[0].best_match:
                matching_attempt = matching_attempts[0] if matching_attempts else None
                no_match_reason = matching_attempt.no_match_reason if matching_attempt else "No matching attempt returned"
                
                return {
                    "success": False,
                    "message": f"Could not match event to ProphetX: {no_match_reason}"
                }
            
            event_match = matching_attempts[0].best_match
            print(f"✅ Matched to ProphetX: {event_match.prophetx_event.display_name} (confidence: {event_match.confidence_score:.2f})")
            
            # Step 3: Match markets
            from app.services.market_matching_service import market_matching_service
            
            print("📊 Matching markets...")
            market_matches = await market_matching_service.match_event_markets(event_match)
            
            if not market_matches.ready_for_trading:
                return {
                    "success": False,
                    "message": f"Markets not ready: {market_matches.issues}"
                }
            
            print(f"✅ Matched {len(market_matches.market_matches)} markets")
            
            # Step 4: Create strategy
            print("💰 Creating strategy...")
            strategy = self.market_making_strategy.create_market_making_plan(event_match, market_matches)
            
            if not strategy or not strategy.is_profitable:
                return {
                    "success": False,
                    "message": f"Strategy not profitable for this event"
                }
            
            print(f"✅ Strategy created: {len(strategy.betting_instructions)} betting instructions")
            
            # Step 5: Store lines to monitor
            self.monitored_lines = {}
            self.line_metadata = {}  # Clear previous metadata
            
            for instruction in strategy.betting_instructions:
                line_id = instruction.line_id
                
                self.monitored_lines[line_id] = {
                    "line_id": line_id,
                    "selection_name": instruction.selection_name,
                    "odds": instruction.odds,
                    "recommended_initial_stake": instruction.stake,
                    "max_position": instruction.max_position,
                    "increment_size": instruction.increment_size,
                    "event_id": str(event_match.prophetx_event.event_id),
                    "market_type": "h2h"  # fallback
                }
                
                # ✅ NEW: Store metadata with improved extraction
                await self._fetch_and_store_line_metadata_improved(
                    line_id=line_id,
                    prophetx_event_id=event_match.prophetx_event.event_id,
                    market_matches=market_matches,  # Pass the full market_matches object
                    selection_name=instruction.selection_name
                )
        
            
            print(f"📋 Lines to monitor: {len(self.monitored_lines)}")
            for line_id, info in self.monitored_lines.items():
                print(f"   📊 {info['selection_name']}: {info['odds']:+d} - ${info['recommended_initial_stake']:.2f} initial, ${info['max_position']:.2f} max")
            
            # Step 6: Create session
            self.session = SingleEventSession(
                odds_api_event_id=odds_api_event_id,
                event_name=f"{target_event.away_team} vs {target_event.home_team}",
                start_time=datetime.now(timezone.utc),
                is_active=True,
                lines_identified=self.monitored_lines.copy(),
                monitoring_cycles=0,
                total_bets_placed=0,
                total_fills_detected=0,
                last_cycle_time=None
            )
            
            print(f"✅ Created test session for: {self.session.event_name}")
            
            # Step 7: INITIAL PHASE - Place initial bets only
            print("\\n🚀 PHASE 1: INITIAL BET PLACEMENT")
            print("=" * 40)
            initial_bets = await self._initial_bet_phase()
            
            # Step 8: MONITORING PHASE - Start monitoring loop  
            print("\\n📊 PHASE 2: MONITORING AND INCREMENTAL BETTING")
            print("=" * 40)
            self.initial_phase_complete = True
            self.monitoring_active = True
            
            # Start monitoring loop
            asyncio.create_task(self._monitoring_loop())
            
            return {
                "success": True,
                "message": f"Single event test started with {initial_bets} initial bets",
                "data": {
                    "event_id": odds_api_event_id,
                    "event_name": self.session.event_name,
                    "lines_identified": len(self.monitored_lines),
                    "initial_bets_placed": initial_bets,
                    "monitoring_started": True,
                    "lines_detail": [
                        {
                            "line_id": line_info["line_id"],
                            "selection_name": line_info["selection_name"],
                            "odds": line_info["odds"],
                            "initial_stake": line_info["recommended_initial_stake"],
                            "max_position": line_info["max_position"]
                        }
                        for line_info in self.monitored_lines.values()
                    ],
                    "monitoring_interval": self.monitoring_interval_seconds,
                    "started_at": self.session.start_time.isoformat()
                }
            }
            
        except Exception as e:
            print(f"❌ Error starting single event test: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"Error starting test: {str(e)}"
            }
    
    async def stop_single_event_test(self) -> Dict[str, Any]:
        """Stop the single event test"""
        if not self.monitoring_active:
            return {
                "success": False,
                "message": "No single event test is currently active"
            }
        
        self.monitoring_active = False
        
        if self.session:
            self.session.is_active = False
            
            return {
                "success": True,
                "message": f"Single event test stopped: {self.session.event_name}",
                "data": {
                    "session_duration": (datetime.now(timezone.utc) - self.session.start_time).total_seconds(),
                    "monitoring_cycles": self.session.monitoring_cycles,
                    "total_bets_placed": self.session.total_bets_placed,
                    "total_fills_detected": self.session.total_fills_detected
                }
            }
        else:
            return {
                "success": True,
                "message": "Single event test stopped"
            }
        
    async def _monitoring_loop(self):
        """
        PHASE 2: Monitoring loop for fills and incremental betting
        
        This runs every 60 seconds and ONLY places incremental bets after fills + wait periods.
        """
        cycle_count = 0
        
        while self.monitoring_active:
            try:
                cycle_count += 1
                cycle_start = time.time()
                
                print(f"\\n🔄 MONITORING CYCLE #{cycle_count} ({datetime.now().strftime('%H:%M:%S')})")
                print("=" * 50)
                
                # Step 1: Check current positions
                await self._check_current_positions()
                
                # Step 2: Check for fills and place incremental bets if needed
                new_bets = await self._check_fills_and_place_incremental_bets()

                # Step 3: **NEW** - Monitor Pinnacle for odds changes
                await self._monitor_pinnacle_odds_changes()

                # Step 4: Update session stats
                if hasattr(self, 'session') and self.session:
                    self.session.monitoring_cycles += 1
                    if new_bets > 0:
                        self.session.total_bets_placed += new_bets
                
                cycle_duration = time.time() - cycle_start
                print(f"\\n📈 CYCLE #{cycle_count} COMPLETE")
                print(f"   Duration: {cycle_duration:.1f}s")
                print(f"   New incremental bets: {new_bets}")
                print(f"   Next cycle in: {self.monitoring_interval_seconds}s")
                
                # Wait before next cycle
                await asyncio.sleep(self.monitoring_interval_seconds)
                
            except Exception as e:
                print(f"❌ Error in monitoring cycle: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(30)

    async def _check_fills_and_place_incremental_bets(self) -> int:
        """
        ENHANCED: Check for fills and manage liquidity restoration
        
        Now only counts SYSTEM BETS for position calculations.
        Manual UI bets are completely ignored.
        """
        print("\\n2️⃣ LIQUIDITY MANAGEMENT AND FILL MONITORING")
        print("📊 Only counting system bets (non-empty external_id)")
        print("-" * 50)
        
        incremental_bets = 0
        
        for line_id, strategy_info in self.monitored_lines.items():
            try:
                # Get current position (system bets only)
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(
                    line_id,
                    system_bets_only=True,
                    external_id_filter="single_test_"  # Filter for our system's bets
                )
                
                if not position_result["success"]:
                    print(f"   ❌ Could not get position for {strategy_info['selection_name']}")
                    continue
                
                summary = position_result["position_summary"]
                total_stake = summary.get("total_stake", 0)
                total_matched = summary.get("total_matched", 0)
                current_unmatched = total_stake - total_matched
                last_fill_time = summary.get("last_fill_time")
                recent_fills = summary.get("recent_fills", [])
                system_bets = summary.get("system_bets", 0)
                manual_bets = summary.get("manual_bets", 0)
                
                recommended_initial = strategy_info["recommended_initial_stake"]
                max_position = strategy_info["max_position"]
                
                print(f"\\n📊 {strategy_info['selection_name'][:30]:<30}")
                
                if manual_bets > 0:
                    print(f"   📝 Found {manual_bets} manual UI bets (ignored in system calculations)")
                
                # Handle case where no SYSTEM wagers exist yet
                if system_bets == 0:
                    print(f"   ⚠️  No system wagers found - this should have been handled in initial phase")
                    print(f"   ✅ Placing initial ${recommended_initial:.2f} bet")
                    
                    success = await self._place_single_bet(
                        strategy_info, 
                        recommended_initial, 
                        "Late initial bet (missed in initial phase)"
                    )
                    
                    if success:
                        incremental_bets += 1
                    continue
                
                print(f"   📈 System position: ${total_stake:.2f} total, ${total_matched:.2f} matched, ${current_unmatched:.2f} unmatched")
                print(f"   🎯 Target: ${recommended_initial:.2f} unmatched, max: ${max_position:.2f} total")
                print(f"   📊 System fills: {len(recent_fills)}")
                
                # Calculate liquidity shortfall
                liquidity_shortfall = max(0, recommended_initial - current_unmatched)
                
                if liquidity_shortfall == 0:
                    print(f"   ✅ Liquidity adequate (${current_unmatched:.2f} >= ${recommended_initial:.2f})")
                    continue
                
                print(f"   🔍 Liquidity shortfall: ${liquidity_shortfall:.2f}")
                
                # Check if we have recent fills and need to wait
                if recent_fills or last_fill_time:
                    wait_needed = False
                    
                    if last_fill_time:
                        try:
                            last_fill = datetime.fromisoformat(last_fill_time.replace('Z', '+00:00'))
                            wait_until = last_fill + timedelta(seconds=self.fill_wait_period_seconds)
                            time_remaining = (wait_until - datetime.now(timezone.utc)).total_seconds()
                            
                            if time_remaining > 0:
                                print(f"   ⏰ WAIT PERIOD: {time_remaining:.0f}s remaining after recent system fill")
                                wait_needed = True
                            else:
                                print(f"   ✅ Wait period completed - can restore liquidity")
                        except Exception as e:
                            print(f"   ⚠️  Could not parse last fill time: {e}")
                    
                    if wait_needed:
                        continue
                
                # Check position limits (based on system bets only)
                remaining_capacity = max_position - total_stake
                if remaining_capacity <= 0:
                    print(f"   🛑 At max system position (${total_stake:.2f} >= ${max_position:.2f}) - cannot add more")
                    continue
                
                # Calculate bet amount to restore liquidity (within limits)
                bet_amount = min(liquidity_shortfall, remaining_capacity)
                
                if bet_amount > 0:
                    print(f"   ✅ RESTORING LIQUIDITY: Adding ${bet_amount:.2f}")
                    print(f"      (shortfall: ${liquidity_shortfall:.2f}, capacity: ${remaining_capacity:.2f})")
                    
                    success = await self._place_single_bet(
                        strategy_info,
                        bet_amount,
                        f"Restore liquidity (${total_matched:.2f} system filled)"
                    )
                    
                    if success:
                        incremental_bets += 1
                        print(f"      ✅ Liquidity restoration bet placed")
                    else:
                        print(f"      ❌ Failed to place liquidity restoration bet")
                else:
                    print(f"   ⏸️  No liquidity restoration needed")
                    
            except Exception as e:
                print(f"   ❌ Error checking line {line_id}: {e}")
                import traceback
                traceback.print_exc()
        
        if incremental_bets == 0:
            print("\\n📊 No liquidity restoration needed this cycle")
        else:
            print(f"\\n✅ Restored liquidity on {incremental_bets} lines this cycle")
        
        return incremental_bets


    async def _initial_bet_phase(self) -> int:
        """
        PHASE 1: Ensure each line has the recommended initial liquidity
        
        Now only counts SYSTEM BETS (non-empty external_id) for position calculations.
        Manual UI bets are completely ignored.
        """
        print("🎯 Running initial liquidity setup...")
        print("Rule: Ensure each line has recommended initial liquidity available")
        print("📊 Only counting system bets (non-empty external_id)")
        print("-" * 60)
        
        initial_bets = 0
        
        for line_id, strategy_info in self.monitored_lines.items():
            try:
                # Get current position (system bets only)
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(
                    line_id, 
                    system_bets_only=True,
                    external_id_filter="single_test_"  # Filter for our system's bets
                )
                
                if not position_result["success"]:
                    print(f"❌ Could not check position for {strategy_info['selection_name']}")
                    continue
                
                summary = position_result["position_summary"]
                total_stake = summary.get("total_stake", 0)
                total_matched = summary.get("total_matched", 0)
                current_unmatched = total_stake - total_matched
                system_bets = summary.get("system_bets", 0)
                manual_bets = summary.get("manual_bets", 0)
                
                recommended_initial = strategy_info["recommended_initial_stake"]
                max_position = strategy_info["max_position"]
                
                print(f"📊 {strategy_info['selection_name'][:30]:<30}")
                
                if manual_bets > 0:
                    print(f"   📝 Found {manual_bets} manual UI bets (ignored in calculations)")
                
                # Handle case where no SYSTEM wagers exist yet
                if system_bets == 0:
                    print(f"   ✅ No system wagers - placing initial ${recommended_initial:.2f} bet")
                    
                    success = await self._place_single_bet(
                        strategy_info, 
                        recommended_initial, 
                        "Initial bet (no prior system wagers)"
                    )
                    
                    if success:
                        initial_bets += 1
                    continue
                
                print(f"   System position: ${total_stake:.2f} total, ${total_matched:.2f} matched, ${current_unmatched:.2f} unmatched")
                print(f"   Target: ${recommended_initial:.2f} unmatched, max: ${max_position:.2f} total")
                
                # Calculate if we need to add liquidity
                liquidity_needed = max(0, recommended_initial - current_unmatched)
                
                if liquidity_needed == 0:
                    print(f"   ✅ Already has adequate liquidity (${current_unmatched:.2f} >= ${recommended_initial:.2f})")
                    continue
                
                # Check position limits (based on system bets only)
                remaining_capacity = max_position - total_stake
                if remaining_capacity <= 0:
                    print(f"   🛑 At max system position (${total_stake:.2f} >= ${max_position:.2f}) - cannot add more")
                    continue
                
                # Calculate actual bet amount (limited by capacity)
                bet_amount = min(liquidity_needed, remaining_capacity)
                
                if bet_amount > 0:
                    print(f"   ✅ Adding ${bet_amount:.2f} liquidity (needed: ${liquidity_needed:.2f}, capacity: ${remaining_capacity:.2f})")
                    
                    success = await self._place_single_bet(
                        strategy_info, 
                        bet_amount, 
                        f"Restore liquidity to ${recommended_initial:.2f}"
                    )
                    
                    if success:
                        initial_bets += 1
                else:
                    print(f"   ⏸️  No liquidity needed")
                    
            except Exception as e:
                print(f"❌ Error checking line {line_id}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\\n📊 Initial phase complete: {initial_bets} bets placed")
        return initial_bets
        
    async def _single_event_monitoring_loop(self):
        """Main monitoring loop for single event"""
        print(f"\\n🔄 Starting single event monitoring loop...")
        print(f"Event: {self.session.event_name}")
        print(f"Lines to monitor: {len(self.monitored_lines)}")
        
        while self.monitoring_active:
            try:
                self.session.monitoring_cycles += 1
                cycle_start = time.time()
                
                print(f"\\n🔄 SINGLE EVENT CYCLE #{self.session.monitoring_cycles} ({datetime.now().strftime('%H:%M:%S')})")
                print(f"Event: {self.session.event_name}")
                print("=" * 50)
                
                # Step 1: Check current positions
                await self._check_current_positions()
                
                # Step 2: Place new bets if needed
                new_bets = await self._place_new_bets()
                self.session.total_bets_placed += new_bets
                
                # Step 3: Check for fills
                fills = await self._check_for_fills()
                self.session.total_fills_detected += fills
                
                # Step 4: Summary
                cycle_duration = time.time() - cycle_start
                print(f"\\n📈 CYCLE #{self.session.monitoring_cycles} COMPLETE")
                print(f"   Duration: {cycle_duration:.1f}s")
                print(f"   New bets placed: {new_bets}")
                print(f"   Fills detected: {fills}")
                print(f"   Total session bets: {self.session.total_bets_placed}")
                print(f"   Next cycle in: {self.monitoring_interval_seconds}s")
                
                self.session.last_cycle_time = datetime.now(timezone.utc)
                
                # Wait for next cycle
                await asyncio.sleep(self.monitoring_interval_seconds)
                
            except Exception as e:
                print(f"❌ Error in single event monitoring cycle: {e}")
                await asyncio.sleep(10)  # Shorter sleep on error
    
    async def _check_current_positions(self):
        """Check current positions for all lines"""
        print("\\n1️⃣ CHECKING CURRENT POSITIONS")
        print("-" * 30)
        
        for line_id, strategy_info in self.monitored_lines.items():
            try:
                # Get position from ProphetX
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(line_id)
                
                if position_result["success"]:
                    summary = position_result["position_summary"]
                    
                    total_stake = summary.get("total_stake", 0)
                    total_matched = summary.get("total_matched", 0)
                    has_active = summary.get("has_active_bets", False)
                    
                    utilization = (total_stake / strategy_info["max_position"]) * 100 if strategy_info["max_position"] > 0 else 0
                    
                    status_parts = []
                    if has_active:
                        unmatched = total_stake - total_matched
                        status_parts.append(f"${unmatched:.0f} active")
                    if total_matched > 0:
                        status_parts.append(f"${total_matched:.0f} matched")
                    
                    status_str = ", ".join(status_parts) if status_parts else "no bets"
                    
                    print(f"   📊 {strategy_info['selection_name'][:25]:<25} ({line_id[-8:]}): "
                          f"${total_stake:.0f}/${strategy_info['max_position']:.0f} "
                          f"({utilization:.0f}%) - {status_str}")
                else:
                    print(f"   📊 {strategy_info['selection_name'][:25]:<25} ({line_id[-8:]}): No position data")
                    
            except Exception as e:
                print(f"   ❌ Error checking line {line_id}: {e}")
    
    async def _place_new_bets(self) -> int:
        """
        UPDATED: Use the new liquidity-based logic
        
        This method now properly manages liquidity instead of just checking 
        if any bets were ever placed.
        """
        print("\\n🔄 LIQUIDITY-BASED BETTING LOGIC")
        print("-" * 40)
        
        # If we're in initial phase, use initial logic
        if not hasattr(self, 'initial_phase_complete') or not self.initial_phase_complete:
            print("   🎯 Running initial liquidity setup...")
            return await self._initial_bet_phase()
        
        # If we're in monitoring phase, use monitoring logic
        print("   📊 Running liquidity monitoring and restoration...")
        return await self._check_fills_and_place_incremental_bets()
    
    async def _place_single_bet(self, strategy_info: Dict[str, Any], amount: float, reason: str) -> bool:
        """Place a single bet"""
        try:
            print(f"   🎯 Placing: {strategy_info['selection_name']} {strategy_info['odds']:+d} for ${amount:.2f}")
            print(f"      Reason: {reason}")
            
            # Import ProphetX service
            from app.services.prophetx_service import prophetx_service
            
            # Generate external ID
            external_id = f"single_test_{strategy_info['line_id']}_{int(time.time())}"
            
            # Place the bet
            result = await prophetx_service.place_bet(
                line_id=strategy_info["line_id"],
                odds=strategy_info["odds"],
                stake=amount,
                external_id=external_id
            )
            
            if result["success"]:
                print(f"      ✅ Bet placed successfully (ID: {external_id})")
                return True
            else:
                print(f"      ❌ Bet failed: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            print(f"      ❌ Exception placing bet: {e}")
            return False
    
    async def _check_for_fills(self) -> int:
        """Check for recent fills"""
        print("\\n3️⃣ CHECKING FOR FILLS")
        print("-" * 30)
        
        try:
            line_ids = list(self.monitored_lines.keys())
            recent_fills = await self.prophetx_wager_service.detect_recent_fills(
                line_ids, 
                minutes_back=self.monitoring_interval_seconds // 60 + 5  # Check last few minutes
            )
            
            if recent_fills:
                print(f"🎉 Detected {len(recent_fills)} recent fills:")
                for fill in recent_fills:
                    strategy_info = self.monitored_lines.get(fill["line_id"])
                    selection_name = strategy_info["selection_name"] if strategy_info else "Unknown"
                    print(f"   💰 {selection_name}: ${fill['matched_stake']:.2f} matched")
            else:
                print("   📊 No recent fills detected")
            
            return len(recent_fills)
            
        except Exception as e:
            print(f"   ❌ Error checking for fills: {e}")
            return 0
    
    def get_session_status(self) -> Dict[str, Any]:
        """Get current session status"""
        if not self.session:
            return {
                "active": False,
                "message": "No active session"
            }
        
        return {
            "active": self.session.is_active,
            "event_id": self.session.odds_api_event_id,
            "event_name": self.session.event_name,
            "start_time": self.session.start_time.isoformat(),
            "monitoring_cycles": self.session.monitoring_cycles,
            "lines_monitored": len(self.session.lines_identified),
            "total_bets_placed": self.session.total_bets_placed,
            "total_fills_detected": self.session.total_fills_detected,
            # NEW: Odds monitoring stats
            "odds_changes_detected": getattr(self, 'odds_changes_detected', 0),
            "last_odds_check": self.last_odds_check_time.isoformat() if self.last_odds_check_time else None,
            "has_original_odds_stored": bool(getattr(self, 'original_pinnacle_odds', {})),
            "last_cycle_time": self.session.last_cycle_time.isoformat() if self.session.last_cycle_time else None,
            "monitoring_interval_seconds": self.monitoring_interval_seconds,
            "metadata_summary": {
                "lines_with_metadata": len(self.line_metadata),
                "prophetx_events": len(set(m.prophetx_event_id for m in self.line_metadata.values() if m.prophetx_event_id)),
                "prophetx_markets": len(set(m.prophetx_market_id for m in self.line_metadata.values() if m.prophetx_market_id)),
                "market_types": list(set(m.market_type for m in self.line_metadata.values() if m.market_type))
            }
        }
    
    # 4. Add this method to fetch and store metadata when lines are created

    async def _fetch_and_store_line_metadata_improved(self, line_id: str, prophetx_event_id: int, 
                                        market_matches, selection_name: str):
        """
        Improved version that properly extracts market_id from market_matches
        """
        try:
            market_id = None
            market_type = "unknown"
            
            # Search through all market matches to find the one containing this line_id
            if hasattr(market_matches, 'market_matches'):
                for market_match in market_matches.market_matches:
                    if hasattr(market_match, 'outcome_mappings'):
                        for outcome_mapping in market_match.outcome_mappings:
                            # Handle both dict and object formats
                            if isinstance(outcome_mapping, dict):
                                mapping_line_id = outcome_mapping.get('prophetx_line_id')
                            else:
                                mapping_line_id = getattr(outcome_mapping, 'prophetx_line_id', None)
                            
                            if mapping_line_id == line_id:
                                # Found our line! Get the market info
                                raw_market_id = getattr(market_match, 'prophetx_market_id', None)
                                market_type = getattr(market_match, 'odds_api_market_type', 'unknown')
                                
                                # ✅ FIX: Convert market_id to integer
                                if raw_market_id is not None:
                                    try:
                                        market_id = int(raw_market_id)
                                    except (ValueError, TypeError):
                                        print(f"⚠️ Could not convert market_id '{raw_market_id}' to int")
                                        market_id = None
                                
                                print(f"   🎯 Found line {line_id} in market {market_id} ({market_type})")
                                break
                    
                    if market_id:  # Break outer loop too
                        break
            
            # Store the metadata
            metadata = LineMetadata(
                line_id=line_id,
                prophetx_event_id=prophetx_event_id,
                prophetx_market_id=market_id,  # This will now be an int or None
                market_type=market_type,
                selection_name=selection_name,
                last_updated=datetime.now(timezone.utc)
            )
            
            self.line_metadata[line_id] = metadata
            
            # Show status
            if market_id:
                print(f"   ✅ Complete metadata for {selection_name}: Event {prophetx_event_id}, Market {market_id} ({market_type})")
            else:
                print(f"   ⚠️ Missing market_id for {selection_name}: Event {prophetx_event_id}")
                
        except Exception as e:
            print(f"❌ Error storing metadata for line {line_id}: {e}")

# 5. Add these utility methods to access the metadata
    def get_line_metadata(self, line_id: str) -> Optional[LineMetadata]:
        """Get metadata for a specific line"""
        return self.line_metadata.get(line_id)
    
    def get_all_line_metadata(self) -> Dict[str, LineMetadata]:
        """Get all line metadata"""
        return self.line_metadata.copy()
    
    def get_lines_by_event_id(self, prophetx_event_id: int) -> List[str]:
        """Get all line IDs for a specific ProphetX event"""
        return [
            line_id for line_id, metadata in self.line_metadata.items()
            if metadata.prophetx_event_id == prophetx_event_id
        ]
    
    def get_lines_by_market_id(self, prophetx_market_id: int) -> List[str]:
        """Get all line IDs for a specific ProphetX market"""
        return [
            line_id for line_id, metadata in self.line_metadata.items()
            if metadata.prophetx_market_id == prophetx_market_id
        ]
    

    def get_markets_for_cancellation(self) -> List[Dict[str, Any]]:
        """
        Get list of markets that can be cancelled
        
        Returns:
            List of markets with event_id and market_id for cancellation
        """
        markets = {}
        
        for line_id, metadata in self.line_metadata.items():
            if metadata.prophetx_event_id and metadata.prophetx_market_id:
                market_key = f"{metadata.prophetx_event_id}_{metadata.prophetx_market_id}"
                
                if market_key not in markets:
                    markets[market_key] = {
                        "event_id": metadata.prophetx_event_id,
                        "market_id": metadata.prophetx_market_id,
                        "market_type": metadata.market_type,
                        "lines": []
                    }
                
                markets[market_key]["lines"].append({
                    "line_id": line_id,
                    "selection_name": metadata.selection_name
                })
        
        return list(markets.values())


    async def cancel_wagers_for_market(self, market_id) -> Dict[str, Any]:
        """
        FIXED: Cancel all wagers for a specific market in the current session
        Now properly passes both event_id and market_id to ProphetX service
        
        Args:
            market_id: ProphetX market ID to cancel (int or string)
            
        Returns:
            Cancellation result
        """
        if not self.session or not self.session.is_active:
            return {
                "success": False,
                "message": "No active session"
            }
        
        try:
            # ✅ FIX: Convert market_id to int for consistent comparison
            try:
                market_id_int = int(market_id)
            except (ValueError, TypeError):
                return {
                    "success": False,
                    "message": f"Invalid market_id: {market_id}"
                }
            
            # Find the event_id for this market
            event_id = None
            affected_lines = []
            
            for line_id, metadata in self.line_metadata.items():
                # ✅ FIX: Compare integers
                if metadata.prophetx_market_id == market_id_int:
                    event_id = metadata.prophetx_event_id
                    affected_lines.append({
                        "line_id": line_id,
                        "selection_name": metadata.selection_name
                    })
            
            if not event_id:
                return {
                    "success": False,
                    "message": f"Market {market_id_int} not found in current session",
                    "debug_info": {
                        "searched_for": market_id_int,
                        "available_markets": [m.prophetx_market_id for m in self.line_metadata.values() if m.prophetx_market_id],
                        "market_types": [(m.prophetx_market_id, type(m.prophetx_market_id)) for m in self.line_metadata.values() if m.prophetx_market_id]
                    }
                }
            
            print(f"🗑️ Cancelling wagers for event {event_id}, market {market_id_int} (affects {len(affected_lines)} lines)")
            for line in affected_lines:
                print(f"   📏 {line['selection_name']}")
            
            # Import and call ProphetX service
            from app.services.prophetx_service import prophetx_service
            
            # ✅ MAJOR FIX: Pass BOTH event_id AND market_id
            result = await prophetx_service.cancel_wagers_by_market(event_id, market_id_int)
            
            if result["success"]:
                print(f"✅ Successfully cancelled wagers for event {event_id}, market {market_id_int}")
                
                # Update our internal tracking - mark affected lines as needing new bets
                for line in affected_lines:
                    line_id = line["line_id"]
                    # Clear any wait periods for these lines so new bets can be placed immediately
                    if hasattr(self, 'market_making_strategy') and self.market_making_strategy:
                        if hasattr(self.market_making_strategy, 'betting_manager'):
                            self.market_making_strategy.betting_manager.clear_wait_period(line_id)
                
                return {
                    "success": True,
                    "message": f"Cancelled wagers for event {event_id}, market {market_id_int}",
                    "data": {
                        "event_id": event_id,
                        "market_id": market_id_int,
                        "affected_lines": len(affected_lines),
                        "lines": affected_lines,
                        "cancelled_count": result.get("data", {}).get("cancelled_count", "unknown")
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to cancel wagers for event {event_id}, market {market_id_int}",
                    "error": result.get("error", "Unknown error"),
                    "prophetx_response": result
                }
                
        except Exception as e:
            import traceback
            return {
                "success": False,
                "message": f"Exception cancelling market {market_id}: {str(e)}",
                "traceback": traceback.format_exc()
            }

    async def cancel_all_wagers_for_event(self) -> Dict[str, Any]:
        """
        Cancel all wagers for all markets in the current event
        
        Returns:
            Cancellation results for all markets
        """
        if not self.session or not self.session.is_active:
            return {
                "success": False,
                "message": "No active session"
            }
        
        markets = self.get_markets_for_cancellation()
        
        if not markets:
            return {
                "success": False,
                "message": "No markets found for cancellation"
            }
        
        print(f"🗑️ Cancelling wagers for {len(markets)} markets")
        
        results = []
        successful_cancellations = 0
        
        for market in markets:
            result = await self.cancel_wagers_for_market(market["market_id"])
            results.append({
                "market_id": market["market_id"],
                "market_type": market["market_type"],
                "success": result["success"],
                "message": result["message"]
            })
            
            if result["success"]:
                successful_cancellations += 1
        
        return {
            "success": successful_cancellations > 0,
            "message": f"Cancelled {successful_cancellations}/{len(markets)} markets",
            "data": {
                "total_markets": len(markets),
                "successful_cancellations": successful_cancellations,
                "results": results
            }
        }
    
    async def _monitor_pinnacle_odds_changes(self):
        """
        NEW STEP 3: Monitor Pinnacle for odds changes and update bets accordingly
        
        This will:
        1. Fetch current Pinnacle odds for our event
        2. Compare with odds we originally bet at
        3. If significant changes detected, cancel affected markets and place new bets
        """
        print("\n3️⃣ MONITORING PINNACLE ODDS CHANGES")
        print("-" * 30)
        
        try:
            # Fetch current Pinnacle odds
            current_pinnacle_odds = await self._fetch_current_pinnacle_odds()
            
            if not current_pinnacle_odds:
                print("⚠️  Could not fetch current Pinnacle odds")
                return
            
            # Compare with our original odds and detect changes
            odds_changes = await self._detect_significant_odds_changes(current_pinnacle_odds)
            
            if not odds_changes:
                print("✅ No significant odds changes detected")
                return
            
            print(f"🚨 SIGNIFICANT ODDS CHANGES DETECTED: {len(odds_changes)} markets affected")
            
            # Process each market with changes
            for market_change in odds_changes:
                await self._handle_market_odds_change(market_change)
            
            print("✅ All odds changes processed")
            
        except Exception as e:
            print(f"❌ Error monitoring Pinnacle odds: {e}")

    async def _fetch_current_pinnacle_odds(self):
        """
        FIXED: Fetch current Pinnacle odds for our specific event
        Uses the EXACT same logic as start_single_event_test()
        """
        try:
            from app.services.odds_api_service import odds_api_service
            
            print(f"📊 Fetching current odds for event: {self.session.odds_api_event_id}")
            
            # Step 1: Get ALL current events (same as initial setup)
            odds_api_events = await odds_api_service.get_events()
            
            # Step 2: Find our SPECIFIC event by ID (same as initial setup)
            target_event = None
            for event in odds_api_events:
                if event.event_id == self.session.odds_api_event_id:
                    target_event = event
                    break
            
            if not target_event:
                print(f"⚠️  Event {self.session.odds_api_event_id} no longer available in Odds API")
                print(f"    This usually means the game has started or odds were removed")
                return None
            
            # Step 3: Verify it's the same event (safety check)
            expected_name = self.session.event_name
            actual_name = f"{target_event.away_team} vs {target_event.home_team}"
            
            if expected_name != actual_name:
                print(f"⚠️  Event name mismatch!")
                print(f"    Expected: {expected_name}")
                print(f"    Found: {actual_name}")
                print(f"    Event ID: {target_event.event_id}")
                # Continue anyway, but log the discrepancy
            
            print(f"✅ Found current odds for: {actual_name}")
            print(f"   Event ID: {target_event.event_id}")
            print(f"   Commence time: {target_event.commence_time}")
            
            # Step 4: Log available markets for debugging
            available_markets = []
            if target_event.moneyline:
                available_markets.append(f"moneyline ({len(target_event.moneyline.outcomes)} outcomes)")
            if target_event.spreads:
                available_markets.append(f"spreads ({len(target_event.spreads.outcomes)} outcomes)")
            if target_event.totals:
                available_markets.append(f"totals ({len(target_event.totals.outcomes)} outcomes)")
            
            print(f"   Available markets: {', '.join(available_markets)}")
            
            return target_event
            
        except Exception as e:
            print(f"❌ Error fetching current Pinnacle odds: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _detect_significant_odds_changes(self, current_pinnacle_event):
        """
        ENHANCED: Compare current Pinnacle odds with stored original odds
        
        Returns list of market changes that require bet updates
        """
        SIGNIFICANT_CHANGE_THRESHOLD = 1  # 1 point odds change threshold

        if not hasattr(self, 'original_pinnacle_odds') or not self.original_pinnacle_odds:
            print("⚠️  No original odds stored for comparison")
            return []
        
        changes = []
        
        try:
            print("🔍 Comparing current odds with original odds...")
            
            # Compare moneyline
            if current_pinnacle_event.moneyline and self.original_pinnacle_odds.get('moneyline'):
                changes.extend(await self._compare_market_odds(
                    'moneyline', 
                    current_pinnacle_event.moneyline.outcomes,
                    self.original_pinnacle_odds['moneyline'],
                    SIGNIFICANT_CHANGE_THRESHOLD
                ))
            
            # Compare spreads
            if current_pinnacle_event.spreads and self.original_pinnacle_odds.get('spreads'):
                changes.extend(await self._compare_market_odds(
                    'spreads',
                    current_pinnacle_event.spreads.outcomes, 
                    self.original_pinnacle_odds['spreads'],
                    SIGNIFICANT_CHANGE_THRESHOLD
                ))
            
            # Compare totals
            if current_pinnacle_event.totals and self.original_pinnacle_odds.get('totals'):
                changes.extend(await self._compare_market_odds(
                    'totals',
                    current_pinnacle_event.totals.outcomes,
                    self.original_pinnacle_odds['totals'], 
                    SIGNIFICANT_CHANGE_THRESHOLD
                ))
            
            if changes:
                print(f"🚨 {len(changes)} significant odds changes detected:")
                for change in changes:
                    print(f"   {change['market_type']}: {change['outcome_name']} {change['old_odds']:+d} → {change['new_odds']:+d} ({change['change_amount']:+d})")
            else:
                print("✅ No significant odds changes detected")
            
            return changes
            
        except Exception as e:
            print(f"❌ Error detecting odds changes: {e}")
            return []

    async def _handle_market_odds_change(self, market_change):
        """
        ENHANCED: Handle a significant odds change in a market by cancelling and replacing bets
        """
        market_id = market_change['prophetx_market_id']
        market_type = market_change['market_type']
        
        print(f"\n🔄 HANDLING ODDS CHANGE: {market_type.upper()} Market (ID: {market_id})")
        print(f"   Change: {market_change['outcome_name']} {market_change['old_odds']:+d} → {market_change['new_odds']:+d}")
        
        if market_id is None:
            print(f"❌ Cannot handle odds change - market_id is None for {market_type}")
            print(f"   This usually means the market type isn't found in line metadata")
            return
        
        try:
            # Step 1: Cancel all existing bets for this market
            print(f"🗑️  Cancelling existing bets for market {market_id}")
            cancel_result = await self.cancel_wagers_for_market(market_id)
            
            if not cancel_result['success']:
                print(f"❌ Failed to cancel market {market_id}: {cancel_result['message']}")
                return
            
            cancelled_count = cancel_result.get('data', {}).get('cancelled_count', 'unknown')
            print(f"✅ Cancelled {cancelled_count} bets for market {market_id}")
            
            # Step 2: Wait a moment for cancellations to process
            print("⏳ Waiting 2 seconds for cancellations to process...")
            await asyncio.sleep(2)
            
            # Step 3: Create new strategy with updated odds
            print("📊 Creating new strategy with updated Pinnacle odds")
            new_strategy = await self._create_updated_strategy_for_market(market_type)
            
            if not new_strategy:
                print(f"❌ Could not create updated strategy for {market_type}")
                return
            
            # Filter strategy to only include the affected market
            filtered_instructions = []
            for instruction in new_strategy.betting_instructions:
                # Check if this instruction belongs to our affected market
                instruction_market_id = self._get_market_id_for_line(instruction.line_id)
                if instruction_market_id == market_id:
                    filtered_instructions.append(instruction)
            
            if not filtered_instructions:
                print(f"❌ No betting instructions found for market {market_id} in new strategy")
                return
            
            print(f"📋 Found {len(filtered_instructions)} new betting instructions for this market")
            
            # Step 4: Place new bets according to updated strategy
            print("💰 Placing new bets with updated odds")
            
            # Create a minimal strategy object with just the filtered instructions
            class FilteredStrategy:
                def __init__(self, instructions):
                    self.betting_instructions = instructions
            
            filtered_strategy = FilteredStrategy(filtered_instructions)
            new_bets_result = await self._place_bets_from_strategy(filtered_strategy)
            
            if new_bets_result['success']:
                print(f"✅ Placed {new_bets_result['bets_placed']} new bets with updated odds")
                
                # Update our monitored lines with new strategy
                await self._update_monitored_lines_from_strategy(filtered_strategy)
                
                # Track this as an odds change event
                if hasattr(self, 'odds_changes_detected'):
                    self.odds_changes_detected += 1
                
            else:
                print(f"❌ Failed to place new bets: {new_bets_result['message']}")
            
        except Exception as e:
            print(f"❌ Error handling market odds change: {e}")
            import traceback
            traceback.print_exc()

    async def _compare_market_odds(self, market_type, current_outcomes, original_outcomes, threshold):
        """Helper method to compare odds for a specific market type"""
        changes = []
        
        for current_outcome in current_outcomes:
            # Find matching original outcome
            original_outcome = None
            for orig in original_outcomes:
                if current_outcome.name == orig['name']:
                    # For spreads/totals, also check point value matches
                    if market_type in ['spreads', 'totals']:
                        if hasattr(current_outcome, 'point') and current_outcome.point == orig.get('point'):
                            original_outcome = orig
                            break
                    else:
                        original_outcome = orig
                        break
            
            if original_outcome:
                odds_diff = current_outcome.american_odds - original_outcome['odds']
                
                if abs(odds_diff) >= threshold:
                    changes.append({
                        'market_type': market_type,
                        'outcome_name': current_outcome.name,
                        'old_odds': original_outcome['odds'],
                        'new_odds': current_outcome.american_odds,
                        'change_amount': odds_diff,
                        'prophetx_market_id': self._get_market_id_for_type(market_type),
                        'point': getattr(current_outcome, 'point', None)  # For spreads/totals
                    })
        
        return changes

    def _store_original_pinnacle_odds(self, pinnacle_event):
        """
        ENHANCED: Store the original Pinnacle odds with better structure
        """
        self.original_pinnacle_odds = {}
        
        print("💾 Storing original Pinnacle odds for monitoring...")
        
        if pinnacle_event.moneyline:
            self.original_pinnacle_odds['moneyline'] = [
                {
                    'name': outcome.name,
                    'odds': outcome.american_odds
                }
                for outcome in pinnacle_event.moneyline.outcomes
            ]
            print(f"   Moneyline: {len(pinnacle_event.moneyline.outcomes)} outcomes stored")
        
        if pinnacle_event.spreads:
            self.original_pinnacle_odds['spreads'] = [
                {
                    'name': outcome.name,
                    'odds': outcome.american_odds,
                    'point': outcome.point
                }
                for outcome in pinnacle_event.spreads.outcomes
            ]
            print(f"   Spreads: {len(pinnacle_event.spreads.outcomes)} outcomes stored")
        
        if pinnacle_event.totals:
            self.original_pinnacle_odds['totals'] = [
                {
                    'name': outcome.name,
                    'odds': outcome.american_odds,
                    'point': outcome.point
                }
                for outcome in pinnacle_event.totals.outcomes
            ]
            print(f"   Totals: {len(pinnacle_event.totals.outcomes)} outcomes stored")
        
        print(f"✅ Original odds stored for {len(self.original_pinnacle_odds)} market types")

    # ADD: New debugging endpoint to check what's being stored/compared
    async def debug_odds_comparison(self):
        """Debug method to show current vs original odds comparison"""
        if not hasattr(self, 'original_pinnacle_odds') or not self.original_pinnacle_odds:
            return {"error": "No original odds stored"}
        
        current_event = await self._fetch_current_pinnacle_odds()
        if not current_event:
            return {"error": "Cannot fetch current odds"}
        
        debug_info = {
            "event_id": self.session.odds_api_event_id,
            "event_name": self.session.event_name,
            "current_event_name": f"{current_event.away_team} vs {current_event.home_team}",
            "comparison": {}
        }
        
        # Compare each market type
        for market_type in ['moneyline', 'spreads', 'totals']:
            if market_type in self.original_pinnacle_odds:
                debug_info["comparison"][market_type] = {
                    "original": self.original_pinnacle_odds[market_type],
                    "current": None
                }
                
                # Get current market data
                if market_type == 'moneyline' and current_event.moneyline:
                    debug_info["comparison"][market_type]["current"] = [
                        {"name": o.name, "odds": o.american_odds} 
                        for o in current_event.moneyline.outcomes
                    ]
                elif market_type == 'spreads' and current_event.spreads:
                    debug_info["comparison"][market_type]["current"] = [
                        {"name": o.name, "odds": o.american_odds, "point": o.point}
                        for o in current_event.spreads.outcomes
                    ]
                elif market_type == 'totals' and current_event.totals:
                    debug_info["comparison"][market_type]["current"] = [
                        {"name": o.name, "odds": o.american_odds, "point": o.point}
                        for o in current_event.totals.outcomes
                    ]
        
        return debug_info

    def _get_market_id_for_type(self, market_type):
        """
        ENHANCED: Get the ProphetX market ID for a given market type with better debugging
        """
        print(f"🔍 Looking for market_type: '{market_type}'")
        print(f"   Available line metadata: {len(self.line_metadata)} lines")
        
        # Debug: Show all available market types
        available_types = set()
        for line_id, metadata in self.line_metadata.items():
            if metadata.market_type:
                available_types.add(metadata.market_type)
                print(f"   Line {line_id[-8:]}: market_type='{metadata.market_type}', market_id={metadata.prophetx_market_id}")
        
        print(f"   Available market types: {list(available_types)}")
        
        # ✅ FIX: Handle different market type naming conventions
        # The issue might be that market_type is stored differently than what we're searching for
        market_type_mappings = {
            'moneyline': ['moneyline', 'h2h', 'match_winner'],
            'spreads': ['spreads', 'spread', 'handicap'],
            'totals': ['totals', 'total', 'over_under']
        }
        
        possible_names = market_type_mappings.get(market_type, [market_type])
        
        for line_id, metadata in self.line_metadata.items():
            if metadata.market_type in possible_names:
                print(f"✅ Found market_id {metadata.prophetx_market_id} for market_type '{market_type}' (stored as '{metadata.market_type}')")
                return metadata.prophetx_market_id
        
        print(f"❌ No market_id found for market_type '{market_type}'")
        print(f"   Tried variations: {possible_names}")
        return None
    
    async def _create_updated_strategy_for_market(self, market_type):
        """Create new strategy with current Pinnacle odds for a specific market"""
        try:
            # Get current event match (reuse existing logic)
            from app.services.event_matching_service import event_matching_service
            from app.services.market_matching_service import market_matching_service
            
            # Get fresh Pinnacle data
            current_pinnacle_event = await self._fetch_current_pinnacle_odds()
            if not current_pinnacle_event:
                return None
            
            # Recreate event match with current odds
            # (You can reuse the logic from your start_single_event_test method)
            odds_api_events = [current_pinnacle_event]
            matching_attempts = await event_matching_service.find_matches_for_events(odds_api_events)
            
            if not matching_attempts or not matching_attempts[0].best_match:
                return None
            
            event_match = matching_attempts[0].best_match
            
            # Get market matching
            market_match_result = await market_matching_service.match_event_markets(event_match)
            
            # Create new strategy with updated odds
            strategy = self.market_making_strategy.create_market_making_plan(event_match, market_match_result)
            
            return strategy
            
        except Exception as e:
            print(f"❌ Error creating updated strategy: {e}")
            return None

    async def _place_bets_from_strategy(self, strategy):
        """
        FIXED: Place bets according to a strategy using the correct ProphetX service
        
        Uses the same bet placement logic as the initial setup
        """
        try:
            if not strategy or not strategy.betting_instructions:
                return {"success": False, "message": "No betting instructions in strategy"}
            
            from app.services.prophetx_service import prophetx_service
            import uuid
            
            bets_placed = 0
            failed_bets = 0
            bet_results = []
            
            print(f"💰 Placing {len(strategy.betting_instructions)} bets with updated odds")
            
            for instruction in strategy.betting_instructions:
                try:
                    # Generate unique external_id for tracking
                    external_id = f"odds_update_{int(time.time())}_{str(uuid.uuid4())[:8]}"
                    
                    print(f"   💰 Placing: {instruction.selection_name} @ {instruction.odds:+d} for ${instruction.stake:.2f}")
                    
                    # Use the correct service and method name
                    bet_result = await prophetx_service.place_bet(
                        line_id=instruction.line_id,
                        odds=instruction.odds,
                        stake=instruction.stake,
                        external_id=external_id
                    )
                    
                    if bet_result["success"]:
                        bets_placed += 1
                        print(f"   ✅ Success: {instruction.selection_name}")
                        
                        # Update our tracking for this line
                        self.session.total_bets_placed += 1
                        
                        bet_results.append({
                            "selection_name": instruction.selection_name,
                            "line_id": instruction.line_id,
                            "odds": instruction.odds,
                            "stake": instruction.stake,
                            "status": "success",
                            "external_id": external_id,
                            "bet_id": bet_result.get("bet_id")
                        })
                        
                    else:
                        failed_bets += 1
                        error_msg = bet_result.get("error", "Unknown error")
                        print(f"   ❌ Failed: {instruction.selection_name} - {error_msg}")
                        
                        bet_results.append({
                            "selection_name": instruction.selection_name,
                            "line_id": instruction.line_id,
                            "odds": instruction.odds,
                            "stake": instruction.stake,
                            "status": "failed",
                            "error": error_msg
                        })
                    
                except Exception as e:
                    failed_bets += 1
                    error_msg = f"Exception placing bet: {str(e)}"
                    print(f"   ❌ Exception: {instruction.selection_name} - {error_msg}")
                    
                    bet_results.append({
                        "selection_name": instruction.selection_name,
                        "line_id": instruction.line_id,
                        "odds": instruction.odds,
                        "stake": instruction.stake,
                        "status": "exception",
                        "error": error_msg
                    })
            
            # Summary
            success_rate = (bets_placed / len(strategy.betting_instructions)) * 100 if strategy.betting_instructions else 0
            
            if bets_placed > 0:
                print(f"✅ Successfully placed {bets_placed}/{len(strategy.betting_instructions)} bets ({success_rate:.1f}% success rate)")
            
            if failed_bets > 0:
                print(f"❌ {failed_bets} bets failed to place")
            
            return {
                "success": bets_placed > 0,
                "bets_placed": bets_placed,
                "failed_bets": failed_bets,
                "success_rate": success_rate,
                "message": f"Placed {bets_placed}/{len(strategy.betting_instructions)} updated bets",
                "bet_details": bet_results
            }
            
        except Exception as e:
            import traceback
            error_msg = f"Error placing bets from strategy: {str(e)}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            
            return {
                "success": False, 
                "message": error_msg,
                "bets_placed": 0,
                "failed_bets": 0
            }

    async def _update_monitored_lines_from_strategy(self, strategy):
        """
        ENHANCED: Update our monitored lines with new strategy information
        
        This ensures our monitoring data reflects the new odds and stakes
        """
        try:
            if not strategy or not strategy.betting_instructions:
                print("⚠️  No strategy instructions to update from")
                return
            
            updated_lines = 0
            
            print(f"📝 Updating monitored lines with new strategy data...")
            
            for instruction in strategy.betting_instructions:
                line_id = instruction.line_id
                
                # Update the monitored line with new odds/strategy
                if line_id in self.monitored_lines:
                    # Keep the existing data but update the key fields
                    old_odds = self.monitored_lines[line_id].get("odds", "unknown")
                    
                    self.monitored_lines[line_id].update({
                        "odds": instruction.odds,
                        "recommended_initial_stake": instruction.stake,
                        "last_updated": datetime.now(timezone.utc),
                        "updated_due_to_odds_change": True
                    })
                    
                    print(f"   📝 Updated {instruction.selection_name}: {old_odds} → {instruction.odds:+d}")
                    updated_lines += 1
                    
                    # Also update line metadata if we have it
                    if hasattr(self, 'line_metadata') and line_id in self.line_metadata:
                        self.line_metadata[line_id].last_updated = datetime.now(timezone.utc)
                
                else:
                    print(f"   ⚠️  Line {line_id} not found in monitored lines")
            
            print(f"✅ Updated {updated_lines} monitored lines with new strategy")
            
        except Exception as e:
            print(f"❌ Error updating monitored lines: {e}")


# Global single event tester instance
single_event_line_tester = SingleEventLineTester()