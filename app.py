"""
Blockchain Balance API
A REST API to query Bitcoin and EVM chain balances
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import httpx
from web3 import Web3
from typing import Optional, Dict, List, Any
import logging
import time
from decimal import Decimal
import hashlib
import json
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Blockchain Balance API",
    description="API to query Bitcoin and EVM chain balances",
    version="1.0.0"
)

# Cache for chainlist JSON data
_chainlist_cache: Optional[List[Dict[str, Any]]] = None
_cache_timestamp: float = 0
_cache_ttl: int = 3600  # Cache for 1 hour

# Cache for API results (30 minutes TTL) and permanent entries (ERC20 metadata)
_result_cache: Dict[str, Dict[str, Any]] = {}
_result_cache_ttl: int = 1800  # 30 minutes in seconds


async def _fetch_chainlist_json() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch chainlist JSON from chainlist.org/rpcs.json
    """
    try:
        async with httpx.AsyncClient() as client:
            url = "https://chainlist.org/rpcs.json"
            response = await client.get(url, timeout=30.0)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Chainlist API returned status {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error fetching chainlist JSON: {e}")
        return None


def _generate_cache_key(endpoint: str, **kwargs) -> str:
    """
    Generate a cache key from endpoint name and parameters
    """
    key_data = {"endpoint": endpoint, **kwargs}
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_string.encode()).hexdigest()


def _get_cached_result(cache_key: str) -> Optional[Any]:
    """
    Get cached result if it exists and is not expired
    Entries with timestamp=float('inf') never expire
    """
    if cache_key in _result_cache:
        cache_entry = _result_cache[cache_key]
        timestamp = cache_entry["timestamp"]
        
        # Entries with infinity timestamp never expire
        if timestamp == float('inf'):
            logger.debug(f"Cache hit for key: {cache_key} (permanent)")
            return cache_entry["result"]
        
        # Check if regular cache entry is still valid
        current_time = time.time()
        if (current_time - timestamp) < _result_cache_ttl:
            logger.debug(f"Cache hit for key: {cache_key}")
            return cache_entry["result"]
        else:
            # Cache expired, remove it
            del _result_cache[cache_key]
            logger.debug(f"Cache expired for key: {cache_key}")
    return None


def _set_cached_result(cache_key: str, result: Any, ttl: float = None):
    """
    Store result in cache with current timestamp
    If ttl=float('inf'), the entry never expires
    """
    if ttl is None:
        ttl = _result_cache_ttl
    
    # Use infinity as timestamp to indicate permanent entry
    timestamp = float('inf') if ttl == float('inf') else time.time()
    
    _result_cache[cache_key] = {
        "result": result,
        "timestamp": timestamp
    }
    logger.debug(f"Cached result for key: {cache_key} (permanent={ttl == float('inf')})")


def _get_erc20_metadata_key(chain_id: int, contract_address: str) -> str:
    """
    Generate a cache key for ERC20 metadata (chain_id + contract_address)
    """
    return _generate_cache_key("erc20_metadata", chain_id=chain_id, contract_address=contract_address.lower())


def _get_cached_erc20_metadata(chain_id: int, contract_address: str) -> Optional[Dict[str, Any]]:
    """
    Get cached ERC20 metadata (symbol and decimals) if it exists
    Uses the shared cache with ttl=float('inf')
    """
    cache_key = _get_erc20_metadata_key(chain_id, contract_address)
    return _get_cached_result(cache_key)


def _set_cached_erc20_metadata(chain_id: int, contract_address: str, decimals: Optional[int], symbol: Optional[str]):
    """
    Store ERC20 metadata in permanent cache
    Uses the shared cache with ttl=float('inf')
    """
    cache_key = _get_erc20_metadata_key(chain_id, contract_address)
    metadata = {
        "decimals": decimals,
        "symbol": symbol
    }
    _set_cached_result(cache_key, metadata, ttl=float('inf'))
    logger.debug(f"Cached ERC20 metadata for chain {chain_id}, contract {contract_address}")


async def get_chainlist_rpc(chain_id: int) -> Optional[str]:
    """
    Fetch RPC URL for a given chain ID from chainlist.org/rpcs.json
    Uses cached data to avoid repeated downloads.
    """
    global _chainlist_cache, _cache_timestamp
    
    # Check if cache is valid
    current_time = time.time()
    if _chainlist_cache is None or (current_time - _cache_timestamp) > _cache_ttl:
        logger.info("Fetching chainlist JSON (cache miss or expired)")
        _chainlist_cache = await _fetch_chainlist_json()
        _cache_timestamp = current_time
        
        if _chainlist_cache is None:
            logger.error("Failed to fetch chainlist JSON")
            return None
    else:
        logger.debug("Using cached chainlist data")
    
    # Find chain by chainId
    for chain in _chainlist_cache:
        if chain.get("chainId") == chain_id:
            rpc_list = chain.get("rpc", [])
            if rpc_list and len(rpc_list) > 0:
                # Get the first RPC URL
                first_rpc = rpc_list[0]
                if isinstance(first_rpc, dict):
                    rpc_url = first_rpc.get("url")
                    if rpc_url and isinstance(rpc_url, str):
                        return rpc_url
                elif isinstance(first_rpc, str):
                    return first_rpc
    
    logger.warning(f"Chain ID {chain_id} not found in chainlist")
    return None


@app.get("/")
async def root():
    """Root endpoint"""
    response = {
        "message": "Blockchain Balance API",
        "endpoints": {
            "btc": "/btc/<address>",
            "evm_native": "/evm/<chainid>/native/<address>",
            "evm_erc20": "/evm/<chainid>/erc20/<erc20-ca>/<address>"
        }
    }
    logger.info(f"API Response [GET /]: {json.dumps(response)}")
    return response


@app.get("/btc/{address}")
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


@app.get("/evm/{chain_id}/native/{address}")
async def get_evm_native_balance(chain_id: int, address: str, full: bool = False):
    """
    Get native token (ETH, MATIC, etc.) balance for an EVM address
    Returns formatted balance (ether) by default, or full JSON if full=true
    """
    # Check cache first
    cache_key = _generate_cache_key("evm_native", chain_id=chain_id, address=address, full=full)
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        logger.info(f"API Response [GET /evm/{chain_id}/native/{address}?full={full}]: {json.dumps(cached_result, default=str)}")
        return cached_result
    
    try:
        # Validate address format
        if not Web3.is_address(address):
            raise HTTPException(status_code=400, detail="Invalid EVM address format")
        
        # Get RPC URL from chainlist
        rpc_url = await get_chainlist_rpc(chain_id)
        if not rpc_url:
            raise HTTPException(
                status_code=404,
                detail=f"Could not find RPC endpoint for chain ID {chain_id}"
            )
        
        # Connect to Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        # Check if connected
        if not w3.is_connected():
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to RPC endpoint for chain {chain_id}"
            )
        
        # Get balance
        balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
        balance_ether = Web3.from_wei(balance_wei, "ether")
        
        full_response = {
            "address": address,
            "chain_id": chain_id,
            "balance_wei": str(balance_wei),
            "balance_ether": str(balance_ether),
            "rpc_url": rpc_url
        }
        
        # Return formatted balance by default, or full response if full=true
        if full:
            result = full_response
        else:
            result = float(balance_ether)
        
        # Cache the result
        _set_cached_result(cache_key, result)
        logger.info(f"API Response [GET /evm/{chain_id}/native/{address}?full={full}]: {json.dumps(result, default=str)}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching EVM native balance: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/evm/{chain_id}/erc20/{erc20_contract_address}/{address}")
async def get_evm_erc20_balance(
    chain_id: int,
    erc20_contract_address: str,
    address: str,
    full: bool = False
):
    """
    Get ERC20 token balance for an EVM address
    Returns formatted balance by default, or full JSON if full=true
    """
    # Check cache first
    cache_key = _generate_cache_key(
        "evm_erc20",
        chain_id=chain_id,
        erc20_contract_address=erc20_contract_address,
        address=address,
        full=full
    )
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        logger.info(f"API Response [GET /evm/{chain_id}/erc20/{erc20_contract_address}/{address}?full={full}]: {json.dumps(cached_result, default=str)}")
        return cached_result
    
    try:
        # Validate address formats
        if not Web3.is_address(address):
            raise HTTPException(status_code=400, detail="Invalid address format")
        if not Web3.is_address(erc20_contract_address):
            raise HTTPException(status_code=400, detail="Invalid ERC20 contract address format")
        
        # Get RPC URL from chainlist
        rpc_url = await get_chainlist_rpc(chain_id)
        if not rpc_url:
            raise HTTPException(
                status_code=404,
                detail=f"Could not find RPC endpoint for chain ID {chain_id}"
            )
        
        # Connect to Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        # Check if connected
        if not w3.is_connected():
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to RPC endpoint for chain {chain_id}"
            )
        
        # ERC20 ABI for balanceOf function
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "symbol",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            }
        ]
        
        # Create contract instance
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(erc20_contract_address),
            abi=erc20_abi
        )
        
        # Check cache for ERC20 metadata first (decimals and symbol never change)
        cached_metadata = _get_cached_erc20_metadata(chain_id, erc20_contract_address)
        
        if cached_metadata:
            decimals = cached_metadata.get("decimals")
            symbol = cached_metadata.get("symbol") if full else None
        else:
            # Get token decimals with retry logic
            decimals = None
            max_retries = 3
            retry_delay = 1  # seconds
            
            for attempt in range(max_retries):
                try:
                    decimals = contract.functions.decimals().call()
                    if decimals is not None:
                        break
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed to get decimals: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"Failed to get decimals after {max_retries} attempts")
            
            # If decimals is still None after retries, default to 18
            if decimals is None:
                logger.warning(f"decimals() returned None for contract {erc20_contract_address}, defaulting to 18")
                decimals = 18
            
            # Get token symbol if needed
            symbol = None
            if full:
                try:
                    symbol = contract.functions.symbol().call()
                except Exception:
                    symbol = "UNKNOWN"
            
            # Cache the metadata permanently
            _set_cached_erc20_metadata(chain_id, erc20_contract_address, decimals, symbol)
        
        # Get balance
        balance_raw = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        
        # Calculate human-readable balance
        balance_formatted = balance_raw / (10 ** decimals)
        
        full_response = {
            "address": address,
            "chain_id": chain_id,
            "contract_address": erc20_contract_address,
            "balance_raw": str(balance_raw),
            "balance_formatted": str(balance_formatted),
            "decimals": decimals,
            "symbol": symbol,
            "rpc_url": rpc_url
        }
        
        # Return formatted balance by default, or full response if full=true
        if full:
            result = full_response
        else:
            result = float(balance_formatted)
        
        # Cache the result
        _set_cached_result(cache_key, result)
        logger.info(f"API Response [GET /evm/{chain_id}/erc20/{erc20_contract_address}/{address}?full={full}]: {json.dumps(result, default=str)}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching ERC20 balance: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

