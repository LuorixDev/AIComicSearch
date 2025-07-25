import os
from flask import Flask

from .tasks import start_worker_threads
from .blueprints.main import main_bp
from .blueprints.upload import upload_bp
from .blueprints.search import search_bp
from .blueprints.manage import manage_bp
from .blueprints.api import api_bp


def create_app():
    """创建并配置 Flask 应用实例。"""
    app = Flask(__name__, instance_relative_config=True)

    # --- 应用配置 ---
    # 确保实例文件夹存在
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    app.config.from_mapping(
        SECRET_KEY='supersecretkey', # 在生产环境中应使用更安全的值
        UPLOAD_FOLDER=os.path.join(app.instance_path, 'uploads')
    )

    # 确保上传文件夹存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


    # --- 注册 Blueprints ---
    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(manage_bp)
    app.register_blueprint(api_bp)

    # --- 启动后台任务 ---
    with app.app_context():
        start_worker_threads()

    return app
