from __future__ import annotations
from enum import Enum
import os
import docker
from docker.types import Mount
from pyroute2 import IPRoute
import subprocess
from itertools import count
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
        ip_counter += 1
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
        
        # Configure interfaces in container1
        container1.exec_run(f"ip addr add {ip1}/24 dev {veth1}")
        container1.exec_run(f"ip link set {veth1} up")
        
        # Configure interfaces in container2
        container2.exec_run(f"ip addr add {ip2}/24 dev {veth2}")
        container2.exec_run(f"ip link set {veth2} up")    
    def __repr__(self):
        return f"{self.name}:\n IP: {self.base_ip_address} \nConnections: {len(self.connections)} nodes\n"

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
        """
        Generate FRR configuration for a switch based on its type, ASN, and connections.
        Returns a string containing the complete FRR configuration.
        """
        def get_ip_and_prefix(ip_addr: str) -> tuple:
            if '/' in ip_addr:
                return ip_addr.split('/')
            return ip_addr, '24' # default 24
        
        def get_network_address(ip_addr: str, prefix_len: str) -> str:
            ip_parts = ip_addr.split('.')
            if prefix_len == '24':
                return f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
            return f"{ip_addr}/{prefix_len}"

        config = [
            "frr version 8.4",
            "frr defaults traditional",
            f"hostname {self.name}",
            "no ipv6 forwarding",
            "ip forwarding",
            "!"
        ]

        local_networks = []
        for i, connection in enumerate(self.connections):
            ip, prefix = get_ip_and_prefix(self.base_ip_address)
            config.extend([
                f"interface eth{i}",
                f" ip address {self.base_ip_address}/24",
                "!"
            ])
            local_networks.append(get_network_address(ip, prefix))

        # prefix lists for local networks
        for i, network in enumerate(local_networks):
            config.extend([
                f"ip prefix-list LOCAL_NETS seq {(i+1)*5} permit {network}",
            ])
        config.append("!")

        #route-map for local network announcement
        config.extend([
            "route-map ANNOUNCE_LOCAL permit 10",
            " match ip address prefix-list LOCAL_NETS",
            "!"
        ])

        config.extend([
            f"router bgp {self.asn}",
            f" bgp router-id {self.base_ip_address.split('/')[0]}",
            " bgp log-neighbor-changes",
        ])

        if self.type == SwitchType.EDGE:
            config.append(" no bgp default ipv4-unicast")
        elif self.type == SwitchType.CORE:
            config.append(" no bgp ebgp-requires-policy")

        # BGP timer configurations
        config.extend([
            " timers bgp 3 9",
            "!"
        ])

        # configure peer groups based on switch type
        if self.type in [SwitchType.CORE, SwitchType.AGGREGATE]:
            config.extend([
                " neighbor PEERS peer-group",
                " neighbor PEERS advertisement-interval 0",
                " neighbor PEERS timers connect 5",
                "!"
            ])

        # neighbors
        for connection in self.connections:
            neighbor_ip = connection.base_ip_address.split('/')[0]
            if isinstance(connection, Switch):
                if self.type in [SwitchType.CORE, SwitchType.AGGREGATE]:
                    config.extend([
                        f" neighbor {neighbor_ip} peer-group PEERS",
                        f" neighbor {neighbor_ip} remote-as {connection.asn}",
                    ])
                else:
                    config.extend([
                        f" neighbor {neighbor_ip} remote-as {connection.asn}",
                        f" neighbor {neighbor_ip} timers connect 5",
                    ])

        config.extend([
            " !",
            " address-family ipv4 unicast",
            "  redistribute connected route-map ANNOUNCE_LOCAL"
        ])

        if self.type in [SwitchType.CORE, SwitchType.AGGREGATE]:
            config.append("  neighbor PEERS activate")
        else:
            for connection in self.connections:
                if isinstance(connection, Switch):
                    config.append(f"  neighbor {connection.base_ip_address.split('/')[0]} activate")

        if self.type != SwitchType.EDGE:
            config.append("  maximum-paths 64")

        config.extend([
            " exit-address-family",
            "!",
            "line vty",
            "!"
        ])

        return "\n".join(config)
    
    def create_frr_container(self):
        # Define container configuration
        container_config = {
            'image': 'frrouting/frr:latest',
            'name': self.name,
            'network_mode': 'none',
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
    
    