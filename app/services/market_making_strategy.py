#!/usr/bin/env python3
"""
Market Making Strategy Engine - UPDATED
Implements exact Pinnacle odds replication with arbitrage position sizing and 3% commission adjustment
"""

from typing import Dict, List, Optional, Tuple, NamedTuple
from datetime import datetime, timezone
from dataclasses import dataclass
import math
import time

# ProphetX allowed odds (complete list)
PROPHETX_ALLOWED_ODDS = [
    # Negative odds
    -300, -295, -290, -285, -280, -275, -270, -265, -260, -255, -250, -245, -240, -235, -230,
    -225, -220, -215, -210, -205, -200, -198, -196, -194, -192, -190, -188, -186, -184, -182,
    -180, -178, -176, -174, -172, -170, -168, -166, -164, -162, -160, -158, -156, -154, -152,
    -150, -148, -146, -144, -142, -140, -138, -136, -134, -132, -130, -129, -128, -127, -126,
    -125, -124, -123, -122, -121, -120, -119, -118, -117, -116, -115, -114, -113, -112, -111,
    -110, -109, -108, -107, -106, -105, -104, -103, -102, -101,
    # Positive odds  
    100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117,
    118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 132, 134, 136, 138, 140,
    142, 144, 146, 148, 150, 152, 154, 156, 158, 160, 162, 164, 166, 168, 170, 172, 174, 176,
    178, 180, 182, 184, 186, 188, 190, 192, 194, 196, 198, 200, 205, 210, 215, 220, 225, 230,
    235, 240, 245, 250, 255, 260, 265, 270, 275, 280, 285, 290, 295, 300
    # Continues with increments of 5 up to 500, then 20 up to 1000, then 100 up to 2000, 
    # then 250 up to 3000, then 500 up to 25000
]

# Add the extended odds ranges
def _generate_extended_odds():
    """Generate the full ProphetX odds range"""
    odds = PROPHETX_ALLOWED_ODDS.copy()
    
    # 305-495 (increment by 5)
    for i in range(305, 500, 5):
        odds.extend([i, -i])
    
    # 500, 520, 540... up to 1000 (increment by 20)
    for i in range(520, 1001, 20):
        odds.extend([i, -i])
    
    # 1100, 1200... up to 2000 (increment by 100)  
    for i in range(1100, 2001, 100):
        odds.extend([i, -i])
    
    # 2250, 2500, 2750, 3000 (increment by 250)
    for i in range(2250, 3001, 250):
        odds.extend([i, -i])
    
    # 3500, 4000... up to 25000 (increment by 500)
    for i in range(3500, 25001, 500):
        odds.extend([i, -i])
    
    return sorted(odds)

PROPHETX_ALLOWED_ODDS_FULL = _generate_extended_odds()

@dataclass
class BettingInstruction:
    """Instructions for placing a single bet on ProphetX"""
    line_id: str
    selection_name: str
    odds: int  # ProphetX odds to bet at
    stake: float  # Amount to wager
    expected_return: float  # Expected return if bet wins
    liquidity_offered: float  # Liquidity we're providing to users
    outcome_offered_to_users: str  # What outcome we're offering (e.g., "Tigers +103")
    odds_offered_to_users: int  # What odds we're offering to users
    is_plus_side: bool  # True if this is the positive odds side
    max_position: float  # Maximum total position size for this line
    increment_size: float  # Size of each increment to add
    
@dataclass
class ArbitrageCalculation:
    """Results of arbitrage calculation between two sides"""
    plus_side_bet: float
    minus_side_bet: float
    total_investment: float
    guaranteed_profit: float
    profit_margin: float
    is_profitable: bool

@dataclass
class PositionLimits:
    """Position sizing limits for a market"""
    base_plus_bet: float
    base_minus_bet: float
    max_plus_bet: float
    max_minus_bet: float
    increment_plus: float
    increment_minus: float
    arbitrage_calc: ArbitrageCalculation

@dataclass
class MarketMakingPlan:
    """Complete market making plan for an event"""
    event_id: str
    event_name: str
    betting_instructions: List[BettingInstruction]
    total_stake: float
    max_exposure: float
    is_profitable: bool
    profitability_analysis: Dict[str, float]
    position_limits: Dict[str, PositionLimits]  # market_type -> limits
    created_at: datetime

class IncrementalBettingManager:
    """Manages incremental betting with wait periods after fills"""
    
    def __init__(self, fill_wait_period: int = 300):  # 5 minutes default
        self.active_positions: Dict[str, Dict] = {}  # line_id -> position info
        self.last_fill_time: Dict[str, float] = {}   # line_id -> timestamp
        self.fill_wait_period = fill_wait_period     # seconds to wait after fill
        
    def record_fill(self, line_id: str, fill_amount: float, total_position: float):
        """Record that a line got filled"""
        self.last_fill_time[line_id] = time.time()
        self.active_positions[line_id] = {
            'last_fill_amount': fill_amount,
            'total_position': total_position,
            'last_fill_time': time.time()
        }
        print(f"📝 Recorded fill for {line_id}: ${fill_amount:.2f} (total: ${total_position:.2f})")
    
    def can_add_liquidity(self, line_id: str) -> bool:
        """Check if enough time has passed since last fill to add more liquidity"""
        if line_id not in self.last_fill_time:
            return True
        
        time_since_fill = time.time() - self.last_fill_time[line_id]
        can_add = time_since_fill >= self.fill_wait_period
        
        if not can_add:
            remaining_wait = self.fill_wait_period - time_since_fill
            print(f"⏱️  Waiting {remaining_wait:.0f}s before adding more liquidity to {line_id}")
        
        return can_add
    
    def get_next_increment(self, line_id: str, current_position: float, max_position: float, increment_size: float) -> float:
        """Calculate next increment amount to add"""
        if not self.can_add_liquidity(line_id):
            return 0.0
        
        if current_position + increment_size <= max_position:
            return increment_size
        elif current_position < max_position:
            # Add remaining amount up to max
            return max_position - current_position
        else:
            # Already at max position
            return 0.0
    
    def clear_wait_period(self, line_id: str):
        """Manually clear wait period for a line (e.g., when odds change significantly)"""
        if line_id in self.last_fill_time:
            del self.last_fill_time[line_id]
            print(f"⚡ Cleared wait period for {line_id} due to odds change")

class MarketMakingStrategy:
    """Core market making strategy implementation - UPDATED for exact Pinnacle replication"""
    
    def __init__(self):
        self.commission_rate = 0.03  # 3% commission on net winnings
        self.max_plus_bet = 500.0    # Max $500 on positive odds
        self.base_plus_bet = 100.0   # $100 increments on positive odds
        self.position_multiplier = 5  # 5x base bet for max position
        
        # Incremental betting manager
        self.betting_manager = IncrementalBettingManager(fill_wait_period=300)  # 5 minutes
        
    def round_to_prophetx_odds(self, calculated_odds: int) -> int:
        """Round calculated odds to nearest allowed ProphetX odds"""
        if calculated_odds in PROPHETX_ALLOWED_ODDS_FULL:
            return calculated_odds
        
        # Find closest allowed odds
        closest_odds = min(PROPHETX_ALLOWED_ODDS_FULL, key=lambda x: abs(x - calculated_odds))
        return closest_odds
    
    def calculate_exact_hedge_odds(self, pinnacle_odds: int) -> int:
        """
        Calculate exact hedge odds to offer Pinnacle's odds to users
        
        If Pinnacle shows Tigers +103, we bet Rays -103 to offer Tigers +103
        If Pinnacle shows Rays -112, we bet Tigers +112 to offer Rays -112
        """
        return -pinnacle_odds
    
    def apply_commission_adjustment(self, odds: int) -> float:
        """Apply 3% commission to calculate effective odds"""
        if odds > 0:
            # Positive odds: reduce winnings by 3%
            return odds * (1 - self.commission_rate)
        else:
            # Negative odds: need to risk more to account for commission
            return odds / (1 - self.commission_rate)
    
    def calculate_arbitrage_bets(self, plus_odds: float, minus_odds: float) -> ArbitrageCalculation:
        """
        Calculate arbitrage bet amounts for guaranteed profit
        
        Args:
            plus_odds: Effective positive odds (after commission)
            minus_odds: Effective negative odds (after commission)
            
        Returns:
            ArbitrageCalculation with bet amounts and profit analysis
        """
        # Always bet base amount on plus side
        plus_bet = self.base_plus_bet
        
        # Calculate corresponding minus bet for arbitrage
        plus_win = plus_bet * (plus_odds / 100)
        minus_bet = plus_win / (abs(minus_odds) / 100)
        
        total_investment = plus_bet + minus_bet
        guaranteed_profit = plus_win - total_investment
        profit_margin = (guaranteed_profit / total_investment) * 100 if total_investment > 0 else 0
        
        return ArbitrageCalculation(
            plus_side_bet=plus_bet,
            minus_side_bet=minus_bet,
            total_investment=total_investment,
            guaranteed_profit=guaranteed_profit,
            profit_margin=profit_margin,
            is_profitable=guaranteed_profit > 0
        )
    
    def calculate_position_limits(self, plus_odds: float, minus_odds: float) -> PositionLimits:
        """
        Calculate position limits based on arbitrage strategy
        
        Args:
            plus_odds: Effective positive odds (after commission)
            minus_odds: Effective negative odds (after commission)
            
        Returns:
            PositionLimits with all sizing information
        """
        # Calculate base arbitrage amounts
        arbitrage = self.calculate_arbitrage_bets(plus_odds, minus_odds)
        
        # Calculate maximum positions
        max_plus_bet = min(self.max_plus_bet, self.base_plus_bet * self.position_multiplier)
        max_minus_bet = arbitrage.minus_side_bet * self.position_multiplier
        
        return PositionLimits(
            base_plus_bet=arbitrage.plus_side_bet,
            base_minus_bet=arbitrage.minus_side_bet,
            max_plus_bet=max_plus_bet,
            max_minus_bet=max_minus_bet,
            increment_plus=self.base_plus_bet,
            increment_minus=arbitrage.minus_side_bet,
            arbitrage_calc=arbitrage
        )
    
    def create_betting_instruction(
        self, 
        line_id: str,
        selection_name: str, 
        pinnacle_odds: int,
        outcome_name: str,
        position_limits: PositionLimits,
        is_plus_side: bool
    ) -> Optional[BettingInstruction]:
        """
        Create a betting instruction for exact Pinnacle replication
        
        Args:
            line_id: ProphetX line ID to bet on
            selection_name: Name of selection (e.g., "Detroit Tigers") 
            pinnacle_odds: Pinnacle odds for this outcome
            outcome_name: What we're offering to users (e.g., "Tigers +103")
            position_limits: Position sizing limits
            is_plus_side: Whether this is the positive odds side
        """
        # Step 1: Calculate what odds we need to bet at (opposite of Pinnacle)
        hedge_odds = self.calculate_exact_hedge_odds(pinnacle_odds)
        
        # Step 2: Apply commission adjustment
        effective_odds = self.apply_commission_adjustment(hedge_odds)
        
        # Step 3: Round to allowed ProphetX odds
        prophetx_odds = self.round_to_prophetx_odds(int(effective_odds))
        
        # Step 4: Determine bet amount and limits
        if is_plus_side:
            stake = position_limits.base_plus_bet
            max_position = position_limits.max_plus_bet
            increment_size = position_limits.increment_plus
        else:
            stake = position_limits.base_minus_bet
            max_position = position_limits.max_minus_bet
            increment_size = position_limits.increment_minus
        
        # Step 5: Calculate expected return
        if prophetx_odds > 0:
            expected_return = stake * (prophetx_odds / 100)
            liquidity_offered = expected_return
        else:
            expected_return = stake / (abs(prophetx_odds) / 100)
            liquidity_offered = expected_return
        
        # Step 6: Create instruction
        instruction = BettingInstruction(
            line_id=line_id,
            selection_name=selection_name,
            odds=prophetx_odds,
            stake=stake,
            expected_return=expected_return,
            liquidity_offered=liquidity_offered,
            outcome_offered_to_users=outcome_name,
            odds_offered_to_users=pinnacle_odds,  # Exact Pinnacle odds
            is_plus_side=is_plus_side,
            max_position=max_position,
            increment_size=increment_size
        )
        
        return instruction
    
    def analyze_profitability(self, instructions: List[BettingInstruction]) -> Dict[str, float]:
        """Analyze profitability of a set of betting instructions"""
        if len(instructions) != 2:
            return {"error": "Need exactly 2 sides for profitability analysis"}
        
        instr1, instr2 = instructions
        
        # Identify plus and minus sides
        if instr1.is_plus_side:
            plus_instr, minus_instr = instr1, instr2
        else:
            plus_instr, minus_instr = instr2, instr1
        
        # Get effective odds after commission
        eff_plus_odds = self.apply_commission_adjustment(plus_instr.odds)
        eff_minus_odds = self.apply_commission_adjustment(minus_instr.odds)
        
        # Calculate arbitrage
        arbitrage = self.calculate_arbitrage_bets(eff_plus_odds, eff_minus_odds)
        
        return {
            "effective_plus_odds": eff_plus_odds,
            "effective_minus_odds": eff_minus_odds,
            "guaranteed_profit": arbitrage.guaranteed_profit,
            "profit_margin": arbitrage.profit_margin,
            "is_profitable": arbitrage.is_profitable,
            "plus_stake": arbitrage.plus_side_bet,
            "minus_stake": arbitrage.minus_side_bet,
            "total_stake": arbitrage.total_investment
        }
    
    def create_market_making_plan(
        self,
        event_match,  # EventMatch object
        market_match   # MarketMatchResult object  
    ) -> Optional[MarketMakingPlan]:
        """
        Create complete market making plan for exact Pinnacle replication
        
        Args:
            event_match: Matched event between Odds API and ProphetX
            market_match: Market matching results with line_id mappings
            
        Returns:
            MarketMakingPlan if profitable, None otherwise
        """
        odds_event = event_match.odds_api_event
        
        instructions = []
        position_limits_by_market = {}
        
        # Process each market type
        for market_result in market_match.market_matches:
            if not market_result.is_matched:
                continue
                
            market_type = market_result.odds_api_market_type
            
            # Get Pinnacle outcomes for this market
            if market_type == "h2h" and odds_event.moneyline:
                pinnacle_outcomes = odds_event.moneyline.outcomes
            elif market_type == "spreads" and odds_event.spreads:
                pinnacle_outcomes = odds_event.spreads.outcomes
            elif market_type == "totals" and odds_event.totals:
                pinnacle_outcomes = odds_event.totals.outcomes
            else:
                continue
            
            # Ensure we have exactly 2 outcomes for arbitrage
            if len(pinnacle_outcomes) != 2:
                print(f"⚠️  Skipping {market_type}: need exactly 2 outcomes, got {len(pinnacle_outcomes)}")
                continue
            
            # Calculate effective odds for both sides
            outcome1, outcome2 = pinnacle_outcomes
            hedge_odds1 = self.calculate_exact_hedge_odds(outcome1.american_odds)
            hedge_odds2 = self.calculate_exact_hedge_odds(outcome2.american_odds)
            
            eff_odds1 = self.apply_commission_adjustment(hedge_odds1)
            eff_odds2 = self.apply_commission_adjustment(hedge_odds2)
            
            # Determine which is plus/minus side
            if eff_odds1 > 0 and eff_odds2 < 0:
                plus_odds, minus_odds = eff_odds1, eff_odds2
                plus_outcome, minus_outcome = outcome1, outcome2
            elif eff_odds2 > 0 and eff_odds1 < 0:
                plus_odds, minus_odds = eff_odds2, eff_odds1
                plus_outcome, minus_outcome = outcome2, outcome1
            else:
                print(f"⚠️  Skipping {market_type}: both sides same sign (odds1: {eff_odds1}, odds2: {eff_odds2})")
                continue
            
            # Calculate position limits
            limits = self.calculate_position_limits(plus_odds, minus_odds)
            position_limits_by_market[market_type] = limits
            
            # Check profitability
            if not limits.arbitrage_calc.is_profitable:
                print(f"❌ Skipping unprofitable {market_type} market: profit = ${limits.arbitrage_calc.guaranteed_profit:.2f}")
                continue
            
            print(f"✅ {market_type} market profitable: ${limits.arbitrage_calc.guaranteed_profit:.2f} profit on ${limits.arbitrage_calc.total_investment:.2f} investment")
            
            # Create betting instructions for both sides
            market_instructions = []
            
            # Find line mappings for both outcomes
            plus_mapping = None
            minus_mapping = None
            
            for outcome_mapping in market_result.outcome_mappings:
                if outcome_mapping['odds_api_outcome_name'].lower() == plus_outcome.name.lower():
                    plus_mapping = outcome_mapping
                elif outcome_mapping['odds_api_outcome_name'].lower() == minus_outcome.name.lower():
                    minus_mapping = outcome_mapping
            
            if not plus_mapping or not minus_mapping:
                print(f"⚠️  Could not find line mappings for {market_type}")
                continue
            
            # Create instructions
            plus_instruction = self.create_betting_instruction(
                line_id=plus_mapping['prophetx_line_id'],
                selection_name=plus_mapping['prophetx_selection_name'],
                pinnacle_odds=plus_outcome.american_odds,
                outcome_name=f"{plus_outcome.name} {plus_outcome.american_odds:+d}",
                position_limits=limits,
                is_plus_side=True
            )
            
            minus_instruction = self.create_betting_instruction(
                line_id=minus_mapping['prophetx_line_id'],
                selection_name=minus_mapping['prophetx_selection_name'],
                pinnacle_odds=minus_outcome.american_odds,
                outcome_name=f"{minus_outcome.name} {minus_outcome.american_odds:+d}",
                position_limits=limits,
                is_plus_side=False
            )
            
            if plus_instruction and minus_instruction:
                market_instructions.extend([plus_instruction, minus_instruction])
                instructions.extend(market_instructions)
        
        if not instructions:
            return None
        
        # Calculate overall metrics
        total_stake = sum(instr.stake for instr in instructions)
        max_exposure = max(instr.max_position for instr in instructions)
        
        # Overall profitability analysis
        overall_profitability = {"markets": {}}
        all_profitable = True
        
        for market_type, limits in position_limits_by_market.items():
            market_profit = {
                "guaranteed_profit": limits.arbitrage_calc.guaranteed_profit,
                "profit_margin": limits.arbitrage_calc.profit_margin,
                "total_investment": limits.arbitrage_calc.total_investment,
                "is_profitable": limits.arbitrage_calc.is_profitable
            }
            overall_profitability["markets"][market_type] = market_profit
            if not limits.arbitrage_calc.is_profitable:
                all_profitable = False
        
        overall_profitability["all_markets_profitable"] = all_profitable
        
        plan = MarketMakingPlan(
            event_id=odds_event.event_id,
            event_name=odds_event.display_name,
            betting_instructions=instructions,
            total_stake=total_stake,
            max_exposure=max_exposure,
            is_profitable=all_profitable,
            profitability_analysis=overall_profitability,
            position_limits=position_limits_by_market,
            created_at=datetime.now(timezone.utc)
        )
        
        return plan

# Global strategy instance
market_making_strategy = MarketMakingStrategy()