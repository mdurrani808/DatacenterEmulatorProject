class Node:
    def __init__(self, id, level=0):
        self.id = id
        self.level = level
        self.connections = []

    def add_connection(self, other_node):
        if other_node not in self.connections:
            self.connections.append(other_node)
            other_node.add_connection(self)

    def __repr__(self):
        return f"Node({self.id}, Level={self.level}, Connections={len(self.connections)})"


class FatTree:
    def __init__(self, k):
        self.k = k
        self.num_core_switches = (k // 2) ** 2
        self.num_pods = k
        self.num_agg_switches_per_pod = k // 2
        self.num_edge_switches_per_pod = k // 2
        self.num_servers_per_edge_switch = k // 2

        # Storage for all types of nodes
        self.nodes = {"Core": [], "Aggregate": [], "Edge": [], "Servers": []}
        self.build_fat_tree()

    def build_fat_tree(self):
        core_level = 2
        agg_level = 1
        edge_level = 0
        server_level = -1

        # Create core switches
        for i in range(self.num_core_switches):
            core_node = Node(id=f"Core-{i}", level=core_level)
            self.nodes["core"].append(core_node)

        # Create aggregation and edge switches, then connect them
        for pod in range(self.num_pods):
            # Create aggregation switches for this pod
            agg_switches = []
            for i in range(self.num_agg_switches_per_pod):
                agg_switch = Node(id=f"Agg-{pod}-{i}", level=agg_level)
                agg_switches.append(agg_switch)
                self.nodes["aggregate"].append(agg_switch)

            # Create edge switches for this pod
            edge_switches = []
            for i in range(self.num_edge_switches_per_pod):
                edge_switch = Node(id=f"Edge-{pod}-{i}", level=edge_level)
                edge_switches.append(edge_switch)
                self.nodes["edge"].append(edge_switch)

            # Connect each aggregation switch to core switches
            for agg_idx, agg_switch in enumerate(agg_switches):
                # index and the actual switch
                
                # k = 4
                # Ex: agg switch 0, connects up to before switch 2
                # Then: agg switch 1, connects up to before switch 4 (in this case there is no 4)
                
                for core_idx in range(
                    agg_idx * (self.k // 2), (agg_idx + 1) * (self.k // 2)
                ):
                    agg_switch.add_connection(self.nodes["core"][core_idx]) 

            # Connect each edge switch to all aggregation switches in the pod
            for edge_switch in edge_switches:
                for agg_switch in agg_switches:
                    edge_switch.add_connection(agg_switch)

            # Connect servers to each edge switch
            for edge_idx, edge_switch in enumerate(edge_switches):
                for server_id in range(self.num_servers_per_edge_switch):
                    
                    # Create Server Node
                    server = Node(id=f"Server-{pod}-{edge_idx}-{server_id}", level=server_level)
                    
                    # add server
                    edge_switch.add_connection(server)
                    self.nodes["servers"].append(server)

    def pretty_print(self):
        for node_type, node_list in self.nodes.items():
            print(f"--- {node_type} Nodes ---")
            for node in node_list:
                print(node)


# Example Usage
k = 4  # For a k=4 Fat Tree
fat_tree = FatTree(k)
fat_tree.pretty_print()
