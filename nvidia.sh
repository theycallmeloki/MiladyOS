#!/bin/bash

# Define keys for each field
keys=( "JENKINS_USERNAME" "timestamp" "name" "pci_bus_id" "driver_version" "pstate" "pcie_link_gen_max" "pcie_link_gen_current" "temperature_gpu" "utilization_gpu" "utilization_memory" "memory_total" "memory_free" "memory_used")

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

# Run nvidia-smi and process its output
nvidia-smi --query-gpu=timestamp,name,pci.bus_id,driver_version,pstate,pcie.link.gen.max,pcie.link.gen.current,temperature.gpu,utilization.gpu,utilization.memory,memory.total,memory.free,memory.used --format=csv -l 1 | \
while IFS= read -r line
do
    # Skip the first line (header)
    if [[ $line != timestamp* ]]; then
        # Prepend JENKINS_USERNAME to the line
        line="$JENKINS_USERNAME,$line"
        
        # Split the line by comma and create a JSON object
        IFS=',' read -ra values <<< "$line"
        json_data="{"
        for i in "${!values[@]}"; do
            # Trim whitespace from the value
            trimmed_value=$(trim "${values[$i]}")
            json_data+="\"${keys[$i]}\": \"$trimmed_value\","
        done
        json_data="${json_data%,}}"  # Remove the trailing comma and close the JSON object
        

        # Extract GPU ID (PCI bus ID)
        gpu_id=$(echo "$json_data" | grep -o '"pci_bus_id": "[^"]*' | cut -d'"' -f4 | tr ':' '_')

        # Print the data (optional, for debugging)
        echo "-----"
        echo "$json_data"
        echo "-----"

        # Send data to the filebrowser
        send_data_to_filebrowser "$json_data" "$gpu_id"
        
    fi
done
