from typing import List, Tuple
from node import Switch, Server, SwitchType
from pod import Pod
from pathlib import Path
import shutil

class FatTree:
    def __init__(self, k, config_folder):
        if k % 2 != 0:
            raise ValueError("k must be even")
            
        self.k = k
        self.asn_counter = 65000
        self.num_core_switches = (k // 2) ** 2
        self.num_pods = k
        self.num_agg_switches_per_pod = k // 2
        self.num_edge_switches_per_pod = k // 2
        self.num_servers_per_edge_switch = k // 2
        self.root_storage_folder = f"{Path.cwd()}/{config_folder}"
        self.links = set()
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
                name=f"C-{i}",
                config_base=self.root_storage_folder
            )
            self.core_switches.append(core_switch)
            
    def generate_pods(self):
        """Generate all pods with their switches and servers"""
        for pod in self.pods:
            # Create aggregation switches for this pod
            for i in range(self.num_agg_switches_per_pod):
                agg_switch = Switch(
                    type=SwitchType.AGGREGATE,
                    name=f"A{pod.pod_num}-{i}",
                    asn=self.get_new_asn(),
                    config_base=self.root_storage_folder
                )
                pod.aggregation_switches.append(agg_switch)

            # Create edge switches for this pod
            for i in range(self.num_edge_switches_per_pod):
                edge_switch = Switch(
                    type=SwitchType.EDGE,
                    name=f"E{pod.pod_num}-{i}",
                    asn=self.get_new_asn(),
                    config_base=self.root_storage_folder
                )
                pod.edge_switches.append(edge_switch)
                for i in range(self.num_servers_per_edge_switch):
                    server = Server(
                        name=f"S{pod.pod_num}-{edge_switch.name}-{i}",
                        config_base=self.root_storage_folder
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
                    core_switch.register_connection(pod.aggregation_switches[j])
    
    def assign_base_ip_addresses(self):
        """Assigns IP addresses to all nodes, assuming a /24 subnet
        Each core switch gets 10.0.x.0/24 (x = core switch number 1-4)
        
        Each agg switch gets 10.pod.x.0/24 (pod = pod number, x = switch number 0-1)
        
        Each edge switch gets 10.pod.x.0/24 (pod = pod number, x = switch number 2-3)
        
        Each host gets 10.pod.x.0/24 (pod = pod number, x = switch number 4-11)
        
        Examples above are for when k = 4, but important idea is that there is an offset between edge, and host based on the number of the aggregation or edge. 
        """
        
        for i, core in enumerate(self.core_switches):
            core.base_ip_address = f"10.0.{i}."
        
        for pod_num, pod in enumerate(self.pods):
            for agg_num, agg_switch in enumerate(pod.aggregation_switches):
                agg_switch.base_ip_address = f"10.{pod_num}.{agg_num}."
                
            edge_offset = len(pod.aggregation_switches)
            for edge_num, edge_switch in enumerate(pod.edge_switches):
                edge_switch.base_ip_address = f"10.{pod_num}.{edge_offset + edge_num}."
                
            host_offset = edge_offset + len(pod.edge_switches)
            for host_num, host_server in enumerate(pod.servers):
                host_server.base_ip_address = f"10.{pod_num}.{host_offset + host_num}."
            
    def generate_interface_ips(self):
        for core in self.core_switches:
            for connection in core.connections.keys():
                core.connections[connection] = core.base_ip_address + core.get_ip_counter()
                print(core.connections[connection])
        
        for pod in self.pods:
            for agg_switch in pod.aggregation_switches:
                for connection in agg_switch.connections.keys():
                    agg_switch.connections[connection] = agg_switch.base_ip_address + agg_switch.get_ip_counter()
                    print(agg_switch.connections[connection])
                
            for edge_switch in pod.edge_switches:
                for connection in edge_switch.connections.keys():
                    edge_switch.connections[connection] = edge_switch.base_ip_address + edge_switch.get_ip_counter()
                    print(edge_switch.connections[connection])
                
            for host_server in pod.servers:
                for connection in host_server.connections.keys():
                    host_server.connections[connection] = host_server.base_ip_address + host_server.get_ip_counter()
                    print(host_server.connections[connection])
                
    def generate_configs(self):
        # clear out all the old configs
        for folder in Path(self.root_storage_folder).iterdir():
            if folder.is_dir():
                shutil.rmtree(folder)
                
        # go one by one and generate new configs
        for core in self.core_switches:
            core.generate_config_folder()
        for pod in self.pods:
            for aggregate in pod.aggregation_switches:
                aggregate.generate_config_folder()
            for edge in pod.edge_switches:
                edge.generate_config_folder()
                
    def create_containers(self):    
        # go one by one and create docker containers
        for core in self.core_switches:
            core.create_frr_container()
        for pod in self.pods:
            for aggregate in pod.aggregation_switches:
                aggregate.create_frr_container()
            for edge in pod.edge_switches:
                edge.create_frr_container()
            for server in pod.servers:
                server.create_container()

    def create_veth_connections(self):
        """Creates veth pairs for all connections in the fat tree topology"""
        # Connect core switches to aggregation switches
        for core_switch in self.core_switches:
            for other_node in core_switch.connections:
                if((core_switch.name, other_node.name) not in self.links and (other_node.name, core_switch.name) not in self.links):
                    core_switch.establish_veth_link(other_node)
                    self.links.add((core_switch.name, other_node.name))
        
        for pod in self.pods:
            for edge_switch in pod.edge_switches:
                for other_node in edge_switch.connections:
                    if((edge_switch.name, other_node.name) not in self.links and (other_node.name, edge_switch.name) not in self.links):
                        edge_switch.establish_veth_link(other_node)
                        self.links.add((edge_switch.name, other_node.name))
            
            for agg in pod.aggregation_switches:
                for other_node in agg.connections:
                    if((agg.name, other_node.name) not in self.links and (other_node.name, agg.name) not in self.links):
                        agg.establish_veth_link(other_node)
                        self.links.add((agg.name, other_node.name))
            for server in pod.servers:
                for other_node in server.connections:
                    if((server.name, other_node.name) not in self.links and (other_node.name, server.name) not in self.links):
                        server.establish_veth_link(other_node)
                        self.links.add((server.name, other_node.name))
                        
        print("Completed creating all veth connections")
    
    def build_fat_tree(self):
        """Build the complete fat tree topology"""
        self.generate_core_switches()
        self.generate_pods()
        self.connect_pods_and_core()
        self.assign_base_ip_addresses()
        self.generate_interface_ips()
        
        self.print_topology()
        
        self.generate_configs()
        
        # generate docker containers for each
        self.create_containers()
                
        # convert all 'connections" to veth pairs
        self.create_veth_connections()
        
        # run a ping test to make sure it all works
        
    

    def print_topology(self):
        """Print a human-readable representation of the fat tree topology and IP assignments"""
        print(f"\n=== Fat Tree (k={self.k}) Topology and IP Assignments ===")
        
        print("\n--- Core Switches ---")
        for switch in self.core_switches:
            print(switch)
            
            
        for pod in self.pods:
            print(f"\n--- Pod {pod.pod_num} ---")
            
            print("Aggregation Switches:")
            for switch in pod.aggregation_switches:
                print(switch)
            
            print("\nEdge Switches:")
            for switch in pod.edge_switches:
                print(switch)
            
            print("\nServers:")
            for server in pod.servers:
                print(server)


k = 2  # For a k=4 Fat Tree

fat_tree = FatTree(k, "configs")
fat_tree.print_topology()