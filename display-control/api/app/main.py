import logging
import time
import asyncio
import base64
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("control-api")

# FastAPI app
app = FastAPI(
    title="Display Control API",
    description="API for controlling multiple displays",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class NavigateRequest(BaseModel):
    url: str = Field(..., description="URL to navigate to")

class ExecuteJSRequest(BaseModel):
    script: str = Field(..., description="JavaScript code to execute")

# In-memory store for display connections
class DisplayManager:
    def __init__(self):
        # Dynamic registry of displays that will be populated as devices connect
        self.displays: Dict[str, Dict] = {}
        # WebSocket connections
        self.ws_clients: Dict[str, WebSocket] = {}
        # LLM agents connected
        self.agent_clients: List[WebSocket] = []

    def _create_display_entry(self, display_name: str, online: bool = False):
        """Helper method to create a display entry with standard fields"""
        if display_name not in self.displays:
            self.displays[display_name] = {
                "online": online,
                "current_url": None,
                "last_contact": time.time(),
                "display_id": None
            }
        return self.displays[display_name]

    def display_connected(self, display_name: str, websocket: WebSocket, display_info: Dict = None):
        """Register a display connection"""
        display = self._create_display_entry(display_name, online=True)
        
        # Update with provided info
        if display_info:
            if "display_id" in display_info:
                display["display_id"] = display_info["display_id"]
            if "url" in display_info:
                display["current_url"] = display_info["url"]
        
        self.ws_clients[display_name] = websocket
        return display

    def display_disconnected(self, display_name: str):
        """Mark a display as disconnected"""
        if display_name in self.displays:
            self.displays[display_name]["online"] = False
            self.displays[display_name]["last_contact"] = time.time()
        if display_name in self.ws_clients:
            del self.ws_clients[display_name]

    def agent_connected(self, websocket: WebSocket):
        """Register an agent connection"""
        self.agent_clients.append(websocket)
        return len(self.agent_clients)

    def agent_disconnected(self, websocket: WebSocket):
        """Remove an agent connection"""
        if websocket in self.agent_clients:
            self.agent_clients.remove(websocket)
        return len(self.agent_clients)

    def update_display_status(self, display_name: str, url: Optional[str] = None):
        """Update a display's status and URL"""
        if display_name not in self.displays:
            self._create_display_entry(display_name, online=True)
            
        self.displays[display_name]["last_contact"] = time.time()
        if url:
            self.displays[display_name]["current_url"] = url

    def get_display_info(self, display_name: str) -> Optional[Dict]:
        """Get information about a specific display"""
        return self.displays.get(display_name)

    def get_all_displays(self) -> Dict[str, Dict]:
        """Get information about all displays"""
        return self.displays

    async def send_to_display(self, display_name: str, message: Dict) -> bool:
        """Send a message to a specific display"""
        if display_name in self.ws_clients and self.displays[display_name]["online"]:
            try:
                await self.ws_clients[display_name].send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error sending to {display_name}: {e}")
                self.display_disconnected(display_name)
                return False
        return False

    async def broadcast_to_agents(self, message: Dict):
        """Send a message to all connected agents"""
        for agent in self.agent_clients[:]:  # Create a copy to avoid modification during iteration
            try:
                await agent.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to agent: {e}")
                self.agent_disconnected(agent)
                
    async def send_navigate_command(self, display_name: str, url: str) -> bool:
        """Send a navigation command to a display"""
        success = await self.send_to_display(display_name, {
            "action": "navigate",
            "url": url
        })
        
        if success:
            self.update_display_status(display_name, url)
        
        return success
    
    async def send_refresh_command(self, display_name: str) -> bool:
        """Send a refresh command to a display"""
        return await self.send_to_display(display_name, {
            "action": "refresh"
        })

# Create display manager
display_manager = DisplayManager()

# API Routes
@app.get("/")
async def root():
    """Root endpoint for API health check"""
    return {
        "status": "online",
        "service": "Display Control API",
        "version": "1.0.0"
    }

@app.get("/displays")
async def get_displays():
    """Get status of all displays"""
    return display_manager.get_all_displays()

@app.get("/displays/{display_name}")
async def get_display(display_name: str):
    """Get status of a specific display"""
    display = display_manager.get_display_info(display_name)
    if not display:
        raise HTTPException(status_code=404, detail=f"Display {display_name} not found")
    return display

@app.post("/displays/{display_name}/navigate")
async def navigate_display(display_name: str, request: NavigateRequest):
    """Navigate a display to a URL"""
    display = display_manager.get_display_info(display_name)
    if not display:
        raise HTTPException(status_code=404, detail=f"Display {display_name} not found")

    success = await display_manager.send_navigate_command(display_name, request.url)

    if success:
        return {"status": "success", "display": display_name, "url": request.url}
    else:
        raise HTTPException(status_code=503, detail=f"Display {display_name} is not connected")

@app.post("/displays/{display_name}/execute_js")
async def execute_js(display_name: str, request: ExecuteJSRequest):
    """Execute JavaScript on a display"""
    display = display_manager.get_display_info(display_name)
    if not display:
        raise HTTPException(status_code=404, detail=f"Display {display_name} not found")

    success = await display_manager.send_to_display(display_name, {
        "action": "execute_js",
        "script": request.script
    })

    if success:
        return {"status": "success", "display": display_name}
    else:
        raise HTTPException(status_code=503, detail=f"Display {display_name} is not connected")

@app.post("/displays/{display_name}/refresh")
async def refresh_display(display_name: str):
    """Refresh a display"""
    display = display_manager.get_display_info(display_name)
    if not display:
        raise HTTPException(status_code=404, detail=f"Display {display_name} not found")

    success = await display_manager.send_refresh_command(display_name)

    if success:
        return {"status": "success", "display": display_name}
    else:
        raise HTTPException(status_code=503, detail=f"Display {display_name} is not connected")

@app.post("/displays/all/navigate")
async def navigate_all_displays(request: NavigateRequest):
    """Navigate all displays to the same URL"""
    results = {}
    for display_name in display_manager.displays:
        success = await display_manager.send_navigate_command(display_name, request.url)
        results[display_name] = "success" if success else "failed"

    return {
        "status": "success",
        "results": results,
        "url": request.url
    }

# WebSocket routes
@app.websocket("/ws/displays/{display_name}")
async def websocket_display(websocket: WebSocket, display_name: str):
    """WebSocket endpoint for displays to connect to"""
    await websocket.accept()
    logger.info(f"Display {display_name} connected via WebSocket")
    
    try:
        # Wait for the initial status message
        initial_msg = await websocket.receive_json()
        logger.info(f"Initial status from {display_name}: {initial_msg}")
        
        display_info = display_manager.display_connected(
            display_name, 
            websocket, 
            {
                "display_id": initial_msg.get("display_id"),
                "url": initial_msg.get("url")
            }
        )

        # Notify agents of display connection
        await display_manager.broadcast_to_agents({
            "event": "display_connected",
            "display": display_name,
            "info": display_info
        })
        
        # Send acknowledgement
        await websocket.send_json({"status": "connected"})
        
        # Process messages
        while True:
            data = await websocket.receive_json()
            logger.info(f"Received from {display_name}: {data}")
            
            # Initialize screenshots storage if needed
            if not hasattr(display_manager, 'last_screenshots'):
                display_manager.last_screenshots = {}
                
            # Handle screenshot responses
            if data.get("status") == "screenshot_taken" and "image" in data:
                # Store the screenshot data for the REST API
                display_manager.last_screenshots[display_name] = data["image"]
                logger.info(f"Received screenshot from {display_name}, size: {len(data['image']) // 1024}KB")
                
            # Update display status based on message
            if "status" in data:
                if data["status"] == "navigated" and "url" in data:
                    display_manager.update_display_status(display_name, data["url"])
                    
                # Forward status to agents
                await display_manager.broadcast_to_agents({
                    "event": "display_update",
                    "display": display_name,
                    "data": data
                })
                
                # Send acknowledgement
                await websocket.send_json({"status": "ack"})
    except WebSocketDisconnect:
        logger.info(f"Display {display_name} disconnected")
    except Exception as e:
        logger.error(f"Error in WebSocket connection for {display_name}: {e}")
    finally:
        display_manager.display_disconnected(display_name)
        # Notify agents of display disconnection
        await display_manager.broadcast_to_agents({
            "event": "display_disconnected",
            "display": display_name
        })

# HTTP endpoint for screenshots with binary response
@app.get("/displays/{display_name}/screenshot")
async def get_screenshot(display_name: str, quality: int = 80, full_page: bool = False):
    """Get a screenshot of a display as a JPEG image"""
    display = display_manager.get_display_info(display_name)
    if not display:
        raise HTTPException(status_code=404, detail=f"Display {display_name} not found")
    
    # Initialize screenshot storage if needed
    if not hasattr(display_manager, 'last_screenshots'):
        display_manager.last_screenshots = {}
    
    # Clear any existing screenshot
    if display_name in display_manager.last_screenshots:
        del display_manager.last_screenshots[display_name]
    
    # Request the screenshot
    success = await display_manager.send_to_display(display_name, {
        "action": "screenshot",
        "quality": quality,
        "full_page": full_page
    })
    
    if not success:
        raise HTTPException(status_code=503, detail=f"Display {display_name} is not connected")
    
    # Wait for the response from the display
    # This is a bit of a hack, but we need to handle the async nature of the WebSocket
    max_retries = 10
    for _ in range(max_retries):
        # Check if screenshot has been received
        if display_name in display_manager.last_screenshots:
            # Screenshot received!
            screenshot_data = base64.b64decode(display_manager.last_screenshots[display_name])
            return Response(content=screenshot_data, media_type="image/jpeg")
        
        # Wait a bit and check again
        await asyncio.sleep(0.2)
    
    # If we get here, we didn't get a screenshot in time
    raise HTTPException(status_code=504, detail="Timed out waiting for screenshot")

# Command handlers for agent websocket
async def handle_navigate(websocket: WebSocket, data: Dict):
    """Handle navigation commands from agents"""
    display_name = data.get("display")
    url = data.get("url")
    
    if display_name == "all":
        # Navigate all displays
        results = {}
        for d_name in display_manager.displays:
            success = await display_manager.send_navigate_command(d_name, url)
            results[d_name] = "success" if success else "failed"
        
        await websocket.send_json({
            "status": "success",
            "action": "navigate_all",
            "results": results,
            "error": None  # Explicitly set error to None for success case
        })
    elif display_name in display_manager.displays:
        # Navigate specific display
        success = await display_manager.send_navigate_command(display_name, url)
        
        await websocket.send_json({
            "status": "success" if success else "error",
            "action": "navigate",
            "display": display_name,
            "error": None if success else "Display not connected"
        })
    else:
        await websocket.send_json({
            "status": "error",
            "error": f"Invalid display: {display_name}"
        })

async def handle_refresh(websocket: WebSocket, data: Dict):
    """Handle refresh commands from agents"""
    display_name = data.get("display")
    
    if display_name == "all":
        # Refresh all displays
        results = {}
        for d_name in display_manager.displays:
            success = await display_manager.send_refresh_command(d_name)
            results[d_name] = "success" if success else "failed"
        
        await websocket.send_json({
            "status": "success",
            "action": "refresh_all",
            "results": results,
            "error": None  # Explicitly set error to None
        })
    elif display_name in display_manager.displays:
        # Refresh specific display
        success = await display_manager.send_refresh_command(display_name)
        
        await websocket.send_json({
            "status": "success" if success else "error",
            "action": "refresh",
            "display": display_name,
            "error": None if success else "Display not connected"
        })
    else:
        await websocket.send_json({
            "status": "error",
            "error": f"Invalid display: {display_name}"
        })

async def handle_execute_js(websocket: WebSocket, data: Dict):
    """Handle JavaScript execution commands from agents"""
    display_name = data.get("display")
    script = data.get("script")
    
    if display_name in display_manager.displays:
        # Execute JS on specific display
        success = await display_manager.send_to_display(display_name, {
            "action": "execute_js",
            "script": script
        })
        
        await websocket.send_json({
            "status": "success" if success else "error",
            "action": "execute_js",
            "display": display_name,
            "error": None if success else "Display not connected"
        })
    else:
        await websocket.send_json({
            "status": "error",
            "error": f"Invalid display: {display_name}"
        })

async def handle_screenshot(websocket: WebSocket, data: Dict):
    """Handle screenshot commands from agents"""
    display_name = data.get("display")
    quality = data.get("quality", 80)
    full_page = data.get("full_page", False)
    
    if display_name in display_manager.displays:
        # Request screenshot from display
        success = await display_manager.send_to_display(display_name, {
            "action": "screenshot",
            "quality": quality,
            "full_page": full_page
        })
        
        # Need to wait for the screenshot to be processed
        await asyncio.sleep(0.5)
        
        # Check if we have a screenshot
        if hasattr(display_manager, 'last_screenshots') and display_name in display_manager.last_screenshots:
            # Return the base64 encoded image to the agent
            # Note: This could be large, so in production you might want to
            # add compression or downsampling for WebSocket transfers
            await websocket.send_json({
                "status": "success",
                "action": "screenshot",
                "display": display_name,
                "image": display_manager.last_screenshots[display_name],
                "format": "jpeg",
                "error": None
            })
        else:
            await websocket.send_json({
                "status": "error",
                "action": "screenshot",
                "display": display_name,
                "error": "Failed to get screenshot"
            })
    else:
        await websocket.send_json({
            "status": "error",
            "error": f"Invalid display: {display_name}"
        })

# Command handler mapping
COMMAND_HANDLERS = {
    "navigate": handle_navigate,
    "refresh": handle_refresh,
    "execute_js": handle_execute_js,
    "screenshot": handle_screenshot
}

@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    """WebSocket endpoint for LLM agents to connect to"""
    await websocket.accept()
    agent_count = display_manager.agent_connected(websocket)
    logger.info(f"Agent connected. Total agents: {agent_count}")
    
    try:
        # Send current display status
        await websocket.send_json({
            "event": "init",
            "displays": display_manager.get_all_displays()
        })
        
        # Process agent commands
        while True:
            data = await websocket.receive_json()
            logger.info(f"Received from agent: {data}")
            
            if "action" in data:
                action = data["action"]
                
                if action in COMMAND_HANDLERS and "display" in data:
                    # Call the appropriate handler based on action
                    await COMMAND_HANDLERS[action](websocket, data)
                else:
                    await websocket.send_json({
                        "status": "error",
                        "error": f"Invalid action: {action} or missing display parameter"
                    })
    except WebSocketDisconnect:
        logger.info("Agent disconnected")
    except Exception as e:
        logger.error(f"Error in agent WebSocket: {e}")
    finally:
        display_manager.agent_disconnected(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)