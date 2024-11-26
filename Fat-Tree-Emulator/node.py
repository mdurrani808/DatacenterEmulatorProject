from __future__ import annotations
from enum import Enum
import os
import docker
from docker.types import Mount
from pyroute2 import IPRoute
import subprocess
from itertools import count
import time
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

    def __init__(self, name: str, config_base:str, base_ip_address: str = ""):
        self.name = name
        self.base_ip_address = base_ip_address # we use a default /24 subnet for everything
        self.connections = {} # mapping between the node that the current node is connected to and the assigned ip address (internally managed to make sure that there are no repeats starting at 1.)
        self.ip_counter = 1
        self.folder_path = f"{config_base}/{self.name}"
        self.container = None

    def get_ip_counter(self):
        """increments and returuns ip counter
            Use this whenever ip_counter neesd to be accessed to ensure that we never have repeat ip addresses
        Returns:
            str: the latest ip counter value
        """
        self.ip_counter += 1
        return str(self.ip_counter)
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
        """Creates a veth pair between two containers using their stored connection IPs
        
        Args:
            other_node (Node): The other container to connect to
        """
        
        
        container1 = self.container
        container2 = other_node.container
        print(f"Adding veth connection between {container1.name} and {container2.name}")
        
        pid1 = self.client.api.inspect_container(container1.id)['State']['Pid']
        pid2 = self.client.api.inspect_container(container2.id)['State']['Pid']
        
        # Create unique veth pair names using node names to avoid conflicts
        veth1 = f"{self.name}-to-{other_node.name}"[:15]  # Linux interface names limited to 15 chars
        veth2 = f"{other_node.name}-to-{self.name}"[:15]
        
        # Create the veth pair
        subprocess.run(['sudo', 'ip', 'link', 'add', veth1, 'type', 'veth', 'peer', 'name', veth2], check=True)
        
        # Move interfaces to their respective network namespaces
        subprocess.run(['sudo', 'ip', 'link', 'set', veth1, 'netns', str(pid1)], check=True)
        subprocess.run(['sudo', 'ip', 'link', 'set', veth2, 'netns', str(pid2)], check=True)
        
        # Get the specific IP addresses for this connection from the connections dictionary
        ip1 = self.connections[other_node]
        ip2 = other_node.connections[self]
        print(f"IP 1: {ip1}")
        print(f"IP 2: {ip2}")
        
        # Configure interfaces in container1
        container1.exec_run(f"ip addr add {ip1}/24 dev {veth1}")
        container1.exec_run(f"ip link set {veth1} up")
        
        # Configure interfaces in container2
        container2.exec_run(f"ip addr add {ip2}/24 dev {veth2}")
        container2.exec_run(f"ip link set {veth2} up")    
        time.sleep(1)
        print(f"\nPinging from {other_node.name} to {self.name} ({ip1})")
        result = self.container.exec_run(f"ping -c 3 {ip1}")
        print(result.output.decode())
        
        print(f"\nPinging from {self.name} to {other_node.name} ({ip2})")
        result = self.container.exec_run(f"ping -c 3 {ip2}")
        print(result.output.decode())
        

    def __repr__(self):
        toRet = f"{self.name}:\n IP: {self.base_ip_address} \nConnections: {len(self.connections)} nodes \n\n"
        for key in self.connections.keys():
            toRet += f"{key.name} -> {self.connections[key]}\n"
        return toRet

class Switch(Node):
    def __init__(self, type: SwitchType, asn: int, name: str,config_base:str, base_ip_address: str = ""):
        super().__init__(name=name, base_ip_address=base_ip_address, config_base=config_base)
        self.type = type
        self.asn = asn
    def generate_config_folder(self) -> None:
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

        # Configure interfaces
        for peer, ip_addr in self.connections.items():
            veth_name = f"{self.name}-to-{peer.name}"[:15]
            config.extend([
                f"interface {veth_name}",
                f" ip address {ip_addr}/24",
                "!"
            ])

        # Add prefix lists for local subnets
        for peer, ip_addr in self.connections.items():
            subnet = '.'.join(ip_addr.split('.')[:-1]) + '.0/24'
            config.extend([
                f"ip prefix-list LOCAL_NETS seq 5 permit {subnet}",
                "!"
            ])

        config.extend([
            "route-map ANNOUNCE_LOCAL permit 10",
            " match ip address prefix-list LOCAL_NETS",
            "!"
        ])

        # BGP configuration using actual interface IPs
        config.extend([
            f"router bgp {self.asn}",
            f" bgp router-id {self.base_ip_address.split('.')[0]}.{self.base_ip_address.split('.')[1]}.{self.base_ip_address.split('.')[2]}.1",
            " bgp log-neighbor-changes",
            " no bgp ebgp-requires-policy",
            " timers bgp 3 9"
        ])

        # Configure neighbors using actual peer IPs
        for peer, _ in self.connections.items():
            if isinstance(peer, Switch):
                peer_ip = self.connections[peer].split('/')[0]  # Use actual interface IP
                config.extend([
                    f" neighbor {peer_ip} remote-as {peer.asn}",
                ])

        # Address family configuration with neighbor activation
        config.extend([
            " address-family ipv4 unicast",
            "  redistribute connected route-map ANNOUNCE_LOCAL"
        ])

        for peer, _ in self.connections.items():
            if isinstance(peer, Switch):
                peer_ip = self.connections[peer].split('/')[0]
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
        toRet = f"{self.name}:\n IP: {self.base_ip_address} \nConnections: {len(self.connections)} nodes\n ASN {self.asn} \n\n"
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
    def __init__(self, name: str, config_base:str, base_ip_address: str = ""):
        super().__init__(name=name, base_ip_address=base_ip_address, config_base=config_base)
        
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
    
    