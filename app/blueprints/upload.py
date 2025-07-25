import os
import zipfile
import shutil
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from werkzeug.utils import secure_filename

from app.processing import process_comic
from app.utils.logger import logger

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
        files = request.files.getlist('file')
        if not files or files[0].filename == '':
            flash('未选择任何文件')
            return redirect(request.url)

        uploaded_comics = []
        for file in files:
            original_filename = file.filename
            logger.info(f"接收到文件: '{original_filename}'")

            if file and allowed_file(original_filename):
                # 移除路径分隔符，保留原始文件名
                filename = os.path.basename(original_filename)
                logger.info(f"处理后的安全文件名: '{filename}'")

                if not filename:
                    logger.warning(f"文件名 '{original_filename}' 处理后为空，跳过。")
                    continue

                upload_folder = current_app.config['UPLOAD_FOLDER']
                filepath = os.path.join(upload_folder, filename)
                
                try:
                    file.save(filepath)
                except Exception as e:
                    logger.error(f"保存文件 '{filepath}' 时出错: {e}", exc_info=True)
                    flash(f"保存文件 '{filename}' 时出错。")
                    continue
                
                comic_name = get_comic_name_from_zip(filepath)
                process_comic(filepath, comic_name)
                uploaded_comics.append(comic_name)
        
        if uploaded_comics:
            flash(f'漫画 {", ".join(uploaded_comics)} 已成功上传，正在后台进行 AI 处理。')
        else:
            flash('没有上传有效的文件。')
            
        return redirect(url_for('api.processing_status'))
    return render_template('upload.html')
