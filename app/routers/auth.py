#!/usr/bin/env python3
"""
Authentication Router
FastAPI endpoints for ProphetX authentication and API testing
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter()

# Simple authentication for market maker - we'll use the same auth patterns as the scanner
# but keep it lightweight since this is primarily an automated system

@router.post("/login", response_model=Dict[str, Any])
async def login():
    """
    Login to ProphetX API using configured credentials
    
    Uses credentials from environment variables to authenticate with ProphetX.
    This is typically called once when starting the market making system.
    """
    try:
        # Import here to avoid circular imports
        from app.services.prophetx_service import prophetx_service
        
        result = await prophetx_service.authenticate()
        
        return {
            "success": True,
            "message": "Successfully authenticated with ProphetX",
            "data": {
                "environment": "sandbox" if prophetx_service.sandbox else "production",
                "access_expires_at": result.get("access_expires_at"),
                "refresh_expires_at": result.get("refresh_expires_at")
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

@router.get("/status", response_model=Dict[str, Any])
async def get_auth_status():
    """
    Get current authentication status
    
    Returns information about current ProphetX authentication state,
    including token expiration times and validity.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        status = prophetx_service.get_auth_status()
        
        return {
            "success": True,
            "message": "Authentication status retrieved",
            "data": status
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting auth status: {str(e)}")

@router.post("/test", response_model=Dict[str, Any])
async def test_connections():
    """
    Test connections to both ProphetX and The Odds API
    
    Verifies that both API connections are working properly.
    Useful for troubleshooting and initial setup validation.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        from app.services.odds_api_service import odds_api_service
        
        results = {}
        
        # Test ProphetX connection
        try:
            prophetx_result = await prophetx_service.test_connection()
            results["prophetx"] = prophetx_result
        except Exception as e:
            results["prophetx"] = {
                "success": False,
                "error": str(e)
            }
        
        # Test Odds API connection
        try:
            odds_api_result = await odds_api_service.test_connection()
            results["odds_api"] = odds_api_result
        except Exception as e:
            results["odds_api"] = {
                "success": False,
                "error": str(e)
            }
        
        # Overall success if both connections work
        overall_success = results["prophetx"].get("success", False) and results["odds_api"].get("success", False)
        
        return {
            "success": overall_success,
            "message": "Connection tests completed",
            "data": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing connections: {str(e)}")

@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_token():
    """
    Refresh ProphetX authentication token
    
    Refreshes the access token if it's close to expiring.
    This is typically handled automatically by the system.
    """
    try:
        from app.services.prophetx_service import prophetx_service
        
        result = await prophetx_service.refresh_token()
        
        return {
            "success": True,
            "message": "Token refreshed successfully",
            "data": {
                "access_expires_at": result.get("access_expires_at")
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {str(e)}")