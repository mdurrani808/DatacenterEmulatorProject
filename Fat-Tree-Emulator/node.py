from __future__ import annotations
from enum import Enum
import os
import docker
from docker.types import Mount
from pyroute2 import IPRoute
import subprocess

class SwitchType(Enum):
    CORE = 1
    AGGREGATE = 2
    EDGE = 3


class Node:
    # shared across all nodes
    client = docker.from_env()
    client.images.pull('frrouting/frr:latest')
    client.images.pull('nicolaka/netshoot:latest')
    ip = IPRoute()

    def __init__(self, name: str, config_base:str):
        self.name = name
        self.connections = {} # mapping between the node that the current node is connected to and the assigned ip address (internally managed to make sure that there are no repeats starting at 1.)
        self.ip_counter = 1
        self.folder_path = f"{config_base}/{self.name}"
        self.container = None

    def register_connection(self, other_node: Node):
        """
        Add bidirectional connection between nodes
        NOTE: This is purely virtual, this is not creating the ethernet pair. For that, you must call establish_veth_link
        """
        if other_node not in self.connections:
            self.connections[other_node] = ""
            if self not in other_node.connections:
                other_node.connections[self] = ""
    

    def establish_veth_link(self, other_node: Node):
        """Creates a veth pair between two containers using their stored connection IPs"""
        container1 = self.container
        container2 = other_node.container
        print(f"Adding veth connection between {container1.name} and {container2.name}")
        
        pid1 = self.client.api.inspect_container(container1.id)['State']['Pid']
        pid2 = self.client.api.inspect_container(container2.id)['State']['Pid']
        
        # Create unique veth pair names using node names to avoid conflicts
        
        # we limit to 15 here because of the linux limitations
        veth1 = f"{self.name}{other_node.name}"[:15]
        veth2 = f"{other_node.name}{self.name}"[:15]
        
        # Create the veth pair
        subprocess.run(['sudo', 'ip', 'link', 'add', veth1, 'type', 'veth', 'peer', 'name', veth2], check=True)
        
        # Move interfaces to their respective network namespaces
        subprocess.run(['sudo', 'ip', 'link', 'set', veth1, 'netns', str(pid1)], check=True)
        subprocess.run(['sudo', 'ip', 'link', 'set', veth2, 'netns', str(pid2)], check=True)
        
        # Get the specific IP addresses for this connection
        ip1 = self.connections[other_node]
        ip2 = other_node.connections[self]
        print(f"IP 1: {ip1}")
        print(f"IP 2: {ip2}")
        
        # Configure interfaces with /30 subnet mask
        container1.exec_run(f"ip addr add {ip1}/30 dev {veth1}")
        container1.exec_run(f"ip link set {veth1} up")
        
        container2.exec_run(f"ip addr add {ip2}/30 dev {veth2}")
        container2.exec_run(f"ip link set {veth2} up")
        
        # for servers we need to add a default gateway so that we actually send traffic to the switch it is connected to 
        if isinstance(self, Server):
            self.container.exec_run(f"ip route add default via {ip2}")
        elif isinstance(other_node, Server):
            other_node.container.exec_run(f"ip route add default via {ip1}")
        

    def __repr__(self):
        toRet = f"{self.name}:\n \nConnections: {len(self.connections)} nodes \n\n"
        for key in self.connections.keys():
            toRet += f"{key.name} -> {self.connections[key]}\n"
        return toRet

class Switch(Node):
    def __init__(self, type: SwitchType, asn: int, name: str,config_base:str):
        super().__init__(name=name, config_base=config_base)
        self.type = type
        self.asn = asn
    def generate_config_folder(self) -> None:
        """Generates config folder with frr routing and daemon file
        """
        if not os.path.exists(self.folder_path):
            os.makedirs(self.folder_path)
        frr_conf_file = open(f"{self.folder_path}/frr.conf", "w")
        frr_conf_file.write(self.generate_frr_config())
        frr_conf_file.close()
        
        daemon_file = open(f"{self.folder_path}/daemons", "w")
        daemon_file.write(self.generate_daemon())
        daemon_file.close()
    
    
    
    def generate_daemon(self) -> str:
        """Generates a string for the daemon file

        Returns:
            str: string representing a daemon file
        """
        return "bgpd=yes\nzebra=yes"
    
    def generate_frr_config(self) -> str:
        config = [
            "frr version 8.4",
            "frr defaults traditional",
            f"hostname {self.name}",
            "no ipv6 forwarding",
            "ip forwarding",
            "!"
        ]

        # Configure interfaces (avoid duplicates)
        seen_interfaces = set()
        for peer, ip_addr in self.connections.items():
            veth_name = f"{self.name}{peer.name}"[:15]
            if veth_name not in seen_interfaces:
                seen_interfaces.add(veth_name)
                config.extend([
                    f"interface {veth_name}",
                    f" ip address {ip_addr}/30",
                    "!"
                ])

        # Add prefix lists with incrementing sequence numbers
        seq_num = 5
        for peer, ip_addr in self.connections.items():
            # Calculate network address for /30
            ip_parts = ip_addr.split('.')
            network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{int(ip_parts[3]) & 0xFC}"
            config.extend([
                f"ip prefix-list LOCAL_NETS seq {seq_num} permit {network}/30",
                "!"
            ])
            seq_num += 5

        config.extend([
            "route-map ANNOUNCE_LOCAL permit 10",
            " match ip address prefix-list LOCAL_NETS",
            "!"
        ])

        # BGP configuration
        config.extend([
            f"router bgp {self.asn}",
            f" bgp router-id {sorted(list(self.connections.values()))[-1]}",
            " bgp log-neighbor-changes",
            " no bgp ebgp-requires-policy",
            " timers bgp 3 9"
        ])

        # Configure neighbors
        for peer, _ in self.connections.items():
            if isinstance(peer, Switch):
                peer_ip = peer.connections[self]
                config.extend([
                    f" neighbor {peer_ip} remote-as {peer.asn}",
                ])

        # Address family configuration
        config.extend([
            " address-family ipv4 unicast",
            "  network 0.0.0.0/0",  # Advertise default route
            "  redistribute connected route-map ANNOUNCE_LOCAL"
        ])

        for peer, _ in self.connections.items():
            if isinstance(peer, Switch):
                peer_ip = peer.connections[self]
                config.append(f"  neighbor {peer_ip} activate")

        config.extend([
            "  maximum-paths 64",
            " exit-address-family",
            "!",
            "line vty",
            "!"
        ])

        return "\n".join(config)
    
    def __repr__(self):
        toRet = f"{self.name}:\nConnections: {len(self.connections)} nodes\n ASN {self.asn} \n\n"
        for key in self.connections.keys():
            toRet += f"{key.name} -> {self.connections[key]}\n"
        return toRet
    
    
    def create_frr_container(self):
        # Define container configuration
        container_config = {
            'image': 'frrouting/frr:latest',
            'name': self.name,
            'network_mode': 'none',
            'privileged':True,
            'cap_add': ['NET_ADMIN', 'SYS_ADMIN'],
            'mounts': [
                Mount(
                    target='/etc/frr',
                    source=self.folder_path,
                    type='bind'
                )
            ]
        }
                
        # start container
        self.container = Node.client.containers.create(**container_config)
        self.container.start()
        
        print(f"Succesfully started {self.container.name}!")


class Server(Node):
    def __init__(self, name: str, config_base:str):
        super().__init__(name=name, config_base=config_base)
        
    def create_container(self):
        # Define container configuration
        container_config = {
            'image': 'nicolaka/netshoot:latest',
            'name': self.name,
            'network_mode': 'none',
            'cap_add': ['NET_ADMIN', 'SYS_ADMIN'],
            'privileged':True,
            'command':"tail -f /dev/null"
        }
                
        # start container
        self.container = Node.client.containers.create(**container_config)
        self.container.start()
        
        print(f"Succesfully started {self.container.name}!")
    
    def ping_server(self, other_server: Server, count: int = 3) -> bool:
        """Pings another server in the fat tree topology
        
        Args:
            other_server (Server): The server to ping
            count (int): Number of ping attempts
        
        Returns:
            bool: True if ping successful, False otherwise
        """
        if not self.container or not other_server.container:
            print(f"Error: One or both containers not running")
            return False
            
        # Get the IP of the other server's connection to its edge switch
        # Since servers only have one connection, we can get the first (and only) one
        target_ip = list(other_server.connections.values())[0]
        
        print(f"\nPinging from {self.name} to {other_server.name} ({target_ip})")
        result = self.container.exec_run(f"ping -c {count} {target_ip}")
        print(result.output.decode())
        
        # Check if ping was successful
        return result.exit_code == 0
    