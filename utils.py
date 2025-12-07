"""
Utility functions for caching and chainlist management
"""

import httpx
from typing import Optional, Dict, List, Any
import logging
import time
import hashlib
import json

# Configure logging
logger = logging.getLogger(__name__)

# Cache for chainlist JSON data
_chainlist_cache: Optional[List[Dict[str, Any]]] = None
_cache_timestamp: float = 0
_cache_ttl: int = 3600  # Cache for 1 hour

# Cache for API results (30 minutes TTL) and permanent entries (ERC20 metadata)
_result_cache: Dict[str, Dict[str, Any]] = {}
_result_cache_ttl: int = 1800  # 30 minutes in seconds

# Cache for Web3 clients (keyed by chain_id)
# Stores dict with 'w3' (Web3 instance) and 'rpc_url' (string)
_web3_cache: Dict[int, Dict[str, Any]] = {}


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


def get_cached_web3(chain_id: int) -> Optional[Dict[str, Any]]:
    """
    Get cached Web3 client for a chain_id if it exists and is still connected
    Returns dict with 'w3' and 'rpc_url' if cached and connected, None otherwise
    """
    if chain_id in _web3_cache:
        cache_entry = _web3_cache[chain_id]
        w3 = cache_entry.get('w3')
        try:
            # Verify connection is still active
            if w3.is_connected():
                logger.debug(f"Using cached Web3 client for chain {chain_id}")
                return cache_entry
            else:
                # Connection lost, remove from cache
                logger.warning(f"Cached Web3 client for chain {chain_id} lost connection, removing from cache")
                del _web3_cache[chain_id]
        except Exception as e:
            # Error checking connection, remove from cache
            logger.warning(f"Error checking cached Web3 client for chain {chain_id}: {e}, removing from cache")
            del _web3_cache[chain_id]
    return None


def set_cached_web3(chain_id: int, w3: Any, rpc_url: str):
    """
    Cache a Web3 client for a chain_id along with its RPC URL
    """
    _web3_cache[chain_id] = {
        'w3': w3,
        'rpc_url': rpc_url
    }
    logger.debug(f"Cached Web3 client for chain {chain_id}")


async def get_or_create_web3(chain_id: int) -> Optional[Dict[str, Any]]:
    """
    Get or create a Web3 client for a chain_id
    Returns dict with 'w3' (Web3 instance) and 'rpc_url' (string) if available and connected,
    otherwise creates and caches a new one
    """
    from web3 import Web3
    
    # Try to get cached client
    cached = get_cached_web3(chain_id)
    if cached is not None:
        return cached
    
    # Create new client
    rpc_url = await get_chainlist_rpc(chain_id)
    if not rpc_url:
        return None
    
    w3 = Web3(Web3.HTTPProvider(rpc_url), cache_allowed_requests=True)
    
    # Verify connection
    if not w3.is_connected():
        logger.error(f"Could not connect to RPC endpoint for chain {chain_id}")
        return None
    
    # Cache the client
    set_cached_web3(chain_id, w3, rpc_url)
    logger.info(f"Created and cached new Web3 client for chain {chain_id}")
    return {
        'w3': w3,
        'rpc_url': rpc_url
    }


# Export cache functions for use in other modules
__all__ = [
    '_generate_cache_key',
    '_get_cached_result',
    '_set_cached_result',
    '_get_cached_erc20_metadata',
    '_set_cached_erc20_metadata',
    'get_chainlist_rpc',
    'get_or_create_web3'
]
