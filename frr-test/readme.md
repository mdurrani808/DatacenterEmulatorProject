## Quick Start

1. Set permissions for FRR configuration files
```bash
chmod 640 frr/*/daemons
chmod 640 frr/*/frr.conf
```

2. Start the containers
```bash
docker-compose up -d
```

3. Verify all containers are running
```bash
docker ps
```
4. Tear everything down.
```bash
docker-compose down
```

### BGP Status Commands

Check BGP status on router:
```bash
# Show BGP summary
docker exec -it frr-router vtysh -c "show ip bgp summary"

# Show BGP neighbors
docker exec -it frr-router vtysh -c "show ip bgp neighbors"

# Show routing table
docker exec -it frr-router vtysh -c "show ip route"

# Show BGP routes
docker exec -it frr-router vtysh -c "show ip bgp"
```

Check BGP status on hosts:
```bash
# Host A
docker exec -it host-a vtysh -c "show ip bgp summary"
docker exec -it host-a vtysh -c "show ip route"

# Host B
docker exec -it host-b vtysh -c "show ip bgp summary"
docker exec -it host-b vtysh -c "show ip route"
```

### Interactive FRR Shell
To enter interactive FRR shell:
```bash
# Router
docker exec -it frr-router vtysh

# Host A
docker exec -it host-a vtysh

# Host B
docker exec -it host-b vtysh
```

Common commands in vtysh:
```bash
# Show running configuration
show running-config

# Show interface status
show interface brief

# Show BGP advertised routes
show ip bgp neighbors 192.168.1.1 advertised-routes

# Show received routes
show ip bgp neighbors 192.168.1.1 received-routes
```
