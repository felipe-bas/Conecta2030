import os

with open('deploy_and_start.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace run_interactive_simulation def and the auto-send logic
old_run_sim = '''def run_interactive_simulation():
    """Starts the Interactive CARLA Simulator as a TCP Server.'''

new_run_sim = '''def run_interactive_simulation(test_data=False):
    """Starts the Interactive CARLA Simulator as a TCP Server.'''

content = content.replace(old_run_sim, new_run_sim)

# Replace the beginning of run_interactive_simulation loop to handle test_data
old_loop_start = '''    sender = SocketSender("0.0.0.0", RSU_PORT)
    sender.start_server()
    msg_count = 0

    while True:'''

new_loop_start = '''    sender = SocketSender("0.0.0.0", RSU_PORT)
    sender.start_server()
    msg_count = 0

    if test_data:
        log("\\n[TESTE DE DADOS] Modo automatizado ativado! Enviando BSM+PSM+TIM a 10Hz...", YELLOW)
        interval = 0.1
        ALERT_TYPES = ["bsm", "psm", "tim"]
        gen_list = [(t, MESSAGE_GENERATORS[t]) for t in ALERT_TYPES if t in MESSAGE_GENERATORS]
        
        # Cria arquivo de log
        log_file = open("log_envio_interno.csv", "w")
        log_file.write("Seq_ID,Timestamp_Send\\n")
        
        try:
            while True:
                msg_count += 1
                for name, gen_func in gen_list:
                    msg = json.loads(gen_func(msg_count))
                    sender.send_event(msg)
                    # O CARLA manda 3 mensagens por ciclo (BSM, PSM, TIM).
                    # A RSU geralmente gera alertas a partir dessa combinação.
                    # Vamos registrar o Timestamp para bater com o Seq_ID do log da OBU.
                
                # Registra apenas o envio do pacote consolidado ou do BSM principal
                timestamp = int(time.time() * 1000)
                log_file.write(f"{msg_count},{timestamp}\\n")
                log_file.flush()
                
                if not sender.clients:
                    print(f"  [>] Auto-Sent #{msg_count} (Sem clientes conectados)")
                else:
                    print(f"  [>] Auto-Sent #{msg_count} para {len(sender.clients)} client(s)")
                
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\\n[*] Auto-Mode Stopped.")
        finally:
            log_file.close()
            sender.close()
            return

    while True:'''

content = content.replace(old_loop_start, new_loop_start)

# Replace open_child_window mode logic
old_open_child = '''    elif mode == "simulate":
        args = f'"{python_exe}" "{script_path}" --simulate'
        
    full_cmd = f'start "{title}" cmd /k "{args}"' '''

new_open_child = '''    elif mode == "simulate":
        args = f'"{python_exe}" "{script_path}" --simulate'
    elif mode == "simulate_test_data":
        args = f'"{python_exe}" "{script_path}" --simulate_test_data'
        
    full_cmd = f'start "{title}" cmd /k "{args}"' '''

content = content.replace(old_open_child, new_open_child)

# Replace the argparse and main logic
old_main = '''if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V2X Deploy System - Unificado")'''

new_main = '''if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V2X Deploy System - Unificado")
    
    # Internal Modes for child windows
    parser.add_argument("--listen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulate_test_data", action="store_true", help=argparse.SUPPRESS)
    
    # Listen arguments
    parser.add_argument("--ip", help=argparse.SUPPRESS)
    parser.add_argument("--user", help=argparse.SUPPRESS)
    parser.add_argument("--pass", dest="password", help=argparse.SUPPRESS)
    parser.add_argument("--cmd", help=argparse.SUPPRESS)
    parser.add_argument("--title", help=argparse.SUPPRESS)'''

content = content.replace(old_main, new_main)

# Add the interception logic right after parser.parse_args()
old_args_parse = '''    args = parser.parse_args()

    # Se não especificou nenhum, assume ipv4'''

new_args_parse = '''    args, _ = parser.parse_known_args()

    if args.listen:
        try:
            interactive_shell(args.ip, args.user, args.password, args.cmd, args.title)
        except Exception as e:
            print(f"Error in listen mode: {e}")
        sys.exit(0)
        
    if args.simulate:
        run_interactive_simulation(test_data=False)
        sys.exit(0)
        
    if args.simulate_test_data:
        run_interactive_simulation(test_data=True)
        sys.exit(0)

    # Se não especificou nenhum, assume ipv4'''

content = content.replace(old_args_parse, new_args_parse)

# Fix open_child_window duplicate
# We have two def open_child_window... wait, the first one was around line 200, I need to check if it's there and remove it.
# Actually, the file size is ~990 lines. Let's just run this replace script and we'll check later if duplicates exist.

with open('deploy_and_start.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Replaced!")
