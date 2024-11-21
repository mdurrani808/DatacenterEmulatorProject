from typing import List
from node import Switch, Server

class Pod:
    def __init__(self, pod_num: int, num_servers_per_edge: int):
        self.pod_num = pod_num
        self.num_servers_per_edge = num_servers_per_edge
        
        self.aggregation_switches: List[Switch] = []
        self.edge_switches: List[Switch] = []
        self.servers: List[Server] = []
        
        
    def connect_internal(self):
        """Connect all switches within the pod and create servers"""
        # Connect each edge switch to each aggregation switch
        for edge_switch in self.edge_switches:
            for agg_switch in self.aggregation_switches:
                edge_switch.add_connection(agg_switch)

        # Create and connect servers to edge switches
        for edge_switch in self.edge_switches:
            for server in self.servers:
                edge_switch.add_connection(server)