import json
import logging
import os
import uuid
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import colorlog

# Configure logging
logger = colorlog.getLogger("miladyos-metadata")
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(levelname)s%(reset)s: %(message)s"
))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Default paths
DEFAULT_TEMPLATES_DIR = "templates"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Try to import redis
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    logger.warning("Redis package not available, some features may be limited")
    REDIS_AVAILABLE = False


class RedkaMetadataManager:
    """
    Redis-based Metadata Management System for MiladyOS pipelines.
    Uses Redka (Redis) for storing metadata while keeping templates on disk.
    """

    def __init__(self, templates_dir: str = None, redis_host: str = None, redis_port: int = None):
        """
        Initialize the Redis metadata manager.
        
        Args:
            templates_dir: Directory containing pipeline templates, defaults to "./templates"
            redis_host: Redis server hostname, defaults to "localhost"
            redis_port: Redis server port, defaults to 6379
        """
        if not REDIS_AVAILABLE:
            raise ImportError("Redis package is required for RedkaMetadataManager. Please install with 'pip install redis'")
            
        self.templates_dir = templates_dir or DEFAULT_TEMPLATES_DIR
        self.redis_host = redis_host or REDIS_HOST
        self.redis_port = redis_port or REDIS_PORT
        
        # Initialize Redis connection
        self.redis = redis.Redis(
            host=self.redis_host, 
            port=self.redis_port, 
            decode_responses=True
        )
        
        # Test Redis connection
        try:
            self.redis.ping()
            logger.info(f"Connected to Redis at {self.redis_host}:{self.redis_port}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        
        # Ensure the templates directory exists
        os.makedirs(self.templates_dir, exist_ok=True)
        
    # Template Management Methods
    
    def register_template(self, template_name: str, description: str = None) -> Dict[str, Any]:
        """
        Register a template with the metadata system.
        
        Args:
            template_name: Name of the template
            description: Optional description of the template
            
        Returns:
            Dictionary with template information
        """
        # Check if template exists in file system
        template_path = os.path.join(self.templates_dir, f"{template_name}.Jenkinsfile")
        if not os.path.exists(template_path):
            logger.error(f"Template file not found: {template_path}")
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        # Read template content to extract description if needed
        try:
            with open(template_path, 'r') as f:
                template_content = f.read()
                # Extract description from template if not provided
                if not description and "// Description:" in template_content:
                    for line in template_content.split("\n"):
                        if line.strip().startswith("// Description:"):
                            description = line.strip()[15:].strip()
                            break
        except Exception as e:
            logger.error(f"Error reading template file: {e}")
            raise
        
        # Get or increment version
        template_key = f"miladyos:template:{template_name}"
        version = 1
        
        if self.redis.exists(template_key):
            current_version = self.redis.hget(template_key, "version")
            if current_version:
                version = int(current_version) + 1
            # Get creation timestamp from existing record
            created_at = self.redis.hget(template_key, "created_at")
        else:
            created_at = datetime.now().isoformat()
        
        # Create template information
        now = datetime.now().isoformat()
        template_data = {
            "name": template_name,
            "description": description or "No description provided",
            "template_path": template_path,
            "created_at": created_at,
            "updated_at": now,
            "version": version
        }
        
        # Save to Redis
        self.redis.hset(template_key, mapping=template_data)
        
        # Add to sorted set for easy listing (scored by update time)
        self.redis.zadd("miladyos:templates", {template_name: time.time()})
        
        logger.info(f"Registered template: {template_name} (v{version})")
        return template_data
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all available templates.
        
        Returns:
            List of dictionaries with template information
        """
        # First, check the file system for templates
        template_files = []
        for file in os.listdir(self.templates_dir):
            if file.endswith(".Jenkinsfile"):
                template_name = file.replace('.Jenkinsfile', '')
                template_files.append(template_name)
        
        # Get templates already in Redis
        redis_templates = self.redis.zrange("miladyos:templates", 0, -1)
        
        # Add any new templates found in the file system but not in Redis
        for template_name in template_files:
            if template_name not in redis_templates:
                try:
                    self.register_template(template_name)
                except Exception as e:
                    logger.error(f"Error registering template {template_name}: {e}")
        
        # Remove any Redis templates that no longer exist in the file system
        for template_name in redis_templates:
            if template_name not in template_files:
                logger.info(f"Removing metadata for deleted template: {template_name}")
                self.redis.delete(f"miladyos:template:{template_name}")
                self.redis.zrem("miladyos:templates", template_name)
        
        # Get the updated list of templates from Redis
        templates = []
        template_names = self.redis.zrange("miladyos:templates", 0, -1)
        
        for name in template_names:
            template_data = self.redis.hgetall(f"miladyos:template:{name}")
            if template_data:
                templates.append({
                    "name": name,
                    "description": template_data.get("description", "No description provided"),
                    "version": int(template_data.get("version", 1)),
                    "updated_at": template_data.get("updated_at", "Unknown")
                })
        
        return templates
    
    def deploy_pipeline(self, template_name: str, jenkins_job_name: str, server_name: str) -> Dict[str, Any]:
        """
        Register a pipeline deployment with the metadata system.
        
        Args:
            template_name: Name of the template to deploy
            jenkins_job_name: Name of the Jenkins job
            server_name: Name of the Jenkins server
            
        Returns:
            Dictionary with deployment information
        """
        # Check if template exists
        template_key = f"miladyos:template:{template_name}"
        if not self.redis.exists(template_key):
            raise ValueError(f"Template not found: {template_name}")
        
        # Get template info
        template_data = self.redis.hgetall(template_key)
        
        # Generate a unique deployment ID
        deployment_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        # Create deployment entry
        deployment_info = {
            "id": deployment_id,
            "template_name": template_name,
            "template_version": template_data.get("version", 1),
            "jenkins_job_name": jenkins_job_name,
            "server_name": server_name,
            "deployed_at": now,
            "status": "deployed"
        }
        
        # Save deployment info to Redis
        deployment_key = f"miladyos:deployment:{deployment_id}"
        self.redis.hset(deployment_key, mapping=deployment_info)
        
        # Add deployment to template's deployments set
        template_deployments_key = f"miladyos:template_deployments:{template_name}"
        self.redis.sadd(template_deployments_key, deployment_id)
        
        # Add deployment to job lookup index
        job_index_key = f"miladyos:job_index:{server_name}:{jenkins_job_name}"
        self.redis.set(job_index_key, deployment_id)
        
        logger.info(f"Deployed pipeline: {template_name} as {jenkins_job_name} on {server_name}")
        return deployment_info
    
    def record_execution(self, 
                       deployment_id: str = None,
                       template_name: str = None, 
                       jenkins_job_name: str = None, 
                       server_name: str = None,
                       build_number: int = None,
                       parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Record a pipeline execution in the metadata system.
        
        Args:
            deployment_id: ID of the deployment to execute
            template_name: Name of the template (required if deployment_id not provided)
            jenkins_job_name: Name of the Jenkins job (required if deployment_id not provided)
            server_name: Name of the Jenkins server (required if deployment_id not provided)
            build_number: Jenkins build number
            parameters: Parameters used for the execution
            
        Returns:
            Dictionary with execution information
        """
        # Find deployment ID if not provided
        if not deployment_id and template_name and jenkins_job_name and server_name:
            job_index_key = f"miladyos:job_index:{server_name}:{jenkins_job_name}"
            deployment_id = self.redis.get(job_index_key)
        
        # Generate a unique execution ID
        execution_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        now_ts = time.time()
        
        # Create execution entry - making sure all values are strings for Redis
        execution_info = {
            "id": execution_id,
            "deployment_id": deployment_id if deployment_id else "",
            "template_name": template_name if template_name else "",
            "jenkins_job_name": jenkins_job_name if jenkins_job_name else "",
            "server_name": server_name if server_name else "",
            "build_number": str(build_number) if build_number is not None else "",
            "parameters": json.dumps(parameters or {}),  # Store parameters as JSON string
            "started_at": now,
            "status": "running",
            "result": "",  # Empty string instead of None
            "duration": "",  # Empty string instead of None
            "finished_at": ""  # Empty string instead of None
        }
        
        # Save execution info to Redis
        execution_key = f"miladyos:execution:{execution_id}"
        try:
            # First clear any existing data (just in case)
            self.redis.delete(execution_key)
            
            # Save new execution data as hash
            self.redis.hset(execution_key, mapping=execution_info)
            
            # Verify the data was saved properly
            if not self.redis.exists(execution_key):
                logger.error(f"Failed to save execution to Redis: {execution_key}")
                # Try one more time with pipeline
                p = self.redis.pipeline()
                p.delete(execution_key)
                p.hset(execution_key, mapping=execution_info)
                p.execute()
                
                if not self.redis.exists(execution_key):
                    logger.error(f"Still failed to save execution to Redis after pipeline attempt: {execution_key}")
        except Exception as e:
            logger.error(f"Error saving execution to Redis: {e}")
            # Continue anyway, as we still want to create the indices
        
        try:
            # Add to various indexes for fast retrieval
            
            # Main execution list (newest first)
            self.redis.zadd("miladyos:executions", {execution_id: now_ts})
            
            # Template-specific execution list
            if template_name:
                self.redis.zadd(f"miladyos:template_executions:{template_name}", {execution_id: now_ts})
            
            # Job-specific execution list
            if jenkins_job_name and server_name:
                self.redis.zadd(f"miladyos:job_executions:{server_name}:{jenkins_job_name}", {execution_id: now_ts})
            
            # Status-specific set
            self.redis.sadd("miladyos:status:running", execution_id)
        except Exception as e:
            logger.error(f"Error adding execution to indexes: {e}")
        
        # Double-check that the execution was saved correctly by retrieving it
        saved_execution = self.redis.hgetall(execution_key)
        if not saved_execution:
            logger.error(f"Execution could not be retrieved after saving: {execution_key}")
        else:
            logger.info(f"Successfully verified execution in Redis: {execution_key}")
        
        logger.info(f"Recorded execution: {execution_id} for {jenkins_job_name} #{build_number}")
        return execution_info
    
    def update_execution_status(self, execution_id: str, status: str, result: str = None,
                              console_output: str = None, duration: int = None) -> Dict[str, Any]:
        """
        Update the status of a pipeline execution.
        
        Args:
            execution_id: ID of the execution to update
            status: New status (running, complete, failed)
            result: Result of the execution (SUCCESS, FAILURE, etc.)
            console_output: Console output of the execution
            duration: Duration of the execution in milliseconds
            
        Returns:
            Updated execution information
        """
        # Check if execution exists
        execution_key = f"miladyos:execution:{execution_id}"
        if not self.redis.exists(execution_key):
            logger.error(f"Execution not found: {execution_id}")
            # Instead of raising an error, let's recreate a minimal execution record
            self.redis.hset(execution_key, mapping={
                "id": execution_id,
                "status": "unknown",
                "started_at": datetime.now().isoformat()
            })
            logger.info(f"Created minimal execution record: {execution_id}")
        
        # Get current execution info
        execution_info = self.redis.hgetall(execution_key)
        
        # Create update data with proper string conversion
        update_data = {"status": status}
        
        if result:
            update_data["result"] = result
        
        if duration:
            update_data["duration"] = str(duration)
        
        if status in ["complete", "failed"]:
            update_data["finished_at"] = datetime.now().isoformat()
        
        # Save console output if provided (do this first for reliability)
        if console_output:
            try:
                console_key = f"miladyos:console:{execution_id}"
                # First check if it already exists
                if self.redis.exists(console_key):
                    self.redis.delete(console_key)  # Delete existing data to ensure clean state
                
                # Set the console output
                self.redis.set(console_key, console_output)
                
                # Verify it was saved
                if not self.redis.exists(console_key):
                    logger.error(f"Failed to save console output to Redis: {console_key}")
                    # Try one more time
                    self.redis.set(console_key, console_output)
                
                update_data["console_stored"] = "true"
                logger.info(f"Saved console output to Redis: {console_key} ({len(console_output)} bytes)")
            except Exception as e:
                logger.error(f"Error saving console output: {e}")
        
        try:
            # Update execution info in Redis
            self.redis.hset(execution_key, mapping=update_data)
            
            # Update status indexes
            old_status = execution_info.get("status")
            if status != old_status:
                # First make sure the execution is in the main sorted set
                self.redis.zadd("miladyos:executions", {execution_id: time.time()})
                
                # Remove from old status set
                if old_status:
                    self.redis.srem(f"miladyos:status:{old_status}", execution_id)
                
                # Add to new status set
                self.redis.sadd(f"miladyos:status:{status}", execution_id)
            
            # Get updated execution info
            updated_info = self.redis.hgetall(execution_key)
            
            # Add the execution to template-specific list if not already there
            template_name = updated_info.get("template_name")
            if template_name:
                self.redis.zadd(f"miladyos:template_executions:{template_name}", {execution_id: time.time()})
            
            # Add to job-specific list if not already there
            jenkins_job_name = updated_info.get("jenkins_job_name")
            server_name = updated_info.get("server_name")
            if jenkins_job_name and server_name:
                self.redis.zadd(f"miladyos:job_executions:{server_name}:{jenkins_job_name}", {execution_id: time.time()})
            
            # Handle parameters (convert JSON string back to dict)
            if "parameters" in updated_info and updated_info["parameters"]:
                try:
                    updated_info["parameters"] = json.loads(updated_info["parameters"])
                except json.JSONDecodeError:
                    updated_info["parameters"] = {}
            
            logger.info(f"Updated execution status: {execution_id} to {status} ({result})")
            return updated_info
            
        except Exception as e:
            logger.error(f"Error updating execution status: {e}")
            # Try to return something useful even if the update failed
            return {
                "id": execution_id,
                "status": status,
                "result": result,
                "error": f"Error updating status: {str(e)}"
            }
    
    def get_execution(self, execution_id: str) -> Dict[str, Any]:
        """
        Get information about a specific execution.
        
        Args:
            execution_id: ID of the execution
            
        Returns:
            Execution information
        """
        # Check if execution exists
        execution_key = f"miladyos:execution:{execution_id}"
        if not self.redis.exists(execution_key):
            logger.error(f"Execution not found in Redis: {execution_id}")
            
            # Look for this execution in local metadata files as fallback
            try:
                # Check if there's a console output file for this execution
                console_file = f"metadata/console_{execution_id}.txt"
                if os.path.exists(console_file):
                    logger.info(f"Found local console file for execution: {execution_id}")
                    
                    # Create a minimal execution record
                    execution_info = {
                        "id": execution_id,
                        "status": "unknown",
                        "console_file": console_file,
                        "message": "Execution metadata recovered from local file"
                    }
                    
                    # Try to read the console output
                    try:
                        with open(console_file, 'r') as f:
                            console_output = f.read()
                            execution_info["console_output"] = console_output
                            
                            # Save it to Redis for next time
                            console_key = f"miladyos:console:{execution_id}"
                            self.redis.set(console_key, console_output)
                            
                            # Try to derive status from console output
                            if "SUCCESS" in console_output and "Finished: SUCCESS" in console_output:
                                execution_info["status"] = "complete"
                                execution_info["result"] = "SUCCESS"
                            elif "FAILURE" in console_output and "Finished: FAILURE" in console_output:
                                execution_info["status"] = "failed"
                                execution_info["result"] = "FAILURE"
                    except Exception as read_error:
                        logger.error(f"Error reading console file: {read_error}")
                    
                    return execution_info
            except Exception as file_error:
                logger.error(f"Error checking local files: {file_error}")
            
            # If we still don't have anything, return an error
            raise ValueError(f"Execution not found: {execution_id}")
        
        # Get execution info
        execution_info = self.redis.hgetall(execution_key)
        
        # Convert parameters from JSON string to dict
        if "parameters" in execution_info and execution_info["parameters"]:
            try:
                execution_info["parameters"] = json.loads(execution_info["parameters"])
            except json.JSONDecodeError:
                execution_info["parameters"] = {}
        
        # Load console output if available
        console_key = f"miladyos:console:{execution_id}"
        if self.redis.exists(console_key):
            try:
                execution_info["console_output"] = self.redis.get(console_key)
                logger.info(f"Loaded console output from Redis: {len(execution_info['console_output'])} bytes")
            except Exception as e:
                logger.error(f"Error loading console output from Redis: {e}")
                execution_info["console_output_error"] = f"Error loading console output: {str(e)}"
        else:
            # Check if console_stored flag is set but content is missing
            if execution_info.get("console_stored") == "true":
                execution_info["console_output"] = "Console output was recorded but is no longer available in Redis."
                
                # Try to load from local file as fallback
                try:
                    console_file = f"metadata/console_{execution_id}.txt"
                    if os.path.exists(console_file):
                        with open(console_file, 'r') as f:
                            console_output = f.read()
                            execution_info["console_output"] = console_output
                            
                            # Save it to Redis for next time
                            self.redis.set(console_key, console_output)
                            logger.info(f"Recovered console output from local file and saved to Redis")
                except Exception as file_error:
                    logger.error(f"Error loading console from local file: {file_error}")
        
        return execution_info
    
    def list_executions(self, template_name: str = None, limit: int = 10, 
                      status: str = None) -> List[Dict[str, Any]]:
        """
        List pipeline executions, optionally filtered by template or status.
        
        Args:
            template_name: Optional template name to filter by
            limit: Maximum number of executions to return
            status: Optional status to filter by
            
        Returns:
            List of execution information dictionaries
        """
        execution_ids = []
        
        # Determine which index to use based on filters
        if template_name and status:
            # Get status-filtered IDs
            status_ids = self.redis.smembers(f"miladyos:status:{status}")
            # Get template-filtered IDs
            template_ids = self.redis.zrange(f"miladyos:template_executions:{template_name}", 0, -1, desc=True)
            # Find intersection
            execution_ids = [eid for eid in template_ids if eid in status_ids][:limit]
        elif template_name:
            # Use template index
            execution_ids = self.redis.zrange(f"miladyos:template_executions:{template_name}", 0, limit-1, desc=True)
        elif status:
            # Use status index combined with main index for time ordering
            status_ids = list(self.redis.smembers(f"miladyos:status:{status}"))
            if status_ids:
                # Get all IDs from main index
                all_ids = self.redis.zrange("miladyos:executions", 0, -1, desc=True)
                # Filter by status and apply limit
                execution_ids = [eid for eid in all_ids if eid in status_ids][:limit]
        else:
            # Use main index with no filters
            execution_ids = self.redis.zrange("miladyos:executions", 0, limit-1, desc=True)
        
        # Fetch execution details for each ID
        executions = []
        for exec_id in execution_ids:
            try:
                execution_info = self.get_execution(exec_id)
                executions.append(execution_info)
            except Exception as e:
                logger.error(f"Error fetching execution {exec_id}: {e}")
        
        return executions
    
    def get_console_output(self, execution_id: str) -> str:
        """
        Get console output for an execution.
        
        Args:
            execution_id: ID of the execution
            
        Returns:
            Console output as string
        """
        console_key = f"miladyos:console:{execution_id}"
        if self.redis.exists(console_key):
            return self.redis.get(console_key)
        
        # Get execution info to check if console_stored flag exists but content doesn't
        execution_key = f"miladyos:execution:{execution_id}"
        if self.redis.exists(execution_key) and self.redis.hget(execution_key, "console_stored") == "true":
            return "Console output was recorded but is no longer available."
        
        return "No console output available"
    
    def update_template(self, template_name: str, description: str) -> Dict[str, Any]:
        """
        Update a template's metadata with a new description and incremented version.
        
        Args:
            template_name: Name of the template to update
            description: New description for the template
            
        Returns:
            Dictionary with updated template information
        """
        # Check if template exists
        template_key = f"miladyos:template:{template_name}"
        if not self.redis.exists(template_key):
            raise ValueError(f"Template not found: {template_name}")
        
        # Get current template data
        template_data = self.redis.hgetall(template_key)
        
        # Update version and description
        version = int(template_data.get("version", 0)) + 1
        now = datetime.now().isoformat()
        
        # Create update data
        update_data = {
            "description": description,
            "version": version,
            "updated_at": now
        }
        
        # Save to Redis
        self.redis.hset(template_key, mapping=update_data)
        
        # Update the template in the sorted set (update score to current time)
        self.redis.zadd("miladyos:templates", {template_name: time.time()})
        
        # Also update the description in the Jenkinsfile
        try:
            template_path = os.path.join(self.templates_dir, f"{template_name}.Jenkinsfile")
            if os.path.exists(template_path):
                with open(template_path, 'r') as f:
                    content = f.read()
                
                # Update the description line if it exists
                new_content_lines = []
                description_updated = False
                
                for line in content.split("\n"):
                    if line.strip().startswith("// Description:"):
                        new_content_lines.append(f"// Description: {description}")
                        description_updated = True
                    else:
                        new_content_lines.append(line)
                
                # Add description if it wasn't found
                if not description_updated and len(new_content_lines) > 0:
                    if new_content_lines[0].startswith("//"):
                        new_content_lines.insert(1, f"// Description: {description}")
                    else:
                        new_content_lines.insert(0, f"// Description: {description}")
                
                # Write updated content
                with open(template_path, 'w') as f:
                    f.write("\n".join(new_content_lines))
        except Exception as e:
            logger.error(f"Error updating template description in file: {e}")
        
        # Get updated template data
        updated_data = self.redis.hgetall(template_key)
        
        logger.info(f"Updated template: {template_name} (v{version}) - {description}")
        return updated_data
    
    def increment_template_version(self, template_name: str) -> Dict[str, Any]:
        """
        Increment a template's version number without changing its description.
        
        Args:
            template_name: Name of the template
            
        Returns:
            Dictionary with updated template information
        """
        # Check if template exists
        template_key = f"miladyos:template:{template_name}"
        if not self.redis.exists(template_key):
            raise ValueError(f"Template not found: {template_name}")
        
        # Get current template data
        template_data = self.redis.hgetall(template_key)
        
        # Increment version
        version = int(template_data.get("version", 0)) + 1
        now = datetime.now().isoformat()
        
        # Update in Redis
        self.redis.hset(template_key, mapping={"version": version, "updated_at": now})
        
        # Update the template in the sorted set (update score to current time)
        self.redis.zadd("miladyos:templates", {template_name: time.time()})
        
        # Get updated template data
        updated_data = self.redis.hgetall(template_key)
        
        logger.info(f"Incremented template version: {template_name} (v{version})")
        return updated_data


class MetadataManager:
    """
    Metadata Management System for MiladyOS pipelines.
    Handles storage and retrieval of pipeline execution metadata,
    independent of Jenkins build numbers.
    """

    def __init__(self, metadata_dir: str = None, templates_dir: str = None):
        """
        Initialize the metadata manager.
        
        Args:
            metadata_dir: Directory to store metadata files, defaults to "./metadata"
            templates_dir: Directory containing pipeline templates, defaults to "./templates"
        """
        DEFAULT_METADATA_DIR = "metadata"
        self.metadata_dir = metadata_dir or DEFAULT_METADATA_DIR
        self.templates_dir = templates_dir or DEFAULT_TEMPLATES_DIR
        self.metadata_file = os.path.join(self.metadata_dir, "pipeline_metadata.json")
        
        # Ensure directories exist
        os.makedirs(self.metadata_dir, exist_ok=True)
        os.makedirs(self.templates_dir, exist_ok=True)
        
        # Initialize metadata store if it doesn't exist
        if not os.path.exists(self.metadata_file):
            self._initialize_metadata_store()
    
    def _initialize_metadata_store(self):
        """Initialize an empty metadata store."""
        initial_data = {
            "pipelines": {},
            "executions": [],
            "last_updated": datetime.now().isoformat()
        }
        self._save_metadata(initial_data)
        logger.info(f"Initialized new metadata store at {self.metadata_file}")
    
    def _load_metadata(self) -> Dict[str, Any]:
        """Load the metadata from disk."""
        try:
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            return {
                "pipelines": {},
                "executions": [],
                "last_updated": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error loading metadata: {e}")
            return {
                "pipelines": {},
                "executions": [],
                "last_updated": datetime.now().isoformat()
            }
    
    def _save_metadata(self, data: Dict[str, Any]):
        """Save the metadata to disk."""
        try:
            with open(self.metadata_file, 'w') as f:
                data["last_updated"] = datetime.now().isoformat()
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving metadata: {e}")
    
    def register_template(self, template_name: str, description: str = None) -> Dict[str, Any]:
        """
        Register a template with the metadata system.
        
        Args:
            template_name: Name of the template
            description: Optional description of the template
            
        Returns:
            Dictionary with template information
        """
        metadata = self._load_metadata()
        
        # Check if template exists in file system
        template_path = os.path.join(self.templates_dir, f"{template_name}.Jenkinsfile")
        if not os.path.exists(template_path):
            logger.error(f"Template file not found: {template_path}")
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        # Get template content for metadata
        try:
            with open(template_path, 'r') as f:
                template_content = f.read()
                # Extract description from template if not provided
                if not description and "// Description:" in template_content:
                    for line in template_content.split("\n"):
                        if line.strip().startswith("// Description:"):
                            description = line.strip()[15:].strip()
                            break
        except Exception as e:
            logger.error(f"Error reading template file: {e}")
            raise
        
        # Create or update pipeline entry
        pipeline_info = {
            "name": template_name,
            "description": description or "No description provided",
            "template_path": template_path,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "version": 1,
            "jenkins_jobs": []
        }
        
        # Update version if pipeline already exists
        if template_name in metadata["pipelines"]:
            existing_info = metadata["pipelines"][template_name]
            pipeline_info["version"] = existing_info.get("version", 0) + 1
            pipeline_info["created_at"] = existing_info.get("created_at", pipeline_info["created_at"])
            pipeline_info["jenkins_jobs"] = existing_info.get("jenkins_jobs", [])
        
        metadata["pipelines"][template_name] = pipeline_info
        self._save_metadata(metadata)
        
        logger.info(f"Registered template: {template_name} (v{pipeline_info['version']})")
        return pipeline_info
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all available templates.
        
        Returns:
            List of dictionaries with template information
        """
        # First, check the file system for templates
        template_files = []
        for file in os.listdir(self.templates_dir):
            if file.endswith(".Jenkinsfile"):
                template_name = file.replace('.Jenkinsfile', '')
                template_files.append(template_name)
        
        # Then, update metadata to ensure it's in sync with the file system
        metadata = self._load_metadata()
        
        # Add any new templates found in the file system
        for template_name in template_files:
            if template_name not in metadata["pipelines"]:
                try:
                    self.register_template(template_name)
                except Exception as e:
                    logger.error(f"Error registering template {template_name}: {e}")
        
        # Remove any templates that no longer exist in the file system
        for template_name in list(metadata["pipelines"].keys()):
            if template_name not in template_files:
                logger.info(f"Removing metadata for deleted template: {template_name}")
                metadata["pipelines"].pop(template_name)
        
        # Save updated metadata
        self._save_metadata(metadata)
        
        # Return the list of templates
        templates = []
        for name, info in metadata["pipelines"].items():
            templates.append({
                "name": name,
                "description": info.get("description", "No description provided"),
                "version": info.get("version", 1),
                "updated_at": info.get("updated_at", "Unknown")
            })
        
        return templates
    
    def deploy_pipeline(self, template_name: str, jenkins_job_name: str, server_name: str) -> Dict[str, Any]:
        """
        Register a pipeline deployment with the metadata system.
        
        Args:
            template_name: Name of the template to deploy
            jenkins_job_name: Name of the Jenkins job
            server_name: Name of the Jenkins server
            
        Returns:
            Dictionary with deployment information
        """
        metadata = self._load_metadata()
        
        # Ensure template exists
        if template_name not in metadata["pipelines"]:
            raise ValueError(f"Template not found: {template_name}")
        
        pipeline_info = metadata["pipelines"][template_name]
        
        # Create deployment entry
        deployment_id = str(uuid.uuid4())
        deployment_info = {
            "id": deployment_id,
            "template_name": template_name,
            "template_version": pipeline_info.get("version", 1),
            "jenkins_job_name": jenkins_job_name,
            "server_name": server_name,
            "deployed_at": datetime.now().isoformat(),
            "status": "deployed"
        }
        
        # Update pipeline info
        pipeline_info["jenkins_jobs"].append({
            "job_name": jenkins_job_name,
            "server_name": server_name,
            "deployment_id": deployment_id,
            "deployed_at": deployment_info["deployed_at"]
        })
        
        metadata["pipelines"][template_name] = pipeline_info
        self._save_metadata(metadata)
        
        logger.info(f"Deployed pipeline: {template_name} as {jenkins_job_name} on {server_name}")
        return deployment_info
    
    def record_execution(self, 
                      deployment_id: str = None,
                      template_name: str = None, 
                      jenkins_job_name: str = None, 
                      server_name: str = None,
                      build_number: int = None,
                      parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Record a pipeline execution in the metadata system.
        
        Args:
            deployment_id: ID of the deployment to execute
            template_name: Name of the template (required if deployment_id not provided)
            jenkins_job_name: Name of the Jenkins job (required if deployment_id not provided)
            server_name: Name of the Jenkins server (required if deployment_id not provided)
            build_number: Jenkins build number
            parameters: Parameters used for the execution
            
        Returns:
            Dictionary with execution information
        """
        metadata = self._load_metadata()
        
        # Generate a unique execution ID
        execution_id = str(uuid.uuid4())
        
        # Find deployment info if deployment_id not provided
        if not deployment_id and template_name and jenkins_job_name and server_name:
            if template_name in metadata["pipelines"]:
                pipeline_info = metadata["pipelines"][template_name]
                for job_info in pipeline_info.get("jenkins_jobs", []):
                    if (job_info["job_name"] == jenkins_job_name and 
                        job_info["server_name"] == server_name):
                        deployment_id = job_info["deployment_id"]
                        break
        
        # Create execution entry
        execution_info = {
            "id": execution_id,
            "deployment_id": deployment_id,
            "template_name": template_name,
            "jenkins_job_name": jenkins_job_name,
            "server_name": server_name,
            "build_number": build_number,
            "parameters": parameters or {},
            "started_at": datetime.now().isoformat(),
            "status": "running",
            "result": None,
            "duration": None,
            "finished_at": None
        }
        
        # Add to executions list
        metadata["executions"].append(execution_info)
        self._save_metadata(metadata)
        
        logger.info(f"Recorded execution: {execution_id} for {jenkins_job_name} #{build_number}")
        return execution_info
    
    def update_execution_status(self, execution_id: str, status: str, result: str = None,
                             console_output: str = None, duration: int = None) -> Dict[str, Any]:
        """
        Update the status of a pipeline execution.
        
        Args:
            execution_id: ID of the execution to update
            status: New status (running, complete, failed)
            result: Result of the execution (SUCCESS, FAILURE, etc.)
            console_output: Console output of the execution
            duration: Duration of the execution in milliseconds
            
        Returns:
            Updated execution information
        """
        metadata = self._load_metadata()
        
        # Find execution
        execution_info = None
        for i, exec_info in enumerate(metadata["executions"]):
            if exec_info["id"] == execution_id:
                execution_info = exec_info
                execution_idx = i
                break
        
        if not execution_info:
            raise ValueError(f"Execution not found: {execution_id}")
        
        # Update execution info
        execution_info["status"] = status
        
        if result:
            execution_info["result"] = result
        
        if duration:
            execution_info["duration"] = duration
        
        if status in ["complete", "failed"]:
            execution_info["finished_at"] = datetime.now().isoformat()
        
        # Save console output to separate file if provided
        if console_output:
            console_file = os.path.join(self.metadata_dir, f"console_{execution_id}.txt")
            try:
                with open(console_file, 'w') as f:
                    f.write(console_output)
                execution_info["console_file"] = console_file
            except Exception as e:
                logger.error(f"Error saving console output: {e}")
        
        # Update in metadata
        metadata["executions"][execution_idx] = execution_info
        self._save_metadata(metadata)
        
        logger.info(f"Updated execution status: {execution_id} to {status} ({result})")
        return execution_info
    
    def get_execution(self, execution_id: str) -> Dict[str, Any]:
        """
        Get information about a specific execution.
        
        Args:
            execution_id: ID of the execution
            
        Returns:
            Execution information
        """
        metadata = self._load_metadata()
        
        for exec_info in metadata["executions"]:
            if exec_info["id"] == execution_id:
                # Load console output if available
                if "console_file" in exec_info and os.path.exists(exec_info["console_file"]):
                    try:
                        with open(exec_info["console_file"], 'r') as f:
                            exec_info["console_output"] = f.read()
                    except Exception as e:
                        logger.error(f"Error reading console output: {e}")
                        exec_info["console_output"] = "Error reading console output"
                
                return exec_info
        
        raise ValueError(f"Execution not found: {execution_id}")
    
    def list_executions(self, template_name: str = None, limit: int = 10, 
                    status: str = None) -> List[Dict[str, Any]]:
        """
        List pipeline executions, optionally filtered by template or status.
        
        Args:
            template_name: Optional template name to filter by
            limit: Maximum number of executions to return
            status: Optional status to filter by
            
        Returns:
            List of execution information dictionaries
        """
        metadata = self._load_metadata()
        
        # Apply filters
        filtered_executions = metadata["executions"]
        
        if template_name:
            filtered_executions = [e for e in filtered_executions if e["template_name"] == template_name]
        
        if status:
            filtered_executions = [e for e in filtered_executions if e["status"] == status]
        
        # Sort by started_at (newest first)
        filtered_executions.sort(key=lambda e: e.get("started_at", ""), reverse=True)
        
        # Apply limit
        return filtered_executions[:limit]
    
    def get_console_output(self, execution_id: str) -> str:
        """
        Get console output for an execution.
        
        Args:
            execution_id: ID of the execution
            
        Returns:
            Console output as string
        """
        execution_info = self.get_execution(execution_id)
        
        if "console_output" in execution_info:
            return execution_info["console_output"]
        
        if "console_file" in execution_info and os.path.exists(execution_info["console_file"]):
            try:
                with open(execution_info["console_file"], 'r') as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Error reading console output: {e}")
        
        return "No console output available"
    
    def update_template(self, template_name: str, description: str) -> Dict[str, Any]:
        """
        Update a template's metadata with a new description and incremented version.
        
        Args:
            template_name: Name of the template to update
            description: New description for the template
            
        Returns:
            Dictionary with updated template information
        """
        metadata = self._load_metadata()
        
        # Check if template exists
        if template_name not in metadata["pipelines"]:
            raise ValueError(f"Template not found: {template_name}")
        
        # Update template information
        pipeline_info = metadata["pipelines"][template_name]
        pipeline_info["description"] = description
        pipeline_info["version"] = pipeline_info.get("version", 0) + 1
        pipeline_info["updated_at"] = datetime.now().isoformat()
        
        # Save metadata
        metadata["pipelines"][template_name] = pipeline_info
        self._save_metadata(metadata)
        
        logger.info(f"Updated template: {template_name} (v{pipeline_info['version']}) - {description}")
        
        # Update the description in the Jenkinsfile too
        try:
            template_path = os.path.join(self.templates_dir, f"{template_name}.Jenkinsfile")
            if os.path.exists(template_path):
                with open(template_path, 'r') as f:
                    content = f.read()
                
                # Update the description line if it exists
                new_content_lines = []
                description_updated = False
                
                for line in content.split("\n"):
                    if line.strip().startswith("// Description:"):
                        new_content_lines.append(f"// Description: {description}")
                        description_updated = True
                    else:
                        new_content_lines.append(line)
                
                # Add description if it wasn't found
                if not description_updated and len(new_content_lines) > 0:
                    if new_content_lines[0].startswith("//"):
                        new_content_lines.insert(1, f"// Description: {description}")
                    else:
                        new_content_lines.insert(0, f"// Description: {description}")
                
                # Write updated content
                with open(template_path, 'w') as f:
                    f.write("\n".join(new_content_lines))
        except Exception as e:
            logger.error(f"Error updating template description in file: {e}")
        
        return pipeline_info
    
    def increment_template_version(self, template_name: str) -> Dict[str, Any]:
        """
        Increment a template's version number without changing its description.
        
        Args:
            template_name: Name of the template
            
        Returns:
            Dictionary with updated template information
        """
        metadata = self._load_metadata()
        
        # Check if template exists
        if template_name not in metadata["pipelines"]:
            raise ValueError(f"Template not found: {template_name}")
        
        # Update template information
        pipeline_info = metadata["pipelines"][template_name]
        pipeline_info["version"] = pipeline_info.get("version", 0) + 1
        pipeline_info["updated_at"] = datetime.now().isoformat()
        
        # Save metadata
        metadata["pipelines"][template_name] = pipeline_info
        self._save_metadata(metadata)
        
        logger.info(f"Incremented template version: {template_name} (v{pipeline_info['version']})")
        return pipeline_info


# Always use Redis implementation for metadata management
if not REDIS_AVAILABLE:
    raise ImportError("Redis package is required for MiladyOS. Please install with 'pip install redis'")

# Initialize the Redis-based metadata manager
metadata_manager = RedkaMetadataManager()
logger.info("Using Redis-based metadata manager")