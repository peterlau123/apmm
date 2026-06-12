import subprocess

cwd = r'D:\workspace\apmm'

# Step 1: Write grep script to remote
cmd1 = 'echo "grep -n TestMMRSModel /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py" > /tmp/grep_test.sh'
r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd1 + '"'],
    capture_output=True, text=True, cwd=cwd)
print('Write script:', r.stdout[-200:], r.stderr[-200:])

# Step 2: Append more greps
cmd2 = 'echo "grep -n num_processes /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py" >> /tmp/grep_test.sh'
r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd2 + '"'],
    capture_output=True, text=True, cwd=cwd)
print('Append:', r.stdout[-200:], r.stderr[-200:])

cmd3 = 'echo "grep -n world_size /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py" >> /tmp/grep_test.sh'
r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd3 + '"'],
    capture_output=True, text=True, cwd=cwd)
print('Append2:', r.stdout[-200:], r.stderr[-200:])

# Step 3: Run the script
r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash /tmp/grep_test.sh'],
    capture_output=True, text=True, cwd=cwd)
print('=== RESULTS ===')
print(r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-500:])
