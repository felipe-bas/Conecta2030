import paramiko
import sys

ip = "192.168.0.53"
password = "Conect@24"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(
        ip, 
        username="root", 
        password=password,
        timeout=10, 
        look_for_keys=False, 
        allow_agent=False,
        disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
        banner_timeout=60
    )
    
    # Check running processes
    stdin, stdout, stderr = client.exec_command("ps aux | grep obu")
    print("Running processes:")
    print(stdout.read().decode())
    
    # Also check /tmp
    stdin, stdout, stderr = client.exec_command("ls -la /tmp")
    print("Contents of /tmp:")
    print(stdout.read().decode())
    
except Exception as e:
    print(f"Connection failed: {e}")
finally:
    client.close()
