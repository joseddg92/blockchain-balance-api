"""
EVM chain balance endpoints (native and ERC20)
"""

from fastapi import APIRouter, HTTPException
from web3 import Web3
import logging
import json
import asyncio
from utils import (
    _generate_cache_key,
    _get_cached_result,
    _set_cached_result,
    _get_cached_erc20_metadata,
    _set_cached_erc20_metadata,
    get_or_create_web3
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/evm/{chain_id}/native/{address}")
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
        
        # Get or create cached Web3 client
        web3_info = await get_or_create_web3(chain_id)
        if not web3_info:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to RPC endpoint for chain {chain_id}"
            )
        
        w3 = web3_info['w3']
        rpc_url = web3_info['rpc_url']
        
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


@router.get("/evm/{chain_id}/erc20/{erc20_contract_address}/{address}")
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
        
        # Get or create cached Web3 client
        web3_info = await get_or_create_web3(chain_id)
        if not web3_info:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to RPC endpoint for chain {chain_id}"
            )
        
        w3 = web3_info['w3']
        rpc_url = web3_info['rpc_url']
        
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
