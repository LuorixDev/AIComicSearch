import os
from flask import Flask

from .tasks import start_worker_thread
from .blueprints.main import main_bp
from .blueprints.upload import upload_bp
from .blueprints.search import search_bp
from .blueprints.manage import manage_bp
from .blueprints.api import api_bp


def create_app():
    """创建并配置 Flask 应用实例。"""
    app = Flask(__name__)

    # --- 应用配置 ---
    app.config['UPLOAD_FOLDER'] = 'app/uploads'
    app.config['SECRET_KEY'] = 'supersecretkey'  # 在生产环境中应使用更安全的值

    # --- 注册 Blueprints ---
    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(manage_bp)
    app.register_blueprint(api_bp)

    # --- 启动后台任务 ---
    with app.app_context():
        start_worker_thread()

    return app
