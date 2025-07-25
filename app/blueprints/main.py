import os
from flask import Blueprint, render_template, send_from_directory

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """主页路由，显示搜索界面。"""
    return render_template('index.html')

@main_bp.route('/logs')
def logs():
    """显示处理日志页面。"""
    log_file_path = 'logs/processing.log'
    log_content = "日志文件不存在或为空。"
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r', encoding='utf-8') as f:
            # 读取文件末尾的 1000 行
            lines = f.readlines()
            log_content = "".join(lines[-1000:])
    return render_template('logs.html', log_content=log_content)

@main_bp.route('/comic_cover/<comic_hash>')
def comic_cover(comic_hash):
    """提供漫画封面图。"""
    # 获取当前文件所在的目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 构建到 data/comicdb 的绝对路径
    comic_dir = os.path.join(base_dir, '..', '..', 'data', 'comicdb', comic_hash)
    # 使用 send_from_directory 发送文件
    return send_from_directory(comic_dir, 'cover.png')
