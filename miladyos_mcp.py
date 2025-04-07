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

import jenkins
import colorlog
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types
from xml.sax.saxutils import escape

# Import our metadata management system
from miladyos_metadata import MetadataManager, RedkaMetadataManager, REDIS_AVAILABLE

# Global metadata manager instance will be set during initialization
metadata_manager = None

# Configure logging
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
        "create_template",
        "edit_template",
        "list_templates",
        "deploy_pipeline",
        "run_pipeline",
        "get_pipeline_status",
        "list_pipeline_runs",
        "hello_world",
        "execute_command"
    ]

    # Jenkins credentials - hardcoded for reliability
    JENKINS_USER = "admin"
    JENKINS_PASSWORD = "password"
    
    # Jenkins server configurations
    JENKINS_SERVERS = {
        "default": {
            "url": "http://localhost:8080"
        }
    }

    # Templates and metadata directories
    TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
    METADATA_DIR = os.getenv("METADATA_DIR", "metadata")

    @classmethod
    def get_jenkins_servers(cls):
        """Return Jenkins server configurations."""
        return cls.JENKINS_SERVERS


# ===== Custom Exceptions =====
class JenkinsApiError(Exception):
    """Raised when there's an error with the Jenkins API."""
    pass


# ===== Jenkins Utilities =====
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
    def get_jenkinsfile_content(template_name):
        """
        Read and return Jenkinsfile content for a template.
        """
        jenkinsfile_path = f"{Config.TEMPLATES_DIR}/{template_name}.Jenkinsfile"
        try:
            with open(jenkinsfile_path, "r") as file:
                content = file.read()
                logger.info(f"Successfully read Jenkinsfile for template: {template_name}")
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
            
            # Start the job
            if parameters:
                queue_number = server.build_job(job_name, parameters)
            else:
                queue_number = server.build_job(job_name)
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
                        except Exception:
                            pass
                        
                        # Wait before checking again
                        await asyncio.sleep(3)
                    else:
                        # Job is complete, get final output
                        try:
                            full_output = server.get_build_console_output(job_name, build_number)
                            new_output = full_output[offset:]
                            
                            if new_output:
                                output_chunks.append(new_output)
                        except Exception:
                            pass
                        
                        # Return complete output and status
                        return {
                            "job_name": job_name,
                            "build_number": build_number,
                            "status": build_info.get("result", "UNKNOWN"),
                            "console_output": "".join(output_chunks),
                            "complete": True
                        }
                except Exception:
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
class TemplateUtils:
    """Utility functions for template management."""
    
    @staticmethod
    def generate_jenkinsfile_content(template_name, description, agent="any", environment_vars=None):
        """Generate Jenkinsfile content based on description."""
        # Check for existing Jenkinsfiles to use as templates/reference
        try:
            example_files = os.listdir(Config.TEMPLATES_DIR)
            if example_files:
                example_file = next((f for f in example_files if f.endswith('.Jenkinsfile')), None)
                if example_file:
                    with open(f"{Config.TEMPLATES_DIR}/{example_file}", "r") as file:
                        pass  # Read a template file, but we don't actually use it
        except Exception as e:
            logger.warning(f"Could not read template Jenkinsfile: {e}")
            
        # Parse description to determine the type of pipeline
        lowercase_desc = description.lower()
        
        # Environment section
        env_section = ""
        if environment_vars:
            env_vars_formatted = "\n            ".join([f'{var}' for var in environment_vars])
            env_section = f"""
        environment {{
            {env_vars_formatted}
        }}"""
            
        # Generate stages based on description
        stages = []
        
        # Checkout stage (common for most pipelines)
        stages.append("""
        stage('Checkout') {
            steps {
                checkout scm
            }
        }""")
        
        # Add stages based on description keywords
        if any(keyword in lowercase_desc for keyword in ["build", "compile", "package"]):
            stages.append("""
        stage('Build') {
            steps {
                echo 'Building...'
                sh 'echo "Your build commands here"'
            }
        }""")
            
        if any(keyword in lowercase_desc for keyword in ["test", "check", "validate"]):
            stages.append("""
        stage('Test') {
            steps {
                echo 'Testing...'
                sh 'echo "Your test commands here"'
            }
        }""")
            
        if any(keyword in lowercase_desc for keyword in ["deploy", "publish", "release"]):
            stages.append("""
        stage('Deploy') {
            steps {
                echo 'Deploying...'
                sh 'echo "Your deployment commands here"'
            }
        }""")
            
        # Determine if specific custom stage is needed
        if "docker" in lowercase_desc or "container" in lowercase_desc:
            stages.append("""
        stage('Docker Build') {
            steps {
                echo 'Building Docker image...'
                sh 'echo "docker build -t myapp:latest ."'
            }
        }""")

        # Add a stage for the main purpose from the description
        # Extract key verb from description (first word)
        main_action = description.split()[0].lower() if description else "run"
        main_action_clean = ''.join(c for c in main_action if c.isalnum())
        
        # If no specific stages added, add a generic one based on description
        if len(stages) <= 1:  # Only checkout stage exists
            stages.append(f"""
        stage('{main_action_clean.capitalize()}') {{
            steps {{
                echo '{description}'
                sh 'echo "Commands to {main_action_clean} will go here"'
            }}
        }}""")
        
        # Combine all stages
        all_stages = "".join(stages)
        
        # Generate the full Jenkinsfile
        jenkinsfile = f"""// Jenkinsfile for {template_name}
// Description: {description}
pipeline {{
    agent {{{agent}}}
{env_section}
    stages {{{all_stages}
    }}
    post {{
        success {{
            echo 'Pipeline completed successfully!'
        }}
        failure {{
            echo 'Pipeline failed'
        }}
    }}
}}
"""
        
        return jenkinsfile


# ===== Tool MCP Server =====
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
            string(name: 'WORKING_DIR', defaultValue: '/workspace', description: 'Working directory')
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
            "edit_template": {
                "name": "Edit Template",
                "description": "Edit an existing template in the templates directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to edit (without .Jenkinsfile extension)"
                        },
                        "content": {
                            "type": "string",
                            "description": "New content for the template"
                        },
                        "diff_preview": {
                            "type": "boolean",
                            "description": "If true, return a diff preview without saving changes",
                            "default": False
                        },
                        "description": {
                            "type": "string",
                            "description": "Updated description for the template (optional)"
                        }
                    },
                    "required": ["template_name", "content"]
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
            "create_template": {
                "name": "Create Template",
                "description": "Create or modify a template in the templates directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to create (without .Jenkinsfile extension)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of what the pipeline should do"
                        },
                        "agent": {
                            "type": "string",
                            "description": "Agent to use (default is 'any')",
                            "default": "any"
                        },
                        "environment": {
                            "type": "array",
                            "description": "List of environment variables to set",
                            "items": {
                                "type": "string"
                            }
                        }
                    },
                    "required": ["template_name", "description"]
                }
            },
            "list_templates": {
                "name": "List Templates",
                "description": "List all available pipeline templates",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            "deploy_pipeline": {
                "name": "Deploy Pipeline",
                "description": "Register a template with Jenkins (with version control)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to deploy (without .Jenkinsfile extension)"
                        },
                        "job_name": {
                            "type": "string",
                            "description": "Name of the Jenkins job to create (defaults to template name)"
                        },
                        "server_name": {
                            "type": "string",
                            "description": "Name of the Jenkins server to deploy to (default is 'default')",
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
                    "required": ["template_name"]
                }
            },
            "run_pipeline": {
                "name": "Run Pipeline",
                "description": "Execute a pipeline and record in metadata layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string", 
                            "description": "Name of the template to run (required unless jenkinsfile_content is provided)"
                        },
                        "job_name": {
                            "type": "string",
                            "description": "Name of the Jenkins job (defaults to template name)"
                        },
                        "server_name": {
                            "type": "string",
                            "description": "Name of the Jenkins server to run on (default is 'default')",
                            "default": "default"
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Parameters to pass to the pipeline"
                        },
                        "stream_output": {
                            "type": "boolean",
                            "description": "Whether to stream the job output (default is true)",
                            "default": True
                        },
                        "username": {
                            "type": "string",
                            "description": "Jenkins username (optional, defaults to admin)"
                        },
                        "password": {
                            "type": "string",
                            "description": "Jenkins password (optional, defaults to configured password)"
                        },
                        "jenkinsfile_content": {
                            "type": "string",
                            "description": "Direct Jenkinsfile content to use instead of a template (optional)"
                        }
                    },
                    "required": []
                }
            },
            "get_pipeline_status": {
                "name": "Get Pipeline Status",
                "description": "Get status from metadata layer (not directly from Jenkins)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "execution_id": {
                            "type": "string",
                            "description": "ID of the execution to check"
                        }
                    },
                    "required": ["execution_id"]
                }
            },
            "list_pipeline_runs": {
                "name": "List Pipeline Runs",
                "description": "Show execution history from metadata",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Optional name of the template to filter by"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of executions to return",
                            "default": 10
                        },
                        "status": {
                            "type": "string",
                            "description": "Optional status to filter by (running, complete, failed)",
                            "enum": ["running", "complete", "failed"]
                        }
                    },
                    "required": []
                }
            }
        }

    async def initialize(self) -> Server:
        """Initialize by loading tools from metadata."""
        # Initialize metadata manager if not already initialized
        global metadata_manager
        
        if metadata_manager is None:
            # Always use Redis for metadata management
            if not REDIS_AVAILABLE:
                raise ImportError("Redis package is required for MiladyOS. Please install with 'pip install redis'")
                
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            
            # Initialize Redis-based metadata manager
            metadata_manager = RedkaMetadataManager(
                templates_dir=Config.TEMPLATES_DIR,
                redis_host=redis_host,
                redis_port=redis_port
            )
            logger.info(f"Initialized Redis-based metadata manager ({redis_host}:{redis_port})")
        
        self.tool_registry = await self.process_tool_metadata()
        
        if not self.tool_registry:
            logger.warning("No tools loaded. Check your configuration.")
            raise ValueError("No tools could be loaded")
            
        self.server = self._create_server()
        return self.server

    def _create_server(self) -> Server:
        """Create and configure the MCP server with all tools."""
        app = Server("miladyos-mcp-server")

        @app.list_tools()
        async def list_tools() -> List[types.Tool]:
            """List all available tools."""
            return [
                types.Tool(
                    name=tool_id,
                    description=tool_info["description"],
                    inputSchema=tool_info["parameters"],
                )
                for tool_id, tool_info in self.tool_registry.items()
            ]

        @app.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[types.TextContent]:
            """Call the specified tool with the given arguments."""
            try:
                if name not in self.tool_registry:
                    logger.error(f"Unknown tool: {name}")
                    error_response = {
                        "error": f"Unknown tool: {name}",
                        "status": "error"
                    }
                    return [types.TextContent(type="text", text=json.dumps(error_response, indent=2))]

                # Execute the appropriate tool function
                try:
                    result = await self._execute_tool(name, arguments)
                except Exception as tool_error:
                    import traceback
                    logger.error(f"Error executing tool {name}: {tool_error}")
                    error_response = {
                        "error": f"Error executing tool: {str(tool_error)}",
                        "status": "error",
                        "tool": name,
                        "arguments": arguments
                    }
                    return [types.TextContent(type="text", text=json.dumps(error_response, indent=2))]

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
                    
                    return [types.TextContent(type="text", text=formatted_result)]
                except Exception as format_error:
                    logger.error(f"Error formatting result: {format_error}")
                    error_response = {
                        "error": f"Error formatting result: {str(format_error)}",
                        "status": "error",
                        "tool": name
                    }
                    return [types.TextContent(type="text", text=json.dumps(error_response, indent=2))]
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
                
                return [types.TextContent(type="text", text=json.dumps(error_response, indent=2))]

        return app
    
    async def _execute_tool(self, tool_id: str, arguments: Dict[str, Any]) -> Any:
        """Execute the specified tool with the given arguments."""
        # Ensure metadata_manager is initialized
        global metadata_manager
        if metadata_manager is None:
            # Always use Redis for metadata management
            if not REDIS_AVAILABLE:
                raise ImportError("Redis package is required for MiladyOS. Please install with 'pip install redis'")
                
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            
            # Initialize Redis-based metadata manager
            metadata_manager = RedkaMetadataManager(
                templates_dir=Config.TEMPLATES_DIR,
                redis_host=redis_host,
                redis_port=redis_port
            )
            logger.info(f"Initialized Redis-based metadata manager ({redis_host}:{redis_port})")
        
        try:
            if tool_id == "hello_world":
                return "Hello from MiladyOS! 👋"
                
            elif tool_id == "execute_command":
                # Extract parameters
                command = arguments.get("command")
                working_directory = arguments.get("working_directory", "/workspace")
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
                        "${params.WORKING_DIR}", working_directory
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
                        except Exception:
                            pass
                        
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
                        
            elif tool_id == "create_template":
                # Extract parameters
                template_name = arguments.get("template_name")
                description = arguments.get("description")
                agent = arguments.get("agent", "any")
                environment_vars = arguments.get("environment", [])
                
                if not template_name:
                    logger.error("template_name is required")
                    return {
                        "success": False,
                        "error": "template_name is required",
                        "status": "error"
                    }
                if not description:
                    logger.error("description is required")
                    return {
                        "success": False,
                        "error": "description is required",
                        "status": "error"
                    }
                
                try:
                    # Generate Jenkinsfile content based on description
                    jenkinsfile_content = TemplateUtils.generate_jenkinsfile_content(
                        template_name,
                        description,
                        agent,
                        environment_vars
                    )
                    
                    # Save the generated Jenkinsfile
                    try:
                        os.makedirs(Config.TEMPLATES_DIR, exist_ok=True)
                        jenkinsfile_path = f"{Config.TEMPLATES_DIR}/{template_name}.Jenkinsfile"
                        
                        with open(jenkinsfile_path, "w") as file:
                            file.write(jenkinsfile_content)
                    except Exception as file_error:
                        logger.error(f"Error writing template file: {file_error}")
                        return {
                            "success": False,
                            "template_name": template_name,
                            "error": f"Error writing template file: {str(file_error)}",
                            "status": "error"
                        }
                    
                    # Register template with metadata system
                    try:
                        template_info = metadata_manager.register_template(template_name, description)
                    except Exception as register_error:
                        logger.error(f"Error registering template with metadata system: {register_error}")
                        # Continue anyway, the file was created successfully
                        template_info = {
                            "name": template_name,
                            "description": description,
                            "version": 1
                        }
                    
                    return {
                        "template_name": template_name,
                        "success": True,
                        "status": "success",
                        "message": f"Created template {template_name}",
                        "path": jenkinsfile_path,
                        "version": template_info.get("version", 1),
                        "content": jenkinsfile_content
                    }
                    
                except Exception as e:
                    logger.error(f"Error creating template: {e}")
                    import traceback
                    error_traceback = traceback.format_exc()
                    logger.error(f"Template creation error traceback: {error_traceback}")
                    return {
                        "success": False,
                        "template_name": template_name,
                        "error": f"Error creating template: {str(e)}",
                        "status": "error"
                    }
                
            elif tool_id == "edit_template":
                # Extract parameters
                template_name = arguments.get("template_name")
                content = arguments.get("content")
                diff_preview = arguments.get("diff_preview", False)
                new_description = arguments.get("description")
                
                if not template_name:
                    logger.error("template_name is required")
                    return {
                        "success": False,
                        "error": "template_name is required",
                        "status": "error"
                    }
                if not content:
                    logger.error("content is required")
                    return {
                        "success": False,
                        "error": "content is required",
                        "status": "error"
                    }
                
                try:
                    # Check if the template exists
                    jenkinsfile_path = f"{Config.TEMPLATES_DIR}/{template_name}.Jenkinsfile"
                    
                    if not os.path.exists(jenkinsfile_path):
                        return {
                            "success": False,
                            "template_name": template_name,
                            "error": f"Template {template_name} does not exist",
                            "status": "error"
                        }
                    
                    # Read existing content for diff preview
                    with open(jenkinsfile_path, "r") as file:
                        existing_content = file.read()
                    
                    # Generate diff if requested
                    diff = None
                    if diff_preview:
                        import difflib
                        differ = difflib.unified_diff(
                            existing_content.splitlines(),
                            content.splitlines(),
                            fromfile=f"{template_name}.Jenkinsfile (original)",
                            tofile=f"{template_name}.Jenkinsfile (edited)",
                            lineterm=""
                        )
                        diff = "\n".join(differ)
                    
                    # If diff_preview is true, just return the diff without saving
                    if diff_preview:
                        return {
                            "success": True,
                            "template_name": template_name,
                            "status": "preview",
                            "diff": diff,
                            "message": "Diff preview generated"
                        }
                    
                    # Write the new content
                    with open(jenkinsfile_path, "w") as file:
                        file.write(content)
                    
                    # Update metadata if description is provided
                    metadata_updated = False
                    if new_description:
                        template_info = metadata_manager.update_template(template_name, new_description)
                        metadata_updated = True
                    else:
                        # Still increment the version without changing description
                        template_info = metadata_manager.increment_template_version(template_name)
                        metadata_updated = True
                    
                    response = {
                        "success": True,
                        "template_name": template_name,
                        "status": "success",
                        "message": f"Template {template_name} updated successfully",
                        "metadata_updated": metadata_updated
                    }
                    
                    # Add diff to response if available
                    if diff:
                        response["diff"] = diff
                    
                    # Add version info if available
                    if template_info and "version" in template_info:
                        response["version"] = template_info["version"]
                    
                    return response
                    
                except Exception as e:
                    logger.error(f"Error editing template: {e}")
                    import traceback
                    error_traceback = traceback.format_exc()
                    logger.error(f"Template editing error traceback: {error_traceback}")
                    return {
                        "success": False,
                        "template_name": template_name,
                        "error": f"Error editing template: {str(e)}",
                        "status": "error"
                    }
                
            elif tool_id == "list_templates":
                try:
                    templates = metadata_manager.list_templates()
                    # Always return a valid JSON structure, never None
                    if not templates:
                        return {
                            "templates": [],
                            "count": 0,
                            "message": "No templates found"
                        }
                    return {
                        "templates": templates,
                        "count": len(templates),
                        "status": "success"
                    }
                except Exception as e:
                    logger.error(f"Error listing templates: {e}")
                    # Return error information instead of raising exception
                    return {
                        "error": f"Error listing templates: {str(e)}",
                        "status": "error",
                        "templates": []
                    }
                
            elif tool_id == "deploy_pipeline":
                # Extract parameters
                template_name = arguments.get("template_name")
                job_name = arguments.get("job_name", template_name)
                server_name = arguments.get("server_name", "default")
                username = arguments.get("username")
                password = arguments.get("password")
                
                if not template_name:
                    raise ValueError("template_name is required")
                
                try:
                    # Detailed step-by-step execution with verbose logging
                    logger.info(f"Starting deploy_pipeline for {template_name} on server {server_name}")
                    
                    # Step 1: Check if the template exists
                    logger.info(f"Step 1: Checking if template {template_name} exists")
                    
                    # Get templates from metadata system
                    templates = metadata_manager.list_templates()
                    template_names = [t["name"] for t in templates]
                    
                    if template_name not in template_names:
                        error_msg = f"Template '{template_name}' not found in templates directory"
                        logger.error(error_msg)
                        return {
                            "success": False,
                            "template_name": template_name,
                            "error": "template_not_found",
                            "message": error_msg
                        }
                    
                    # Step 2: Connect to Jenkins server
                    logger.info(f"Step 2: Connecting to Jenkins server {server_name}")
                    server = JenkinsUtils.connect_to_jenkins(server_name, username, password)
                    
                    # Step 3: Read Jenkinsfile content
                    logger.info(f"Step 3: Reading Jenkinsfile content for {template_name}")
                    jenkinsfile_content = JenkinsUtils.get_jenkinsfile_content(template_name)
                    logger.info(f"Successfully read Jenkinsfile with {len(jenkinsfile_content)} characters")
                    
                    # Step 4: Delete existing job if it exists
                    logger.info(f"Step 4: Deleting existing job {job_name} if it exists")
                    deleted = await JenkinsUtils.delete_job_if_exists(server, job_name)
                    if deleted:
                        logger.info(f"Existing job {job_name} was deleted")
                    else:
                        logger.info(f"No existing job {job_name} found, will create new one")
                    
                    # Step 5: Create new job
                    logger.info(f"Step 5: Creating new job {job_name}")
                    await JenkinsUtils.create_job(server, job_name, jenkinsfile_content)
                    logger.info(f"Successfully created job {job_name}")
                    
                    # Step 6: Register deployment in metadata system
                    logger.info(f"Step 6: Registering deployment in metadata system")
                    deployment_info = metadata_manager.deploy_pipeline(
                        template_name,
                        job_name,
                        server_name
                    )
                    
                    # Return success response
                    return {
                        "success": True,
                        "template_name": template_name,
                        "job_name": job_name,
                        "server_name": server_name,
                        "deployment_id": deployment_info.get("id"),
                        "message": f"Successfully deployed template {template_name} as job {job_name} on server {server_name}"
                    }
                        
                except FileNotFoundError as e:
                    error_msg = f"Jenkinsfile not found for template {template_name}: {str(e)}"
                    logger.error(error_msg)
                    return {
                        "success": False,
                        "template_name": template_name,
                        "error": "jenkinsfile_not_found",
                        "message": error_msg
                    }
                except JenkinsApiError as e:
                    error_msg = f"Jenkins API error while deploying template {template_name}: {str(e)}"
                    logger.error(error_msg)
                    return {
                        "success": False,
                        "template_name": template_name,
                        "error": "jenkins_api_error",
                        "message": error_msg
                    }
                except Exception as e:
                    error_msg = f"Unexpected error deploying template {template_name}: {str(e)}"
                    logger.error(error_msg)
                    return {
                        "success": False,
                        "template_name": template_name,
                        "error": "unexpected_error",
                        "message": error_msg
                    }
            
            elif tool_id == "run_pipeline":
                # Extract parameters
                template_name = arguments.get("template_name")
                job_name = arguments.get("job_name", template_name)
                server_name = arguments.get("server_name", "default")
                pipeline_params = arguments.get("parameters", {})
                stream_output = arguments.get("stream_output", True)
                username = arguments.get("username")
                password = arguments.get("password")
                
                # New parameter for direct Jenkinsfile content
                jenkinsfile_content = arguments.get("jenkinsfile_content")
                
                if not template_name and not jenkinsfile_content:
                    logger.error("Either template_name or jenkinsfile_content is required")
                    return {
                        "success": False,
                        "error": "Either template_name or jenkinsfile_content is required",
                        "status": "error"
                    }
                    
                logger.info(f"Running pipeline with {'direct Jenkinsfile content' if jenkinsfile_content else f'template {template_name}'}")
                
                # If only jenkinsfile_content is provided but no job_name, generate a unique job name
                if jenkinsfile_content and not template_name and job_name == template_name:
                    import uuid as uuid_module  # Import locally to avoid scope issues
                    job_name = f"direct-pipeline-{str(uuid_module.uuid4())[:8]}"
                    # Use a placeholder template name for tracking
                    template_name = f"direct-{job_name}"
                
                try:
                    # Connect to Jenkins
                    try:
                        server = JenkinsUtils.connect_to_jenkins(server_name, username, password)
                    except Exception as connect_error:
                        logger.error(f"Error connecting to Jenkins server: {connect_error}")
                        return {
                            "success": False,
                            "error": f"Error connecting to Jenkins server: {str(connect_error)}",
                            "status": "error",
                            "template_name": template_name,
                            "job_name": job_name
                        }
                    
                    # Check if job exists or if we have direct content
                    if jenkinsfile_content or not server.job_exists(job_name):
                        # If job doesn't exist or we have direct content, deploy it
                        try:
                            if jenkinsfile_content:
                                logger.info(f"Using provided Jenkinsfile content for job {job_name}")
                            else:
                                logger.info(f"Job {job_name} does not exist. Attempting to deploy it first.")
                                # Get Jenkinsfile content from template
                                jenkinsfile_content = JenkinsUtils.get_jenkinsfile_content(template_name)
                            
                            # Delete job if it exists (for direct content or redeployment)
                            await JenkinsUtils.delete_job_if_exists(server, job_name)
                            
                            # Create the job
                            await JenkinsUtils.create_job(server, job_name, jenkinsfile_content)
                            
                            # Register deployment in metadata system only for template-based jobs
                            if not jenkinsfile_content or template_name:
                                deployment_info = metadata_manager.deploy_pipeline(
                                    template_name,
                                    job_name,
                                    server_name
                                )
                        except Exception as deploy_error:
                            logger.error(f"Error deploying job: {deploy_error}")
                            return {
                                "success": False,
                                "error": f"Error deploying job: {str(deploy_error)}",
                                "status": "error",
                                "template_name": template_name,
                                "job_name": job_name
                            }
                    
                    # Start the job
                    job_info = await JenkinsUtils.start_jenkins_job(server, job_name, pipeline_params)
                    
                    # Check for error in job_info
                    if job_info.get("status") == "error":
                        logger.error(f"Error starting job: {job_info.get('error')}")
                        return {
                            "success": False,
                            "error": job_info.get('error', "Unknown error starting job"),
                            "status": "error",
                            "template_name": template_name,
                            "job_name": job_name
                        }
                    
                    if job_info["status"] == "started":
                        build_number = job_info["build_number"]
                        
                        # Record execution in metadata system
                        try:
                            # Make sure we're using RedkaMetadataManager
                            if not isinstance(metadata_manager, RedkaMetadataManager):
                                logger.error("metadata_manager is not an instance of RedkaMetadataManager")
                                # Initialize Redis-based metadata manager
                                redis_host = os.getenv("REDIS_HOST", "localhost")
                                redis_port = int(os.getenv("REDIS_PORT", "6379"))
                                metadata_manager = RedkaMetadataManager(
                                    templates_dir=Config.TEMPLATES_DIR,
                                    redis_host=redis_host,
                                    redis_port=redis_port
                                )
                                logger.info(f"Re-initialized Redis-based metadata manager ({redis_host}:{redis_port})")
                            
                            # Record execution in Redis
                            execution_info = metadata_manager.record_execution(
                                template_name=template_name,
                                jenkins_job_name=job_name,
                                server_name=server_name,
                                build_number=build_number,
                                parameters=pipeline_params
                            )
                            
                            # Verify execution was saved properly
                            execution_key = f"miladyos:execution:{execution_info['id']}"
                            if not metadata_manager.redis.exists(execution_key):
                                logger.error(f"Execution was not saved to Redis after record_execution: {execution_key}")
                                # Attempt to save it directly
                                metadata_manager.redis.hset(execution_key, mapping={
                                    "id": execution_info["id"],
                                    "template_name": template_name,
                                    "jenkins_job_name": job_name,
                                    "server_name": server_name,
                                    "build_number": str(build_number),
                                    "status": "running",
                                    "started_at": execution_info.get("started_at", datetime.now().isoformat())
                                })
                                # Add to the main sorted set
                                metadata_manager.redis.zadd("miladyos:executions", {execution_info["id"]: time.time()})
                                
                                logger.info(f"Directly saved execution to Redis: {execution_key}")
                            
                        except Exception as record_error:
                            logger.error(f"Error recording execution: {record_error}")
                            # Continue anyway, the job is still running
                            import uuid as uuid_module  # Import locally to avoid scope issues
                            execution_id = str(uuid_module.uuid4())
                            execution_info = {
                                "id": execution_id,
                                "template_name": template_name,
                                "jenkins_job_name": job_name,
                                "server_name": server_name,
                                "build_number": build_number
                            }
                            
                            # Try to save directly to Redis as a fallback
                            try:
                                execution_key = f"miladyos:execution:{execution_id}"
                                metadata_manager.redis.hset(execution_key, mapping={
                                    "id": execution_id,
                                    "template_name": template_name,
                                    "jenkins_job_name": job_name,
                                    "server_name": server_name,
                                    "build_number": str(build_number),
                                    "status": "running",
                                    "started_at": datetime.now().isoformat()
                                })
                                # Add to the main sorted set
                                metadata_manager.redis.zadd("miladyos:executions", {execution_id: time.time()})
                                
                                logger.info(f"Saved execution to Redis as fallback: {execution_key}")
                            except Exception as redis_error:
                                logger.error(f"Error saving to Redis as fallback: {redis_error}")
                        
                        # Stream job output if requested
                        if stream_output and build_number is not None:
                            try:
                                result = await JenkinsUtils.stream_job_output(server, job_name, build_number)
                                
                                # Update execution status in metadata system
                                try:
                                    # Make sure we're using RedkaMetadataManager
                                    if not isinstance(metadata_manager, RedkaMetadataManager):
                                        logger.error("metadata_manager is not an instance of RedkaMetadataManager")
                                        # Initialize Redis-based metadata manager
                                        redis_host = os.getenv("REDIS_HOST", "localhost")
                                        redis_port = int(os.getenv("REDIS_PORT", "6379"))
                                        metadata_manager = RedkaMetadataManager(
                                            templates_dir=Config.TEMPLATES_DIR,
                                            redis_host=redis_host,
                                            redis_port=redis_port
                                        )
                                        logger.info(f"Re-initialized Redis-based metadata manager ({redis_host}:{redis_port})")
                                    
                                    # First check if the execution key exists
                                    execution_key = f"miladyos:execution:{execution_info['id']}"
                                    if not metadata_manager.redis.exists(execution_key):
                                        logger.error(f"Execution not found in Redis before update: {execution_key}")
                                        # Recreate it first
                                        metadata_manager.redis.hset(execution_key, mapping={
                                            "id": execution_info["id"],
                                            "template_name": template_name,
                                            "jenkins_job_name": job_name,
                                            "server_name": server_name,
                                            "build_number": str(build_number),
                                            "started_at": datetime.now().isoformat()
                                        })
                                        logger.info(f"Recreated execution in Redis: {execution_key}")
                                    
                                    # Update the execution status
                                    updated_info = metadata_manager.update_execution_status(
                                        execution_info["id"],
                                        "complete" if result["status"] == "SUCCESS" else "failed",
                                        result["status"],
                                        result["console_output"],
                                        server.get_build_info(job_name, build_number).get("duration")
                                    )
                                    
                                    # Store console output in Redis directly
                                    console_key = f"miladyos:console:{execution_info['id']}"
                                    metadata_manager.redis.set(console_key, result["console_output"])
                                    logger.info(f"Saved console output to Redis: {console_key}")
                                    
                                    # Make sure the execution is in the main sorted set
                                    metadata_manager.redis.zadd("miladyos:executions", {execution_info["id"]: time.time()})
                                    
                                    # Remove from running status and add to completed/failed status
                                    status = "complete" if result["status"] == "SUCCESS" else "failed"
                                    metadata_manager.redis.srem("miladyos:status:running", execution_info["id"])
                                    metadata_manager.redis.sadd(f"miladyos:status:{status}", execution_info["id"])
                                    
                                    logger.info(f"Updated execution status in Redis: {execution_info['id']} to {status}")
                                
                                except Exception as update_error:
                                    logger.error(f"Error updating execution status: {update_error}")
                                    # Save execution status directly to Redis as fallback
                                    try:
                                        execution_key = f"miladyos:execution:{execution_info['id']}"
                                        status = "complete" if result["status"] == "SUCCESS" else "failed"
                                        
                                        # Update execution info
                                        update_data = {
                                            "status": status,
                                            "result": result["status"],
                                            "finished_at": datetime.now().isoformat(),
                                            "console_stored": "true"
                                        }
                                        
                                        try:
                                            duration = server.get_build_info(job_name, build_number).get("duration")
                                            if duration:
                                                update_data["duration"] = str(duration)
                                        except Exception:
                                            pass
                                            
                                        metadata_manager.redis.hset(execution_key, mapping=update_data)
                                        
                                        # Store console output
                                        console_key = f"miladyos:console:{execution_info['id']}"
                                        metadata_manager.redis.set(console_key, result["console_output"])
                                        
                                        # Update status sets
                                        metadata_manager.redis.srem("miladyos:status:running", execution_info["id"])
                                        metadata_manager.redis.sadd(f"miladyos:status:{status}", execution_info["id"])
                                        
                                        logger.info(f"Saved execution status directly to Redis as fallback: {execution_key}")
                                    except Exception as redis_error:
                                        logger.error(f"Error saving execution status to Redis as fallback: {redis_error}")
                                
                                # Return final result with comprehensive information
                                return {
                                    "success": True,
                                    "template_name": template_name,
                                    "job_name": job_name,
                                    "server_name": server_name,
                                    "build_number": build_number,
                                    "execution_id": execution_info["id"],
                                    "status": result["status"],
                                    "console_output": result["console_output"],
                                    "message": f"Successfully ran {'provided pipeline' if jenkinsfile_content else f'template {template_name}'} as job {job_name} on server {server_name}"
                                }
                            except Exception as stream_error:
                                logger.error(f"Error streaming job output: {stream_error}")
                                return {
                                    "success": True,
                                    "template_name": template_name,
                                    "job_name": job_name,
                                    "server_name": server_name,
                                    "build_number": build_number,
                                    "execution_id": execution_info["id"],
                                    "status": "running",
                                    "error": f"Error streaming job output: {str(stream_error)}",
                                    "message": f"Job is running but there was an error streaming output"
                                }
                        else:
                            # Return early result without streaming
                            return {
                                "success": True,
                                "template_name": template_name,
                                "job_name": job_name,
                                "server_name": server_name,
                                "build_number": build_number,
                                "execution_id": execution_info["id"],
                                "status": "running",
                                "message": f"Successfully started {'provided pipeline' if jenkinsfile_content else f'template {template_name}'} as job {job_name} on server {server_name}. Build #{build_number} is running."
                            }
                    else:
                        # Job still in queue
                        # Record execution in metadata system (even though it's just queued)
                        try:
                            execution_info = metadata_manager.record_execution(
                                template_name=template_name,
                                jenkins_job_name=job_name,
                                server_name=server_name,
                                build_number=None,
                                parameters=pipeline_params
                            )
                        except Exception as record_error:
                            logger.error(f"Error recording execution: {record_error}")
                            # Continue anyway, the job is still queued
                            import uuid as uuid_module  # Import locally to avoid scope issues
                            execution_info = {
                                "id": str(uuid_module.uuid4()),
                                "template_name": template_name,
                                "jenkins_job_name": job_name,
                                "server_name": server_name
                            }
                        
                        return {
                            "success": True,
                            "template_name": template_name,
                            "job_name": job_name,
                            "server_name": server_name,
                            "queue_number": job_info.get("queue_number"),
                            "execution_id": execution_info["id"],
                            "status": "queued",
                            "message": f"Successfully queued {'provided pipeline' if jenkinsfile_content else f'template {template_name}'} as job {job_name} on server {server_name}."
                        }
                
                except Exception as e:
                    logger.error(f"Error running pipeline: {e}")
                    import traceback
                    error_traceback = traceback.format_exc()
                    logger.error(f"Pipeline execution error traceback: {error_traceback}")
                    # Return error information instead of raising exception
                    return {
                        "success": False,
                        "template_name": template_name,
                        "job_name": job_name,
                        "server_name": server_name,
                        "error": f"Error running pipeline: {str(e)}",
                        "status": "error"
                    }
                
            elif tool_id == "get_pipeline_status":
                # Extract parameters
                execution_id = arguments.get("execution_id")
                
                if not execution_id:
                    logger.error("execution_id is required")
                    return {
                        "success": False,
                        "error": "execution_id is required",
                        "status": "error"
                    }
                
                try:
                    # Get execution info from metadata system
                    execution_info = metadata_manager.get_execution(execution_id)
                    return {
                        "success": True,
                        "status": "success",
                        "execution": execution_info
                    }
                except Exception as e:
                    logger.error(f"Error getting pipeline status: {e}")
                    return {
                        "success": False,
                        "error": f"Error getting pipeline status: {str(e)}",
                        "status": "error",
                        "execution_id": execution_id
                    }
                
            elif tool_id == "list_pipeline_runs":
                # Extract parameters
                template_name = arguments.get("template_name")
                limit = arguments.get("limit", 10)
                status = arguments.get("status")
                
                try:
                    # Get executions from metadata system
                    executions = metadata_manager.list_executions(template_name, limit, status)
                    return {
                        "success": True,
                        "status": "success",
                        "executions": executions,
                        "count": len(executions),
                        "template_name": template_name,
                        "filter_status": status
                    }
                except Exception as e:
                    logger.error(f"Error listing pipeline runs: {e}")
                    return {
                        "success": False,
                        "error": f"Error listing pipeline runs: {str(e)}",
                        "status": "error",
                        "executions": []
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
def main(all_tools: bool, templates_dir: str, metadata_dir: str, 
         redis_host: str, redis_port: int) -> int:
    """Run the MiladyOS Tools MCP Server.

    Provides MCP-compatible tools for MiladyOS pipeline management.
    """
    # Set up configuration based on CLI parameters
    Config.TEMPLATES_DIR = templates_dir
    Config.METADATA_DIR = metadata_dir
    
    # Set environment variables for Redis configuration
    os.environ["REDIS_HOST"] = redis_host
    os.environ["REDIS_PORT"] = str(redis_port)
    
    # Initialize metadata manager with Redis
    global metadata_manager
    if not REDIS_AVAILABLE:
        raise ImportError("Redis package is required for MiladyOS. Please install with 'pip install redis'")
    
    # Always use Redis-based manager
    metadata_manager = RedkaMetadataManager(templates_dir, redis_host, redis_port)
    logger.info(f"Initialized Redis-based metadata manager ({redis_host}:{redis_port})")
    
    # Create server instance with appropriate tool filtering
    supported_tools = None if all_tools else Config.DEFAULT_TOOLS
    server = MiladyOSToolServer(supported_tools=supported_tools)

    # Run with stdio transport
    anyio.run(server.run_stdio)

    return 0


if __name__ == "__main__":
    main()