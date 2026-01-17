// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import {Script, console} from "forge-std/Script.sol";
import {MiladyAlpha} from "../src/MiladyAlpha.sol";

contract InteractScript is Script {
    MiladyAlpha miladyAlpha = MiladyAlpha(0xdFBD17d4d20fBF1bD8DC8E73E14d124a005BF3a6);
    
    function run() public view {
        // Read current greeting
        string memory greeting = miladyAlpha.greeting();
        console.log("Current greeting:", greeting);
        
        // Get contract info
        (
            string memory _greeting,
            uint256 _deploymentTime,
            address _deployer,
            uint256 _currentTime
        ) = miladyAlpha.getContractInfo();
        
        console.log("Deployment time:", _deploymentTime);
        console.log("Deployer:", _deployer);
        console.log("Current time:", _currentTime);
    }
    
    function setNewGreeting(string memory newGreeting) public {
        vm.startBroadcast();
        miladyAlpha.setGreeting(newGreeting);
        vm.stopBroadcast();
        console.log("Greeting updated to:", newGreeting);
    }
    
    function storeMessage(string memory message) public {
        vm.startBroadcast();
        miladyAlpha.storeMessage(message);
        vm.stopBroadcast();
        console.log("Message stored:", message);
    }
}