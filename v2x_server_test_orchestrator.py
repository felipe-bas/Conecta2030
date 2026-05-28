import subprocess
import time
import requests
import sys
import socket
import json

# Configuration
RSU_IPV6 = "2804:214:8780:b30:f911:3c79:9074:860b"
REGISTRY_PORT = 5000
FORWARDER_PORT = 9090

def run_test():
    print(f"--- Starting V2X Test on Server ---")
    
    # 1. Start Registry
    print("Starting Registry...")
    registry_proc = subprocess.Popen(["python3", "v2x_registry.py"], 
                                     cwd="/home/conecta2030/v2x_test",
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2) # Wait for registry to start
    
    # 2. Update Registry (DDNS) via POST
    print(f"Registering RSU IPv6: {RSU_IPV6}")
    try:
        # v2x_registry expects name and ip in query params even for POST based on its code
        # Actually, let's check its do_POST again:
        # query = parse_qs(parsed_url.query)
        # Yes, it parses from query.
        resp = requests.post(f"http://localhost:{REGISTRY_PORT}/update?name=rsu-v2x&ip={RSU_IPV6}")
        print(f"Registry POST Response: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Registry Update Failed: {e}")
        registry_proc.terminate()
        return

    # 3. Verify Resolution
    print("Verifying Resolution...")
    try:
        resp = requests.get(f"http://localhost:{REGISTRY_PORT}/resolve?name=rsu-v2x")
        print(f"Resolved rsu-v2x -> {resp.text}")
    except Exception as e:
        print(f"Resolution Failed: {e}")

    # 4. Start Forwarder
    print("Starting Forwarder...")
    # Use the name 'rsu-v2x' to test dynamic resolution if the forwarder supports it
    # rsu_5g_forwarder.py resolves the IP in its main()
    fwd_proc = subprocess.Popen(["python3", "rsu_5g_forwarder.py", "--obu-ip", RSU_IPV6, "--listen-port", str(FORWARDER_PORT)],
                                cwd="/home/conecta2030/v2x_test",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(5) # Give it time to load schema
    
    # 5. Send Test Messages (BSM)
    print("Sending Test Messages (BSM)...")
    bsm_msg = {
        "bsm": {
            "messageId": 20,
            "value": {
                "coreData": {
                    "msgCnt": 1,
                    "id": "A1B2C3D4",
                    "secMark": 12345,
                    "lat": -235497100,
                    "long": -466327200,
                    "elev": 100,
                    "speed": 750,
                    "heading": 0
                }
            }
        }
    }
    
    try:
        # Send to both 127.0.0.1 and ::1 to be safe
        sock_v4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_v6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        
        for i in range(5):
            payload = json.dumps(bsm_msg).encode()
            sock_v4.sendto(payload, ("127.0.0.1", FORWARDER_PORT))
            try:
                sock_v6.sendto(payload, ("::1", FORWARDER_PORT))
            except:
                pass
            print(f"Sent message batch {i+1}")
            time.sleep(1)
    except Exception as e:
        print(f"Failed to send message: {e}")
        
    time.sleep(3) 
    
    # 6. Cleanup and check logs
    print("--- Test Logs ---")
    fwd_proc.terminate()
    registry_proc.terminate()
    
    fwd_out, fwd_err = fwd_proc.communicate()
    reg_out, reg_err = registry_proc.communicate()
    
    print("\nForwarder Output:")
    print(fwd_out)
    if fwd_err:
        print(f"Forwarder ERR: {fwd_err}")
    
    print("\nRegistry Output:")
    print(reg_out)
    if reg_err:
        print(f"Registry ERR: {reg_err}")
    
    print("--- Test Finished ---")

if __name__ == "__main__":
    run_test()
