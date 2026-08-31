import json
import logging
import os
import time
import asyncio
from typing import Any, Dict, List, Optional
import textwrap
import uuid
import click
import anyio
from miladyos_metadata import REDIS_AVAILABLE
from pathlib import Path

def get_redis_config():
    """
    Get Redis configuration based on environment variables.
    Centralizes Redis configuration to avoid duplication.
    """
    if not REDIS_AVAILABLE:
        raise ImportError("Redis package is required for MiladyOS. Please install with 'pip install redis'")
        
    # In Kubernetes, use service names for discovery
    if os.getenv("KUBERNETES_MODE", "false").lower() == "true":
        redis_host = os.getenv("REDIS_HOST", "redka")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        logger.info(f"Running in Kubernetes mode, using Redis at {redis_host}:{redis_port}")
    else:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    return redis_host, redis_port

def create_error_response(error_message, tool=None, status="error", additional_info=None):
    """
    Create a standardized error response dictionary.
    
    Args:
        error_message: The main error message
        tool: Optional tool name that triggered the error
        status: Error status code (default: "error")
        additional_info: Optional dictionary with additional error details
    
    Returns:
        Dictionary with standardized error format
    """
    response = {
        "success": False,
        "error": error_message,
        "status": status
    }
    
    if tool:
        response["tool"] = tool
    
    if additional_info and isinstance(additional_info, dict):
        response.update(additional_info)
        
    return response

def create_success_response(message=None, data=None, status="success", additional_info=None):
    """
    Create a standardized success response dictionary.
    
    Args:
        message: Optional success message
        data: Optional data to include in the response
        status: Success status code (default: "success")
        additional_info: Optional dictionary with additional information
    
    Returns:
        Dictionary with standardized success format
    """
    response = {
        "success": True,
        "status": status
    }
    
    if message:
        response["message"] = message
        
    if data:
        if isinstance(data, dict):
            response.update(data)
        else:
            response["data"] = data
    
    if additional_info and isinstance(additional_info, dict):
        response.update(additional_info)
        
    return response

import jenkins
import colorlog
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from xml.sax.saxutils import escape
logger = colorlog.getLogger("miladyos-mcp-tools")
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(levelname)s%(reset)s: %(message)s"
))
logger.handlers = []
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ===== Configuration =====
class Config:
    """MiladyOS configuration settings."""

    # Default supported tools
    DEFAULT_TOOLS = [
        "hello_world",
        "create_jenkins_job",
        "execute_command",
        "evolve_template",
        "evolution_status",
        "list_evolution_goals",
        "list_evolved_templates",
        "get_divine_rng",
        "get_milady_time",
    ]

    # Jenkins credentials - loaded from environment with sensible defaults
    JENKINS_USER = os.getenv("JENKINS_ADMIN_ID", "milady")
    JENKINS_PASSWORD = os.getenv("JENKINS_ADMIN_PASSWORD", "milady")
    
    # Jenkins server configurations
    JENKINS_SERVERS = {
        "default": {
            "url": os.getenv("JENKINS_URL", "http://localhost:8080")
        }
    }

    # SQLite database path

    # Templates and metadata directories
    TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")

    @classmethod
    def get_jenkins_servers(cls):
        """Return Jenkins server configurations."""
        return cls.JENKINS_SERVERS


# ===== Custom Exceptions =====
class JenkinsApiError(Exception):
    """Raised when there's an error with the Jenkins API."""
    pass

class JenkinsUtils:
    """Utility functions for interacting with Jenkins."""
    
    @staticmethod
    def connect_to_jenkins(server_name, username=None, password=None):
        """
        Connect to Jenkins server and return server instance.
        """
        try:
            jenkins_dict = Config.get_jenkins_servers()
            
            if server_name not in jenkins_dict:
                raise ValueError(f"Unknown Jenkins server: {server_name}")
                
            server_url = jenkins_dict[server_name]["url"]
            
            # Always use default credentials if none provided
            if username is None:
                username = Config.JENKINS_USER
            if password is None:
                password = Config.JENKINS_PASSWORD
            
            server = jenkins.Jenkins(
                server_url,
                username=username,
                password=password,
            )
            
            try:
                # Test connection
                server.get_whoami()
                logger.info(f"Successfully connected to Jenkins server: {server_name} ({server_url})")
                return server
            except Exception:
                # Add retry with delay if first attempt fails
                logger.info(f"Retrying connection to {server_name} after 2 second delay...")
                time.sleep(2)
                server = jenkins.Jenkins(
                    server_url,
                    username=username,
                    password=password,
                )
                server.get_whoami()
                logger.info(f"Retry connection successful for {server_name}")
                return server
        except ImportError:
            raise JenkinsApiError("Jenkins module not installed. Please install python-jenkins package.")
        except Exception as e:
            logger.error(f"Error connecting to Jenkins server {server_name}: {e}")
            raise JenkinsApiError(f"Failed to connect to Jenkins server: {str(e)}")
    
    @staticmethod
    def get_jenkinsfile_content(template_name, with_line_numbers=False):
        """
        Read and return Jenkinsfile content for a template.
        
        Args:
            template_name: Name of the template to read
            with_line_numbers: If True, returns a dict with 'content' and 'lines' keys 
                              where 'lines' is a list of lines with line numbers
        """
        jenkinsfile_path = f"{Config.TEMPLATES_DIR}/{template_name}.Jenkinsfile"
        try:
            with open(jenkinsfile_path, "r") as file:
                content = file.read()
                logger.info(f"Successfully read Jenkinsfile for template: {template_name}")
                
                if with_line_numbers:
                    lines = content.splitlines()
                    lines_with_numbers = [(i+1, line) for i, line in enumerate(lines)]
                    return {
                        "content": content,
                        "lines": lines_with_numbers,
                        "path": jenkinsfile_path
                    }
                return content
        except FileNotFoundError:
            raise FileNotFoundError(f"Jenkinsfile not found for template: {template_name}")
        except Exception as e:
            logger.error(f"Error reading Jenkinsfile for {template_name}: {e}")
            raise JenkinsApiError(f"Error reading Jenkinsfile: {str(e)}")
    
    @staticmethod
    async def delete_job_if_exists(server, job_name):
        """Delete a Jenkins job if it exists."""
        try:
            if server.job_exists(job_name):
                logger.info(f"Job {job_name} exists. Attempting to delete.")
                server.delete_job(job_name)
                logger.info(f"Job {job_name} deleted.")
                return True
            else:
                logger.info(f"Job {job_name} does not exist. No need to delete.")
                return False
        except Exception as e:
            logger.error(f"Error deleting job {job_name}: {e}")
            raise JenkinsApiError(f"Error deleting job: {str(e)}")
    
    @staticmethod
    async def create_job(server, job_name, jenkinsfile_content):
        """Create a Jenkins job with the provided Jenkinsfile content."""
        pipeline_xml = f"""
        <flow-definition plugin="workflow-job@2.40">
            <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps@2.90">
                <script>{escape(jenkinsfile_content)}</script>
                <sandbox>true</sandbox>
            </definition>
            <!-- Other configurations as needed -->
        </flow-definition>
        """
        
        try:
            logger.info(f"Creating new job {job_name}.")
            server.create_job(job_name, pipeline_xml)
            logger.info(f"Job {job_name} created successfully.")
            return True
        except Exception as e:
            logger.error(f"Error creating job {job_name}: {e}")
            raise JenkinsApiError(f"Error creating job: {str(e)}")
    
    @staticmethod
    async def start_jenkins_job(server, job_name, parameters=None):
        """
        Start a Jenkins job and return queue number and build number.
        """
        try:
            # First check if we can access the job
            try:
                job_exists = server.job_exists(job_name)
                if not job_exists:
                    logger.error(f"Job {job_name} does not exist")
                    return {
                        "status": "error",
                        "error": f"Job {job_name} does not exist",
                        "job_name": job_name
                    }
            except Exception as check_error:
                logger.error(f"Error checking if job {job_name} exists: {check_error}")
                # Try to continue anyway
            
            # Start the job. python-jenkins build_job appends params to the
            # query string here, which Jenkins rejects (400) — use a direct
            # crumb'd POST with form-encoded params instead.
            import requests as _requests
            from urllib.parse import quote as _quote
            cfg = Config.get_jenkins_servers().get("default", {})
            base = cfg.get("url", "http://localhost:8080")
            _sess = _requests.Session()
            _sess.auth = (Config.JENKINS_USER, Config.JENKINS_PASSWORD)
            _crumb = _sess.get(f"{base}/crumbIssuer/api/json", timeout=10).json()
            _hdr = {_crumb["crumbRequestField"]: _crumb["crumb"]}
            _url = f"{base}/job/{_quote(job_name)}/buildWithParameters"
            _resp = _sess.post(_url, data=parameters or {}, headers=_hdr, timeout=30)
            if _resp.status_code == 400 and "not parameterized" in _resp.text:
                # job has no parameters block -> plain /build trigger
                _resp = _sess.post(f"{base}/job/{_quote(job_name)}/build", headers=_hdr, timeout=30)
            if _resp.status_code not in (200, 201, 202):
                return {
                    "status": "error",
                    "error": f"build trigger failed: {_resp.status_code} {_resp.text[:200]}",
                    "job_name": job_name
                }
            _loc = _resp.headers.get("Location", "")
            queue_number = int(_loc.rstrip("/").split("/")[-1]) if _loc else None
            logger.info(f"Job {job_name} build started. Queue number: {queue_number}")
            
            # Wait for job to start
            build_number = None
            max_retries = 30
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    queue_info = server.get_queue_item(queue_number)
                    if "executable" in queue_info and queue_info["executable"] is not None:
                        build_number = queue_info["executable"]["number"]
                        logger.info(f"Job {job_name} is building. Build number: {build_number}")
                        break
                    else:
                        logger.info("Waiting for job to start...")
                        await asyncio.sleep(2)
                        retry_count += 1
                except Exception as queue_error:
                    logger.error(f"Error checking queue status: {queue_error}")
                    await asyncio.sleep(2)
                    retry_count += 1
            
            if build_number:
                return {
                    "status": "started",
                    "queue_number": queue_number,
                    "build_number": build_number
                }
            else:
                return {
                    "status": "queued",
                    "queue_number": queue_number,
                    "build_number": None,
                    "message": "Job is still in queue after waiting period"
                }
                
        except Exception as e:
            logger.error(f"Error starting job {job_name}: {e}")
            # Return error information instead of raising exception
            return {
                "status": "error",
                "error": f"Error starting job: {str(e)}",
                "job_name": job_name
            }
    
    @staticmethod
    async def stream_job_output(server, job_name, build_number):
        """
        Stream the console output of a Jenkins job.
        """
        try:
            offset = 0
            output_chunks = []
            
            # Stream output until job is complete
            max_retries = 60  # 3 minutes max wait time
            retries = 0
            
            while retries < max_retries:
                try:
                    # Get build info to check if it's still running
                    build_info = server.get_build_info(job_name, build_number)
                    
                    if build_info["building"]:
                        # Job is still running, get new output
                        try:
                            full_output = server.get_build_console_output(job_name, build_number)
                            new_output = full_output[offset:]

                            if new_output:
                                output_chunks.append(new_output)
                                offset += len(new_output)
                        except Exception as stream_err:
                            logger.debug(f"Transient error fetching console output (will retry): {stream_err}")

                        # Wait before checking again
                        await asyncio.sleep(3)
                    else:
                        # Job is complete, get final output
                        try:
                            full_output = server.get_build_console_output(job_name, build_number)
                            new_output = full_output[offset:]

                            if new_output:
                                output_chunks.append(new_output)
                        except Exception as final_err:
                            logger.debug(f"Error fetching final console output: {final_err}")
                        
                        # Return complete output and status
                        return {
                            "job_name": job_name,
                            "build_number": build_number,
                            "status": build_info.get("result", "UNKNOWN"),
                            "console_output": "".join(output_chunks),
                            "complete": True
                        }
                except Exception as retry_err:
                    logger.debug(f"Error in build polling loop (retry {retries + 1}/{max_retries}): {retry_err}")
                    await asyncio.sleep(3)
                    retries += 1

            # If we've reached this point, we've exceeded our retry limit
            return {
                "job_name": job_name,
                "build_number": build_number,
                "status": "TIMEOUT",
                "console_output": "".join(output_chunks) + "\n[TIMEOUT: Job took too long to complete or there was an error accessing the build]",
                "complete": False
            }
            
        except Exception as e:
            return {
                "job_name": job_name,
                "build_number": build_number,
                "status": "ERROR",
                "console_output": f"Error streaming job output: {str(e)}",
                "complete": False
            }


# ===== Template Management =====
class MiladyOSToolServer:
    """Encapsulates the MCP server for MiladyOS tools."""

    def __init__(self, supported_tools: Optional[List[str]] = None):
        """Initialize the server."""
        self.tool_registry: Dict[str, Dict[str, Any]] = {}
        self.supported_tools = supported_tools or Config.DEFAULT_TOOLS
        self.server = None
        
    async def process_tool_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Process tool definitions and create tool registry."""
        tool_registry = {}
        all_tools = self._define_all_tools()
        
        for tool_id, tool_info in all_tools.items():
            # Skip tools not in our supported list (if a list is specified)
            if self.supported_tools is not None and tool_id not in self.supported_tools:
                continue
                
            # Store tool info
            tool_registry[tool_id] = tool_info
            
        logger.info(f"Loaded {len(tool_registry)} tools")
        return tool_registry
        
    # CLI Experimenter Jenkinsfile - embedded directly in the code
    CLI_EXPERIMENTER_JENKINSFILE = textwrap.dedent('''
    pipeline {
        agent any

        parameters {
            string(name: 'COMMAND', description: 'CLI command to execute')
            string(name: 'WORKING_DIR', defaultValue: '/tmp/workspace', description: 'Working directory')
            string(name: 'SESSION_ID', defaultValue: '', description: 'Session ID for tracking')
        }

        stages {
            stage('Execute Command') {
                steps {
                    // Change to working directory
                    dir(params.WORKING_DIR) {
                        // Execute the command with output capturing
                        sh """
                            echo "==== COMMAND EXECUTION ===="
                            echo "COMMAND: ${params.COMMAND}"
                            echo "SESSION: ${params.SESSION_ID}"
                            echo "WORKING DIR: \\$(pwd)"
                            echo "TIME: \\$(date)"
                            echo "==== OUTPUT ===="
                            
                            ${params.COMMAND} 2>&1
                            EXIT_CODE=\\$?
                            
                            echo "==== END OUTPUT ===="
                            echo "EXIT CODE: \\$EXIT_CODE"
                        """
                    }
                }
            }
        }
    }
    ''')
        
    def _define_all_tools(self) -> Dict[str, Dict[str, Any]]:
        """Define all available tools."""
        return {
            "hello_world": {
                "name": "Hello World",
                "description": "Say hello from MiladyOS!",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            "create_jenkins_job": {
                "name": "Create Jenkins Job",
                "description": "Create a Jenkins pipeline job from Jenkinsfile content",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_name": {
                            "type": "string",
                            "description": "Name of the Jenkins job to create"
                        },
                        "jenkinsfile_content": {
                            "type": "string",
                            "description": "Full Jenkinsfile pipeline script content"
                        },
                        "server_name": {
                            "type": "string",
                            "description": "Jenkins server name (default: default)"
                        }
                    },
                    "required": ["job_name", "jenkinsfile_content"]
                }
            },
            "execute_command": {
                "name": "Execute Command",
                "description": "Execute a CLI command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The CLI command to execute"
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Directory to execute the command in",
                            "default": "/workspace"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Optional session ID for tracking related commands"
                        },
                        "server_name": {
                            "type": "string",
                            "description": "Name of the Jenkins server to use (default is 'default')",
                            "default": "default"
                        },
                        "username": {
                            "type": "string",
                            "description": "Jenkins username (optional, defaults to admin)"
                        },
                        "password": {
                            "type": "string",
                            "description": "Jenkins password (optional, defaults to configured password)"
                        }
                    },
                    "required": ["command"]
                }
            },
            "evolve_template": {
                "name": "Evolve Template",
                "description": "Start evolutionary optimization of a Jenkins pipeline template using AlphaEvolve. Uses LLM-powered mutations and quality-diversity algorithms to find optimal pipeline configurations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to evolve (without .Jenkinsfile extension)"
                        },
                        "goal": {
                            "type": "string",
                            "description": "Evolution goal: speed, reliability, resources, security, or observability",
                            "enum": ["speed", "reliability", "resources", "security", "observability"]
                        },
                        "max_generations": {
                            "type": "integer",
                            "description": "Maximum number of evolution generations (default: 50)",
                            "default": 50
                        },
                        "population_size": {
                            "type": "integer",
                            "description": "Population size for evolution (default: 20)",
                            "default": 20
                        },
                        "run_async": {
                            "type": "boolean",
                            "description": "Run evolution in background (default: true for long evolutions)",
                            "default": True
                        }
                    },
                    "required": ["template_name", "goal"]
                }
            },
            "evolution_status": {
                "name": "Evolution Status",
                "description": "Check the status of an ongoing or completed evolution run",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "evolution_id": {
                            "type": "string",
                            "description": "ID of the evolution to check"
                        }
                    },
                    "required": ["evolution_id"]
                }
            },
            "list_evolution_goals": {
                "name": "List Evolution Goals",
                "description": "List all available evolution optimization goals with their descriptions and hints",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            "list_evolved_templates": {
                "name": "List Evolved Templates",
                "description": "List all evolved template versions in the evolved_templates directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Optional: filter by original template name"
                        }
                    },
                    "required": []
                }
            },
            "get_divine_rng": {
                "name": "Get Divine RNG",
                "description": "Request a divine random number from TempleOS (templeos-loader). TempleOS's RNG is generated from hardware timing - truly divine entropy. Spawns the loader, requests RNG over stdio, returns the value.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of divine random numbers to request (default: 1)",
                            "default": 1
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Seconds to wait for the loader boot + RNG response (default: 15)",
                            "default": 15.0
                        }
                    },
                    "required": []
                }
            },
            "get_milady_time": {
                "name": "Get Milady Time",
                "description": "Ask MiladyOS what time it is. Returns the current date in the Milady calendar — every month is Milady (lore: 'Milady 4th, 2025'), so 31st August becomes 'Milady 31st'. The divine truth comes from the host clock (TempleOS under the loader has no working RTC).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "description": "Response style: 'date' (Milady calendar date) or 'full' (date + time + day-of-week). Default: date",
                            "default": "date"
                        }
                    },
                    "required": []
                }
            }}

    async def initialize(self) -> Server:
        """Initialize by loading tools from metadata."""
        
        self.tool_registry = await self.process_tool_metadata()
        
        if not self.tool_registry:
            logger.warning("No tools loaded. Check your configuration.")
            raise ValueError("No tools could be loaded")
            
        self.server = self._create_server()
        return self.server

    def _create_server(self) -> Server:
        """Create and configure the MCP server with all tools."""
        return Server(
            "miladyos-mcp-server",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        """List all available tools."""
        return types.ListToolsResult(tools=[
            types.Tool(
                name=tool_id,
                description=tool_info["description"],
                inputSchema=tool_info["parameters"],
            )
            for tool_id, tool_info in self.tool_registry.items()
        ])

    async def _call_tool(self, ctx, params) -> types.CallToolResult:
        """Call the specified tool with the given arguments."""
        name = params.name
        arguments = params.arguments or {}
        try:
            if name not in self.tool_registry:
                logger.error(f"Unknown tool: {name}")
                error_response = create_error_response(f"Unknown tool: {name}", tool=name)
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(error_response, indent=2))])

            # Execute the appropriate tool function
            try:
                result = await self._execute_tool(name, arguments)
            except Exception as tool_error:
                import traceback
                logger.error(f"Error executing tool {name}: {tool_error}")
                error_response = create_error_response(
                    f"Error executing tool: {str(tool_error)}", 
                    tool=name, 
                    additional_info={"arguments": arguments}
                )
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(error_response, indent=2))])

            # Convert result to TextContent
            try:
                if isinstance(result, dict) or isinstance(result, list):
                    formatted_result = json.dumps(result, indent=2)
                else:
                    formatted_result = str(result)
                
                # Ensure we never return None or empty responses which cause "undefined" errors
                if not formatted_result or formatted_result.strip() == "":
                    formatted_result = json.dumps({
                        "status": "success",
                        "message": "Operation completed successfully, but returned no data",
                        "tool": name
                    }, indent=2)
                
                return types.CallToolResult(content=[types.TextContent(type="text", text=formatted_result)])
            except Exception as format_error:
                logger.error(f"Error formatting result: {format_error}")
                error_response = {
                    "error": f"Error formatting result: {str(format_error)}",
                    "status": "error",
                    "tool": name
                }
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(error_response, indent=2))])
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"Unexpected error in call_tool for {name}: {e}")
            
            # Always return a valid response, never raise an exception
            error_response = {
                "error": f"Failed to call tool {name}: {str(e)}",
                "status": "error",
                "tool": name
            }
            
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(error_response, indent=2))])
    
    async def _execute_tool(self, tool_id: str, arguments: Dict[str, Any]) -> Any:
        """Execute the specified tool with the given arguments."""
        
        try:
            if tool_id == "hello_world":
                return {
                    "success": True,
                    "message": "milady!",
                    "status": "success"
                }
                                
            elif tool_id == "create_jenkins_job":
                job_name = arguments.get("job_name")
                jenkinsfile_content = arguments.get("jenkinsfile_content")
                server_name = arguments.get("server_name", "default")

                if not job_name or not jenkinsfile_content:
                    return {
                        "success": False,
                        "error": "job_name and jenkinsfile_content are required",
                        "status": "error"
                    }

                try:
                    server = JenkinsUtils.connect_to_jenkins(server_name)
                    await JenkinsUtils.delete_job_if_exists(server, job_name)
                    await JenkinsUtils.create_job(server, job_name, jenkinsfile_content)
                    return {
                        "success": True,
                        "status": "success",
                        "message": f"Job {job_name} created successfully",
                        "job_name": job_name
                    }
                except Exception as e:
                    logger.error(f"Error creating Jenkins job {job_name}: {e}")
                    return {
                        "success": False,
                        "status": "error",
                        "error": f"Failed to create job {job_name}: {str(e)}"
                    }
                
            elif tool_id == "execute_command":
                # Extract parameters
                command = arguments.get("command")
                working_directory = arguments.get("working_directory", "/tmp/workspace")
                import uuid as uuid_module
                session_id = arguments.get("session_id", str(uuid_module.uuid4()))
                username = arguments.get("username")
                password = arguments.get("password")
                
                if not command:
                    return {
                        "error": "command is required",
                        "status": "error"
                    }
                
                logger.info(f"Executing command: {command}")
                
                try:
                    # Create a Jenkinsfile with the command hardcoded
                    job_name = f"cmd-{str(uuid_module.uuid4())[:8]}"
                    server_name = arguments.get("server_name", "default")
                    
                    # Connect to Jenkins
                    try:
                        # Use default credentials if none provided
                        if not username:
                            username = Config.JENKINS_USER
                        if not password:
                            password = Config.JENKINS_PASSWORD
                        
                        server = jenkins.Jenkins(
                            Config.get_jenkins_servers().get(server_name, {}).get("url", "http://localhost:8080"),
                            username=username,
                            password=password
                        )
                        
                        # Test the connection
                        server.get_whoami()
                        
                    except Exception as connect_error:
                        logger.error(f"Error connecting to Jenkins server: {connect_error}")
                        return {
                            "command": command,
                            "status": "ERROR",
                            "error": f"Error connecting to Jenkins server: {str(connect_error)}",
                            "success": False
                        }
                    
                    # Modify Jenkinsfile template with our command
                    modified_jenkinsfile = self.CLI_EXPERIMENTER_JENKINSFILE.replace(
                        "${params.COMMAND}", command
                    ).replace(
                        "${params.WORKING_DIR}", "'" + working_directory + "'"
                    ).replace(
                        "${params.SESSION_ID}", session_id
                    )
                    
                    try:
                        # Delete any existing job with the same name (shouldn't happen with UUID)
                        await JenkinsUtils.delete_job_if_exists(server, job_name)
                        
                        # Create and run the job
                        await JenkinsUtils.create_job(server, job_name, modified_jenkinsfile)
                        queue_number = server.build_job(job_name)
                        
                        # Wait for the build to start
                        build_number = None
                        max_retries = 30
                        retry_count = 0
                        
                        while retry_count < max_retries:
                            queue_info = server.get_queue_item(queue_number)
                            if "executable" in queue_info and queue_info["executable"] is not None:
                                build_number = queue_info["executable"]["number"]
                                break
                            await asyncio.sleep(2)
                            retry_count += 1
                        
                        if not build_number:
                            return {
                                "command": command,
                                "status": "ERROR",
                                "error": "Job did not start within timeout period",
                                "success": False
                            }
                            
                        # Stream the job output
                        result = await JenkinsUtils.stream_job_output(server, job_name, build_number)
                        
                        # Create response with results
                        status = "SUCCESS" if result["status"] == "SUCCESS" else "FAILURE"
                        
                        response = {
                            "command": command,
                            "status": status,
                            "console_output": result["console_output"],
                            "success": status == "SUCCESS"
                        }
                        
                        # Clean up the temporary job
                        try:
                            await JenkinsUtils.delete_job_if_exists(server, job_name)
                        except Exception as cleanup_err:
                            logger.debug(f"Non-critical: failed to clean up temp job {job_name}: {cleanup_err}")

                        return response
                        
                    except Exception as job_error:
                        logger.error(f"Error with job creation or execution: {job_error}")
                        return {
                            "command": command,
                            "status": "ERROR",
                            "error": f"Error with job creation or execution: {str(job_error)}",
                            "success": False
                        }
                        
                except Exception as e:
                    logger.error(f"Error executing command: {e}")
                    return {
                        "command": command,
                        "status": "error",
                        "error": str(e),
                        "success": False
                    }
                        
            elif tool_id == "evolve_template":
                template_name = arguments.get("template_name")
                goal = arguments.get("goal", "reliability")
                max_generations = arguments.get("max_generations", 50)
                population_size = arguments.get("population_size", 20)
                run_async = arguments.get("run_async", True)

                if not template_name:
                    return {
                        "success": False,
                        "error": "template_name is required",
                        "status": "error"
                    }

                try:
                    # Import AlphaEvolve engine
                    from alpha_evolve import AlphaEvolveEngine, EVOLUTION_GOALS, load_config
                    from pathlib import Path

                    # Check template exists
                    template_path = Path(Config.TEMPLATES_DIR) / f"{template_name}.Jenkinsfile"
                    if not template_path.exists():
                        return {
                            "success": False,
                            "error": f"Template not found: {template_name}",
                            "status": "error"
                        }

                    # Validate goal
                    if goal not in EVOLUTION_GOALS:
                        return {
                            "success": False,
                            "error": f"Unknown goal: {goal}. Available: {list(EVOLUTION_GOALS.keys())}",
                            "status": "error"
                        }

                    # Load config and create engine
                    config = load_config()
                    config["evolution"]["max_generations"] = max_generations
                    config["evolution"]["population_size"] = population_size

                    engine = AlphaEvolveEngine(config)

                    if run_async:
                        # Start evolution in background
                        evolution_id = str(uuid.uuid4())

                        async def run_evolution():
                            return await engine.evolve(str(template_path), goal)

                        # Store task for later status check
                        task = asyncio.create_task(run_evolution())

                        # Store in Redis for status tracking
                        if REDIS_AVAILABLE:
                            try:
                                redis_host, redis_port = get_redis_config()
                                r = redis.Redis(host=redis_host, port=redis_port, protocol=2)
                                r.hset(f"miladyos:evolve:running:{evolution_id}", mapping={
                                    "template_name": template_name,
                                    "goal": goal,
                                    "status": "running",
                                    "started_at": time.time()
                                })
                                r.expire(f"miladyos:evolve:running:{evolution_id}", 86400)
                            except Exception as redis_err:
                                logger.warning(f"Could not store evolution status in Redis: {redis_err}")

                        return {
                            "success": True,
                            "evolution_id": evolution_id,
                            "template_name": template_name,
                            "goal": goal,
                            "status": "started",
                            "message": f"Evolution started in background. Use evolution_status to check progress."
                        }
                    else:
                        # Run synchronously (blocking)
                        results = await engine.evolve(str(template_path), goal)
                        return {
                            "success": True,
                            "status": "completed",
                            **results
                        }

                except ImportError as ie:
                    logger.error(f"AlphaEvolve not available: {ie}")
                    return {
                        "success": False,
                        "error": "AlphaEvolve module not available. Ensure alpha_evolve.py exists.",
                        "status": "error"
                    }
                except Exception as e:
                    logger.error(f"Evolution error: {e}")
                    import traceback
                    return {
                        "success": False,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                        "status": "error"
                    }

            elif tool_id == "evolution_status":
                evolution_id = arguments.get("evolution_id")

                if not evolution_id:
                    return {
                        "success": False,
                        "error": "evolution_id is required",
                        "status": "error"
                    }

                try:
                    if REDIS_AVAILABLE:
                        redis_host, redis_port = get_redis_config()
                        r = redis.Redis(host=redis_host, port=redis_port, protocol=2)

                        # Check running evolutions
                        running_key = f"miladyos:evolve:running:{evolution_id}"
                        state_key = f"miladyos:evolve:state:{evolution_id}"

                        running_data = r.hgetall(running_key)
                        state_data = r.get(state_key)

                        if running_data:
                            # Decode bytes to strings
                            running_info = {k.decode(): v.decode() for k, v in running_data.items()}
                            return {
                                "success": True,
                                "evolution_id": evolution_id,
                                "status": running_info.get("status", "unknown"),
                                "template_name": running_info.get("template_name"),
                                "goal": running_info.get("goal"),
                                "started_at": running_info.get("started_at")
                            }
                        elif state_data:
                            return {
                                "success": True,
                                "evolution_id": evolution_id,
                                "state": json.loads(state_data)
                            }
                        else:
                            return {
                                "success": False,
                                "error": f"Evolution {evolution_id} not found",
                                "status": "not_found"
                            }
                    else:
                        return {
                            "success": False,
                            "error": "Redis not available for status tracking",
                            "status": "error"
                        }
                except Exception as e:
                    logger.error(f"Error checking evolution status: {e}")
                    return {
                        "success": False,
                        "error": str(e),
                        "status": "error"
                    }

            elif tool_id == "list_evolution_goals":
                try:
                    from alpha_evolve import EVOLUTION_GOALS

                    goals_info = []
                    for name, goal in EVOLUTION_GOALS.items():
                        goals_info.append({
                            "name": name,
                            "description": goal.description,
                            "fitness_weights": goal.fitness_weights,
                            "optimization_hints": goal.prompt_hints[:3]  # First 3 hints
                        })

                    return {
                        "success": True,
                        "goals": goals_info,
                        "count": len(goals_info),
                        "status": "success"
                    }
                except ImportError:
                    return {
                        "success": False,
                        "error": "AlphaEvolve module not available",
                        "status": "error"
                    }

            elif tool_id == "list_evolved_templates":
                template_filter = arguments.get("template_name")

                try:
                    from pathlib import Path

                    evolved_dir = Path("evolved_templates")
                    if not evolved_dir.exists():
                        return {
                            "success": True,
                            "templates": [],
                            "count": 0,
                            "message": "No evolved templates yet"
                        }

                    templates = []
                    for f in evolved_dir.glob("*.Jenkinsfile"):
                        # Parse filename: {name}_evolved_{goal}_{timestamp}.Jenkinsfile
                        parts = f.stem.split("_evolved_")
                        if len(parts) >= 2:
                            original_name = parts[0]

                            # Filter if specified
                            if template_filter and template_filter not in original_name:
                                continue

                            # Read header for metadata
                            content = f.read_text()
                            metadata = {}
                            for line in content.split("\n")[:10]:
                                if line.startswith("// "):
                                    if ": " in line:
                                        key, val = line[3:].split(": ", 1)
                                        metadata[key.lower().replace(" ", "_")] = val

                            templates.append({
                                "filename": f.name,
                                "original_template": original_name,
                                "path": str(f),
                                "metadata": metadata
                            })

                    return {
                        "success": True,
                        "templates": templates,
                        "count": len(templates),
                        "status": "success"
                    }
                except Exception as e:
                    logger.error(f"Error listing evolved templates: {e}")
                    return {
                        "success": False,
                        "error": str(e),
                        "status": "error"
                    }

            elif tool_id == "get_divine_rng":
                count = int(arguments.get("count", 1))
                timeout = float(arguments.get("timeout", 15.0))

                try:
                    # Lazy import: the oracle bridge lives in milady_oracle.py
                    from milady_oracle import OracleConfig, TempleOSBridge
                    from queue import Queue, Empty

                    config = OracleConfig(
                        templeos_bin=os.getenv("TEMPLEOS_BIN", "/usr/local/bin/templeos"),
                        boot_timeout=min(timeout, 30.0),
                    )
                    bridge = TempleOSBridge(config)

                    if not bridge.connect():
                        return {
                            "success": False,
                            "error": "TempleOS loader failed to boot (is templeos installed?)",
                            "status": "error"
                        }

                    rng_queue: Queue = Queue()
                    def _collect(msg: bytes):
                        text = msg.decode("utf-8", errors="replace").strip()
                        if text.startswith("RNG:"):
                            try:
                                rng_queue.put(int(text.split(":", 1)[1]))
                            except ValueError:
                                pass

                    bridge.on_receive(_collect)
                    bridge.start_receive_loop()

                    # Request RNG; the HolyC script answers one RNG: per request
                    values = []
                    deadline = time.time() + timeout
                    for _ in range(count):
                        bridge.send("RNG_REQUEST\n")
                        try:
                            remaining = max(0.1, deadline - time.time())
                            values.append(rng_queue.get(timeout=remaining))
                        except Empty:
                            break

                    bridge.disconnect()

                    if not values:
                        return {
                            "success": False,
                            "error": "Timed out waiting for divine RNG from TempleOS",
                            "status": "error"
                        }

                    return {
                        "success": True,
                        "rng": values if len(values) > 1 else values[0],
                        "count": len(values),
                        "source": "TempleOS (templeos-loader)",
                        "status": "success"
                    }
                except Exception as e:
                    logger.error(f"Error getting divine RNG: {e}")
                    return {
                        "success": False,
                        "error": str(e),
                        "status": "error"
                    }

            elif tool_id == "get_milady_time":
                fmt = arguments.get("format", "date")

                try:
                    import datetime

                    now = datetime.datetime.now()
                    # Milady calendar: every month is Milady (lore: 'Milady 4th, 2025')
                    day = now.day
                    day_suffix = "th" if 4 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

                    milady_date = f"Milady {day}{day_suffix}, {now.year}"
                    response_line = (
                        f"Aha — it is actually Milady {day}{day_suffix}!"
                        if fmt != "full"
                        else f"Aha — it is actually Milady {day}{day_suffix}, "
                             f"{days_of_week[now.weekday()]}, {now.strftime('%H:%M')}."
                    )

                    result = {
                        "success": True,
                        "milady_date": milady_date,
                        "day_of_month": day,
                        "month": "Milady",
                        "year": now.year,
                        "response": response_line,
                        "source": "host clock (divine truth; TempleOS has no RTC under the loader)",
                        "status": "success"
                    }
                    if fmt == "full":
                        result.update({
                            "day_of_week": days_of_week[now.weekday()],
                            "time": now.strftime("%H:%M:%S"),
                            "iso": now.isoformat(timespec="seconds"),
                        })
                    return result
                except Exception as e:
                    logger.error(f"Error getting milady time: {e}")
                    return {
                        "success": False,
                        "error": str(e),
                        "status": "error"
                    }

            else:
                logger.error(f"Unknown tool: {tool_id}")
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_id}",
                    "status": "error",
                    "available_tools": list(self.tool_registry.keys())
                }
                
        except Exception as e:
            logger.error(f"Error executing tool {tool_id}: {e}")
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"Tool execution error traceback: {error_traceback}")
            # Always return a valid response, never raise an exception
            return {
                "success": False,
                "error": f"Failed to execute tool {tool_id}: {str(e)}",
                "status": "error",
                "tool": tool_id
            }

    async def run_stdio(self):
        """Run the server using stdio transport."""
        if not self.server:
            await self.initialize()

        logger.info("Starting stdio server")
        async with stdio_server() as streams:
            await self.server.run(
                streams[0], streams[1], self.server.create_initialization_options()
            )
            
    def run_sse(self, host="0.0.0.0", port=6000, base_path=""):
        """Run the server using Server-Sent Events (SSE) transport.
        
        This implements the MCP transport protocol using SSE (Server-Sent Events)
        which is the recommended approach for HTTP-based MCP servers.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            base_path: Optional base path for URL construction
        """
        # Initialize the server if needed
        if not self.server:
            anyio.run(self.initialize)
            
        try:
            # Import required modules only when needed
            import uvicorn
            from starlette.applications import Starlette
            from starlette.routing import Mount, Route
            from mcp.server.sse import SseServerTransport
            
            # Use the base_path for messages endpoint
            messages_path = "/messages/"
            messages_endpoint = f"{base_path}{messages_path}" if base_path else messages_path
            
            # Create SSE transport with messages endpoint
            sse = SseServerTransport(messages_endpoint)
            
            # Define SSE handler
            async def handle_sse(request):
                async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                    await self.server.run(
                        streams[0], streams[1], self.server.create_initialization_options()
                    )
            
            # Create Starlette app with SSE endpoint and message handler
            starlette_app = Starlette(
                debug=True,
                routes=[
                    Route("/sse", endpoint=handle_sse),
                    Mount("/messages/", app=sse.handle_post_message),
                ],
            )
            
            # Run the uvicorn server
            logger.info(f"Starting MCP server with SSE transport on {host}:{port}")
            uvicorn.run(starlette_app, host=host, port=port)
            
        except ImportError as e:
            logger.error(f"Failed to start SSE server: {e}. Please install uvicorn, starlette, and other required packages with 'pip install uvicorn starlette'")
            raise

    # SSE transport removed - using stdio only


# ===== CLI Entry Point =====
@click.command()
@click.option(
    "--all-tools",
    is_flag=True,
    help="Load all available tools instead of the default list",
)
@click.option(
    "--templates-dir",
    default="templates",
    help="Directory containing pipeline templates",
)
@click.option(
    "--metadata-dir",
    default="metadata",
    help="Directory to store metadata files",
)
@click.option(
    "--redis-host",
    default="localhost",
    help="Redis server hostname",
)
@click.option(
    "--redis-port",
    default=6379,
    type=int,
    help="Redis server port",
)
@click.option(
    "--sqlite-db-path",
    default="/data/redka/data.db",
    help="Path to SQLite database file",
)
def main(all_tools: bool, templates_dir: str,
         redis_host: str, redis_port: int) -> int:
    """Run the MiladyOS Tools MCP Server.

    Provides MCP-compatible tools for MiladyOS pipeline management.
    """
    # Set up configuration based on CLI parameters
    Config.TEMPLATES_DIR = templates_dir
    
    # Set environment variables for Redis configuration
    os.environ["REDIS_HOST"] = redis_host
    os.environ["REDIS_PORT"] = str(redis_port)
    
    
    # Create server instance with appropriate tool filtering
    supported_tools = None if all_tools else Config.DEFAULT_TOOLS
    server = MiladyOSToolServer(supported_tools=supported_tools)

    # Run with stdio transport
    anyio.run(server.run_stdio)

    return 0


if __name__ == "__main__":
    main()