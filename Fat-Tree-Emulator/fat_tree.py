import time
from typing import List
from node import Switch, Server, SwitchType
from pod import Pod
from pathlib import Path
import shutil
import subprocess
import networkx as nx
from networkx.drawing.nx_agraph import to_agraph
import pygraphviz as pgv

class FatTree:
    def __init__(self, k, config_folder):
        """Intializes a fat tree

        Args:
            k (int): k parameter for fat tree, must be even
            config_folder (str): base folder where frr routing configs will be stored

        Raises:
            ValueError: Raised if an odd k value is provided
        """
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
        """Maintains monotonicly increasing ASN counter for all switches

        Returns:
            int: new asn number
        """
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


    def generate_ips(self):
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
                
                # makes sure that we don't have any repeating links
                if((core_switch.name, other_node.name) not in self.links and (other_node.name, core_switch.name) not in self.links):
                    core_switch.establish_veth_link(other_node)
                    self.links.add((core_switch.name, other_node.name))
        
        for pod in self.pods:
            #edge connections
            for edge_switch in pod.edge_switches:
                for other_node in edge_switch.connections:
                    
                    # makes sure that we don't have any repeating links (probably a better way to do this)
                    if((edge_switch.name, other_node.name) not in self.links and (other_node.name, edge_switch.name) not in self.links):
                        edge_switch.establish_veth_link(other_node)
                        self.links.add((edge_switch.name, other_node.name))
            
            # aggregation connections
            for agg in pod.aggregation_switches:
                for other_node in agg.connections:
                    if((agg.name, other_node.name) not in self.links and (other_node.name, agg.name) not in self.links):
                        agg.establish_veth_link(other_node)
                        self.links.add((agg.name, other_node.name))
            
            #server connections
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
        self.generate_ips()
        self.generate_configs()
        
        # generate docker containers for each
        self.create_containers()
                
        # convert all 'connections" to veth pairs
        self.create_veth_connections()
        
        self.ping_mesh_parallel()
        self.generate_topology_graph()
        self.cleanup()
     

        
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
    
    def ping_mesh_parallel(self):
        servers = [server for pod in self.pods for server in pod.servers]
        for server in servers:
            target_ips = [
                list(other.connections.values())[0]
                for other in servers
                if other.name != server.name
            ]
            if not target_ips:
                continue
                
            # -a: show alive hosts
            # -s: print stats
            fping_cmd = f"fping -a -s -t 1000 -c 3 {' '.join(target_ips)}"
            
            print(f"\nPinging from {server.name} to all other servers:")
            result = server.container.exec_run(fping_cmd)
            
            if result.exit_code != 0:
                failed_ips = [
                    line.split()[0] 
                    for line in result.output.decode().strip().split('\n')
                    if "unreachable" in line
                ]
                print(f"Failed to reach: {failed_ips}")
            else:
                print("Success!")
        return result.exit_code == 0

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
    def generate_topology_graph(self):
        """
        Creates a visual representation of the fat tree topology and saves it as a PNG file.
        Requires pygraphviz package.
        """

        G = nx.Graph()
        
        for switch in self.core_switches:
            G.add_node(switch.name, level="core")
            
        for pod in self.pods:
            for switch in pod.aggregation_switches:
                G.add_node(switch.name, level="aggregation")
                
            for switch in pod.edge_switches:
                G.add_node(switch.name, level="edge")
                
            for server in pod.servers:
                G.add_node(server.name, level="server")
        
        # Add all edges
        for core in self.core_switches:
            for connection in core.connections:
                G.add_edge(core.name, connection.name)
        
        for pod in self.pods:
            for agg in pod.aggregation_switches:
                for connection in agg.connections:
                    G.add_edge(agg.name, connection.name)
            
            for edge in pod.edge_switches:
                for connection in edge.connections:
                    G.add_edge(edge.name, connection.name)
        
        A = to_agraph(G)
        
        A.graph_attr.update({
            'rankdir': 'TB', 
            'splines': 'line', 
            'nodesep': '0.5', 
            'ranksep': '1.0',
            'fontname': 'Arial',
            'bgcolor': 'white'
        })
        
        A.node_attr.update({
            'shape': 'box',
            'style': 'filled',
            'fontname': 'Arial',
            'margin': '0.1'
        })
        
        for node in A.nodes():
            level = G.nodes[node]['level']
            if level == "core":
                node.attr.update({'fillcolor': '#FF9999', 'label': f'Core\n{node}'})
            elif level == "aggregation":
                node.attr.update({'fillcolor': '#99FF99', 'label': f'Agg\n{node}'})
            elif level == "edge":
                node.attr.update({'fillcolor': '#9999FF', 'label': f'Edge\n{node}'})
            elif level == "server":
                node.attr.update({'fillcolor': '#FFFF99', 'label': f'Server\n{node}'})
        
        for pod in self.pods:
            pod_nodes = []
            pod_nodes.extend([switch.name for switch in pod.aggregation_switches])
            pod_nodes.extend([switch.name for switch in pod.edge_switches])
            pod_nodes.extend([server.name for server in pod.servers])
            
            with A.subgraph(name=f'cluster_pod_{pod.pod_num}') as s:
                s.graph_attr.update({
                    'label': f'Pod {pod.pod_num}',
                    'style': 'dashed',
                    'color': 'blue',
                    'bgcolor': '#EEEEFF'
                })
                for node in pod_nodes:
                    s.add_node(node)
        
        A.layout(prog='dot')
        output_file = f"fat_tree_k{self.k}_topology.png"
        A.draw(output_file)
        print(f"Topology graph saved as {output_file}")

k = 4  # For a k=4 Fat Tree

fat_tree = FatTree(k, "configs")
