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

# Fix Windows console encoding (cp1252 cannot handle emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Configuration
RSU_IP = "192.168.0.50"
RSU_USER = "root"
RSU_PASS = "Conect@2024"
RSU_PORT = 8080

OBU_IP = "192.168.0.53"
OBU_USER = "root"
OBU_PASS = "Conect@24"
OBU_PORT = 8080

def get_local_ip_towards_rsu():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((RSU_IP, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.0.56" # Fallback anterior

# IP of the PC running the Python simulator (this machine, reachable from RSU)
PC_IP = "192.168.0.246"

# IP of the real CARLA simulator PC (external machine)
CARLA_REAL_IP = "192.168.0.56"

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

def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")

def check_ping(ip):
    """Checks if the device is reachable via Ping."""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '1', ip]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        return False

def recompile_binaries(rsu_only=False): 
    """
    Uses the local 'arm32-builder' Docker image to cross-compile the
    source files in sdk_examples/conecta/ into the current directory.
    """
    log("\n[0/3] Recompiling Binaries (Docker)...", YELLOW)
    
    cwd = os.getcwd()
    
    # Path to SDK within the mounted workspace
    # The SDK is at commsignia_sdk/ with include/ and lib/ directly inside
    sdk_base = "commsignia-sdk/Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk/Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk"
    inc_path = f"{sdk_base}/include"
    lib_path = f"{sdk_base}/lib"
    
    # Common flags
    # We add inc_path/asn1 because some headers are included as <asn1defs.h> directly
    flags = f"-static -s -I {inc_path} -I {inc_path}/asn1 -L {lib_path} -lits-asnsdk -lits-rem -lpthread -lrt -lstdc++ -lm"
    
    # 1. Compile RSU Client (fac_alert)
    log("  🔨 Compiling RSU Client (fac_alert)...", CYAN)
    cmd_rsu = (
        f'docker run --rm -v "{cwd}:/workspace" arm32-builder '
        f'arm-linux-gnueabihf-gcc sdk_examples/conecta/fac_alert.c '
        f'-o fac_alert {flags}'
    )
    res_rsu = subprocess.run(cmd_rsu, shell=True)
    
    if res_rsu.returncode != 0:
        log("  \u274c Compilation Failed for RSU Client!", RED)
        return False
    else:
        # Verify freshness
        ts = time.strftime('%H:%M:%S', time.localtime(os.path.getmtime("fac_alert")))
        size = os.path.getsize("fac_alert")
        log(f"  \u2705 RSU Client Compiled. (Time: {ts}, Size: {size} bytes)", GREEN)

    # 2. Compile OBU Server (obu_alert_server) - skip if rsu_only
    if not rsu_only:
        log("  🔨 Compiling OBU Server (obu_alert_server)...", CYAN)
        cmd_obu = (
            f'docker run --rm -v "{cwd}:/workspace" arm32-builder '
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
    else:
        log("  ⏭️  Skipping OBU compilation (--rsu-only)", YELLOW)
        
    return True

def get_ssh_client(ip, user, password):
    """Creates and returns a connected Paramiko SSH client."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        # Force legacy algorithms for older embedded devices
        client.connect(
            ip, 
            username=user, 
            password=password, 
            timeout=10, 
            look_for_keys=False, 
            allow_agent=False,
            disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
            banner_timeout=60
        )
        return client
    except Exception as e:
        log(f"  ⚠️ SSH connection failed: {e}", YELLOW)
        return None

# ==========================================
# TRANSFER LOGIC
# ==========================================

def transfer_via_pipe(client, local_path, remote_path):
    """
    Transfers file binary content via 'cat' command.
    Robust against SFTP subsystem failures.
    """
    filename = os.path.basename(local_path)
    full_remote = os.path.join(remote_path, filename).replace("\\", "/") # Ensure unix paths
    
    try:
        log(f"  ➡️  Stopping and Transferring {filename}...", YELLOW)
        
        # 0. Kill existing instances and remove file
        client.exec_command(f"killall -9 {filename} >/dev/null 2>&1")
        client.exec_command(f"rm -f {full_remote} >/dev/null 2>&1")
        time.sleep(0.5)
        
        # 1. Open remote file for writing via cat
        cmd = f"cat > {full_remote}"
        
        stdin, stdout, stderr = client.exec_command(cmd)
        
        # 2. Write local file content to remote stdin
        with open(local_path, "rb") as f:
            while True:
                data = f.read(32768)
                if not data: break
                stdin.write(data)
                
        stdin.channel.shutdown_write() # Send EOF to remote cat
        
        # 3. Check for errors
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            err = stderr.read().decode()
            log(f"  ❌ Pipe failed (Exit {exit_status}): {err}", RED)
            return False
            
        # 4. Verify Size
        local_size = os.path.getsize(local_path)
        stdin, stdout, stderr = client.exec_command(f"wc -c < {full_remote}")
        remote_size = int(stdout.read().decode().strip())
        
        if local_size == remote_size:
            log(f"  ✅ Transfer Verified ({remote_size} bytes)", GREEN)
            # 5. Chmod
            client.exec_command(f"chmod +x {full_remote}")
            return True
        else:
            log(f"  ❌ Size mismatch! Local: {local_size}, Remote: {remote_size}", RED)
            return False
            
    except Exception as e:
        log(f"  ❌ Pipe Exception: {e}", RED)
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
# Multi-Client TCP Server (Simulation)
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
    """Starts the Interactive CARLA Simulator as a TCP Server.
    
    Architecture: This PC acts as TCP SERVER on port 8080.
    RSU (fac_alert) connects here as a CLIENT, receives JSON messages,
    encodes them to UPER and broadcasts via DSRC radio to the OBU.
    """
    os.system("title CARLA_Simulator_Controller")
    log("CARLA INTERACTIVE SIMULATOR (TCP Server Mode)", CYAN)
    log(f"This PC IP (RSU must reach this): {PC_IP}", GREEN)
    log(f"Listening on 0.0.0.0:{RSU_PORT} — RSU (fac_alert) will auto-connect...", CYAN)
    log("Commands: list, send [TYPE], auto [TYPE] [INTERVAL], status, close, quit", YELLOW)
    log("Types: bsm, map, spat, rsa, tim, psm, all", YELLOW)
    log("====================================" , CYAN)
    log(">>> Waiting for RSU to connect. Once connected, type 'send' to trigger an OBU alert (sends BSM+PSM+TIM).", GREEN)

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
                print("  all  - Send ALL types (bsm+map+spat+rsa+tim+psm)")
                print("")
                print("  NOTE: The OBU only forwards to the tablet when it receives")
                print("        BSM + PSM + TIM together. 'send' without args sends all 3.")
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

                msg_type = parts[1] if len(parts) > 1 else "alert"
                msg_count += 1

                # "alert" (default) = the 3 types the OBU needs to forward to the tablet
                ALERT_TYPES = ["bsm", "psm", "tim"]

                if msg_type == "all":
                    for gen_name, gen_func in MESSAGE_GENERATORS.items():
                        msg = json.loads(gen_func(msg_count))
                        sender.send_event(msg)
                    print(f"  [>] Sent ALL types (Msg #{msg_count}) to {len(sender.clients)} client(s)")
                elif msg_type == "alert":
                    sent = []
                    for t in ALERT_TYPES:
                        gen = MESSAGE_GENERATORS.get(t)
                        if gen:
                            msg = json.loads(gen(msg_count))
                            sender.send_event(msg)
                            sent.append(t)
                    print(f"  [>] Sent alert bundle [{'+'.join(sent)}] (Msg #{msg_count}) -> OBU will now forward to tablet")
                else:
                    gen = MESSAGE_GENERATORS.get(msg_type)
                    if not gen:
                        print(f"[!] Unknown message type: {msg_type}. Type 'list' for options.")
                        continue
                    msg = json.loads(gen(msg_count))
                    sender.send_event(msg)
                    print(f"  [>] Sent '{msg_type}' (Msg #{msg_count}) to {len(sender.clients)} client(s)")
                    if msg_type in ("bsm", "psm", "tim"):
                        print(f"  [!] NOTE: OBU needs BSM+PSM+TIM to forward. Missing: { {t for t in ALERT_TYPES if t != msg_type} }")

            elif cmd == "auto":
                if not sender.clients:
                    print("[!] No clients connected. Wait for RSU/OBU to connect.")
                    continue

                msg_type = parts[1] if len(parts) > 1 else "alert"
                interval = 1.0  # Default 1Hz
                if len(parts) > 2:
                    try: interval = float(parts[2])
                    except: pass

                ALERT_TYPES = ["bsm", "psm", "tim"]

                if msg_type == "all":
                    gen_list = list(MESSAGE_GENERATORS.items())
                elif msg_type == "alert":
                    gen_list = [(t, MESSAGE_GENERATORS[t]) for t in ALERT_TYPES if t in MESSAGE_GENERATORS]
                else:
                    gen = MESSAGE_GENERATORS.get(msg_type)
                    if not gen:
                        print(f"[!] Unknown message type: {msg_type}")
                        continue
                    gen_list = [(msg_type, gen)]

                type_label = '+'.join([t for t, _ in gen_list])
                print(f"[*] Auto-sending '{type_label}' every {interval}s (Ctrl+C to stop)...")
                if msg_type == "alert":
                    print(f"    (BSM+PSM+TIM bundle — OBU will forward to tablet on each cycle)")
                try:
                    while True:
                        msg_count += 1
                        for name, gen_func in gen_list:
                            msg = json.loads(gen_func(msg_count))
                            sender.send_event(msg)
                        if not sender.clients:
                            print("[!] All clients disconnected, stopping auto-mode.")
                            break
                        print(f"  [>] Auto-Sent #{msg_count} [{type_label}] to {len(sender.clients)} client(s)")
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
    os.system(f"title {title}")
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
        
        import msvcrt
        
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
        
        while True:
            if msvcrt.kbhit():
                char = msvcrt.getch()
                chan.send(char)
            if not t.is_alive() or not chan.active:
                break
            time.sleep(0.05)
            
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
        # Escapamos caracteres especiais do Windows (^|, ^&, ^>) para que não sejam interpretados localmente
        safe_cmd = command.replace('"', '\\"').replace('|', '^|').replace('&', '^&').replace('>', '^>')
        args = f'"{python_exe}" "{script_path}" --listen --ip {ip} --user {user} --pass "{safe_pass}" --cmd "{safe_cmd}" --title "{title}"'
        
    elif mode == "simulate":
        args = f'"{python_exe}" "{script_path}" --simulate'
        
    full_cmd = f'start "{title}" cmd /k "{args}"'
    
    log(f"  🖥️  Launching {title}...", CYAN)
    subprocess.Popen(full_cmd, shell=True)

# ==========================================
# MAIN DEPLOY FLOW
# ==========================================

def main_deploy(enable_carla=False, rsu_only=False):
    log("============================================", CYAN)
    log("  V2X Deploy System v8.0 (Auto-Recompile)", CYAN)
    log("============================================", CYAN)

    if rsu_only:
        log("  ⚡ RSU-Only Mode: OBU will be skipped.", YELLOW)

    # 0. Always Recompile
    if not recompile_binaries(rsu_only=rsu_only):
        log("\n🛑 Aborting due to compilation failure.", RED)
        return

    # 1. Connectivity
    log("\n[1/3] Connectivity Check...", YELLOW)
    rsu_ok = check_ping(RSU_IP)
    if rsu_ok: log(f"  ✓ RSU ({RSU_IP}) Online", GREEN)
    else: log(f"  ❌ RSU ({RSU_IP}) Offline", RED)
    
    obu_ok = False
    if not rsu_only:
        obu_ok = check_ping(OBU_IP)
        if obu_ok: log(f"  ✓ OBU ({OBU_IP}) Online", GREEN)
        else: log(f"  ❌ OBU ({OBU_IP}) Offline", RED)
    else:
        log(f"  ⏭️  Skipping OBU connectivity check (--rsu-only)", YELLOW)

    fac_path = os.path.join(LOCAL_DIR, "fac_alert")
    obu_path = os.path.join(LOCAL_DIR, "obu_alert_server")
    
    rsu_ready = False
    obu_ready = False

    # 2. Sequential Transfer
    log("\n[2/3] Transferring files (Pipe Mode)...", YELLOW)
    
    # RSU
    if rsu_ok:
        log(f"\n  🔌 Connecting to RSU...", CYAN)
        for attempt in range(1, 4):
            try:
                client = get_ssh_client(RSU_IP, RSU_USER, RSU_PASS)
                if client:
                    rsu_ready = transfer_via_pipe(client, fac_path, "/tmp/")
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
        log(f"\n  🔌 Connecting to OBU...", CYAN)
        for attempt in range(1, 4):
            try:
                client = get_ssh_client(OBU_IP, OBU_USER, OBU_PASS)
                if client:
                    obu_ready = transfer_via_pipe(client, obu_path, "/tmp/")
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
    # IMPORTANT: CARLA (TCP server) must start BEFORE the RSU (TCP client).
    # fac_alert will keep retrying, but start CARLA first to minimize wait time.
    log("\n[3/3] Launching Execution Windows...", YELLOW)

    # Step 3a: Launch CARLA server FIRST so port 8080 is listening
    if enable_carla:
        log("\n[3a/4] Launching CARLA Simulator (TCP Server) FIRST...", YELLOW)
        open_child_window("CARLA_Controller", mode="simulate")
        log("  ⏳ Waiting 3s for CARLA server to bind port 8080...", YELLOW)
        time.sleep(3)  # Give CARLA time to bind the port before RSU connects

    # Step 3b: Launch OBU (independent of RSU/CARLA, listens for radio)
    if obu_ready:
        log("\n[3b/4] Launching OBU Server...", YELLOW)
        open_child_window("OBU_Console", ip=OBU_IP, user=OBU_USER, password=OBU_PASS, command="/tmp/obu_alert_server", mode="listen")
        time.sleep(1)
    elif obu_ok:
        log("  ⚠️ OBU Transfer failed, skipping launch.", RED)

    # Step 3c: Launch RSU LAST - fac_alert connects to the appropriate CARLA target
    if rsu_ready:
        if enable_carla:
            # Normal mode: try local Python simulator first, then fallback to real CARLA
            carla_target = f"{PC_IP} {CARLA_REAL_IP}"
            log(f"\n[3c/4] Launching RSU Client (targets: {carla_target})...", YELLOW)
        else:
            # --no-carla mode: try real CARLA first, then fallback to local Python simulator
            carla_target = f"{CARLA_REAL_IP} {PC_IP}"
            log(f"\n[3c/4] Launching RSU Client (targets: {carla_target})...", YELLOW)

        open_child_window("RSU_Console", ip=RSU_IP, user=RSU_USER, password=RSU_PASS, command=f"/tmp/fac_alert {carla_target}", mode="listen")
    elif rsu_ok:
        log("  ⚠️ RSU Transfer failed, skipping launch.", RED)

    target_label = f"Python Simulator ({PC_IP})" if enable_carla else f"Real CARLA ({CARLA_REAL_IP})"
    log(f"\n✅ Done. Connection flow: {target_label} (server :8080) ← RSU (fac_alert) → [DSRC radio] → OBU → Tablet", GREEN)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V2X Deploy System - CARLA=Server, RSU=Client")
    # Modes
    parser.add_argument("--listen", action="store_true", help="Internal: Remote Shell Mode")
    parser.add_argument("--simulate", action="store_true", help="Internal: CARLA Simulation Mode")
    
    # User Options
    # CARLA is now ON by default (it's the TCP server the RSU connects to)
    parser.add_argument("--no-carla", action="store_true", help="Skip launching the CARLA Simulator window")
    parser.add_argument("--carla", action="store_true", help="(Kept for compatibility) Launch CARLA Simulation window")
    parser.add_argument("--rsu-only", action="store_true", help="Deploy only the RSU (fac_alert), skip OBU entirely")
    
    # Listen Args
    parser.add_argument("--ip")
    parser.add_argument("--user")
    parser.add_argument("--pass", dest="password")
    parser.add_argument("--cmd")
    parser.add_argument("--title")
    
    args, _ = parser.parse_known_args()
    
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
            # CARLA is enabled by default (it's the TCP server).
            # Pass --no-carla to skip it (e.g. if you already have CARLA running).
            enable_carla = not args.no_carla
            main_deploy(enable_carla=enable_carla, rsu_only=args.rsu_only)
        except KeyboardInterrupt:
            pass
