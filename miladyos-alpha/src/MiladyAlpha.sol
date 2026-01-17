// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

contract MiladyAlpha {
    string public greeting = "Hello from MiladyOS Alpha on Sanko!";
    uint256 public deploymentTime;
    address public deployer;
    
    mapping(address => string) public userMessages;
    
    event MessageStored(address indexed user, string message);
    event GreetingChanged(string newGreeting);
    
    constructor() {
        deploymentTime = block.timestamp;
        deployer = msg.sender;
    }
    
    function setGreeting(string memory _greeting) public {
        greeting = _greeting;
        emit GreetingChanged(_greeting);
    }
    
    function storeMessage(string memory _message) public {
        userMessages[msg.sender] = _message;
        emit MessageStored(msg.sender, _message);
    }
    
    function getContractInfo() public view returns (
        string memory _greeting,
        uint256 _deploymentTime,
        address _deployer,
        uint256 _currentTime
    ) {
        return (greeting, deploymentTime, deployer, block.timestamp);
    }
}