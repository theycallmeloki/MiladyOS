import logging
import os
import asyncio
import sys
import json
import time
from typing import Dict

import websockets
from playwright.async_api import async_playwright

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("display")

# Configuration from environment variables
DISPLAY_ID = os.environ.get("DISPLAY_ID", ":0")
DEFAULT_URL = os.environ.get("DEFAULT_URL", "https://grafana.miladyos.net")
CONTROL_API = os.environ.get("CONTROL_API", "http://control-api:8000")

# Get device identity from balena environment variables
DEVICE_UUID = os.environ.get("BALENA_DEVICE_UUID", "unknown")
DEVICE_NAME = os.environ.get("BALENA_DEVICE_NAME", f"device-{DISPLAY_ID.replace(':', '')}")
CONTAINER_NAME = f"{DEVICE_NAME}-display"

# Extract websocket URL from control API
ws_base = CONTROL_API.replace("http://", "ws://").replace("https://", "wss://")
if not (ws_base.startswith("ws://") or ws_base.startswith("wss://")):
    ws_base = f"ws://{ws_base}"
WEBSOCKET_URL = f"{ws_base}/ws/displays/{CONTAINER_NAME}"

# Get detected resolution if available
DETECTED_RESOLUTION = os.environ.get("DETECTED_RESOLUTION", "")
if DETECTED_RESOLUTION:
    try:
        width, height = map(int, DETECTED_RESOLUTION.split("x"))
        logger.info(f"Using detected resolution: {width}x{height}")
    except Exception as e:
        logger.error(f"Error parsing resolution '{DETECTED_RESOLUTION}': {e}")
        width, height = None, None
else:
    width, height = None, None
    logger.info("No specific resolution detected, using default")

# Global variables
page = None
browser = None

async def process_command(command: Dict):
    """Process a command from the control API"""
    global page
    
    if not page:
        logger.error("Browser not initialized, cannot process command")
        return {"status": "error", "error": "Browser not initialized"}
    
    try:
        action = command.get("action")
        
        if action == "navigate" and "url" in command:
            url = command["url"]
            logger.info(f"Navigating to {url}")
            await page.goto(url)
            return {"status": "navigated", "url": page.url}
            
        elif action == "refresh":
            logger.info("Refreshing page")
            await page.reload()
            return {"status": "refreshed", "url": page.url}
            
        elif action == "execute_js" and "script" in command:
            script = command["script"]
            logger.info(f"Executing script: {script[:50]}...")
            result = await page.evaluate(script)
            return {"status": "script_executed", "result": str(result)}
            
        elif action == "screenshot":
            logger.info("Taking screenshot")
            # Capture screenshot as binary data
            quality = command.get("quality", 80)  # Default JPEG quality
            screenshot_bytes = await page.screenshot(
                type="jpeg", 
                quality=quality,
                full_page=command.get("full_page", False)
            )
            # Convert to base64 for JSON transport
            import base64
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            return {
                "status": "screenshot_taken", 
                "format": "jpeg",
                "quality": quality,
                "image": screenshot_b64,
                "url": page.url
            }
            
        else:
            logger.warning(f"Unknown command: {command}")
            return {"status": "error", "error": f"Unknown command: {action}"}
    except Exception as e:
        logger.error(f"Error processing command: {e}")
        return {"status": "error", "error": str(e)}

async def connect_websocket():
    """Connect to control API via WebSocket"""
    global page
    
    logger.info(f"Connecting to control API at {WEBSOCKET_URL}")
    retry_delay = 5
    
    while True:
        try:
            async with websockets.connect(WEBSOCKET_URL) as ws:
                logger.info("Connected to control API")
                
                # Send initial status
                initial_status = {
                    "status": "connected",
                    "url": page.url if page else None,
                    "display_id": DISPLAY_ID
                }
                
                await ws.send(json.dumps(initial_status))
                
                # Process commands
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    logger.info(f"Received message: {data}")
                    
                    # Process the command
                    result = await process_command(data)
                    await ws.send(json.dumps(result))
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            logger.info(f"Retrying in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)

async def run_browser():
    """Run the browser and navigate to the default URL"""
    global page, browser
    
    logger.info(f"Starting browser on display {DISPLAY_ID}")
    logger.info(f"Will navigate to {DEFAULT_URL}")
    
    try:
        # Start the browser
        playwright = await async_playwright().start()
        
        # Build browser arguments
        browser_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--kiosk",
            "--disable-gpu",
            f"--display={DISPLAY_ID}",
        ]
        
        # Add window size if resolution was detected
        if width and height:
            browser_args.append(f"--window-size={width},{height}")
            logger.info(f"Setting window size to {width}x{height}")
        
        browser = await playwright.chromium.launch(
            headless=False,
            args=browser_args
        )
        
        # Create a context and page with detected viewport if available
        context_opts = {
            "ignore_https_errors": True
        }
        
        if width and height:
            context_opts["viewport"] = {"width": width, "height": height}
        else:
            context_opts["viewport"] = None  # Auto-detect viewport
            
        context = await browser.new_context(**context_opts)
        page = await context.new_page()
        
        # Navigate to the URL
        logger.info(f"Navigating to {DEFAULT_URL}")
        await page.goto(DEFAULT_URL)
        
        logger.info("Browser started successfully")
        
        # Start websocket connection in the background
        asyncio.create_task(connect_websocket())
        
        # Keep the main task running
        while True:
            await asyncio.sleep(60)
            if page:
                logger.info(f"Still running, current URL: {page.url}")
            else:
                logger.warning("Page object not available")
    except Exception as e:
        logger.error(f"Error running browser: {e}")
        return False

async def main():
    """Main entry point"""
    await run_browser()

if __name__ == "__main__":
    asyncio.run(main())