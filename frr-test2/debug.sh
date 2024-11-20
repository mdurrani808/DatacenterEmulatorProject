#!/bin/bash

# Function to print section headers
print_header() {
    echo -e "\n=== $1 ===\n"
}

# Print network info for a container
print_network_info() {
    local container=$1
    print_header "Network Information for $container"
    
    echo "IP Addresses and Interfaces:"
    docker exec $container ip addr show

    echo -e "\nRouting Table:"
    docker exec $container ip route

    echo -e "\nBGP Information:"
    docker exec $container vtysh -c "show ip bgp summary"
    docker exec $container vtysh -c "show ip bgp"
}

# Main execution
print_header "STARTING NETWORK DIAGNOSTICS"

# Print network information for each container
for container in core-router router-a router-b router-c host-a host-b host-c; do
    print_network_info $container
done

print_header "CONNECTIVITY AND TRACEROUTE TESTS"

# Define test pairs with their IPs - now only between hosts
TESTS=(
    "host-a:host-b:192.168.2.1"
    "host-a:host-c:192.168.3.1"
    "host-b:host-a:192.168.1.1"
    "host-b:host-c:192.168.3.1"
    "host-c:host-a:192.168.1.1"
    "host-c:host-b:192.168.2.1"
)

# Execute ping and traceroute tests
for test in "${TESTS[@]}"; do
    IFS=':' read -r source target ip <<< "$test"
    echo -e "\nTesting connectivity from $source to $target ($ip)"
    docker exec $source ping -c 2 $ip
    echo -e "\nTraceroute from $source to $target ($ip)"
    docker exec $source traceroute $ip
done