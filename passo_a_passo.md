# 🚦 Passo a Passo Completo - Sistema V2X com CARLA e Commsignia

Este guia detalha o fluxo completo para configurar, compilar, implantar e testar o sistema de alertas V2X.

---

## 🏗️ 1. Infraestrutura e Compilação

### Onde fazer:
No seu computador Windows (terminal PowerShell).

### O que fazer:
Se você alterou algum código em `sdk_examples/conecta/`, você precisa recompilar os executáveis.

1. **Abra o PowerShell na pasta do projeto:**
   ```powershell
   cd c:\Users\ferob\Downloads\conecta2030
   ```

2. **Inicie o Docker Desktop** (verifique se o ícone verde aparece na bandeja).

3. **Compile a imagem (gera os executáveis):**
   ```powershell
   cd commsignia-sdk\Unplugged-RT-y20.73.0-b311922-linuxm_obx_sdk-remote_c_sdk\Unplugged-RT-y20.73.0-b311922-linuxm_obx_sdk-remote_c_sdk
   docker build --no-cache -t arm32-builder .

   OR

   cd c:\Users\ferob\Downloads\conecta2030
   .\build_v2x.ps1  
   ```
   > ⏳ Isso pode levar alguns minutos.

4. **Extraia os arquivos compilados do Docker:**
   ```powershell
   cd c:\Users\ferob\Downloads\conecta2030
   
   # Criar container temporário
   $containerId = docker create arm32-builder
   
   # Copiar RSU Server
   docker cp ${containerId}:/workspace/build/fac_alert_server .\fac_alert_server
   
   # Copiar OBU Server
   docker cp ${containerId}:/workspace/build/obu_alert_server .\obu_alert_server
   
   # Remover container
   docker rm $containerId
   ```

---

## 🚀 2. Deploy (Transferência para Dispositivos)

### Onde fazer:
Do PowerShell local para os dispositivos físicos (RSU/OBU).

### Informações de acesso:
| Dispositivo | IP | Usuário | Senha |
|---|---|---|---|
| **RSU** | 192.168.0.56 | root | Conect@2024 |
| **OBU** | 192.168.0.53 | root | Conect@24 |

1. **Transferir para RSU:**
   ```powershell
   scp -O .\fac_alert_server root@192.168.0.56:/tmp/
   # Digite a senha: Conect@2024
   ```

2. **Transferir para OBU:**
   ```powershell
   scp -O .\obu_alert_server root@192.168.0.53:/tmp/
   # Digite a senha: Conect@24
   ```

---

## ⚡ 3. Execução dos Servidores

### Onde fazer:
Em dois terminais SSH separados (um para RSU, um para OBU).

### Terminal 1: Iniciar RSU (Roadside Unit)
Esta unidade recebe dados do CARLA e transmite via rádio DSRC.

```bash
ssh root@192.168.0.56
# Senha: Conect@2024

cd /tmp
chmod +x fac_alert_server
./fac_alert_server
```
> **Saída esperada:** `Waiting for clients to connect...`

### Terminal 2: Iniciar OBU (Onboard Unit)
Esta unidade recebe dados do rádio DSRC e repassa para o tablet/app.

```bash
ssh root@192.168.0.53
# Senha: Conect@24

cd /tmp
chmod +x obu_alert_server
./obu_alert_server
```
> **Saída esperada:** `Server listening on port 8080...`

---

## 🚗 4. Simulação CARLA (Envio de Dados)

### Opção A: Usando o Simulador CARLA Real
Se você tem o CARLA instalado e rodando em um servidor Linux:

1. Inicie o CARLA Simulator.
2. Inicie o script `manual_control.py` ou similar.
3. Configure o script para enviar os dados para o IP da RSU (`192.168.0.56:8080`).

### Opção B: Simulação via Script Python (Sem CARLA)
Se você quer testar a comunicação V2X sem abrir o simulador pesado:

1. **No seu PC local**, execute o script de teste:
   ```powershell
   python test_v2x_communication.py -i
   ```

2. **No modo interativo:**
   - Digite `send` para enviar uma mensagem simulada de "Pedestre na Pista".
   
3. **O que deve acontecer:**
   - **Script:** Mostra `✓ Mensagem enviada`
   - **Terminal RSU:** Mostra `WSMP message sent` e logs em Hex
   - **Terminal OBU:** Mostra dados recebidos e decodificados

---

## ✅ Resumo do Fluxo de Dados

1. **CARLA / Script Python** (TCP)  
   Envia JSON: `{"basicType": "aPEDESTRIAN", ...}`  
   ⬇
2. **RSU (fac_alert_server)**  
   Recebe JSON → Codifica para ASN.1 (UPER) → Envia rádio (WSMP)  
   ⬇ 
   *(Transmissão via ondas de rádio 5.9 GHz)*
   ⬇
3. **OBU (obu_alert_server)**  
   Recebe rádio (WSMP) → Decodifica ASN.1 → Gera JSON  
   ⬇
4. **Tablet / App** (TCP)  
   Recebe alerta JSON para exibir ao motorista

---

## 🛠️ Troubleshooting

- **Erro "Exec format error"**: Você tentou rodar o executável no PC ou Docker errado. Os arquivos só rodam na RSU/OBU (ARM32).
- **Erro "Connection refused" no SSH**: O dispositivo está desligado ou firewall bloqueando. Ping o IP antes de conectar.
- **RSU não envia WSMP**: Verifique `commsignia-device-info` na RSU. Se TX Status não for ACTIVE, a licença ou hardware pode estar com problema.
