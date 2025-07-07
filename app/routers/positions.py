#!/usr/bin/env python3
"""
Positions Router
FastAPI endpoints for position management and risk monitoring
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.models.market_models import ProphetXBet, PortfolioSummary, RiskReport, RiskLimit
from app.services.market_maker_service import market_maker_service

router = APIRouter()

@router.get("/summary", response_model=PortfolioSummary)
async def get_positions_summary():
    """
    Get comprehensive portfolio and positions summary
    
    Returns detailed information about all current positions including:
    - Total exposure across all markets
    - Number of active bets and markets
    - Performance metrics and success rates
    - Risk utilization percentages
    """
    try:
        return await market_maker_service.get_portfolio_summary()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting positions summary: {str(e)}")

@router.get("/bets", response_model=List[ProphetXBet])
async def get_all_bets(
    status: Optional[str] = Query(None, description="Filter by bet status (placed, matched, cancelled, etc.)"),
    event_id: Optional[str] = Query(None, description="Filter by specific event"),
    limit: Optional[int] = Query(100, description="Maximum number of bets to return")
):
    """
    Get all bets with optional filtering
    
    Returns list of all bets placed by the market making system with filtering options.
    """
    try:
        all_bets = list(market_maker_service.all_bets.values())
        
        # Apply filters
        if status:
            all_bets = [bet for bet in all_bets if bet.status.value == status]
        
        if event_id:
            # Filter by event (bet external_id contains event_id)
            all_bets = [bet for bet in all_bets if event_id in bet.external_id]
        
        # Sort by placed_at (most recent first)
        all_bets.sort(key=lambda x: x.placed_at, reverse=True)
        
        # Apply limit
        if limit:
            all_bets = all_bets[:limit]
        
        return all_bets
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting bets: {str(e)}")

@router.get("/bets/{bet_id}", response_model=ProphetXBet)
async def get_bet_details(bet_id: str):
    """
    Get details for a specific bet
    
    - **bet_id**: External ID of the bet to retrieve
    
    Returns detailed information about a specific bet including current status and exposure.
    """
    try:
        if bet_id not in market_maker_service.all_bets:
            raise HTTPException(status_code=404, detail=f"Bet {bet_id} not found")
        
        return market_maker_service.all_bets[bet_id]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting bet details: {str(e)}")

@router.get("/exposure", response_model=Dict[str, Any])
async def get_exposure_breakdown():
    """
    Get detailed exposure breakdown across all positions
    
    Returns comprehensive analysis of current exposure including:
    - Exposure by event
    - Exposure by market type
    - Net position analysis
    - Risk concentration metrics
    """
    try:
        exposure_data = {
            "total_exposure": market_maker_service.total_exposure,
            "max_exposure_limit": market_maker_service.settings.max_exposure_total,
            "utilization_percentage": (market_maker_service.total_exposure / market_maker_service.settings.max_exposure_total) * 100,
            "by_event": {},
            "by_market_type": {},
            "net_positions": {}
        }
        
        # Calculate exposure by event
        for event_id, managed_event in market_maker_service.managed_events.items():
            exposure_data["by_event"][event_id] = {
                "event_name": managed_event.display_name,
                "total_exposure": managed_event.total_exposure,
                "max_exposure": managed_event.max_exposure,
                "utilization": (managed_event.total_exposure / managed_event.max_exposure) * 100 if managed_event.max_exposure > 0 else 0,
                "markets_count": len(managed_event.markets)
            }
        
        # Calculate exposure by market type
        market_type_exposure = {}
        for managed_event in market_maker_service.managed_events.values():
            for market in managed_event.markets:
                market_type = market.market_type
                if market_type not in market_type_exposure:
                    market_type_exposure[market_type] = 0
                market_type_exposure[market_type] += market.total_exposure
        
        exposure_data["by_market_type"] = market_type_exposure
        
        # Calculate net positions (simplified)
        total_matched_stake = sum(bet.matched_stake for bet in market_maker_service.all_bets.values())
        total_unmatched_stake = sum(bet.unmatched_stake for bet in market_maker_service.all_bets.values())
        
        exposure_data["net_positions"] = {
            "total_matched_stake": total_matched_stake,
            "total_unmatched_stake": total_unmatched_stake,
            "total_stake": total_matched_stake + total_unmatched_stake
        }
        
        return {
            "success": True,
            "message": "Exposure breakdown retrieved",
            "data": exposure_data,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting exposure breakdown: {str(e)}")

@router.get("/risk-report", response_model=Dict[str, Any])
async def get_risk_report():
    """
    Get comprehensive risk report
    
    Returns detailed risk analysis including:
    - All risk limits and their current utilization
    - Risk warnings and violations
    - Recommended actions for risk management
    """
    try:
        # Calculate current risk metrics
        total_exposure = market_maker_service.total_exposure
        max_exposure = market_maker_service.settings.max_exposure_total
        events_count = len(market_maker_service.managed_events)
        max_events = market_maker_service.settings.max_events_tracked
        
        # Create risk limits
        limits = [
            RiskLimit(
                limit_type="total_exposure",
                current_value=total_exposure,
                limit_value=max_exposure,
                warning_threshold=80.0
            ),
            RiskLimit(
                limit_type="events_count",
                current_value=events_count,
                limit_value=max_events,
                warning_threshold=90.0
            )
        ]
        
        # Add per-event exposure limits
        for event_id, managed_event in market_maker_service.managed_events.items():
            limits.append(
                RiskLimit(
                    limit_type=f"event_exposure_{event_id}",
                    current_value=managed_event.total_exposure,
                    limit_value=managed_event.max_exposure,
                    warning_threshold=75.0
                )
            )
        
        # Generate warnings and recommendations
        warnings = []
        recommendations = []
        
        for limit in limits:
            if limit.is_exceeded:
                warnings.append(f"{limit.limit_type} limit exceeded: {limit.current_value:.2f} > {limit.limit_value:.2f}")
                recommendations.append(f"Reduce {limit.limit_type} immediately")
            elif limit.is_warning:
                warnings.append(f"{limit.limit_type} approaching limit: {limit.utilization_percentage:.1f}%")
                recommendations.append(f"Monitor {limit.limit_type} closely")
        
        # Add general recommendations
        if total_exposure > 0:
            recommendations.append("Monitor market conditions for adverse moves")
            recommendations.append("Ensure adequate capital reserves")
        
        if events_count > max_events * 0.8:
            recommendations.append("Consider reducing number of tracked events")
        
        risk_report = RiskReport(
            timestamp=datetime.now(),
            limits=limits,
            warnings=warnings,
            recommendations=recommendations
        )
        
        return {
            "success": True,
            "message": "Risk report generated",
            "data": risk_report.dict(),
            "summary": {
                "has_warnings": risk_report.has_warnings,
                "has_violations": risk_report.has_violations,
                "overall_risk_level": "HIGH" if risk_report.has_violations else "MEDIUM" if risk_report.has_warnings else "LOW"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating risk report: {str(e)}")

@router.post("/close-position", response_model=Dict[str, Any])
async def close_position(
    event_id: str = Query(..., description="Event ID to close position for"),
    market_type: Optional[str] = Query(None, description="Specific market type to close (optional)")
):
    """
    Close position for a specific event or market
    
    Cancels all active bets for the specified event/market to reduce exposure.
    Use with caution as this will stop market making for that position.
    """
    try:
        if event_id not in market_maker_service.managed_events:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        
        managed_event = market_maker_service.managed_events[event_id]
        cancelled_bets = 0
        
        for market in managed_event.markets:
            # Skip if we're only closing a specific market type
            if market_type and market.market_type != market_type:
                continue
            
            for side in market.sides:
                if side.current_bet and side.current_bet.is_active:
                    # Cancel the bet (in real implementation, this would call ProphetX API)
                    side.current_bet.status = "cancelled"
                    side.current_bet.unmatched_stake = 0.0
                    cancelled_bets += 1
                    print(f"❌ Cancelled bet: {side.current_bet.external_id}")
        
        return {
            "success": True,
            "message": f"Position closed for {managed_event.display_name}",
            "data": {
                "event_id": event_id,
                "event_name": managed_event.display_name,
                "market_type": market_type,
                "cancelled_bets": cancelled_bets
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error closing position: {str(e)}")

@router.post("/emergency-stop", response_model=Dict[str, Any])
async def emergency_stop():
    """
    Emergency stop - close all positions immediately
    
    **WARNING**: This cancels ALL active bets across ALL events and stops market making.
    Use only in emergency situations or when system needs immediate shutdown.
    """
    try:
        print("🚨 EMERGENCY STOP INITIATED")
        
        # Stop the market making system
        stop_result = await market_maker_service.stop_market_making()
        
        # Count cancelled bets
        total_cancelled = 0
        for bet in market_maker_service.all_bets.values():
            if bet.is_active:
                bet.status = "cancelled"
                bet.unmatched_stake = 0.0
                total_cancelled += 1
        
        return {
            "success": True,
            "message": "EMERGENCY STOP COMPLETED",
            "data": {
                "total_bets_cancelled": total_cancelled,
                "events_affected": len(market_maker_service.managed_events),
                "stop_timestamp": datetime.now().isoformat(),
                "system_status": "stopped"
            },
            "warning": "All market making has been stopped. Manual restart required."
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during emergency stop: {str(e)}")

@router.get("/performance", response_model=Dict[str, Any])
async def get_performance_metrics():
    """
    Get performance metrics and statistics
    
    Returns detailed performance analysis including:
    - Success rates for market updates
    - Average response times
    - Bet matching statistics
    - System uptime and reliability metrics
    """
    try:
        stats = await market_maker_service.get_system_stats()
        
        # Calculate additional performance metrics
        total_bets = len(market_maker_service.all_bets)
        active_bets = sum(1 for bet in market_maker_service.all_bets.values() if bet.is_active)
        matched_bets = sum(1 for bet in market_maker_service.all_bets.values() if bet.matched_stake > 0)
        
        performance_metrics = {
            "system_uptime_hours": stats["uptime_hours"],
            "market_update_success_rate": stats["success_rate"],
            "total_markets_created": stats["total_markets_created"],
            "bet_statistics": {
                "total_bets_placed": total_bets,
                "active_bets": active_bets,
                "matched_bets": matched_bets,
                "match_rate": (matched_bets / total_bets) * 100 if total_bets > 0 else 0
            },
            "exposure_metrics": {
                "current_total_exposure": stats["total_exposure"],
                "max_exposure_reached": stats["max_exposure_reached"],
                "capacity_utilization": stats["capacity_utilization"]
            },
            "api_performance": stats["odds_api_stats"]
        }
        
        return {
            "success": True,
            "message": "Performance metrics retrieved",
            "data": performance_metrics,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting performance metrics: {str(e)}")