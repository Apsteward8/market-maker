#!/usr/bin/env python3
"""
ProphetX Service
Handles ProphetX API authentication and bet placement for market making
"""

import requests
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException

from app.core.config import get_settings

class ProphetXService:
    """Service for interacting with ProphetX API"""
    
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
        
    async def authenticate(self) -> Dict[str, Any]:
        """
        Authenticate with ProphetX API
        
        Returns:
            dict: Authentication result with token information
        """
        print("🔐 Authenticating with ProphetX...")
        
        url = f"{self.base_url}/partner/auth/login"
        payload = {
            "access_key": self.access_key,
            "secret_key": self.secret_key
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
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
                    refresh_expire_dt = datetime.fromtimestamp(self.refresh_expire_time, tz=timezone.utc)
                    
                    print("✅ ProphetX authentication successful!")
                    print(f"   Environment: {'SANDBOX' if self.sandbox else 'PRODUCTION'}")
                    print(f"   Access token expires: {access_expire_dt}")
                    
                    return {
                        "success": True,
                        "message": "Authentication successful",
                        "access_expires_at": access_expire_dt.isoformat(),
                        "refresh_expires_at": refresh_expire_dt.isoformat()
                    }
                else:
                    raise HTTPException(status_code=400, detail="Missing tokens in response")
                    
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                raise HTTPException(status_code=response.status_code, detail=error_msg)
                
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
    
    async def refresh_token_if_needed(self) -> bool:
        """
        Refresh access token if it's close to expiring
        
        Returns:
            bool: True if refresh was successful or not needed
        """
        if not self.is_authenticated:
            return False
        
        # Check if token needs refresh (refresh if expires within 5 minutes)
        current_time = int(time.time())
        if self.access_expire_time and current_time >= (self.access_expire_time - 300):
            print("🔄 Refreshing ProphetX access token...")
            
            url = f"{self.base_url}/partner/auth/refresh"
            payload = {"refresh_token": self.refresh_token}
            headers = {'Content-Type': 'application/json'}
            
            try:
                response = requests.post(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    token_data = data.get('data', {})
                    
                    self.access_token = token_data.get('access_token')
                    self.access_expire_time = token_data.get('access_expire_time')
                    
                    print("✅ Token refreshed successfully")
                    return True
                else:
                    print(f"❌ Token refresh failed: {response.status_code}")
                    self.is_authenticated = False
                    return False
                    
            except Exception as e:
                print(f"❌ Token refresh error: {e}")
                self.is_authenticated = False
                return False
        
        return True
    
    async def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for API requests
        
        Returns:
            dict: Headers with Bearer token
        """
        # Ensure we have a valid token
        if not await self.refresh_token_if_needed():
            await self.authenticate()
        
        if not self.access_token:
            raise HTTPException(status_code=401, detail="No valid access token available")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_auth_status(self) -> Dict[str, Any]:
        """
        Get current authentication status
        
        Returns:
            dict: Authentication status information
        """
        if not self.is_authenticated:
            return {
                "authenticated": False,
                "message": "Not authenticated"
            }
        
        current_time = int(time.time())
        access_remaining = max(0, self.access_expire_time - current_time) if self.access_expire_time else 0
        refresh_remaining = max(0, self.refresh_expire_time - current_time) if self.refresh_expire_time else 0
        
        return {
            "authenticated": True,
            "access_token_valid": access_remaining > 0,
            "refresh_token_valid": refresh_remaining > 0,
            "access_expires_in_seconds": access_remaining,
            "refresh_expires_in_seconds": refresh_remaining,
            "environment": "sandbox" if self.sandbox else "production"
        }
    
    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to ProphetX API
        
        Returns:
            dict: Test result
        """
        try:
            # Try to get tournaments as a test
            headers = await self.get_auth_headers()
            url = f"{self.base_url}/partner/mm/get_tournaments"
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                tournaments = data.get('data', {}).get('tournaments', [])
                
                return {
                    "success": True,
                    "message": "ProphetX connection test successful",
                    "tournaments_available": len(tournaments),
                    "environment": "sandbox" if self.sandbox else "production"
                }
            else:
                return {
                    "success": False,
                    "message": f"ProphetX test failed: HTTP {response.status_code}",
                    "error": response.text
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": "ProphetX connection test failed",
                "error": str(e)
            }
    
    async def place_bet(
        self, 
        line_id: str, 
        odds: int, 
        stake: float, 
        external_id: str
    ) -> Dict[str, Any]:
        """
        Place a bet on ProphetX
        
        Args:
            line_id: ProphetX line ID
            odds: Bet odds in American format
            stake: Bet stake amount
            external_id: Our unique bet identifier
            
        Returns:
            dict: Bet placement result
        """
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
            
            print(f"💰 Placing bet: {line_id}, {odds:+d}, ${stake}")
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                data = response.json()
                print(f"✅ Bet placed successfully: {external_id}")
                
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
    
    async def cancel_bet(self, bet_id: str) -> Dict[str, Any]:
        """
        Cancel a bet on ProphetX
        
        Args:
            bet_id: ProphetX bet ID to cancel
            
        Returns:
            dict: Cancellation result
        """
        if self.settings.dry_run_mode:
            print(f"🧪 [DRY RUN] Would cancel bet: {bet_id}")
            return {
                "success": True,
                "message": "Dry run - bet cancellation simulated",
                "bet_id": bet_id,
                "dry_run": True
            }
        
        try:
            headers = await self.get_auth_headers()
            # Note: ProphetX may not have a direct cancel endpoint
            # This is a placeholder for the actual implementation
            
            print(f"❌ Cancelling bet: {bet_id}")
            
            # For now, return not supported
            return {
                "success": False,
                "message": "Bet cancellation not currently supported by ProphetX API",
                "bet_id": bet_id,
                "dry_run": False
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "bet_id": bet_id,
                "dry_run": False
            }
    
    async def get_bet_status(self, bet_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a specific bet
        
        Args:
            bet_id: ProphetX bet ID
            
        Returns:
            dict: Bet status information or None
        """
        if self.settings.dry_run_mode:
            return {
                "bet_id": bet_id,
                "status": "simulated",
                "dry_run": True
            }
        
        try:
            headers = await self.get_auth_headers()
            # Note: ProphetX may not have a direct bet status endpoint
            # This would need to be implemented based on actual API
            
            # For now, return None (not available)
            return None
            
        except Exception as e:
            print(f"❌ Error getting bet status: {e}")
            return None
    
    async def refresh_token(self) -> Dict[str, Any]:
        """
        Manually refresh the access token
        
        Returns:
            dict: Refresh result
        """
        if not self.refresh_token:
            raise HTTPException(status_code=401, detail="No refresh token available")
        
        url = f"{self.base_url}/partner/auth/refresh"
        payload = {"refresh_token": self.refresh_token}
        headers = {'Content-Type': 'application/json'}
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                token_data = data.get('data', {})
                
                self.access_token = token_data.get('access_token')
                self.access_expire_time = token_data.get('access_expire_time')
                
                access_expire_dt = datetime.fromtimestamp(self.access_expire_time, tz=timezone.utc)
                
                return {
                    "success": True,
                    "message": "Token refreshed successfully",
                    "access_expires_at": access_expire_dt.isoformat()
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                raise HTTPException(status_code=response.status_code, detail=error_msg)
                
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")

# Global ProphetX service instance
prophetx_service = ProphetXService()