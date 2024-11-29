from typing import List
from node import Switch, Server

class Pod:
    def __init__(self, pod_num: int):
        self.pod_num = pod_num
        
        self.aggregation_switches: List[Switch] = []
        self.edge_switches: List[Switch] = []
        self.servers: List[Server] = []
        
        
    def connect_internal(self):
        """Connect all switches within the pod and connect servers to their designated edge switches"""
        # Connect each edge switch to each aggregation switch
        for edge_switch in self.edge_switches:
            for agg_switch in self.aggregation_switches:
                edge_switch.register_connection(agg_switch)

        # Connect servers to their designated edge switch
        servers_per_edge = len(self.servers) // len(self.edge_switches)
        
        for edge_idx, edge_switch in enumerate(self.edge_switches):
            start_idx = edge_idx * servers_per_edge
            end_idx = start_idx + servers_per_edge
            
            # Connect only the designated servers to this edge switch
            for server in self.servers[start_idx:end_idx]:
                edge_switch.register_connection(server)
                server.register_connection(edge_switch)