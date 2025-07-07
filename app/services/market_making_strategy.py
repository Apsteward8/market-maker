#!/usr/bin/env python3
"""
Market Making Strategy Engine
Implements the core betting strategy: improve Pinnacle odds by 1 point while accounting for 3% commission
"""

from typing import Dict, List, Optional, Tuple, NamedTuple
from datetime import datetime, timezone
from dataclasses import dataclass
import math

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
    outcome_offered_to_users: str  # What outcome we're offering (e.g., "Tigers +107")
    odds_offered_to_users: int  # What odds we're offering to users
    
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
    created_at: datetime

class MarketMakingStrategy:
    """Core market making strategy implementation"""
    
    def __init__(self):
        self.commission_rate = 0.03  # 3% commission on net winnings
        self.improvement_points = 1  # Improve Pinnacle odds by 1 point
        self.target_liquidity = 100.0  # Target $100 liquidity per line
        self.max_exposure_per_line = 500.0  # Max $500 risk per line
        
    def round_to_prophetx_odds(self, calculated_odds: int) -> int:
        """Round calculated odds to nearest allowed ProphetX odds"""
        if calculated_odds in PROPHETX_ALLOWED_ODDS_FULL:
            return calculated_odds
        
        # Find closest allowed odds
        closest_odds = min(PROPHETX_ALLOWED_ODDS_FULL, key=lambda x: abs(x - calculated_odds))
        return closest_odds
    
    def improve_pinnacle_odds(self, pinnacle_odds: int) -> int:
        """Improve Pinnacle odds by 1 point for user offering"""
        if pinnacle_odds > 0:
            # Positive odds: +106 becomes +107
            return pinnacle_odds + self.improvement_points
        else:
            # Negative odds: -117 becomes -116  
            return pinnacle_odds + self.improvement_points
    
    def calculate_hedge_odds(self, improved_odds: int) -> int:
        """Calculate what odds we need to bet at to offer improved odds to users"""
        if improved_odds > 0:
            # If we offer Tigers +107, we bet Rays at -107
            return -improved_odds
        else:
            # If we offer Rays -116, we bet Tigers at +116
            return -improved_odds
    
    def apply_commission_adjustment(self, odds: int) -> float:
        """Apply 3% commission to calculate effective odds"""
        if odds > 0:
            # Positive odds: reduce winnings by 3%
            return odds * (1 - self.commission_rate)
        else:
            # Negative odds: need to risk more to account for commission
            # If we bet -110 and win, we only get 97% of the winnings
            # So effective odds are worse
            return odds / (1 - self.commission_rate)
    
    def is_profitable_after_commission(self, plus_side_odds: int, minus_side_odds: int) -> bool:
        """
        Check if the market making opportunity is profitable after commission
        
        Args:
            plus_side_odds: Odds for positive side (e.g., +116)
            minus_side_odds: Odds for negative side (e.g., -107)
            
        Returns:
            True if profitable (plus side > abs(minus side) after commission)
        """
        # Apply commission to both sides
        effective_plus = self.apply_commission_adjustment(plus_side_odds)
        effective_minus = self.apply_commission_adjustment(minus_side_odds)
        
        # For profitability, effective plus odds should be higher than absolute value of minus odds
        return effective_plus > abs(effective_minus)
    
    def calculate_bet_amount(self, odds: int) -> Tuple[float, float, float]:
        """
        Calculate bet amount to provide target liquidity
        
        Args:
            odds: The odds we're betting at
            
        Returns:
            Tuple of (stake, expected_return, liquidity_offered)
        """
        if odds > 0:
            # Positive odds: bet $100 to win more
            # If we bet $100 at +116, we win $116, offering $116 liquidity
            stake = self.target_liquidity
            expected_return = stake * (odds / 100)
            liquidity_offered = expected_return
        else:
            # Negative odds: bet amount to win $100
            # If we bet at -107, we bet $107 to win $100, offering $100 liquidity
            expected_return = self.target_liquidity
            stake = expected_return * (abs(odds) / 100)
            liquidity_offered = expected_return
            
        return stake, expected_return, liquidity_offered
    
    def create_betting_instruction(
        self, 
        line_id: str,
        selection_name: str, 
        pinnacle_odds: int,
        outcome_name: str
    ) -> Optional[BettingInstruction]:
        """
        Create a betting instruction for a single outcome
        
        Args:
            line_id: ProphetX line ID to bet on
            selection_name: Name of selection (e.g., "Detroit Tigers") 
            pinnacle_odds: Pinnacle odds for this outcome
            outcome_name: What we're offering to users (e.g., "Tigers +107")
        """
        # Step 1: Improve Pinnacle odds for user offering
        improved_odds = self.improve_pinnacle_odds(pinnacle_odds)
        
        # Step 2: Calculate what odds we need to bet at
        hedge_odds = self.calculate_hedge_odds(improved_odds)
        
        # Step 3: Round to allowed ProphetX odds
        prophetx_odds = self.round_to_prophetx_odds(hedge_odds)
        
        # Step 4: Calculate bet amounts
        stake, expected_return, liquidity_offered = self.calculate_bet_amount(prophetx_odds)
        
        # Step 5: Create instruction
        instruction = BettingInstruction(
            line_id=line_id,
            selection_name=selection_name,
            odds=prophetx_odds,
            stake=stake,
            expected_return=expected_return,
            liquidity_offered=liquidity_offered,
            outcome_offered_to_users=outcome_name,
            odds_offered_to_users=improved_odds
        )
        
        return instruction
    
    def analyze_profitability(self, instructions: List[BettingInstruction]) -> Dict[str, float]:
        """Analyze profitability of a set of betting instructions"""
        if len(instructions) != 2:
            return {"error": "Need exactly 2 sides for profitability analysis"}
        
        instr1, instr2 = instructions
        
        # Get effective odds after commission
        eff_odds1 = self.apply_commission_adjustment(instr1.odds)
        eff_odds2 = self.apply_commission_adjustment(instr2.odds)
        
        # Determine plus and minus sides
        if instr1.odds > 0:
            plus_odds, minus_odds = eff_odds1, eff_odds2
            plus_stake, minus_stake = instr1.stake, instr2.stake
        else:
            plus_odds, minus_odds = eff_odds2, eff_odds1
            plus_stake, minus_stake = instr2.stake, instr1.stake
        
        # Calculate margin
        margin = plus_odds - abs(minus_odds)
        is_profitable = margin > 0
        
        return {
            "effective_plus_odds": plus_odds,
            "effective_minus_odds": minus_odds,
            "margin": margin,
            "is_profitable": is_profitable,
            "plus_stake": plus_stake,
            "minus_stake": minus_stake,
            "total_stake": plus_stake + minus_stake
        }
    
    def create_market_making_plan(
        self,
        event_match,  # EventMatch object
        market_match   # MarketMatchResult object  
    ) -> Optional[MarketMakingPlan]:
        """
        Create complete market making plan for an event
        
        Args:
            event_match: Matched event between Odds API and ProphetX
            market_match: Market matching results with line_id mappings
            
        Returns:
            MarketMakingPlan if profitable, None otherwise
        """
        odds_event = event_match.odds_api_event
        
        instructions = []
        
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
            
            # Create betting instructions for each outcome
            market_instructions = []
            
            for outcome_mapping in market_result.outcome_mappings:
                # Find corresponding Pinnacle outcome
                pinnacle_outcome = None
                for outcome in pinnacle_outcomes:
                    if outcome.name.lower() == outcome_mapping['odds_api_outcome_name'].lower():
                        pinnacle_outcome = outcome
                        break
                
                if not pinnacle_outcome:
                    continue
                
                # Create betting instruction
                instruction = self.create_betting_instruction(
                    line_id=outcome_mapping['prophetx_line_id'],
                    selection_name=outcome_mapping['prophetx_selection_name'],
                    pinnacle_odds=pinnacle_outcome.american_odds,
                    outcome_name=f"{pinnacle_outcome.name} {self.improve_pinnacle_odds(pinnacle_outcome.american_odds):+d}"
                )
                
                if instruction:
                    market_instructions.append(instruction)
            
            # Check profitability for this market
            if len(market_instructions) == 2:
                profitability = self.analyze_profitability(market_instructions)
                if profitability.get("is_profitable", False):
                    instructions.extend(market_instructions)
                else:
                    print(f"❌ Skipping unprofitable {market_type} market: margin = {profitability.get('margin', 0):.2f}")
        
        if not instructions:
            return None
        
        # Calculate overall metrics
        total_stake = sum(instr.stake for instr in instructions)
        max_exposure = max(instr.stake for instr in instructions)
        
        # Overall profitability analysis
        overall_profitability = {}
        if len(instructions) >= 2:
            # Group by market and analyze each
            markets = {}
            for instr in instructions:
                market_key = instr.outcome_offered_to_users.split()[0]  # Team name
                if market_key not in markets:
                    markets[market_key] = []
                markets[market_key].append(instr)
            
            overall_profitability["markets"] = {}
            all_profitable = True
            
            for market_name, market_instrs in markets.items():
                if len(market_instrs) == 2:
                    market_profit = self.analyze_profitability(market_instrs)
                    overall_profitability["markets"][market_name] = market_profit
                    if not market_profit.get("is_profitable", False):
                        all_profitable = False
            
            overall_profitability["all_markets_profitable"] = all_profitable
        
        plan = MarketMakingPlan(
            event_id=odds_event.event_id,
            event_name=odds_event.display_name,
            betting_instructions=instructions,
            total_stake=total_stake,
            max_exposure=max_exposure,
            is_profitable=overall_profitability.get("all_markets_profitable", False),
            profitability_analysis=overall_profitability,
            created_at=datetime.now(timezone.utc)
        )
        
        return plan

# Global strategy instance
market_making_strategy = MarketMakingStrategy()