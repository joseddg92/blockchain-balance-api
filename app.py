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
    return {
        "message": "Blockchain Balance API",
        "endpoints": {
            "btc": "/btc/<address>",
            "evm_native": "/evm/<chainid>/native/<address>",
            "evm_erc20": "/evm/<chainid>/erc20/<erc20-ca>/<address>"
        }
    }


@app.get("/btc/{address}")
async def get_btc_balance(address: str, full: bool = False):
    """
    Get Bitcoin balance for an address using mempool.space API
    Returns formatted balance (BTC) by default, or full JSON if full=true
    """
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
            
            # Convert satoshi to BTC (1 BTC = 100,000,000 satoshi)
            balance_btc = balance_satoshi / 100_000_000
            
            full_response = {
                "address": address,
                "balance_satoshi": balance_satoshi,
                "balance_btc": balance_btc,
                "confirmed_balance_satoshi": chain_stats.get("funded_txo_sum", 0) - chain_stats.get("spent_txo_sum", 0),
                "unconfirmed_balance_satoshi": mempool_stats.get("funded_txo_sum", 0) - mempool_stats.get("spent_txo_sum", 0)
            }
            
            # Return formatted balance by default, or full response if full=true
            if full:
                return full_response
            else:
                return balance_btc
            
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
            return full_response
        else:
            return str(balance_ether)
        
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
        
        # Get balance
        balance_raw = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        
        # Get token decimals
        try:
            decimals = contract.functions.decimals().call()
        except Exception:
            decimals = None  # Default to 18 if decimals() is not available
        
        # Calculate human-readable balance
        balance_formatted = balance_raw / (10 ** decimals)
        
        # Get token symbol if available
        if full:
            try:
                symbol = contract.functions.symbol().call()
            except Exception:
                symbol = "UNKNOWN"
        else:
            symbol = None
        
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
            return full_response
        else:
            return str(balance_formatted)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching ERC20 balance: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

