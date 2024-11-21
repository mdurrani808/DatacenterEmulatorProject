#!/bin/bash

# Stop and remove containers
echo "Stopping and removing containers..."
docker stop host-a host-b host-c router-a router-b router-c core-router
docker rm -f host-a host-b host-c router-a router-b router-c core-router

# Remove networks
echo "Removing networks..."
docker network rm custom_net1 custom_net2 custom_net3 custom_net4 custom_net5 custom_net6

# Prune system
echo "Pruning unused resources..."
docker system prune -f

echo "Cleanup complete!"