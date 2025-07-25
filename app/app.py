# 导入必要的库
import os
import time
import json
from flask import Flask, render_template, request, redirect, url_for, flash, Response, stream_with_context, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename  # 用于安全地处理上传的文件名

# 从其他模块导入核心功能和数据
from processing import (
    process_comic, search_comics_by_embedding, get_all_processing_statuses, 
    get_all_comics_info, start_worker_thread, processing_statuses, DATA_BASE_PATH,
    delete_comic, update_comic_info, get_comic_details, delete_chapter,
    rename_chapter, get_comic_image_from_fs
)
from logger_setup import logger

# --- 应用配置 ---
UPLOAD_FOLDER = 'app/uploads'  # 定义上传文件存储的目录
ALLOWED_EXTENSIONS = {'zip'}  # 定义允许上传的文件扩展名

# 初始化 Flask 应用
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER  # 设置上传目录
app.config['SECRET_KEY'] = 'supersecretkey'  # 设置用于 session 和 flash 消息的密钥，生产环境应使用更复杂的值

# --- 辅助函数 ---
def allowed_file(filename):
    """检查上传的文件扩展名是否在允许范围内"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 路由定义 ---

@app.route('/')
def index():
    """主页路由，显示搜索界面。"""
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """文件上传路由。GET 请求显示上传表单，POST 请求处理文件上传。"""
    if request.method == 'POST':
        # 检查 POST 请求中是否包含文件部分
        print(request)
        if 'file' not in request.files:
            flash('请求中没有文件部分')
            return redirect(request.url)
        file = request.files['file']
        # 如果用户没有选择文件，浏览器可能会提交一个没有文件名的空部分
        if file.filename == '':
            flash('未选择任何文件')
            return redirect(request.url)
        # 如果文件存在且扩展名合法
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)  # 获取安全的文件名
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)  # 保存文件
            
            # 将漫画处理任务添加到队列
            process_comic(filepath)
            
            flash(f'"{filename}" 已成功上传，正在后台进行 AI 处理。')
            return redirect(url_for('processing_status')) # 重定向到处理状态页面
    # 如果是 GET 请求，则显示上传页面
    return render_template('upload.html')

@app.route('/search')
def search():
    """搜索结果路由。根据查询参数执行语义搜索并显示结果。"""
    query = request.args.get('query', '')  # 从 URL 参数中获取查询内容
    results = []
    if query:
        # 如果查询非空，则调用 embedding 搜索函数
        results = search_comics_by_embedding(query)
    return render_template('search.html', query=query, results=results)

@app.route('/processing')
def processing_status():
    """显示文件处理状态的页面。"""
    statuses = get_all_processing_statuses()
    return render_template('processing.html', statuses=statuses)

@app.route('/api/processing-status')
def api_processing_status():
    """以 JSON 格式返回所有任务的状态，移除不可序列化的部分。"""
    statuses = get_all_processing_statuses()
    # 创建一个可序列化的版本，移除 stream_buffers
    serializable_statuses = []
    for task in statuses:
        # 复制字典，排除 'stream_buffers'
        serializable_task = {k: v for k, v in task.items() if k != 'stream_buffers'}
        serializable_statuses.append(serializable_task)
    return jsonify(serializable_statuses)

@app.route('/manage')
def manage_data():
    """数据显示管理页面，展示所有已索引的漫画章节信息。"""
    comics_info = get_all_comics_info()
    return render_template('manage.html', comics=comics_info)

@app.route('/delete_comic/<comic_hash>', methods=['POST'])
def delete_comic_route(comic_hash):
    """删除指定漫画的路由。"""
    success, message = delete_comic(comic_hash)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('manage_data'))

@app.route('/update_comic/<comic_hash>', methods=['POST'])
def update_comic_route(comic_hash):
    """更新漫画信息的路由。"""
    new_name = request.form.get('name')
    if not new_name:
        flash('漫画名称不能为空', 'error')
        return redirect(url_for('manage_data'))

    success, message = update_comic_info(comic_hash, {'name': new_name})
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('manage_data'))

@app.route('/comicinfo/<comic_hash>')
def comic_info(comic_hash):
    """显示漫画详细信息的页面。"""
    selected_chapter = request.args.get('chapter')
    details, message = get_comic_details(comic_hash, load_page_details=True, chapter_filter=selected_chapter)
    
    if not details:
        flash(message, 'error')
        return redirect(url_for('manage_data'))
        
    return render_template('comicinfo.html', comic=details, selected_chapter_name=selected_chapter)

@app.route('/delete_chapter/<comic_hash>/<path:chapter_name>', methods=['POST'])
def delete_chapter_route(comic_hash, chapter_name):
    """删除指定章节的路由。"""
    success, message = delete_chapter(comic_hash, chapter_name)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('comic_info', comic_hash=comic_hash))

@app.route('/rename_chapter/<comic_hash>/<path:old_name>', methods=['POST'])
def rename_chapter_route(comic_hash, old_name):
    """重命名指定章节的路由。"""
    new_name = request.form.get('new_name')
    if not new_name:
        flash('新章节名不能为空', 'error')
        return redirect(url_for('comic_info', comic_hash=comic_hash, chapter=old_name))

    success, message = rename_chapter(comic_hash, old_name, new_name)
    if success:
        flash(message, 'success')
        # 重命名成功后，跳转到新的章节名
        return redirect(url_for('comic_info', comic_hash=comic_hash, chapter=new_name))
    else:
        flash(message, 'error')
        return redirect(url_for('comic_info', comic_hash=comic_hash, chapter=old_name))

@app.route('/comic_image/<comic_hash>/<path:chapter_name>/<path:image_name>')
def comic_image_route(comic_hash, chapter_name, image_name):
    """提供章节内单张图片的路由。"""
    image_io = get_comic_image_from_fs(comic_hash, chapter_name, image_name)
    if image_io:
        return send_file(image_io, mimetype='image/png')
    else:
        return "Image not found", 404

@app.route('/logs')
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

@app.route('/comic_cover/<comic_hash>')
def comic_cover(comic_hash):
    """提供漫画封面图。"""
    # 获取当前文件（app.py）所在的目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 构建到 data/comicdb 的绝对路径
    comic_dir = os.path.join(base_dir, '..', 'data', 'comicdb', comic_hash)
    # 使用 send_from_directory 发送文件
    return send_from_directory(comic_dir, 'cover.png')

@app.route('/stream-ai/<task_id>')
def stream_ai(task_id):
    def generate():
        if task_id not in processing_statuses:
            error_data = json.dumps({"stream_id": "error", "content": f"错误：未找到任务ID {task_id}"})
            yield f"data: {error_data}\n\n"
            return

        task_status = processing_statuses.get(task_id)
        if not task_status:
            return

        # --- 1. 识别已结束的流 ---
        finished_stream_ids = set()
        if 'stream_buffers' in task_status:
            for stream_id, buffer in task_status['stream_buffers'].items():
                if any(isinstance(item, dict) and item.get('type') == 'stream_end' for item in buffer):
                    finished_stream_ids.add(stream_id)

        # --- 2. 发送历史日志 (仅限未结束的流) ---
        if 'stream_buffers' in task_status:
            for stream_id, buffer in task_status['stream_buffers'].items():
                if stream_id in finished_stream_ids:
                    continue  # 如果流已结束，则不发送历史记录
                
                if buffer:
                    history_content = "".join([item for item in buffer if isinstance(item, str)])
                    if history_content:
                        data = json.dumps({"stream_id": stream_id, "content": history_content, "is_history": True})
                        yield f"data: {data}\n\n"
        
        # --- 3. 准备流式传输 ---
        known_stream_ids = set(task_status.get('stream_buffers', {}).keys())
        sent_positions = {stream_id: len(buffer) for stream_id, buffer in task_status.get('stream_buffers', {}).items()}

        # --- 4. 开始流式传输新日志 ---
        try:
            while True:
                task_status = processing_statuses.get(task_id)
                if not task_status:
                    break  # 任务被移除

                # 检查是否有新的流加入
                current_stream_ids = set(task_status.get('stream_buffers', {}).keys())
                new_streams = current_stream_ids - known_stream_ids
                if new_streams:
                    for stream_id in new_streams:
                        known_stream_ids.add(stream_id)
                        sent_positions[stream_id] = 0

                # 从所有已知的流中读取新数据
                has_data = False
                for stream_id in list(known_stream_ids):
                    buffer = task_status.get('stream_buffers', {}).get(stream_id)
                    if buffer:
                        current_pos = sent_positions.get(stream_id, 0)
                        if len(buffer) > current_pos:
                            new_chunks = list(buffer)[current_pos:]
                            for chunk in new_chunks:
                                if isinstance(chunk, dict): # 检查是否是特殊标记
                                    # 直接将字典作为数据发送
                                    data = json.dumps(chunk)
                                else:
                                    # 否则，是普通的日志内容
                                    data = json.dumps({"stream_id": stream_id, "content": chunk})
                                yield f"data: {data}\n\n"
                                has_data = True
                            sent_positions[stream_id] = len(buffer)
                
                # 如果任务完成或失败，则退出循环
                if task_status['status'] in ['完成', '失败']:
                    break
                
                if not has_data:
                    time.sleep(0.1)

            # 最终关闭事件
            yield "event: close\ndata: Task finished\n\n"

        except Exception as e:
            logger.error(f"流式传输 AI 输出时出错: {e}", exc_info=True)
            error_data = json.dumps({"stream_id": "error", "content": f"发生内部错误: {e}"})
            yield f"data: {error_data}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# --- 应用启动 ---
if __name__ == '__main__':
    # 在应用启动时，显式启动后台工作线程
    start_worker_thread()
    # 启动 Flask 开发服务器
    # debug=True 会在代码更改后自动重载，并提供详细的错误页面
    # port=5001 指定了服务运行的端口
    app.run(debug=True, port=5001)
