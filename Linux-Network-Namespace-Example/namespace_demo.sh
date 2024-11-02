#!/bin/bash

# Function to check if command succeeded
check_error() {
    if [ $? -ne 0 ]; then
        echo "Error: $1"
        exit 1
    fi
}

# Function to clean up existing namespaces
cleanup() {
    echo "Cleaning up existing namespaces..."
    sudo ip netns delete hostA 2>/dev/null
    sudo ip netns delete hostB 2>/dev/null
    sudo ip netns delete router 2>/dev/null
    echo "Cleanup completed"
}

# Function to test connectivity
test_connectivity() {
    echo "Testing connectivity..."
    echo "Pinging router from Host A (192.168.1.2):"
    sudo ip netns exec hostA ping -c 2 192.168.1.2
    echo ""
    
    echo "Pinging Host B from Host A (192.168.2.1):"
    sudo ip netns exec hostA ping -c 2 192.168.2.1
    echo ""
    
    echo "Pinging Host A from Host B (192.168.1.1):"
    sudo ip netns exec hostB ping -c 2 192.168.1.1
}

# Main setup function
setup_network() {
    echo "Creating network namespaces..."
    sudo ip netns add hostA
    check_error "Failed to create hostA namespace"
    
    sudo ip netns add hostB
    check_error "Failed to create hostB namespace"
    
    sudo ip netns add router
    check_error "Failed to create router namespace"

    echo "Creating virtual ethernet pairs..."
    sudo ip link add veth-a-h type veth peer name veth-a-r
    check_error "Failed to create veth pair for Host A"
    
    sudo ip link add veth-b-h type veth peer name veth-b-r
    check_error "Failed to create veth pair for Host B"

    echo "Moving interfaces to their namespaces..."
    sudo ip link set veth-a-h netns hostA
    sudo ip link set veth-a-r netns router
    sudo ip link set veth-b-h netns hostB
    sudo ip link set veth-b-r netns router

    echo "Configuring IP addresses..."
    # Configure Host A
    sudo ip netns exec hostA ip addr add 192.168.1.1/24 dev veth-a-h
    sudo ip netns exec hostA ip link set veth-a-h up
    sudo ip netns exec hostA ip link set lo up

    # Configure Host B
    sudo ip netns exec hostB ip addr add 192.168.2.1/24 dev veth-b-h
    sudo ip netns exec hostB ip link set veth-b-h up
    sudo ip netns exec hostB ip link set lo up

    # Configure Router
    sudo ip netns exec router ip addr add 192.168.1.2/24 dev veth-a-r
    sudo ip netns exec router ip addr add 192.168.2.2/24 dev veth-b-r
    sudo ip netns exec router ip link set veth-a-r up
    sudo ip netns exec router ip link set veth-b-r up
    sudo ip netns exec router ip link set lo up

    echo "Enabling IP forwarding in router..."
    sudo ip netns exec router sysctl -w net.ipv4.ip_forward=1

    echo "Configuring routing..."
    sudo ip netns exec hostA ip route add default via 192.168.1.2
    sudo ip netns exec hostB ip route add default via 192.168.2.2
}

# Display network information function
show_network_info() {
    echo "Network Information:"
    echo "==================="
    echo "Host A IP addresses:"
    sudo ip netns exec hostA ip addr show
    echo ""
    echo "Host B IP addresses:"
    sudo ip netns exec hostB ip addr show
    echo ""
    echo "Router IP addresses:"
    sudo ip netns exec router ip addr show
    echo ""
    echo "Routing tables:"
    echo "Host A routing table:"
    sudo ip netns exec hostA ip route
    echo ""
    echo "Host B routing table:"
    sudo ip netns exec hostB ip route
    echo ""
    echo "Router routing table:"
    sudo ip netns exec router ip route
}

# Main script execution
echo "Starting network setup..."

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Clean up existing namespaces
cleanup

# Setup network
setup_network
check_error "Network setup failed"

# Show network information
show_network_info

# Test connectivity
test_connectivity

echo "Setup completed successfully!"
echo "To clean up, run: sudo ./$(basename $0) cleanup"

# Handle cleanup argument
if [ "$1" = "cleanup" ]; then
    cleanup
    exit 0
fi
