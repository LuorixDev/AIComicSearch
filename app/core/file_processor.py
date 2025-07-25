import os
import zipfile
import shutil
import json
import concurrent.futures
import re
import time
from PIL import Image
from collections import deque

from ..utils.logger import logger
from ..tasks import update_task_status, get_or_create_stream_buffer
from ..services.vision_service import analyze_image
from ..services.openai_service import summarize_text, get_embedding
from ..services.chroma_service import add_embedding

DATA_BASE_PATH = os.getenv('DATA_BASE_PATH', './data/comicdb')
TEMP_FOLDER = os.getenv('TEMP_FOLDER', './tmp')
SUPPORTED_FORMATS = tuple(os.getenv('SUPPORTED_FORMATS', '.png,.jpg,.jpeg,.webp,.bmp,.gif').split(','))
COVER_NAMES = tuple(os.getenv('COVER_NAMES', 'cover,folder').split(','))

def natural_sort_key(s):
    """自然排序键函数，用于正确排序包含数字的字符串。"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def _analyze_image_task(task_id, chapter_name, img_file, img_path):
    """封装单个图片分析任务，使其可在线程池中运行。"""
    log_key = f"{chapter_name}_{os.path.splitext(img_file)[0]}"
    
    buffer = get_or_create_stream_buffer(task_id, log_key)
    if buffer is None:
        logger.error(f"[{task_id}] 无法为 {log_key} 获取流缓冲区。")
        return img_file, None

    logger.info(f"[{task_id}] [图片分析中] 开始分析图片 {img_file}...")
    buffer.append(f"[开始分析图片: {img_file}]\n")
    
    description_chunks = []
    try:
        # 直接传递图片路径给 analyze_image，它现在内置了重试逻辑
        for chunk in analyze_image(img_path):
            buffer.append(chunk)
            description_chunks.append(chunk)
        
        description = "".join(description_chunks)

        # 检查是否有错误信息从 analyze_image 返回
        if description.startswith("错误："):
            logger.error(f"[{task_id}] {description}")
            buffer.append(f"\n[错误: {description}]\n")
            buffer.append({'type': 'stream_end', 'stream_id': log_key, 'error': True})
            return img_file, None

        buffer.append(f"\n[图片分析结束: {img_file}]\n\n")
        buffer.append({'type': 'stream_end', 'stream_id': log_key})
        
        logger.info(f"[{task_id}] [图片分析完成] 图片 {img_file} 分析完毕。")
        return img_file, description
    
    except Exception as e:
        error_message = f"处理图片 {img_file} 时发生意外错误: {e}"
        logger.error(f"[{task_id}] {error_message}", exc_info=True)
        buffer.append(f"\n[严重错误: {error_message}]\n")
        buffer.append({'type': 'stream_end', 'stream_id': log_key, 'error': True})
        return img_file, None

def _get_comic_index():
    """加载或初始化漫画索引。"""
    index_path = os.path.join(DATA_BASE_PATH, 'index.json')
    if not os.path.exists(DATA_BASE_PATH):
        os.makedirs(DATA_BASE_PATH)
    if not os.path.exists(index_path):
        return {}
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def _save_comic_index(index):
    """保存漫画索引。"""
    index_path = os.path.join(DATA_BASE_PATH, 'index.json')
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=4)

def _process_zip_file(task):
    """实际处理单个 ZIP 漫画文件的内部函数。"""
    task_id = task['task_id']
    filepath = task['filepath']
    comic_name = task['comic_name']
    file_content_hash = task['file_content_hash']
    
    update_task_status(task_id, {'status': '正在处理', 'details': '开始解压文件...'})

    temp_extract_path = os.path.join(TEMP_FOLDER, task_id)

    try:
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
        os.makedirs(temp_extract_path, exist_ok=True)

        logger.info(f"[{task_id}] 解压文件到 {temp_extract_path}")
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_path)
        
        extracted_items = os.listdir(temp_extract_path)
        comic_base_path = temp_extract_path
        
        # 如果ZIP内有单层目录，则以该目录为基础进行处理
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_extract_path, extracted_items[0])):
            comic_base_path = os.path.join(temp_extract_path, extracted_items[0])
            logger.info(f"[{task_id}] 检测到单层目录，处理路径设为: {comic_base_path}")

        # 加载漫画索引
        comic_index = _get_comic_index()
        
        # 确定漫画的存储哈希
        comic_hash = comic_index.get(comic_name)
        if comic_hash:
            logger.info(f"[{task_id}] 漫画 '{comic_name}' 已存在，使用哈希 {comic_hash} 进行更新。")
        else:
            # 对于新漫画，使用文件内容的哈希作为其存储哈希
            comic_hash = file_content_hash
            comic_index[comic_name] = comic_hash
            _save_comic_index(comic_index)
            logger.info(f"[{task_id}] 创建新漫画 '{comic_name}'，使用哈希: {comic_hash}")

        comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
        if not os.path.exists(comic_path):
            os.makedirs(comic_path)
            with open(os.path.join(comic_path, 'info.json'), 'w', encoding='utf-8') as f:
                json.dump({'name': comic_name}, f, ensure_ascii=False, indent=4)

        os.remove(filepath)
        logger.info(f"[{task_id}] 原始 zip 文件已被处理和删除: {filepath}")

        pic_storage_path = os.path.join(comic_path, 'pic')
        pic_detail_base_path = os.path.join(comic_path, 'pic_detail')
        cap_summary_base_path = os.path.join(comic_path, 'cap_summary')
        os.makedirs(pic_storage_path, exist_ok=True)
        os.makedirs(pic_detail_base_path, exist_ok=True)
        os.makedirs(cap_summary_base_path, exist_ok=True)

        potential_chapters = [d for d in os.listdir(comic_base_path) if os.path.isdir(os.path.join(comic_base_path, d))]
        chapters = sorted(potential_chapters, key=natural_sort_key) if potential_chapters else ['.']
        logger.info(f"[{task_id}] 找到章节: {chapters}")

        # 更新封面（仅当不存在时）
        cover_path = os.path.join(comic_path, 'cover.png')
        if not os.path.exists(cover_path):
            search_paths = [comic_base_path] + [os.path.join(comic_base_path, d) for d in os.listdir(comic_base_path) if os.path.isdir(os.path.join(comic_base_path, d))]
            
            cover_found = False
            for search_dir in search_paths:
                if cover_found: break
                for item in os.listdir(search_dir):
                    if any(name in item.lower() for name in COVER_NAMES) and item.lower().endswith(SUPPORTED_FORMATS):
                        try:
                            with Image.open(os.path.join(search_dir, item)) as img:
                                img.convert('RGB').save(cover_path, 'PNG')
                            logger.info(f"[{task_id}] 找到并保存封面图到: {cover_path}")
                            cover_found = True
                            break
                        except Exception as e:
                            logger.error(f"[{task_id}] 处理封面图 {item} 时出错: {e}")
            if not cover_found: logger.warning(f"[{task_id}] 未找到封面图。")

        total_images = sum(len(sorted([f for f in os.listdir(os.path.join(comic_base_path, c)) if f.lower().endswith(SUPPORTED_FORMATS) and not any(cn in f.lower() for cn in COVER_NAMES)], key=natural_sort_key)) for c in chapters)
        if total_images == 0: raise ValueError("漫画中未找到有效图片。")

        processed_images = 0
        total_chapters = len(chapters)
        for i, chapter_name in enumerate(chapters):
            chapter_path = os.path.join(comic_base_path, chapter_name)
            image_files = sorted([f for f in os.listdir(chapter_path) if f.lower().endswith(SUPPORTED_FORMATS) and not any(cn in f.lower() for cn in COVER_NAMES)], key=natural_sort_key)
            
            if not image_files:
                logger.warning(f"[{task_id}] 章节 '{chapter_name}' 中未找到有效图片，跳过。")
                continue

            # 如果章节已存在，则删除旧章节数据
            chapter_pic_storage_path = os.path.join(pic_storage_path, chapter_name)
            if os.path.exists(chapter_pic_storage_path):
                shutil.rmtree(chapter_pic_storage_path)
                logger.info(f"[{task_id}] 已删除旧的图片存储目录: {chapter_pic_storage_path}")
            
            chapter_pic_detail_path = os.path.join(pic_detail_base_path, chapter_name)
            if os.path.exists(chapter_pic_detail_path):
                shutil.rmtree(chapter_pic_detail_path)
                logger.info(f"[{task_id}] 已删除旧的图片详情目录: {chapter_pic_detail_path}")

            chapter_summary_path = os.path.join(cap_summary_base_path, chapter_name)
            if os.path.exists(chapter_summary_path):
                shutil.rmtree(chapter_summary_path)
                logger.info(f"[{task_id}] 已删除旧的章节摘要目录: {chapter_summary_path}")

            # 创建新章节目录
            os.makedirs(chapter_pic_storage_path, exist_ok=True)
            os.makedirs(chapter_pic_detail_path, exist_ok=True)
            os.makedirs(chapter_summary_path, exist_ok=True)

            manifest_path = os.path.join(chapter_pic_detail_path, 'manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(image_files, f, ensure_ascii=False, indent=4)
            logger.info(f"[{task_id}] 章节 '{chapter_name}' 的文件清单已保存。")

            page_descriptions_map = {}
            max_workers = int(os.getenv("MAX_CONCURRENT_REQUESTS", 4))

            for img_file in image_files:
                src_img_path = os.path.join(chapter_path, img_file)
                dest_img_path = os.path.join(chapter_pic_storage_path, img_file)
                shutil.move(src_img_path, dest_img_path)
            logger.info(f"[{task_id}] 章节 '{chapter_name}' 的所有图片已移动到永久存储位置。")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_img = {executor.submit(_analyze_image_task, task_id, chapter_name, img_file, os.path.join(chapter_pic_storage_path, img_file)): img_file for img_file in image_files}

                for future in concurrent.futures.as_completed(future_to_img):
                    img_file = future_to_img[future]
                    try:
                        _, description = future.result()
                        if description:
                            page_descriptions_map[img_file] = description
                            desc_filename = os.path.splitext(img_file)[0] + '.txt'
                            with open(os.path.join(chapter_pic_detail_path, desc_filename), 'w', encoding='utf-8') as f:
                                f.write(description)
                        
                        processed_images += 1
                        progress = (processed_images / total_images) * 95
                        details = f'章节 {chapter_name} ({i+1}/{total_chapters}): 分析图片 {processed_images}/{total_images}'
                        update_task_status(task_id, {'status': 'AI处理中', 'progress': progress, 'details': details})

                    except Exception as exc:
                        logger.error(f'[{task_id}] 图片 {img_file} 生成时发生错误: {exc}', exc_info=True)

            page_descriptions = [page_descriptions_map[img_file] for img_file in image_files if img_file in page_descriptions_map]

            if page_descriptions:
                details = f'正在为章节 {chapter_name} 生成摘要...'
                update_task_status(task_id, {'details': details})
                logger.info(f"[{task_id}] {details}")
                
                full_description_text = "\n\n".join(page_descriptions)
                # 注意：summarize_text 也需要修改以使用新的状态更新机制
                # 目前假设 summarize_text 内部也已更新或不直接修改状态
                summary_chunks = list(summarize_text(full_description_text, task_id, chapter_name))
                chapter_summary = "".join(summary_chunks)
                
                with open(os.path.join(chapter_summary_path, 'summary.txt'), 'w', encoding='utf-8') as f:
                    f.write(chapter_summary)
                logger.info(f"[{task_id}] [摘要完成] 章节 {chapter_name} 摘要已保存。")

                # 使用稳定的漫画哈希来添加嵌入
                embedding = get_embedding(chapter_summary)
                add_embedding(comic_hash, chapter_name, chapter_summary, embedding)

        update_task_status(task_id, {'status': '完成', 'progress': 100, 'details': '所有章节处理完毕。', 'end_time': time.time()})
        logger.info(f"[{task_id}] 漫画 '{comic_name}' 处理完成。")

    except Exception as e:
        logger.error(f"[{task_id}] 处理漫画时发生严重错误: {e}", exc_info=True)
        update_task_status(task_id, {'status': '失败', 'details': str(e), 'end_time': time.time()})
    finally:
        if os.path.exists(temp_extract_path):
            shutil.rmtree(temp_extract_path)
            logger.info(f"[{task_id}] 已清理临时文件: {temp_extract_path}")
