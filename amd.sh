#!/bin/bash

# Define keys for each field
keys=( "JENKINS_ADMIN_ID" "timestamp" "name" "bus_id" "driver_version" "temperature_edge" "utilization_gpu" "memory_total" "memory_free" "memory_used")

# Define the filebrowser URL and credentials
FILEBROWSER_URL="http://localhost:7331"
FILEBROWSER_USERNAME="admin"
FILEBROWSER_PASSWORD="admin"
UPLOAD_PATH="metrics"

# Function to send data to the filebrowser
send_data_to_filebrowser() {
    local payload="$1"
    local gpu_id="$2"
    local timestamp=$(date +%s)
    local filename="gpu_data_${gpu_id}_${timestamp}.json"
    
    # Write payload to a temporary file
    echo "$payload" > "/tmp/$filename"
    
    # Login to filebrowser and get the auth token (only if not already authenticated)
    if [ -z "$AUTH_TOKEN" ]; then
        echo "Attempting to login to filebrowser..."
        AUTH_TOKEN=$(curl -s -X POST "${FILEBROWSER_URL}/api/login" -d "{\"username\":\"${FILEBROWSER_USERNAME}\",\"password\":\"${FILEBROWSER_PASSWORD}\"}" -H "Content-Type: application/json")
        echo "Login response received."
        
        if [ -z "$AUTH_TOKEN" ]; then
            echo "Failed to authenticate with filebrowser. Auth token is empty."
            rm "/tmp/$filename"
            return 1
        fi
        echo "Successfully authenticated."
    fi
    
    echo "Attempting to upload file..."
    
    # Upload file to filebrowser
    local upload_response=$(curl -s -X POST "${FILEBROWSER_URL}/api/resources${UPLOAD_PATH}/${filename}" \
         -H "X-Auth: ${AUTH_TOKEN}" \
         -H "Content-Type: application/octet-stream" \
         --data-binary "@/tmp/$filename")
    
    echo "Upload response: $upload_response"
    
    if [ -z "$upload_response" ]; then
        echo "Failed to upload file to filebrowser. No response received."
    elif [[ "$upload_response" == *"error"* ]]; then
        echo "Failed to upload file to filebrowser. Error in response."
    else
        echo "File uploaded successfully."
    fi
    
    # Remove temporary file
    rm "/tmp/$filename"
}

# Function to trim whitespace
trim() {
    local var="$*"
    # Remove leading whitespace characters
    var="${var#"${var%%[![:space:]]*}"}"
    # Remove trailing whitespace characters
    var="${var%"${var##*[![:space:]]}"}"   
    printf '%s' "$var"
}

# Check rocm-smi version and capabilities
ROCM_VERSION=$(rocm-smi --version 2>&1 | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" || echo "unknown")
echo "Detected ROCm version: $ROCM_VERSION"

# Log the output format for debugging
echo "Testing rocm-smi output format..."
rocm-smi --showdriverversion --csv | head -n 3 > /tmp/rocm_format.txt
echo "Format sample saved to /tmp/rocm_format.txt"

# Collect basic information first (more reliable)
GPU_INFO=$(rocm-smi --json)
DRIVER_VERSION=$(echo "$GPU_INFO" | grep -o '"Driver version".*' | head -1 | cut -d '"' -f 4 || echo "Unknown")

# Collect and process AMD GPU data using rocm-smi
# Using separate options to make it more robust across different versions
rocm-smi --showtemp --showuse --showmemuse --csv | \
while IFS= read -r line
do
    # Print raw line for debugging
    echo "RAW: $line" >> /tmp/amd_gpu_raw.log
    
    # Skip headers and empty lines
    if [[ $line != *"ROCm"* && $line != *"GPU"* && $line != "=" && -n "$line" ]]; then
        # Extract GPU card number or bus ID
        if [[ $line == *"GPU"* ]]; then
            # Format might be "GPU[0]" or similar
            bus_id=$(echo "$line" | grep -o "GPU\[[0-9]\+\]" || echo "$line" | awk -F, '{print $1}' | tr -d '[:space:]')
        else
            # Try to get PCI bus ID format
            bus_id=$(echo "$line" | awk -F, '{print $1}' | tr -d '[:space:]' || echo "GPU0")
        fi
        
        name="AMD GPU"
        
        # Try different approaches to get temperature
        temp=$(echo "$line" | grep -o "[0-9]\+\.* *C" | grep -o "[0-9]\+" || echo "0")
        if [ "$temp" = "0" ]; then
            temp=$(echo "$line" | awk -F, '{for(i=1;i<=NF;i++) if($i ~ /[0-9]+.?[0-9]* *C/) print $i}' | grep -o "[0-9]\+" || echo "N/A")
        fi
        
        # Try to get GPU usage percentage
        gpu_use=$(echo "$line" | grep -o "[0-9]\+%" | sed 's/%//' || echo "N/A")
        if [ "$gpu_use" = "N/A" ]; then
            gpu_use=$(echo "$line" | awk -F, '{for(i=1;i<=NF;i++) if($i ~ /[0-9]+%/) print $i}' | grep -o "[0-9]\+" || echo "N/A")
        fi
        
        # Use pre-collected driver version as it's more reliable
        driver_version="$DRIVER_VERSION"
        
        # Memory info is highly version dependent, try multiple approaches
        mem_total=$(echo "$line" | grep -o "[0-9]\+ *MB" | head -1 | grep -o "[0-9]\+" || echo "100")
        mem_used=$(echo "$line" | grep -o "[0-9]\+%" | head -1 || echo "N/A")
        mem_free=$(echo "$line" | grep -o "[0-9]\+%" | tail -1 || echo "N/A")
        
        # Create timestamp
        timestamp=$(date +"%Y/%m/%d %H:%M:%S")
        
        # Format data as JSON
        json_data="{"
        json_data+="\"JENKINS_ADMIN_ID\": \"$JENKINS_ADMIN_ID\","
        json_data+="\"timestamp\": \"$timestamp\","
        json_data+="\"name\": \"$name\","
        json_data+="\"bus_id\": \"$bus_id\","
        json_data+="\"driver_version\": \"$driver_version\","
        json_data+="\"temperature_edge\": \"$temp C\","
        json_data+="\"utilization_gpu\": \"$gpu_use %\","
        json_data+="\"memory_total\": \"$mem_total\","
        json_data+="\"memory_free\": \"$mem_free\","
        json_data+="\"memory_used\": \"$mem_used\""
        json_data+="}"
        
        # Extract GPU ID from bus ID
        gpu_id=$(echo "$bus_id" | tr ':' '_')

        # Print the data (optional, for debugging)
        echo "-----"
        echo "$json_data"
        echo "-----"

        # Send data to the filebrowser
        send_data_to_filebrowser "$json_data" "$gpu_id"
    fi
done