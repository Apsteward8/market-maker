#!/usr/bin/env python3
"""
ProphetX Service - COMPLETE API COVERAGE
Comprehensive ProphetX API methods for granular bet and line management
"""

import requests
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from fastapi import HTTPException
import asyncio

from app.core.config import get_settings

class ProphetXAuthManager:
    """
    Enhanced authentication manager with automatic token refresh
    
    Features:
    - Automatic token refresh 2 minutes before expiry
    - Background refresh task
    - Shared authentication state across all services
    - Retry logic for authentication failures
    """
    
    def __init__(self, prophetx_service):
        self.prophetx_service = prophetx_service
        self.base_url = prophetx_service.base_url
        self.access_key = prophetx_service.access_key
        self.secret_key = prophetx_service.secret_key
        self.sandbox = prophetx_service.sandbox
        
        # Authentication state
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.access_expire_time: Optional[int] = None
        self.refresh_expire_time: Optional[int] = None
        self.is_authenticated = False
        
        # Auto-refresh settings
        self.refresh_buffer_seconds = 120  # Refresh 2 minutes before expiry
        self.refresh_task: Optional[asyncio.Task] = None
        self.refresh_running = False
        
        # Retry settings
        self.max_auth_retries = 3
        self.auth_retry_delay = 5  # seconds
        
    async def authenticate(self) -> Dict[str, Any]:
        """Enhanced authentication with better error handling"""
        print("🔐 Authenticating with ProphetX...")
        
        url = f"{self.base_url}/partner/auth/login"
        payload = {
            "access_key": self.access_key,
            "secret_key": self.secret_key
        }
        
        headers = {'Content-Type': 'application/json'}
        
        for attempt in range(self.max_auth_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    token_data = data.get('data', {})
                    
                    self.access_token = token_data.get('access_token')
                    self.refresh_token = token_data.get('refresh_token')
                    self.access_expire_time = token_data.get('access_expire_time')
                    self.refresh_expire_time = token_data.get('refresh_expire_time')
                    
                    if self.access_token and self.refresh_token:
                        self.is_authenticated = True
                        
                        # Update the main service's auth state
                        self._update_service_auth_state()
                        
                        access_expire_dt = datetime.fromtimestamp(self.access_expire_time, tz=timezone.utc)
                        refresh_expire_dt = datetime.fromtimestamp(self.refresh_expire_time, tz=timezone.utc)
                        
                        print("✅ ProphetX authentication successful!")
                        print(f"   Environment: {'SANDBOX' if self.sandbox else 'PRODUCTION'}")
                        print(f"   Access token expires: {access_expire_dt}")
                        print(f"   Refresh token expires: {refresh_expire_dt}")
                        
                        # Start auto-refresh task
                        await self._start_refresh_task()
                        
                        return {
                            "success": True,
                            "message": "Authentication successful",
                            "access_expires_at": access_expire_dt.isoformat(),
                            "refresh_expires_at": refresh_expire_dt.isoformat(),
                            "expires_in_minutes": (self.access_expire_time - time.time()) / 60
                        }
                    else:
                        raise Exception("Missing tokens in response")
                        
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    print(f"❌ Authentication attempt {attempt + 1} failed: {error_msg}")
                    
                    if attempt < self.max_auth_retries - 1:
                        print(f"   Retrying in {self.auth_retry_delay} seconds...")
                        await asyncio.sleep(self.auth_retry_delay)
                    else:
                        raise Exception(error_msg)
                        
            except requests.exceptions.RequestException as e:
                print(f"❌ Network error on attempt {attempt + 1}: {e}")
                if attempt < self.max_auth_retries - 1:
                    await asyncio.sleep(self.auth_retry_delay)
                else:
                    raise Exception(f"Network error: {str(e)}")
        
        raise Exception("Authentication failed after all retries")
    
    async def refresh_access_token(self) -> Dict[str, Any]:
        """Refresh the access token using the refresh token"""
        if not self.refresh_token:
            print("❌ No refresh token available - need to re-authenticate")
            return await self.authenticate()
        
        print("🔄 Refreshing ProphetX access token...")
        
        url = f"{self.base_url}/partner/auth/refresh"
        headers = {
            'Authorization': f'Bearer {self.refresh_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                token_data = data.get('data', {})
                
                # Update tokens
                old_access_token = self.access_token
                self.access_token = token_data.get('access_token')
                self.access_expire_time = token_data.get('access_expire_time')
                
                # Update service auth state
                self._update_service_auth_state()
                
                access_expire_dt = datetime.fromtimestamp(self.access_expire_time, tz=timezone.utc)
                
                print("✅ Access token refreshed successfully!")
                print(f"   New expiry: {access_expire_dt}")
                print(f"   Valid for: {(self.access_expire_time - time.time()) / 60:.1f} minutes")
                
                return {
                    "success": True,
                    "message": "Token refreshed successfully",
                    "access_expires_at": access_expire_dt.isoformat(),
                    "expires_in_minutes": (self.access_expire_time - time.time()) / 60
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ Token refresh failed: {error_msg}")
                print("🔄 Attempting full re-authentication...")
                return await self.authenticate()
                
        except Exception as e:
            print(f"❌ Error refreshing token: {e}")
            print("🔄 Attempting full re-authentication...")
            return await self.authenticate()
    
    def _update_service_auth_state(self):
        """Update the main ProphetX service with current auth state"""
        self.prophetx_service.access_token = self.access_token
        self.prophetx_service.refresh_token = self.refresh_token
        self.prophetx_service.access_expire_time = self.access_expire_time
        self.prophetx_service.refresh_expire_time = self.refresh_expire_time
        self.prophetx_service.is_authenticated = self.is_authenticated
    
    def is_token_expired(self, buffer_seconds: int = 0) -> bool:
        """Check if access token is expired or will expire within buffer_seconds"""
        if not self.access_expire_time:
            return True
        
        current_time = time.time()
        return current_time >= (self.access_expire_time - buffer_seconds)
    
    def time_until_expiry(self) -> float:
        """Get seconds until token expires"""
        if not self.access_expire_time:
            return 0
        return max(0, self.access_expire_time - time.time())
    
    async def get_valid_auth_headers(self) -> Dict[str, str]:
        """Get auth headers, refreshing token if necessary"""
        
        # Check if we need to refresh
        if self.is_token_expired(buffer_seconds=30):  # 30 second buffer for API calls
            print("🔄 Token expired or expiring soon - refreshing...")
            await self.refresh_access_token()
        
        if not self.access_token:
            print("🔐 No access token - authenticating...")
            await self.authenticate()
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    async def _start_refresh_task(self):
        """Start the background token refresh task"""
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
        
        self.refresh_task = asyncio.create_task(self._refresh_loop())
        print(f"🔄 Started auto-refresh task (will refresh {self.refresh_buffer_seconds}s before expiry)")
    
    async def _refresh_loop(self):
        """Background task that refreshes tokens automatically"""
        self.refresh_running = True
        
        try:
            while self.refresh_running and self.is_authenticated:
                # Calculate when to refresh (2 minutes before expiry)
                time_until_refresh = self.time_until_expiry() - self.refresh_buffer_seconds
                
                if time_until_refresh <= 0:
                    # Token is about to expire - refresh now
                    print("⏰ Token approaching expiry - auto-refreshing...")
                    await self.refresh_access_token()
                    time_until_refresh = self.time_until_expiry() - self.refresh_buffer_seconds
                
                if time_until_refresh > 0:
                    print(f"🔄 Next auto-refresh in {time_until_refresh / 60:.1f} minutes")
                    await asyncio.sleep(min(time_until_refresh, 300))  # Check at least every 5 minutes
                else:
                    await asyncio.sleep(60)  # Check again in 1 minute
                    
        except asyncio.CancelledError:
            print("🛑 Auto-refresh task cancelled")
        except Exception as e:
            print(f"❌ Error in refresh loop: {e}")
            # Try to restart the loop after a delay
            await asyncio.sleep(60)
            if self.refresh_running:
                await self._start_refresh_task()
        finally:
            self.refresh_running = False
    
    async def stop_refresh_task(self):
        """Stop the background refresh task"""
        self.refresh_running = False
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        print("🛑 Auto-refresh task stopped")
    
    def get_auth_status(self) -> Dict[str, Any]:
        """Get current authentication status"""
        if not self.is_authenticated:
            return {
                "authenticated": False,
                "message": "Not authenticated"
            }
        
        current_time = time.time()
        time_until_expiry = max(0, self.access_expire_time - current_time)
        time_until_refresh_expiry = max(0, self.refresh_expire_time - current_time)
        
        return {
            "authenticated": True,
            "access_token_valid": not self.is_token_expired(),
            "expires_in_seconds": time_until_expiry,
            "expires_in_minutes": time_until_expiry / 60,
            "refresh_expires_in_hours": time_until_refresh_expiry / 3600,
            "auto_refresh_active": self.refresh_running,
            "environment": "sandbox" if self.sandbox else "production"
        }

class ProphetXService:
    """Service with complete ProphetX API coverage"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.prophetx_base_url
        
        # Authentication state
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.access_expire_time: Optional[int] = None
        self.refresh_expire_time: Optional[int] = None
        self.is_authenticated = False
        
        # ProphetX credentials
        self.access_key = self.settings.prophetx_access_key
        self.secret_key = self.settings.prophetx_secret_key
        self.sandbox = self.settings.prophetx_sandbox

        # Initialize authentication manager
        self.auth_manager = ProphetXAuthManager(self)


    # ============================================================================
    # AUTHENTICATION METHODS (keep existing ones)
    # ============================================================================
    
    async def authenticate(self) -> Dict[str, Any]:
        """Authenticate with ProphetX API using the auth manager"""
        return await self.auth_manager.authenticate()

    async def refresh_token(self) -> Dict[str, Any]:
        """Refresh the access token"""
        return await self.auth_manager.refresh_access_token()

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers with automatic refresh"""
        return await self.auth_manager.get_valid_auth_headers()
    
    def get_auth_status(self) -> Dict[str, Any]:
        """Get current authentication status"""
        return self.auth_manager.get_auth_status()

    async def start_auth_monitoring(self):
        """Start automatic token refresh monitoring"""
        print("🚀 Starting ProphetX authentication monitoring...")
        await self.auth_manager.authenticate()

    async def stop_auth_monitoring(self):
        """Stop automatic token refresh monitoring"""
        print("🛑 Stopping ProphetX authentication monitoring...")
        await self.auth_manager.stop_refresh_task()

    # ============================================================================
    # LINE-SPECIFIC METHODS (NEW)
    # ============================================================================
    
    async def get_line_details(self, line_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific betting line
        
        Args:
            line_id: ProphetX line ID
            
        Returns:
            Line details including current odds, status, liquidity, etc.
        """
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/mm/get_line/{line_id}"
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                line_data = data.get('data', {})
                
                print(f"📏 Line {line_id[-8:]}: {line_data.get('selection_name', 'Unknown')} @ {line_data.get('odds', 'N/A')}")
                return line_data
            elif response.status_code == 404:
                print(f"📏 Line {line_id[-8:]}: Not found (404)")
                return None
            else:
                print(f"❌ Error getting line {line_id}: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Exception getting line {line_id}: {e}")
            return None

    async def get_lines_for_event(self, event_id: int) -> List[Dict[str, Any]]:
        """
        Get all betting lines for a specific event
        
        Args:
            event_id: ProphetX event ID
            
        Returns:
            List of all lines for this event across all markets
        """
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/v2/mm/get_markets"
            params = {"event_id": event_id}
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                markets = data.get('data', {}).get('markets', [])
                
                all_lines = []
                for market in markets:
                    # Extract lines from each market
                    if 'selections' in market:
                        for selection_group in market.get('selections', []):
                            if isinstance(selection_group, list):
                                for selection in selection_group:
                                    line_info = {
                                        'line_id': selection.get('line_id'),
                                        'selection_name': selection.get('name'),
                                        'odds': selection.get('odds'),
                                        'point': selection.get('line', 0),
                                        'market_type': market.get('type'),
                                        'market_name': market.get('name'),
                                        'status': 'active' if selection.get('odds') is not None else 'inactive'
                                    }
                                    all_lines.append(line_info)
                
                print(f"📋 Event {event_id}: Found {len(all_lines)} total lines")
                return all_lines
            else:
                print(f"❌ Error getting lines for event {event_id}: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Exception getting lines for event {event_id}: {e}")
            return []

    async def get_my_bets_for_line(self, line_id: str) -> List[Dict[str, Any]]:
        """
        Get all of our bets (active and inactive) for a specific line
        
        Args:
            line_id: ProphetX line ID
            
        Returns:
            List of our bets on this specific line
        """
        try:
            # Get all our wager histories and filter by line_id
            all_wagers = await self.get_all_my_wagers(include_matched=True)
            
            line_bets = []
            for wager in all_wagers:
                if wager.get('line_id') == line_id:
                    line_bets.append(wager)
            
            print(f"🎯 Line {line_id[-8:]}: Found {len(line_bets)} of our bets")
            return line_bets
            
        except Exception as e:
            print(f"❌ Exception getting our bets for line {line_id}: {e}")
            return []

    # ============================================================================
    # COMPREHENSIVE WAGER MANAGEMENT
    # ============================================================================
    
    async def get_all_my_wagers(self, include_matched: bool = True, days_back: int = 7) -> List[Dict[str, Any]]:
        """
        Get ALL of our wagers (active, matched, cancelled, etc.) with better filtering
        
        Args:
            include_matched: Whether to include matched/settled bets
            days_back: How many days back to look
            
        Returns:
            Comprehensive list of all our wagers
        """
        try:
            headers = await self.get_auth_headers()
            
            # Calculate date range
            now_timestamp = int(time.time())
            days_ago_timestamp = now_timestamp - (days_back * 24 * 60 * 60)
            
            all_wagers = []
            
            # Get active (unmatched) wagers
            print(f"📊 Fetching active wagers from last {days_back} days...")
            active_url = f"{self.base_url}/partner/v2/mm/get_wager_histories"
            active_params = {
                "from": days_ago_timestamp,
                "to": now_timestamp,
                "matching_status": "unmatched",
                "status": "open",
                "limit": 1000
            }
            
            response = requests.get(active_url, headers=headers, params=active_params)
            if response.status_code == 200:
                data = response.json()
                wagers = self._extract_wagers_from_response(data)
                all_wagers.extend(wagers)
                print(f"   ✅ Found {len(wagers)} active wagers")
            
            # Get matched wagers if requested
            if include_matched:
                print(f"📊 Fetching matched wagers from last {days_back} days...")
                matched_url = f"{self.base_url}/partner/mm/get_matched_bets"
                matched_params = {
                    "from": days_ago_timestamp,
                    "to": now_timestamp,
                    "limit": 1000
                }
                
                response = requests.get(matched_url, headers=headers, params=matched_params)
                if response.status_code == 200:
                    data = response.json()
                    matched_wagers = self._extract_wagers_from_response(data)
                    all_wagers.extend(matched_wagers)
                    print(f"   ✅ Found {len(matched_wagers)} matched wagers")
            
            print(f"📊 Total wagers retrieved: {len(all_wagers)}")
            return all_wagers
            
        except Exception as e:
            print(f"❌ Exception getting all wagers: {e}")
            return []

    def _extract_wagers_from_response(self, data) -> List[Dict[str, Any]]:
        """Extract wagers from various ProphetX response formats"""
        wagers = []
        
        if isinstance(data, dict):
            if 'data' in data:
                inner_data = data['data']
                if isinstance(inner_data, list):
                    wagers = inner_data
                elif isinstance(inner_data, dict):
                    # Try common field names
                    for field in ['wagers', 'bets', 'matches', 'histories']:
                        if field in inner_data and isinstance(inner_data[field], list):
                            wagers = inner_data[field]
                            break
            else:
                # Try direct field access
                for key, value in data.items():
                    if isinstance(value, list) and value:
                        wagers = value
                        break
        elif isinstance(data, list):
            wagers = data
        
        return wagers

    async def get_wager_details_comprehensive(self, wager_id: str) -> Dict[str, Any]:
        """
        Get comprehensive wager details with multiple lookup methods
        
        Args:
            wager_id: ProphetX wager ID or external ID
            
        Returns:
            Detailed wager information
        """
        result = {
            "wager_id": wager_id,
            "found_via": None,
            "details": None,
            "status": "not_found"
        }
        
        try:
            headers = await self.get_auth_headers()
            
            # Method 1: Direct wager lookup
            url = f"{self.base_url}/partner/mm/get_wager/{wager_id}"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                result["found_via"] = "direct_lookup"
                result["details"] = data.get('data', {})
                result["status"] = "found"
                print(f"📋 Wager {wager_id[-8:]}: Found via direct lookup")
                return result
            
            # Method 2: Search in all active wagers
            print(f"🔍 Searching for wager {wager_id[-8:]} in active wagers...")
            active_wagers = await self.get_all_my_wagers(include_matched=False)
            
            for wager in active_wagers:
                if (wager.get('id') == wager_id or 
                    wager.get('external_id') == wager_id):
                    result["found_via"] = "active_search"
                    result["details"] = wager
                    result["status"] = "found_active"
                    print(f"📋 Wager {wager_id[-8:]}: Found in active wagers")
                    return result
            
            # Method 3: Search in matched bets
            print(f"🔍 Searching for wager {wager_id[-8:]} in matched bets...")
            matched_wagers = await self.get_all_my_wagers(include_matched=True, days_back=1)
            
            for wager in matched_wagers:
                if (wager.get('id') == wager_id or 
                    wager.get('external_id') == wager_id):
                    result["found_via"] = "matched_search"
                    result["details"] = wager
                    result["status"] = "found_matched"
                    print(f"📋 Wager {wager_id[-8:]}: Found in matched bets")
                    return result
            
            print(f"❌ Wager {wager_id[-8:]}: Not found anywhere")
            return result
            
        except Exception as e:
            print(f"❌ Exception in comprehensive wager lookup: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            return result

    # ============================================================================
    # POSITION TRACKING METHODS (NEW)
    # ============================================================================
    
    async def get_position_summary_for_event(self, event_id: int) -> Dict[str, Any]:
        """
        Get complete position summary for a specific event
        
        Args:
            event_id: ProphetX event ID
            
        Returns:
            Summary of all positions/exposure for this event
        """
        try:
            # Get all lines for this event
            event_lines = await self.get_lines_for_event(event_id)
            
            position_summary = {
                "event_id": event_id,
                "total_lines": len(event_lines),
                "lines_with_bets": 0,
                "total_stake": 0.0,
                "total_unmatched": 0.0,
                "total_matched": 0.0,
                "line_details": {}
            }
            
            # For each line, get our bet details
            for line in event_lines:
                line_id = line.get('line_id')
                if not line_id:
                    continue
                
                our_bets = await self.get_my_bets_for_line(line_id)
                
                if our_bets:
                    position_summary["lines_with_bets"] += 1
                    
                    line_stake = sum(bet.get('stake', 0) for bet in our_bets)
                    line_matched = sum(bet.get('matched_stake', 0) for bet in our_bets if bet.get('matched_stake'))
                    line_unmatched = line_stake - line_matched
                    
                    position_summary["total_stake"] += line_stake
                    position_summary["total_matched"] += line_matched
                    position_summary["total_unmatched"] += line_unmatched
                    
                    position_summary["line_details"][line_id] = {
                        "selection_name": line.get('selection_name'),
                        "market_type": line.get('market_type'),
                        "current_odds": line.get('odds'),
                        "our_bets_count": len(our_bets),
                        "total_stake": line_stake,
                        "matched_stake": line_matched,
                        "unmatched_stake": line_unmatched,
                        "line_status": line.get('status')
                    }
            
            print(f"📊 Event {event_id} Position Summary:")
            print(f"   Lines with bets: {position_summary['lines_with_bets']}/{position_summary['total_lines']}")
            print(f"   Total stake: ${position_summary['total_stake']:.2f}")
            print(f"   Matched: ${position_summary['total_matched']:.2f}")
            print(f"   Unmatched: ${position_summary['total_unmatched']:.2f}")
            
            return position_summary
            
        except Exception as e:
            print(f"❌ Exception getting position summary for event {event_id}: {e}")
            return {"error": str(e)}

    # ============================================================================
    # BULK OPERATIONS (NEW)
    # ============================================================================
    
    async def cancel_all_bets_for_event(self, event_id: int) -> Dict[str, Any]:
        """
        Cancel all our active bets for a specific event
        
        Args:
            event_id: ProphetX event ID
            
        Returns:
            Cancellation results
        """
        try:
            if self.settings.dry_run_mode:
                print(f"🧪 [DRY RUN] Would cancel all bets for event {event_id}")
                return {"success": True, "dry_run": True, "cancelled_count": 0}
            
            # Get position summary to find all our bets
            position_summary = await self.get_position_summary_for_event(event_id)
            
            cancelled_count = 0
            failed_count = 0
            
            for line_id, line_details in position_summary.get("line_details", {}).items():
                if line_details["unmatched_stake"] > 0:
                    # Get our bets for this line
                    our_bets = await self.get_my_bets_for_line(line_id)
                    
                    for bet in our_bets:
                        if bet.get('status') == 'open' and bet.get('matching_status') == 'unmatched':
                            bet_id = bet.get('id')
                            cancel_result = await self.cancel_wager(bet_id)
                            
                            if cancel_result.get("success"):
                                cancelled_count += 1
                            else:
                                failed_count += 1
            
            print(f"🗑️ Event {event_id}: Cancelled {cancelled_count} bets, {failed_count} failed")
            
            return {
                "success": True,
                "event_id": event_id,
                "cancelled_count": cancelled_count,
                "failed_count": failed_count
            }
            
        except Exception as e:
            print(f"❌ Exception cancelling bets for event {event_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_lines_needing_liquidity(self, event_id: int, max_position_per_line: float = 500.0) -> List[Dict[str, Any]]:
        """
        Identify lines that need more liquidity (under position limits)
        
        Args:
            event_id: ProphetX event ID
            max_position_per_line: Maximum stake allowed per line
            
        Returns:
            List of lines that can accept more liquidity
        """
        try:
            position_summary = await self.get_position_summary_for_event(event_id)
            
            lines_needing_liquidity = []
            
            for line_id, line_details in position_summary.get("line_details", {}).items():
                current_stake = line_details["total_stake"]
                unmatched_stake = line_details["unmatched_stake"]
                
                # Only add liquidity if:
                # 1. Current total stake is below max position
                # 2. Line is currently active (has odds)
                if (current_stake < max_position_per_line and 
                    line_details["current_odds"] is not None and
                    line_details["line_status"] == "active"):
                    
                    available_liquidity = max_position_per_line - current_stake
                    
                    lines_needing_liquidity.append({
                        "line_id": line_id,
                        "selection_name": line_details["selection_name"],
                        "market_type": line_details["market_type"],
                        "current_odds": line_details["current_odds"],
                        "current_stake": current_stake,
                        "unmatched_stake": unmatched_stake,
                        "available_liquidity": available_liquidity,
                        "priority": unmatched_stake  # Lines with less unmatched stake get priority
                    })
            
            # Sort by priority (less unmatched stake = higher priority for more liquidity)
            lines_needing_liquidity.sort(key=lambda x: x["priority"])
            
            print(f"📈 Event {event_id}: {len(lines_needing_liquidity)} lines need more liquidity")
            
            return lines_needing_liquidity
            
        except Exception as e:
            print(f"❌ Exception finding lines needing liquidity: {e}")
            return []

    # ============================================================================
    # TESTING AND DIAGNOSTICS (NEW)
    # ============================================================================
    
    async def run_diagnostics(self) -> Dict[str, Any]:
        """
        Run comprehensive diagnostics on ProphetX API connectivity and data
        
        Returns:
            Detailed diagnostic results
        """
        diagnostics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "authentication": {},
            "api_endpoints": {},
            "data_quality": {},
            "recommendations": []
        }
        
        try:
            # Test authentication
            print("🔍 Running ProphetX API Diagnostics...")
            print("1️⃣ Testing authentication...")
            
            auth_result = await self.authenticate()
            diagnostics["authentication"] = {
                "success": auth_result.get("success", False),
                "environment": "sandbox" if self.sandbox else "production"
            }
            
            if not auth_result.get("success"):
                diagnostics["recommendations"].append("Fix authentication issues first")
                return diagnostics
            
            # Test core endpoints
            print("2️⃣ Testing core API endpoints...")
            
            endpoints_to_test = [
                ("get_tournaments", "/partner/mm/get_tournaments"),
                ("get_wager_histories", "/partner/v2/mm/get_wager_histories"),
                ("get_matched_bets", "/partner/mm/get_matched_bets")
            ]
            
            for endpoint_name, endpoint_url in endpoints_to_test:
                try:
                    headers = await self.get_auth_headers()
                    full_url = f"{self.base_url}{endpoint_url}"
                    
                    # Add minimal required params
                    params = {}
                    if "get_wager_histories" in endpoint_url:
                        now = int(time.time())
                        params = {
                            "from": now - 86400,  # Last 24 hours
                            "to": now,
                            "limit": 10
                        }
                    elif "get_matched_bets" in endpoint_url:
                        now = int(time.time())
                        params = {
                            "from": now - 86400,
                            "to": now,
                            "limit": 10
                        }
                    
                    response = requests.get(full_url, headers=headers, params=params)
                    
                    diagnostics["api_endpoints"][endpoint_name] = {
                        "status_code": response.status_code,
                        "success": response.status_code == 200,
                        "response_size": len(response.text) if response.text else 0
                    }
                    
                    if response.status_code == 200:
                        print(f"   ✅ {endpoint_name}: OK")
                    else:
                        print(f"   ❌ {endpoint_name}: HTTP {response.status_code}")
                        
                except Exception as e:
                    diagnostics["api_endpoints"][endpoint_name] = {
                        "success": False,
                        "error": str(e)
                    }
                    print(f"   ❌ {endpoint_name}: Exception - {e}")
            
            # Test data retrieval
            print("3️⃣ Testing data retrieval...")
            
            all_wagers = await self.get_all_my_wagers(include_matched=True, days_back=1)
            diagnostics["data_quality"] = {
                "total_wagers_found": len(all_wagers),
                "active_wagers": len([w for w in all_wagers if w.get('matching_status') == 'unmatched']),
                "matched_wagers": len([w for w in all_wagers if w.get('matching_status') in ['fully_matched', 'partially_matched']])
            }
            
            print(f"   📊 Found {len(all_wagers)} total wagers in last 24 hours")
            
            # Generate recommendations
            if diagnostics["data_quality"]["total_wagers_found"] == 0:
                diagnostics["recommendations"].append("No recent wagers found - check if betting is working")
            
            if len([ep for ep in diagnostics["api_endpoints"].values() if not ep.get("success", False)]) > 0:
                diagnostics["recommendations"].append("Some API endpoints failing - check ProphetX API documentation")
            
            if diagnostics["data_quality"]["active_wagers"] == 0:
                diagnostics["recommendations"].append("No active wagers found - market making may not be placing bets")
            
            if not diagnostics["recommendations"]:
                diagnostics["recommendations"].append("All systems appear to be working correctly")
            
            print("✅ Diagnostics complete!")
            
        except Exception as e:
            diagnostics["error"] = str(e)
            print(f"❌ Diagnostics failed: {e}")
        
        return diagnostics

    # ============================================================================
    # EXISTING METHODS (keep all your existing bet placement, cancellation, etc.)
    # ============================================================================
    
    async def place_bet(self, line_id: str, odds: int, stake: float, external_id: str) -> Dict[str, Any]:
        """Place a bet on ProphetX (keep existing implementation)"""
        if self.settings.dry_run_mode:
            print(f"🧪 [DRY RUN] Would place bet: {line_id}, {odds:+d}, ${stake}")
            return {
                "success": True,
                "bet_id": f"dry_run_{external_id}",
                "external_id": external_id,
                "message": "Dry run - bet simulated",
                "dry_run": True
            }
        
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/mm/place_wager"
            
            payload = {
                "external_id": external_id,
                "line_id": line_id,
                "odds": odds,
                "stake": stake
            }
            
            print(f"💰 Placing bet: {line_id[-8:]}, {odds:+d}, ${stake}")
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                data = response.json()
                print(f"✅ Bet placed successfully: {external_id[-8:]}")
                
                return {
                    "success": True,
                    "bet_id": data.get('id', external_id),
                    "external_id": external_id,
                    "response_data": data,
                    "dry_run": False
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ Bet placement failed: {error_msg}")
                
                return {
                    "success": False,
                    "error": error_msg,
                    "external_id": external_id,
                    "dry_run": False
                }
                
        except Exception as e:
            error_msg = f"Exception placing bet: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                "success": False,
                "error": error_msg,
                "external_id": external_id,
                "dry_run": False
            }

    async def cancel_wager(self, wager_id: str) -> Dict[str, Any]:
        """Cancel a wager (keep existing implementation)"""
        if self.settings.dry_run_mode:
            print(f"🧪 [DRY RUN] Would cancel wager: {wager_id}")
            return {"success": True, "message": "Dry run - wager cancellation simulated", "wager_id": wager_id, "dry_run": True}
        
        try:
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/mm/cancel_wager"
            
            payload = {"wager_id": wager_id}
            
            print(f"❌ Cancelling wager: {wager_id[-8:]}")
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                data = response.json()
                print(f"✅ Wager cancelled successfully: {wager_id[-8:]}")
                
                return {"success": True, "wager_id": wager_id, "response_data": data, "dry_run": False}
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ Wager cancellation failed: {error_msg}")
                return {"success": False, "error": error_msg, "wager_id": wager_id, "dry_run": False}
                
        except Exception as e:
            error_msg = f"Exception cancelling wager: {str(e)}"
            print(f"❌ {error_msg}")
            return {"success": False, "error": error_msg, "wager_id": wager_id, "dry_run": False}

# Global ProphetX service instance
prophetx_service = ProphetXService()