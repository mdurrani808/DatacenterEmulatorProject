# Datacenter Network Emulator
> Built by: Cheng-Yuan Lee, Jose Cruz, John Shim, Mohammad Durrani, Andrew Liu

A Python-based network emulator that creates and simulates k-ary fat-tree datacenter topologies using Docker containers and Linux network namespaces.

See our report [here](CMSC498B_Final_Report.pdf).

## Overview

This project emulates datacenter networks with fat-tree topology, supporting up to k=70 (42,875 servers). It uses Docker for containerization, FRRouting (FRR) for BGP routing, and provides interactive visualization and network diagnostics.

## Key Features

- **Fat-Tree Topology Generation**: Creates hierarchical datacenter networks with core, aggregation, and edge layers
- **BGP Routing**: Implements Border Gateway Protocol with ECMP for load balancing
- **Containerized Switches**: Uses Docker with FRRouting for realistic switch behavior
- **Network Diagnostics**: Includes PingMesh and Traceroute for connectivity testing
- **Interactive Visualization**: Web-based interface with real-time topology visualization
- **Scalable Design**: Supports topologies from small test networks to large-scale datacenters
