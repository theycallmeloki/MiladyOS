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
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; 
            background: #0a0a0a; 
            color: #ffffff; 
            min-height: 100vh; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            padding: 20px; 
        }
        .container { 
            max-width: 500px; 
            width: 100%; 
            background: rgba(255, 255, 255, 0.02); 
            border: 1px solid rgba(255, 255, 255, 0.1); 
            border-radius: 20px; 
            padding: 40px; 
            backdrop-filter: blur(20px); 
            text-align: center; 
        }
        .milady-logo { 
            font-size: 64px; 
            margin-bottom: 16px; 
            filter: drop-shadow(0 0 20px rgba(255, 255, 255, 0.3)); 
        }
        .title { 
            font-size: 28px; 
            font-weight: 600; 
            margin-bottom: 8px; 
            background: linear-gradient(135deg, #ff6b9d 0%, #c44569 100%); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
            background-clip: text; 
        }
        .subtitle { 
            color: rgba(255, 255, 255, 0.7); 
            font-size: 16px; 
            margin-bottom: 30px; 
        }
        .connect-button { 
            width: 100%; 
            padding: 16px 24px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            border: none; 
            border-radius: 12px; 
            color: white; 
            font-size: 16px; 
            font-weight: 500; 
            cursor: pointer; 
            transition: all 0.3s ease; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            gap: 12px; 
            margin: 20px 0; 
        }
        .connect-button:hover { 
            transform: translateY(-2px); 
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3); 
        }
        .connect-button:disabled { 
            opacity: 0.6; 
            cursor: not-allowed; 
            transform: none; 
        }
        .status { 
            margin: 20px 0; 
            padding: 16px; 
            border-radius: 8px; 
            background: rgba(76, 175, 80, 0.1); 
            border: 1px solid #4CAF50; 
            color: #4CAF50; 
        }
        .error { 
            margin: 20px 0; 
            padding: 16px; 
            border-radius: 8px; 
            background: rgba(244, 67, 54, 0.1); 
            border: 1px solid #f44336; 
            color: #f44336; 
        }
        .loading { 
            display: inline-block; 
            width: 20px; 
            height: 20px; 
            border: 2px solid rgba(255, 255, 255, 0.3); 
            border-radius: 50%; 
            border-top-color: #fff; 
            animation: spin 1s ease-in-out infinite; 
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .wallet-address { 
            font-family: 'Courier New', monospace; 
            font-size: 12px; 
            word-break: break-all; 
            margin-top: 8px; 
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="milady-logo">✨</div>
        <h1 class="title">Sign in with Ethereum</h1>
        <p class="subtitle">High Integrity Milady NFT Authentication</p>
        
        <button id="connectBtn" class="connect-button" onclick="signInWithEthereum()">
            🦊 Sign in with Ethereum
        </button>
        
        <div id="status" style="display: none;"></div>
        <div id="error" style="display: none;"></div>
    </div>

    <script>
        const CONTRACT_ADDRESS = "{{ contract_address }}";
        
        async function signInWithEthereum() {
            const connectBtn = document.getElementById('connectBtn');
            const statusDiv = document.getElementById('status');
            const errorDiv = document.getElementById('error');
            
            // Hide previous messages
            statusDiv.style.display = 'none';
            errorDiv.style.display = 'none';
            
            // Update button to loading state
            connectBtn.innerHTML = '<span class="loading"></span> Connecting...';
            connectBtn.disabled = true;
            
            try {
                if (!window.ethereum) {
                    throw new Error("MetaMask not found. Please install MetaMask to continue.");
                }
                
                // Request account access
                const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
                const walletAddress = accounts[0];
                
                statusDiv.innerHTML = `Connected: <div class="wallet-address">${walletAddress}</div>`;
                statusDiv.className = 'status';
                statusDiv.style.display = 'block';
                
                // Check network
                const chainId = await window.ethereum.request({ method: 'eth_chainId' });
                if (chainId !== '0x1') {
                    await window.ethereum.request({
                        method: 'wallet_switchEthereumChain',
                        params: [{ chainId: '0x1' }],
                    });
                }
                
                // Check NFT ownership
                const provider = new ethers.providers.Web3Provider(window.ethereum);
                const abi = ["function balanceOf(address owner) view returns (uint256)"];
                const contract = new ethers.Contract(CONTRACT_ADDRESS, abi, provider);
                const balance = await contract.balanceOf(walletAddress);
                
                if (!balance.gt(0)) {
                    throw new Error("High Integrity Milady NFT required for access");
                }
                
                // Generate SIWE message (EIP-4361 compliant)
                const domain = window.location.host;
                const timestamp = new Date().toISOString();
                const nonce = Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
                
                const siweMessage = `${domain} wants you to sign in with your Ethereum account:
${walletAddress}

I accept the terms of service.

URI: ${window.location.origin}
Version: 1
Chain ID: 1
Nonce: ${nonce}
Issued At: ${timestamp}`;
                
                statusDiv.innerHTML = 'Please sign the message in MetaMask...';
                
                // Sign the SIWE message
                const signature = await window.ethereum.request({
                    method: 'personal_sign',
                    params: [
                        siweMessage,
                        walletAddress
                    ]
                });
                
                // Submit authentication to server
                const authData = {
                    wallet_address: walletAddress,
                    signature: signature,
                    message: siweMessage,
                    nonce: nonce,
                    timestamp: timestamp
                };
                
                const response = await fetch('/authenticate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(authData)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    statusDiv.innerHTML = '✅ Authentication successful! Redirecting...';
                    statusDiv.className = 'status';
                    
                    // Redirect back to original URL
                    const redirectUrl = new URLSearchParams(window.location.search).get('rd') || '/';
                    setTimeout(() => {
                        window.location.href = redirectUrl;
                    }, 1000);
                } else {
                    throw new Error(result.error || 'Authentication failed');
                }
                
            } catch (error) {
                errorDiv.textContent = error.message;
                errorDiv.className = 'error';
                errorDiv.style.display = 'block';
                console.error('Authentication failed:', error);
                
                // Reset button
                connectBtn.innerHTML = '🦊 Sign in with Ethereum';
                connectBtn.disabled = false;
            }
        }
        
        // Check if user is already connected
        window.addEventListener('load', async () => {
            if (window.ethereum && window.ethereum.selectedAddress) {
                const connectBtn = document.getElementById('connectBtn');
                connectBtn.innerHTML = '🔗 Already Connected - Click to Sign In';
            }
        });
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
    """Handle SIWE (Sign-In with Ethereum) authentication"""
    try:
        data = request.get_json()
        wallet_address = data.get('wallet_address')
        signature = data.get('signature')
        message = data.get('message')
        nonce = data.get('nonce')
        timestamp = data.get('timestamp')
        
        if not all([wallet_address, signature, message, nonce, timestamp]):
            return jsonify({"success": False, "error": "Missing authentication data"}), 400
        
        # Parse timestamp and check if it's within 5 minutes
        try:
            from datetime import datetime, timezone
            issued_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            time_diff = (now - issued_time).total_seconds()
            
            if abs(time_diff) > 300:  # 5 minutes
                return jsonify({"success": False, "error": "Authentication expired"}), 400
        except Exception:
            return jsonify({"success": False, "error": "Invalid timestamp format"}), 400
        
        # Verify SIWE message format
        if not message.startswith(f"{request.headers.get('Host', 'localhost')} wants you to sign in"):
            return jsonify({"success": False, "error": "Invalid message format"}), 400
        
        if wallet_address.lower() not in message.lower():
            return jsonify({"success": False, "error": "Wallet address mismatch"}), 400
        
        # Verify signature using personal_sign format
        try:
            # Remove 0x prefix from signature if present
            sig = signature[2:] if signature.startswith('0x') else signature
            
            # Verify the signature
            message_hash = hashlib.sha256(message.encode()).hexdigest()
            
            # Use web3 to verify the signature
            from eth_account.messages import encode_defunct
            encoded_message = encode_defunct(text=message)
            recovered_address = nft_auth.w3.eth.account.recover_message(encoded_message, signature=signature)
            
            if recovered_address.lower() != wallet_address.lower():
                return jsonify({"success": False, "error": "Invalid signature"}), 401
                
        except Exception as e:
            print(f"Signature verification failed: {e}")
            return jsonify({"success": False, "error": "Signature verification failed"}), 401
        
        # Check NFT ownership
        if not nft_auth.check_nft_ownership_rpc(wallet_address):
            return jsonify({"success": False, "error": "High Integrity Milady NFT required"}), 403
        
        # Create session token
        session_data = {
            "wallet": wallet_address,
            "authenticated": True,
            "timestamp": time.time(),
            "nonce": nonce,
            "siwe_message": message
        }
        
        token = base64.b64encode(json.dumps(session_data).encode()).decode()
        
        # Set secure cookie
        response = make_response(jsonify({"success": True, "wallet": wallet_address}))
        response.set_cookie('nft_auth_token', token, 
                          max_age=3600,  # 1 hour
                          secure=False,  # Set to True in production with HTTPS
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