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
from pathlib import Path

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
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type to use",
)
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind the server to (only used with sse transport)",
)
@click.option(
    "--port",
    default=6000,
    type=int,
    help="Port to bind the server to (only used with sse transport)",
)
@click.option(
    "--base-path",
    default="",
    help="Base path for URL construction (only used with sse transport)",
)
def mcp(all_tools, templates_dir, redis_host, redis_port, transport, host, port, base_path):
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

    from miladyos_mcp import MiladyOSToolServer
    
    # Create and run the server
    # Make sure execute_command is always included (since it's not a template-based tool)
    default_tools = Config.DEFAULT_TOOLS.copy()
    if "execute_command" not in default_tools:
        default_tools.append("execute_command")
    
    supported_tools = None if all_tools else default_tools
    server = MiladyOSToolServer(supported_tools=supported_tools)
    
    # Run with the appropriate transport
    if transport == "sse":
        logger.info(f"Starting MCP server with SSE transport on {host}:{port}")
        server.run_sse(host=host, port=port, base_path=base_path)
        return 0
    else:
        logger.info("Starting MCP server with stdio transport")
        return anyio.run(server.run_stdio)




@cli.command()
@click.argument("template_name")
@click.option("--job-name", help="Optional pipeline repo name (defaults to template name)")
def deploy(template_name, job_name):
    """Deploy a template as a woodpecker pipeline repo (forge + activate)."""
    from miladyos_metadata import metadata_manager
    from woodpecker_client import WoodpeckerClient
    import asyncio

    job_name = job_name or template_name

    async def deploy_async():
        try:
            template_path = Path(template_name)
            if not template_path.exists():
                template_path = Path(os.getenv("TEMPLATES_DIR", "templates")) / f"{template_name}.yml"
            if not template_path.exists():
                logger.error(f"Template not found: {template_name}")
                return 1

            client = WoodpeckerClient()
            client.forge_create_repo(job_name)
            repo = f"{client.forge_user}/{job_name}"
            client.forge_upsert_file(repo, ".woodpecker.yml", template_path.read_text())
            client.repo_id(repo)  # idempotent activation

            # Register deployment in metadata system
            deployment_info = metadata_manager.deploy_pipeline(
                template_name,
                job_name,
                repo
            )

            logger.info(f"Successfully deployed template {template_name} as pipeline repo {repo}")
            logger.info(f"Deployment ID: {deployment_info['id']}")
            return 0
        except Exception as e:
            logger.error(f"Error deploying template: {e}")
            return 1

    return asyncio.run(deploy_async())


@cli.command()
@click.argument("template_name")
@click.option("--repo", "repo_name", help="Pipeline repo to run in (default: milady/<template>)")
@click.option("--no-stream", is_flag=True, help="Don't print console output")
def run(template_name, repo_name, no_stream):
    """Run a pipeline template on the local woodpecker agent."""
    from miladyos_metadata import metadata_manager
    from woodpecker_client import WoodpeckerClient
    import asyncio

    stream_output = not no_stream

    async def run_async():
        try:
            template_path = Path(template_name)
            if not template_path.exists():
                template_path = Path(os.getenv("TEMPLATES_DIR", "templates")) / f"{template_name}.yml"
            if not template_path.exists():
                logger.error(f"Template not found: {template_name}")
                return 1

            client = WoodpeckerClient()
            repo = repo_name or f"{client.forge_user}/{template_name}"
            result = await asyncio.to_thread(client.run_content, repo, template_path.read_text())

            # Record execution in metadata system
            execution_info = metadata_manager.record_execution(
                template_name=template_name,
                pipeline_name=template_name,
                repo_name=repo,
                pipeline_id=result["pipeline_id"],
            )

            logger.info(f"Ran template {template_name} in {repo} (pipeline #{result['pipeline_id']})")
            logger.info(f"Execution ID: {execution_info['id']}")

            if stream_output:
                print(result["console"])
                print(f"\nStatus: {result['status']}")

            return 0 if result["success"] else 1
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
                for file in sorted(os.listdir(templates_dir)):
                    if file.endswith(".yml"):
                        template_name = file.replace(".yml", '')

                        # Try to extract description from file
                        description = "No description provided"
                        try:
                            with open(os.path.join(templates_dir, file), 'r') as f:
                                content = f.read()
                                for line in content.split("\n"):
                                    if line.strip().startswith("# Description:"):
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
@click.argument("template_name")
def view_template(template_name):
    """View content of a template with line numbers."""
    import os

    try:
        template_path = Path(template_name)
        if not template_path.exists():
            template_path = Path(os.getenv("TEMPLATES_DIR", "templates")) / f"{template_name}.yml"
        if not template_path.exists():
            raise FileNotFoundError(template_name)

        logger.info(f"Template path: {template_path}")
        logger.info("")

        for line_num, line_content in enumerate(template_path.read_text().split("\n"), start=1):
            print(f"{line_num:4d} | {line_content}")

        return 0
    except FileNotFoundError:
        logger.error(f"Template {template_name} not found")
        return 1
    except Exception as e:
        logger.error(f"Error viewing template: {e}")
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