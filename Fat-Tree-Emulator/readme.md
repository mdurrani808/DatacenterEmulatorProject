# Fat-Tree-Emulator

To clean everything up:

```bash
 docker stop $(docker ps -a -q) && docker rm $(docker ps -a -q)&& ip netns | xargs -I {} sudo ip netns delete -y {} && docker network prune
 ```