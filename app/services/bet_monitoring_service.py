#!/usr/bin/env python3
"""
Bet Monitoring Service
Monitors bet status and handles fills on ProphetX
"""

import asyncio
import time
from typing import Dict, List, Optional
from datetime import datetime, timezone

class BetMonitoringService:
    """Service for monitoring bet status and handling fills"""
    
    def __init__(self):
        self.monitoring_active = False
        self.last_status_check = 0
        self.status_check_interval = 60  # Check every 30 seconds
        
    async def start_monitoring(self):
        """Start continuous bet monitoring"""
        self.monitoring_active = True
        print("🔍 Starting bet status monitoring...")
        
        while self.monitoring_active:
            try:
                await self._check_all_bet_statuses()
                await asyncio.sleep(self.status_check_interval)
            except Exception as e:
                print(f"❌ Error in bet monitoring: {e}")
                await asyncio.sleep(10)  # Wait before retrying
    
    async def _check_all_bet_statuses(self):
        """Check status of all active bets"""
        from app.services.market_maker_service import market_maker_service
        from app.services.prophetx_service import prophetx_service
        
        active_bets = [bet for bet in market_maker_service.all_bets.values() 
                      if bet.is_active]
        
        if not active_bets:
            return
            
        print(f"🔍 Checking status of {len(active_bets)} active bets...")
        
        for bet in active_bets:
            try:
                # Get current bet status from ProphetX
                status = await self._get_bet_status_from_prophetx(bet.bet_id or bet.external_id)
                
                if status:
                    await self._process_bet_status_update(bet, status)
                    
            except Exception as e:
                print(f"❌ Error checking bet {bet.external_id}: {e}")
                continue
    
    async def _check_all_bet_statuses(self):
        """Check status of all active bets using bulk ProphetX API calls"""
        from app.services.market_maker_service import market_maker_service
        from app.services.prophetx_service import prophetx_service
        
        our_active_bets = [bet for bet in market_maker_service.all_bets.values() 
                          if bet.is_active]
        
        if not our_active_bets:
            return
            
        print(f"🔍 Checking status of {len(our_active_bets)} active bets...")
        
        try:
            # Get all active wagers from ProphetX
            prophetx_active_wagers = await prophetx_service.get_all_active_wagers()
            prophetx_matched_bets = await prophetx_service.get_matched_bets()
            
            # Create lookup maps by external_id for faster matching
            active_wagers_map = {}
            if prophetx_active_wagers:
                for wager in prophetx_active_wagers:
                    if isinstance(wager, dict):  # Safety check
                        external_id = wager.get('external_id')
                        if external_id:
                            active_wagers_map[external_id] = wager
            
            matched_bets_map = {}
            if prophetx_matched_bets:
                for bet in prophetx_matched_bets:
                    if isinstance(bet, dict):  # Safety check
                        external_id = bet.get('external_id')
                        if external_id:
                            matched_bets_map[external_id] = bet
            
            print(f"   📊 Active wagers map: {len(active_wagers_map)} entries")
            print(f"   🎯 Matched bets map: {len(matched_bets_map)} entries")
            
            # Check each of our bets against ProphetX data
            bets_found_active = 0
            bets_found_matched = 0
            bets_not_found = 0
            
            for our_bet in our_active_bets:
                try:
                    result = await self._update_bet_status(our_bet, active_wagers_map, matched_bets_map)
                    if result == "active":
                        bets_found_active += 1
                    elif result == "matched":
                        bets_found_matched += 1
                    else:
                        bets_not_found += 1
                except Exception as e:
                    print(f"   ❌ Error updating bet {our_bet.external_id}: {e}")
                    bets_not_found += 1
            
            print(f"   📊 Status summary: {bets_found_active} still active, {bets_found_matched} matched, {bets_not_found} not found")
                
        except Exception as e:
            print(f"❌ Error in bulk bet status check: {e}")
            import traceback
            traceback.print_exc()

    async def _check_all_bet_statuses(self):
        """Check status of all active bets using bulk ProphetX API calls"""
        from app.services.market_maker_service import market_maker_service
        from app.services.prophetx_service import prophetx_service
        
        our_active_bets = [bet for bet in market_maker_service.all_bets.values() 
                          if bet.is_active]
        
        if not our_active_bets:
            return
            
        print(f"🔍 Checking status of {len(our_active_bets)} active bets...")
        
        try:
            # Get all active wagers from ProphetX
            prophetx_active_wagers = await prophetx_service.get_all_active_wagers()
            prophetx_matched_bets = await prophetx_service.get_matched_bets()
            
            # Create lookup maps by external_id for faster matching
            active_wagers_map = {}
            if prophetx_active_wagers:
                for wager in prophetx_active_wagers:
                    if isinstance(wager, dict):  # Safety check
                        external_id = wager.get('external_id')
                        if external_id:
                            active_wagers_map[external_id] = wager
            
            # For matched bets, try multiple ID fields since we're not sure of the structure
            matched_bets_map = {}
            matched_bets_by_prophetx_id = {}
            
            if prophetx_matched_bets:
                for bet in prophetx_matched_bets:
                    if isinstance(bet, dict):  # Safety check
                        # Try external_id first
                        external_id = bet.get('external_id')
                        if external_id:
                            matched_bets_map[external_id] = bet
                        
                        # Also index by ProphetX bet ID for fallback matching
                        prophetx_bet_id = bet.get('id') or bet.get('wager_id') or bet.get('bet_id')
                        if prophetx_bet_id:
                            matched_bets_by_prophetx_id[str(prophetx_bet_id)] = bet
            
            print(f"   📊 Active wagers map: {len(active_wagers_map)} entries")
            print(f"   🎯 Matched bets map: {len(matched_bets_map)} entries (by external_id)")
            print(f"   🆔 Matched bets by ProphetX ID: {len(matched_bets_by_prophetx_id)} entries")
            
            # Check each of our bets against ProphetX data
            bets_found_active = 0
            bets_found_matched = 0
            bets_not_found = 0
            
            for our_bet in our_active_bets:
                try:
                    result = await self._update_bet_status(
                        our_bet, active_wagers_map, matched_bets_map, matched_bets_by_prophetx_id
                    )
                    if result == "active":
                        bets_found_active += 1
                    elif result == "matched":
                        bets_found_matched += 1
                    else:
                        bets_not_found += 1
                except Exception as e:
                    print(f"   ❌ Error updating bet {our_bet.external_id}: {e}")
                    bets_not_found += 1
            
            print(f"   📊 Status summary: {bets_found_active} still active, {bets_found_matched} matched, {bets_not_found} not found")
                
        except Exception as e:
            print(f"❌ Error in bulk bet status check: {e}")
            import traceback
            traceback.print_exc()

    async def _update_bet_status(self, our_bet, active_wagers_map, matched_bets_map, matched_bets_by_prophetx_id):
        """Update status of a single bet based on ProphetX data with enhanced matching"""
        external_id = our_bet.external_id
        
        # Check if bet is still active (unmatched) on ProphetX
        if external_id in active_wagers_map:
            prophetx_wager = active_wagers_map[external_id]
            
            # Update our bet with ProphetX data
            prophetx_bet_id = prophetx_wager.get('id')
            if prophetx_bet_id and not our_bet.bet_id:
                our_bet.bet_id = str(prophetx_bet_id)
            
            # Bet is still active - no status change needed
            # print(f"   ✅ {our_bet.selection_name}: Still active on ProphetX")
            return "active"
            
        # Check if bet has been matched by external_id
        elif external_id in matched_bets_map:
            matched_bet = matched_bets_map[external_id]
            print(f"🎉 FOUND MATCHED BET (by external_id): {our_bet.selection_name}")
            return await self._process_matched_bet(our_bet, matched_bet)
            
        # Check if bet has been matched by ProphetX ID (fallback)
        elif our_bet.bet_id and our_bet.bet_id in matched_bets_by_prophetx_id:
            matched_bet = matched_bets_by_prophetx_id[our_bet.bet_id]
            print(f"🎉 FOUND MATCHED BET (by ProphetX ID): {our_bet.selection_name}")
            return await self._process_matched_bet(our_bet, matched_bet)
        
        else:
            # Bet not found in active or matched - investigate further
            print(f"❓ {our_bet.selection_name}: Not found in ProphetX active or matched bets")
            
            # Try to get specific bet details if we have a ProphetX bet ID
            if our_bet.bet_id:
                try:
                    from app.services.prophetx_service import prophetx_service
                    bet_details = await prophetx_service.get_wager_by_id(our_bet.bet_id)
                    if bet_details:
                        status = bet_details.get('status', 'unknown').lower()
                        matching_status = bet_details.get('matching_status', 'unknown').lower()
                        
                        print(f"   🔍 Bet details: status={status}, matching_status={matching_status}")
                        
                        # Check if it's matched but not in our matched bets list
                        if matching_status in ['fully_matched', 'partially_matched']:
                            print(f"🎉 FOUND MATCHED BET (by individual lookup): {our_bet.selection_name}")
                            return await self._process_matched_bet(our_bet, bet_details)
                        
                        # Check if it's cancelled/expired/etc
                        if status in ['cancelled', 'expired', 'rejected', 'void']:
                            our_bet.status = status
                            our_bet.unmatched_stake = 0.0
                            print(f"   ❌ Bet {status}: {our_bet.selection_name}")
                            return status
                            
                    else:
                        print(f"   ⚠️  Bet details not found (404) - likely matched and settled")
                        # If bet returns 404, it might be matched and already settled
                        # Mark as matched with full amount
                        return await self._handle_missing_matched_bet(our_bet)
                        
                except Exception as e:
                    print(f"   ⚠️  Error getting bet details for {our_bet.bet_id}: {e}")
            
            # If we can't find the bet anywhere, assume it's still pending but not yet visible
            print(f"   ⏳ Bet status unclear - keeping as active for now")
            return "not_found"
    
    async def _process_matched_bet(self, our_bet, matched_bet_data):
        """Process a matched bet and update our records"""
        try:
            # Extract match information with multiple possible field names
            matched_amount = None
            
            # Try different field names for the matched amount
            for field in ['stake', 'matched_stake', 'matched_amount', 'amount']:
                if field in matched_bet_data:
                    matched_amount = float(matched_bet_data[field])
                    break
            
            if matched_amount is None:
                print(f"   ❌ Could not determine matched amount from: {list(matched_bet_data.keys())}")
                return "error"
            
            original_stake = our_bet.stake
            
            if matched_amount > 0:
                print(f"🎉 BET FILLED: {our_bet.selection_name} - ${matched_amount:.2f} matched!")
                
                # Update bet status
                our_bet.matched_stake = matched_amount
                our_bet.unmatched_stake = max(0, original_stake - matched_amount)
                our_bet.updated_at = datetime.now(timezone.utc)
                
                if matched_amount >= original_stake:
                    our_bet.status = "matched"  # Fully matched
                else:
                    our_bet.status = "partially_matched"  # Partially matched
                
                # Record fill for incremental betting
                from app.services.market_maker_service import market_maker_service
                market_maker_service.position_tracker.record_fill(
                    our_bet.line_id, matched_amount, matched_amount
                )
                
                # Start wait period
                from app.services.market_making_strategy import market_making_strategy
                market_making_strategy.betting_manager.record_fill(
                    our_bet.line_id, matched_amount, matched_amount
                )
                
                print(f"   📊 Fill details:")
                print(f"      Line: {our_bet.line_id}")
                print(f"      Odds: {our_bet.odds:+d}")
                print(f"      Matched: ${matched_amount:.2f}")
                print(f"      Remaining: ${our_bet.unmatched_stake:.2f}")
                print(f"      ⏱️  Starting 5-minute wait period for incremental liquidity")
                
                return "matched"
                
        except (ValueError, TypeError) as e:
            print(f"   ❌ Error processing matched bet data: {e}")
            print(f"   📊 Matched bet data: {matched_bet_data}")
            return "error"
    
    async def _handle_missing_matched_bet(self, our_bet):
        """Handle case where bet is missing (likely matched and settled)"""
        print(f"   💡 Assuming bet was fully matched (common when bet settles quickly)")
        
        # Assume full match
        matched_amount = our_bet.stake
        
        # Update bet status
        our_bet.matched_stake = matched_amount
        our_bet.unmatched_stake = 0.0
        our_bet.status = "matched"
        our_bet.updated_at = datetime.now(timezone.utc)
        
        # Record fill for incremental betting
        from app.services.market_maker_service import market_maker_service
        market_maker_service.position_tracker.record_fill(
            our_bet.line_id, matched_amount, matched_amount
        )
        
        # Start wait period
        from app.services.market_making_strategy import market_making_strategy
        market_making_strategy.betting_manager.record_fill(
            our_bet.line_id, matched_amount, matched_amount
        )
        
        print(f"   📊 Assumed fill details:")
        print(f"      Line: {our_bet.line_id}")
        print(f"      Odds: {our_bet.odds:+d}")
        print(f"      Assumed matched: ${matched_amount:.2f}")
        print(f"      ⏱️  Starting 5-minute wait period for incremental liquidity")
        
        return "matched"
    
    async def _process_bet_status_update(self, bet, status_data):
        """Process bet status update and handle fills"""
        from app.services.market_maker_service import market_maker_service
        
        # Extract relevant information from ProphetX response
        # This structure depends on actual ProphetX API response format
        new_matched_amount = status_data.get('matched_amount', 0)
        bet_status = status_data.get('status', 'unknown')
        
        # Check if there's a new fill
        previous_matched = bet.matched_stake
        new_fill_amount = new_matched_amount - previous_matched
        
        if new_fill_amount > 0:
            print(f"🎉 BET FILLED: {bet.selection_name} - ${new_fill_amount:.2f} matched!")
            
            # Update bet object
            bet.matched_stake = new_matched_amount
            bet.unmatched_stake = bet.stake - new_matched_amount
            bet.updated_at = datetime.now(timezone.utc)
            
            # Update status based on fill
            if new_matched_amount >= bet.stake:
                bet.status = "matched"  # Fully matched
            else:
                bet.status = "partially_matched"
            
            # Record fill in position tracker
            market_maker_service.position_tracker.record_fill(
                bet.line_id, new_fill_amount, new_matched_amount
            )
            
            # Log fill details
            print(f"   Line: {bet.line_id}")
            print(f"   Selection: {bet.selection_name}")
            print(f"   Odds: {bet.odds:+d}")
            print(f"   Fill amount: ${new_fill_amount:.2f}")
            print(f"   Total matched: ${new_matched_amount:.2f}")
            print(f"   Still unmatched: ${bet.unmatched_stake:.2f}")
            
            # Trigger 5-minute wait period for incremental betting
            from app.services.market_making_strategy import market_making_strategy
            market_making_strategy.betting_manager.record_fill(
                bet.line_id, new_fill_amount, new_matched_amount
            )
            
        # Handle other status changes
        elif bet_status == 'cancelled':
            bet.status = "cancelled"
            bet.unmatched_stake = 0.0
            print(f"❌ Bet cancelled: {bet.external_id}")
            
        elif bet_status == 'expired':
            bet.status = "expired" 
            bet.unmatched_stake = 0.0
            print(f"⏰ Bet expired: {bet.external_id}")
    
    def stop_monitoring(self):
        """Stop bet monitoring"""
        self.monitoring_active = False
        print("🛑 Bet monitoring stopped")

# Global bet monitoring service instance
bet_monitoring_service = BetMonitoringService()