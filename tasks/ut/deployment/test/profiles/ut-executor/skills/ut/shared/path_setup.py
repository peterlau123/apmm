#!/usr/bin/env python3
"""路径设置模块

自动将项目根目录添加到 sys.path，确保 skills 包可被导入。
使用方法：
    from skills.ut.shared.path_setup import setup_path
    setup_path()
    
或直接导入：
    from skills.ut.shared.path_setup import *  # 自动设置路径
"""

import sys
from pathlib import Path

def setup_path():
    """将项目根目录添加到 sys.path"""
    # 从 shared 目录向上查找项目根
    project_root = Path(__file__).parent.parent.parent.parent
    project_root_str = str(project_root)
    
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

# 导入时自动设置
setup_path()
