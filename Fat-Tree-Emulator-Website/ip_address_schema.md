# Fat Tree IP Address Allocation Technical Specification

## 1. Address Space Selection
### 1.1 Range Selection
- Primary Range: 172.16.0.0/12 (172.16.0.0 - 172.31.255.255)
- Subnet Division: /30 subnets for point-to-point links

### 1.2 Capacity Analysis
Maximum topology size calculations:
```
Available Address Space: 172.16.0.0/12
- 16 second octets (172.16 - 172.31)
- 256 third octets per second octet
- 64 /30 subnets per third octet (256/4)
Total point-to-point links = 16 * 256 * 64 = 262,144
```

## 2. Network Segmentation

### 2.1 Core Layer (172.16.x.x)
- Starting Range: 172.16.0.0
- Allocation: Sequential /30 subnets
- Purpose: Core-to-Aggregation links

### 2.2 Pod Layer (172.20.x.x+)
Each pod contains:
- Aggregation layer links
- Edge layer links
- Server connections
- Sequential allocation within pod

### 2.3 Subnet Structure
Each /30 subnet provides:
```
Network: x.x.x.0
First Host: x.x.x.1
Second Host: x.x.x.2
Broadcast: x.x.x.3
```

## 3. Technical Implementation

### 3.1 Address Assignment Algorithm
```
1. Start with base 172.16.0.0
2. Increment through second octet (16-31)
3. For each second octet:
   - Use all 256 third octets
   - Divide each third octet into 64 /30 subnets
4. Track allocation using:
   - current_second_octet (16-31)
   - current_third_octet (0-255)
   - current_fourth_octet (increments by 4)
```

### 3.2 Subnet Allocation
Network devices receive addresses based on hierarchy:
```
Core Switches: Start at 172.16.0.0
Aggregation Switches: Start at 172.20.0.0
Edge Switches: Following Aggregation
Servers: Following Edge
```

## 4. Topology Scalability Limits

### 4.1 Maximum Scale (k=70)
```
Core Switches: (70/2)² = 1,225
Pods: 70
Per Pod:
- Aggregation Switches: 35
- Edge Switches: 35
- Servers per Edge: 35
Total Servers: 70 * 35 * 35 = 42,875
```

