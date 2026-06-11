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
                if 'timestamp_envio' in row:
                    ts_key = 'timestamp_envio'
                elif 'Timestamp_Send' in row:
                    ts_key = 'Timestamp_Send'
                else:
                    ts_key = list(row.keys())[-1] # fallback to last column
                
                # Check if it needs converting from seconds to ms
                ts_raw = float(row[ts_key])
                if ts_raw < 1e11: # se for em segundos (e.g. 1780428282)
                    ts = ts_raw * 1000.0
                else: # se já for em ms (e.g. 1780428282332)
                    ts = ts_raw
                
                # find msg_cnt
                if 'msg_cnt' in row:
                    msg_cnt_key = 'msg_cnt'
                elif 'Seq_ID' in row:
                    msg_cnt_key = 'Seq_ID'
                else:
                    msg_cnt_key = list(row.keys())[0] # fallback to first column
                    
                msg_cnt = int(row[msg_cnt_key])
                
                # find size_bytes
                size = int(row['size_bytes']) if 'size_bytes' in row else 0
                
                envios.append({'ts_ms': ts, 'msg_cnt': msg_cnt, 'size': size})
            except Exception:
                continue
            
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

    # Agora, precisamos cruzar os dados.
    # O msg_cnt reseta a cada 128. Se houver perda de pacote, contar "ciclos" falha.
    # A melhor forma é encontrar o envio com o mesmo msg_cnt que ocorreu MAIS PRÓXIMO 
    # e ANTES do rx_timestamp (considerando um possível offset de relógio).
    
    # Primeiro, vamos descobrir o offset grosseiro comparando o primeiro pacote recebido
    # com o primeiro pacote enviado (assumindo que o primeiro recebido não atrasou muito).
    offset_grosseiro = 0
    if envios and recv:
        # Pega os primeiros 5 para achar um correspondente
        for r in recv[:10]:
            for e in envios[:128]:
                if e['msg_cnt'] == r['msg_cnt']:
                    offset_grosseiro = r['ts_ms'] - e['ts_ms']
                    break
            if offset_grosseiro != 0:
                break
    
    recebidos_finais = []
    latencias = []
    rssis = []
    tamanhos = []
    
    # Agrupar envios por msg_cnt para busca rápida
    envios_por_cnt = {}
    for e in envios:
        envios_por_cnt.setdefault(e['msg_cnt'], []).append(e)
        
    for r in recv:
        cnt = r['msg_cnt']
        if cnt not in envios_por_cnt:
            continue
            
        possiveis_envios = envios_por_cnt[cnt]
        
        # Encontra o envio cujo (ts_envio + offset_grosseiro) está mais próximo do ts_recepcao
        melhor_envio = None
        menor_diff = float('inf')
        
        for e in possiveis_envios:
            # Tempo esperado de chegada baseado no offset inicial
            tempo_esperado = e['ts_ms'] + offset_grosseiro
            diff = abs(r['ts_ms'] - tempo_esperado)
            
            if diff < menor_diff:
                menor_diff = diff
                melhor_envio = e
                
        if melhor_envio and menor_diff < 10000: # Aceita se descasou no máx 10s do esperado
            lat = r['ts_ms'] - melhor_envio['ts_ms']
            latencias.append(lat)
            rssis.append(r['rssi'])
            tamanhos.append(melhor_envio['size'])
            recebidos_finais.append({
                'msg_cnt': cnt,
                'timestamp_envio_ms': melhor_envio['ts_ms'],
                'rx_timestamp_ms': r['ts_ms'],
                'latencia_ms': lat,
                'rssi_dbm': r['rssi'],
                'size_bytes': melhor_envio['size']
            })
            # Remove para não parear duas vezes
            possiveis_envios.remove(melhor_envio)

    total_enviados = len(envios)
    total_recebidos = len(recebidos_finais)
    pdr = (total_recebidos / total_enviados * 100) if total_enviados > 0 else 0
    
    # Corrige problemas de relógios dessincronizados (ex: OBU com horas de diferença do PC)
    if latencias and (min(latencias) < 0 or sum(latencias)/len(latencias) > 60000):
        # Assume que o pacote mais rápido levou 5ms
        min_lat = min(latencias)
        offset = 5.0 - min_lat
        print(f"[AVISO] Relógios dessincronizados detectados. Aplicando offset de {offset/1000:.2f}s para ajustar a latência relativa.")
        latencias = [l + offset for l in latencias]
        for r in recebidos_finais:
            r['latencia_ms'] += offset
    
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
