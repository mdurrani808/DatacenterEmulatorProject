# Fat-Tree-Emulator-Website

## Set up (Tested on fresh Ubuntu 22.04 VM)

Clone this repository
```bash
git clone https://github.com/mdurrani808/DatacenterEmulatorProject.git
cd DatacenterEmulatorProject/Fat-Tree-Emulator-Website
```

Install necessary packages
```bash
sudo apt-get update
sudo apt-get install python3 pip docker docker-compose graphviz graphviz-dev
pip install -r requirements.txt
```

Add user to docker group
```bash
sudo usermod -aG docker $USER
```

Log out and login again

```bash
cd DatacenterEmulatorProject/Fat-Tree-Emulator-Website
```

Run the code

```bash
python3 app.py
```

You can now access the website at port `5000`

## To clean everything up:

```bash
 docker stop $(docker ps -a -q) && docker rm $(docker ps -a -q)&& ip netns | xargs -I {} sudo ip netns delete -y {} && docker network prune
 ```
