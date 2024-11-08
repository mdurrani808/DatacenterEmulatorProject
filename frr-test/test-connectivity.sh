#!/bin/bash

test_ping() {
    local from=$1
    local to=$2
    local result=$(docker exec -it $from ping -c 1 -W 1 $to >/dev/null 2>&1; echo $?)
    if [ $result -eq 0 ]; then
        echo -e "can ping from $from to $to"
    else
        echo -e "cannot ping from $from to $to"
    fi
}

echo "Testing connectivity between all containers..."
echo "============================================"

# Test from host-a
echo "From host-a:"
test_ping "host-a" "192.168.1.2"  # to router via net1
test_ping "host-a" "192.168.2.1"  # to host-b (via BGP)

# Test from host-b
echo -e "\nFrom host-b:"
test_ping "host-b" "192.168.2.2"  # to router via net2
test_ping "host-b" "192.168.1.1"  # to host-a (via BGP)

# Test from router
echo -e "\nFrom router:"
test_ping "frr-router" "192.168.1.1"  # to host-a
test_ping "frr-router" "192.168.2.1"  # to host-b