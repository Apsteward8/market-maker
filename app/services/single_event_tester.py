#!/usr/bin/env python3
"""
Single Event Market Making Tester
Test monitoring/updating/refilling logic for a single event
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class SingleEventSession:
    """Track a single event testing session"""
    event_id: str
    event_name: str
    odds_api_event_id: str
    prophetx_event_id: int
    start_time: datetime
    initial_bets_placed: int
    total_fills: int
    total_incremental_bets: int
    odds_updates: int
    is_active: bool

class SingleEventTester:
    """Test market making workflow for a single event"""
    
    def __init__(self):
        self.session: Optional[SingleEventSession] = None
        self.monitoring_active = False
        self.placed_bets: Dict[str, Dict] = {}  # external_id -> bet info
        self.last_odds_check = {}  # Store last odds for comparison
        
    async def start_single_event_test(self, odds_api_event_id: str) -> Dict[str, any]:
        """
        Start testing market making for a single event
        
        Args:
            odds_api_event_id: Event ID from The Odds API
            
        Returns:
            Test session info
        """
        if self.session and self.session.is_active:
            return {
                "success": False,
                "message": "Test already running",
                "current_session": self.session
            }
        
        print(f"🧪 Starting Single Event Test for {odds_api_event_id}")
        
        try:
            # Step 1: Get the event and its match
            matching_attempts = await event_matching_service.find_matches_for_events([odds_event])
            event_match = matching_attempts[0].best_match if matching_attempts and matching_attempts[0].best_match else None
            if not event_match:
                return {
                    "success": False,
                    "message": f"Could not find or match event {odds_api_event_id}"
                }
            
            # Step 2: Create session
            self.session = SingleEventSession(
                event_id=odds_api_event_id,
                event_name=event_match.odds_api_event.display_name,
                odds_api_event_id=odds_api_event_id,
                prophetx_event_id=event_match.prophetx_event.event_id,
                start_time=datetime.now(timezone.utc),
                initial_bets_placed=0,
                total_fills=0,
                total_incremental_bets=0,
                odds_updates=0,
                is_active=True
            )
            
            print(f"✅ Created test session for: {self.session.event_name}")
            
            # Step 3: Place initial bets
            initial_bets = await self._place_initial_bets(event_match)
            self.session.initial_bets_placed = initial_bets
            
            if initial_bets == 0:
                return {
                    "success": False,
                    "message": "No initial bets could be placed"
                }
            
            # Step 4: Start monitoring tasks
            self.monitoring_active = True
            
            # Start monitoring tasks in background
            bet_monitoring_task = asyncio.create_task(self._monitor_bet_fills())
            odds_monitoring_task = asyncio.create_task(self._monitor_odds_changes())
            
            print(f"🚀 Test session started with {initial_bets} initial bets")
            print(f"📊 Monitoring bet fills and odds changes...")
            
            return {
                "success": True,
                "message": f"Single event test started for {self.session.event_name}",
                "session": self.session,
                "initial_bets_placed": initial_bets,
                "monitoring_tasks": ["bet_fills", "odds_changes"]
            }
            
        except Exception as e:
            print(f"❌ Error starting single event test: {e}")
            return {
                "success": False,
                "message": f"Error starting test: {str(e)}"
            }
    
    async def _get_event_match(self, odds_api_event_id: str):
        """Get the event match for testing"""
        from app.services.event_matching_service import event_matching_service
        
        # Get confirmed matches
        confirmed_matches = await event_matching_service.get_matched_events()
        
        # Find our target event
        for match in confirmed_matches:
            if match.odds_api_event.event_id == odds_api_event_id:
                return match
        
        return None
    
    async def _place_initial_bets(self, event_match) -> int:
        """Place initial bets using existing strategy"""
        from app.services.market_matching_service import market_matching_service
        from app.services.market_making_strategy import market_making_strategy
        
        print(f"💰 Placing initial bets for {event_match.odds_api_event.display_name}")
        
        try:
            # Get market matching
            market_match_result = await market_matching_service.match_event_markets(event_match)
            
            if not market_match_result.ready_for_trading:
                print(f"❌ Event not ready for trading: {market_match_result.issues}")
                return 0
            
            # Create strategy
            plan = market_making_strategy.create_market_making_plan(event_match, market_match_result)
            
            if not plan or not plan.is_profitable:
                print(f"❌ No profitable strategy found")
                return 0
            
            print(f"✅ Created profitable strategy with {len(plan.betting_instructions)} instructions")
            
            # Place each bet
            bets_placed = 0
            for instruction in plan.betting_instructions:
                success = await self._place_single_bet(instruction, event_match)
                if success:
                    bets_placed += 1
                    print(f"   ✅ Placed: {instruction.selection_name} {instruction.odds:+d} ${instruction.stake:.2f}")
                else:
                    print(f"   ❌ Failed: {instruction.selection_name}")
            
            return bets_placed
            
        except Exception as e:
            print(f"❌ Error placing initial bets: {e}")
            return 0
    
    async def _place_single_bet(self, instruction, event_match) -> bool:
        """Place a single bet and track it"""
        from app.services.prophetx_service import prophetx_service
        
        try:
            external_id = f"test_{self.session.prophetx_event_id}_{instruction.line_id}_{int(time.time())}"
            
            # Place bet on ProphetX
            result = await prophetx_service.place_bet(
                line_id=instruction.line_id,
                odds=instruction.odds,
                stake=instruction.stake,
                external_id=external_id
            )
            
            if result["success"]:
                # Track this bet
                self.placed_bets[external_id] = {
                    "external_id": external_id,
                    "prophetx_bet_id": result.get("bet_id"),
                    "line_id": instruction.line_id,
                    "selection_name": instruction.selection_name,
                    "odds": instruction.odds,
                    "stake": instruction.stake,
                    "status": "placed",
                    "placed_at": datetime.now(timezone.utc),
                    "matched_amount": 0.0,
                    "unmatched_amount": instruction.stake,
                    "fills": [],
                    "in_wait_period": False,
                    "wait_period_ends": None,
                    "total_position": instruction.stake,
                    "max_position": instruction.max_position,
                    "increment_size": instruction.increment_size
                }
                
                return True
            else:
                print(f"      ❌ ProphetX error: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            print(f"      ❌ Exception placing bet: {e}")
            return False
    
    async def _monitor_bet_fills(self):
        """Monitor our bets for fills and handle wait periods"""
        print(f"🔍 Starting bet fill monitoring for {self.session.event_name}")
        
        while self.monitoring_active:
            try:
                print(f"\n🔍 Checking bet fills ({datetime.now().strftime('%H:%M:%S')})")
                
                # Check each of our bets
                for external_id, bet_info in self.placed_bets.items():
                    if bet_info["status"] in ["cancelled", "expired"]:
                        continue
                    
                    # Check if this bet has been filled
                    fill_detected = await self._check_single_bet_fill(bet_info)
                    
                    if fill_detected:
                        self.session.total_fills += 1
                        print(f"🎉 FILL DETECTED: {bet_info['selection_name']} - ${fill_detected:.2f}")
                        
                        # Start 5-minute wait period
                        await self._start_wait_period(bet_info)
                    
                    # Check if wait period is over and we can add incremental liquidity
                    elif self._can_add_incremental_liquidity(bet_info):
                        incremental_added = await self._add_incremental_liquidity(bet_info)
                        if incremental_added:
                            self.session.total_incremental_bets += 1
                
                # Summary
                active_bets = sum(1 for bet in self.placed_bets.values() if bet["status"] == "placed")
                filled_bets = sum(1 for bet in self.placed_bets.values() if bet["matched_amount"] > 0)
                in_wait = sum(1 for bet in self.placed_bets.values() if bet["in_wait_period"])
                
                print(f"📊 Bet Status: {active_bets} active, {filled_bets} filled, {in_wait} in wait period")

                await asyncio.sleep(60)  # Check every 60 seconds

            except Exception as e:
                print(f"❌ Error in bet monitoring: {e}")
                await asyncio.sleep(60)
    
    async def _check_single_bet_fill(self, bet_info) -> Optional[float]:
        """Check if a single bet has been filled"""
        from app.services.prophetx_service import prophetx_service
        
        try:
            # Get current bet status from ProphetX
            if bet_info["prophetx_bet_id"]:
                bet_details = await prophetx_service.get_wager_by_id(bet_info["prophetx_bet_id"])
                
                if bet_details:
                    # Check matching status
                    matching_status = bet_details.get('matching_status', 'unknown').lower()
                    
                    if matching_status in ['fully_matched', 'partially_matched']:
                        # Try to extract matched amount
                        for field in ['stake', 'matched_stake', 'matched_amount', 'amount']:
                            if field in bet_details:
                                try:
                                    matched_amount = float(bet_details[field])
                                    previous_matched = bet_info["matched_amount"]
                                    
                                    if matched_amount > previous_matched:
                                        # New fill detected
                                        fill_amount = matched_amount - previous_matched
                                        
                                        # Update bet info
                                        bet_info["matched_amount"] = matched_amount
                                        bet_info["unmatched_amount"] = bet_info["stake"] - matched_amount
                                        bet_info["status"] = "matched" if matched_amount >= bet_info["stake"] else "partially_matched"
                                        
                                        # Record fill
                                        bet_info["fills"].append({
                                            "amount": fill_amount,
                                            "timestamp": datetime.now(timezone.utc),
                                            "total_matched": matched_amount
                                        })
                                        
                                        return fill_amount
                                except (ValueError, TypeError):
                                    continue
                
                elif bet_details is None:
                    # Bet not found - likely filled and settled
                    if bet_info["matched_amount"] == 0:
                        # Assume full fill
                        fill_amount = bet_info["stake"]
                        bet_info["matched_amount"] = fill_amount
                        bet_info["unmatched_amount"] = 0
                        bet_info["status"] = "matched"
                        
                        bet_info["fills"].append({
                            "amount": fill_amount,
                            "timestamp": datetime.now(timezone.utc),
                            "total_matched": fill_amount,
                            "note": "Assumed full fill (bet not found in API)"
                        })
                        
                        return fill_amount
        
        except Exception as e:
            print(f"   ❌ Error checking fill for {bet_info['selection_name']}: {e}")
        
        return None
    
    async def _start_wait_period(self, bet_info):
        """Start 5-minute wait period after a fill"""
        bet_info["in_wait_period"] = True
        bet_info["wait_period_ends"] = datetime.now(timezone.utc) + timedelta(minutes=5)
        
        print(f"⏱️  Started 5-minute wait period for {bet_info['selection_name']}")
        print(f"   Wait ends at: {bet_info['wait_period_ends'].strftime('%H:%M:%S')}")
    
    def _can_add_incremental_liquidity(self, bet_info) -> bool:
        """Check if we can add incremental liquidity to this bet"""
        # Check if wait period is over
        if bet_info["in_wait_period"]:
            if datetime.now(timezone.utc) >= bet_info["wait_period_ends"]:
                bet_info["in_wait_period"] = False
                print(f"✅ Wait period ended for {bet_info['selection_name']}")
            else:
                return False
        
        # Check if we're under max position
        if bet_info["total_position"] < bet_info["max_position"]:
            return True
        
        return False
    
    async def _add_incremental_liquidity(self, bet_info) -> bool:
        """Add incremental liquidity to a line"""
        try:
            # Calculate increment amount
            remaining_capacity = bet_info["max_position"] - bet_info["total_position"]
            increment_amount = min(bet_info["increment_size"], remaining_capacity)
            
            if increment_amount <= 0:
                return False
            
            print(f"📈 Adding ${increment_amount:.2f} incremental liquidity to {bet_info['selection_name']}")
            print(f"   Current position: ${bet_info['total_position']:.2f}")
            print(f"   Max position: ${bet_info['max_position']:.2f}")
            
            # Place incremental bet
            from app.services.prophetx_service import prophetx_service
            
            external_id = f"incr_{self.session.prophetx_event_id}_{bet_info['line_id']}_{int(time.time())}"
            
            result = await prophetx_service.place_bet(
                line_id=bet_info["line_id"],
                odds=bet_info["odds"],
                stake=increment_amount,
                external_id=external_id
            )
            
            if result["success"]:
                # Track incremental bet
                self.placed_bets[external_id] = {
                    "external_id": external_id,
                    "prophetx_bet_id": result.get("bet_id"),
                    "line_id": bet_info["line_id"],
                    "selection_name": bet_info["selection_name"],
                    "odds": bet_info["odds"],
                    "stake": increment_amount,
                    "status": "placed",
                    "placed_at": datetime.now(timezone.utc),
                    "matched_amount": 0.0,
                    "unmatched_amount": increment_amount,
                    "fills": [],
                    "in_wait_period": False,
                    "wait_period_ends": None,
                    "total_position": bet_info["total_position"] + increment_amount,
                    "max_position": bet_info["max_position"],
                    "increment_size": bet_info["increment_size"],
                    "is_incremental": True,
                    "parent_bet": bet_info["external_id"]
                }
                
                # Update original bet's total position
                bet_info["total_position"] += increment_amount
                
                print(f"✅ Added ${increment_amount:.2f} incremental liquidity")
                return True
            else:
                print(f"❌ Failed to place incremental bet: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            print(f"❌ Error adding incremental liquidity: {e}")
            return False
    
    async def _monitor_odds_changes(self):
        """Monitor odds changes every 60 seconds"""
        print(f"📊 Starting odds change monitoring for {self.session.event_name}")
        
        while self.monitoring_active:
            try:
                print(f"\n📊 Checking odds changes ({datetime.now().strftime('%H:%M:%S')})")
                
                # Get current odds
                current_odds = await self._get_current_odds()
                
                if current_odds:
                    # Compare with last odds
                    changes = self._detect_odds_changes(current_odds)
                    
                    if changes:
                        print(f"📈 Detected {len(changes)} odds changes")
                        await self._handle_odds_changes(changes)
                        self.session.odds_updates += 1
                    else:
                        print("✅ No significant odds changes")
                    
                    # Store current odds for next comparison
                    self.last_odds_check = current_odds
                
                await asyncio.sleep(60)  # Check every 60 seconds
                
            except Exception as e:
                print(f"❌ Error in odds monitoring: {e}")
                await asyncio.sleep(60)
    
    async def _get_current_odds(self) -> Optional[Dict]:
        """Get current odds for our event"""
        from app.services.odds_api_service import odds_api_service
        
        try:
            # Get all events from Odds API
            events = await odds_api_service.get_events()
            
            # Find our event
            for event in events:
                if event.event_id == self.session.odds_api_event_id:
                    return {
                        "moneyline": {outcome.name: outcome.american_odds for outcome in event.moneyline.outcomes} if event.moneyline else {},
                        "spreads": {f"{outcome.name}_{outcome.point}": outcome.american_odds for outcome in event.spreads.outcomes} if event.spreads else {},
                        "totals": {f"{outcome.name}_{outcome.point}": outcome.american_odds for outcome in event.totals.outcomes} if event.totals else {}
                    }
            
            return None
            
        except Exception as e:
            print(f"❌ Error getting current odds: {e}")
            return None
    
    def _detect_odds_changes(self, current_odds: Dict) -> List[Dict]:
        """Detect significant odds changes"""
        changes = []
        
        if not self.last_odds_check:
            return changes
        
        # Check each market type
        for market_type, current_market in current_odds.items():
            if market_type not in self.last_odds_check:
                continue
            
            last_market = self.last_odds_check[market_type]
            
            # Check each outcome
            for outcome_name, current_odds_value in current_market.items():
                if outcome_name not in last_market:
                    continue
                
                last_odds_value = last_market[outcome_name]
                change_amount = current_odds_value - last_odds_value
                
                # Check if change is significant (5+ points)
                if abs(change_amount) >= 5:
                    changes.append({
                        "market_type": market_type,
                        "outcome_name": outcome_name,
                        "old_odds": last_odds_value,
                        "new_odds": current_odds_value,
                        "change_amount": change_amount
                    })
        
        return changes
    
    async def _handle_odds_changes(self, changes: List[Dict]):
        """Handle odds changes by updating our bets"""
        print(f"🔄 Handling {len(changes)} odds changes")
        
        for change in changes:
            print(f"   📊 {change['outcome_name']}: {change['old_odds']:+d} → {change['new_odds']:+d} ({change['change_amount']:+d})")
            
            # Find bets affected by this change
            affected_bets = self._find_affected_bets(change)
            
            for bet_info in affected_bets:
                await self._update_bet_for_odds_change(bet_info, change)
    
    def _find_affected_bets(self, change: Dict) -> List[Dict]:
        """Find bets affected by an odds change"""
        affected = []
        
        # This is simplified - you'd need to map outcomes to selection names
        # For now, we'll assume all active bets are affected
        for bet_info in self.placed_bets.values():
            if bet_info["status"] in ["placed", "partially_matched"]:
                affected.append(bet_info)
        
        return affected
    
    async def _update_bet_for_odds_change(self, bet_info: Dict, change: Dict):
        """Update a bet due to odds change"""
        from app.services.prophetx_service import prophetx_service
        
        try:
            print(f"   🔄 Updating bet for {bet_info['selection_name']}")
            
            # Cancel existing bet
            if bet_info["prophetx_bet_id"]:
                cancel_result = await prophetx_service.cancel_wager(bet_info["prophetx_bet_id"])
                
                if cancel_result.get("success", False):
                    bet_info["status"] = "cancelled"
                    bet_info["unmatched_amount"] = 0
                    print(f"      ❌ Cancelled old bet")
                    
                    # Clear wait period
                    bet_info["in_wait_period"] = False
                    
                    # Place new bet with updated odds
                    # This is simplified - you'd need to recalculate the correct odds
                    new_odds = change["new_odds"]  # This is not correct - just for demo
                    
                    external_id = f"update_{self.session.prophetx_event_id}_{bet_info['line_id']}_{int(time.time())}"
                    
                    result = await prophetx_service.place_bet(
                        line_id=bet_info["line_id"],
                        odds=new_odds,
                        stake=bet_info["stake"],
                        external_id=external_id
                    )
                    
                    if result["success"]:
                        print(f"      ✅ Placed updated bet with new odds")
                        # Update bet info...
                    else:
                        print(f"      ❌ Failed to place updated bet")
                else:
                    print(f"      ❌ Failed to cancel old bet")
        
        except Exception as e:
            print(f"   ❌ Error updating bet: {e}")
    
    async def stop_test(self) -> Dict[str, any]:
        """Stop the single event test"""
        if not self.session:
            return {"success": False, "message": "No active test session"}
        
        print(f"🛑 Stopping single event test for {self.session.event_name}")
        
        self.monitoring_active = False
        self.session.is_active = False
        
        # Generate final report
        report = {
            "session_duration": (datetime.now(timezone.utc) - self.session.start_time).total_seconds() / 60,
            "initial_bets_placed": self.session.initial_bets_placed,
            "total_fills": self.session.total_fills,
            "total_incremental_bets": self.session.total_incremental_bets,
            "odds_updates": self.session.odds_updates,
            "final_bet_count": len(self.placed_bets),
            "bet_details": self.placed_bets
        }
        
        return {
            "success": True,
            "message": f"Test completed for {self.session.event_name}",
            "report": report
        }
    
    def get_test_status(self) -> Dict[str, any]:
        """Get current test status"""
        if not self.session:
            return {"active": False, "message": "No active test session"}
        
        return {
            "active": self.session.is_active,
            "session": self.session,
            "placed_bets": len(self.placed_bets),
            "active_bets": sum(1 for bet in self.placed_bets.values() if bet["status"] == "placed"),
            "filled_bets": sum(1 for bet in self.placed_bets.values() if bet["matched_amount"] > 0),
            "in_wait_period": sum(1 for bet in self.placed_bets.values() if bet["in_wait_period"]),
            "bet_details": self.placed_bets
        }

# Global single event tester
single_event_tester = SingleEventTester()