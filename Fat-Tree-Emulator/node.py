
# node.py
from __future__ import annotations
from enum import Enum

class SwitchType(Enum):
    CORE = 1
    AGGREGATE = 2
    EDGE = 3
    
class Node:
    def __init__(self, name: str, ip_address: str = ""):
        self.name = name
        self.ip_address = ip_address
        self.connections = []

    def add_connection(self, other_node: Node):
        """Add bidirectional connection between nodes"""
        if other_node not in self.connections:
            self.connections.append(other_node)
            if self not in other_node.connections:
                other_node.connections.append(self)

    def __repr__(self):
        return f"{self.name} (Connections: {len(self.connections)})"

class Switch(Node):
    def __init__(self, type: SwitchType, asn: int, name: str, ip_address: str = ""):
        super().__init__(name=name, ip_address=ip_address)
        self.type = type
        self.asn = asn

class Server(Node):
    def __init__(self, name: str, ip_address: str = ""):
        super().__init__(name=name, ip_address=ip_address)