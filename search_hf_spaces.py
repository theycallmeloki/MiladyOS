#!/usr/bin/env python3
"""
Scrape all Hugging Face MCP Server Docker containers
"""

import requests
import json
import time
from typing import List, Dict
from datetime import datetime


def parse_link_header(link_header: str) -> Dict[str, str]:
    """
    Parse the Link header to extract pagination URLs.
    
    Args:
        link_header: The Link header value from the response
        
    Returns:
        Dictionary mapping rel types to URLs
    """
    links = {}
    if not link_header:
        return links
    
    # Parse each link
    for link in link_header.split(','):
        link = link.strip()
        if ';' in link:
            url_part, rel_part = link.split(';', 1)
            url = url_part.strip('<>')
            rel_match = rel_part.split('=')[1].strip('"')
            links[rel_match] = url
    
    return links


def fetch_all_spaces_recursive(
    filter_term: str = "mcp-server",
    full: bool = False,
    delay: float = 0.5,
    fetch_details: bool = True
) -> List[Dict]:
    """
    Recursively fetch ALL spaces matching the filter from Hugging Face.
    Handles pagination automatically.
    
    Args:
        filter_term: Filter term (e.g., "mcp-server")
        full: Whether to fetch additional space data
        delay: Delay between requests to avoid rate limiting
        fetch_details: Whether to fetch detailed information for each space
        
    Returns:
        List of all space dictionaries
    """
    base_url = "https://huggingface.co/api/spaces"
    all_spaces = []
    page = 0  # Start at page 0
    
    print(f"Fetching all spaces with filter '{filter_term}'...")
    
    while True:
        # Build params with filter and page
        params = {
            "filter": filter_term,
            "p": page,
            "limit": 100  # Try to get more per page
        }
        
        if full:
            params["full"] = "true"
        
        try:
            print(f"  Fetching page {page}...")
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            
            spaces_batch = response.json()
            
            # If no results or empty batch, we're done
            if not spaces_batch or len(spaces_batch) == 0:
                print(f"  No more results on page {page}")
                break
                
            all_spaces.extend(spaces_batch)
            print(f"  Retrieved {len(spaces_batch)} spaces (total: {len(all_spaces)})")
            
            # If we got fewer than expected, might be the last page
            if len(spaces_batch) < 30:  # HF seems to return ~30 per page
                print(f"  Got only {len(spaces_batch)} spaces, likely last page")
                # Try one more page to be sure
                page += 1
                time.sleep(delay)
                continue
            
            # Move to next page
            page += 1
            time.sleep(delay)  # Rate limiting
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching spaces on page {page}: {e}")
            break
    
    print(f"\nTotal spaces found: {len(all_spaces)}")
    
    # If fetch_details is True, get detailed info for each space
    if fetch_details and all_spaces:
        print("\nFetching detailed information for each space...")
        detailed_spaces = []
        
        for idx, space in enumerate(all_spaces):
            space_id = space.get('id')
            if not space_id:
                detailed_spaces.append(space)
                continue
                
            try:
                # Fetch detailed space info
                detail_url = f"https://huggingface.co/api/spaces/{space_id}"
                response = requests.get(detail_url)
                response.raise_for_status()
                
                detailed_data = response.json()
                # Merge with basic data
                space.update(detailed_data)
                detailed_spaces.append(space)
                
                if (idx + 1) % 10 == 0:
                    print(f"  Fetched details for {idx + 1}/{len(all_spaces)} spaces...")
                
                # Small delay to avoid rate limiting
                time.sleep(delay * 0.5)
                
            except Exception as e:
                print(f"  Warning: Could not fetch details for {space_id}: {e}")
                detailed_spaces.append(space)
        
        print(f"  Completed fetching details for {len(detailed_spaces)} spaces")
        return detailed_spaces
    
    return all_spaces


def extract_docker_info(space: Dict) -> Dict:
    """
    Extract Docker-related information from a space.
    
    Args:
        space: Space dictionary
        
    Returns:
        Dictionary with Docker information
    """
    docker_info = {}
    
    # Check if it's a Docker space
    if space.get('sdk') == 'docker':
        docker_info['is_docker_space'] = True
        docker_info['requires_gpu'] = any('gpu' in tag.lower() for tag in space.get('tags', []))
        
        # Try to extract actual Docker image from space config
        space_id = space.get('id', '')
        
        # Check for cardData which might contain Docker info
        card_data = space.get('cardData', {})
        if isinstance(card_data, dict):
            # Look for docker info in various places
            docker_config = card_data.get('docker', {})
            if docker_config:
                docker_info['docker_config'] = docker_config
            
            # Check app_file or other Docker-related fields
            app_file = card_data.get('app_file')
            if app_file:
                docker_info['app_file'] = app_file
        
        # Default Docker image URL if not found in config
        if space_id and 'docker_image' not in docker_info:
            docker_info['docker_image'] = f"registry.hf.space/{space_id.replace('/', '-')}:latest"
        
        # Check for runtime info
        runtime = space.get('runtime', {})
        if runtime:
            hardware_current = runtime.get('hardware', {}).get('current')
            docker_info['runtime'] = {
                'stage': runtime.get('stage'),
                'hardware': hardware_current,
                'gpu_enabled': hardware_current and hardware_current.lower() != 'cpu'
            }
    
    return docker_info


def main():
    """Main function to scrape all MCP Docker containers."""
    # Fetch all spaces with the mcp-server filter
    spaces = fetch_all_spaces_recursive(
        filter_term="mcp-server",
        full=False,
        fetch_details=False  # We'll fetch details only for Docker spaces
    )
    
    # Filter Docker spaces first
    docker_spaces = [s for s in spaces if s.get('sdk') == 'docker']
    print(f"\nFound {len(docker_spaces)} Docker spaces to fetch details for...")
    
    # Fetch details only for Docker spaces
    if docker_spaces:
        print("\nFetching detailed information for Docker spaces...")
        for idx, space in enumerate(docker_spaces):
            space_id = space.get('id')
            if not space_id:
                continue
                
            try:
                detail_url = f"https://huggingface.co/api/spaces/{space_id}"
                response = requests.get(detail_url)
                response.raise_for_status()
                
                detailed_data = response.json()
                # Update the space with detailed data
                space.update(detailed_data)
                
                if (idx + 1) % 10 == 0:
                    print(f"  Fetched details for {idx + 1}/{len(docker_spaces)} Docker spaces...")
                
                time.sleep(0.25)  # Rate limiting
                
            except Exception as e:
                print(f"  Warning: Could not fetch details for {space_id}: {e}")
        
        print(f"  Completed fetching details for Docker spaces")
    
    # Extract and enhance Docker containers
    docker_containers = []
    for space in docker_spaces:
        docker_info = extract_docker_info(space)
        if docker_info:
            docker_containers.append({
                    'id': space.get('id'),
                    'docker_image': docker_info.get('docker_image'),
                    'created_at': space.get('createdAt'),
                    'last_modified': space.get('lastModified'),
                    'likes': space.get('likes', 0),
                    'runtime': docker_info.get('runtime', {}),
                    'tags': space.get('tags', []),
                    'requires_gpu': docker_info.get('requires_gpu', False),
                    'docker_config': docker_info.get('docker_config', {}),
                    'app_file': docker_info.get('app_file')
                })
    
    # Save results
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'total_spaces': len(spaces),
        'docker_containers': docker_containers,
        'docker_count': len(docker_containers)
    }
    
    with open('mcp_docker_containers.json', 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n=== Scraping Complete ===")
    print(f"Total MCP spaces: {len(spaces)}")
    print(f"Docker containers: {len(docker_containers)}")
    print(f"Output saved to: mcp_docker_containers.json")
    
    # Print Docker images for quick reference
    print(f"\nDocker images found:")
    for container in docker_containers:
        print(f"  {container['docker_image']}")


if __name__ == "__main__":
    main()