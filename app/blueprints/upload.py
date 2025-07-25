import os
import zipfile
import shutil
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from werkzeug.utils import secure_filename

from app.processing import process_comic

upload_bp = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {'zip'}

def allowed_file(filename):
    """检查上传的文件扩展名是否在允许范围内"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_comic_name_from_zip(filepath):
    """从ZIP文件中提取漫画名称。"""
    temp_extract_path = filepath + '_temp_extract'
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_path)
        
        extracted_items = os.listdir(temp_extract_path)
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_extract_path, extracted_items[0])):
            return extracted_items[0]
        else:
            return os.path.splitext(os.path.basename(filepath))[0]
    finally:
        if os.path.exists(temp_extract_path):
            shutil.rmtree(temp_extract_path)

@upload_bp.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """文件上传路由。GET 请求显示上传表单，POST 请求处理文件上传。"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('请求中没有文件部分')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('未选择任何文件')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_folder = current_app.config['UPLOAD_FOLDER']
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)
            file.save(filepath)
            
            comic_name = get_comic_name_from_zip(filepath)
            process_comic(filepath, comic_name)
            
            flash(f'"{comic_name}" 已成功上传，正在后台进行 AI 处理。')
            return redirect(url_for('api.processing_status'))
    return render_template('upload.html')
