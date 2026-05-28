import paramiko
import sys

OBU_IP   = "192.168.0.53"
OBU_USER = "root"
OBU_PASS = "Conect@24"
RSU_IP   = "192.168.0.50"
RSU_USER = "root"
RSU_PASS = "Conect@2024"

def ssh(ip, user, pw):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip, username=user, password=pw, timeout=10,
              look_for_keys=False, allow_agent=False,
              disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
              banner_timeout=30)
    return c

def run_cmd(client, cmd, label=""):
    _, out, err = client.exec_command(cmd)
    o = out.read().decode('utf-8', errors='replace').strip()
    e = err.read().decode('utf-8', errors='replace').strip()
    print(f"\n=== {label} ===")
    print(f"CMD: {cmd}")
    if o:
        print("STDOUT:")
        print(o)
    if e:
        print("STDERR:")
        print(e)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ls -l /var/run/"
    print(f"Running command: {cmd}")
    
    print("Connecting to OBU...")
    obu = ssh(OBU_IP, OBU_USER, OBU_PASS)
    run_cmd(obu, cmd, "OBU")
    obu.close()
    
    print("Connecting to RSU...")
    rsu = ssh(RSU_IP, RSU_USER, RSU_PASS)
    run_cmd(rsu, cmd, "RSU")
    rsu.close()
