#monitor.py

import time
import argparse
from torch.utils.tensorboard import SummaryWriter
from nvitop import Device

# 1. 解析命令行参数
parser = argparse.ArgumentParser(description='GPU 监控工具 - 采集 GPU 数据并写入 TensorBoard')
parser.add_argument(
    '--log_dir',
    type=str,
    default="/gpfs/gcsp/M2.7_verify/performance_test/gpu_monitor",
    help='TensorBoard 日志目录路径 (默认: /gpfs/gcsp/M2.7_verify/performance_test/gpu_monitor)'
)
parser.add_argument(
    '--interval',
    type=float,
    default=1.0,
    help='数据采集间隔，单位为秒 (默认: 1.0)'
)
args = parser.parse_args()

# 2. 初始化 TensorBoard 写入器
log_dir = args.log_dir
writer = SummaryWriter(log_dir=log_dir)
devices = Device.all()

print(f"🚀 开始采集 GPU 数据并写入 {log_dir} ... (按 Ctrl+C 停止)")

step = 0
try:
    # 2. 开启无限循环，每秒采集一次
    while True:
        for device in devices:
            # 记录 GPU 利用率 (%)
            writer.add_scalar(f'GPU_{device.index}/Utilization_Percent', device.gpu_utilization(), step)
            # 记录显存使用量 (MB)
            writer.add_scalar(f'GPU_{device.index}/Memory_Used_MB', device.memory_used_human(), step)
            # 你也可以记录功耗 (W)
            writer.add_scalar(f'GPU_{device.index}/Power_Draw_W', device.power_usage(), step)
            
        step += 1
        time.sleep(args.interval) # 采集间隔
except KeyboardInterrupt:
    writer.close()
    print("\n🛑 监控已停止。")
