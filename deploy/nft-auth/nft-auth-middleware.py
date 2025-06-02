#!/usr/bin/env python3
"""
NFT Authentication Middleware for MiladyOS MCP Server
Simple High Integrity Milady NFT ownership verification
"""

import json
import time
import hashlib
import redis
from functools import wraps
from typing import Optional, Dict, Any
from web3 import Web3
from eth_account.messages import encode_defunct
import requests
from flask import request, jsonify, abort

# Configuration
HIGH_INTEGRITY_MILADY_CONTRACT = "0xf01B34d9418874258B35b0507AB53ED971CBB8D3"
ETHEREUM_RPC_URL = "https://mainnet.infura.io/v3/YOUR_PROJECT_ID"
ETHERSCAN_API_KEY = "YOUR_ETHERSCAN_API_KEY"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
CACHE_TTL = 600  # 10 minutes

class NFTAuthMiddleware:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(ETHEREUM_RPC_URL))
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.contract_address = Web3.to_checksum_address(HIGH_INTEGRITY_MILADY_CONTRACT)
        
    def verify_wallet_signature(self, wallet_address: str, signature: str, message: str) -> bool:
        """Verify wallet signature"""
        try:
            # Encode message for verification
            encoded_message = encode_defunct(text=message)
            
            # Recover address from signature
            recovered_address = self.w3.eth.account.recover_message(
                encoded_message, 
                signature=signature
            )
            
            return recovered_address.lower() == wallet_address.lower()
        except Exception as e:
            print(f"Signature verification failed: {e}")
            return False
    
    def check_nft_ownership_etherscan(self, wallet_address: str) -> bool:
        """Check NFT ownership using Etherscan API"""
        try:
            # Check cache first
            cache_key = f"nft_ownership:{wallet_address.lower()}"
            cached_result = self.redis_client.get(cache_key)
            if cached_result:
                return json.loads(cached_result)
            
            # Call Etherscan API
            url = "https://api.etherscan.io/api"
            params = {
                "module": "account",
                "action": "tokennfttx",
                "contractaddress": self.contract_address,
                "address": wallet_address,
                "page": 1,
                "offset": 100,
                "sort": "desc",
                "apikey": ETHERSCAN_API_KEY
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("status") == "1" and data.get("result"):
                # Check if wallet currently owns any tokens
                for tx in data["result"]:
                    if tx["to"].lower() == wallet_address.lower():
                        # Cache positive result
                        self.redis_client.setex(cache_key, CACHE_TTL, json.dumps(True))
                        return True
            
            # Cache negative result (shorter TTL)
            self.redis_client.setex(cache_key, 60, json.dumps(False))
            return False
            
        except Exception as e:
            print(f"NFT ownership check failed: {e}")
            return False
    
    def check_nft_ownership_rpc(self, wallet_address: str) -> bool:
        """Check NFT ownership using direct RPC call"""
        try:
            # ERC-721 balanceOf function signature
            function_signature = "0x70a08231"  # balanceOf(address)
            wallet_padded = wallet_address[2:].zfill(64)
            data = function_signature + wallet_padded
            
            result = self.w3.eth.call({
                "to": self.contract_address,
                "data": data
            })
            
            # Convert result to integer
            balance = int(result.hex(), 16)
            return balance > 0
            
        except Exception as e:
            print(f"RPC ownership check failed: {e}")
            return False

# Global middleware instance
nft_auth = NFTAuthMiddleware()

def require_nft_auth(f):
    """Decorator to require High Integrity Milady NFT ownership"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for authentication header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid authorization header"}), 401
        
        try:
            # Parse the token (simple JSON for now)
            token_data = json.loads(auth_header[7:])  # Remove "Bearer "
            wallet_address = token_data.get('wallet_address')
            signature = token_data.get('signature')
            timestamp = token_data.get('timestamp')
            nonce = token_data.get('nonce')
            
            if not all([wallet_address, signature, timestamp, nonce]):
                return jsonify({"error": "Invalid token format"}), 401
            
            # Check timestamp (5 minute window)
            if abs(time.time() - timestamp) > 300:
                return jsonify({"error": "Token expired"}), 401
            
            # Verify signature
            message = f"MiladyOS Access Request\nWallet: {wallet_address}\nTimestamp: {timestamp}\nNonce: {nonce}"
            if not nft_auth.verify_wallet_signature(wallet_address, signature, message):
                return jsonify({"error": "Invalid signature"}), 401
            
            # Check NFT ownership
            owns_nft = (nft_auth.check_nft_ownership_rpc(wallet_address) or 
                       nft_auth.check_nft_ownership_etherscan(wallet_address))
            
            if not owns_nft:
                return jsonify({"error": "High Integrity Milady NFT required"}), 403
            
            # Add wallet info to request context
            request.nft_wallet = wallet_address
            request.nft_verified = True
            
            return f(*args, **kwargs)
            
        except Exception as e:
            print(f"Authentication error: {e}")
            return jsonify({"error": "Authentication failed"}), 401
    
    return decorated_function

def create_auth_token(wallet_address: str, private_key: str) -> Dict[str, Any]:
    """Helper function to create authentication token (for testing)"""
    timestamp = int(time.time())
    nonce = hashlib.sha256(f"{wallet_address}{timestamp}".encode()).hexdigest()[:16]
    
    message = f"MiladyOS Access Request\nWallet: {wallet_address}\nTimestamp: {timestamp}\nNonce: {nonce}"
    
    # Sign message
    encoded_message = encode_defunct(text=message)
    signed_message = nft_auth.w3.eth.account.sign_message(encoded_message, private_key=private_key)
    
    return {
        "wallet_address": wallet_address,
        "signature": signed_message.signature.hex(),
        "timestamp": timestamp,
        "nonce": nonce
    }

# Example usage in MCP server routes
def apply_nft_auth_to_mcp():
    """Apply NFT authentication to sensitive MCP endpoints"""
    from main import app  # Import your MCP Flask app
    
    # Protect sensitive endpoints
    sensitive_endpoints = [
        '/execute_command',
        '/pipeline_management', 
        '/template_edit',
        '/database_query'
    ]
    
    for endpoint in sensitive_endpoints:
        # Get the existing route function
        existing_rule = None
        for rule in app.url_map.iter_rules():
            if rule.rule == endpoint:
                existing_rule = rule
                break
        
        if existing_rule:
            # Wrap with NFT auth
            view_func = app.view_functions[existing_rule.endpoint]
            app.view_functions[existing_rule.endpoint] = require_nft_auth(view_func)

if __name__ == "__main__":
    # Test NFT ownership check
    test_wallet = "0x1234567890123456789012345678901234567890"
    result = nft_auth.check_nft_ownership_etherscan(test_wallet)
    print(f"NFT ownership for {test_wallet}: {result}")