#!/usr/bin/env python3
"""
ProphetX Wager Retrieval Methods
Based on actual ProphetX API documentation
"""

import requests
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from fastapi import HTTPException

from app.core.config import get_settings

class ProphetXWagerService:
    """Service focused on ProphetX wager retrieval and management"""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.prophetx_base_url
        
        # Authentication (you'll need to include your auth methods here)
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.access_expire_time: Optional[int] = None
        self.refresh_expire_time: Optional[int] = None
        self.is_authenticated = False
        
        self.access_key = self.settings.prophetx_access_key
        self.secret_key = self.settings.prophetx_secret_key
        self.sandbox = self.settings.prophetx_sandbox

    async def authenticate(self) -> Dict[str, Any]:
        """Authenticate with ProphetX API"""
        print("🔐 Authenticating with ProphetX...")
        
        url = f"{self.base_url}/partner/auth/login"
        payload = {
            "access_key": self.access_key,
            "secret_key": self.secret_key
        }
        
        headers = {'Content-Type': 'application/json'}
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                token_data = data.get('data', {})
                
                self.access_token = token_data.get('access_token')
                self.refresh_token = token_data.get('refresh_token')
                self.access_expire_time = token_data.get('access_expire_time')
                self.refresh_expire_time = token_data.get('refresh_expire_time')
                
                if self.access_token and self.refresh_token:
                    self.is_authenticated = True
                    
                    access_expire_dt = datetime.fromtimestamp(self.access_expire_time, tz=timezone.utc)
                    print("✅ ProphetX authentication successful!")
                    print(f"   Environment: {'SANDBOX' if self.sandbox else 'PRODUCTION'}")
                    print(f"   Access token expires: {access_expire_dt}")
                    
                    return {
                        "success": True,
                        "message": "Authentication successful",
                        "access_expires_at": access_expire_dt.isoformat(),
                        "refresh_expires_at": datetime.fromtimestamp(self.refresh_expire_time, tz=timezone.utc).isoformat()
                    }
                else:
                    raise HTTPException(status_code=400, detail="Missing tokens in response")
                    
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                raise HTTPException(status_code=response.status_code, detail=error_msg)
                
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        if not self.access_token:
            await self.authenticate()
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

    # ============================================================================
    # CORE WAGER RETRIEVAL METHODS
    # ============================================================================

    async def get_wager_histories(
        self,
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
        updated_at_from: Optional[int] = None,
        updated_at_to: Optional[int] = None,
        matching_status: Optional[str] = None,  # unmatched, fully_matched, partially_matched
        status: Optional[str] = None,  # void, closed, canceled, manually_settled, inactive, wiped, open, invalid, settled
        event_id: Optional[str] = None,
        market_id: Optional[str] = None,
        limit: int = 1000,
        next_cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get wager histories using the actual ProphetX API endpoint
        
        Args:
            from_timestamp: From timestamp (e.g., 1664617512)
            to_timestamp: To timestamp (e.g., 1664790312)
            updated_at_from: Updated at from timestamp
            updated_at_to: Updated at to timestamp
            matching_status: Filter by matching status (unmatched, fully_matched, partially_matched)
            status: Filter by status (void, closed, canceled, etc.)
            event_id: Filter by event ID
            market_id: Filter by market ID
            limit: Max results (max 1000, default 20)
            next_cursor: Cursor for pagination
            
        Returns:
            Raw ProphetX response with wagers data
        """
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/v2/mm/get_wager_histories"
            
            # Build parameters
            params = {}
            
            if from_timestamp is not None:
                params["from"] = from_timestamp
            if to_timestamp is not None:
                params["to"] = to_timestamp
            if updated_at_from is not None:
                params["updated_at_from"] = updated_at_from
            if updated_at_to is not None:
                params["updated_at_to"] = updated_at_to
            if matching_status is not None:
                params["matching_status"] = matching_status
            if status is not None:
                params["status"] = status
            if event_id is not None:
                params["event_id"] = event_id
            if market_id is not None:
                params["market_id"] = market_id
            if limit is not None:
                params["limit"] = limit
            if next_cursor is not None:
                params["next_cursor"] = next_cursor
            
            print(f"📊 Fetching wager histories with params: {params}")
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract wagers from the response
                wagers_data = data.get('data', {})
                wagers = wagers_data.get('wagers', [])
                next_cursor = wagers_data.get('next_cursor')
                last_synced_at = data.get('last_synced_at')
                
                print(f"✅ Retrieved {len(wagers)} wagers")
                
                return {
                    "success": True,
                    "wagers": wagers,
                    "next_cursor": next_cursor,
                    "last_synced_at": last_synced_at,
                    "total_retrieved": len(wagers)
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ Error fetching wager histories: {error_msg}")
                
                return {
                    "success": False,
                    "error": error_msg,
                    "wagers": []
                }
                
        except Exception as e:
            error_msg = f"Exception fetching wager histories: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                "success": False,
                "error": error_msg,
                "wagers": []
            }

    async def get_wager_by_id(self, wager_id: str) -> Dict[str, Any]:
        """
        Get a specific wager by its ID
        
        Args:
            wager_id: The wager ID (e.g., "wager_id_123_xyz")
            
        Returns:
            Wager details or error info
        """
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/mm/get_wager/{wager_id}"
            
            print(f"🎯 Fetching wager by ID: {wager_id}")
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                
                wager_data = data.get('data', {})
                last_synced_at = data.get('last_synced_at')
                
                print(f"✅ Retrieved wager {wager_id}")
                
                return {
                    "success": True,
                    "wager": wager_data,
                    "last_synced_at": last_synced_at
                }
            elif response.status_code == 404:
                print(f"❌ Wager {wager_id} not found")
                
                return {
                    "success": False,
                    "error": "Wager not found",
                    "wager": None
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ Error fetching wager {wager_id}: {error_msg}")
                
                return {
                    "success": False,
                    "error": error_msg,
                    "wager": None
                }
                
        except Exception as e:
            error_msg = f"Exception fetching wager {wager_id}: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                "success": False,
                "error": error_msg,
                "wager": None
            }

    async def get_wager_matching_detail(
        self,
        wager_id: Optional[str] = None,
        limit: int = 100,
        next_cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get wager matching details
        
        Args:
            wager_id: Specific wager ID to get matching details for
            limit: Max results (max 100, default 100)
            next_cursor: Cursor for pagination
            
        Returns:
            Matching details data
        """
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/v2/mm/get_wager_matching_detail"
            
            # Build parameters
            params = {}
            
            if wager_id is not None:
                params["wager_id"] = wager_id
            if limit is not None:
                params["limit"] = limit
            if next_cursor is not None:
                params["next_cursor"] = next_cursor
            
            print(f"🎯 Fetching wager matching details with params: {params}")
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                details_data = data.get('data', {})
                matching_details = details_data.get('matching_details', [])
                next_cursor = details_data.get('next_cursor')
                last_synced_at = data.get('last_synced_at')
                
                print(f"✅ Retrieved {len(matching_details)} matching details")
                
                return {
                    "success": True,
                    "matching_details": matching_details,
                    "next_cursor": next_cursor,
                    "last_synced_at": last_synced_at,
                    "total_retrieved": len(matching_details)
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ Error fetching matching details: {error_msg}")
                
                return {
                    "success": False,
                    "error": error_msg,
                    "matching_details": []
                }
                
        except Exception as e:
            error_msg = f"Exception fetching matching details: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                "success": False,
                "error": error_msg,
                "matching_details": []
            }

    # ============================================================================
    # CONVENIENCE METHODS FOR COMMON USE CASES
    # ============================================================================

    async def get_all_active_wagers(self, days_back: int = 7) -> List[Dict[str, Any]]:
        """
        Get all active (unmatched) wagers from the last X days
        
        Args:
            days_back: How many days back to look
            
        Returns:
            List of active wagers
        """
        print(f"📊 Getting all active wagers from last {days_back} days...")
        
        # Calculate timestamp range
        now_timestamp = int(time.time())
        from_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
        
        result = await self.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status="unmatched",
            status="open",
            limit=1000
        )
        
        if result["success"]:
            print(f"✅ Found {len(result['wagers'])} active wagers")
            return result["wagers"]
        else:
            print(f"❌ Failed to get active wagers: {result.get('error', 'Unknown error')}")
            return []

    async def get_all_matched_wagers(self, days_back: int = 7) -> List[Dict[str, Any]]:
        """
        Get all matched wagers from the last X days
        
        Args:
            days_back: How many days back to look
            
        Returns:
            List of matched wagers
        """
        print(f"🎯 Getting all matched wagers from last {days_back} days...")
        
        # Calculate timestamp range
        now_timestamp = int(time.time())
        from_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
        
        all_matched = []
        
        # Get fully matched wagers
        fully_matched = await self.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status="fully_matched",
            limit=1000
        )
        
        if fully_matched["success"]:
            all_matched.extend(fully_matched["wagers"])
        
        # Get partially matched wagers
        partially_matched = await self.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            matching_status="partially_matched",
            limit=1000
        )
        
        if partially_matched["success"]:
            all_matched.extend(partially_matched["wagers"])
        
        print(f"✅ Found {len(all_matched)} matched wagers")
        return all_matched

    async def get_wager_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        """
        Find a wager by its external_id
        
        Args:
            external_id: Our external ID for the wager
            
        Returns:
            Wager data if found, None otherwise
        """
        print(f"🔍 Searching for wager with external_id: {external_id}")
        
        # We need to search through recent wagers since ProphetX doesn't support filtering by external_id
        # Get recent wagers (last 24 hours)
        now_timestamp = int(time.time())
        from_timestamp = now_timestamp - (24 * 60 * 60)  # 24 hours ago
        
        result = await self.get_wager_histories(
            from_timestamp=from_timestamp,
            to_timestamp=now_timestamp,
            limit=1000
        )
        
        if result["success"]:
            # Search through wagers for matching external_id
            for wager in result["wagers"]:
                if wager.get("external_id") == external_id:
                    print(f"✅ Found wager with external_id {external_id}")
                    return wager
        
        print(f"❌ No wager found with external_id {external_id}")
        return None

    async def get_comprehensive_wager_status(self, identifier: str) -> Dict[str, Any]:
        """
        Get comprehensive status for a wager using multiple lookup methods
        
        Args:
            identifier: Could be wager_id or external_id
            
        Returns:
            Comprehensive wager status information
        """
        print(f"🔍 Getting comprehensive status for wager: {identifier}")
        
        result = {
            "identifier": identifier,
            "found_methods": [],
            "wager_data": None,
            "matching_details": None,
            "status_summary": {}
        }
        
        # Method 1: Try direct wager lookup (assuming it's a wager_id)
        direct_result = await self.get_wager_by_id(identifier)
        if direct_result["success"] and direct_result["wager"]:
            result["found_methods"].append("direct_wager_lookup")
            result["wager_data"] = direct_result["wager"]
            
            # Get matching details for this wager
            matching_result = await self.get_wager_matching_detail(wager_id=identifier)
            if matching_result["success"]:
                result["matching_details"] = matching_result["matching_details"]
        
        # Method 2: Try external_id search
        if not result["wager_data"]:
            external_result = await self.get_wager_by_external_id(identifier)
            if external_result:
                result["found_methods"].append("external_id_search")
                result["wager_data"] = external_result
                
                # Get matching details using the wager_id from the found wager
                wager_id = external_result.get("wager_id")
                if wager_id:
                    matching_result = await self.get_wager_matching_detail(wager_id=wager_id)
                    if matching_result["success"]:
                        result["matching_details"] = matching_result["matching_details"]
        
        # Generate status summary
        if result["wager_data"]:
            wager = result["wager_data"]
            result["status_summary"] = {
                "wager_id": wager.get("wager_id"),
                "external_id": wager.get("external_id"),
                "status": wager.get("status"),
                "matching_status": wager.get("matching_status"),
                "stake": wager.get("stake", 0),
                "matched_stake": wager.get("matched_stake", 0),
                "unmatched_stake": wager.get("unmatched_stake", 0),
                "odds": wager.get("odds"),
                "created_at": wager.get("created_at"),
                "updated_at": wager.get("updated_at"),
                "is_active": wager.get("status") == "open" and wager.get("matching_status") == "unmatched",
                "is_matched": wager.get("matching_status") in ["fully_matched", "partially_matched"]
            }
        else:
            result["status_summary"] = {
                "found": False,
                "message": "Wager not found using any method"
            }
        
        return result

# Global wager service instance
prophetx_wager_service = ProphetXWagerService()