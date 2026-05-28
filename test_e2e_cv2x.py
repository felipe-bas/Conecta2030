import paramiko
import socket
import threading
import time
import sys
import json

OBU_IP = "192.168.0.53"
OBU_USER = "root"
OBU_PASS = "Conect@24"

RSU_IP = "192.168.0.50"
RSU_USER = "root"
RSU_PASS = "Conect@2024"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((RSU_IP, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.0.56"

PC_IP = get_local_ip()
print(f"Local PC IP towards RSU: {PC_IP}")

# Signal to stop all background threads
running = True

def run_ssh_stream(ip, user, password, command, label):
    global running
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ip, 
            username=user, 
            password=password, 
            timeout=10, 
            look_for_keys=False, 
            allow_agent=False,
            disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
            banner_timeout=30
        )
        
        # Kill existing instances first
        proc_name = command.split()[0].split("/")[-1]
        client.exec_command(f"killall -9 {proc_name} >/dev/null 2>&1")
        time.sleep(0.5)
        
        print(f"[{label}] Starting command: {command}")
        stdin, stdout, stderr = client.exec_command(command)
        
        # Non-blocking stdout/stderr reading
        def read_stream(stream, prefix):
            while running:
                line = stream.readline()
                if not line:
                    break
                print(f"[{label} - {prefix}] {line.strip()}")
                
        t_out = threading.Thread(target=read_stream, args=(stdout, "STDOUT"), daemon=True)
        t_err = threading.Thread(target=read_stream, args=(stderr, "STDERR"), daemon=True)
        t_out.start()
        t_err.start()
        
        while running:
            time.sleep(0.5)
            
        # Cleanup
        client.exec_command(f"killall -9 {proc_name} >/dev/null 2>&1")
        client.close()
    except Exception as e:
        print(f"[{label}] SSH Exception: {e}")

# Spawns a TCP server on PC to act as CARLA
rsu_client_sock = None
def start_carla_server():
    global rsu_client_sock, running
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 8080))
    server.listen(1)
    server.settimeout(5)
    print("[CARLA SERVER] Listening on 0.0.0.0:8080...")
    
    while running:
        try:
            sock, addr = server.accept()
            print(f"[CARLA SERVER] RSU connected from {addr}")
            rsu_client_sock = sock
            break
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[CARLA SERVER] Accept error: {e}")
            break
    server.close()

# Message generators
def create_bsm(msg_count):
    return {
        "messageId": 20,
        "value": {
            "coreData": {
                "msgCnt": msg_count,
                "id": "A1B2C3D4",
                "secMark": 1000,
                "lat": -235497100,
                "long": -466327200,
                "elev": 100,
                "accuracy": {"semiMajor": 40, "semiMinor": 40, "orientation": 0},
                "transmission": "forwardGears",
                "speed": 750,
                "heading": 0,
                "angle": 0,
                "accelSet": {"long": 0, "lat": 0, "vert": 0, "yaw": 0},
                "brakes": {"wheelBrakes": "00", "traction": "unavailable", "abs": "unavailable", "scs": "unavailable", "brakeBoost": "unavailable", "auxBrakes": "unavailable"},
                "size": {"width": 200, "length": 500}
            }
        }
    }

def create_psm(msg_count):
    return {
        "messageId": 32,
        "value": {
            "basicType": "aPEDESTRIAN",
            "secMark": 1000,
            "msgCnt": msg_count,
            "id": "50534D31",
            "position": {"lat": -235497100, "long": -466327200, "elevation": 100},
            "accuracy": {"semiMajor": 40, "semiMinor": 40, "orientation": 0},
            "speed": 100,
            "heading": 0,
            "pathHistory": {"crumbData": [{"latOffset": 0, "lonOffset": 0, "elevationOffset": 0, "timeOffset": 1}]},
            "pathPrediction": {"radiusOfCurve": 0, "confidence": 200}
        }
    }

def create_tim(msg_count):
    return {
        "messageId": 31,
        "value": {
            "msgCnt": msg_count,
            "timeStamp": 1000,
            "packetID": "000000000000000000",
            "dataFrames": [{
                "notUsed": 0, "frameType": "advisory",
                "msgId": {"roadSignID": {"position": {"lat": -235502000, "long": -466332000, "elevation": 100}, "viewAngle": "0000", "mutcdCode": "warning", "crc": "0000"}},
                "startTime": 0, "durationTime": 1, "priority": 1, "notUsed1": 0,
                "regions": [{"name": "zona_escolar", "anchor": {"lat": -235497100, "long": -466327200, "elevation": 100}, "directionality": "both", "closedPath": False}],
                "notUsed2": 0, "notUsed3": 0,
                "content": {"workZone": [{"item": {"itis": 4867}}]}
            }]
        }
    }

# Tablet receiver thread
tablet_received = []
def tablet_client_thread():
    global running
    print("[TABLET CLIENT] Waiting 3 seconds before connecting...")
    time.sleep(3)
    
    tablet_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tablet_sock.settimeout(5)
    
    print(f"[TABLET CLIENT] Connecting to OBU at {OBU_IP}:8080...")
    try:
        tablet_sock.connect((OBU_IP, 8080))
        print("[TABLET CLIENT] Connected to OBU!")
    except Exception as e:
        print(f"[TABLET CLIENT] Connection failed: {e}")
        tablet_sock.close()
        return
        
    tablet_sock.settimeout(1)
    buf = b""
    while running:
        try:
            data = tablet_sock.recv(4096)
            if not data:
                print("[TABLET CLIENT] Connection closed by server.")
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = line.decode('utf-8', errors='replace')
                print(f"\n[TABLET RECEIVED] {msg}\n")
                tablet_received.append(msg)
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[TABLET CLIENT] Error: {e}")
            break
            
    tablet_sock.close()

if __name__ == "__main__":
    # Start CARLA server
    server_thread = threading.Thread(target=start_carla_server, daemon=True)
    server_thread.start()
    
    # Start OBU server in background
    obu_thread = threading.Thread(
        target=run_ssh_stream, 
        args=(OBU_IP, OBU_USER, OBU_PASS, "/tmp/obu_alert_server", "OBU"), 
        daemon=True
    )
    obu_thread.start()
    
    # Start Tablet client in background
    tab_thread = threading.Thread(target=tablet_client_thread, daemon=True)
    tab_thread.start()
    
    # Wait for CARLA server to listen
    time.sleep(1)
    
    # Start RSU client in background
    rsu_thread = threading.Thread(
        target=run_ssh_stream, 
        args=(RSU_IP, RSU_USER, RSU_PASS, f"/tmp/fac_alert {PC_IP}", "RSU"), 
        daemon=True
    )
    rsu_thread.start()
    
    # Wait for RSU to connect to CARLA
    time.sleep(12)
    
    if rsu_client_sock is None:
        print("[!] RSU failed to connect to CARLA TCP server.")
        running = False
        sys.exit(1)
        
    # Send BSM, PSM, TIM
    print("[TEST SENDER] Sending BSM, PSM, TIM to RSU...")
    try:
        # BSM (Id 20)
        bsm_data = json.dumps({"bsm": create_bsm(1)}) + "\n"
        rsu_client_sock.sendall(bsm_data.encode())
        print("  - Sent BSM")
        time.sleep(1)
        
        # PSM (Id 32)
        psm_data = json.dumps({"psm": create_psm(1)}) + "\n"
        rsu_client_sock.sendall(psm_data.encode())
        print("  - Sent PSM")
        time.sleep(1)
        
        # TIM (Id 31)
        tim_data = json.dumps({"tim": create_tim(1)}) + "\n"
        rsu_client_sock.sendall(tim_data.encode())
        print("  - Sent TIM")
        time.sleep(1)
        
    except Exception as e:
        print(f"[TEST SENDER] Send failed: {e}")
        
    # Wait to see if message is received on tablet
    print("[TEST] Waiting 10 seconds for E2E delivery...")
    time.sleep(10)
    
    # Check results
    print("\n" + "="*40 + " E2E TEST RESULTS " + "="*40)
    print(f"Messages received on tablet: {len(tablet_received)}")
    if len(tablet_received) > 0:
        print(">>> SUCCESS: RSU -> C-V2X Radio -> OBU -> Tablet communication path working! <<<")
        for idx, msg in enumerate(tablet_received):
            print(f"Message {idx+1}: {msg[:300]}...")
    else:
        print(">>> FAILURE: No messages received on tablet. <<<")
    print("="*98)
    
    running = False
    time.sleep(1)
