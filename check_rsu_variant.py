import paramiko

def run_check(ip, password, name):
    print(f"\n=== {name} ({ip}) ===")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(ip, username="root", password=password, timeout=10,
                  look_for_keys=False, allow_agent=False,
                  disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
                  banner_timeout=30)
        
        cmd = 'RADIO_HANDLER_SCRIPT=$(v2x-config-wrapper cms-radio-handler.sh); [ -f "$RADIO_HANDLER_SCRIPT" ] && . $RADIO_HANDLER_SCRIPT; echo UPL_RADIO_VARIANT_NAME=$UPL_RADIO_VARIANT_NAME'
        _, out, err = c.exec_command(cmd)
        print("STDOUT:", out.read().decode().strip())
        print("STDERR:", err.read().decode().strip())
        
        # Let's also check what v2x-config-wrapper returns
        _, out2, _ = c.exec_command("v2x-config-wrapper cms-radio-handler.sh")
        print("Wrapper output:", out2.read().decode().strip())
        
        c.close()
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    run_check("192.168.0.50", "Conect@2024", "RSU")
    run_check("192.168.0.53", "Conect@24", "OBU")
