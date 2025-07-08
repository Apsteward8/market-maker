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
        
        CORRECTED LOGIC:
        If Pinnacle shows Mets -121, we bet Orioles +121 to offer Mets -121
        If Pinnacle shows Orioles +111, we bet Mets -111 to offer Orioles +111
        
        We bet the OPPOSITE team at the SAME ABSOLUTE VALUE but opposite sign
        """
        # We bet the opposite absolute value with opposite sign
        return -pinnacle_odds
    
    def apply_commission_adjustment(self, odds: int) -> float:
        """
        Apply 3% commission to calculate effective odds for OUR bet sizing
        
        IMPORTANT: This only affects how much we need to bet, NOT the odds we offer users
        
        Commission is taken on winnings AFTER we win, so:
        - If we bet +121 and win $121, we only get $121 * 0.97 = $117.37
        - If we bet -111 to win $100, but only get $97 after commission, we need to bet more
        """
        if odds > 0:
            # Positive odds: we win less due to commission on winnings
            # If we bet $100 at +121, we should win $121 but only get $117.37
            return odds * (1 - self.commission_rate)
        else:
            # Negative odds: we need to risk more to account for commission on winnings
            # If we want to effectively win $100 after commission, we need to win $103.09 before commission
            # So we need to risk more than the face value suggests
            return odds / (1 - self.commission_rate)
    
    def calculate_true_arbitrage_bets(self, plus_odds: int, minus_odds: int) -> ArbitrageCalculation:
        """
        Calculate true arbitrage bet amounts for guaranteed profit
        
        Strategy:
        1. Always bet $100 on the higher odds side (after commission)
        2. Calculate exact amount to bet on lower odds side for equal returns
        3. Guaranteed profit = return - total investment
        
        Args:
            plus_odds: Our positive bet odds (before commission)
            minus_odds: Our negative bet odds (before commission)
            
        Returns:
            ArbitrageCalculation with true arbitrage amounts
        """
        # Apply commission to get effective odds
        eff_plus_odds = plus_odds * (1 - self.commission_rate)  # Reduced winnings
        eff_minus_odds = minus_odds / (1 - self.commission_rate)  # Need to bet more
        
        print(f"   Commission adjustment: {plus_odds:+d} → {eff_plus_odds:+.2f}, {minus_odds:+d} → {eff_minus_odds:+.2f}")
        
        # Step 1: Always bet $100 on the higher effective odds side
        plus_bet = self.base_plus_bet  # $100
        
        # Step 2: Calculate total return if plus side wins
        plus_win_amount = plus_bet * (eff_plus_odds / 100)
        total_return_target = plus_bet + plus_win_amount
        
        print(f"   Plus bet: ${plus_bet} at {eff_plus_odds:+.2f} → Total return ${total_return_target:.2f}")
        
        # Step 3: Calculate minus bet amount to achieve same total return
        # If we bet X at minus odds, total return = X + (X * win_rate)
        # We want: X + (X * (100/abs(eff_minus_odds))) = total_return_target
        # So: X * (1 + 100/abs(eff_minus_odds)) = total_return_target
        # So: X = total_return_target / (1 + 100/abs(eff_minus_odds))
        
        minus_multiplier = 1 + (100 / abs(eff_minus_odds))
        minus_bet = total_return_target / minus_multiplier
        
        print(f"   Minus bet: ${minus_bet:.2f} at {eff_minus_odds:+.2f} → Total return ${total_return_target:.2f}")
        
        # Step 4: Calculate profit
        total_investment = plus_bet + minus_bet
        guaranteed_profit = total_return_target - total_investment
        profit_margin = (guaranteed_profit / total_investment) * 100 if total_investment > 0 else 0
        
        print(f"   Total investment: ${total_investment:.2f}")
        print(f"   Guaranteed profit: ${guaranteed_profit:.2f} ({profit_margin:.2f}%)")
        
        return ArbitrageCalculation(
            plus_side_bet=plus_bet,
            minus_side_bet=minus_bet,
            total_investment=total_investment,
            guaranteed_profit=guaranteed_profit,
            profit_margin=profit_margin,
            is_profitable=guaranteed_profit > 0
        )
        """
        Calculate market making bet amounts for profitable spread
        
        For market making, we want to profit from the margin between plus and minus odds.
        Example: +117 vs -114 gives us a 3-point margin for profit.
        
        Args:
            plus_odds: Effective positive odds (after commission)
            minus_odds: Effective negative odds (after commission)
            
        Returns:
            ArbitrageCalculation with bet amounts and profit analysis
        """
        # Always bet base amount on plus side
        plus_bet = self.base_plus_bet  # $100
        
        # For market making, we want balanced risk on both sides
        # If we risk $100 on plus side, we should risk similar amount on minus side
        # But adjust for the odds difference to maintain roughly equal risk
        
        # Calculate what we win if plus side hits
        plus_win_amount = plus_bet * (plus_odds / 100)  # $100 * (117/100) = $117
        
        # For minus side, bet amount that gives us similar win potential
        # If minus odds are -114, we need to bet $114 to win $100
        # But we want to scale this to match our plus side risk
        minus_bet = plus_bet * (abs(minus_odds) / 100)  # $100 * (114/100) = $114
        
        # Calculate profit scenarios
        # Scenario 1: Plus side wins
        scenario1_profit = plus_win_amount - minus_bet  # Win $117, lose $114 = +$3
        
        # Scenario 2: Minus side wins  
        minus_win_amount = minus_bet / (abs(minus_odds) / 100)  # $114 / (114/100) = $100
        scenario2_profit = minus_win_amount - plus_bet  # Win $100, lose $100 = $0
        
        # Average expected profit (assuming 50/50 probability)
        expected_profit = (scenario1_profit + scenario2_profit) / 2
        
        total_investment = plus_bet + minus_bet
        profit_margin = (expected_profit / total_investment) * 100 if total_investment > 0 else 0
        
        # Market making is profitable if we have positive margin
        # This happens when |plus_odds| > |minus_odds|
        is_profitable = abs(plus_odds) > abs(minus_odds)
        
        return ArbitrageCalculation(
            plus_side_bet=plus_bet,
            minus_side_bet=minus_bet,
            total_investment=total_investment,
            guaranteed_profit=expected_profit,  # Expected profit, not guaranteed
            profit_margin=profit_margin,
            is_profitable=is_profitable
        )
    
    def calculate_position_limits_simple(self, plus_odds: int, minus_odds: int) -> PositionLimits:
        """
        Calculate position limits using true arbitrage strategy
        
        Args:
            plus_odds: Our positive bet odds
            minus_odds: Our negative bet odds
            
        Returns:
            PositionLimits with true arbitrage sizing
        """
        # Calculate true arbitrage amounts
        arbitrage = self.calculate_true_arbitrage_bets(plus_odds, minus_odds)
        
        # Calculate max positions (5x base amounts)
        max_plus_bet = min(self.max_plus_bet, arbitrage.plus_side_bet * self.position_multiplier)
        max_minus_bet = arbitrage.minus_side_bet * self.position_multiplier
        
        return PositionLimits(
            base_plus_bet=arbitrage.plus_side_bet,
            base_minus_bet=arbitrage.minus_side_bet,
            max_plus_bet=max_plus_bet,
            max_minus_bet=max_minus_bet,
            increment_plus=arbitrage.plus_side_bet,  # Always $100 increments
            increment_minus=arbitrage.minus_side_bet,  # Proportional arbitrage amount
            arbitrage_calc=arbitrage
        )
    def calculate_position_limits(self, plus_odds: float, minus_odds: float) -> PositionLimits:
        """
        Calculate position limits based on market making strategy (LEGACY - use simple version)
        """
        return self.calculate_position_limits_simple(int(plus_odds), int(minus_odds))
    
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
        Create a betting instruction using true arbitrage sizing
        
        Args:
            line_id: ProphetX line ID to bet on
            selection_name: Name of selection WE ARE BETTING ON
            pinnacle_odds: Pinnacle odds for the OUTCOME WE'RE OFFERING TO USERS
            outcome_name: What we're offering to users (e.g., "Mets -118")
            position_limits: Position sizing with true arbitrage amounts
            is_plus_side: Whether OUR BET is the positive odds side
        """
        # Step 1: Our bet odds are exact opposite of Pinnacle
        our_bet_odds = self.calculate_exact_hedge_odds(pinnacle_odds)
        
        # Step 2: Round to allowed ProphetX odds (should be very close)
        prophetx_odds = self.round_to_prophetx_odds(our_bet_odds)
        
        # Step 3: Use true arbitrage stake amounts (commission already factored in)
        if is_plus_side:
            stake = position_limits.base_plus_bet  # Always $100
            max_position = position_limits.max_plus_bet
            increment_size = position_limits.increment_plus
        else:
            stake = position_limits.base_minus_bet  # Arbitrage calculated amount
            max_position = position_limits.max_minus_bet
            increment_size = position_limits.increment_minus
        
        # Step 4: Calculate returns
        if prophetx_odds > 0:
            # Positive odds: gross winnings, then apply commission
            gross_winnings = stake * (prophetx_odds / 100)
            net_winnings = gross_winnings * (1 - self.commission_rate)
            expected_return = net_winnings  # What we actually get
            liquidity_offered = gross_winnings  # What users see as potential win
        else:
            # Negative odds: gross winnings, then apply commission  
            gross_winnings = stake / (abs(prophetx_odds) / 100)
            net_winnings = gross_winnings * (1 - self.commission_rate)
            expected_return = net_winnings  # What we actually get
            liquidity_offered = gross_winnings  # What users see as potential win
        
        # Step 5: Create instruction
        instruction = BettingInstruction(
            line_id=line_id,
            selection_name=selection_name,           # WHO we're betting on
            odds=prophetx_odds,                      # OUR bet odds (exact opposite of Pinnacle)
            stake=stake,                             # True arbitrage stake amount
            expected_return=expected_return,         # What we get after commission
            liquidity_offered=liquidity_offered,    # What users see
            outcome_offered_to_users=outcome_name,  # What USERS see (exact Pinnacle)
            odds_offered_to_users=pinnacle_odds,    # Exact Pinnacle odds
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
        
        print(f"🎯 Creating market making plan for: {odds_event.display_name}")
        
        # DEBUG: Show all available Pinnacle markets
        print(f"📊 Available Pinnacle markets:")
        if odds_event.moneyline:
            print(f"   Moneyline: {len(odds_event.moneyline.outcomes)} outcomes")
            for outcome in odds_event.moneyline.outcomes:
                print(f"     {outcome.name}: {outcome.american_odds:+d}")
        if odds_event.spreads:
            print(f"   Spreads: {len(odds_event.spreads.outcomes)} outcomes") 
            for outcome in odds_event.spreads.outcomes:
                print(f"     {outcome.name}: {outcome.american_odds:+d} @ {outcome.point}")
        if odds_event.totals:
            print(f"   Totals: {len(odds_event.totals.outcomes)} outcomes")
            for outcome in odds_event.totals.outcomes:
                print(f"     {outcome.name}: {outcome.american_odds:+d} @ {outcome.point}")
        
        print(f"📋 Processing {len(market_match.market_matches)} market matches...")
        
        # Process each market type
        for market_result in market_match.market_matches:
            if not market_result.is_matched:
                print(f"⚠️  Skipping {market_result.odds_api_market_type}: not matched")
                continue
                
            market_type = market_result.odds_api_market_type
            print(f"📊 Processing {market_type} market...")
            
            # Get Pinnacle outcomes for this market
            if market_type == "h2h" and odds_event.moneyline:
                pinnacle_outcomes = odds_event.moneyline.outcomes
            elif market_type == "spreads" and odds_event.spreads:
                pinnacle_outcomes = odds_event.spreads.outcomes
            elif market_type == "totals" and odds_event.totals:
                pinnacle_outcomes = odds_event.totals.outcomes
            else:
                print(f"⚠️  No Pinnacle data for {market_type}")
                continue
            
            # Ensure we have exactly 2 outcomes for arbitrage
            if len(pinnacle_outcomes) != 2:
                print(f"⚠️  Skipping {market_type}: need exactly 2 outcomes, got {len(pinnacle_outcomes)}")
                continue
            
            # Calculate what we would bet (exact opposite of Pinnacle, no commission adjustment to odds)
            outcome1, outcome2 = pinnacle_outcomes
            print(f"   Pinnacle odds: {outcome1.name} {outcome1.american_odds:+d}, {outcome2.name} {outcome2.american_odds:+d}")
            
            # Calculate our exact hedge bets (exact opposite of Pinnacle)
            our_bet_odds1 = self.calculate_exact_hedge_odds(outcome1.american_odds)  # To offer outcome1
            our_bet_odds2 = self.calculate_exact_hedge_odds(outcome2.american_odds)  # To offer outcome2
            
            print(f"   To offer {outcome1.name} {outcome1.american_odds:+d}: We bet {outcome2.name} at {our_bet_odds1:+d}")
            print(f"   To offer {outcome2.name} {outcome2.american_odds:+d}: We bet {outcome1.name} at {our_bet_odds2:+d}")
            
            # Determine which of our bets is plus vs minus (based on our bet odds, not Pinnacle)
            if our_bet_odds1 > 0 and our_bet_odds2 < 0:
                # Bet 1 is positive, Bet 2 is negative
                plus_bet_odds = our_bet_odds1
                plus_bet_team = outcome2.name      # We bet on outcome2 team
                plus_offer_outcome = outcome1      # We offer outcome1 to users
                
                minus_bet_odds = our_bet_odds2
                minus_bet_team = outcome1.name     # We bet on outcome1 team  
                minus_offer_outcome = outcome2     # We offer outcome2 to users
                
            elif our_bet_odds2 > 0 and our_bet_odds1 < 0:
                # Bet 2 is positive, Bet 1 is negative
                plus_bet_odds = our_bet_odds2
                plus_bet_team = outcome1.name      # We bet on outcome1 team
                plus_offer_outcome = outcome2      # We offer outcome2 to users
                
                minus_bet_odds = our_bet_odds1
                minus_bet_team = outcome2.name     # We bet on outcome2 team
                minus_offer_outcome = outcome1     # We offer outcome1 to users
            else:
                print(f"⚠️  Skipping {market_type}: both bet odds same sign ({our_bet_odds1:+d}, {our_bet_odds2:+d})")
                continue
            
            print(f"   Plus side bet: {plus_bet_team} at {plus_bet_odds:+d} → Offers users {plus_offer_outcome.name} {plus_offer_outcome.american_odds:+d}")
            print(f"   Minus side bet: {minus_bet_team} at {minus_bet_odds:+d} → Offers users {minus_offer_outcome.name} {minus_offer_outcome.american_odds:+d}")
            
            # Check profitability based on margin between our bet odds
            margin = abs(plus_bet_odds) - abs(minus_bet_odds)
            is_profitable = margin > 0
            print(f"   Margin: |{plus_bet_odds:+d}| - |{minus_bet_odds:+d}| = {margin}")
            print(f"   Is profitable: {is_profitable}")
            
            if not is_profitable:
                print(f"❌ Skipping unprofitable {market_type} market")
                continue
            
            print(f"✅ {market_type} market is profitable!")
            
            # Calculate position limits (using our bet odds for commission calculations)
            limits = self.calculate_position_limits_simple(plus_bet_odds, minus_bet_odds)
            position_limits_by_market[market_type] = limits
            
            # Create betting instructions with corrected logic
            print(f"   Creating betting instructions...")
            
            # Instruction 1: Plus side bet
            print(f"   \n   Creating plus side instruction:")
            print(f"     Bet on: {plus_bet_team} at {plus_bet_odds:+d}")
            print(f"     Offers users: {plus_offer_outcome.name} {plus_offer_outcome.american_odds:+d}")
            
            # Find the line for plus side bet
            plus_line_mapping = None
            for outcome_mapping in market_result.outcome_mappings:
                if outcome_mapping['odds_api_outcome_name'].lower() == plus_bet_team.lower():
                    plus_line_mapping = outcome_mapping
                    break
            
            if plus_line_mapping:
                plus_instruction = self.create_betting_instruction(
                    line_id=plus_line_mapping['prophetx_line_id'],
                    selection_name=plus_line_mapping['prophetx_selection_name'],
                    pinnacle_odds=plus_offer_outcome.american_odds,  # What we offer users
                    outcome_name=f"{plus_offer_outcome.name} {plus_offer_outcome.american_odds:+d}",
                    position_limits=limits,
                    is_plus_side=True
                )
                if plus_instruction:
                    instructions.append(plus_instruction)
                    print(f"     ✅ Plus instruction: Bet {plus_instruction.selection_name} {plus_instruction.odds:+d}")
                    print(f"        → Users see: {plus_instruction.outcome_offered_to_users}")
            
            # Instruction 2: Minus side bet
            print(f"   \n   Creating minus side instruction:")
            print(f"     Bet on: {minus_bet_team} at {minus_bet_odds:+d}")
            print(f"     Offers users: {minus_offer_outcome.name} {minus_offer_outcome.american_odds:+d}")
            
            # Find the line for minus side bet
            minus_line_mapping = None
            for outcome_mapping in market_result.outcome_mappings:
                if outcome_mapping['odds_api_outcome_name'].lower() == minus_bet_team.lower():
                    minus_line_mapping = outcome_mapping
                    break
            
            if minus_line_mapping:
                minus_instruction = self.create_betting_instruction(
                    line_id=minus_line_mapping['prophetx_line_id'],
                    selection_name=minus_line_mapping['prophetx_selection_name'],
                    pinnacle_odds=minus_offer_outcome.american_odds,  # What we offer users
                    outcome_name=f"{minus_offer_outcome.name} {minus_offer_outcome.american_odds:+d}",
                    position_limits=limits,
                    is_plus_side=False
                )
                if minus_instruction:
                    instructions.append(minus_instruction)
                    print(f"     ✅ Minus instruction: Bet {minus_instruction.selection_name} {minus_instruction.odds:+d}")
                    print(f"        → Users see: {minus_instruction.outcome_offered_to_users}")
            
            created_instructions = 2 if plus_line_mapping and minus_line_mapping else 0
            print(f"   ✅ Created {created_instructions} betting instructions for {market_type}")
        
        if not instructions:
            print("❌ No profitable opportunities found - no betting instructions created")
            return None
        
        print(f"🎉 Created {len(instructions)} total betting instructions")
        
        # Calculate overall metrics
        total_stake = sum(instr.stake for instr in instructions)
        max_exposure = max(instr.max_position for instr in instructions)
        
        # Overall profitability analysis using the corrected calculations
        overall_profitability = {"markets": {}}
        all_profitable = True
        
        for market_type, limits in position_limits_by_market.items():
            # Use the new margin-based profitability
            market_profit = {
                "expected_profit": limits.arbitrage_calc.guaranteed_profit,
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