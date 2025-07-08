#!/usr/bin/env python3
"""
Debug Workflow Script
Step-by-step testing of the market making pipeline to identify where it's failing
"""

import asyncio
import sys
import os

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.odds_api_service import odds_api_service
from app.services.prophetx_service import prophetx_service
from app.services.prophetx_events_service import prophetx_events_service
from app.services.event_matching_service import event_matching_service
from app.services.market_matching_service import market_matching_service
from app.services.market_making_strategy import market_making_strategy

async def debug_full_workflow():
    """Test the complete workflow step by step"""
    
    print("🔍 DEBUGGING MARKET MAKING WORKFLOW")
    print("=" * 50)
    
    # Step 1: Test API Connections
    print("\n1️⃣ TESTING API CONNECTIONS")
    print("-" * 30)
    
    try:
        # Test Odds API
        print("📊 Testing Odds API connection...")
        odds_test = await odds_api_service.test_connection()
        print(f"   Odds API: {'✅ Connected' if odds_test['success'] else '❌ Failed'}")
        if not odds_test['success']:
            print(f"   Error: {odds_test.get('error', 'Unknown error')}")
            return
        
        # Test ProphetX authentication
        print("🔐 Testing ProphetX authentication...")
        auth_result = await prophetx_service.authenticate()
        print(f"   ProphetX Auth: {'✅ Connected' if auth_result['success'] else '❌ Failed'}")
        if not auth_result['success']:
            print(f"   Error: Failed to authenticate with ProphetX")
            return
            
        # Test ProphetX connection
        print("⚡ Testing ProphetX API connection...")
        px_test = await prophetx_service.test_connection()
        print(f"   ProphetX API: {'✅ Connected' if px_test['success'] else '❌ Failed'}")
        if not px_test['success']:
            print(f"   Error: {px_test.get('error', 'Unknown error')}")
            return
            
    except Exception as e:
        print(f"❌ API Connection Error: {e}")
        return
    
    # Step 2: Get Events from Both Sources
    print("\n2️⃣ FETCHING EVENTS FROM BOTH SOURCES")
    print("-" * 30)
    
    try:
        # Get Odds API events
        print("📈 Fetching Odds API events...")
        odds_events = await odds_api_service.get_events()
        print(f"   Found {len(odds_events)} events from Odds API")
        
        if len(odds_events) == 0:
            print("❌ No events from Odds API - check sport filter or API")
            return
        
        # Show sample events
        for i, event in enumerate(odds_events[:3]):
            print(f"   {i+1}. {event.display_name} (starts in {event.starts_in_hours:.1f}h)")
            print(f"      Markets: {', '.join(event.get_available_markets())}")
        
        # Get ProphetX events
        print("\n⚡ Fetching ProphetX events...")
        px_events = await prophetx_events_service.get_all_upcoming_events()
        print(f"   Found {len(px_events)} events from ProphetX")
        
        if len(px_events) == 0:
            print("❌ No events from ProphetX - check tournament availability")
            return
            
        # Show sample events
        for i, event in enumerate(px_events[:3]):
            print(f"   {i+1}. {event.display_name} (starts in {event.starts_in_hours:.1f}h)")
            
    except Exception as e:
        print(f"❌ Event Fetching Error: {e}")
        return
    
    # Step 3: Test Event Matching
    print("\n3️⃣ TESTING EVENT MATCHING")
    print("-" * 30)
    
    try:
        print("🔗 Running event matching...")
        
        # Test with just first few events for debugging
        test_events = odds_events[:5]
        matching_attempts = await event_matching_service.find_matches_for_events(test_events)
        
        successful_matches = [attempt for attempt in matching_attempts if attempt.best_match]
        print(f"   Successful matches: {len(successful_matches)}/{len(test_events)}")
        
        if len(successful_matches) == 0:
            print("❌ No event matches found!")
            print("   Debugging first attempt:")
            if matching_attempts:
                first_attempt = matching_attempts[0]
                print(f"   Event: {first_attempt.odds_api_event.display_name}")
                print(f"   Reason: {first_attempt.no_match_reason}")
                if first_attempt.prophetx_matches:
                    best_px_match = first_attempt.prophetx_matches[0]
                    print(f"   Best PX match: {best_px_match[0].display_name} (confidence: {best_px_match[1]:.3f})")
            return
        
        # Show successful matches
        for match in successful_matches:
            print(f"   ✅ {match.odds_api_event.display_name} ↔ {match.prophetx_event.display_name}")
            print(f"      Confidence: {match.confidence_score:.3f}")
        
        # Use first match for further testing
        test_match = successful_matches[0]
        
    except Exception as e:
        print(f"❌ Event Matching Error: {e}")
        return
    
    # Step 4: Test Market Matching
    print("\n4️⃣ TESTING MARKET MATCHING")
    print("-" * 30)
    
    try:
        print(f"🎯 Testing market matching for: {test_match.odds_api_event.display_name}")
        
        market_match_result = await market_matching_service.match_event_markets(test_match)
        
        print(f"   Overall confidence: {market_match_result.overall_confidence:.3f}")
        print(f"   Ready for trading: {market_match_result.ready_for_trading}")
        print(f"   Successful markets: {len(market_match_result.successful_markets)}")
        print(f"   Issues: {market_match_result.issues}")
        
        if not market_match_result.ready_for_trading:
            print("❌ Event not ready for trading!")
            for market_match in market_match_result.market_matches:
                print(f"   Market {market_match.odds_api_market_type}: {market_match.match_status}")
                if market_match.issues:
                    print(f"      Issues: {market_match.issues}")
            return
        
        # Show successful market matches
        for market_match in market_match_result.successful_markets:
            print(f"   ✅ {market_match.odds_api_market_type}: {len(market_match.outcome_mappings)} outcomes mapped")
            
    except Exception as e:
        print(f"❌ Market Matching Error: {e}")
        return
    
    # Step 5: Test Strategy Creation
    print("\n5️⃣ TESTING STRATEGY CREATION")
    print("-" * 30)
    
    try:
        print("💡 Creating market making plan...")
        
        plan = market_making_strategy.create_market_making_plan(test_match, market_match_result)
        
        if not plan:
            print("❌ No market making plan created!")
            print("   Checking individual markets for profitability...")
            
            # Debug profitability for each market
            for market_match in market_match_result.successful_markets:
                print(f"   Checking {market_match.odds_api_market_type}...")
                
                # Get Pinnacle outcomes
                odds_event = test_match.odds_api_event
                if market_match.odds_api_market_type == "h2h" and odds_event.moneyline:
                    pinnacle_outcomes = odds_event.moneyline.outcomes
                elif market_match.odds_api_market_type == "spreads" and odds_event.spreads:
                    pinnacle_outcomes = odds_event.spreads.outcomes
                elif market_match.odds_api_market_type == "totals" and odds_event.totals:
                    pinnacle_outcomes = odds_event.totals.outcomes
                else:
                    continue
                
                if len(pinnacle_outcomes) == 2:
                    outcome1, outcome2 = pinnacle_outcomes
                    
                    # Calculate what we'd bet
                    hedge1 = market_making_strategy.calculate_exact_hedge_odds(outcome1.american_odds)
                    hedge2 = market_making_strategy.calculate_exact_hedge_odds(outcome2.american_odds)
                    
                    # Apply commission
                    eff1 = market_making_strategy.apply_commission_adjustment(hedge1)
                    eff2 = market_making_strategy.apply_commission_adjustment(hedge2)
                    
                    print(f"      {outcome1.name}: Pinnacle {outcome1.american_odds:+d} → We bet {hedge1:+d} (eff: {eff1:+.1f})")
                    print(f"      {outcome2.name}: Pinnacle {outcome2.american_odds:+d} → We bet {hedge2:+d} (eff: {eff2:+.1f})")
                    
                    # Check profitability
                    if eff1 > 0 and eff2 < 0:
                        plus_odds, minus_odds = eff1, eff2
                    elif eff2 > 0 and eff1 < 0:
                        plus_odds, minus_odds = eff2, eff1
                    else:
                        print(f"      ❌ Both sides same sign: {eff1:+.1f}, {eff2:+.1f}")
                        continue
                    
                    arbitrage = market_making_strategy.calculate_arbitrage_bets(plus_odds, minus_odds)
                    print(f"      Arbitrage: ${arbitrage.guaranteed_profit:.2f} profit on ${arbitrage.total_investment:.2f}")
                    print(f"      Profitable: {arbitrage.is_profitable}")
            return
        
        print(f"   ✅ Plan created successfully!")
        print(f"   Event: {plan.event_name}")
        print(f"   Total betting instructions: {len(plan.betting_instructions)}")
        print(f"   Is profitable: {plan.is_profitable}")
        print(f"   Total stake required: ${plan.total_stake:.2f}")
        
        # Show betting instructions
        print("\n   📋 BETTING INSTRUCTIONS:")
        for i, instruction in enumerate(plan.betting_instructions):
            print(f"      {i+1}. {instruction.selection_name}")
            print(f"         Bet: {instruction.odds:+d} for ${instruction.stake:.2f}")
            print(f"         Offers users: {instruction.outcome_offered_to_users}")
            print(f"         Line ID: {instruction.line_id}")
            print(f"         Plus side: {instruction.is_plus_side}")
        
        # Show profitability analysis
        print(f"\n   💰 PROFITABILITY ANALYSIS:")
        for market_type, analysis in plan.profitability_analysis.get("markets", {}).items():
            print(f"      {market_type}: ${analysis['guaranteed_profit']:.2f} profit ({analysis['profit_margin']:.2f}%)")
        
    except Exception as e:
        print(f"❌ Strategy Creation Error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 6: Test Bet Placement (Dry Run)
    print("\n6️⃣ TESTING BET PLACEMENT (DRY RUN)")
    print("-" * 30)
    
    try:
        print("🎯 Simulating bet placement...")
        
        from app.services.market_maker_service import market_maker_service
        
        # Create a mock managed event
        from app.models.market_models import ManagedEvent
        mock_event = ManagedEvent(
            event_id=str(test_match.prophetx_event.event_id),
            sport=test_match.prophetx_event.sport_name,
            home_team=test_match.prophetx_event.home_team,
            away_team=test_match.prophetx_event.away_team,
            commence_time=test_match.prophetx_event.commence_time,
            max_exposure=market_maker_service.settings.max_exposure_per_event
        )
        
        # Test placing each bet
        for instruction in plan.betting_instructions:
            print(f"   Placing bet: {instruction.selection_name} {instruction.odds:+d} for ${instruction.stake:.2f}")
            
            success = await market_maker_service._place_line_bet(instruction, instruction.stake, mock_event)
            
            if success:
                print(f"      ✅ Bet placed successfully")
            else:
                print(f"      ❌ Bet placement failed")
        
        print(f"\n   Total bets created: {len(market_maker_service.all_bets)}")
        
        # Show created bets
        for bet_id, bet in market_maker_service.all_bets.items():
            print(f"      {bet.selection_name}: {bet.odds:+d} for ${bet.stake:.2f} (Status: {bet.status.value})")
        
    except Exception as e:
        print(f"❌ Bet Placement Error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n✅ WORKFLOW DEBUGGING COMPLETE!")
    print("=" * 50)
    print("If you see this message, the workflow should be working.")
    print("Check the dry run bets above to see what would be placed in live mode.")

async def main():
    """Run the debugging workflow"""
    await debug_full_workflow()

if __name__ == "__main__":
    asyncio.run(main())