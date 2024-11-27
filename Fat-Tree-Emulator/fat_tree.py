import time
from typing import List, Tuple
from node import Switch, Server, SwitchType
from pod import Pod
from pathlib import Path
import shutil
import subprocess

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
        """Assigns IP address bases using the full 172.16.0.0/12 range.
        172.16-31.x.x provides 16 second octets * 256 third octets = 4096 subnets
        Using /30 subnets gives us 4096 * 64 = 262,144 point-to-point links
        """
        self.current_second_octet = 16  # Start at 172.16
        self.current_third_octet = 0
        self.current_fourth_octet = 0  # Will increment by 4 for each /30
        
        # Start each type of node in a different second octet for organization
        # Core switches start at 172.16.x.x
        for core in self.core_switches:
            core.base_ip_address = f"172.{self.current_second_octet}.{self.current_third_octet}."
            self._increment_subnet()
        
        self.current_second_octet = 20  # Aggregation switches start at 172.20.x.x
        self.current_third_octet = 0
        
        # Assign to pods
        for pod_num, pod in enumerate(self.pods):
            for agg_switch in pod.aggregation_switches:
                agg_switch.base_ip_address = f"172.{self.current_second_octet}.{self.current_third_octet}."
                self._increment_subnet()
            
            for edge_switch in pod.edge_switches:
                edge_switch.base_ip_address = f"172.{self.current_second_octet}.{self.current_third_octet}."
                self._increment_subnet()
            
            for server in pod.servers:
                server.base_ip_address = f"172.{self.current_second_octet}.{self.current_third_octet}."
                self._increment_subnet()
                
    def _increment_subnet(self):
        """Helper method to manage subnet allocation"""
        self.current_third_octet += 1
        if self.current_third_octet >= 256:
            self.current_third_octet = 0
            self.current_second_octet += 1
            if self.current_second_octet >= 32:  # Past 172.31
                raise ValueError("IP address space exhausted")

    def generate_interface_ips(self):
        """Generates interface IPs for all connections using /30 subnets.
        Each connection gets its own /30 subnet with 2 usable IPs.
        """
        self.current_second_octet = 16
        self.current_third_octet = 0
        self.current_fourth_octet = 0
        
        def get_next_ip_pair():
            """Returns a pair of IPs for a point-to-point link"""
            # In a /30, .0 is network, .3 is broadcast, .1 and .2 are usable
            ip1 = f"172.{self.current_second_octet}.{self.current_third_octet}.{self.current_fourth_octet + 1}"
            ip2 = f"172.{self.current_second_octet}.{self.current_third_octet}.{self.current_fourth_octet + 2}"
            
            # Increment for next subnet (move by 4 for next /30)
            self.current_fourth_octet += 4
            if self.current_fourth_octet >= 256:
                self.current_fourth_octet = 0
                self.current_third_octet += 1
                if self.current_third_octet >= 256:
                    self.current_third_octet = 0
                    self.current_second_octet += 1
                    if self.current_second_octet >= 32:
                        raise ValueError("IP address space exhausted")
            
            return ip1, ip2
        
        def assign_connection_ips(node1, node2):
            """Helper to assign IPs to both ends of a connection"""
            if node1.connections[node2] != "":  # Already assigned
                return
                
            ip1, ip2 = get_next_ip_pair()
            node1.connections[node2] = ip1
            node2.connections[node1] = ip2
        
        # Assign IPs to core switch connections
        for core in self.core_switches:
            for connection in core.connections.keys():
                assign_connection_ips(core, connection)
        
        # Assign IPs to pod connections
        for pod in self.pods:
            for agg_switch in pod.aggregation_switches:
                for connection in agg_switch.connections.keys():
                    if agg_switch.connections[connection] == "":
                        assign_connection_ips(agg_switch, connection)
            
            for edge_switch in pod.edge_switches:
                for connection in edge_switch.connections.keys():
                    if edge_switch.connections[connection] == "":
                        assign_connection_ips(edge_switch, connection)
            
            for server in pod.servers:
                for connection in server.connections.keys():
                    if server.connections[connection] == "":
                        assign_connection_ips(server, connection)
    
    def print_interface_ips(self):
        print("Core\n")
        for core in self.core_switches:
            print(core.connections.values())
        
        for pod in self.pods:
            print("\nAggregation")
            for agg_switch in pod.aggregation_switches:
                print(agg_switch.connections.values())
                
            print("\nEdge")
            for edge_switch in pod.edge_switches:
                print(edge_switch.connections.values())
                
            print("\nHost")
            for host_server in pod.servers:
                print(host_server.connections.values())
                
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
        
                
        self.generate_configs()
        
        # generate docker containers for each
        self.create_containers()
                
        # convert all 'connections" to veth pairs
        self.create_veth_connections()
        
        # run a ping test to make sure it all works
        self.single_ping()
        #self.cleanup()
        
    def cleanup(self):
        """
        Stops and removes all Docker containers, deletes network namespaces,
        and prunes Docker networks.
        """
        try:
            # Get all container IDs
            container_ids = subprocess.run(
                ["docker", "ps", "-a", "-q"],
                capture_output=True,
                text=True,
                check=True
            ).stdout.strip()

            if container_ids:
                # Stop all containers
                subprocess.run(
                    ["docker", "stop"] + container_ids.split("\n"),
                    check=True
                )
                
                # Remove all containers
                subprocess.run(
                    ["docker", "rm"] + container_ids.split("\n"),
                    check=True
                )

            # Get list of network namespaces
            netns = subprocess.run(
                ["ip", "netns"],
                capture_output=True,
                text=True,
                check=True
            ).stdout.strip()

            if netns:
                # Delete each network namespace
                for ns in netns.split("\n"):
                    subprocess.run(
                        ["sudo", "ip", "netns", "delete", ns],
                        check=True
                    )

            # Prune Docker networks
            subprocess.run(
                ["docker", "network", "prune", "-f"],
                check=True
            )

            print("Cleanup completed successfully")

        except subprocess.CalledProcessError as e:
            print(f"An error occurred: {e}")
            raise
    
    def single_ping(self):
        # get two servers
        server1 = self.pods[0].servers[0]
        server2 = self.pods[2].servers[2]
        
        server1.ping_server(server2)
        server2.ping_server(server1)

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


k = 4  # For a k=4 Fat Tree

fat_tree = FatTree(k, "configs")
fat_tree.print_topology()