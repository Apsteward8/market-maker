"""
Line Monitoring and Betting Loop

This is the core service that implements your complete workflow:

1. Run main strategy (map events/markets/lines)
2. For each line: check existing position via ProphetX wager histories  
3. If no position AND profitable → place initial bet
4. Every 60 seconds: scan all lines for fills
5. If fills detected → start 5-minute wait period
6. After wait period → add incremental liquidity up to 4x limit

Key features:
- Line-based position tracking (not individual bets)
- Real ProphetX data via wager histories API
- 4x position limits (e.g., $100 initial → $400 max)
- 5-minute wait periods after fills
- Proper incremental betting logic
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class LineStrategy:
    """Strategy information for a single line"""
    line_id: str
    selection_name: str
    odds: int
    recommended_initial_stake: float
    max_position: float  # 4x the initial stake
    increment_size: float  # Same as initial stake
    is_profitable: bool
    event_id: str
    market_type: str

class LineMonitoringService:
    """Main service that monitors lines and places bets according to the complete workflow"""
    
    def __init__(self):
        self.monitoring_active = False
        self.monitored_lines: Dict[str, LineStrategy] = {}
        self.last_strategy_run = None
        self.last_monitoring_cycle = None
        
        # Services
        self.line_position_service = None
        self.prophetx_wager_service = None
        self.market_making_strategy = None
        
        # Settings
        self.monitoring_interval_seconds = 60  # Check every 60 seconds
        self.fill_wait_period_seconds = 300   # 5 minutes
        
    def initialize_services(self, line_position_service, prophetx_wager_service, market_making_strategy):
        """Initialize required services"""
        self.line_position_service = line_position_service
        self.prophetx_wager_service = prophetx_wager_service
        self.market_making_strategy = market_making_strategy
    
    async def start_monitoring(self) -> Dict[str, Any]:
        """Start the complete monitoring workflow"""
        if self.monitoring_active:
            return {
                "success": False,
                "message": "Monitoring already active"
            }
        
        self.monitoring_active = True
        
        print("🚀 Starting Line Monitoring and Betting Service")
        print("=" * 60)
        
        # Start the main monitoring loop
        asyncio.create_task(self._main_monitoring_loop())
        
        return {
            "success": True,
            "message": "Line monitoring started",
            "monitoring_interval_seconds": self.monitoring_interval_seconds,
            "fill_wait_period_seconds": self.fill_wait_period_seconds
        }
    
    async def stop_monitoring(self) -> Dict[str, Any]:
        """Stop monitoring"""
        self.monitoring_active = False
        
        return {
            "success": True,
            "message": "Line monitoring stopped"
        }
    
    async def _main_monitoring_loop(self):
        """
        Main monitoring loop - this is the heart of the workflow
        
        Every cycle:
        1. Run strategy to get current profitable lines
        2. Check positions for each line via ProphetX API
        3. Place initial bets where appropriate
        4. Check for fills and manage wait periods
        5. Place incremental bets when ready
        """
        cycle_count = 0
        
        while self.monitoring_active:
            try:
                cycle_count += 1
                cycle_start = time.time()
                
                print(f"\\n🔄 MONITORING CYCLE #{cycle_count} ({datetime.now().strftime('%H:%M:%S')})")
                print("=" * 50)
                
                # Step 1: Run main strategy to get current lines
                await self._run_main_strategy()
                
                # Step 2: Monitor existing positions for fills
                await self._monitor_existing_positions()
                
                # Step 3: Place new bets where appropriate
                await self._place_new_bets()
                
                # Step 4: Log cycle summary
                cycle_duration = time.time() - cycle_start
                self._log_cycle_summary(cycle_count, cycle_duration)
                
                self.last_monitoring_cycle = datetime.now(timezone.utc)
                
                # Wait for next cycle
                await asyncio.sleep(self.monitoring_interval_seconds)
                
            except Exception as e:
                print(f"❌ Error in monitoring cycle: {e}")
                await asyncio.sleep(30)  # Shorter sleep on error
    
    async def _run_main_strategy(self):
        """
        Step 1: Run main strategy to identify profitable lines
        
        This maps events from Odds API to ProphetX and creates betting instructions
        for all profitable/arbitragable lines.
        """
        print("\\n1️⃣ RUNNING MAIN STRATEGY")
        print("-" * 30)
        
        try:
            # Import strategy services
            from app.services.odds_api_service import odds_api_service
            from app.services.event_matching_service import event_matching_service
            from app.services.market_matching_service import market_matching_service
            
            # Get events from Odds API
            print("📊 Fetching Odds API events...")
            odds_events = await odds_api_service.get_events()
            print(f"   Found {len(odds_events)} events")
            
            if not odds_events:
                print("⚠️  No events found - skipping strategy run")
                return
            
            # Process each event
            new_lines = {}
            total_profitable_lines = 0
            
            for odds_event in odds_events[:10]:  # Limit for performance
                try:
                    # Match event to ProphetX using correct method
                    matching_attempts = await event_matching_service.find_matches_for_events([odds_event])
                    
                    if not matching_attempts or not matching_attempts[0].best_match:
                        continue
                    
                    event_match = matching_attempts[0].best_match
                    
                    # Match markets
                    market_matches = await market_matching_service.match_event_markets(event_match)
                    
                    if not market_matches or not market_matches.ready_for_trading:
                        continue
                    
                    # Create betting strategy
                    strategy = self.market_making_strategy.create_market_making_plan(
                        event_match, market_matches
                    )
                    
                    if not strategy or not strategy.is_profitable:
                        continue
                    
                    # Extract line strategies
                    for instruction in strategy.betting_instructions:
                        line_strategy = LineStrategy(
                            line_id=instruction.line_id,
                            selection_name=instruction.selection_name,
                            odds=instruction.odds,
                            recommended_initial_stake=instruction.stake,
                            max_position=instruction.max_position,
                            increment_size=instruction.increment_size,
                            is_profitable=True,
                            event_id=str(event_match.prophetx_event.event_id),
                            market_type="h2h"  # Simplified for now
                        )
                        
                        new_lines[instruction.line_id] = line_strategy
                        total_profitable_lines += 1
                
                except Exception as e:
                    print(f"   ❌ Error processing event {odds_event.event_id}: {e}")
                    continue
            
            # Update monitored lines
            self.monitored_lines = new_lines
            self.last_strategy_run = datetime.now(timezone.utc)
            
            print(f"✅ Strategy complete: {total_profitable_lines} profitable lines identified")
            
        except Exception as e:
            print(f"❌ Error running main strategy: {e}")
    
    async def _monitor_existing_positions(self):
        """
        Step 2: Monitor existing positions for fills and status changes
        
        For each line we're tracking, check ProphetX wager histories to see:
        - If any bets got filled (matched)
        - Current total position size
        - Whether wait periods have expired
        """
        print("\\n2️⃣ MONITORING EXISTING POSITIONS")
        print("-" * 30)
        
        if not self.monitored_lines:
            print("⚠️  No lines to monitor")
            return
        
        print(f"🔍 Checking {len(self.monitored_lines)} lines for fills...")
        
        # Check each line for position changes
        fills_detected = 0
        
        for line_id, strategy in self.monitored_lines.items():
            try:
                # Get current position from ProphetX
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(line_id)
                
                if not position_result["success"]:
                    continue
                
                summary = position_result["position_summary"]
                
                # Check for new fills
                if summary["recent_fills"]:
                    fills_detected += len(summary["recent_fills"])
                    
                    print(f"🎉 FILLS DETECTED: {strategy.selection_name} ({line_id[-8:]})")
                    print(f"   Total matched: ${summary['total_matched']:.2f}")
                    print(f"   Total position: ${summary['total_stake']:.2f}")
                    
                    # The 5-minute wait period is automatically handled by the position service
                
                # Log current status
                self._log_line_status(line_id, strategy, summary)
                
            except Exception as e:
                print(f"❌ Error monitoring line {line_id}: {e}")
        
        if fills_detected > 0:
            print(f"\\n🎉 Total fills detected this cycle: {fills_detected}")
        else:
            print("📊 No new fills detected")
    
    async def _place_new_bets(self):
        """
        Step 3: Place new bets where appropriate
        
        For each profitable line:
        - If no position exists → place initial bet
        - If position exists and wait period over → place incremental bet
        - Respect 4x position limits
        """
        print("\\n3️⃣ PLACING NEW BETS")
        print("-" * 30)
        
        if not self.monitored_lines:
            print("⚠️  No lines to place bets on")
            return
        
        bets_to_place = []
        
        # Analyze each line
        for line_id, strategy in self.monitored_lines.items():
            try:
                # Get current position
                position_result = await self.prophetx_wager_service.get_all_wagers_for_line(line_id)
                
                if not position_result["success"]:
                    # No position data - place initial bet
                    bet_amount = strategy.recommended_initial_stake
                    bet_reason = "Initial bet (no position data)"
                    
                elif position_result["position_summary"]["total_bets"] == 0:
                    # No bets placed yet - place initial bet
                    bet_amount = strategy.recommended_initial_stake
                    bet_reason = "Initial bet (first bet on line)"
                    
                else:
                    # Check if we can place incremental bet
                    summary = position_result["position_summary"]
                    current_stake = summary["total_stake"]
                    
                    # Check position limit (4x initial)
                    if current_stake >= strategy.max_position:
                        continue  # At max position
                    
                    # Check wait period (5 minutes after last fill)
                    if summary["last_fill_time"]:
                        try:
                            last_fill = datetime.fromisoformat(summary["last_fill_time"].replace('Z', '+00:00'))
                            wait_until = last_fill + timedelta(seconds=self.fill_wait_period_seconds)
                            
                            if datetime.now(timezone.utc) < wait_until:
                                # Still in wait period
                                continue
                        except:
                            pass
                    
                    # Calculate incremental bet amount
                    remaining_capacity = strategy.max_position - current_stake
                    bet_amount = min(strategy.increment_size, remaining_capacity)
                    bet_reason = f"Incremental bet (position: ${current_stake:.2f})"
                
                if bet_amount > 0:
                    bets_to_place.append({
                        "line_id": line_id,
                        "strategy": strategy,
                        "amount": bet_amount,
                        "reason": bet_reason
                    })
            
            except Exception as e:
                print(f"❌ Error analyzing line {line_id}: {e}")
        
        # Place the bets
        print(f"🎯 {len(bets_to_place)} bets ready to place")
        
        successful_bets = 0
        for bet_info in bets_to_place:
            success = await self._place_single_bet(bet_info)
            if success:
                successful_bets += 1
        
        print(f"✅ Successfully placed {successful_bets}/{len(bets_to_place)} bets")
    
    async def _place_single_bet(self, bet_info: Dict[str, Any]) -> bool:
        """Place a single bet on ProphetX"""
        try:
            strategy = bet_info["strategy"]
            amount = bet_info["amount"]
            
            print(f"   🎯 Placing: {strategy.selection_name} {strategy.odds:+d} for ${amount:.2f}")
            print(f"      Reason: {bet_info['reason']}")
            
            # Import ProphetX service
            from app.services.prophetx_service import prophetx_service
            
            # Generate external ID
            external_id = f"line_{strategy.line_id}_{int(time.time())}"
            
            # Place the bet
            result = await prophetx_service.place_bet(
                line_id=strategy.line_id,
                odds=strategy.odds,
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
    
    def _log_line_status(self, line_id: str, strategy: LineStrategy, summary: Dict[str, Any]):
        """Log current status of a line"""
        total_stake = summary.get("total_stake", 0)
        total_matched = summary.get("total_matched", 0)
        has_active = summary.get("has_active_bets", False)
        
        utilization = (total_stake / strategy.max_position) * 100 if strategy.max_position > 0 else 0
        
        status_parts = []
        if has_active:
            unmatched = total_stake - total_matched
            status_parts.append(f"${unmatched:.0f} active")
        if total_matched > 0:
            status_parts.append(f"${total_matched:.0f} matched")
        
        status_str = ", ".join(status_parts) if status_parts else "no bets"
        
        print(f"   📊 {strategy.selection_name[:20]:<20} ({line_id[-8:]}): "
              f"${total_stake:.0f}/${strategy.max_position:.0f} "
              f"({utilization:.0f}%) - {status_str}")
    
    def _log_cycle_summary(self, cycle_count: int, duration: float):
        """Log summary of monitoring cycle"""
        print(f"\\n📈 CYCLE #{cycle_count} COMPLETE")
        print(f"   Duration: {duration:.1f}s")
        print(f"   Lines monitored: {len(self.monitored_lines)}")
        print(f"   Next cycle in: {self.monitoring_interval_seconds}s")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current monitoring status"""
        return {
            "monitoring_active": self.monitoring_active,
            "lines_monitored": len(self.monitored_lines),
            "last_strategy_run": self.last_strategy_run.isoformat() if self.last_strategy_run else None,
            "last_monitoring_cycle": self.last_monitoring_cycle.isoformat() if self.last_monitoring_cycle else None,
            "monitoring_interval_seconds": self.monitoring_interval_seconds,
            "fill_wait_period_seconds": self.fill_wait_period_seconds
        }

# Global line monitoring service instance
line_monitoring_service = LineMonitoringService()