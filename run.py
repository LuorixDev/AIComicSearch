import os
import sys

# 将项目根目录添加到 Python 路径中
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.app import create_app
from app.data_validator import validate_data_consistency

# 在应用启动前执行数据一致性检查
if not validate_data_consistency():
    sys.exit(1) # 如果用户选择不修复，则退出

app = create_app()

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    port = int(os.getenv('FLASK_RUN_PORT', 5001))
    app.run(debug=debug_mode, port=port)
