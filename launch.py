# encoding: utf-8
"""启动器：加载环境变量后启动 server.py

API Key 配置方式（二选一）：
1. 创建 .env 文件（推荐，已被 .gitignore 排除）：
       DEEPSEEK_API_KEY=sk-你的密钥
2. 设置系统环境变量 DEEPSEEK_API_KEY

未配置时程序会自动降级到 Mock 模式（可离线演示，功能流程完整）。
"""
import os
import sys
import subprocess

os.environ["PYTHONIOENCODING"] = "utf-8"

ROOT = os.path.dirname(os.path.abspath(__file__))


# ── 加载 .env 文件（无需第三方依赖） ──────────────────────
def load_dotenv(path: str) -> None:
    """从 .env 文件加载环境变量（不覆盖已存在的）"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv(os.path.join(ROOT, ".env"))

# ── 环境检查 ──────────────────────────────────────────────
if not os.getenv("DEEPSEEK_API_KEY") and not os.getenv("OPENAI_API_KEY"):
    print("[提示] 未检测到 API Key，将以 Mock 模式启动（流程完整，可离线演示）")
    print("       配置方法：复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY")

# ── 启动服务 ──────────────────────────────────────────────
python = (
    os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if sys.platform == "win32"
    else os.path.join(ROOT, ".venv", "bin", "python")
)
server = os.path.join(ROOT, "server.py")

if not os.path.exists(python):
    python = sys.executable  # 回退到当前解释器

proc = subprocess.Popen([python, server], cwd=ROOT, env=os.environ)

import time  # noqa: E402

time.sleep(1)
print(f"PID={proc.pid} | http://localhost:5000", flush=True)

try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    proc.wait()
