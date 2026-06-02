with open('deploy_and_start.py', 'r', encoding='utf-8') as f:
    lines = f.read().splitlines()

idx_main = -1
for i, line in enumerate(lines):
    if line.startswith('if __name__ == "__main__":'):
        idx_main = i
        break

idx_import_json = -1
for i, line in enumerate(lines):
    if line.startswith('import json'):
        idx_import_json = i
        break

part1 = lines[:idx_main]
if idx_import_json != -1:
    main_block = lines[idx_main:idx_import_json]
    sim_logic = lines[idx_import_json:]
else:
    main_block = lines[idx_main:]
    sim_logic = []

with open('deploy_and_start.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(part1) + '\n\n')
    f.write('\n'.join(sim_logic) + '\n\n')
    f.write('\n'.join(main_block) + '\n')
