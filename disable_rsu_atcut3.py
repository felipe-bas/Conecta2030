import paramiko
import json

RSU_IP   = "192.168.0.50"
RSU_USER = "root"
RSU_PASS = "Conect@2024"

def main():
    print(f"Connecting to RSU at {RSU_IP}...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(RSU_IP, username=RSU_USER, password=RSU_PASS, timeout=10,
              look_for_keys=False, allow_agent=False,
              disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
              banner_timeout=30)

    print("Reading /rwdata/v2x_configs/its.json...")
    _, out, err = c.exec_command("cat /rwdata/v2x_configs/its.json")
    content = out.read().decode('utf-8', errors='replace').strip()
    
    try:
        data = json.loads(content)
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        print("Raw content:")
        print(content)
        c.close()
        return

    if 'radio' in data and 'atcut3' in data['radio']:
        print("atcut3 found in radio config. Disabling it...")
        data['radio']['atcut3']['enable'] = False
    else:
        print("atcut3 not found in radio config.")
        c.close()
        return

    new_content = json.dumps(data, indent=2)
    
    # Escape single quotes and backslashes for echo command
    escaped_content = new_content.replace('\\', '\\\\').replace("'", "'\\''")
    
    print("Backing up its.json...")
    c.exec_command("cp /rwdata/v2x_configs/its.json /rwdata/v2x_configs/its.json.bak")
    
    print("Writing new its.json...")
    c.exec_command(f"echo '{escaped_content}' > /rwdata/v2x_configs/its.json")
    
    # Verify the write
    _, out_verify, _ = c.exec_command("cat /rwdata/v2x_configs/its.json")
    verify_content = out_verify.read().decode('utf-8', errors='replace').strip()
    try:
        json.loads(verify_content)
        print("Verification successful! JSON is valid.")
    except Exception as e:
        print("Verification FAILED! Reverting from backup...")
        c.exec_command("cp /rwdata/v2x_configs/its.json.bak /rwdata/v2x_configs/its.json")
        c.close()
        return
        
    print("Restarting V2X stack control (/etc/init.d/unplugged-rt-control restart)...")
    _, out_rest, err_rest = c.exec_command("/etc/init.d/unplugged-rt-control restart")
    print("Restart STDOUT:")
    print(out_rest.read().decode('utf-8', errors='replace').strip())
    print("Restart STDERR:")
    print(err_rest.read().decode('utf-8', errors='replace').strip())
    
    c.close()
    print("Done!")

if __name__ == '__main__':
    main()
