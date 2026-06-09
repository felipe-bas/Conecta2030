import os
import argparse
import paramiko
import csv
import math
from dotenv import load_dotenv

# Reutiliza as lógicas de conexão robusta desenvolvidas
def get_ssh_client(ip, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print(f"[SSH] Conectando a {ip}...")
        client.connect(
            ip, 
            username=username, 
            password=password, 
            timeout=10,
            disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']}
        )
        return client
    except Exception as e:
        print(f"[ERROR] Falha de conexão SSH a {ip}: {e}")
        return None

def processar_metricas(log_envio, log_recepcao, output_file="metricas_finais.csv"):
    print("\n--- INICIANDO PROCESSAMENTO DE MÉTRICAS ---")
    if not os.path.exists(log_envio):
        print(f"[ERRO] {log_envio} não encontrado. Não é possível calcular latência.")
        return
    if not os.path.exists(log_recepcao):
        print(f"[ERRO] {log_recepcao} não encontrado.")
        return

    envios = []
    with open(log_envio, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # find timestamp
                ts_key = 'timestamp_envio' if 'timestamp_envio' in row else list(row.keys())[0]
                ts = float(row[ts_key]) * 1000.0
                
                # find msg_cnt
                msg_cnt_key = 'msg_cnt' if 'msg_cnt' in row else 'Seq_ID'
                msg_cnt = int(row[msg_cnt_key]) if msg_cnt_key in row else 0
                
                # find size_bytes
                size = int(row['size_bytes']) if 'size_bytes' in row else 0
                
                envios.append({'ts_ms': ts, 'msg_cnt': msg_cnt, 'size': size})
            except Exception:
                continue
            
    # Calculate cycle for envios (msg_cnt resets at 127)
    cycle = 0
    last_cnt = -1
    for e in envios:
        if e['msg_cnt'] < last_cnt:
            cycle += 1
        e['cycle'] = cycle
        last_cnt = e['msg_cnt']

    recv = []
    with open(log_recepcao, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                msg_cnt_key = 'msg_cnt' if 'msg_cnt' in row else 'Seq_ID'
                ts_key = 'rx_timestamp' if 'rx_timestamp' in row else 'Timestamp_Recv'
                rssi_key = 'rssi_dbm' if 'rssi_dbm' in row else 'RSSI'
                
                ts_raw = float(row[ts_key])
                if ts_raw > 1e14:
                    ts_ms = ts_raw / 1000.0
                else:
                    ts_ms = ts_raw
                    
                msg_cnt = int(row.get(msg_cnt_key, 0))
                rssi = int(row.get(rssi_key, 0))
                
                recv.append({'ts_ms': ts_ms, 'msg_cnt': msg_cnt, 'rssi': rssi})
            except Exception:
                continue
            
    cycle = 0
    last_cnt = -1
    for r in recv:
        if r['msg_cnt'] < last_cnt:
            cycle += 1
        r['cycle'] = cycle
        last_cnt = r['msg_cnt']
        
    # Match using msg_cnt and cycle
    recv_dict = {(r['msg_cnt'], r['cycle']): r for r in recv}
    
    recebidos_finais = []
    latencias = []
    rssis = []
    tamanhos = []
    for e in envios:
        key = (e['msg_cnt'], e['cycle'])
        if key in recv_dict:
            r = recv_dict[key]
            lat = r['ts_ms'] - e['ts_ms']
            latencias.append(lat)
            rssis.append(r['rssi'])
            tamanhos.append(e['size'])
            recebidos_finais.append({
                'msg_cnt': e['msg_cnt'],
                'cycle': e['cycle'],
                'timestamp_envio_ms': e['ts_ms'],
                'rx_timestamp_ms': r['ts_ms'],
                'latencia_ms': lat,
                'rssi_dbm': r['rssi'],
                'size_bytes': e['size']
            })

    total_enviados = len(envios)
    total_recebidos = len(recebidos_finais)
    pdr = (total_recebidos / total_enviados * 100) if total_enviados > 0 else 0
    
    latencia_media = sum(latencias) / len(latencias) if latencias else 0
    if latencias:
        sorted_lat = sorted(latencias)
        idx = int(math.ceil(0.95 * len(sorted_lat))) - 1
        latencia_p95 = sorted_lat[max(0, idx)]
    else:
        latencia_p95 = 0
        
    jitter = []
    for i in range(1, len(latencias)):
        jitter.append(abs(latencias[i] - latencias[i-1]))
    jitter_medio = sum(jitter) / len(jitter) if jitter else 0
    
    if total_recebidos > 1:
        tempo_total_s = (recebidos_finais[-1]['rx_timestamp_ms'] - recebidos_finais[0]['rx_timestamp_ms']) / 1000.0
        if tempo_total_s > 0:
            throughput_kbps = (sum(tamanhos) / 1024) / tempo_total_s
        else:
            throughput_kbps = 0
    else:
        throughput_kbps = 0
        
    rssi_medio = sum(rssis) / len(rssis) if rssis else 0
    
    print("--- RESULTADOS ---")
    print(f"Total Enviados: {total_enviados}")
    print(f"Total Recebidos: {total_recebidos}")
    print(f"PDR: {pdr:.2f}%")
    print(f"Latência Média: {latencia_media:.2f} ms")
    print(f"Latência P95: {latencia_p95:.2f} ms")
    print(f"Jitter Médio: {jitter_medio:.2f} ms")
    print(f"Throughput: {throughput_kbps:.2f} KB/s")
    print(f"RSSI Médio: {rssi_medio:.2f} dBm")
    
    if recebidos_finais:
        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=recebidos_finais[0].keys())
            writer.writeheader()
            writer.writerows(recebidos_finais)
        print(f"\nDetalhes salvos em: {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Coletar logs da OBU e processar métricas V2X (Sem dependência do Pandas)")
    parser.add_argument("--ipv4", action="store_true", help="Usa a configuração IPv4 para conectar na OBU")
    parser.add_argument("--ipv6", action="store_true", help="Usa a configuração IPv6 para conectar na OBU")
    parser.add_argument("--envio", default="log_envio_interno.csv", help="Caminho do log local do simulador (Envio)")
    parser.add_argument("--recv", default="log_recepcao.csv", help="Caminho local para salvar o log da OBU (Recepção)")
    parser.add_argument("--out", default="metricas_finais.csv", help="Caminho do CSV de saída")
    parser.add_argument("--skip-download", action="store_true", help="Pula o download do log da OBU e apenas processa")
    args = parser.parse_args()

    load_dotenv()
    
    if not args.skip_download:
        if args.ipv6:
            obu_ip = os.getenv("OBU_IPV6")
        else:
            obu_ip = os.getenv("OBU_IPV4")
            
        obu_user = os.getenv("OBU_USER", "root")
        obu_pass = os.getenv("OBU_PASS", "root")
        
        if not obu_ip:
            print("[ERRO] OBU_IP não definido no arquivo .env!")
            return
            
        ssh = get_ssh_client(obu_ip, obu_user, obu_pass)
        if ssh:
            try:
                print(f"[OBU] Lendo arquivo /tmp/log_recepcao.csv via SSH pipe...")
                stdin, stdout, stderr = ssh.exec_command("cat /tmp/log_recepcao.csv")
                data = stdout.read()
                err = stderr.read()
                
                if len(data) == 0:
                    if b"No such file or directory" in err:
                        print("[AVISO] O arquivo /tmp/log_recepcao.csv ainda não existe na OBU.")
                    else:
                        print(f"[ERRO] Falha ao ler o arquivo: {err.decode('utf-8', errors='ignore')}")
                else:
                    with open(args.recv, "wb") as f:
                        f.write(data)
                    print(f"[SUCESSO] Log da OBU baixado para '{args.recv}' ({len(data)} bytes)")
            finally:
                ssh.close()
    
    # Processa os logs
    processar_metricas(args.envio, args.recv, args.out)

if __name__ == "__main__":
    main()
