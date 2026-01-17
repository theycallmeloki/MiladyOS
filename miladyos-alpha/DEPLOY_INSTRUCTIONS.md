# Deploy MiladyAlpha to Sanko

Since you're using MetaMask with Ledger, here's the simplest way to deploy:

## Option 1: Using Remix (Easiest)

1. Open https://remix.ethereum.org
2. Create a new file called `MiladyAlpha.sol`
3. Copy the contract code from `src/MiladyAlpha.sol`
4. Compile with Solidity 0.8.13+
5. In Deploy tab:
   - Environment: "Injected Provider - MetaMask"
   - Make sure MetaMask is on Sanko network
   - Click "Deploy"
   - Confirm in MetaMask (will prompt Ledger)

## Option 2: Using Foundry with Private Key Export

If you want to use Foundry, you'll need to:
1. Get your Ledger account address from MetaMask
2. Use cast commands with --interactive flag

## Option 3: Deploy via Etherscan/Blockscout

Some explorers allow contract deployment through their UI if verified.

The contract is compiled and ready at:
`/Users/laneone/Documents/MiladyOS/miladyos-alpha/src/MiladyAlpha.sol`