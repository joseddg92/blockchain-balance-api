# Blockchain Balance API

A REST API to query Bitcoin and EVM chain balances.

## Features

- **Bitcoin Balance**: Query Bitcoin address balances using mempool.space API
- **EVM Native Balance**: Query native token balances (ETH, MATIC, etc.) for any EVM-compatible chain
- **ERC20 Token Balance**: Query ERC20 token balances for any EVM-compatible chain

## Installation

### Option 1: Local Installation

1. Install Python 3.14 (or compatible version)

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the API:
```bash
python app.py
```

Or using uvicorn directly:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Option 2: Docker

1. Build and run with Docker Compose:
```bash
docker-compose up --build
```

Or run with Docker directly:
```bash
docker build -t blockchain-balance-api .
docker run -p 8000:8000 blockchain-balance-api
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Root
- `GET /` - API information and available endpoints

### Bitcoin Balance
- `GET /btc/<address>` - Get Bitcoin balance for an address
- `GET /btc/<address>?full` - Get full Bitcoin balance details

**Example:**
```bash
curl http://localhost:8000/btc/1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
```

**Response (default):**
```
50.0
```

**Response (with ?full):**
```json
{
  "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
  "balance_satoshi": 5000000000,
  "balance_btc": 50.0,
  "confirmed_balance_satoshi": 5000000000,
  "unconfirmed_balance_satoshi": 0
}
```

### EVM Native Balance
- `GET /evm/<chainid>/native/<address>` - Get native token balance for an EVM address
- `GET /evm/<chainid>/native/<address>?full` - Get full native token balance details

**Example:**
```bash
curl http://localhost:8000/evm/1/native/0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
```

**Response (default):**
```
"1.0"
```

**Response (with ?full):**
```json
{
  "address": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
  "chain_id": 1,
  "balance_wei": "1000000000000000000",
  "balance_ether": "1.0",
  "rpc_url": "https://eth.llamarpc.com"
}
```

### ERC20 Token Balance
- `GET /evm/<chainid>/erc20/<erc20-ca>/<address>` - Get ERC20 token balance
- `GET /evm/<chainid>/erc20/<erc20-ca>/<address>?full` - Get full ERC20 token balance details

**Example:**
```bash
curl http://localhost:8000/evm/1/erc20/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48/0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
```

**Response (default):**
```
"1.0"
```

**Response (with ?full):**
```json
{
  "address": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
  "chain_id": 1,
  "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  "balance_raw": "1000000",
  "balance_formatted": "1.0",
  "decimals": 6,
  "symbol": "USDC",
  "rpc_url": "https://eth.llamarpc.com"
}
```

## Supported Chains

The API uses [chainlist.org](https://chainlist.org) to automatically discover RPC endpoints for any EVM-compatible chain. Simply provide the chain ID in the endpoint URL.

Common chain IDs:
- `1` - Ethereum Mainnet
- `137` - Polygon
- `56` - BSC (Binance Smart Chain)
- `42161` - Arbitrum One
- `10` - Optimism
- `43114` - Avalanche C-Chain

## API Documentation

When the server is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Error Handling

The API returns appropriate HTTP status codes:
- `200` - Success
- `400` - Bad Request (invalid address format)
- `404` - Not Found (address or chain not found)
- `500` - Internal Server Error
- `503` - Service Unavailable (RPC connection issues)

