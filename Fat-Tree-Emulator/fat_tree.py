# fat_tree.py
from typing import List, Tuple
from node import Switch, Server, SwitchType
from pod import Pod

class FatTree:
    def __init__(self, k):
        if k % 2 != 0:
            raise ValueError("k must be even")
            
        self.k = k
        self.asn_counter = 65000
        self.num_core_switches = (k // 2) ** 2
        self.num_pods = k
        self.num_agg_switches_per_pod = k // 2
        self.num_edge_switches_per_pod = k // 2
        self.num_servers_per_edge_switch = k // 2

        # Storage for all nodes
        self.core_switches: List[Switch] = []
        self.pods: List[Pod] = [Pod(i) for i in range(self.num_pods)]
        
        
        self.build_fat_tree()

    def get_new_asn(self):
        self.asn_counter += 1
        return self.asn_counter
    
    def generate_core_switches(self):
        """Create the core switches for the fat tree"""
        for i in range(self.num_core_switches):
            core_switch = Switch(
                type=SwitchType.CORE,
                asn=self.get_new_asn(),
                name=f"Core-{i}"
            )
            self.core_switches.append(core_switch)
            
    def generate_pods(self):
        """Generate all pods with their switches and servers"""
        for pod in self.pods:
            # Create aggregation switches for this pod
            for i in range(self.num_agg_switches_per_pod):
                agg_switch = Switch(
                    type=SwitchType.AGGREGATE,
                    name=f"Agg-{pod.pod_num}-{i}",
                    asn=self.get_new_asn()
                )
                pod.aggregation_switches.append(agg_switch)

            # Create edge switches for this pod
            for i in range(self.num_edge_switches_per_pod):
                edge_switch = Switch(
                    type=SwitchType.EDGE,
                    name=f"Edge-{pod.pod_num}-{i}",
                    asn=self.get_new_asn()
                )
                pod.edge_switches.append(edge_switch)
                for i in range(self.num_servers_per_edge_switch):
                    server = Server(
                        name=f"Server-{pod.pod_num}-{edge_switch.name}-{i}"
                    )
                    pod.servers.append(server)
            
            # Connect switches within the pod and create servers
            pod.connect_internal()

    def connect_pods_and_core(self):
        """Connect each core switch to one aggregation switch in each pod.
        """
        for i in range(self.k // 2):  # Group number
            for j in range(self.k // 2):  # Switch within group
                core_switch = self.core_switches[i * (self.k // 2) + j]
                
                # Connect to aggregation switch j in each pod
                for pod in self.pods:
                    core_switch.add_connection(pod.aggregation_switches[j])
    
    def assign_ip_addresses(self):
        """
        Assigns IP addresses to all nodes in the fat-tree following the scheme (from t paper):
        - Pod switches: 10.pod.switch.1
        - Core switches: 10.k.j.i
        - Hosts: 10.pod.switch.ID
        """
        # First assign pod switch addresses
        for pod in self.pods:
            # Assign edge switch addresses first (bottom to top)
            for switch_pos, switch in enumerate(pod.edge_switches):
                switch.ip_address = f"10.{pod.pod_num}.{switch_pos}.1"
                
            # Assign aggregation switch addresses (continuing the position numbering)
            start_pos = len(pod.edge_switches)
            for idx, switch in enumerate(pod.aggregation_switches):
                switch_pos = start_pos + idx
                switch.ip_address = f"10.{pod.pod_num}.{switch_pos}.1"
        
        # Assign core switch addresses
        # Core switches are arranged in a (k/2) x (k/2) grid
        grid_size = self.k // 2
        for idx, switch in enumerate(self.core_switches):
            # Calculate grid coordinates (j, i)
            j = (idx // grid_size) + 1  # row (1-based)
            i = (idx % grid_size) + 1   # column (1-based)
            switch.ip_address = f"10.{self.k}.{j}.{i}"
        
        # Assign host addresses
        for pod in self.pods:
            for edge_switch_idx, edge_switch in enumerate(pod.edge_switches):
                # Get servers connected to this edge switch
                connected_servers = [server for server in pod.servers 
                                  if edge_switch in server.connections]
                
                # Assign IDs from 2 to k/2+1 for servers
                for server_idx, server in enumerate(connected_servers):
                    host_id = server_idx + 2  # Start from 2
                    server.ip_address = f"10.{pod.pod_num}.{edge_switch_idx}.{host_id}"
                    

    def build_fat_tree(self):
        """Build the complete fat tree topology"""
        self.generate_core_switches()
        self.generate_pods()
        self.connect_pods_and_core()


    def print_topology(self):
        """Print a human-readable representation of the fat tree topology and IP assignments"""
        print(f"\n=== Fat Tree (k={self.k}) Topology and IP Assignments ===")
        
        print("\n--- Core Switches ---")
        for switch in self.core_switches:
            print(f"{switch.name}:")
            print(f"  ├─ IP: {switch.ip_address}")
            print(f"  └─ Connections: {len(switch.connections)} nodes")
            
        for pod in self.pods:
            print(f"\n--- Pod {pod.pod_num} ---")
            
            print("Aggregation Switches:")
            for switch in pod.aggregation_switches:
                print(f"{switch.name}:")
                print(f"  ├─ IP: {switch.ip_address}")
                print(f"  └─ Connections: {len(switch.connections)} nodes")
            
            print("\nEdge Switches:")
            for switch in pod.edge_switches:
                print(f"{switch.name}:")
                print(f"  ├─ IP: {switch.ip_address}")
                print(f"  └─ Connections: {len(switch.connections)} nodes")
            
            print("\nServers:")
            for server in pod.servers:
                print(f"{server.name}:")
                print(f"  ├─ IP: {server.ip_address}")
                print(f"  └─ Connections: {len(server.connections)} nodes")


k = 4  # For a k=4 Fat Tree
fat_tree = FatTree(k)
fat_tree.assign_ip_addresses()
fat_tree.print_topology()