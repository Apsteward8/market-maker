"""
Enhanced ProphetX Wager Service

This service provides enhanced wager history functionality, specifically:
- Getting all wagers for a specific line_id
- Filtering by matching status and time ranges
- Calculating position summaries by line
- Detecting fills and status changes

Key for the line-based position monitoring workflow.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import aiohttp

class ProphetXWagerService:
    """Enhanced ProphetX wager service with line-based filtering"""
    
    def __init__(self, prophetx_service):
        self.prophetx_service = prophetx_service
        self.base_url = prophetx_service.base_url
        
    async def get_wager_histories(
        self,
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
        updated_at_from: Optional[int] = None,
        updated_at_to: Optional[int] = None,
        limit: int = 100,
        matching_status: Optional[str] = None,
        status: Optional[str] = None,
        event_id: Optional[str] = None,
        market_id: Optional[str] = None,
        next_cursor: Optional[str] = None,
        line_id: Optional[str] = None  # NEW: Filter by line_id
    ) -> Dict[str, Any]:
        """
        Get wager histories with optional line_id filtering
        
        This wraps ProphetX's /v2/mm/get_wager_histories endpoint and adds
        client-side line_id filtering since the API doesn't support it directly.
        """
        try:
            # Build query parameters
            params = {}
            
            if from_timestamp:
                params["from"] = from_timestamp
            if to_timestamp:
                params["to"] = to_timestamp
            if updated_at_from:
                params["updated_at_from"] = updated_at_from
            if updated_at_to:
                params["updated_at_to"] = updated_at_to
            if limit:
                params["limit"] = min(limit, 1000)  # Max 1000
            if matching_status:
                params["matching_status"] = matching_status
            if status:
                params["status"] = status
            if event_id:
                params["event_id"] = event_id
            if market_id:
                params["market_id"] = market_id
            if next_cursor:
                params["next_cursor"] = next_cursor
            
            # Make the API call
            headers = await self.prophetx_service.get_auth_headers()
            url = f"{self.base_url}/v2/mm/get_wager_histories"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        wagers = data.get("data", {}).get("wagers", [])
                        
                        # Filter by line_id if specified (client-side filtering)
                        if line_id:
                            wagers = [w for w in wagers if w.get("line_id") == line_id]
                        
                        return {
                            "success": True,
                            "wagers": wagers,
                            "next_cursor": data.get("data", {}).get("next_cursor"),
                            "last_synced_at": data.get("last_synced_at"),
                            "total_retrieved": len(wagers),
                            "filtered_by_line_id": line_id is not None
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}",
                            "status_code": response.status
                        }
                        
        except Exception as e:
            return {
                "success": False,
                "error": f"Exception: {str(e)}"
            }
    
    async def get_all_wagers_for_line(
        self,
        line_id: str,
        days_back: int = 7,
        include_all_statuses: bool = True
    ) -> Dict[str, Any]:
        """
        Get ALL wagers for a specific line_id
        
        This is the key method for line-based position tracking.
        Gets all wagers (active, matched, cancelled, etc.) for a line.
        
        Args:
            line_id: ProphetX line ID
            days_back: How many days back to search
            include_all_statuses: Whether to include cancelled/expired bets
            
        Returns:
            All wagers for this line with position summary
        """
        try:
            # Calculate time range
            now_timestamp = int(time.time())
            from_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
            
            all_wagers = []
            next_cursor = None
            
            # DEBUG: Log what we're searching for
            print(f"🔍 Searching for wagers on line_id: {line_id}")
            
            # Paginate through all results - get ALL our wagers, then filter by line_id
            while True:
                result = await self.get_wager_histories(
                    from_timestamp=from_timestamp,
                    to_timestamp=now_timestamp,
                    limit=1000,
                    next_cursor=next_cursor
                    # NOTE: No line_id parameter here since API doesn't support it
                )
                
                if not result["success"]:
                    print(f"❌ Failed to get wager histories: {result.get('error')}")
                    break
                
                wagers = result["wagers"]
                print(f"📊 Retrieved {len(wagers)} total wagers from ProphetX")
                
                # CLIENT-SIDE FILTERING: Filter by line_id
                line_wagers = []
                for wager in wagers:
                    wager_line_id = wager.get("line_id")
                    if wager_line_id == line_id:
                        line_wagers.append(wager)
                        print(f"✅ Found wager for line {line_id}: {wager.get('external_id', 'unknown')} - ${wager.get('stake', 0)}")
                
                all_wagers.extend(line_wagers)
                print(f"📊 Found {len(line_wagers)} wagers for line {line_id} in this batch")
                
                next_cursor = result.get("next_cursor")
                if not next_cursor:
                    break
            
            print(f"📊 TOTAL: Found {len(all_wagers)} wagers for line {line_id}")
            
            # Filter out cancelled/expired if requested
            if not include_all_statuses:
                before_filter = len(all_wagers)
                all_wagers = [w for w in all_wagers if w.get("status") not in ["cancelled", "expired", "void"]]
                print(f"📊 After status filter: {len(all_wagers)}/{before_filter} wagers")
            
            # Calculate position summary
            summary = self._calculate_line_summary(all_wagers, line_id)
            
            # DEBUG: Log summary
            print(f"💰 Line {line_id[-8:]} summary:")
            print(f"   Total bets: {summary['total_bets']}")
            print(f"   Total stake: ${summary['total_stake']:.2f}")
            print(f"   Total matched: ${summary['total_matched']:.2f}")
            print(f"   Has active: {summary['has_active_bets']}")
            
            return {
                "success": True,
                "line_id": line_id,
                "total_wagers": len(all_wagers),
                "wagers": all_wagers,
                "position_summary": summary
            }
            
        except Exception as e:
            print(f"❌ Error getting wagers for line {line_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Error getting wagers for line {line_id}: {str(e)}"
            }
    
    def _calculate_line_summary(self, wagers: List[Dict[str, Any]], line_id: str) -> Dict[str, Any]:
        """Calculate position summary for a line from wagers list"""
        if not wagers:
            return {
                "total_bets": 0,
                "total_stake": 0.0,
                "total_matched": 0.0,
                "total_unmatched": 0.0,
                "has_active_bets": False,
                "last_bet_time": None,
                "last_fill_time": None,
                "recent_fills": []
            }
        
        # Calculate totals
        total_bets = len(wagers)
        total_stake = sum(w.get("stake", 0) for w in wagers)
        total_matched = sum(w.get("matched_stake", 0) for w in wagers)
        total_unmatched = total_stake - total_matched
        
        # Check for active bets
        has_active_bets = any(
            w.get("matching_status") == "unmatched" and 
            w.get("status") in ["open", "active"] 
            for w in wagers
        )
        
        # Find most recent activity
        last_bet_time = None
        last_fill_time = None
        recent_fills = []
        
        # Sort by creation time
        sorted_wagers = sorted(wagers, key=lambda w: w.get("created_at", ""), reverse=True)
        
        for wager in sorted_wagers:
            created_at = wager.get("created_at")
            updated_at = wager.get("updated_at")
            matched_stake = wager.get("matched_stake", 0)
            
            # Track last bet time
            if not last_bet_time and created_at:
                last_bet_time = created_at
            
            # Track fills
            if matched_stake > 0:
                if not last_fill_time and updated_at:
                    last_fill_time = updated_at
                
                # Recent fills (last hour)
                if updated_at:
                    try:
                        update_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        if update_time > datetime.now(timezone.utc) - timedelta(hours=1):
                            recent_fills.append({
                                "wager_id": wager.get("wager_id"),
                                "external_id": wager.get("external_id"),
                                "matched_stake": matched_stake,
                                "fill_time": updated_at,
                                "matching_status": wager.get("matching_status")
                            })
                    except:
                        pass
        
        return {
            "total_bets": total_bets,
            "total_stake": total_stake,
            "total_matched": total_matched,
            "total_unmatched": total_unmatched,
            "has_active_bets": has_active_bets,
            "last_bet_time": last_bet_time,
            "last_fill_time": last_fill_time,
            "recent_fills": recent_fills
        }
    
    async def get_position_summary_for_lines(
        self,
        line_ids: List[str],
        days_back: int = 7
    ) -> Dict[str, Any]:
        """
        Get position summaries for multiple lines efficiently
        
        Args:
            line_ids: List of ProphetX line IDs
            days_back: How many days back to search
            
        Returns:
            Position summaries for all lines
        """
        try:
            summaries = {}
            
            # Process each line
            for line_id in line_ids:
                result = await self.get_all_wagers_for_line(line_id, days_back)
                
                if result["success"]:
                    summaries[line_id] = result["position_summary"]
                else:
                    summaries[line_id] = {
                        "error": result.get("error"),
                        "total_bets": 0,
                        "total_stake": 0.0,
                        "total_matched": 0.0,
                        "total_unmatched": 0.0,
                        "has_active_bets": False
                    }
            
            # Calculate overall summary
            total_lines = len(summaries)
            total_stake = sum(s.get("total_stake", 0) for s in summaries.values())
            total_matched = sum(s.get("total_matched", 0) for s in summaries.values())
            lines_with_active_bets = sum(1 for s in summaries.values() if s.get("has_active_bets", False))
            
            return {
                "success": True,
                "line_summaries": summaries,
                "overall_summary": {
                    "total_lines": total_lines,
                    "total_stake": total_stake,
                    "total_matched": total_matched,
                    "total_unmatched": total_stake - total_matched,
                    "lines_with_active_bets": lines_with_active_bets
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Error getting position summaries: {str(e)}"
            }
    
    async def detect_recent_fills(
        self,
        line_ids: List[str],
        minutes_back: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Detect recent fills across multiple lines
        
        Args:
            line_ids: List of line IDs to check
            minutes_back: How many minutes back to check for fills
            
        Returns:
            List of recent fills detected
        """
        try:
            recent_fills = []
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_back)
            
            for line_id in line_ids:
                result = await self.get_all_wagers_for_line(line_id, days_back=1)
                
                if result["success"]:
                    for wager in result["wagers"]:
                        matched_stake = wager.get("matched_stake", 0)
                        updated_at = wager.get("updated_at")
                        
                        if matched_stake > 0 and updated_at:
                            try:
                                update_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                                if update_time > cutoff_time:
                                    recent_fills.append({
                                        "line_id": line_id,
                                        "wager_id": wager.get("wager_id"),
                                        "external_id": wager.get("external_id"),
                                        "matched_stake": matched_stake,
                                        "fill_time": updated_at,
                                        "matching_status": wager.get("matching_status"),
                                        "odds": wager.get("odds"),
                                        "original_stake": wager.get("stake")
                                    })
                            except:
                                pass
            
            return recent_fills
            
        except Exception as e:
            print(f"❌ Error detecting recent fills: {e}")
            return []

# This will be initialized with the main ProphetX service
prophetx_wager_service = None

def initialize_wager_service(prophetx_service):
    """Initialize the global wager service instance"""
    global prophetx_wager_service
    prophetx_wager_service = ProphetXWagerService(prophetx_service)
    return prophetx_wager_service