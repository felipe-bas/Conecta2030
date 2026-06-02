import paramiko
import sys

ip = "192.168.0.53"
password = "rsu"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(ip, username="root", password=password)
    
    # Check what is in /tmp
    stdin, stdout, stderr = client.exec_command("ls -la /tmp/obu_alert*")
    print(stdout.read().decode())
    
    # Try fetching obu_alert_server.c
    sftp = client.open_sftp()
    try:
        sftp.get("/tmp/obu_alert_server.c", "obu_alert_server.c")
        print("Successfully fetched obu_alert_server.c")
    except Exception as e:
        print(f"Could not fetch obu_alert_server.c: {e}")
        
    sftp.close()
except Exception as e:
    print(f"Connection failed: {e}")
finally:
    client.close()
