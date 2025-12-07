"""
Bitcoin (BTC) balance endpoints
"""

from fastapi import APIRouter, HTTPException
import httpx
from typing import Optional
from decimal import Decimal
import logging
import json
from utils import _generate_cache_key, _get_cached_result, _set_cached_result

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/btc/{address}")
async def get_btc_balance(address: str, full: bool = False):
    """
    Get Bitcoin balance for an address using mempool.space API
    Returns formatted balance (BTC) by default, or full JSON if full=true
    """
    # Check cache first
    cache_key = _generate_cache_key("btc", address=address, full=full)
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        logger.info(f"API Response [GET /btc/{address}?full={full}]: {json.dumps(cached_result, default=str)}")
        return cached_result
    
    try:
        async with httpx.AsyncClient() as client:
            # Use mempool.space API
            url = f"https://mempool.space/api/address/{address}"
            response = await client.get(url, timeout=10.0)
            
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="Bitcoin address not found")
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error fetching Bitcoin balance: {response.text}"
                )
            
            data = response.json()
            
            # Extract balance information
            # mempool.space returns chain_stats and mempool_stats
            chain_stats = data.get("chain_stats", {})
            mempool_stats = data.get("mempool_stats", {})
            
            # Calculate total balance (confirmed + unconfirmed)
            funded = chain_stats.get("funded_txo_sum", 0) + mempool_stats.get("funded_txo_sum", 0)
            spent = chain_stats.get("spent_txo_sum", 0) + mempool_stats.get("spent_txo_sum", 0)
            balance_satoshi = funded - spent
            
            # Convert satoshi to BTC (1 BTC = 100,000,000 satoshi) using Decimal for precision
            balance_btc = Decimal(balance_satoshi) / Decimal(100_000_000)
            
            full_response = {
                "address": address,
                "balance_satoshi": balance_satoshi,
                "balance_btc": float(balance_btc),
                "confirmed_balance_satoshi": chain_stats.get("funded_txo_sum", 0) - chain_stats.get("spent_txo_sum", 0),
                "unconfirmed_balance_satoshi": mempool_stats.get("funded_txo_sum", 0) - mempool_stats.get("spent_txo_sum", 0)
            }
            
            # Return formatted balance by default, or full response if full=true
            if full:
                result = full_response
            else:
                # Return as string to preserve all decimal places
                result = float(balance_btc)
            
            # Cache the result
            _set_cached_result(cache_key, result)
            logger.info(f"API Response [GET /btc/{address}?full={full}]: {json.dumps(result, default=str)}")
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching BTC balance: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")
    except Exception as e:
        logger.error(f"Error fetching BTC balance: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
