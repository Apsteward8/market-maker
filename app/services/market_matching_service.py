#!/usr/bin/env python3
"""
Market Matching Service
Matches markets and outcomes between Odds API and ProphetX
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from difflib import SequenceMatcher

from app.models.odds_models import ProcessedEvent, ProcessedMarket, ProcessedOutcome
from app.services.prophetx_events_service import ProphetXEvent
from app.services.prophetx_service import prophetx_service
from app.services.event_matching_service import EventMatch

# Import the new market models
from app.models.prophetx_market_models import (
    ProphetXLine, ProphetXRawMarket, ProphetXEventMarkets,
    MarketMatchResult, OutcomeMapping, EventMarketsMatch
)

class MarketMatchingService:
    """Service for matching markets between Odds API and ProphetX"""
    
    def __init__(self):
        # Cache for ProphetX market data
        self.markets_cache: Dict[int, ProphetXEventMarkets] = {}
        self.cache_ttl = 300  # 5 minutes
        
        # Market type mappings between platforms
        self.market_type_mappings = {
            "h2h": "moneyline",
            "spreads": "spread", 
            "totals": "total"
        }
        
        # Name normalization patterns
        self.team_name_patterns = {
            r'\b(red sox|redsox)\b': 'red sox',
            r'\b(white sox|whitesox)\b': 'white sox',
            r'\b(blue jays|bluejays)\b': 'blue jays',
            r'\btampa bay\b': 'rays',  # Sometimes just "Rays" vs "Tampa Bay Rays"
        }
    
    async def fetch_prophetx_markets(self, event_id: int) -> Optional[ProphetXEventMarkets]:
        """
        Fetch and parse ProphetX markets for a specific event
        
        Args:
            event_id: ProphetX event ID
            
        Returns:
            Parsed ProphetX markets or None if failed
        """
        print(f"📊 Fetching ProphetX markets for event {event_id}...")
        
        try:
            headers = await prophetx_service.get_auth_headers()
            url = f"{prophetx_service.base_url}/partner/v2/mm/get_markets"
            params = {"event_id": event_id}
            
            import requests
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                raw_data = response.json()
                
                # Parse the ProphetX market response
                event_markets = self._parse_prophetx_markets(event_id, raw_data)
                
                if event_markets:
                    print(f"✅ Found {len(event_markets.markets)} markets for event {event_id}")
                    
                    # Log market summary
                    for market in event_markets.markets:
                        print(f"   📈 {market.market_type}: {len(market.lines)} lines")
                    
                    # Cache the results
                    self.markets_cache[event_id] = event_markets
                    
                return event_markets
                
            else:
                print(f"❌ Error fetching markets for event {event_id}: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Exception fetching markets for event {event_id}: {e}")
            return None
    
    def _parse_prophetx_markets(self, event_id: int, raw_data: Dict[str, Any]) -> Optional[ProphetXEventMarkets]:
        """
        Parse raw ProphetX API response into our market models
        
        ProphetX structure:
        {
          "data": {
            "markets": [
              {
                "id": 251,
                "name": "Moneyline", 
                "type": "moneyline",
                "category_name": "Game Lines",  // FILTER FOR THIS
                "selections": [
                  [{"line_id": "...", "name": "Detroit Tigers", "odds": null}],
                  [{"line_id": "...", "name": "Tampa Bay Rays", "odds": 100}]
                ]
              }
            ]
          }
        }
        """
        try:
            data_section = raw_data.get('data', {})
            markets_data = data_section.get('markets', [])
            
            if not markets_data:
                print(f"⚠️  No markets found in ProphetX response for event {event_id}")
                return None
            
            print(f"📊 Found {len(markets_data)} raw markets for event {event_id}")
            
            # **NEW**: Filter for Game Lines only
            game_line_markets = []
            for market_data in markets_data:
                category_name = market_data.get('category_name', '')
                if category_name == 'Game Lines':
                    game_line_markets.append(market_data)
                    print(f"   ✅ Found Game Line market: {market_data.get('name', 'Unknown')} (ID: {market_data.get('id')})")
                else:
                    print(f"   ⏭️  Skipping non-Game Line market: {market_data.get('name', 'Unknown')} (Category: {category_name})")
            
            if not game_line_markets:
                print(f"⚠️  No Game Lines markets found for event {event_id}")
                return None
            
            print(f"🎯 Processing {len(game_line_markets)} Game Lines markets...")
            
            parsed_markets = []
            
            for market_data in game_line_markets:
                try:
                    # Parse individual market
                    market = self._parse_single_market(event_id, market_data)
                    if market:
                        parsed_markets.append(market)
                        print(f"   ✅ Parsed market: {market.market_type} ({len(market.lines)} lines)")
                        
                        # Log each line for debugging
                        for line in market.lines:
                            odds_str = f"{line.odds:+d}" if line.odds is not None else "null"
                            point_str = f" @ {line.point}" if line.point else ""
                            print(f"      📝 {line.selection_name}: {odds_str}{point_str} (line_id: {line.line_id})")
                        
                except Exception as e:
                    print(f"⚠️  Error parsing market {market_data.get('id', 'unknown')}: {e}")
                    continue
            
            if not parsed_markets:
                print(f"⚠️  No valid Game Lines markets parsed for event {event_id}")
                return None
            
            # Create event markets object
            event_markets = ProphetXEventMarkets(
                event_id=event_id,
                event_name=f"Event {event_id}",
                markets=parsed_markets,
                last_updated=datetime.now(timezone.utc),
                raw_response=raw_data
            )
            
            print(f"🎉 Successfully parsed {len(parsed_markets)} Game Lines markets for event {event_id}")
            return event_markets
            
        except Exception as e:
            print(f"❌ Error parsing ProphetX markets response: {e}")
            return None
    
    def _parse_single_market(self, event_id: int, market_data: Dict[str, Any]) -> Optional[ProphetXRawMarket]:
        """
        Parse a single ProphetX market
        
        ProphetX markets can have two structures:
        1. Simple markets with direct 'selections' 
        2. Complex markets with 'market_lines' containing multiple lines
        """
        try:
            # Extract basic market info
            market_id = str(market_data.get('id', 'unknown'))
            market_name = market_data.get('name', 'Unknown Market')
            market_type = market_data.get('type', market_data.get('sub_type', 'unknown'))
            status = market_data.get('status', 'active')
            
            print(f"   🔧 Parsing market {market_id}: {market_name} ({market_type})")
            
            parsed_lines = []
            
            # Check if this market has market_lines (complex market)
            if 'market_lines' in market_data:
                # Complex market with multiple lines
                market_lines = market_data.get('market_lines', [])
                for line_data in market_lines:
                    lines_from_market_line = self._parse_market_line(line_data)
                    parsed_lines.extend(lines_from_market_line)
            
            # Check if this market has direct selections (simple market)
            elif 'selections' in market_data:
                # Simple market with direct selections
                selections = market_data.get('selections', [])
                lines_from_selections = self._parse_selections(selections, market_data.get('line', 0))
                parsed_lines.extend(lines_from_selections)
            
            # **CHANGED**: Include ALL lines, but separate available vs unavailable
            all_lines = parsed_lines
            available_lines = [line for line in parsed_lines if line.odds is not None and line.odds != 0]
            
            print(f"      📊 Total lines: {len(all_lines)}, Available: {len(available_lines)}")
            
            # **CHANGED**: Return market if it has ANY lines (not just available ones)
            if not all_lines:
                print(f"      ❌ No lines found for market {market_id}")
                return None
            
            # **CHANGED**: Use all_lines instead of just available_lines
            market = ProphetXRawMarket(
                market_id=market_id,
                market_type=self._normalize_market_type(market_type),
                event_id=event_id,
                name=market_name,
                status=status,
                lines=all_lines  # Include all lines, not just available ones
            )
            
            return market
            
        except Exception as e:
            print(f"❌ Error parsing single market: {e}")
            return None
    
    def _parse_market_line(self, line_data: Dict[str, Any]) -> List[ProphetXLine]:
        """Parse a market_line (used in complex markets)"""
        try:
            line_point = line_data.get('line', 0)
            selections = line_data.get('selections', [])
            
            return self._parse_selections(selections, line_point)
            
        except Exception as e:
            print(f"❌ Error parsing market line: {e}")
            return []
    
    def _parse_selections(self, selections: List[List[Dict]], default_point: float = 0) -> List[ProphetXLine]:
        """
        Parse selections array from ProphetX
        
        selections is an array of arrays:
        [
          [{"line_id": "...", "name": "Detroit Tigers", "odds": 105}],
          [{"line_id": "...", "name": "Tampa Bay Rays", "odds": -115}]
        ]
        """
        parsed_lines = []
        
        try:
            for selection_group in selections:
                # Each selection_group is an array, usually with one item
                if not isinstance(selection_group, list) or not selection_group:
                    continue
                
                # Take the first (and usually only) selection in the group
                selection = selection_group[0]
                
                line = self._parse_single_selection(selection, default_point)
                if line:
                    parsed_lines.append(line)
            
            return parsed_lines
            
        except Exception as e:
            print(f"❌ Error parsing selections: {e}")
            return []
    
    def _parse_single_selection(self, selection_data: Dict[str, Any], default_point: float = 0) -> Optional[ProphetXLine]:
        """Parse a single selection into a ProphetXLine"""
        try:
            # Extract basic fields
            line_id = selection_data.get('line_id', 'unknown')
            name = selection_data.get('name', selection_data.get('display_name', 'Unknown'))
            odds = selection_data.get('odds')
            
            # Handle point/line - can be in 'line' or 'display_line' 
            point = selection_data.get('line', default_point)
            if isinstance(point, str):
                try:
                    point = float(point)
                except:
                    point = default_point
            
            # **CHANGED**: Don't skip lines with null odds, include them but mark as inactive
            if odds is None:
                # Line exists but no odds available
                status = 'inactive'
                odds_value = 0  # Use 0 as placeholder for null odds
            else:
                # Line has odds available
                status = 'active'
                # Convert odds to int if it's a number
                if isinstance(odds, (int, float)):
                    odds_value = int(odds)
                else:
                    # Invalid odds format
                    return None
            
            line = ProphetXLine(
                line_id=str(line_id),
                selection_name=str(name),
                odds=odds_value,
                point=float(point) if point != 0 else None,
                status=status
            )
            
            return line
            
        except Exception as e:
            print(f"❌ Error parsing single selection: {e}")
            return None
    
    def _normalize_market_type(self, market_type: str) -> str:
        """Normalize ProphetX market types to our standard types"""
        if not market_type:
            return 'unknown'
        
        market_type = market_type.lower()
        
        # Map ProphetX types to our standard types
        type_mappings = {
            'moneyline': 'moneyline',
            'spread': 'spread',
            'total': 'total',
            'h2h': 'moneyline',
            # Add more mappings as needed
        }
        
        return type_mappings.get(market_type, market_type)
    
    async def match_event_markets(self, event_match: EventMatch) -> EventMarketsMatch:
        """
        Match all markets for a specific event between Odds API and ProphetX
        """
        odds_event = event_match.odds_api_event
        prophetx_event = event_match.prophetx_event
        
        print(f"🎯 Matching markets for: {odds_event.display_name}")
        
        # Fetch ProphetX markets
        prophetx_markets = await self.fetch_prophetx_markets(prophetx_event.event_id)
        
        if not prophetx_markets:
            # No ProphetX markets available
            return EventMarketsMatch(
                odds_api_event_id=odds_event.event_id,
                prophetx_event_id=prophetx_event.event_id,
                event_display_name=odds_event.display_name,
                market_matches=[],
                overall_confidence=0.0,
                ready_for_trading=False,
                issues=["Could not fetch ProphetX markets"],
                matched_at=datetime.now(timezone.utc)
            )
        
        # Match each market type
        market_matches = []
        
        # Match moneyline
        if odds_event.moneyline:
            match_result = await self._match_moneyline_market(
                odds_event.moneyline, 
                prophetx_markets,
                odds_event.home_team,
                odds_event.away_team
            )
            market_matches.append(match_result)
        
        # Match spreads
        if odds_event.spreads:
            match_result = await self._match_spreads_market(
                odds_event.spreads,
                prophetx_markets,
                odds_event.home_team,
                odds_event.away_team
            )
            market_matches.append(match_result)
        
        # Match totals
        if odds_event.totals:
            match_result = await self._match_totals_market(
                odds_event.totals,
                prophetx_markets
            )
            market_matches.append(match_result)
        
        # Calculate overall assessment
        successful_matches = [m for m in market_matches if m.is_matched]
        overall_confidence = sum(m.confidence_score for m in market_matches) / len(market_matches) if market_matches else 0
        
        # ✅ FIXED: Distinguish between blocking issues and market making opportunities
        blocking_issues = []
        market_making_opportunities = []
        
        for match in market_matches:
            for issue in match.issues:
                if "market making opportunities" in issue.lower() or "✅" in issue:
                    market_making_opportunities.append(issue)
                else:
                    blocking_issues.append(issue)
        
        # ✅ UPDATED: Only blocking issues prevent trading
        ready_for_trading = (
            len(successful_matches) > 0 and  # At least one market matched
            overall_confidence >= 0.7 and   # High confidence
            len(blocking_issues) == 0        # No BLOCKING issues (market making opportunities are OK!)
        )
        
        # ✅ ENHANCED: Separate reporting of blocking vs opportunity issues
        all_issues = blocking_issues + market_making_opportunities
        
        print(f"📊 Market matching summary:")
        print(f"   Successful matches: {len(successful_matches)}/{len(market_matches)}")
        print(f"   Overall confidence: {overall_confidence:.3f}")
        print(f"   Blocking issues: {len(blocking_issues)}")
        print(f"   Market making opportunities: {len(market_making_opportunities)}")
        print(f"   Ready for trading: {ready_for_trading}")
        
        if market_making_opportunities:
            print(f"🟡 Market making opportunities found:")
            for opp in market_making_opportunities:
                print(f"     {opp}")
        
        if blocking_issues:
            print(f"❌ Blocking issues:")
            for issue in blocking_issues:
                print(f"     {issue}")
        
        return EventMarketsMatch(
            odds_api_event_id=odds_event.event_id,
            prophetx_event_id=prophetx_event.event_id,
            event_display_name=odds_event.display_name,
            market_matches=market_matches,
            overall_confidence=overall_confidence,
            ready_for_trading=ready_for_trading,
            issues=all_issues,
            matched_at=datetime.now(timezone.utc)
        )
    
    async def _match_moneyline_market(
        self, 
        odds_api_market: ProcessedMarket,
        prophetx_markets: ProphetXEventMarkets,
        home_team: str,
        away_team: str
    ) -> MarketMatchResult:
        """Match moneyline market between platforms - INCLUDE INACTIVE LINES"""
        
        # Find ProphetX moneyline market
        px_market = prophetx_markets.get_moneyline_market()
        
        if not px_market:
            return MarketMatchResult(
                odds_api_market_type="h2h",
                confidence_score=0.0,
                match_status="failed",
                issues=["No moneyline market found on ProphetX"]
            )
        
        # Match outcomes
        outcome_mappings = []
        
        for odds_outcome in odds_api_market.outcomes:
            # Find matching ProphetX line
            px_line = self._find_matching_line(
                odds_outcome.name,
                px_market.lines,
                home_team,
                away_team
            )
            
            if px_line:
                mapping = OutcomeMapping(
                    odds_api_outcome_name=odds_outcome.name,
                    odds_api_odds=odds_outcome.american_odds,
                    prophetx_line_id=px_line.line_id,
                    prophetx_selection_name=px_line.selection_name,
                    prophetx_odds=px_line.american_odds,  # Will be 0 for inactive lines
                    confidence_score=self._calculate_name_similarity(odds_outcome.name, px_line.selection_name),
                    name_similarity=self._calculate_name_similarity(odds_outcome.name, px_line.selection_name)
                )
                
                # Convert to dict and add status information
                mapping_dict = mapping.dict()
                mapping_dict['prophetx_line_active'] = px_line.is_active
                mapping_dict['prophetx_line_status'] = px_line.status
                if not px_line.is_active:
                    mapping_dict['note'] = 'Line available for betting but no current liquidity'
                    mapping_dict['market_making_opportunity'] = True
                else:
                    mapping_dict['market_making_opportunity'] = False
                
                outcome_mappings.append(mapping_dict)
        
        # Assess match quality
        match_status = "matched" if len(outcome_mappings) == len(odds_api_market.outcomes) else "partial"
        confidence = sum(m["confidence_score"] for m in outcome_mappings) / len(outcome_mappings) if outcome_mappings else 0
        
        # ✅ FIXED: Separate blocking issues from market making opportunities
        blocking_issues = []
        if len(outcome_mappings) < len(odds_api_market.outcomes):
            blocking_issues.append(f"Only matched {len(outcome_mappings)}/{len(odds_api_market.outcomes)} outcomes")
        
        return MarketMatchResult(
            odds_api_market_type="h2h",
            prophetx_market_id=px_market.market_id,
            prophetx_market_type=px_market.market_type,
            outcome_mappings=outcome_mappings,
            confidence_score=confidence,
            match_status=match_status,
            issues=blocking_issues  # No market making opportunities added to issues
        )

    async def _match_spreads_market(
        self,
        odds_api_market: ProcessedMarket,
        prophetx_markets: ProphetXEventMarkets,
        home_team: str,
        away_team: str
    ) -> MarketMatchResult:
        """Match spreads market between platforms - INCLUDE INACTIVE LINES"""
        
        px_market = prophetx_markets.get_spread_market()
        
        if not px_market:
            return MarketMatchResult(
                odds_api_market_type="spreads",
                confidence_score=0.0,
                match_status="failed",
                issues=["No spread market found on ProphetX"]
            )
        
        outcome_mappings = []
        
        for odds_outcome in odds_api_market.outcomes:
            # For spreads, need to match both name and point
            px_line = self._find_matching_spread_line(
                odds_outcome.name,
                odds_outcome.point,
                px_market.lines,
                home_team,
                away_team
            )
            
            if px_line:
                mapping = OutcomeMapping(
                    odds_api_outcome_name=odds_outcome.name,
                    odds_api_odds=odds_outcome.american_odds,
                    odds_api_point=odds_outcome.point,
                    prophetx_line_id=px_line.line_id,
                    prophetx_selection_name=px_line.selection_name,
                    prophetx_odds=px_line.american_odds,  # Will be 0 for inactive lines
                    prophetx_point=px_line.point,
                    confidence_score=self._calculate_spread_match_confidence(odds_outcome, px_line),
                    name_similarity=self._calculate_name_similarity(odds_outcome.name, px_line.selection_name),
                    point_match=abs((odds_outcome.point or 0) - (px_line.point or 0)) <= 0.1
                )
                
                # Convert to dict and add status information
                mapping_dict = mapping.dict()
                mapping_dict['prophetx_line_active'] = px_line.is_active
                mapping_dict['prophetx_line_status'] = px_line.status
                if not px_line.is_active:
                    mapping_dict['note'] = 'Line available for betting but no current liquidity'
                    mapping_dict['market_making_opportunity'] = True
                else:
                    mapping_dict['market_making_opportunity'] = False
                
                outcome_mappings.append(mapping_dict)
        
        match_status = "matched" if len(outcome_mappings) == len(odds_api_market.outcomes) else "partial"
        confidence = sum(m["confidence_score"] for m in outcome_mappings) / len(outcome_mappings) if outcome_mappings else 0
        
        # ✅ FIXED: Separate blocking issues from market making opportunities
        blocking_issues = []
        if len(outcome_mappings) < len(odds_api_market.outcomes):
            blocking_issues.append(f"Only matched {len(outcome_mappings)}/{len(odds_api_market.outcomes)} spread outcomes")
        
        return MarketMatchResult(
            odds_api_market_type="spreads",
            prophetx_market_id=px_market.market_id,
            prophetx_market_type=px_market.market_type,
            outcome_mappings=outcome_mappings,
            confidence_score=confidence,
            match_status=match_status,
            issues=blocking_issues  # No market making opportunities added to issues
        )
    
    async def _match_totals_market(
        self,
        odds_api_market: ProcessedMarket,
        prophetx_markets: ProphetXEventMarkets
    ) -> MarketMatchResult:
        """Match totals (over/under) market between platforms - INCLUDE INACTIVE LINES"""
        
        px_market = prophetx_markets.get_total_market()
        
        if not px_market:
            return MarketMatchResult(
                odds_api_market_type="totals",
                confidence_score=0.0,
                match_status="failed",
                issues=["No total market found on ProphetX"]
            )
        
        outcome_mappings = []
        
        for odds_outcome in odds_api_market.outcomes:
            # For totals, match "Over"/"Under" with the same point value
            px_line = self._find_matching_total_line(
                odds_outcome.name,
                odds_outcome.point,
                px_market.lines
            )
            
            if px_line:
                mapping = OutcomeMapping(
                    odds_api_outcome_name=odds_outcome.name,
                    odds_api_odds=odds_outcome.american_odds,
                    odds_api_point=odds_outcome.point,
                    prophetx_line_id=px_line.line_id,
                    prophetx_selection_name=px_line.selection_name,
                    prophetx_odds=px_line.american_odds,  # Will be 0 for inactive lines
                    prophetx_point=px_line.point,
                    confidence_score=self._calculate_total_match_confidence(odds_outcome, px_line),
                    name_similarity=self._calculate_name_similarity(odds_outcome.name, px_line.selection_name),
                    point_match=abs((odds_outcome.point or 0) - (px_line.point or 0)) <= 0.1
                )
                
                # Convert to dict and add status information
                mapping_dict = mapping.dict()
                mapping_dict['prophetx_line_active'] = px_line.is_active
                mapping_dict['prophetx_line_status'] = px_line.status
                if not px_line.is_active:
                    mapping_dict['note'] = 'Line available for betting but no current liquidity'
                    mapping_dict['market_making_opportunity'] = True
                else:
                    mapping_dict['market_making_opportunity'] = False
                
                outcome_mappings.append(mapping_dict)
        
        # ✅ UPDATED: Consider it a successful match even if lines are inactive
        # The presence of valid line_ids means we can place bets
        match_status = "matched" if len(outcome_mappings) == len(odds_api_market.outcomes) else "partial"
        confidence = sum(m["confidence_score"] for m in outcome_mappings) / len(outcome_mappings) if outcome_mappings else 0
        
        # ✅ FIXED: Separate blocking issues from market making opportunities
        blocking_issues = []        
        if len(outcome_mappings) < len(odds_api_market.outcomes):
            blocking_issues.append(f"Only matched {len(outcome_mappings)}/{len(odds_api_market.outcomes)} total outcomes")
        
        return MarketMatchResult(
            odds_api_market_type="totals",
            prophetx_market_id=px_market.market_id,
            prophetx_market_type=px_market.market_type,
            outcome_mappings=outcome_mappings,
            confidence_score=confidence,
            match_status=match_status,
            issues=blocking_issues  # This will be filtered in match_event_markets
        )
    
    def _find_matching_line(
        self,
        outcome_name: str,
        prophetx_lines: List[ProphetXLine],
        home_team: str,
        away_team: str
    ) -> Optional[ProphetXLine]:
        """Find matching ProphetX line for an outcome name - INCLUDE INACTIVE LINES"""
        
        normalized_name = self._normalize_selection_name(outcome_name)
        
        best_match = None
        best_similarity = 0.0
        
        for line in prophetx_lines:
            # ✅ FIXED: Don't filter by is_active - we WANT inactive lines for market making!
            # The line_id being present means it's available for betting
            
            line_name = self._normalize_selection_name(line.selection_name)
            similarity = self._calculate_name_similarity(normalized_name, line_name)
            
            if similarity > best_similarity and similarity >= 0.8:  # Require high similarity
                best_similarity = similarity
                best_match = line
        
        return best_match

    def _find_matching_total_line(
        self,
        outcome_name: str,
        point: Optional[float],
        prophetx_lines: List[ProphetXLine]
    ) -> Optional[ProphetXLine]:
        """Find matching ProphetX total line - INCLUDE INACTIVE LINES"""
        
        if point is None:
            return None
        
        normalized_name = outcome_name.lower().strip()
        
        for line in prophetx_lines:
            # ✅ FIXED: Don't filter by is_active - inactive lines are OPPORTUNITIES!
            
            line_name = line.selection_name.lower().strip()
            
            # Check both name and point match
            name_match = (
                (normalized_name == "over" and "over" in line_name) or
                (normalized_name == "under" and "under" in line_name)
            )
            
            point_match = (
                line.point is not None and 
                abs(line.point - point) <= 0.1
            )
            
            if name_match and point_match:
                return line
        
        return None

    def _find_matching_spread_line(
        self,
        outcome_name: str,
        point: Optional[float],
        prophetx_lines: List[ProphetXLine],
        home_team: str,
        away_team: str
    ) -> Optional[ProphetXLine]:
        """Find matching ProphetX spread line - INCLUDE INACTIVE LINES"""
        
        if point is None:
            return None
        
        # First filter by point value (include both active and inactive)
        point_matches = [line for line in prophetx_lines 
                        if line.point is not None 
                        and abs(line.point - point) <= 0.1]
        
        if not point_matches:
            return None
        
        # Then find best name match among point matches
        return self._find_matching_line(outcome_name, point_matches, home_team, away_team)
    
    def _normalize_selection_name(self, name: str) -> str:
        """Normalize selection name for comparison"""
        if not name:
            return ""
        
        normalized = name.lower().strip()
        
        # Apply team name patterns
        for pattern, replacement in self.team_name_patterns.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized
    
    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names"""
        if not name1 or not name2:
            return 0.0
        
        norm1 = self._normalize_selection_name(name1)
        norm2 = self._normalize_selection_name(name2)
        
        if norm1 == norm2:
            return 1.0
        
        if norm1 in norm2 or norm2 in norm1:
            return 0.9
        
        # Use sequence matcher for fuzzy comparison
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def _calculate_spread_match_confidence(self, odds_outcome: ProcessedOutcome, px_line: ProphetXLine) -> float:
        """Calculate confidence for spread match"""
        name_similarity = self._calculate_name_similarity(odds_outcome.name, px_line.selection_name)
        
        # Point match
        point_match = 1.0
        if odds_outcome.point is not None and px_line.point is not None:
            point_diff = abs(odds_outcome.point - px_line.point)
            point_match = 1.0 if point_diff <= 0.1 else max(0.0, 1.0 - point_diff)
        elif odds_outcome.point != px_line.point:  # One is None, other isn't
            point_match = 0.0
        
        # **CHANGED**: Don't penalize for inactive status - line_id is still valid
        confidence = (name_similarity * 0.7 + point_match * 0.3)
        
        return confidence
    
    def _calculate_total_match_confidence(self, odds_outcome: ProcessedOutcome, px_line: ProphetXLine) -> float:
        """Calculate confidence for total match"""
        name_similarity = self._calculate_name_similarity(odds_outcome.name, px_line.selection_name)
        
        # Point match
        point_match = 1.0
        if odds_outcome.point is not None and px_line.point is not None:
            point_diff = abs(odds_outcome.point - px_line.point)
            point_match = 1.0 if point_diff <= 0.1 else 0.0  # Totals must match exactly
        elif odds_outcome.point != px_line.point:
            point_match = 0.0
        
        # **CHANGED**: Don't penalize for inactive status - line_id is still valid
        confidence = (name_similarity * 0.5 + point_match * 0.5)  # Equal weight for totals
        
        return confidence

# Global market matching service instance
market_matching_service = MarketMatchingService()