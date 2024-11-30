# fat_tree.py

import subprocess
import shutil
from pathlib import Path
from typing import List
from node import Switch, Server, SwitchType
from pod import Pod
import networkx as nx
import plotly.graph_objects as go
from networkx.drawing.nx_agraph import to_agraph
import plotly.io as pio

class FatTree:
    def __init__(self, k, config_folder, message_callback=None):
        """Initializes a fat tree.

        Args:
            k (int): k parameter for fat tree, must be even.
            config_folder (str): Base folder where FRR routing configs will be stored.
            message_callback (function): Function to call for emitting messages.
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
        
        self.message_callback = message_callback  # Assign the callback

    def get_new_asn(self):
        """Maintains monotonically increasing ASN counter for all switches

        Returns:
            int: new ASN number
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
            self.log(f"Generated core switch: {core_switch.name}")

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
                self.log(f"Generated aggregation switch: {agg_switch.name} in Pod {pod.pod_num}")

            # Create edge switches for this pod
            for i in range(self.num_edge_switches_per_pod):
                edge_switch = Switch(
                    type=SwitchType.EDGE,
                    name=f"E{pod.pod_num}-{i}",
                    asn=self.get_new_asn(),
                    config_base=self.root_storage_folder
                )
                pod.edge_switches.append(edge_switch)
                self.log(f"Generated edge switch: {edge_switch.name} in Pod {pod.pod_num}")
                for j in range(self.num_servers_per_edge_switch):
                    server = Server(
                        name=f"S{pod.pod_num}-{edge_switch.name}-{j}",
                        config_base=self.root_storage_folder
                    )
                    pod.servers.append(server)
                    self.log(f"Generated server: {server.name} in Pod {pod.pod_num}")
            
            # Connect switches within the pod and create servers
            pod.connect_internal()
            self.log(f"Connected internal switches and servers within Pod {pod.pod_num}")

    def connect_pods_and_core(self):
        """Connect each core switch to one aggregation switch in each pod."""
        for i in range(self.k // 2):  # Group number
            for j in range(self.k // 2):  # Switch within group
                core_switch = self.core_switches[i * (self.k // 2) + j]
                
                # Connect to aggregation switch j in each pod
                for pod in self.pods:
                    core_switch.register_connection(pod.aggregation_switches[j])
                    self.log(f"Connected Core {core_switch.name} to Aggregation {pod.aggregation_switches[j].name} in Pod {pod.pod_num}")

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
            if node1.connections.get(node2, "") != "":  # Already assigned
                return
                
            ip1, ip2 = get_next_ip_pair()
            node1.connections[node2] = ip1
            node2.connections[node1] = ip2
            self.log(f"Assigned IPs: {node1.name} <-> {node2.name} : {ip1} <-> {ip2}")

        # Assign IPs to core switch connections
        for core in self.core_switches:
            for connection in core.connections.keys():
                assign_connection_ips(core, connection)
        
        # Assign IPs to pod connections
        for pod in self.pods:
            for agg_switch in pod.aggregation_switches:
                for connection in agg_switch.connections.keys():
                    if agg_switch.connections.get(connection, "") == "":
                        assign_connection_ips(agg_switch, connection)
            
            for edge_switch in pod.edge_switches:
                for connection in edge_switch.connections.keys():
                    if edge_switch.connections.get(connection, "") == "":
                        assign_connection_ips(edge_switch, connection)
            
            for server in pod.servers:
                for connection in server.connections.keys():
                    if server.connections.get(connection, "") == "":
                        assign_connection_ips(server, connection)

    def generate_configs(self):
        # Clear out all the old configs
        for folder in Path(self.root_storage_folder).iterdir():
            if folder.is_dir():
                shutil.rmtree(folder)
                self.log(f"Removed old config folder: {folder.name}")
                
        # Generate new configs
        for core in self.core_switches:
            core.generate_config_folder()
            self.log(f"Generated config for {core.name}")
        for pod in self.pods:
            for aggregate in pod.aggregation_switches:
                aggregate.generate_config_folder()
                self.log(f"Generated config for {aggregate.name}")
            for edge in pod.edge_switches:
                edge.generate_config_folder()
                self.log(f"Generated config for {edge.name}")

    def create_containers(self):
        """
        Creates Docker containers for all nodes in the fat tree.
        Returns:
            str: Output messages.
        """
        outputs = []
        try:
            for core in self.core_switches:
                output = core.create_frr_container()
                outputs.append(output)
                self.log(f"Created container for {core.name}")
            for pod in self.pods:
                for aggregate in pod.aggregation_switches:
                    output = aggregate.create_frr_container()
                    outputs.append(output)
                    self.log(f"Created container for {aggregate.name}")
                for edge in pod.edge_switches:
                    output = edge.create_frr_container()
                    outputs.append(output)
                    self.log(f"Created container for {edge.name}")
                for server in pod.servers:
                    output = server.create_container()
                    outputs.append(output)
                    self.log(f"Created container for {server.name}")
            return "\n".join(outputs)
        except Exception as e:
            self.log(f"Error during container creation: {str(e)}", error=True)
            return f"Error during container creation: {str(e)}"

    def create_veth_connections(self):
        """Creates veth pairs for all connections in the fat tree topology"""
        try:
            # Connect core switches to aggregation switches
            for core_switch in self.core_switches:
                for other_node in core_switch.connections:
                    # Avoid repeating links
                    if((core_switch.name, other_node.name) not in self.links and (other_node.name, core_switch.name) not in self.links):
                        core_switch.establish_veth_link(other_node)
                        self.links.add((core_switch.name, other_node.name))
                        self.log(f"Established veth link between {core_switch.name} and {other_node.name}")
            
            for pod in self.pods:
                # Edge connections
                for edge_switch in pod.edge_switches:
                    for other_node in edge_switch.connections:
                        if((edge_switch.name, other_node.name) not in self.links and (other_node.name, edge_switch.name) not in self.links):
                            edge_switch.establish_veth_link(other_node)
                            self.links.add((edge_switch.name, other_node.name))
                            self.log(f"Established veth link between {edge_switch.name} and {other_node.name}")
                
                # Aggregation connections
                for agg in pod.aggregation_switches:
                    for other_node in agg.connections:
                        if((agg.name, other_node.name) not in self.links and (other_node.name, agg.name) not in self.links):
                            agg.establish_veth_link(other_node)
                            self.links.add((agg.name, other_node.name))
                            self.log(f"Established veth link between {agg.name} and {other_node.name}")
                
                # Server connections
                for server in pod.servers:
                    for other_node in server.connections:
                        if((server.name, other_node.name) not in self.links and (other_node.name, server.name) not in self.links):
                            server.establish_veth_link(other_node)
                            self.links.add((server.name, other_node.name))
                            self.log(f"Established veth link between {server.name} and {other_node.name}")
            
            self.log("Completed creating all veth connections")
        except Exception as e:
            self.log(f"Error during veth connection creation: {str(e)}", error=True)

    def log(self, message, error=False):
        """Helper method to emit messages if a callback is provided."""
        if self.message_callback:
            self.message_callback(message, error=error)
        if error:
            print(f"ERROR: {message}")  # Distinguish error messages
        else:
            print(message)  # Also print to server console for debugging


    def build_fat_tree(self):
        """Build the complete fat tree topology."""
        self.cleanup()
        self.log("Cleaned up existing Docker containers and networks.")
        self.generate_core_switches()
        self.generate_pods()
        self.connect_pods_and_core()
        self.generate_ips()
        self.generate_configs()
        self.create_containers()
        self.create_veth_connections()
        # Uncomment the following lines if you want to create veth connections and other steps
        # self.ping_mesh_parallel()
        # self.generate_topology_graph_plotly()
        # self.cleanup()
        self.log("Fat Tree build process completed.")

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
                self.log("Stopped all Docker containers.")
                
                # Remove all containers
                subprocess.run(
                    ["docker", "rm"] + container_ids.split("\n"),
                    check=True
                )
                self.log("Removed all Docker containers.")

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
                    self.log(f"Deleted network namespace: {ns}")

            # Prune Docker networks
            subprocess.run(
                ["docker", "network", "prune", "-f"],
                check=True
            )
            self.log("Pruned Docker networks.")

            self.log("Cleanup completed successfully.")

        except subprocess.CalledProcessError as e:
            self.log(f"An error occurred during cleanup: {e}", error=True)
            raise

    def ping_mesh_parallel(self):
        servers = [server for pod in self.pods for server in pod.servers]
        all_outputs = []
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

            self.log(f"Pinging from {server.name} to all other servers...")
            result = server.container.exec_run(fping_cmd)

            if result.exit_code != 0:
                failed_ips = [
                    line.split()[0]
                    for line in result.output.decode().strip().split('\n')
                    if "unreachable" in line
                ]
                output = f"Failed to reach: {failed_ips}"
                self.log(output)
                all_outputs.append(f"Server {server.name}: {output}")
            else:
                success_output = "Ping Success!"
                self.log(success_output)
                all_outputs.append(f"Server {server.name}: {success_output}")
        # Return all outputs as a single string
        return "\n".join(all_outputs)

    def print_topology(self):
        """Print a human-readable representation of the fat tree topology and IP assignments"""
        self.log(f"\n=== Fat Tree (k={self.k}) Topology and IP Assignments ===")
        
        self.log("\n--- Core Switches ---")
        for switch in self.core_switches:
            self.log(switch)
            
        for pod in self.pods:
            self.log(f"\n--- Pod {pod.pod_num} ---")
            
            self.log("Aggregation Switches:")
            for switch in pod.aggregation_switches:
                self.log(switch)
            
            self.log("\nEdge Switches:")
            for switch in pod.edge_switches:
                self.log(switch)
            
            self.log("\nServers:")
            for server in pod.servers:
                self.log(server)

    def generate_topology_graph_plotly(self):
        """
        Creates an interactive visual representation of the fat tree topology using Plotly
        and saves it as an HTML file with cores on top, pods arranged from left to right,
        and servers aligned on the same horizontal level. The height of the visualization
        can be adjusted by modifying vertical spacing parameters.
        """
        import math

        # Step 1: Create the NetworkX graph
        G = nx.Graph()

        # Add core switches
        for switch in self.core_switches:
            G.add_node(switch.name, level="core")

        # Add pods with aggregation switches, edge switches, and servers
        for pod in self.pods:
            for switch in pod.aggregation_switches:
                G.add_node(switch.name, level="aggregation")

            for switch in pod.edge_switches:
                G.add_node(switch.name, level="edge")

            for server in pod.servers:
                G.add_node(server.name, level="server")

        # Add edges for core switches
        for core in self.core_switches:
            for connection in core.connections:
                G.add_edge(core.name, connection.name)

        # Add edges within each pod
        for pod in self.pods:
            for agg in pod.aggregation_switches:
                for connection in agg.connections:
                    G.add_edge(agg.name, connection.name)

            for edge in pod.edge_switches:
                for connection in edge.connections:
                    G.add_edge(edge.name, connection.name)

        # Step 2: Manually compute positions
        pos = {}
        hierarchy_levels = {
            "core": 3,
            "aggregation": 2,
            "edge": 1,
            "server": 0
        }

        base_spacing_value = 100

        # Define spacing parameters
        server_spacing = base_spacing_value * 6 # Horizontal spacing between servers within a pod
        pod_spacing =  server_spacing * (self.k + 6)      # Horizontal spacing between pods
        core_spacing = pod_spacing * 0.5      # Horizontal spacing between core switches
        inter_pod_spacing = pod_spacing * 0.3   # Additional spacing between nodes within a pod

        # Adjustable vertical spacing multiplier
        vertical_spacing_multiplier = base_spacing_value * 15 # Increase for more height, decrease for less

        # Update hierarchy_levels to reflect vertical spacing
        hierarchy_levels_scaled = {level: y * vertical_spacing_multiplier for level, y in hierarchy_levels.items()}

        # Calculate total number of pods and cores
        num_pods = len(self.pods)
        num_cores = len(self.core_switches)

        # Calculate the total width needed
        total_width = max(num_pods * pod_spacing, num_cores * core_spacing) * 1.5

        # Step 3: Position Core Switches
        # Spread core switches evenly across the top
        core_x_start = (total_width - (num_cores - 1) * core_spacing) / 2
        for idx, core in enumerate(sorted(self.core_switches, key=lambda c: c.name)):
            x = core_x_start + idx * core_spacing
            y = hierarchy_levels_scaled["core"]
            pos[core.name] = (x, y)

        # Step 4: Position Pods
        # Spread pods evenly across the x-axis
        pod_x_start = (total_width - (num_pods - 1) * pod_spacing) / 2
        for pod_idx, pod in enumerate(sorted(self.pods, key=lambda p: p.pod_num)):
            # Assign a central x position for each pod
            pod_center_x = pod_x_start + pod_spacing * pod_idx # + pod_spacing / 2

            # Position Aggregation Switches
            sorted_agg = sorted(pod.aggregation_switches, key=lambda a: a.name)
            num_agg = len(sorted_agg)
            agg_total_width = (num_agg - 1) * inter_pod_spacing
            agg_x_start_pod = pod_center_x - agg_total_width / 2
            for idx_agg, agg in enumerate(sorted_agg):
                x = agg_x_start_pod + idx_agg * inter_pod_spacing
                y = hierarchy_levels_scaled["aggregation"]
                pos[agg.name] = (x, y)

            # Position Edge Switches
            sorted_edge = sorted(pod.edge_switches, key=lambda e: e.name)
            num_edge = len(sorted_edge)
            edge_total_width = (num_edge - 1) * inter_pod_spacing
            edge_x_start_pod = pod_center_x - edge_total_width / 2
            for idx_edge, edge in enumerate(sorted_edge):
                x = edge_x_start_pod + idx_edge * inter_pod_spacing
                y = hierarchy_levels_scaled["edge"]
                pos[edge.name] = (x, y)

            # Position Servers
            sorted_servers = sorted(pod.servers, key=lambda s: s.name)
            num_servers = len(sorted_servers)
            server_total_width = (num_servers - 1) * server_spacing
            server_x_start_pod = pod_center_x - server_total_width / 2
            for idx_srv, server in enumerate(sorted_servers):
                x = server_x_start_pod + idx_srv * server_spacing
                y = hierarchy_levels_scaled["server"]
                pos[server.name] = (x, y)

        # Step 5: Extract edge coordinates
        edge_x = []
        edge_y = []
        for edge in G.edges():
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

        edge_trace = go.Scatter(
            x=edge_x, y=edge_y,
            line=dict(width=1, color='#888'),
            hoverinfo='none',
            mode='lines'
        )

        # Step 6: Extract node coordinates and attributes
        node_x = []
        node_y = []
        node_labels = []
        node_hovertexts = []
        node_color = []

        # Define color mapping based on node level
        color_map = {
            "core": "#FF9999",         # Red
            "aggregation": "#99FF99",  # Green
            "edge": "#9999FF",         # Blue
            "server": "#FFFF99"        # Yellow
        }

        for node in G.nodes():
            node_labels.append(node)  # Label: node name
            x, y = pos[node]
            node_x.append(x)
            node_y.append(y)
            # Retrieve node attributes
            level = G.nodes[node]['level']
            num_connections = len(G.edges(node))  # Number of connections

            # Example: You can include more attributes as needed
            # Assuming each node has an 'asn' or 'ip' attribute, modify accordingly
            # For demonstration, we'll include level and number of connections
            hover_text = f"<b>{level.capitalize()} Switch</b><br>Name: {node}<br>Connections: {num_connections}"
            node_hovertexts.append(hover_text)
            node_color.append(color_map.get(level, "#CCCCCC"))  # Default color if level not found


        node_trace = go.Scatter(
            x=node_x, y=node_y,
            mode='markers+text',
            text=node_labels,  # Labels displayed on the graph
            textposition="bottom center",
            hovertext=node_hovertexts,  # Detailed hover information
            hoverinfo='text',  # Use only the hovertext for hover info
            marker=dict(
                showscale=False,
                color=node_color,
                size=40,
                line=dict(width=2, color='#FFFFFF')
            )
        )

        # Step 7: Create the Plotly figure with adjustable height
        fig = go.Figure(data=[edge_trace, node_trace],
                        layout=go.Layout(
                            title='Fat Tree Topology',
                            titlefont_size=20,
                            showlegend=False,
                            hovermode='closest',
                            margin=dict(b=20, l=5, r=5, t=40),
                            annotations=[dict(
                                text="",
                                showarrow=False,
                                xref="paper", yref="paper")],
                            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)),
                        )

        # Step 8: Add pod boundaries and labels
        shapes = []
        for pod_idx, pod in enumerate(sorted(self.pods, key=lambda p: p.pod_num)):
            pod_nodes = set()
            pod_nodes.update([switch.name for switch in pod.aggregation_switches])
            pod_nodes.update([switch.name for switch in pod.edge_switches])
            pod_nodes.update([server.name for server in pod.servers])

            # Get positions of pod nodes
            xs = [pos[node][0] for node in pod_nodes]
            ys = [pos[node][1] for node in pod_nodes]
            if not xs or not ys:
                continue
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)

            # Add some padding
            padding_x = pod_spacing / 10
            padding_y = vertical_spacing_multiplier * 0.25  # Small padding relative to vertical spacing
            shapes.append(dict(
                type="rect",
                x0=x_min - padding_x, y0=y_min - padding_y,
                x1=x_max + padding_x, y1=y_max + padding_y,
                line=dict(color="RoyalBlue"),
                fillcolor="LightBlue",
                opacity=0.2,
                layer="below"
            ))

            # Add pod label
            fig.add_annotation(
                x=(x_min + x_max) / 2,
                y=y_max + padding_y + (vertical_spacing_multiplier * 0.1),  # Position above the rectangle
                text=f"Pod {pod.pod_num}",
                showarrow=False,
                font=dict(color="RoyalBlue", size=14)
            )

        fig.update_layout(shapes=shapes)

        # Step 9: Adjust layout for better visualization
        fig.update_layout(
            xaxis=dict(
                range=[-pod_spacing, total_width + pod_spacing],
                scaleanchor="y",
                scaleratio=1,
                showgrid=False,
                zeroline=False,
                showticklabels=False
            ),
            yaxis=dict(
                range=[-1, hierarchy_levels_scaled["core"] + vertical_spacing_multiplier * 0.5],
                showgrid=False,
                zeroline=False,
                showticklabels=False
            ),
            height=800,  # Adjust the figure height here (in pixels)
            width=1200,  # Optionally, adjust the figure width
        )

        # Step 10: Save the figure as an HTML file
        output_html_file = f"fat_tree_k{self.k}_topology.html"
        fig.write_html(output_html_file, full_html=True, include_plotlyjs='cdn')
        self.log(f"Topology graph saved as {output_html_file}")

    def find_server_by_name(self, name: str):
        """Find a server by its name."""
        for pod in self.pods:
            for server in pod.servers:
                if server.name == name:
                    return server
        return None

    def ping(self, source: str, destination: str):
        """Ping from source server to destination server."""

        source_server = self.find_server_by_name(source)
        destination_server = self.find_server_by_name(destination)

        if not source_server:
            self.log(f"Source server '{source}' not found.", error=True)
            return {'success': False, 'output': f"Source server '{source}' not found."}

        if not destination_server:
            self.log(f"Destination server '{destination}' not found.", error=True)
            return {'success': False, 'output': f"Destination server '{destination}' not found."}

        destination_ip = destination_server.ip  # Ensure 'ip' attribute exists
        self.log(f"Executing ping from {source} ({source_server.ip}) to {destination} ({destination_ip})")

        try:
            # Example: ping -c 4 destination_ip
            result = source_server.container.exec_run(f"ping -c 4 {destination_ip}", stdout=True, stderr=True)
            output = result.output.decode()
            success = result.exit_code == 0
            self.log(f"Ping result: {output}" if success else f"Ping failed: {output}", error=not success)
            return {'success': success, 'output': output}
        except Exception as e:
            self.log(f"Exception during ping: {str(e)}", error=True)
            return {'success': False, 'output': str(e)}

    def traceroute(self, source: str, destination: str):
        """Traceroute from source server to destination server."""

        source_server = self.find_server_by_name(source)
        destination_server = self.find_server_by_name(destination)

        if not source_server:
            self.log(f"Source server '{source}' not found.", error=True)
            return {'success': False, 'output': f"Source server '{source}' not found."}

        if not destination_server:
            self.log(f"Destination server '{destination}' not found.", error=True)
            return {'success': False, 'output': f"Destination server '{destination}' not found."}

        destination_ip = destination_server.ip  # Ensure 'ip' attribute exists
        self.log(f"Executing traceroute from {source} ({source_server.ip}) to {destination} ({destination_ip})")

        try:
            # Example: traceroute destination_ip
            result = source_server.container.exec_run(f"traceroute {destination_ip}", stdout=True, stderr=True)
            output = result.output.decode()
            success = result.exit_code == 0
            self.log(f"Traceroute result: {output}" if success else f"Traceroute failed: {output}", error=not success)
            return {'success': success, 'output': output}
        except Exception as e:
            self.log(f"Exception during traceroute: {str(e)}", error=True)
            return {'success': False, 'output': str(e)}