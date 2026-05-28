#!/usr/bin/env python3
"""
V2X Deploy System - v6.0 (Interactive CARLA Sim)
Conecta 2030

Features:
1. Sequential Logic: Connects to RSU -> Sends File -> Disconnects -> Connects to OBU...
2. Silent Transfer: Uses SSH Pipeline (cat > file) for invisible transfer locally.
3. Final Execution: Spawns RSU/OBU windows.
4. CARLA Sim (Interactive): Spawns a control window where you can manually send alerts.
"""

import os
import sys
import time
import json
import socket
import random
import argparse
import subprocess
import threading
import platform
import paramiko

# Configuration
RSU_IP = ""  # IP virá estritamente do DDNS
RSU_USER = "root"
RSU_PASS = "Conect@2024"
RSU_PORT = 8080

OBU_IP = "192.168.0.53"
OBU_USER = "root"
OBU_PASS = "Conect@24"
OBU_PORT = 8080

CARLA_IP = "2804:214:8780:3d5::633"  # IPv6 do PC rodando CARLA e DDNS

# DDNS Configuration (servidor roda na máquina CARLA)
DDNS_URL = f"http://[{CARLA_IP}]:5000"
DDNS_RSU_NAME = "rsu-v2x"

LOCAL_DIR = os.getcwd()

# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

# ==========================================
# UTILS
# ==========================================

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.0.100"

def set_terminal_title(title):
    if platform.system().lower() == "windows":
        os.system(f"title {title}")
    else:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()

def log(msg, color=RESET):
    try:
        print(f"{color}{msg}{RESET}")
    except UnicodeEncodeError:
        # Fallback for Windows consoles that don't support emojis
        safe_msg = msg.encode('ascii', 'replace').decode('ascii')
        print(f"{color}{safe_msg}{RESET}")

def check_ping(ip):
    """Checks if the device is reachable via Ping. Handles IPv6."""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    
    # Use ping6 on Linux if it's an IPv6 address
    cmd_name = 'ping'
    if platform.system().lower() != 'windows' and ':' in ip:
        cmd_name = 'ping6'
        
    command = [cmd_name, param, '1', ip]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        return False

def register_rsu_in_ddns(ssh_client):
    """Gets RSU IPv6 from wwan0 and registers it in the DDNS server."""
    try:
        log("  📡 Getting RSU IPv6 address...", CYAN)
        stdin, stdout, stderr = ssh_client.exec_command(
            "ip -6 addr show wwan0 scope global | grep inet6 | awk '{print $2}' | cut -d/ -f1 | head -1"
        )
        rsu_ipv6 = stdout.read().decode().strip()
        
        if not rsu_ipv6:
            log("  ⚠️ RSU has no global IPv6 on wwan0, trying wlan0...", YELLOW)
            stdin, stdout, stderr = ssh_client.exec_command(
                "ip -6 addr show wlan0 scope global | grep inet6 | awk '{print $2}' | cut -d/ -f1 | head -1"
            )
            rsu_ipv6 = stdout.read().decode().strip()
        
        if not rsu_ipv6:
            log("  ⚠️ No global IPv6 found on RSU. DDNS registration skipped.", YELLOW)
            return False
        
        log(f"  📡 RSU IPv6: {rsu_ipv6}", GREEN)
        
        # Register from deploy machine to CARLA DDNS directly
        import urllib.request
        url = f"{DDNS_URL}/update?name={DDNS_RSU_NAME}&ip={rsu_ipv6}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                result = response.read().decode().strip()
            
            if result == "OK":
                log(f"  ✅ RSU registered in DDNS: {DDNS_RSU_NAME} → {rsu_ipv6}", GREEN)
                return True
            else:
                log(f"  ⚠️ DDNS registration response: {result}", YELLOW)
                return False
        except Exception as e:
            log(f"  ⚠️ DDNS registration failed (Is v2x_ddns_server.py running on {CARLA_IP}?): {e}", YELLOW)
            return False
    except Exception as e:
        log(f"  ⚠️ DDNS registration failed: {e}", YELLOW)
        return False




def recompile_binaries():
    """
    Uses the local 'arm32-builder' Docker image to cross-compile the
    source files in sdk_examples/conecta/ into the current directory.
    """
    log("\n[0/3] Recompiling Binaries (Docker)...", YELLOW)
    
    cwd = os.getcwd()
    
    # Path to SDK within the mounted workspace
    # Note: We use relative path from the mount point (/workspace)
    # The SDK path found was: commsignia-sdk\Unplugged-RT-y20.41.3...\Unplugged-RT-y20.41.3...\include
    
    # Let's verify the exact folder name from previous list_dir
    # Root: commsignia-sdk
    # Sub: Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk
    # Sub: Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk
    
    sdk_base = "commsignia-sdk/Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk/Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk"
    inc_path = f"{sdk_base}/include"
    lib_path = f"{sdk_base}/lib"
    
    # Common flags
    # We add inc_path/asn1 because some headers are included as <asn1defs.h> directly
    flags = f"-static -s -I {inc_path} -I {inc_path}/asn1 -L {lib_path} -lits-asnsdk -lits-rem -lpthread -lrt -lstdc++ -lm"
    
    # Docker base command
    docker_base = "sudo docker" if platform.system().lower() == "linux" else "docker"

    # 1. Compile RSU Server (fac_alert)
    log("  🔨 Compiling RSU Server (fac_alert)...", CYAN)
    cmd_rsu = (
        f'{docker_base} run --rm -v "{cwd}:/workspace" arm32-builder '
        f'arm-linux-gnueabihf-gcc sdk_examples/conecta/fac_alert.c '
        f'-o fac_alert {flags}'
    )
    res_rsu = subprocess.run(cmd_rsu, shell=True)
    
    if res_rsu.returncode != 0:
        log("  ❌ Compilation Failed for RSU Server!", RED)
        return False
    else:
        # Verify freshness
        ts = time.strftime('%H:%M:%S', time.localtime(os.path.getmtime("fac_alert")))
        size = os.path.getsize("fac_alert")
        log(f"  ✅ RSU Server Compiled. (Time: {ts}, Size: {size} bytes)", GREEN)

    # 2. Compile OBU Server (obu_alert_server)
    log("  🔨 Compiling OBU Server (obu_alert_server)...", CYAN)
    cmd_obu = (
        f'{docker_base} run --rm -v "{cwd}:/workspace" arm32-builder '
        f'arm-linux-gnueabihf-gcc sdk_examples/conecta/obu_alert_server.c '
        f'-o obu_alert_server {flags}'
    )
    res_obu = subprocess.run(cmd_obu, shell=True)
    
    if res_obu.returncode != 0:
        log("  ❌ Compilation Failed for OBU Server!", RED)
        return False
    else:
        ts = time.strftime('%H:%M:%S', time.localtime(os.path.getmtime("obu_alert_server")))
        size = os.path.getsize("obu_alert_server")
        log(f"  ✅ OBU Server Compiled. (Time: {ts}, Size: {size} bytes)", GREEN)
        
    return True

def get_ssh_client(ip, user, password, retries=3):
    """Creates and returns a connected Paramiko SSH client with retries."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    for attempt in range(1, retries + 1):
        try:
            # Force legacy algorithms for older embedded devices
            client.connect(
                ip, 
                username=user, 
                password=password, 
                timeout=15,  # Increased timeout for flaky IPv6
                look_for_keys=False, 
                allow_agent=False,
                disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
                banner_timeout=60
            )
            return client
        except Exception as e:
            if attempt < retries:
                log(f"  ⚠️ SSH connection failed (Attempt {attempt}/{retries}): {e}. Retrying...", YELLOW)
                time.sleep(2)
            else:
                log(f"  ❌ SSH connection ultimately failed: {e}", RED)
                
    return None

# ==========================================
# TRANSFER LOGIC
# ==========================================

def transfer_file_robust(client, local_path, remote_path):
    """
    Robust file transfer for unstable IPv6 cellular connections.
    Compresses the file locally using GZIP, transfers via Base64 stream,
    and decompresses remotely. This reduces size by ~4x, avoiding timeouts.
    """
    import gzip
    import base64
    
    filename = os.path.basename(local_path)
    full_remote = os.path.join(remote_path, filename).replace("\\", "/")
    gz_remote = full_remote + ".gz"
    
    # 0. Kill existing instances
    client.exec_command(f"killall -9 {filename} >/dev/null 2>&1")
    client.exec_command(f"rm -f {full_remote} {gz_remote} >/dev/null 2>&1")
    time.sleep(1.0)
    
    local_size = os.path.getsize(local_path)
    
    # 1. Compress the file in memory
    log(f"  ➡️  Compressing {filename}...", YELLOW)
    with open(local_path, "rb") as f_in:
        raw_data = f_in.read()
    
    gz_data = gzip.compress(raw_data)
    gz_size = len(gz_data)
    
    log(f"  ➡️  Transferring compressed {filename} ({gz_size} bytes, originally {local_size})...", YELLOW)
    
    try:
        # Start base64 decoding to the .gz file on remote side
        cmd = f"base64 -d > {gz_remote}"
        stdin, stdout, stderr = client.exec_command(cmd)
        
        # Send in very small chunks to respect MTU
        chunk_size = 1024
        for i in range(0, len(gz_data), chunk_size):
            chunk = gz_data[i:i+chunk_size]
            encoded = base64.b64encode(chunk)
            try:
                stdin.write(encoded)
                stdin.flush()
                time.sleep(0.01) # Critical delay
            except Exception as e:
                log(f"  ❌ Base64 Pipe Exception: {e}", RED)
                return False
                    
        stdin.channel.shutdown_write()
        time.sleep(1.0)
        
        # 2. Decompress remotely
        log(f"  ➡️  Decompressing on target...", YELLOW)
        client.exec_command(f"gzip -d {gz_remote}")
        time.sleep(0.5)
        
        # Verify Size
        stdin, stdout, stderr = client.exec_command(f"wc -c < {full_remote}")
        remote_size_str = stdout.read().decode().strip()
        
        if not remote_size_str.isdigit():
            log(f"  ❌ Decompression failed! Output: {remote_size_str}", RED)
            return False
            
        remote_size = int(remote_size_str)
        
        if local_size == remote_size:
            log(f"  ✅ Transfer Verified via Compressed Base64 ({remote_size} bytes)", GREEN)
            client.exec_command(f"chmod +x {full_remote}")
            return True
        else:
            log(f"  ❌ Size mismatch! Local: {local_size}, Remote: {remote_size}", RED)
            return False
            
    except Exception as e:
        log(f"  ❌ Transfer Exception: {e}", RED)
        return False

# ==========================================
# SIMULATION LOGIC (CARLA INTERACTIVE)
# ==========================================

# --------------------------
# Message Generation Helpers
# Structs reference: modular_us/*.h
# --------------------------

def create_bsm(msg_count):
    """Generates a Basic Safety Message (BSM) JSON wrapped in MessageFrame.
    MessageFrame { messageId: 20, value: BasicSafetyMessage }
    Struct ref: bsm_types.h -> US_BSMcoreData, US_BasicSafetyMessage
    """
    sec_mark = int((time.time() * 1000) % 60000)
    # FORCING BSM LOCATION TO MATCH PSM LOCATION FOR IMMEDIATE COLLISION
    lat_asn = -235497100
    lon_asn = -466327200
    speed_asn = 750  # 15 m/s

    json_data = {
        "bsm": {
            "messageId": 20,
            "value": {
                "coreData": {
                    "msgCnt": msg_count % 128,
                    "id": "A1B2C3D4",
                    "secMark": sec_mark,
                    "lat": lat_asn,
                    "long": lon_asn,
                    "elev": 100,
                    "accuracy": {
                        "semiMajor": 40,
                        "semiMinor": 40,
                        "orientation": 0
                    },
                    "transmission": "forwardGears",
                    "speed": speed_asn,
                    "heading": 0,
                    "angle": 0,
                    "accelSet": {
                        "long": 0,
                        "lat": 0,
                        "vert": 0,
                        "yaw": 0
                    },
                    "brakes": {
                        "wheelBrakes": "00",
                        "traction": "unavailable",
                        "abs": "unavailable",
                        "scs": "unavailable",
                        "brakeBoost": "unavailable",
                        "auxBrakes": "unavailable"
                    },
                    "size": {
                        "width": 200,
                        "length": 500
                    }
                }
            }
        }
    }
    return json.dumps(json_data)

def create_map(msg_count):
    """Generates a Map Data (MAP) JSON.
    Struct ref: map_and_signal_types.h -> US_MapData, US_IntersectionGeometry,
    US_GenericLane, US_LaneAttributes, US_LaneTypeAttributes
    US_NodeOffsetPointXY CHOICE: node-XY1 = Node_XY_20b (x, y as Offset_B10)
    """
    json_data = {
        "mapData": {
            "messageId": 18,
            "value": {
                "msgIssueRevision": msg_count % 128,
                "intersections": [
                    {
                        "id": {
                            "region": 0,
                            "id": 1
                        },
                        "revision": 1,
                        "refPoint": {
                            "lat": -235500000,
                            "long": -466330000
                        },
                        "laneSet": [
                            {
                                "laneID": 1,
                                "laneAttributes": {
                                    "directionalUse": {
                                        "value": "80",
                                        "length": 2
                                    },
                                    "sharedWith": {
                                        "value": "0000",
                                        "length": 10
                                    },
                                    "laneType": {
                                        "vehicle": {
                                            "value": "00",
                                            "length": 8
                                        }
                                    }
                                },
                                "nodeList": {
                                    "nodes": [
                                        {"delta": {"node-XY1": {"x": 0, "y": 0}}},
                                        {"delta": {"node-XY1": {"x": 100, "y": 0}}}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }
    }
    return json.dumps(json_data)

def create_spat(msg_count):
    """Generates a Signal Phase and Timing (SPAT) JSON.
    Struct ref: message_frame_and_spat_types.h -> US_SPAT, US_IntersectionState,
    US_MovementState, US_MovementEvent, US_TimeChangeDetails
    """
    now = time.time()
    local_time = time.localtime(now)
    current_dsec = (local_time.tm_min * 60 + local_time.tm_sec) * 10
    event_state = "protected-Movement-Allowed" if (msg_count % 20 < 10) else "stop-And-Remain"
    min_end = (current_dsec + 100) % 36000

    json_data = {
        "spat": {
            "messageId": 19,
            "value": {
                "intersections": [
                    {
                        "id": {
                            "region": 0,
                            "id": 1
                        },
                        "revision": 1,
                        "status": "0000",
                        "states": [
                            {
                                "signalGroup": 1,
                                "state-time-speed": [
                                    {
                                        "eventState": event_state,
                                        "timing": {
                                            "minEndTime": min_end,
                                            "maxEndTime": min_end + 50
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        }
    }
    return json.dumps(json_data)

def create_rsa(msg_count):
    """Generates a Road Side Alert (RSA) JSON.
    Struct ref: rsa_types.h -> US_RoadSideAlert
    US_FullPositionVector field order: Long, lat, elevation
    US_Priority is ASN1String (1 byte OCTET STRING)
    US_HeadingSlice is ASN1BitString (16 bits)
    US_FurtherInfoID is ASN1String (2 byte OCTET STRING)
    US_Extent enum: useInstantlyOnly (not useInstantly)
    """
    json_data = {
        "rsa": {
            "messageId": 27,
            "value": {
                "msgCnt": msg_count % 128,
                "typeEvent": 1231,
                "description": [533],
                "priority": "00",
                "heading": {
                    "value": "0001",
                    "length": 16
                },
                "extent": "useInstantlyOnly",
                "position": {
                    "long": -466335000,
                    "lat": -235505000,
                    "elevation": 100
                },
                "furtherInfoID": "0000"
            }
        }
    }
    return json.dumps(json_data)

def create_tim(msg_count):
    """Generates a Traveler Information Message (TIM) wrapped in MessageFrame.
    MessageFrame { messageId: 31, value: TravelerInformation }
    Struct ref: traveler_and_probe_types.h -> US_TravelerInformation
    """
    json_data = {
        "tim": {
            "messageId": 31,
            "value": {
                "msgCnt": msg_count % 127,
                "timeStamp": int(time.time() % 525600),
                "packetID": "000000000000000000",
                "dataFrames": [
                    {
                        "notUsed": 0,
                        "frameType": "advisory",
                        "msgId": {
                            "roadSignID": {
                                "position": {
                                    "lat": -235502000,
                                    "long": -466332000,
                                    "elevation": 100
                                },
                                "viewAngle": "0000",
                                "mutcdCode": "warning",
                                "crc": "0000"
                            }
                        },
                        "startTime": 0,
                        "durationTime": 1,
                        "priority": 1,
                        "notUsed1": 0,
                        "regions": [
                            {
                                "name": "zona_escolar",
                                "anchor": {
                                    "lat": -235497100,
                                    "long": -466327200,
                                    "elevation": 100
                                },
                                "directionality": "both",
                                "closedPath": False
                            }
                        ],
                        "notUsed2": 0,
                        "notUsed3": 0,
                        "content": {
                            "workZone": [
                                {"item": {"itis": 4867}}
                            ]
                        }
                    }
                ]
            }
        }
    }
    return json.dumps(json_data)

def create_psm(msg_count):
    """Creates a PSM (Personal Safety Message) wrapped in MessageFrame.
    MessageFrame { messageId: 32, value: PersonalSafetyMessage }
    Struct ref: psm_types.h -> US_PersonalSafetyMessage
    """
    sec_mark = int((time.time() * 1000) % 60000)
    # FORCING PSM LOCATION TO MATCH BSM LOCATION FOR IMMEDIATE COLLISION
    lat_asn = -235497100
    lon_asn = -466327200

    json_data = {
        "psm": {
            "messageId": 32,
            "value": {
                "basicType": "aPEDESTRIAN",
                "secMark": sec_mark,
                "msgCnt": msg_count % 128,
                "id": "50534D31",
                "position": {
                    "lat": lat_asn,
                    "long": lon_asn,
                    "elevation": 100
                },
                "accuracy": {
                    "semiMajor": 40,
                    "semiMinor": 40,
                    "orientation": 0
                },
                "speed": 100,
                "heading": 0,
                "pathHistory": {
                    "crumbData": [
                        {
                            "latOffset": 0,
                            "lonOffset": 0,
                            "elevationOffset": 0,
                            "timeOffset": 1
                        }
                    ]
                },
                "pathPrediction": {
                    "radiusOfCurve": 0,
                    "confidence": 200
                }
            }
        }
    }
    return json.dumps(json_data)

# --------------------------
# Message Dispatcher
# --------------------------

MESSAGE_GENERATORS = {
    "bsm": create_bsm,
    "map": create_map,
    "spat": create_spat,
    "rsa": create_rsa,
    "tim": create_tim,
    "psm": create_psm,
}

# --------------------------
# SocketSender (same pattern as manual_control_steeringwheel.py)
# --------------------------

class SocketSender:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.listen_sock = None
        self.clients = []  # List to store active client socket objects
        self.running = True

    def start_server(self):
        """Initializes the server and starts a background thread to accept clients."""
        self.listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_sock.bind((self.host, self.port))
        self.listen_sock.listen(5)  # Allow a backlog of connections
        log(f"[INFO] Server listening on {self.host}:{self.port}...", CYAN)

        # Start the background thread for accepting connections
        self.accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        self.accept_thread.start()

    def _accept_clients(self):
        """Background loop to accept new clients without blocking the main loop."""
        while self.running:
            try:
                client_sock, addr = self.listen_sock.accept()
                log(f"[INFO] New client connected from: {addr}", GREEN)
                self.clients.append(client_sock)
            except Exception as e:
                if self.running:
                    log(f"[ERROR] Accept failed: {e}", RED)
                break

    def send_event(self, event_data):
        """Sends data to ALL connected clients and removes dead ones."""
        if not self.clients:
            return

        message = json.dumps(event_data).encode('utf-8') + b'\n'
        disconnected_clients = []

        for client in self.clients:
            try:
                client.sendall(message)
            except (socket.error, BrokenPipeError):
                disconnected_clients.append(client)

        # Clean up clients that closed the connection
        for client in disconnected_clients:
            log("[INFO] Removing disconnected client.", YELLOW)
            client.close()
            self.clients.remove(client)

    def close(self):
        self.running = False
        if self.listen_sock:
            self.listen_sock.close()
        for client in self.clients:
            client.close()
        log("[INFO] Server shut down.", CYAN)


def run_interactive_simulation():
    """Starts the CARLA Simulator as a TCP Server with interactive message control.
    Uses SocketSender (same pattern as manual_control_steeringwheel.py)."""
    set_terminal_title("CARLA_Simulator_Controller")
    log("============================================", CYAN)
    log("  CARLA V2X INTERACTIVE SIMULATOR", CYAN)
    log("============================================", CYAN)
    log(f"Listening on 0.0.0.0:{RSU_PORT} for RSU/OBU clients...", CYAN)
    log("Commands: send [TYPE], auto [TYPE] [INTERVAL], status, list, close, quit", YELLOW)
    log("Types: bsm, map, spat, rsa, tim, psm, all", YELLOW)
    log("====================================", CYAN)

    sender = SocketSender("0.0.0.0", RSU_PORT)
    sender.start_server()
    msg_count = 0

    while True:
        try:
            n_clients = len(sender.clients)
            cmd_raw = input(f"CARLA ({n_clients} connected)> ").strip().lower()
            parts = cmd_raw.split()
            if not parts:
                continue

            cmd = parts[0]

            if cmd in ("quit", "exit"):
                break

            elif cmd == "list":
                print("\nAvailable Message Types:")
                print("  bsm  - Basic Safety Message (Vehicle pos/state)")
                print("  map  - Map Data (Intersection Geometry)")
                print("  spat - Signal Phase and Timing (Traffic Lights)")
                print("  rsa  - Road Side Alert (Hazards)")
                print("  tim  - Traveler Information (Work Zones)")
                print("  psm  - Personal Safety Message (Pedestrians)")
                print("  all  - Send all message types at once")
                print("")

            elif cmd == "status":
                print(f"\nConnected clients: {n_clients}")
                for i, client in enumerate(sender.clients):
                    try:
                        addr = client.getpeername()
                        print(f"  [{i}] {addr[0]}:{addr[1]}")
                    except Exception:
                        print(f"  [{i}] (unknown)")
                print("")

            elif cmd == "close":
                for client in sender.clients:
                    try: client.close()
                    except: pass
                sender.clients.clear()
                print("[-] Disconnected all clients.")

            elif cmd == "send":
                if not sender.clients:
                    print("[!] No clients connected. Wait for RSU/OBU to connect.")
                    continue

                msg_type = parts[1] if len(parts) > 1 else "bsm"
                msg_count += 1

                if msg_type == "all":
                    for gen_name, gen_func in MESSAGE_GENERATORS.items():
                        msg = json.loads(gen_func(msg_count))
                        sender.send_event(msg)
                    print(f"  [>] Sent ALL types (Msg #{msg_count}) to {len(sender.clients)} client(s)")
                else:
                    gen = MESSAGE_GENERATORS.get(msg_type)
                    if not gen:
                        print(f"[!] Unknown message type: {msg_type}. Type 'list' for options.")
                        continue
                    msg = json.loads(gen(msg_count))
                    sender.send_event(msg)
                    print(f"  [>] Sent '{msg_type}' (Msg #{msg_count}) to {len(sender.clients)} client(s)")

            elif cmd == "auto":
                if not sender.clients:
                    print("[!] No clients connected. Wait for RSU/OBU to connect.")
                    continue

                msg_type = parts[1] if len(parts) > 1 else "bsm"
                interval = 0.1  # Default 10Hz
                if len(parts) > 2:
                    try: interval = float(parts[2])
                    except: pass

                if msg_type == "all":
                    gen_list = list(MESSAGE_GENERATORS.items())
                else:
                    gen = MESSAGE_GENERATORS.get(msg_type)
                    if not gen:
                        print(f"[!] Unknown message type: {msg_type}")
                        continue
                    gen_list = [(msg_type, gen)]

                print(f"[*] Auto-sending '{msg_type}' every {interval}s (Ctrl+C to stop)...")
                try:
                    while True:
                        msg_count += 1
                        for name, gen_func in gen_list:
                            msg = json.loads(gen_func(msg_count))
                            sender.send_event(msg)
                        if not sender.clients:
                            print("[!] All clients disconnected, stopping auto-mode.")
                            break
                        if msg_count % max(1, int(1.0 / interval)) == 0:
                            print(f"  [>] #{msg_count} | {len(sender.clients)} client(s)")
                        time.sleep(interval)
                except KeyboardInterrupt:
                    print("\n[*] Auto-Mode Stopped.")

            else:
                print("Unknown command. Type 'list' for options.")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR: {e}")

    sender.close()
    log("Simulator Closed.", CYAN)


# ==========================================
# WINDOW MANAGEMENT
# ==========================================

def interactive_shell(ip, user, password, command, title):
    """Refined Interactive Shell for the child windows."""
    set_terminal_title(title)
    log(f"🔌 Connecting to {title} ({ip})...", CYAN)
    
    client = get_ssh_client(ip, user, password)
    if not client:
        log("\n❌ Failed to connect. Press key to exit.", RED)
        input()
        return

    try:
        log(f"🚀 Starting Remote Command: {command}", GREEN)
        log("==========================================", CYAN)
        
        chan = client.invoke_shell()
        time.sleep(1)
        chan.send(command + "\n")
        
        def write_to_stdout():
            while True:
                if chan.recv_ready():
                    try:
                        data = chan.recv(1024)
                        if not data: break
                        sys.stdout.buffer.write(data)
                        sys.stdout.flush()
                    except: break
                time.sleep(0.01)
                
        t = threading.Thread(target=write_to_stdout, daemon=True)
        t.start()
        
        if platform.system().lower() == "windows":
            import msvcrt
            while True:
                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    chan.send(char)
                if not t.is_alive() or not chan.active:
                    break
                time.sleep(0.05)
        else:
            import select
            import tty
            import termios
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                while True:
                    if select.select([sys.stdin], [], [], 0.0) == ([sys.stdin], [], []):
                        char = sys.stdin.read(1)
                        if char:
                            chan.send(char.encode('utf-8'))
                    if not t.is_alive() or not chan.active:
                        break
                    time.sleep(0.05)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            
    except Exception as e:
        log(f"\n❌ Connection Error: {e}", RED)
    finally:
        if client: client.close()
        log("\nDisconnected.", RESET)
        input("\nPress Enter to close window...")

def open_child_window(title, ip=None, user=None, password=None, command=None, mode="listen"):
    """
    Spawns a new CMD window running THIS script in a specific mode.
    Modes: 
      - 'listen': Connects SSH and runs command (RSU/OBU Consoles)
      - 'simulate': Runs the CARLA simulation loop (Local)
    """
    script_path = os.path.abspath(__file__)
    python_exe = sys.executable
    
    if mode == "listen":
        # Argument Quoting
        safe_pass = password.replace('"', '\\"')
        safe_cmd = command.replace('"', '\\"')
        args = f'"{python_exe}" "{script_path}" --listen --ip {ip} --user {user} --pass "{safe_pass}" --cmd "{safe_cmd}" --title "{title}"'
        
    elif mode == "simulate":
        args = f'"{python_exe}" "{script_path}" --simulate'
        
    if platform.system().lower() == "windows":
        full_cmd = f'start "{title}" cmd /k "{args}"'
    else:
        # Detect terminal
        terminals = [
            ("gnome-terminal", f"gnome-terminal --title='{title}' -- bash -c '{args}; exec bash'"),
            ("konsole", f"konsole --title '{title}' -e bash -c '{args}; exec bash'"),
            ("xfce4-terminal", f"xfce4-terminal --title='{title}' -e 'bash -c \"{args}; exec bash\"'"),
            ("xterm", f"xterm -T '{title}' -e bash -c '{args}; exec bash'")
        ]
        
        full_cmd = ""
        for term, cmd in terminals:
            if subprocess.run(["which", term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                full_cmd = cmd
                break
        
        if not full_cmd:
            full_cmd = f"xterm -T '{title}' -e bash -c '{args}; exec bash'"
            
    log(f"  🖥️  Launching {title}...", CYAN)
    subprocess.Popen(full_cmd, shell=True)

# ==========================================
# MAIN DEPLOY FLOW
# ==========================================

def get_rsu_ip_from_ddns():
    """Queries the DDNS server to get the dynamic IPv6 address of the RSU."""
    import urllib.request
    try:
        url = f"{DDNS_URL}/resolve?name={DDNS_RSU_NAME}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                ip = response.read().decode('utf-8').strip()
                if ip:
                    return ip
    except Exception as e:
        log(f"  ⚠️ Could not resolve RSU IP from DDNS ({DDNS_URL}): {e}", YELLOW)
    return None

def main_deploy(enable_carla=False, skip_rsu=False, skip_obu=False):
    global RSU_IP
    log("============================================", CYAN)
    log("  V2X Deploy System v8.0 (Auto-Recompile)", CYAN)
    log("============================================", CYAN)

    # 0. Always Recompile
    if not recompile_binaries():
        log("\n🛑 Aborting due to compilation failure.", RED)
        return

    # 0.5. Resolve RSU IPv6 via DDNS for Everything
    if not skip_rsu:
        log("\n[0.5/3] Resolving RSU IP via DDNS...", YELLOW)
        log("  📡 Getting RSU IP from DDNS...", CYAN)
        resolved = get_rsu_ip_from_ddns()
        if resolved:
            RSU_IP = resolved
            log(f"  ✅ RSU IPv6 dynamically resolved to: {RSU_IP}", GREEN)
        else:
            log(f"  ⚠️ Could not resolve IPv6 from DDNS. Deploy may fail.", YELLOW)

    # 1. Connectivity
    log("\n[1/3] Connectivity Check (IPv6 Strict)...", YELLOW)
    rsu_ok = False
    obu_ok = False
    
    if not skip_rsu:
        rsu_ok = check_ping(RSU_IP)
            
        if rsu_ok: 
            log(f"  ✓ RSU ({RSU_IP}) Online", GREEN)
        else: 
            log(f"  ❌ RSU ({RSU_IP}) Offline (Ping falhou) - Atualize o DDNS ou verifique a antena!", RED)
    else:
        log("  ⏭️ RSU Deployment Skipped", YELLOW)

    if not skip_obu:
        obu_ok = check_ping(OBU_IP)
        if obu_ok: log(f"  ✓ OBU ({OBU_IP}) Online", GREEN)
        else: log(f"  ❌ OBU ({OBU_IP}) Offline", RED)
    else:
        log("  ⏭️ OBU Deployment Skipped", YELLOW)

    fac_path = os.path.join(LOCAL_DIR, "fac_alert")
    obu_path = os.path.join(LOCAL_DIR, "obu_alert_server")
    
    rsu_ready = False
    obu_ready = False

    # 2. Sequential Transfer
    log("\n[2/3] Transferring files (Pipe Mode)...", YELLOW)
    
    # RSU
    if rsu_ok:
        log(f"\n  🔌 Connecting to RSU via IPv6 ({RSU_IP})...", CYAN)
        for attempt in range(1, 4):
            try:
                client = get_ssh_client(RSU_IP, RSU_USER, RSU_PASS)
                if client:
                    rsu_ready = transfer_file_robust(client, fac_path, "/tmp/")
                    client.close()
                    if rsu_ready: break
            except Exception as e:
                log(f"    ⚠️ RSU Attempt {attempt} failed: {e}", YELLOW)
            time.sleep(2)
        if rsu_ready:
             log("  🔌 RSU Disconnected.", CYAN)
        else:
             log("  ❌ RSU Transfer Failed after retries.", RED)
    
    time.sleep(2)
    
    # OBU
    if obu_ok:
        log(f"\n  🔌 Connecting to OBU ({OBU_IP})...", CYAN)
        for attempt in range(1, 4):
            try:
                client = get_ssh_client(OBU_IP, OBU_USER, OBU_PASS)
                if client:
                    obu_ready = transfer_file_robust(client, obu_path, "/tmp/")
                    client.close()
                    if obu_ready: break
            except Exception as e:
                log(f"    ⚠️ OBU Attempt {attempt} failed: {e}", YELLOW)
            time.sleep(2)
        if obu_ready:
             log("  🔌 OBU Disconnected.", CYAN)
        else:
             log("  ❌ OBU Transfer Failed after retries.", RED)

    # 3. Execution
    log("\n[3/3] Launching Execution Windows...", YELLOW)
    
    # Wait to allow remote SSH daemon to close sockets properly
    # Dropbear (RSU SSH server) drops connections if too many are made quickly.
    log("  ⏳ Waiting 5s for remote SSH sockets to close...", YELLOW)
    time.sleep(5.0)
    
    if rsu_ready:
        open_child_window("RSU_Console", ip=RSU_IP, user=RSU_USER, password=RSU_PASS, command=f"/tmp/fac_alert {CARLA_IP}", mode="listen")
    elif rsu_ok:
        log("  ⚠️ RSU Transfer failed, skipping launch.", RED)
        
    if obu_ready:
        time.sleep(1)
        open_child_window("OBU_Console", ip=OBU_IP, user=OBU_USER, password=OBU_PASS, command="/tmp/obu_alert_server", mode="listen")
    elif obu_ok:
         log("  ⚠️ OBU Transfer failed, skipping launch.", RED)
         
    # 4. CARLA Simulation
    if enable_carla:
        log("\n[4/4] Launching Interactive CARLA Simulator...", YELLOW)
        time.sleep(1)
        open_child_window("CARLA_Controller", mode="simulate")
         
    log("\n✅ Done.", GREEN)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Modes
    parser.add_argument("--listen", action="store_true", help="Internal: Remote Shell Mode")
    parser.add_argument("--simulate", action="store_true", help="Internal: CARLA Simulation Mode")
    
    # User Options
    parser.add_argument("--carla", action="store_true", help="Launch CARLA Simulation window after deploy")
    parser.add_argument("--skip-rsu", action="store_true", help="Skip deploying RSU Server")
    parser.add_argument("--skip-obu", action="store_true", help="Skip deploying OBU Server")
    # parser.add_argument("--recompile", action="store_true", help="Recompile binaries via Docker before deploying")
    
    # Listen Args
    parser.add_argument("--ip")
    parser.add_argument("--user")
    parser.add_argument("--pass", dest="password")
    parser.add_argument("--cmd")
    parser.add_argument("--title")
    
    args = parser.parse_args()
    
    if args.listen:
        try:
            print(f"DEBUG: Starting Listener for {args.ip}")
            interactive_shell(args.ip, args.user, args.password, args.cmd, args.title)
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
            input("Press Enter to exit...")
            
    elif args.simulate:
        try:
            run_interactive_simulation()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"SIMULATION ERROR: {e}")
            input("Press Enter to exit...")
            
    else:
        try:
            # Recompile is now mandatory
            main_deploy(enable_carla=args.carla, skip_rsu=args.skip_rsu, skip_obu=args.skip_obu)
        except KeyboardInterrupt:
            pass
