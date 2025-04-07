#!/usr/bin/env python3
"""
MiladyOS - AI for Hardware Infrastructure
Main entry point for MiladyOS CLI and MCP server
"""

import sys
import logging
import click
import colorlog
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logger
logger = colorlog.getLogger("miladyos")
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(levelname)s%(reset)s: %(message)s"
))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


@click.group()
def cli():
    """MiladyOS CLI and MCP server for hardware infrastructure."""
    pass


@cli.command()
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
def mcp(all_tools, templates_dir, metadata_dir, redis_host, redis_port):
    """Run the MiladyOS MCP server.

    Provides MCP-compatible tools for MiladyOS pipeline management.
    """
    from miladyos_mcp import Config
    import anyio
    import os
    
    # Set environment variables for Redis configuration
    os.environ["REDIS_HOST"] = redis_host
    os.environ["REDIS_PORT"] = str(redis_port)
    
    # Configure MCP
    Config.TEMPLATES_DIR = templates_dir
    Config.METADATA_DIR = metadata_dir
    
    # Set up metadata manager with the right directories
    from miladyos_mcp import MiladyOSToolServer
    
    # Create and run the server
    # Make sure execute_command is always included (since it's not a template-based tool)
    default_tools = Config.DEFAULT_TOOLS.copy()
    if "execute_command" not in default_tools:
        default_tools.append("execute_command")
    
    supported_tools = None if all_tools else default_tools
    server = MiladyOSToolServer(supported_tools=supported_tools)
    
    # Run with stdio transport
    return anyio.run(server.run_stdio)




@cli.command()
@click.argument("template_name")
@click.option("--job-name", help="Optional job name (defaults to template name)")
@click.option("--server", default="default", help="Jenkins server to use")
def deploy(template_name, job_name, server):
    """Deploy a template to Jenkins."""
    from miladyos_metadata import metadata_manager
    from miladyos_mcp import JenkinsUtils
    import asyncio
    
    job_name = job_name or template_name
    
    async def deploy_async():
        try:
            # Connect to Jenkins
            jenkins_server = JenkinsUtils.connect_to_jenkins(server)
            
            # Get Jenkinsfile content
            jenkinsfile_content = JenkinsUtils.get_jenkinsfile_content(template_name)
            
            # Delete existing job if it exists
            await JenkinsUtils.delete_job_if_exists(jenkins_server, job_name)
            
            # Create new job
            await JenkinsUtils.create_job(jenkins_server, job_name, jenkinsfile_content)
            
            # Register deployment in metadata system
            deployment_info = metadata_manager.deploy_pipeline(
                template_name,
                job_name,
                server
            )
            
            logger.info(f"Successfully deployed template {template_name} as job {job_name} on server {server}")
            logger.info(f"Deployment ID: {deployment_info['id']}")
            return 0
        except Exception as e:
            logger.error(f"Error deploying template: {e}")
            return 1
    
    return asyncio.run(deploy_async())


@cli.command()
@click.argument("template_name")
@click.option("--job-name", help="Optional job name (defaults to template name)")
@click.option("--server", default="default", help="Jenkins server to use")
@click.option("--no-stream", is_flag=True, help="Don't stream console output")
def run(template_name, job_name, server, no_stream):
    """Run a pipeline template on Jenkins."""
    from miladyos_metadata import metadata_manager
    from miladyos_mcp import JenkinsUtils
    import asyncio
    
    job_name = job_name or template_name
    stream_output = not no_stream
    
    async def run_async():
        try:
            # Connect to Jenkins
            jenkins_server = JenkinsUtils.connect_to_jenkins(server)
            
            # Check if job exists
            if not jenkins_server.job_exists(job_name):
                logger.info(f"Job {job_name} does not exist. Deploying it first.")
                
                # Get Jenkinsfile content
                jenkinsfile_content = JenkinsUtils.get_jenkinsfile_content(template_name)
                
                # Create the job
                await JenkinsUtils.create_job(jenkins_server, job_name, jenkinsfile_content)
                
                # Register deployment in metadata system
                metadata_manager.deploy_pipeline(
                    template_name,
                    job_name,
                    server
                )
            
            # Start the job
            job_info = await JenkinsUtils.start_jenkins_job(jenkins_server, job_name)
            
            if job_info["status"] == "started":
                build_number = job_info["build_number"]
                
                # Record execution in metadata system
                execution_info = metadata_manager.record_execution(
                    template_name=template_name,
                    jenkins_job_name=job_name,
                    server_name=server,
                    build_number=build_number
                )
                
                logger.info(f"Started job {job_name} build #{build_number}")
                logger.info(f"Execution ID: {execution_info['id']}")
                
                # Stream job output if requested
                if stream_output:
                    logger.info("Streaming console output...")
                    result = await JenkinsUtils.stream_job_output(jenkins_server, job_name, build_number)
                    
                    # Update execution status in metadata system
                    metadata_manager.update_execution_status(
                        execution_info["id"],
                        "complete" if result["status"] == "SUCCESS" else "failed",
                        result["status"],
                        result["console_output"],
                        jenkins_server.get_build_info(job_name, build_number).get("duration")
                    )
                    
                    logger.info(f"Job completed with status: {result['status']}")
                    return 0 if result["status"] == "SUCCESS" else 1
                
                return 0
            else:
                logger.info(f"Job {job_name} is queued. Queue number: {job_info['queue_number']}")
                return 0
        except Exception as e:
            logger.error(f"Error running template: {e}")
            return 1
    
    return asyncio.run(run_async())


@cli.command()
def list_templates():
    """List all available templates."""
    from miladyos_metadata import metadata_manager
    import os
    
    try:
        # Check if templates directory exists
        templates_dir = os.getenv("TEMPLATES_DIR", "templates")
        if not os.path.exists(templates_dir):
            logger.warning(f"Templates directory {templates_dir} does not exist")
            os.makedirs(templates_dir, exist_ok=True)
            logger.info(f"Created templates directory {templates_dir}")
            return 0
            
        # Try to get templates from metadata manager
        try:
            templates = metadata_manager.list_templates()
        except Exception as e:
            logger.error(f"Error from metadata manager: {e}")
            # Fallback to filesystem directly
            templates = []
            try:
                for file in os.listdir(templates_dir):
                    if file.endswith(".Jenkinsfile"):
                        template_name = file.replace('.Jenkinsfile', '')
                        
                        # Try to extract description from file
                        description = "No description provided"
                        try:
                            with open(os.path.join(templates_dir, file), 'r') as f:
                                content = f.read()
                                for line in content.split("\n"):
                                    if line.strip().startswith("// Description:"):
                                        description = line.strip()[15:].strip()
                                        break
                        except Exception:
                            pass
                            
                        templates.append({
                            "name": template_name,
                            "description": description,
                            "version": 1
                        })
            except Exception as fs_error:
                logger.error(f"Error reading templates directory: {fs_error}")
                return 1
        
        if not templates:
            logger.info("No templates found")
        else:
            logger.info(f"Found {len(templates)} templates:")
            for template in templates:
                logger.info(f"  - {template['name']} (v{template.get('version', 1)}): {template.get('description', 'No description')}")
        
        return 0
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        return 1


@cli.command()
@click.option("--template", help="Filter by template name")
@click.option("--limit", default=10, help="Maximum number of runs to show")
@click.option("--status", type=click.Choice(["running", "complete", "failed"]), help="Filter by status")
def list_runs(template, limit, status):
    """List pipeline runs from the metadata system."""
    from miladyos_metadata import metadata_manager
    
    try:
        executions = metadata_manager.list_executions(template, limit, status)
        
        if not executions:
            logger.info("No pipeline runs found")
        else:
            logger.info(f"Found {len(executions)} pipeline runs:")
            for execution in executions:
                status_str = execution.get("status", "unknown")
                result_str = f" ({execution.get('result', 'unknown')})" if execution.get("result") else ""
                build_str = f" #{execution.get('build_number')}" if execution.get("build_number") else ""
                
                logger.info(f"  - {execution['id']}: {execution['template_name']}{build_str} - {status_str}{result_str}")
        
        return 0
    except Exception as e:
        logger.error(f"Error listing pipeline runs: {e}")
        return 1


def main():
    """Main entry point for MiladyOS CLI."""
    return cli()


if __name__ == "__main__":
    sys.exit(main())