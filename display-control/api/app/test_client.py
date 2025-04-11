#!/usr/bin/env python3
import asyncio
import json
import logging
import sys
import websockets
import argparse
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("test-client")

class DisplayControlClient:
    def __init__(self, api_base="http://localhost:8000"):
        self.api_base = api_base
        # Ensure proper WebSocket URL format
        ws_base = api_base.replace("http://", "ws://").replace("https://", "wss://")
        if not (ws_base.startswith("ws://") or ws_base.startswith("wss://")):
            ws_base = f"ws://{ws_base}"
        self.agent_url = f"{ws_base}/ws/agent"
    
    async def agent_session(self):
        """Connect as an agent to control displays"""
        logger.info(f"Connecting to {self.agent_url}")
        
        async with websockets.connect(self.agent_url) as websocket:
            # Handle the initial message
            init_msg = await websocket.recv()
            init_data = json.loads(init_msg)
            
            logger.info(f"Connected successfully. Available displays:")
            for name, info in init_data.get("displays", {}).items():
                status = "ONLINE" if info.get("online") else "OFFLINE"
                url = info.get("current_url") or "N/A"
                logger.info(f"  - {name}: {status}, URL: {url}")
            
            # Command loop
            print("\nType commands in the format: ACTION DISPLAY URL")
            print("Examples:")
            print("  navigate display-1 https://example.com")
            print("  navigate all https://example.org")
            print("  refresh display-2")
            print("  status")
            print("  exit")
            
            while True:
                try:
                    command = input("\n> ").strip()
                    
                    if command.lower() == "exit":
                        print("Exiting...")
                        break
                        
                    if command.lower() == "status":
                        # Get current status through REST API
                        try:
                            response = requests.get(f"{self.api_base}/displays")
                            displays = response.json()
                            print("\nDisplay Status:")
                            for name, info in displays.items():
                                status = "ONLINE" if info.get("online") else "OFFLINE"
                                url = info.get("current_url") or "N/A"
                                print(f"  - {name}: {status}, URL: {url}")
                        except Exception as e:
                            logger.error(f"Error getting status: {e}")
                        continue
                    
                    parts = command.split()
                    if len(parts) < 2:
                        print("Invalid command format. Use: ACTION DISPLAY [URL]")
                        continue
                    
                    action = parts[0].lower()
                    display = parts[1]
                    
                    if action == "navigate" and len(parts) < 3:
                        print("Navigate command requires a URL")
                        continue
                    
                    # Build command JSON
                    cmd = {"action": action, "display": display}
                    
                    if action == "navigate":
                        cmd["url"] = " ".join(parts[2:])
                    
                    # Send command
                    logger.info(f"Sending command: {cmd}")
                    await websocket.send(json.dumps(cmd))
                    
                    # Get response (may need to wait for multiple messages)
                    command_processed = False
                    while not command_processed:
                        response = await websocket.recv()
                        result = json.loads(response)
                        
                        # Add debug logging for the response
                        logger.info(f"Server response: {result}")
                        
                        # Check if this is a direct response to our command or an event
                        if "event" in result:
                            # This is an event notification, wait for the next message
                            logger.info(f"Received event notification: {result['event']}")
                            continue
                        
                        # This is the command response
                        command_processed = True
                    
                    if result.get("status") == "success":
                        print(f"Command executed successfully")
                        if "results" in result:
                            for d, r in result["results"].items():
                                print(f"  - {d}: {r}")
                    else:
                        error_msg = result.get('error')
                        if error_msg:
                            print(f"Error: {error_msg}")
                        else:
                            print(f"Command processed but status is '{result.get('status')}'")
                except Exception as e:
                    logger.error(f"Error processing command: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Test client for Display Control API")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()
    
    client = DisplayControlClient(api_base=args.api)
    await client.agent_session()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)