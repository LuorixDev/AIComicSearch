from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from ..models import (
    get_all_comics_info, delete_comic, update_comic_info, get_comic_details,
    delete_chapter, rename_chapter, get_comic_image_from_fs
)
from ..tasks import processing_statuses

manage_bp = Blueprint('manage', __name__)

@manage_bp.route('/manage')
def manage_data():
    """数据显示管理页面，展示所有已索引的漫画章节信息。"""
    comics_info = get_all_comics_info()
    return render_template('manage.html', comics=comics_info)

@manage_bp.route('/delete_comic/<comic_hash>', methods=['POST'])
def delete_comic_route(comic_hash):
    """删除指定漫画的路由。"""
    success, message = delete_comic(comic_hash, processing_statuses)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('manage.manage_data'))

@manage_bp.route('/rename_comic/<comic_hash>', methods=['POST'])
def rename_comic_route(comic_hash):
    """重命名指定漫画的路由。"""
    new_name = request.form.get('new_name')
    if not new_name:
        flash('新漫画名不能为空', 'error')
        return redirect(url_for('manage.manage_data'))

    success, message = update_comic_info(comic_hash, {'name': new_name})
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('manage.manage_data'))

@manage_bp.route('/update_comic/<comic_hash>', methods=['POST'])
def update_comic_route(comic_hash):
    """更新漫画信息的路由。"""
    new_name = request.form.get('name')
    if not new_name:
        flash('漫画名称不能为空', 'error')
        return redirect(url_for('manage.manage_data'))

    success, message = update_comic_info(comic_hash, {'name': new_name})
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('manage.manage_data'))

@manage_bp.route('/comicinfo/<comic_hash>')
def comic_info(comic_hash):
    """显示漫画详细信息的页面。"""
    selected_chapter = request.args.get('chapter')
    details, message = get_comic_details(comic_hash, load_page_details=True, chapter_filter=selected_chapter)
    
    if not details:
        flash(message, 'error')
        return redirect(url_for('manage.manage_data'))
        
    return render_template('comicinfo.html', comic=details, selected_chapter_name=selected_chapter)

@manage_bp.route('/delete_chapter/<comic_hash>/<path:chapter_name>', methods=['POST'])
def delete_chapter_route(comic_hash, chapter_name):
    """删除指定章节的路由。"""
    success, message = delete_chapter(comic_hash, chapter_name)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('manage.comic_info', comic_hash=comic_hash))

@manage_bp.route('/rename_chapter/<comic_hash>/<path:old_name>', methods=['POST'])
def rename_chapter_route(comic_hash, old_name):
    """重命名指定章节的路由。"""
    new_name = request.form.get('new_name')
    if not new_name:
        flash('新章节名不能为空', 'error')
        return redirect(url_for('manage.comic_info', comic_hash=comic_hash, chapter=old_name))

    success, message = rename_chapter(comic_hash, old_name, new_name)
    if success:
        flash(message, 'success')
        return redirect(url_for('manage.comic_info', comic_hash=comic_hash, chapter=new_name))
    else:
        flash(message, 'error')
        return redirect(url_for('manage.comic_info', comic_hash=comic_hash, chapter=old_name))

@manage_bp.route('/comic_image/<comic_hash>/<path:chapter_name>/<path:image_name>')
def comic_image_route(comic_hash, chapter_name, image_name):
    """提供章节内单张图片的路由。"""
    image_io = get_comic_image_from_fs(comic_hash, chapter_name, image_name)
    if image_io:
        return send_file(image_io, mimetype='image/png')
    else:
        return "Image not found", 404
