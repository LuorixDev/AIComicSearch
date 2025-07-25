import os
import sys

# 将项目根目录添加到 Python 路径中
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
