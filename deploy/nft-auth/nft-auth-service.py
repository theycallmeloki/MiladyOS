#!/usr/bin/env python3
"""
NFT Authentication Service for MiladyOS
Standalone service for High Integrity Milady NFT verification
"""

import json
import time
import redis
import base64
from typing import Optional
from web3 import Web3
from eth_account.messages import encode_defunct
from flask import Flask, request, jsonify, redirect, render_template_string, make_response
import os

app = Flask(__name__)

# Configuration
HIGH_INTEGRITY_MILADY_CONTRACT = "0xf01B34d9418874258B35b0507AB53ED971CBB8D3"
ETHEREUM_RPC_URL = os.getenv("ETHEREUM_RPC_URL", "https://ethereum-rpc.publicnode.com")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8080"))

class NFTAuthService:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(ETHEREUM_RPC_URL))
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.contract_address = Web3.to_checksum_address(HIGH_INTEGRITY_MILADY_CONTRACT)
        
    def check_nft_ownership(self, wallet_address: str) -> bool:
        """Check if wallet owns High Integrity Milady NFT"""
        try:
            # Check cached holder list first
            cached_holders = self.redis_client.get("holder_list")
            if cached_holders:
                holder_list = json.loads(cached_holders)
                return wallet_address.lower() in holder_list
            
            # Fallback to real-time blockchain check
            function_signature = "0x70a08231"  # balanceOf(address)
            wallet_padded = wallet_address[2:].zfill(64)
            data = function_signature + wallet_padded
            
            result = self.w3.eth.call({
                "to": self.contract_address,
                "data": data
            })
            
            balance = int(result.hex(), 16)
            return balance > 0
            
        except Exception as e:
            print(f"NFT ownership check failed: {e}")
            return False

    def update_holder_list_async(self):
        """Update holder list if cache is expired (non-blocking)"""
        try:
            # Check if cache exists and is still fresh (within 30 minutes)
            ttl = self.redis_client.ttl("holder_list")
            if ttl > 1800:  # More than 30 minutes left
                return  # Skip update, cache is still fresh
            
            print("Cache expired or missing, triggering holder list update...")
            # Clear expired cache and generate new list
            self.redis_client.delete("holder_list")
            self.generate_holder_list()
        except Exception as e:
            print(f"Async holder list update failed: {e}")

    def generate_holder_list(self) -> list:
        """Generate complete list of current NFT holders"""
        try:
            print("Starting holder list generation...")
            
            # Check if we have a cached holder list
            cached_holders = self.redis_client.get("holder_list")
            if cached_holders:
                print("Returning cached holder list")
                return json.loads(cached_holders)
            
            # Get total supply
            total_supply_signature = "0x18160ddd"  # totalSupply()
            result = self.w3.eth.call({
                "to": self.contract_address,
                "data": total_supply_signature
            })
            total_supply = int(result.hex(), 16)
            print(f"Total supply: {total_supply}")
            
            holders = set()
            
            # For each token ID, get the owner (High Integrity Milady starts from token 1)
            for token_id in range(1, total_supply + 1):
                try:
                    # ownerOf(tokenId) function signature
                    owner_of_signature = "0x6352211e"  # ownerOf(uint256)
                    token_id_padded = hex(token_id)[2:].zfill(64)
                    data = owner_of_signature + token_id_padded
                    
                    result = self.w3.eth.call({
                        "to": self.contract_address,
                        "data": data
                    })
                    
                    # Extract address from result (last 20 bytes)
                    owner_address = "0x" + result.hex()[-40:]
                    holders.add(owner_address.lower())
                    
                    if token_id % 50 == 0:
                        print(f"Processed {token_id}/{total_supply} tokens...")
                        
                except Exception as e:
                    print(f"Error getting owner of token {token_id}: {e}")
                    continue
            
            holder_list = list(holders)
            print(f"Found {len(holder_list)} unique holders")
            
            # Cache for 1 hour
            self.redis_client.setex("holder_list", 3600, json.dumps(holder_list))
            
            return holder_list
            
        except Exception as e:
            print(f"Holder list generation failed: {e}")
            return []

# Initialize service
nft_auth = NFTAuthService()

# Login page template
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>High Integrity Milady Authentication</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✨</text></svg>" />
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
        async function signInWithEthereum() {
            const connectBtn = document.getElementById('connectBtn');
            const statusDiv = document.getElementById('status');
            const errorDiv = document.getElementById('error');
            
            statusDiv.style.display = 'none';
            errorDiv.style.display = 'none';
            
            connectBtn.innerHTML = '<span class="loading"></span> Connecting...';
            connectBtn.disabled = true;
            
            try {
                if (!window.ethereum) {
                    throw new Error("MetaMask not found. Please install MetaMask to continue.");
                }
                
                // Handle multiple wallet extensions
                let ethereum = window.ethereum;
                if (window.ethereum.providers?.length) {
                    ethereum = window.ethereum.providers.find(provider => provider.isMetaMask) || window.ethereum;
                }
                
                // Request account access
                const accounts = await ethereum.request({ method: 'eth_requestAccounts' });
                const walletAddress = accounts[0];
                
                statusDiv.innerHTML = `Connected: <div class="wallet-address">${walletAddress}</div>`;
                statusDiv.className = 'status';
                statusDiv.style.display = 'block';
                
                // Switch to mainnet if needed
                try {
                    const chainId = await ethereum.request({ method: 'eth_chainId' });
                    if (chainId !== '0x1') {
                        await ethereum.request({
                            method: 'wallet_switchEthereumChain',
                            params: [{ chainId: '0x1' }],
                        });
                    }
                } catch (switchError) {
                    console.log('Network switch error:', switchError);
                }
                
                statusDiv.innerHTML = 'Please sign the message in MetaMask...';
                
                // Generate message to sign
                const timestamp = Math.floor(Date.now() / 1000);
                const nonce = Math.random().toString(36).substring(2, 15);
                const message = `Sign in to MiladyOS

Wallet: ${walletAddress}
Time: ${timestamp}
Nonce: ${nonce}`;
                
                // Sign the message
                const signature = await ethereum.request({
                    method: 'personal_sign',
                    params: [message, walletAddress]
                });
                
                statusDiv.innerHTML = 'Verifying NFT ownership...';
                
                // Submit authentication to server
                const authData = {
                    walletAddress: walletAddress,
                    signature: signature,
                    message: message,
                    timestamp: timestamp,
                    nonce: nonce
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
                
                connectBtn.innerHTML = '🦊 Sign in with Ethereum';
                connectBtn.disabled = false;
            }
        }
    </script>
</body>
</html>
"""

@app.route('/login')
def login():
    """Login page with Web3 authentication"""
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/authenticate', methods=['POST'])
def authenticate():
    """Handle wallet signature authentication"""
    try:
        data = request.get_json()
        wallet_address = data.get('walletAddress')
        signature = data.get('signature')
        message = data.get('message')
        nonce = data.get('nonce')
        timestamp = data.get('timestamp')
        
        if not all([wallet_address, signature, message, nonce, timestamp]):
            return jsonify({"success": False, "error": "Missing authentication data"}), 400
        
        # Check timestamp (5 minute window)
        current_time = int(time.time())
        if abs(current_time - timestamp) > 300:
            return jsonify({"success": False, "error": "Authentication expired"}), 400
        
        # Check nonce to prevent replay attacks
        nonce_key = f"nonce:{nonce}:{wallet_address.lower()}"
        if nft_auth.redis_client.exists(nonce_key):
            return jsonify({"success": False, "error": "Nonce already used"}), 400
        
        # Store nonce for 10 minutes to prevent reuse
        nft_auth.redis_client.setex(nonce_key, 600, "used")
        
        # Verify message format
        if wallet_address.lower() not in message.lower():
            return jsonify({"success": False, "error": "Wallet address mismatch"}), 400
        
        # Verify signature
        try:
            encoded_message = encode_defunct(text=message)
            recovered_address = nft_auth.w3.eth.account.recover_message(encoded_message, signature=signature)
            
            if recovered_address.lower() != wallet_address.lower():
                return jsonify({"success": False, "error": "Invalid signature"}), 401
                
        except Exception as e:
            print(f"Signature verification failed: {e}")
            return jsonify({"success": False, "error": "Signature verification failed"}), 401
        
        # Check NFT ownership
        if not nft_auth.check_nft_ownership(wallet_address):
            return jsonify({"success": False, "error": "High Integrity Milady NFT required"}), 403
        
        # Trigger holder list update in background (fire and forget)
        try:
            nft_auth.update_holder_list_async()
        except Exception as e:
            print(f"Background holder list update failed: {e}")
            # Don't fail authentication if background update fails
        
        # Create session token
        session_data = {
            "wallet": wallet_address,
            "authenticated": True,
            "timestamp": time.time(),
            "nonce": nonce
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

@app.route('/admin/generate-holders', methods=['POST'])
def admin_generate_holders():
    """Admin endpoint to trigger holder list generation"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {SECRET_KEY}":
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        holder_list = nft_auth.generate_holder_list()
        return jsonify({
            "status": "Holder list generated",
            "total_holders": len(holder_list),
            "sample_holders": holder_list[:5] if holder_list else []
        })
    except Exception as e:
        print(f"Holder list generation failed: {e}")
        return jsonify({"error": "Holder list generation failed"}), 500

@app.route('/admin/holders')
def admin_view_holders():
    """Admin endpoint to view current holder list and stats"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {SECRET_KEY}":
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        cached_holders = nft_auth.redis_client.get("holder_list")
        if not cached_holders:
            return jsonify({
                "status": "No holder list cached",
                "total_holders": 0,
                "cache_status": "empty"
            })
        
        holder_list = json.loads(cached_holders)
        ttl = nft_auth.redis_client.ttl("holder_list")
        
        return jsonify({
            "status": "Holder list available",
            "total_holders": len(holder_list),
            "cache_ttl_seconds": ttl,
            "sample_holders": holder_list[:10] if holder_list else [],
            "cache_status": "active"
        })
        
    except Exception as e:
        print(f"Error retrieving holder list: {e}")
        return jsonify({"error": "Failed to retrieve holder list"}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=SERVICE_PORT, debug=False)