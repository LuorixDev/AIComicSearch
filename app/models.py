import os
import json
import shutil
import io
import re

from .utils.logger import logger
from .services.chroma_service import delete_by_comic_hash, delete_by_chapter_id, rename_chapter_embedding, search_by_embedding
from .services.openai_service import get_embedding

DATA_BASE_PATH = './data/comicdb'

def natural_sort_key(s):
    """自然排序键函数，用于正确排序包含数字的字符串。"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def get_all_comics_info():
    """扫描数据目录，收集所有已处理漫画的信息。"""
    comics = []
    if not os.path.exists(DATA_BASE_PATH): return comics
    for comic_hash in os.listdir(DATA_BASE_PATH):
        comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
        info_path = os.path.join(comic_path, 'info.json')
        if os.path.isdir(comic_path) and os.path.exists(info_path):
            try:
                with open(info_path, 'r', encoding='utf-8') as f: info = json.load(f)
                summary_path = os.path.join(comic_path, 'cap_summary')
                num_chapters = len(os.listdir(summary_path)) if os.path.exists(summary_path) else 0
                comics.append({'hash': comic_hash, 'name': info.get('name', '未知名称'), 'chapters': num_chapters})
            except Exception as e:
                logger.error(f"读取漫画 {comic_hash} 信息时出错: {e}")
    comics.sort(key=lambda x: x['name'])
    return comics

def update_comic_info(comic_hash, new_data):
    """更新漫画的元数据信息。"""
    info_path = os.path.join(DATA_BASE_PATH, comic_hash, 'info.json')
    if not os.path.exists(info_path):
        return False, "漫画信息文件不存在"
    
    try:
        with open(info_path, 'r+', encoding='utf-8') as f:
            data = json.load(f)
            data.update(new_data)
            f.seek(0)
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.truncate()
        
        logger.info(f"漫画 {comic_hash} 的信息已更新: {new_data}")
        return True, "漫画信息更新成功"
    except Exception as e:
        logger.error(f"更新漫画 {comic_hash} 信息时出错: {e}", exc_info=True)
        return False, f"更新失败: {e}"

def delete_comic(comic_hash, processing_statuses):
    """删除指定的漫画及其所有相关数据。"""
    try:
        comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
        if os.path.exists(comic_path):
            shutil.rmtree(comic_path)
            logger.info(f"已从文件系统删除漫画目录: {comic_path}")
        
        delete_by_comic_hash(comic_hash)
        
        if comic_hash in processing_statuses:
            del processing_statuses[comic_hash]
            logger.info(f"已从任务状态列表中删除任务 {comic_hash}")

        return True, "漫画删除成功"
    except Exception as e:
        logger.error(f"删除漫画 {comic_hash} 时出错: {e}", exc_info=True)
        return False, f"删除失败: {e}"

def get_comic_details(comic_hash, load_page_details=False, chapter_filter=None):
    """获取漫画的详细信息。可选择性加载特定章节的页面详情。"""
    comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
    info_path = os.path.join(comic_path, 'info.json')
    if not os.path.exists(info_path): return None, "漫画信息文件不存在"
    try:
        with open(info_path, 'r', encoding='utf-8') as f: details = json.load(f)
        details['hash'] = comic_hash
        details['chapters'] = []
        summary_dir = os.path.join(comic_path, 'cap_summary')
        pic_detail_dir = os.path.join(comic_path, 'pic_detail')
        if os.path.exists(summary_dir):
            chapter_names = sorted(os.listdir(summary_dir), key=natural_sort_key)
            for chapter_name in chapter_names:
                chapter_info = {'name': chapter_name, 'summary': '', 'pages': []}
                summary_file = os.path.join(summary_dir, chapter_name, 'summary.txt')
                if os.path.exists(summary_file):
                    with open(summary_file, 'r', encoding='utf-8') as f: chapter_info['summary'] = f.read()
                if load_page_details and chapter_name == chapter_filter:
                    chapter_pic_path = os.path.join(pic_detail_dir, chapter_name)
                    if os.path.exists(chapter_pic_path):
                        manifest_path = os.path.join(chapter_pic_path, 'manifest.json')
                        original_filenames = []
                        if os.path.exists(manifest_path):
                            with open(manifest_path, 'r', encoding='utf-8') as f: original_filenames = json.load(f)
                        desc_files = sorted([f for f in os.listdir(chapter_pic_path) if f.endswith('.txt')], key=natural_sort_key)
                        for i, desc_file in enumerate(desc_files):
                            with open(os.path.join(chapter_pic_path, desc_file), 'r', encoding='utf-8') as f: description = f.read()
                            image_filename = original_filenames[i] if i < len(original_filenames) else os.path.splitext(desc_file)[0] + '.png' # Fallback
                            chapter_info['pages'].append({'image': image_filename, 'description': description})
                details['chapters'].append(chapter_info)
        return details, "获取成功"
    except Exception as e:
        logger.error(f"获取漫画 {comic_hash} 详情时出错: {e}", exc_info=True)
        return None, f"获取详情失败: {e}"

def rename_chapter(comic_hash, old_name, new_name):
    """重命名漫画的特定章节。"""
    try:
        comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
        new_summary_path = os.path.join(comic_path, 'cap_summary', new_name)
        if os.path.exists(new_summary_path): return False, f"章节名称 '{new_name}' 已存在。"
        old_summary_path = os.path.join(comic_path, 'cap_summary', old_name)
        old_detail_path = os.path.join(comic_path, 'pic_detail', old_name)
        old_pic_path = os.path.join(comic_path, 'pic', old_name)
        new_detail_path = os.path.join(comic_path, 'pic_detail', new_name)
        new_pic_path = os.path.join(comic_path, 'pic', new_name)
        if os.path.exists(old_summary_path): os.rename(old_summary_path, new_summary_path)
        if os.path.exists(old_detail_path): os.rename(old_detail_path, new_detail_path)
        if os.path.exists(old_pic_path): os.rename(old_pic_path, new_pic_path)
        
        rename_chapter_embedding(comic_hash, old_name, new_name)
        
        return True, f"章节 '{old_name}' 已成功重命名为 '{new_name}'"
    except Exception as e:
        logger.error(f"重命名章节 {comic_hash}/{old_name} 时出错: {e}", exc_info=True)
        return False, f"重命名失败: {e}"

def get_comic_image_from_fs(comic_hash, chapter_name, image_name):
    """从文件系统中直接读取并返回单个图片。"""
    image_path = os.path.join(DATA_BASE_PATH, comic_hash, 'pic', chapter_name, image_name)
    if not os.path.exists(image_path):
        logger.warning(f"图片未找到: {image_path}")
        return None
    try:
        with open(image_path, 'rb') as f:
            return io.BytesIO(f.read())
    except Exception as e:
        logger.error(f"从 {image_path} 读取图片时出错: {e}")
    return None

def delete_chapter(comic_hash, chapter_name):
    """删除漫画的特定章节。"""
    try:
        chapter_summary_path = os.path.join(DATA_BASE_PATH, comic_hash, 'cap_summary', chapter_name)
        if os.path.exists(chapter_summary_path):
            shutil.rmtree(chapter_summary_path)
            logger.info(f"已删除章节摘要目录: {chapter_summary_path}")

        chapter_detail_path = os.path.join(DATA_BASE_PATH, comic_hash, 'pic_detail', chapter_name)
        if os.path.exists(chapter_detail_path):
            shutil.rmtree(chapter_detail_path)
            logger.info(f"已删除章节图片描述目录: {chapter_detail_path}")

        chapter_id = f"{comic_hash}_{chapter_name}"
        delete_by_chapter_id(chapter_id)

        return True, f"章节 '{chapter_name}' 删除成功"
    except Exception as e:
        logger.error(f"删除章节 {comic_hash}/{chapter_name} 时出错: {e}", exc_info=True)
        return False, f"删除失败: {e}"

def search_comics(query, k=1000):
    """根据用户查询在 ChromaDB 中执行语义搜索。"""
    if not query: return []
    query_embedding = get_embedding(query)
    results = search_by_embedding(query_embedding, k)
    if not results or not results['ids'][0]: return []

    comic_scores = {}
    for i in range(len(results['ids'][0])):
        meta = results['metadatas'][0][i]
        distance = results['distances'][0][i]
        comic_hash = meta['comic_hash']
        
        info_path = os.path.join(DATA_BASE_PATH, comic_hash, 'info.json')
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                comic_name = json.load(f).get('name', '未知漫画')
        except FileNotFoundError:
            comic_name = '未知漫画'

        similarity = 1 / (1 + distance)
        
        if comic_name not in comic_scores:
            comic_scores[comic_name] = {'score': 0, 'chapters': [], 'hash': comic_hash}
        
        comic_scores[comic_name]['score'] += similarity
        comic_scores[comic_name]['chapters'].append({'chapter': meta['chapter'], 'similarity': similarity})

    for name in comic_scores:
        comic_scores[name]['chapters'].sort(key=lambda c: natural_sort_key(c['chapter']))

    formatted_results = [{'title': name, 'relevance': data['score'], 'matched_chapters': data['chapters'], 'hash': data['hash']} for name, data in comic_scores.items()]
    formatted_results.sort(key=lambda x: x['relevance'], reverse=True)
    return formatted_results
