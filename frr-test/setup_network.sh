#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo)"
    exit 1
fi


# Get container PIDs
ROUTER_PID=$(docker inspect -f '{{.State.Pid}}' frr-router)
HOST_A_PID=$(docker inspect -f '{{.State.Pid}}' host-a)
HOST_B_PID=$(docker inspect -f '{{.State.Pid}}' host-b)

echo "Router PID: $ROUTER_PID"
echo "Host A PID: $HOST_A_PID"
echo "Host B PID: $HOST_B_PID"

# Create veth pairs
ip link add veth-a type veth peer name veth-r1
ip link add veth-b type veth peer name veth-r2

# Set all links up in root namespace first
ip link set veth-a up
ip link set veth-r1 up
ip link set veth-b up
ip link set veth-r2 up

# Move interfaces to namespaces
ip link set veth-a netns $HOST_A_PID
ip link set veth-r1 netns $ROUTER_PID
ip link set veth-b netns $HOST_B_PID
ip link set veth-r2 netns $ROUTER_PID

# Configure host-a interface
docker exec host-a ip addr add 192.168.1.2/31 dev veth-a
docker exec host-a ip link set veth-a up

# Configure router interfaces
docker exec frr-router ip addr add 192.168.1.3/31 dev veth-r1
docker exec frr-router ip addr add 192.168.2.3/31 dev veth-r2
docker exec frr-router ip link set veth-r1 up
docker exec frr-router ip link set veth-r2 up

# Configure host-b interface
docker exec host-b ip addr add 192.168.2.2/31 dev veth-b
docker exec host-b ip link set veth-b up

echo "Network setup completed!"