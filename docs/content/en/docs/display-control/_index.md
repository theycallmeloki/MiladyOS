---
title: "Display Control System"
linkTitle: "Display Control"
weight: 50
description: >
  Remote display management and control capabilities
---

## Overview

The Display Control system provides remote management capabilities for displays and visual output across the MiladyOS cluster.

## Architecture

### API Service
- **Location**: `display-control/api/`
- **Main Module**: `app/main.py`
- **Test Client**: `app/test_client.py`
- **Screenshot Client**: `app/screenshot_client.py`

### Display Service
- **Location**: `display-control/display/`
- **Main Module**: `app/display.py`

## Features

### Remote Display Management
- Control displays across the cluster
- Centralized display configuration
- Real-time display status monitoring

### Screenshot Capabilities
- Capture screenshots from remote displays
- Programmatic screenshot API
- Batch screenshot operations

### API Endpoints
- RESTful API for display operations
- WebSocket support for real-time updates
- Authentication and authorization

## Quick Start

### Installation
```bash
cd display-control
pip install -r api/requirements.txt
pip install -r display/requirements.txt
```

### Running with Docker Compose
```bash
cd display-control
docker-compose up -d
```

### API Usage Example
```python
from display-control.api.app.test_client import TestClient

client = TestClient()
# Control display operations
client.set_display_mode('1920x1080')
client.capture_screenshot()
```

## Configuration

### Environment Variables
- `DISPLAY_API_HOST` - API server host (default: localhost)
- `DISPLAY_API_PORT` - API server port (default: 8000)
- `DISPLAY_SERVICE_HOST` - Display service host

### Docker Compose Setup
The system includes a pre-configured `docker-compose.yml` for easy local development and testing.

## API Reference

### Display Operations
- `GET /displays` - List available displays
- `POST /displays/{id}/configure` - Configure display settings
- `GET /displays/{id}/status` - Get display status
- `POST /displays/{id}/screenshot` - Capture screenshot

### WebSocket Events
- `display.status_changed` - Display status updates
- `display.screenshot_ready` - Screenshot completion events

## Integration with MiladyOS

The Display Control system integrates with the broader MiladyOS infrastructure:

- **Service Discovery** - Automatic registration with MiladyOS services
- **Authentication** - Integration with NFT-auth service
- **Monitoring** - Metrics exported to Prometheus
- **Logging** - Centralized logging via MiladyOS infrastructure

## Troubleshooting

### Common Issues
- Display service not responding
- Screenshot capture failures
- Network connectivity issues

### Debug Commands
```bash
# Check service status
docker-compose ps

# View logs
docker-compose logs display-api
docker-compose logs display-service

# Test API connectivity
python app/test_client.py
```