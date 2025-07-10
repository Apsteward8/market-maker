"""
Line Position Monitoring Service

This service tracks our betting positions by line_id using ProphetX's wager histories API.
Key features:
- Gets real position data from ProphetX (not just internal tracking)
- Tracks total stake per line across all bets
- Determines when to place initial vs incremental bets
- Enforces 4x position limits
- Handles 5-minute wait periods after fills
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class LinePosition:
    """Complete position information for a single line"""
    line_id: str
    selection_name: str
    total_bets: int
    total_stake: float
    total_matched: float
    total_unmatched: float
    last_bet_time: Optional[datetime]
    last_fill_time: Optional[datetime]
    recent_fills: List[Dict[str, Any]]  # List of recent fills for wait period tracking
    
    # Position limits from strategy
    max_position: float
    increment_size: float
    recommended_initial: float
    
    # Status
    has_active_bets: bool
    in_wait_period: bool
    wait_period_ends: Optional[datetime]
    can_add_liquidity: bool
    next_bet_amount: float

class LinePositionService:
    """Service for monitoring and managing positions by line_id using ProphetX wager histories"""
    
    def __init__(self):
        self.positions: Dict[str, LinePosition] = {}
        self.monitoring_active = False
        self.last_monitoring_time = None
        self.fill_wait_period_seconds = 300  # 5 minutes
        
    async def get_line_position(self, line_id: str) -> Optional[LinePosition]:
        """Get current position for a specific line"""
        return self.positions.get(line_id)
    
    async def refresh_line_position(self, line_id: str, strategy_info: Dict[str, Any] = None) -> LinePosition:
        """
        Refresh position data for a specific line using ProphetX wager histories
        
        Args:
            line_id: ProphetX line ID to refresh
            strategy_info: Strategy info (max_position, increment_size, etc.)
            
        Returns:
            Updated LinePosition object
        """
        try:
            # Get wager histories for this specific line
            from app.services.prophetx_wager_service import prophetx_wager_service
            
            # Get wagers for last 7 days (covers most betting scenarios)
            now_timestamp = int(time.time())
            week_ago_timestamp = now_timestamp - (7 * 24 * 60 * 60)
            
            # Get all wagers for this line (active and matched)
            all_wagers_result = await prophetx_wager_service.get_wager_histories(
                from_timestamp=week_ago_timestamp,
                to_timestamp=now_timestamp,
                limit=1000,
                line_id=line_id  # This would need to be added to the API call
            )
            
            if not all_wagers_result["success"]:
                print(f"❌ Failed to get wager histories for line {line_id}")
                return None
            
            wagers = all_wagers_result["wagers"]
            
            # Calculate position statistics
            total_bets = len(wagers)
            total_stake = sum(w.get("stake", 0) for w in wagers)
            total_matched = sum(w.get("matched_stake", 0) for w in wagers)
            total_unmatched = total_stake - total_matched
            
            # Find recent activity
            last_bet_time = None
            last_fill_time = None
            recent_fills = []
            
            for wager in sorted(wagers, key=lambda w: w.get("created_at", ""), reverse=True):
                # Parse timestamps
                created_at = self._parse_timestamp(wager.get("created_at"))
                updated_at = self._parse_timestamp(wager.get("updated_at"))
                
                if not last_bet_time and created_at:
                    last_bet_time = created_at
                
                # Check for fills (matched stake > 0)
                matched_stake = wager.get("matched_stake", 0)
                if matched_stake > 0:
                    if not last_fill_time and updated_at:
                        last_fill_time = updated_at
                    
                    # Track recent fills for wait period logic
                    if updated_at and updated_at > datetime.now(timezone.utc) - timedelta(hours=1):
                        recent_fills.append({
                            "wager_id": wager.get("wager_id"),
                            "external_id": wager.get("external_id"),
                            "matched_stake": matched_stake,
                            "fill_time": updated_at,
                            "matching_status": wager.get("matching_status")
                        })
            
            # Determine current status
            has_active_bets = any(w.get("matching_status") == "unmatched" and 
                                w.get("status") in ["open", "active"] for w in wagers)
            
            # Check wait period (5 minutes after last fill)
            in_wait_period = False
            wait_period_ends = None
            if last_fill_time:
                wait_period_ends = last_fill_time + timedelta(seconds=self.fill_wait_period_seconds)
                in_wait_period = datetime.now(timezone.utc) < wait_period_ends
            
            # Get strategy limits
            max_position = strategy_info.get("max_position", 500.0) if strategy_info else 500.0
            increment_size = strategy_info.get("increment_size", 100.0) if strategy_info else 100.0
            recommended_initial = strategy_info.get("recommended_initial", 100.0) if strategy_info else 100.0
            
            # Calculate next bet amount
            can_add_liquidity = not in_wait_period and total_stake < max_position
            next_bet_amount = 0.0
            
            if can_add_liquidity:
                if total_stake == 0:
                    # First bet
                    next_bet_amount = recommended_initial
                else:
                    # Incremental bet
                    remaining_capacity = max_position - total_stake
                    next_bet_amount = min(increment_size, remaining_capacity)
            
            # Create position object
            position = LinePosition(
                line_id=line_id,
                selection_name=strategy_info.get("selection_name", "Unknown") if strategy_info else "Unknown",
                total_bets=total_bets,
                total_stake=total_stake,
                total_matched=total_matched,
                total_unmatched=total_unmatched,
                last_bet_time=last_bet_time,
                last_fill_time=last_fill_time,
                recent_fills=recent_fills,
                max_position=max_position,
                increment_size=increment_size,
                recommended_initial=recommended_initial,
                has_active_bets=has_active_bets,
                in_wait_period=in_wait_period,
                wait_period_ends=wait_period_ends,
                can_add_liquidity=can_add_liquidity,
                next_bet_amount=next_bet_amount
            )
            
            # Cache the position
            self.positions[line_id] = position
            
            return position
            
        except Exception as e:
            print(f"❌ Error refreshing line position for {line_id}: {e}")
            return None
    
    def should_place_initial_bet(self, line_id: str) -> bool:
        """
        Check if we should place initial bet on this line
        
        Returns True if:
        - We have no bets on this line, OR
        - We have bets but they're all filled and wait period is over
        """
        position = self.positions.get(line_id)
        
        if not position:
            return True  # No position data = place initial bet
        
        if position.total_bets == 0:
            return True  # No bets placed = place initial bet
        
        # We have bets - check if we can add more liquidity
        return position.can_add_liquidity and position.next_bet_amount > 0
    
    def get_next_bet_amount(self, line_id: str, recommended_initial: float) -> float:
        """
        Get the next bet amount for a line
        
        Args:
            line_id: ProphetX line ID
            recommended_initial: Recommended initial bet from strategy
            
        Returns:
            Amount to bet (0 if shouldn't bet)
        """
        position = self.positions.get(line_id)
        
        if not position:
            return recommended_initial  # First bet
        
        return position.next_bet_amount
    
    async def monitor_all_lines(self, line_strategies: Dict[str, Dict[str, Any]]):
        """
        Monitor all active lines for fills and position changes
        
        Args:
            line_strategies: Dict of line_id -> strategy info (max_position, increment_size, etc.)
        """
        if not line_strategies:
            return
        
        print(f"🔍 Monitoring {len(line_strategies)} lines for fills and position changes...")
        
        for line_id, strategy_info in line_strategies.items():
            try:
                # Refresh position data
                old_position = self.positions.get(line_id)
                new_position = await self.refresh_line_position(line_id, strategy_info)
                
                if not new_position:
                    continue
                
                # Check for new fills
                if old_position and new_position.total_matched > old_position.total_matched:
                    new_fill_amount = new_position.total_matched - old_position.total_matched
                    print(f"🎉 FILL DETECTED: {line_id[-8:]} - ${new_fill_amount:.2f}")
                    print(f"   Total matched: ${new_position.total_matched:.2f}")
                    print(f"   Total position: ${new_position.total_stake:.2f}")
                    
                    if new_position.in_wait_period:
                        wait_mins = (new_position.wait_period_ends - datetime.now(timezone.utc)).total_seconds() / 60
                        print(f"   ⏱️  Starting 5-minute wait period ({wait_mins:.1f} mins remaining)")
                
                # Log position status
                self._log_position_status(new_position)
                
            except Exception as e:
                print(f"❌ Error monitoring line {line_id}: {e}")
        
        self.last_monitoring_time = datetime.now(timezone.utc)
    
    def _log_position_status(self, position: LinePosition):
        """Log current position status for a line"""
        utilization = (position.total_stake / position.max_position) * 100
        
        status_parts = []
        if position.has_active_bets:
            status_parts.append(f"${position.total_unmatched:.0f} active")
        if position.total_matched > 0:
            status_parts.append(f"${position.total_matched:.0f} matched")
        if position.in_wait_period:
            status_parts.append("wait period")
        if position.can_add_liquidity:
            status_parts.append(f"can add ${position.next_bet_amount:.0f}")
        
        status_str = ", ".join(status_parts) if status_parts else "no activity"
        
        print(f"   📊 {position.line_id[-8:]}: ${position.total_stake:.0f}/{position.max_position:.0f} "
              f"({utilization:.0f}%) - {status_str}")
    
    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """Parse timestamp string to datetime object"""
        if not timestamp_str:
            return None
        
        try:
            # Handle different timestamp formats
            if timestamp_str.endswith('Z'):
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                return datetime.fromisoformat(timestamp_str)
        except:
            return None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all line positions"""
        total_lines = len(self.positions)
        total_stake = sum(p.total_stake for p in self.positions.values())
        total_matched = sum(p.total_matched for p in self.positions.values())
        lines_in_wait = sum(1 for p in self.positions.values() if p.in_wait_period)
        lines_can_add = sum(1 for p in self.positions.values() if p.can_add_liquidity)
        
        return {
            "total_lines_tracked": total_lines,
            "total_stake_all_lines": total_stake,
            "total_matched_all_lines": total_matched,
            "lines_in_wait_period": lines_in_wait,
            "lines_can_add_liquidity": lines_can_add,
            "last_monitoring_time": self.last_monitoring_time.isoformat() if self.last_monitoring_time else None
        }

# Global line position service instance
line_position_service = LinePositionService()