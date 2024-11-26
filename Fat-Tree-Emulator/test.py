import docker
from dataclasses import dataclass
from typing import Dict, List, Optional
import subprocess
import time

@dataclass
class ContainerConfig:
    name: str
    image: str
    command: str = "tail -f /dev/null"
    environment: Dict[str, str] = None
    base_ip_address: str = None

class DockerContainer:
    def __init__(self, config: ContainerConfig):
        self.config = config
        self.client = docker.from_env()
        self.container = None
        
    def create(self) -> docker.models.containers.Container:
        self.container = self.client.containers.run(
            self.config.image,
            name=self.config.name,
            command=self.config.command,
            detach=True,
            environment=self.config.environment,
            privileged=True,  # Need privileged mode to configure network
            network_mode="none"  # Start with no network
        )
        print(f"Created container: {self.config.name}")
        return self.container
    
    def remove(self):
        if self.container:
            self.container.remove(force=True)
            print(f"Removed container: {self.config.name}")
    
    def get_pid(self) -> str:
        if self.container:
            return self.client.api.inspect_container(self.container.id)['State']['Pid']
        return None

class VethConnector:
    def __init__(self):
        self.containers: Dict[str, DockerContainer] = {}
    
    def add_container(self, config: ContainerConfig):
        container = DockerContainer(config)
        self.containers[config.name] = container
        container.create()
    
    def connect_containers(self, container1_name: str, container2_name: str):
        container1 = self.containers[container1_name]
        container2 = self.containers[container2_name]
        
        # Get container PIDs
        pid1 = container1.get_pid()
        pid2 = container2.get_pid()
        
        veth1 = f"veth_{container1_name}"
        veth2 = f"veth_{container2_name}"
        
        try:
            # Create veth pair
            subprocess.run(["sudo", "ip", "link", "add", veth1, "type", "veth", "peer", "name", veth2], check=True)
            
            # Move interfaces to containers' network namespaces
            subprocess.run(["sudo", "ip", "link", "set", veth1, "netns", str(pid1)], check=True)
            subprocess.run(["sudo", "ip", "link", "set", veth2, "netns", str(pid2)], check=True)
            
            # Configure interfaces in container1
            container1.container.exec_run(f"ip addr add {container1.config.base_ip_address}/24 dev {veth1}")
            container1.container.exec_run(f"ip link set {veth1} up")
            
            # Configure interfaces in container2
            container2.container.exec_run(f"ip addr add {container2.config.base_ip_address}/24 dev {veth2}")
            container2.container.exec_run(f"ip link set {veth2} up")
            
            print(f"Created veth pair between {container1_name} and {container2_name}")
            
        except subprocess.CalledProcessError as e:
            print(f"Error creating veth pair: {e}")
            raise
    
    def install_ping(self, container_name: str):
        container = self.containers[container_name].container
        container.exec_run("apt-get update")
        container.exec_run("apt-get install -y inetutils-ping")
    
    def ping_test(self, from_container: str, to_container: str, count: int = 4):
        source = self.containers[from_container]
        target = self.containers[to_container]
        target_ip = target.config.base_ip_address
        
        print(f"\nPinging from {from_container} to {to_container} ({target_ip})")
        result = source.container.exec_run(f"ping -c {count} {target_ip}")
        print(result.output.decode())
    
    def cleanup(self):
        print("\nCleaning up resources...")
        for container in self.containers.values():
            container.remove()
        print("Cleanup complete")

def main():
    tester = VethConnector()
    
    try:
        # Define container configurations with IP addresses
        container1_config = ContainerConfig(
            name="container1",
            image="nicolaka/netshoot:latest",
            base_ip_address="192.168.100.1"
        )
        
        container2_config = ContainerConfig(
            name="container2",
            image="nicolaka/netshoot:latest",
            base_ip_address="192.168.100.2"
        )
        
        # Create containers
        tester.add_container(container1_config)
        tester.add_container(container2_config)
        
        # Create veth pair connection
        tester.connect_containers("container1", "container2")
        
        # Show network information
        print("\nNetwork Information:")
        for name, container in tester.containers.items():
            print(f"{name} IP: {container.config.base_ip_address}")
        
        # Run ping tests
        tester.ping_test("container1", "container2")
        tester.ping_test("container2", "container1")
        
        # Keep containers running for manual inspection
        input("\nPress Enter to cleanup...")
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        tester.cleanup()

if __name__ == "__main__":
    main()