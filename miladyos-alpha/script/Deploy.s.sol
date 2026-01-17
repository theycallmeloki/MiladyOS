// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import {Script, console} from "forge-std/Script.sol";
import {MiladyAlpha} from "../src/MiladyAlpha.sol";

contract DeployScript is Script {
    function setUp() public {}

    function run() public {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        
        vm.startBroadcast(deployerPrivateKey);
        
        MiladyAlpha miladyAlpha = new MiladyAlpha();
        
        console.log("MiladyAlpha deployed to:", address(miladyAlpha));
        
        vm.stopBroadcast();
    }
}