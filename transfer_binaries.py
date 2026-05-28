import deploy_and_start_ipv4
import os

def main():
    fac_path = os.path.join(os.getcwd(), "fac_alert")
    obu_path = os.path.join(os.getcwd(), "obu_alert_server")

    print("Connecting to RSU...")
    rsu_client = deploy_and_start_ipv4.get_ssh_client(
        deploy_and_start_ipv4.RSU_IP, 
        deploy_and_start_ipv4.RSU_USER, 
        deploy_and_start_ipv4.RSU_PASS
    )
    if rsu_client:
        print(f"Debug RSU: Path={fac_path}, Exists={os.path.exists(fac_path)}, Size={os.path.getsize(fac_path) if os.path.exists(fac_path) else 'N/A'}")
        deploy_and_start_ipv4.transfer_via_pipe(rsu_client, fac_path, "/tmp/")
        rsu_client.close()
        print("RSU transfer done.")
    else:
        print("Failed to connect to RSU.")

    print("\nConnecting to OBU...")
    obu_client = deploy_and_start_ipv4.get_ssh_client(
        deploy_and_start_ipv4.OBU_IP, 
        deploy_and_start_ipv4.OBU_USER, 
        deploy_and_start_ipv4.OBU_PASS
    )
    if obu_client:
        print(f"Debug OBU: Path={obu_path}, Exists={os.path.exists(obu_path)}, Size={os.path.getsize(obu_path) if os.path.exists(obu_path) else 'N/A'}")
        deploy_and_start_ipv4.transfer_via_pipe(obu_client, obu_path, "/tmp/")
        obu_client.close()
        print("OBU transfer done.")
    else:
        print("Failed to connect to OBU.")

if __name__ == '__main__':
    main()
