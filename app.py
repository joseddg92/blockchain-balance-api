"""
Blockchain Balance API
A REST API to query Bitcoin and EVM chain balances
"""

from fastapi import FastAPI
import logging
import json
from btc import router as btc_router
from evm import router as evm_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Blockchain Balance API",
    description="API to query Bitcoin and EVM chain balances",
    version="1.0.0"
)

# Include routers
app.include_router(btc_router)
app.include_router(evm_router)


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

