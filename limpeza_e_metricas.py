import pandas as pd
import numpy as np
import argparse
import os

def processar_metricas(log_envio, log_recepcao, output_file="metricas_finais.csv"):
    if not os.path.exists(log_envio):
        print(f"Erro: {log_envio} não encontrado.")
        return
    if not os.path.exists(log_recepcao):
        print(f"Erro: {log_recepcao} não encontrado.")
        return

    # Carregar logs com os headers reais
    try:
        df_envio = pd.read_csv(log_envio)
        df_recv = pd.read_csv(log_recepcao)
    except Exception as e:
        print(f"Erro ao ler CSV: {e}")
        return

    # Normalizar headers de recebimento (log_recepcao.csv: Seq_ID,Timestamp_Recv,SNR,RSSI)
    if 'Seq_ID' in df_recv.columns:
        df_recv.rename(columns={'Seq_ID': 'msg_cnt', 'Timestamp_Recv': 'rx_timestamp', 'RSSI': 'rssi_dbm'}, inplace=True)
    
    # Normalizar timestamp de envio (time.time() retorna segundos)
    if 'timestamp_envio' in df_envio.columns:
        df_envio['timestamp_envio_ms'] = df_envio['timestamp_envio'] * 1000.0
    else:
        # Fallback se houver outro nome
        df_envio['timestamp_envio_ms'] = df_envio.iloc[:, 0] * 1000.0

    # Normalizar timestamp de recebimento (Commsignia timestamp pode ser us ou ms)
    # Se maior que 1e14, assumimos microssegundos
    if not df_recv.empty and df_recv['rx_timestamp'].max() > 1e14:
        df_recv['rx_timestamp_ms'] = df_recv['rx_timestamp'] / 1000.0
    else:
        df_recv['rx_timestamp_ms'] = df_recv['rx_timestamp']

    # Criar um identificador de ciclo, pois msg_cnt reseta no 127
    if 'msg_cnt' in df_envio.columns:
        df_envio['cycle'] = (df_envio['msg_cnt'].diff() < 0).cumsum()
    if 'msg_cnt' in df_recv.columns:
        df_recv['cycle'] = (df_recv['msg_cnt'].diff() < 0).cumsum()
    
    # Merge usando msg_cnt e cycle
    df_merged = pd.merge(df_envio, df_recv, on=['msg_cnt', 'cycle'], how='left')

    # Filtrar pacotes recebidos
    recebidos = df_merged[df_merged['rx_timestamp_ms'].notnull()].copy()

    # Calcular Latência (em milissegundos)
    recebidos['latencia_ms'] = recebidos['rx_timestamp_ms'] - recebidos['timestamp_envio_ms']
    
    # Calcular Métricas
    total_enviados = len(df_envio)
    total_recebidos = len(recebidos)
    pdr = (total_recebidos / total_enviados) * 100 if total_enviados > 0 else 0

    latencia_media = recebidos['latencia_ms'].mean()
    latencia_p95 = recebidos['latencia_ms'].quantile(0.95)

    # Jitter (Variação da latência entre pacotes consecutivos)
    jitter_medio = recebidos['latencia_ms'].diff().abs().mean()

    # Throughput (KB/s)
    if total_recebidos > 1:
        tempo_total_s = (recebidos['rx_timestamp_ms'].max() - recebidos['rx_timestamp_ms'].min()) / 1000.0
        if tempo_total_s > 0:
            total_bytes = recebidos['size_bytes'].sum() if 'size_bytes' in recebidos.columns else 0
            throughput_kbps = (total_bytes / 1024) / tempo_total_s
        else:
            throughput_kbps = 0
    else:
        throughput_kbps = 0

    rssi_medio = recebidos['rssi_dbm'].mean() if 'rssi_dbm' in recebidos.columns else 0

    print("\n--- MÉTRICAS FINAIS ---")
    print(f"Total Enviados: {total_enviados}")
    print(f"Total Recebidos: {total_recebidos}")
    print(f"PDR: {pdr:.2f}%")
    print(f"Latência Média: {latencia_media:.2f} ms")
    print(f"Latência P95: {latencia_p95:.2f} ms")
    print(f"Jitter Médio: {jitter_medio:.2f} ms")
    print(f"Throughput: {throughput_kbps:.2f} KB/s")
    print(f"RSSI Médio: {rssi_medio:.2f} dBm")
    
    # Salvar resultados processados
    recebidos.to_csv(output_file, index=False)
    print(f"\nDetalhes salvos em: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Processar logs de V2X")
    parser.add_argument("--envio", default="log_envio_interno.csv", help="Caminho do log do PC (CARLA/Simulador)")
    parser.add_argument("--recv", default="log_recepcao.csv", help="Caminho do log da OBU")
    parser.add_argument("--out", default="metricas_finais.csv", help="Caminho do output")
    args = parser.parse_args()

    processar_metricas(args.envio, args.recv, args.out)
