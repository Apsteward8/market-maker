#!/usr/bin/env python3
"""
Simple API Test Script
Test the market making workflow through API endpoints
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8001"

def test_api_endpoint(method, endpoint, params=None, data=None):
    """Test a single API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, params=params)
        elif method.upper() == "POST":
            response = requests.post(url, params=params, json=data)
        
        print(f"{method.upper()} {endpoint}")
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Success")
            return result
        else:
            print(f"❌ Failed: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def main():
    """Run step-by-step API tests"""
    
    print("🔍 TESTING MARKET MAKING WORKFLOW VIA API")
    print("=" * 50)
    
    # Step 1: Test basic health
    print("\n1️⃣ TESTING API HEALTH")
    print("-" * 30)
    health = test_api_endpoint("GET", "/health")
    if not health:
        print("❌ API not responding - make sure server is running with: python run.py")
        return
    
    # Step 2: Test authentication
    print("\n2️⃣ TESTING AUTHENTICATION")
    print("-" * 30)
    auth = test_api_endpoint("POST", "/auth/login")
    if not auth or not auth.get("success"):
        print("❌ Authentication failed - check ProphetX credentials")
        return
    
    # Step 3: Test connections
    print("\n3️⃣ TESTING API CONNECTIONS")
    print("-" * 30)
    connections = test_api_endpoint("POST", "/auth/test")
    if not connections or not connections.get("success"):
        print("❌ API connections failed")
        return
    
    print(f"Odds API: {'✅' if connections['data']['odds_api']['success'] else '❌'}")
    print(f"ProphetX: {'✅' if connections['data']['prophetx']['success'] else '❌'}")
    
    # Step 4: Get events from both sources
    print("\n4️⃣ FETCHING EVENTS")
    print("-" * 30)
    
    # Odds API events
    odds_events = test_api_endpoint("GET", "/matching/odds-api-events")
    if not odds_events:
        print("❌ Failed to get Odds API events")
        return
    print(f"Odds API events: {len(odds_events)}")
    
    # ProphetX events  
    px_events = test_api_endpoint("GET", "/matching/prophetx-events")
    if not px_events:
        print("❌ Failed to get ProphetX events")
        return
    print(f"ProphetX events: {len(px_events)}")
    
    if len(odds_events) == 0:
        print("❌ No Odds API events found - check sport filter or time window")
        return
        
    if len(px_events) == 0:
        print("❌ No ProphetX events found - check tournament availability")
        return
    
    # Step 5: Test event matching
    print("\n5️⃣ TESTING EVENT MATCHING")
    print("-" * 30)
    matching = test_api_endpoint("POST", "/matching/find-matches")
    if not matching:
        print("❌ Event matching failed")
        return
    
    successful_matches = [attempt for attempt in matching if attempt.get("best_match")]
    print(f"Successful matches: {len(successful_matches)}")
    
    if len(successful_matches) == 0:
        print("❌ No event matches found!")
        print("Debugging first attempt...")
        if matching:
            first = matching[0]
            print(f"Event: {first['odds_api_event']['display_name']}")
            print(f"Reason: {first.get('no_match_reason', 'Unknown')}")
        return
    
    # Show matches
    for match in successful_matches[:3]:
        odds_event = match["odds_api_event"]
        px_event = match["best_match"]["prophetx_event"]
        confidence = match["best_match"]["confidence_score"]
        print(f"✅ {odds_event['display_name']} ↔ {px_event['display_name']} ({confidence:.3f})")
    
    # Step 6: Test market matching
    print("\n6️⃣ TESTING MARKET MATCHING")
    print("-" * 30)
    
    # Use first successful match
    test_event_id = successful_matches[0]["odds_api_event"]["event_id"]
    market_matching = test_api_endpoint("POST", f"/matching/test-market-matching/{test_event_id}")
    
    if not market_matching or not market_matching.get("success"):
        print("❌ Market matching failed")
        return
    
    market_data = market_matching["data"]
    print(f"Overall confidence: {market_data['event_info']['overall_confidence']:.3f}")
    print(f"Ready for trading: {market_data['event_info']['ready_for_trading']}")
    print(f"Successful markets: {market_data['summary']['successful_markets']}")
    
    if not market_data['event_info']['ready_for_trading']:
        print("❌ Event not ready for trading!")
        for market in market_data['market_matches']:
            print(f"   {market['odds_api_market_type']}: {market['match_status']}")
            if market.get('issues'):
                print(f"      Issues: {market['issues']}")
        return
    
    # Step 7: Test strategy creation
    print("\n7️⃣ TESTING STRATEGY CREATION")
    print("-" * 30)
    
    strategy = test_api_endpoint("POST", f"/matching/test-strategy/{test_event_id}")
    
    if not strategy or not strategy.get("success"):
        print("❌ Strategy creation failed")
        if strategy:
            print(f"Error: {strategy.get('message', 'Unknown error')}")
        return
    
    strategy_data = strategy["data"]
    print(f"Event: {strategy_data['event_name']}")
    print(f"Profitable: {strategy_data['is_profitable']}")
    print(f"Total stake: {strategy_data['total_stake_required']}")
    print(f"Betting instructions: {len(strategy_data['betting_instructions'])}")
    
    # Show betting instructions
    print("\nBetting Instructions:")
    for i, instruction in enumerate(strategy_data['betting_instructions']):
        bet_info = instruction['our_bet']
        offer_info = instruction['offer_to_users']
        print(f"   {i+1}. {instruction['selection_name']}")
        print(f"      Our bet: {bet_info['odds']:+d} for {bet_info['stake']}")
        print(f"      Offer users: {offer_info['outcome']}")
    
    # Step 8: Start market making 
    print("\n8️⃣ TESTING MARKET MAKING START")
    print("-" * 30)
    
    start_result = test_api_endpoint("POST", "/markets/start")
    if not start_result or not start_result.get("success"):
        print("❌ Failed to start market making")
        return
    
    print("✅ Market making started successfully!")
    
    # Wait a moment for processing
    print("⏱️  Waiting 10 seconds for initial processing...")
    time.sleep(10)
    
    # Step 9: Check status and positions
    print("\n9️⃣ CHECKING RESULTS")
    print("-" * 30)
    
    status = test_api_endpoint("GET", "/markets/status")
    if status and status.get("success"):
        data = status["data"]
        print(f"System status: {data['system_status']}")
        print(f"Events managed: {data['events_managed']}")
        print(f"Total bets: {data['total_bets']}")
        print(f"Active bets: {data['active_bets']}")
        
        incremental = data.get('incremental_betting', {})
        print(f"Lines with positions: {incremental.get('lines_with_positions', 0)}")
    
    positions = test_api_endpoint("GET", "/markets/positions")
    if positions and positions.get("success"):
        data = positions["data"]
        print(f"Total lines: {data['total_lines']}")
        print(f"Total stake: ${data['total_stake_across_all_lines']:.2f}")
        
        if data['lines_detail']:
            print("Line details:")
            for line_id, details in list(data['lines_detail'].items())[:3]:
                print(f"   {line_id}: ${details['total_stake']:.2f} ({details['number_of_bets']} bets)")
    
    print("\n✅ WORKFLOW TEST COMPLETE!")
    print("=" * 50)
    
    if status and status.get("success") and status["data"]["total_bets"] > 0:
        print("🎉 SUCCESS: Bets are being placed!")
        print("Check /markets/positions for detailed position information")
    else:
        print("⚠️  No bets placed yet - this could be normal if:")
        print("   1. Still processing (wait a bit longer)")
        print("   2. No profitable opportunities found")
        print("   3. Dry run mode is enabled")

if __name__ == "__main__":
    main()