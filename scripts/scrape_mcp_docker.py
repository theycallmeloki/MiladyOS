#!/usr/bin/env python3
"""
Scrape ALL Hugging Face MCP Server spaces and fetch actual Docker details.
"""

import requests
import json
import time
from datetime import datetime


def parse_link_header(link_header):
    """Parse the Link header to extract pagination URLs."""
    links = {}
    if not link_header:
        return links
    
    for link in link_header.split(','):
        link = link.strip()
        if ';' in link:
            url_part, rel_part = link.split(';', 1)
            url = url_part.strip('<>')
            rel_match = rel_part.split('=')[1].strip('"')
            links[rel_match] = url
    
    return links


def fetch_space_details(space_id):
    """Fetch detailed information for a space including Docker details."""
    try:
        url = f"https://huggingface.co/api/spaces/{space_id}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"    Error fetching details for {space_id}: {e}")
        return None


def main():
    """Fetch all MCP server spaces with full Docker details."""
    base_url = "https://huggingface.co/api/spaces"
    all_spaces = []
    
    # Initial request
    params = {
        "filter": "mcp-server",
        "limit": 100,
        "full": "true"  # Try to get more info in initial request
    }
    
    print("Fetching MCP server spaces...")
    
    next_url = None
    page = 0
    
    # First, get all spaces with pagination
    max_pages = 10  # Safety limit
    while page < max_pages:
        try:
            if next_url:
                response = requests.get(next_url)
            else:
                response = requests.get(base_url, params=params)
            
            response.raise_for_status()
            spaces_batch = response.json()
            
            if not spaces_batch:
                print("  No more spaces found")
                break
            
            all_spaces.extend(spaces_batch)
            print(f"  Page {page}: {len(spaces_batch)} spaces (total: {len(all_spaces)})")
            
            # Check for next page
            link_header = response.headers.get('Link', '')
            print(f"  Link header: {link_header[:100] if link_header else 'None'}")  # Debug
            
            links = parse_link_header(link_header)
            
            if 'next' in links:
                next_url = links['next']
                page += 1
                time.sleep(0.5)
            else:
                print("  No next link found, stopping")
                break
                
        except Exception as e:
            print(f"Error: {e}")
            break
    
    if page >= max_pages:
        print(f"  Reached max pages limit ({max_pages})")
    
    print(f"\nFetching detailed information for first 5 spaces (out of {len(all_spaces)})...")
    
    # Now fetch details for each space (limit to 5 for testing)
    docker_containers = []
    for idx, space in enumerate(all_spaces[:5]):
        space_id = space.get('id')
        if not space_id:
            continue
        
        # Fetch full details
        details = fetch_space_details(space_id)
        if details:
            # Extract all information from the detailed response
            docker_info = {
                'id': space_id,
                'sdk': details.get('sdk', 'unknown'),
                'runtime': details.get('runtime', {}),
                'cardData': details.get('cardData', {}),
                'likes': details.get('likes', 0),
                'created_at': details.get('createdAt'),
                'last_modified': details.get('lastModified'),
                'tags': details.get('tags', []),
                'subdomain': details.get('subdomain'),
                'host': details.get('host')
            }
            
            # Look for Docker-related information in the response
            # Check if there's Docker info in cardData
            if 'cardData' in details and isinstance(details['cardData'], dict):
                if 'docker' in details['cardData']:
                    docker_info['docker_config'] = details['cardData']['docker']
            
            # Store the full details so we can analyze what HF actually provides
            docker_containers.append(docker_info)
        
        if (idx + 1) % 10 == 0:
            print(f"  Processed {idx + 1}/{len(all_spaces)} spaces...")
        
        time.sleep(0.25)  # Rate limiting
    
    # Save results
    output = {
        'timestamp': datetime.now().isoformat(),
        'total_spaces': len(all_spaces),
        'docker_containers': docker_containers
    }
    
    import os
    output_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'mcp_docker_images.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nTotal spaces: {len(all_spaces)}")
    print(f"Docker containers with details: {len(docker_containers)}")
    print(f"Saved to {output_path}")
    
    # Show what we actually found
    print("\nExample spaces found:")
    for container in docker_containers[:3]:
        print(f"\n  Space: {container['id']}")
        print(f"  SDK: {container['sdk']}")
        print(f"  Host: {container.get('host', 'N/A')}")
        if 'docker_config' in container:
            print(f"  Docker config: {container['docker_config']}")


if __name__ == "__main__":
    main()