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

class SingleEventLineTester:
    """Test line monitoring workflow on a single event"""
    
    def __init__(self):
        self.session: Optional[SingleEventSession] = None
        self.monitoring_active = False
        self.monitored_lines: Dict[str, Any] = {}  # line_id -> strategy info
        self.initial_phase_complete = False
        
        # Services (will be injected)
        self.line_position_service = None
        self.prophetx_wager_service = None
        self.market_making_strategy = None
        
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
            for instruction in strategy.betting_instructions:
                self.monitored_lines[instruction.line_id] = {
                    "line_id": instruction.line_id,
                    "selection_name": instruction.selection_name,
                    "odds": instruction.odds,
                    "recommended_initial_stake": instruction.stake,
                    "max_position": instruction.max_position,
                    "increment_size": instruction.increment_size,
                    "event_id": str(event_match.prophetx_event.event_id),
                    "market_type": "h2h"
                }
            
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
                
                # Step 3: Update session stats
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
                print(f"❌ Error in monitoring cycle {cycle_count}: {e}")
                await asyncio.sleep(30)  # Wait 30s before retrying

    async def _check_fills_and_place_incremental_bets(self) -> int:
        """
        Check for fills and place incremental bets only when appropriate
        
        Rules:
        - Only place incremental bets if there are recent fills
        - Must wait 5 minutes after fills before adding liquidity
        - Never exceed 4x max position
        """
        print("\\n2️⃣ CHECKING FOR FILLS AND INCREMENTAL BETTING")
        print("-" * 45)
        
        incremental_bets = 0
        
        for line_id, strategy_info in self.monitored_lines.items():
            try:
                # Get current position
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(line_id)
                
                if not position_result["success"]:
                    continue
                
                summary = position_result["position_summary"]
                recent_fills = summary.get("recent_fills", [])
                last_fill_time = summary.get("last_fill_time")
                
                print(f"   📊 {strategy_info['selection_name']}: {len(recent_fills)} recent fills")
                
                # Only proceed if we have fills
                if not recent_fills and not last_fill_time:
                    print(f"      ⏸️  No fills detected - no action needed")
                    continue
                
                # Check wait period
                if last_fill_time:
                    try:
                        last_fill = datetime.fromisoformat(last_fill_time.replace('Z', '+00:00'))
                        wait_until = last_fill + timedelta(seconds=self.fill_wait_period_seconds)
                        time_remaining = (wait_until - datetime.now(timezone.utc)).total_seconds()
                        
                        if time_remaining > 0:
                            print(f"      ⏰ Wait period active - {time_remaining:.0f}s remaining")
                            continue
                    except:
                        pass
                
                # Calculate incremental bet needed
                current_stake = summary["total_stake"]
                total_matched = summary["total_matched"]
                
                # If we've had fills, we need to restore liquidity
                if total_matched > 0:
                    target_unmatched = strategy_info["recommended_initial_stake"]
                    current_unmatched = current_stake - total_matched
                    
                    if current_unmatched < target_unmatched:
                        needed = target_unmatched - current_unmatched
                        
                        # Check position limits
                        remaining_capacity = strategy_info["max_position"] - current_stake
                        bet_amount = min(needed, remaining_capacity, strategy_info["increment_size"])
                        
                        if bet_amount > 0:
                            print(f"      ✅ Adding ${bet_amount:.2f} to restore liquidity after fills")
                            
                            success = await self._place_single_bet(
                                strategy_info,
                                bet_amount,
                                f"Incremental bet (restore after ${total_matched:.2f} filled)"
                            )
                            
                            if success:
                                incremental_bets += 1
                        else:
                            print(f"      🛑 At position limit - cannot add more")
                    else:
                        print(f"      ✅ Liquidity adequate - no incremental bet needed")
                        
            except Exception as e:
                print(f"   ❌ Error checking line {line_id}: {e}")
        
        if incremental_bets == 0:
            print("   📊 No incremental bets needed this cycle")
        
        return incremental_bets

    async def _initial_bet_phase(self) -> int:
        """
        PHASE 1: Place initial bets only where no position exists
        
        This runs ONCE at the start and only places bets on lines with NO existing bets.
        """
        print("🎯 Running initial bet placement...")
        print("Rule: Only place bet if line has NO existing bets AND is profitable")
        print("-" * 50)
        
        initial_bets = 0
        
        for line_id, strategy_info in self.monitored_lines.items():
            try:
                # Check if ANY bets exist for this line
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(line_id)
                
                if not position_result["success"]:
                    print(f"❌ Could not check position for {strategy_info['selection_name']}")
                    continue
                
                total_bets = position_result["position_summary"]["total_bets"]
                total_stake = position_result["position_summary"]["total_stake"]
                
                if total_bets == 0:
                    # No existing bets - place initial bet
                    print(f"✅ {strategy_info['selection_name']}: No existing bets - placing initial ${strategy_info['recommended_initial_stake']:.2f}")
                    
                    success = await self._place_single_bet(
                        strategy_info, 
                        strategy_info["recommended_initial_stake"], 
                        "Initial bet"
                    )
                    
                    if success:
                        initial_bets += 1
                else:
                    # Existing bets found - skip
                    print(f"⏸️  {strategy_info['selection_name']}: {total_bets} existing bets (${total_stake:.2f}) - skipping")
                    
            except Exception as e:
                print(f"❌ Error checking line {line_id}: {e}")
        
        print(f"\\n📊 Initial phase complete: {initial_bets} new bets placed")
        return initial_bets
    
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
                
                # Step 3: Update session stats
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
                print(f"❌ Error in monitoring cycle {cycle_count}: {e}")
                await asyncio.sleep(30)  # Wait 30s before retrying

    async def _check_fills_and_place_incremental_bets(self) -> int:
        """
        Check for fills and place incremental bets only when appropriate
        
        Rules:
        - Only place incremental bets if there are recent fills
        - Must wait 5 minutes after fills before adding liquidity
        - Never exceed 4x max position
        """
        print("\\n2️⃣ CHECKING FOR FILLS AND INCREMENTAL BETTING")
        print("-" * 45)
        
        incremental_bets = 0
        
        for line_id, strategy_info in self.monitored_lines.items():
            try:
                # Get current position
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(line_id)
                
                if not position_result["success"]:
                    continue
                
                summary = position_result["position_summary"]
                recent_fills = summary.get("recent_fills", [])
                last_fill_time = summary.get("last_fill_time")
                
                print(f"   📊 {strategy_info['selection_name']}: {len(recent_fills)} recent fills")
                
                # Only proceed if we have fills
                if not recent_fills and not last_fill_time:
                    print(f"      ⏸️  No fills detected - no action needed")
                    continue
                
                # Check wait period
                if last_fill_time:
                    try:
                        last_fill = datetime.fromisoformat(last_fill_time.replace('Z', '+00:00'))
                        wait_until = last_fill + timedelta(seconds=self.fill_wait_period_seconds)
                        time_remaining = (wait_until - datetime.now(timezone.utc)).total_seconds()
                        
                        if time_remaining > 0:
                            print(f"      ⏰ Wait period active - {time_remaining:.0f}s remaining")
                            continue
                    except:
                        pass
                
                # Calculate incremental bet needed
                current_stake = summary["total_stake"]
                total_matched = summary["total_matched"]
                
                # If we've had fills, we need to restore liquidity
                if total_matched > 0:
                    target_unmatched = strategy_info["recommended_initial_stake"]
                    current_unmatched = current_stake - total_matched
                    
                    if current_unmatched < target_unmatched:
                        needed = target_unmatched - current_unmatched
                        
                        # Check position limits
                        remaining_capacity = strategy_info["max_position"] - current_stake
                        bet_amount = min(needed, remaining_capacity, strategy_info["increment_size"])
                        
                        if bet_amount > 0:
                            print(f"      ✅ Adding ${bet_amount:.2f} to restore liquidity after fills")
                            
                            success = await self._place_single_bet(
                                strategy_info,
                                bet_amount,
                                f"Incremental bet (restore after ${total_matched:.2f} filled)"
                            )
                            
                            if success:
                                incremental_bets += 1
                        else:
                            print(f"      🛑 At position limit - cannot add more")
                    else:
                        print(f"      ✅ Liquidity adequate - no incremental bet needed")
                        
            except Exception as e:
                print(f"   ❌ Error checking line {line_id}: {e}")
        
        if incremental_bets == 0:
            print("   📊 No incremental bets needed this cycle")
        
        return incremental_bets
    
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
        DEPRECATED: This method is replaced by the new phase-based approach
        
        The new workflow uses:
        1. _initial_bet_phase() - runs once at startup
        2. _check_fills_and_place_incremental_bets() - runs in monitoring loop
        
        This method should no longer be called in the new workflow.
        """
        print("⚠️  WARNING: _place_new_bets called but deprecated")
        print("   Using new phase-based approach instead")
        
        # If we're in initial phase, don't place any bets here
        if not hasattr(self, 'initial_phase_complete') or not self.initial_phase_complete:
            print("   ⏸️  In initial phase - skipping")
            return 0
        
        # If we're in monitoring phase, delegate to the new method
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
            "last_cycle_time": self.session.last_cycle_time.isoformat() if self.session.last_cycle_time else None,
            "monitoring_interval_seconds": self.monitoring_interval_seconds
        }

# Global single event tester instance
single_event_line_tester = SingleEventLineTester()