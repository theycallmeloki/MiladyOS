/**
 * NFT Web3 Authentication Client
 * Simple High Integrity Milady NFT authentication for MiladyOS
 */

class NFTAuth {
    constructor() {
        this.contractAddress = "0xf01B34d9418874258B35b0507AB53ED971CBB8D3";
        this.chainId = 1; // Ethereum mainnet
        this.provider = null;
        this.signer = null;
        this.walletAddress = null;
    }

    /**
     * Connect to MetaMask wallet
     */
    async connectWallet() {
        if (!window.ethereum) {
            throw new Error("MetaMask not found. Please install MetaMask to continue.");
        }

        try {
            // Request account access
            await window.ethereum.request({ method: 'eth_requestAccounts' });
            
            this.provider = new ethers.providers.Web3Provider(window.ethereum);
            this.signer = this.provider.getSigner();
            this.walletAddress = await this.signer.getAddress();

            // Check if on correct network
            const network = await this.provider.getNetwork();
            if (network.chainId !== this.chainId) {
                await this.switchToEthereum();
            }

            return this.walletAddress;
        } catch (error) {
            console.error("Failed to connect wallet:", error);
            throw error;
        }
    }

    /**
     * Switch to Ethereum mainnet
     */
    async switchToEthereum() {
        try {
            await window.ethereum.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: '0x1' }], // Ethereum mainnet
            });
        } catch (error) {
            console.error("Failed to switch network:", error);
            throw error;
        }
    }

    /**
     * Check High Integrity Milady NFT ownership
     */
    async checkNFTOwnership(walletAddress = this.walletAddress) {
        if (!walletAddress) {
            throw new Error("No wallet address provided");
        }

        try {
            // ERC-721 contract ABI for balanceOf
            const abi = ["function balanceOf(address owner) view returns (uint256)"];
            const contract = new ethers.Contract(this.contractAddress, abi, this.provider);
            
            const balance = await contract.balanceOf(walletAddress);
            return balance.gt(0);
        } catch (error) {
            console.error("Failed to check NFT ownership:", error);
            throw error;
        }
    }

    /**
     * Generate authentication signature
     */
    async generateAuthSignature() {
        if (!this.signer || !this.walletAddress) {
            throw new Error("Wallet not connected");
        }

        const timestamp = Math.floor(Date.now() / 1000);
        const nonce = ethers.utils.id(`${this.walletAddress}${timestamp}`).substring(0, 18);
        
        const message = `MiladyOS Access Request\nWallet: ${this.walletAddress}\nTimestamp: ${timestamp}\nNonce: ${nonce}`;
        
        try {
            const signature = await this.signer.signMessage(message);
            
            return {
                wallet_address: this.walletAddress,
                signature: signature,
                timestamp: timestamp,
                nonce: nonce
            };
        } catch (error) {
            console.error("Failed to sign message:", error);
            throw error;
        }
    }

    /**
     * Complete authentication flow
     */
    async authenticate() {
        try {
            // Step 1: Connect wallet
            const walletAddress = await this.connectWallet();
            console.log("Connected wallet:", walletAddress);

            // Step 2: Check NFT ownership
            const ownsNFT = await this.checkNFTOwnership();
            if (!ownsNFT) {
                throw new Error("High Integrity Milady NFT required for access");
            }
            console.log("NFT ownership verified");

            // Step 3: Generate signature
            const authData = await this.generateAuthSignature();
            console.log("Authentication signature generated");

            return {
                success: true,
                walletAddress: walletAddress,
                authToken: btoa(JSON.stringify(authData)) // Base64 encode for Bearer token
            };

        } catch (error) {
            console.error("Authentication failed:", error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    /**
     * Create authenticated HTTP client
     */
    createAuthenticatedClient(authToken) {
        return {
            async get(url, options = {}) {
                return fetch(url, {
                    ...options,
                    headers: {
                        'Authorization': `Bearer ${authToken}`,
                        'Content-Type': 'application/json',
                        ...options.headers
                    }
                });
            },

            async post(url, data, options = {}) {
                return fetch(url, {
                    method: 'POST',
                    ...options,
                    headers: {
                        'Authorization': `Bearer ${authToken}`,
                        'Content-Type': 'application/json',
                        ...options.headers
                    },
                    body: JSON.stringify(data)
                });
            }
        };
    }
}

// Usage example
const nftAuth = new NFTAuth();

// Authentication flow
document.getElementById('connect-wallet')?.addEventListener('click', async () => {
    const result = await nftAuth.authenticate();
    
    if (result.success) {
        document.getElementById('auth-status').textContent = `Authenticated: ${result.walletAddress}`;
        
        // Store auth token for API calls
        localStorage.setItem('miladyos_auth_token', result.authToken);
        
        // Create authenticated client
        const client = nftAuth.createAuthenticatedClient(result.authToken);
        
        // Example API call to MCP server
        const response = await client.get('/mcp/status');
        console.log('MCP Status:', await response.json());
        
    } else {
        document.getElementById('auth-status').textContent = `Error: ${result.error}`;
    }
});

// Auto-authenticate if token exists
window.addEventListener('load', async () => {
    const savedToken = localStorage.getItem('miladyos_auth_token');
    if (savedToken) {
        try {
            // Verify token is still valid by making a test request
            const client = nftAuth.createAuthenticatedClient(savedToken);
            const response = await client.get('/mcp/health');
            
            if (response.ok) {
                document.getElementById('auth-status').textContent = 'Previously authenticated';
            } else {
                localStorage.removeItem('miladyos_auth_token');
            }
        } catch (error) {
            localStorage.removeItem('miladyos_auth_token');
        }
    }
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = NFTAuth;
}