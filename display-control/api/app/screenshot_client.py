#!/usr/bin/env python3
import argparse
import requests
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Get a screenshot from a display")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--display", default="device-0-display", help="Display name")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality (1-100)")
    parser.add_argument("--full", action="store_true", help="Capture full page")
    parser.add_argument("--output", help="Output file path (defaults to display_name_timestamp.jpg)")
    args = parser.parse_args()
    
    # Generate default output filename if not provided
    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"{args.display}_{timestamp}.jpg"
    
    # Build the URL
    url = f"{args.api}/displays/{args.display}/screenshot"
    params = {
        "quality": args.quality,
        "full_page": args.full
    }
    
    print(f"Getting screenshot from {url}")
    try:
        response = requests.get(url, params=params, stream=True)
        
        if response.status_code == 200:
            with open(args.output, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            
            print(f"Screenshot saved to {args.output}")
            print(f"Size: {os.path.getsize(args.output) / 1024:.1f} KB")
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()