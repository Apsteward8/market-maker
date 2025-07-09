#!/usr/bin/env python3
"""
Odds Change Detection and Handling
Monitors Pinnacle odds changes and updates ProphetX bets accordingly
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

@dataclass
class OddsChange:
    """Represents a significant odds change"""
    event_id: str
    market_type: str
    outcome_name: str
    old_odds: int
    new_odds: int
    change_amount: int
    timestamp: datetime

class OddsChangeHandler:
    """Handles odds changes and bet updates"""
    
    def __init__(self, significant_change_threshold: int = 5):
        self.change_threshold = significant_change_threshold  # 5 point minimum change
        self.odds_history: Dict[str, Dict] = {}  # event_id -> market data
        
    async def process_odds_update(self, events_with_new_odds):
        """Process new odds and detect significant changes"""
        from app.services.market_maker_service import market_maker_service
        
        significant_changes = []
        
        for event in events_with_new_odds:
            event_id = event.event_id
            
            # Get previous odds for comparison
            previous_odds = self.odds_history.get(event_id, {})
            current_odds = self._extract_odds_snapshot(event)
            
            # Compare and detect changes
            changes = self._detect_odds_changes(event_id, previous_odds, current_odds)
            
            if changes:
                significant_changes.extend(changes)
                
                # Log changes
                for change in changes:
                    print(f"📊 ODDS CHANGE: {change.outcome_name} {change.old_odds:+d} → {change.new_odds:+d} ({change.change_amount:+d})")
                
                # Update bets for this event if we're managing it
                if event_id in market_maker_service.managed_events:
                    await self._update_bets_for_odds_changes(event_id, changes)
            
            # Update odds history
            self.odds_history[event_id] = current_odds
        
        return significant_changes
    
    def _extract_odds_snapshot(self, event) -> Dict:
        """Extract current odds for comparison"""
        snapshot = {}
        
        if event.moneyline:
            snapshot['moneyline'] = {
                outcome.name: outcome.american_odds 
                for outcome in event.moneyline.outcomes
            }
        
        if event.spreads:
            snapshot['spreads'] = {
                f"{outcome.name}_{outcome.point}": outcome.american_odds 
                for outcome in event.spreads.outcomes
            }
        
        if event.totals:
            snapshot['totals'] = {
                f"{outcome.name}_{outcome.point}": outcome.american_odds 
                for outcome in event.totals.outcomes
            }
        
        return snapshot
    
    def _detect_odds_changes(self, event_id: str, old_odds: Dict, new_odds: Dict) -> List[OddsChange]:
        """Detect significant odds changes"""
        changes = []
        
        for market_type in new_odds:
            if market_type not in old_odds:
                continue  # New market, not a change
                
            old_market = old_odds[market_type]
            new_market = new_odds[market_type]
            
            for outcome_key in new_market:
                if outcome_key not in old_market:
                    continue  # New outcome, not a change
                
                old_value = old_market[outcome_key]
                new_value = new_market[outcome_key]
                change_amount = new_value - old_value
                
                if abs(change_amount) >= self.change_threshold:
                    change = OddsChange(
                        event_id=event_id,
                        market_type=market_type,
                        outcome_name=outcome_key,
                        old_odds=old_value,
                        new_odds=new_value,
                        change_amount=change_amount,
                        timestamp=datetime.now(timezone.utc)
                    )
                    changes.append(change)
        
        return changes
    
    async def _update_bets_for_odds_changes(self, event_id: str, changes: List[OddsChange]):
        """Update bets when odds change significantly"""
        from app.services.market_maker_service import market_maker_service
        from app.services.prophetx_service import prophetx_service
        
        print(f"🔄 Updating bets for event {event_id} due to odds changes...")
        
        # Group changes by market type
        changes_by_market = {}
        for change in changes:
            market_type = change.market_type
            if market_type not in changes_by_market:
                changes_by_market[market_type] = []
            changes_by_market[market_type].append(change)
        
        # For each affected market, cancel existing bets and create new ones
        for market_type, market_changes in changes_by_market.items():
            await self._refresh_market_bets(event_id, market_type, market_changes)
    
    async def _refresh_market_bets(self, event_id: str, market_type: str, changes: List[OddsChange]):
        """Refresh all bets for a specific market due to odds changes"""
        from app.services.market_maker_service import market_maker_service
        from app.services.prophetx_service import prophetx_service
        
        print(f"   🔄 Refreshing {market_type} market bets...")
        
        # Find all active bets for this event and market
        bets_to_cancel = []
        for bet in market_maker_service.all_bets.values():
            if (bet.is_active and 
                event_id in bet.external_id and  # Simple check - could be more sophisticated
                self._bet_belongs_to_market(bet, market_type)):
                bets_to_cancel.append(bet)
        
        if not bets_to_cancel:
            print(f"   ℹ️  No active bets to cancel for {market_type} market")
            return
        
        print(f"   ❌ Cancelling {len(bets_to_cancel)} bets due to odds changes...")
        
        # Cancel bets individually (or use bulk cancel if available)
        cancelled_count = 0
        for bet in bets_to_cancel:
            try:
                # Use ProphetX bet ID if available, otherwise use external ID
                bet_id_to_cancel = bet.bet_id or bet.external_id
                
                cancel_result = await prophetx_service.cancel_wager(bet_id_to_cancel)
                
                if cancel_result.get("success", False):
                    bet.status = "cancelled"
                    bet.unmatched_stake = 0.0
                    cancelled_count += 1
                    print(f"      ❌ Cancelled: {bet.selection_name} {bet.odds:+d}")
                    
                    # Clear wait period for this line so new bets can be placed immediately
                    from app.services.market_making_strategy import market_making_strategy
                    market_making_strategy.betting_manager.clear_wait_period(bet.line_id)
                    
                else:
                    print(f"      ⚠️ Failed to cancel bet {bet.external_id}: {cancel_result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                print(f"      ⚠️ Exception cancelling bet {bet.external_id}: {e}")
        
        print(f"   ✅ Successfully cancelled {cancelled_count}/{len(bets_to_cancel)} bets")
        print(f"   🔄 New bets will be created in next market making cycle")
    
    def _bet_belongs_to_market(self, bet, market_type: str) -> bool:
        """Check if a bet belongs to a specific market type"""
        # This is a simplified check - you might want to store market_type with bets
        # or use a more sophisticated matching method
        
        # For now, we'll assume all bets need to be cancelled when any market changes
        # This is conservative but safe
        return True
    
    def clear_odds_history(self):
        """Clear odds history (useful for testing or resets)"""
        self.odds_history.clear()
        print("🗑️ Odds history cleared")

# Global odds change handler instance
odds_change_handler = OddsChangeHandler()