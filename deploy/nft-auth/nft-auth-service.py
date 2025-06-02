#!/usr/bin/env python3
"""
NFT Authentication Service for MiladyOS
Standalone service similar to TinyAuth but with High Integrity Milady NFT verification
"""

import json
import time
import hashlib
import redis
import base64
from typing import Optional, Dict, Any
from web3 import Web3
from eth_account.messages import encode_defunct
import requests
from flask import Flask, request, jsonify, redirect, render_template_string, make_response
import os

app = Flask(__name__)

# Configuration from environment
HIGH_INTEGRITY_MILADY_CONTRACT = os.getenv("HIGH_INTEGRITY_MILADY_CONTRACT", "0xf01B34d9418874258B35b0507AB53ED971CBB8D3")
ETHEREUM_RPC_URL = os.getenv("ETHEREUM_RPC_URL", "https://mainnet.infura.io/v3/YOUR_PROJECT_ID")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "YOUR_ETHERSCAN_API_KEY")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8080"))

class NFTAuthService:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(ETHEREUM_RPC_URL))
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.contract_address = Web3.to_checksum_address(HIGH_INTEGRITY_MILADY_CONTRACT)
        
    def verify_wallet_signature(self, wallet_address: str, signature: str, message: str) -> bool:
        """Verify wallet signature"""
        try:
            encoded_message = encode_defunct(text=message)
            recovered_address = self.w3.eth.account.recover_message(
                encoded_message, 
                signature=signature
            )
            return recovered_address.lower() == wallet_address.lower()
        except Exception as e:
            print(f"Signature verification failed: {e}")
            return False
    
    def check_nft_ownership_rpc(self, wallet_address: str) -> bool:
        """Check NFT ownership using direct RPC call"""
        try:
            # Check cache first
            cache_key = f"nft_ownership:{wallet_address.lower()}"
            cached_result = self.redis_client.get(cache_key)
            if cached_result:
                return json.loads(cached_result)
            
            # ERC-721 balanceOf function signature
            function_signature = "0x70a08231"  # balanceOf(address)
            wallet_padded = wallet_address[2:].zfill(64)
            data = function_signature + wallet_padded
            
            result = self.w3.eth.call({
                "to": self.contract_address,
                "data": data
            })
            
            balance = int(result.hex(), 16)
            owns_nft = balance > 0
            
            # Cache result
            self.redis_client.setex(cache_key, CACHE_TTL, json.dumps(owns_nft))
            return owns_nft
            
        except Exception as e:
            print(f"RPC ownership check failed: {e}")
            return False

# Initialize service
nft_auth = NFTAuthService()

# HTML templates
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>High Integrity Milady Authentication</title>
    <script src="https://cdn.ethers.io/lib/ethers-5.7.2.umd.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
        .container { text-align: center; background: #f5f5f5; padding: 30px; border-radius: 10px; }
        button { background: #007bff; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; margin: 10px; }
        button:hover { background: #0056b3; }
        .error { color: red; margin: 10px 0; }
        .success { color: green; margin: 10px 0; }
        .milady-logo { font-size: 48px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="milady-logo">✨</div>
        <h2>High Integrity Milady Authentication</h2>
        <p>Connect your wallet to verify NFT ownership</p>
        <button onclick="connectWallet()">Connect MetaMask</button>
        <div id="status"></div>
        <div id="error" class="error"></div>
    </div>

    <script>
        const CONTRACT_ADDRESS = "{{ contract_address }}";
        
        async function connectWallet() {
            const statusDiv = document.getElementById('status');
            const errorDiv = document.getElementById('error');
            
            try {
                if (!window.ethereum) {
                    throw new Error("MetaMask not found");
                }
                
                // Request account access
                await window.ethereum.request({ method: 'eth_requestAccounts' });
                
                const provider = new ethers.providers.Web3Provider(window.ethereum);
                const signer = provider.getSigner();
                const walletAddress = await signer.getAddress();
                
                statusDiv.innerHTML = `Connected: ${walletAddress}`;
                
                // Check NFT ownership
                const abi = ["function balanceOf(address owner) view returns (uint256)"];
                const contract = new ethers.Contract(CONTRACT_ADDRESS, abi, provider);
                const balance = await contract.balanceOf(walletAddress);
                
                if (!balance.gt(0)) {
                    throw new Error("High Integrity Milady NFT required for access");
                }
                
                // Generate signature for authentication
                const timestamp = Math.floor(Date.now() / 1000);
                const nonce = ethers.utils.id(`${walletAddress}${timestamp}`).substring(0, 18);
                const message = `MiladyOS Access Request\\nWallet: ${walletAddress}\\nTimestamp: ${timestamp}\\nNonce: ${nonce}`;
                
                const signature = await signer.signMessage(message);
                
                // Submit authentication
                const authData = {
                    wallet_address: walletAddress,
                    signature: signature,
                    timestamp: timestamp,
                    nonce: nonce
                };
                
                const response = await fetch('/authenticate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(authData)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    const redirectUrl = new URLSearchParams(window.location.search).get('rd') || '/';
                    window.location.href = redirectUrl;
                } else {
                    throw new Error(result.error);
                }
                
            } catch (error) {
                errorDiv.textContent = error.message;
                console.error('Authentication failed:', error);
            }
        }
    </script>
</body>
</html>
"""

@app.route('/login')
def login():
    """Login page with Web3 authentication"""
    return render_template_string(LOGIN_TEMPLATE, contract_address=HIGH_INTEGRITY_MILADY_CONTRACT)

@app.route('/authenticate', methods=['POST'])
def authenticate():
    """Handle Web3 authentication"""
    try:
        data = request.get_json()
        wallet_address = data.get('wallet_address')
        signature = data.get('signature')
        timestamp = data.get('timestamp')
        nonce = data.get('nonce')
        
        if not all([wallet_address, signature, timestamp, nonce]):
            return jsonify({"success": False, "error": "Missing authentication data"}), 400
        
        # Check timestamp (5 minute window)
        if abs(time.time() - timestamp) > 300:
            return jsonify({"success": False, "error": "Authentication expired"}), 400
        
        # Verify signature
        message = f"MiladyOS Access Request\\nWallet: {wallet_address}\\nTimestamp: {timestamp}\\nNonce: {nonce}"
        if not nft_auth.verify_wallet_signature(wallet_address, signature, message):
            return jsonify({"success": False, "error": "Invalid signature"}), 401
        
        # Check NFT ownership
        if not nft_auth.check_nft_ownership_rpc(wallet_address):
            return jsonify({"success": False, "error": "High Integrity Milady NFT required"}), 403
        
        # Create session token
        session_data = {
            "wallet": wallet_address,
            "authenticated": True,
            "timestamp": time.time()
        }
        
        token = base64.b64encode(json.dumps(session_data).encode()).decode()
        
        # Set secure cookie
        response = make_response(jsonify({"success": True, "wallet": wallet_address}))
        response.set_cookie('nft_auth_token', token, 
                          max_age=3600,  # 1 hour
                          secure=True, 
                          httponly=True,
                          samesite='Lax')
        
        return response
        
    except Exception as e:
        print(f"Authentication error: {e}")
        return jsonify({"success": False, "error": "Authentication failed"}), 500

@app.route('/auth')
def auth_check():
    """Authentication check endpoint for ingress-nginx"""
    try:
        # Check for authentication token
        token = request.cookies.get('nft_auth_token') or request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            return '', 401
        
        # Verify token
        try:
            session_data = json.loads(base64.b64decode(token).decode())
            
            # Check if token is still valid (1 hour)
            if time.time() - session_data.get('timestamp', 0) > 3600:
                return '', 401
            
            if not session_data.get('authenticated'):
                return '', 401
                
            # Add user info to response headers
            response = make_response('', 200)
            response.headers['X-Auth-User'] = session_data.get('wallet', '')
            response.headers['X-Auth-NFT'] = 'high-integrity-milady'
            
            return response
            
        except Exception:
            return '', 401
        
    except Exception as e:
        print(f"Auth check error: {e}")
        return '', 500

@app.route('/logout')
def logout():
    """Logout endpoint"""
    response = make_response(redirect('/login'))
    response.set_cookie('nft_auth_token', '', expires=0)
    return response

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "nft-auth"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=SERVICE_PORT, debug=False)