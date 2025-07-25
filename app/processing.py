import os
import zipfile
import hashlib
import shutil
import json
import threading
from collections import deque
import time
import concurrent.futures
import re

from PIL import Image
import io
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv
import chromadb

from vision import analyze_image
from logger_setup import logger

# --- 初始化 ---
load_dotenv()

# --- 路径和数据库配置 ---
DATA_BASE_PATH = './data/comicdb'
CHROMA_PATH = os.path.join(DATA_BASE_PATH, 'chroma')
os.makedirs(DATA_BASE_PATH, exist_ok=True)
os.makedirs(CHROMA_PATH, exist_ok=True)

# --- OpenAI 客户端和模型配置 ---
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_API_BASE"),
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gpt-3.5-turbo")

# --- 任务队列和状态管理 ---
processing_queue = deque()
processing_statuses = {}
queue_lock = threading.Lock()

# --- ChromaDB 连接 ---
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="comic_chapters")


def natural_sort_key(s):
    """自然排序键函数，用于正确排序包含数字的字符串。"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


# --- 核心 AI 和文本处理函数 ---

def get_embedding(text, model=EMBEDDING_MODEL):
    """为文本生成 embedding 向量。"""
    text = text.replace("\n", " ")
    return client.embeddings.create(input=[text], model=model).data[0].embedding

def summarize_text(text, task_id, chapter_name, model=SUMMARY_MODEL):
    """以流式方式为文本生成摘要，并将日志写入特定的缓冲区。"""
    summary_log_key = f"summary_{chapter_name}"
    try:
        if 'stream_buffers' not in processing_statuses[task_id]:
            processing_statuses[task_id]['stream_buffers'] = {}
        processing_statuses[task_id]['stream_buffers'][summary_log_key] = deque()

        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个善于总结的助手。请根据以下漫画各页描述，生成一个连贯的本章节摘要，用作EMBEDDING关键词搜索。只输出关键词和复杂事件总结关键句（用作事件比对）;格式：\n关键词\n关键词\n关键词。\n\n关键句：\n关键句\n关键句\n关键句。"},
                {"role": "user", "content": text}
            ],
            max_tokens=16384,
            stream=True,
        )
        
        buffer = processing_statuses[task_id]['stream_buffers'][summary_log_key]
        buffer.append("[摘要开始]\n")
        
        summary_content = []
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                buffer.append(content)
                summary_content.append(content)
                yield content
        
        buffer.append("\n[摘要结束]\n")
        
    except Exception as e:
        error_message = f"生成摘要时出错: {e}"
        logger.error(f"[{task_id}] {error_message}")
        if 'stream_buffers' in processing_statuses[task_id] and summary_log_key in processing_statuses[task_id]['stream_buffers']:
            processing_statuses[task_id]['stream_buffers'][summary_log_key].append(error_message)
        yield "摘要生成失败。"

# --- 任务处理和工作流 ---

def process_comic(filepath):
    """将漫画处理任务添加到队列中，并初始化其状态。"""
    try:
        with open(filepath, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        task_id = file_hash
        original_filename = os.path.basename(filepath)

        with queue_lock:
            if task_id in processing_statuses:
                logger.warning(f"任务 {task_id} ({original_filename}) 已存在，跳过。")
                return

            processing_queue.append({
                'task_id': task_id,
                'filepath': filepath,
                'original_filename': original_filename
            })
            
            processing_statuses[task_id] = {
                'task_id': task_id,
                'filename': original_filename,
                'status': '排队中',
                'progress': 0,
                'details': '',
                'start_time': time.time(),
                'end_time': None,
                'stream_buffers': {}
            }
            logger.info(f"任务 {task_id} ({original_filename}) 已加入队列。")

    except Exception as e:
        logger.error(f"将任务添加到队列时出错: {e}")


def _analyze_image_task(task_id, chapter_name, img_file, img_path):
    """封装单个图片分析任务，使其可在线程池中运行。"""
    log_key = f"{chapter_name}_{os.path.splitext(img_file)[0]}"
    
    if 'stream_buffers' not in processing_statuses[task_id]:
        processing_statuses[task_id]['stream_buffers'] = {}
    processing_statuses[task_id]['stream_buffers'][log_key] = deque()
    
    buffer = processing_statuses[task_id]['stream_buffers'][log_key]
    
    logger.info(f"[{task_id}] [图片分析中] 开始分析图片 {img_file}...")
    buffer.append(f"[开始分析图片: {img_file}]\n")
    
    description_chunks = []
    try:
        # 直接传递图片路径给 analyze_image
        for chunk in analyze_image(img_path):
            buffer.append(chunk)
            description_chunks.append(chunk)
        
        description = "".join(description_chunks)
        buffer.append(f"\n[图片分析结束: {img_file}]\n\n")
        buffer.append({'type': 'stream_end', 'stream_id': log_key})
        
        logger.info(f"[{task_id}] [图片分析完成] 图片 {img_file} 分析完毕。")
        return img_file, description
    except Exception as e:
        error_message = f"分析图片 {img_file} 时发生严重错误: {e}"
        logger.error(f"[{task_id}] {error_message}", exc_info=True)
        buffer.append(f"\n[错误: {error_message}]\n")
        buffer.append({'type': 'stream_end', 'stream_id': log_key, 'error': True})
        return img_file, None


def _process_zip_file(task):
    """实际处理单个 ZIP 漫画文件的内部函数。"""
    task_id = task['task_id']
    filepath = task['filepath']
    original_filename = task['original_filename']
    
    processing_statuses[task_id].update({'status': '正在处理', 'details': '开始解压文件...'})

    comic_hash = task_id
    comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
    temp_extract_path = os.path.join('./tmp', comic_hash)

    try:
        if os.path.exists(comic_path): shutil.rmtree(comic_path)
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
            
        os.makedirs(comic_path, exist_ok=True)
        os.makedirs(temp_extract_path, exist_ok=True)

        logger.info(f"[{task_id}] 解压文件到 {temp_extract_path}")
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_path)
        
        extracted_items = os.listdir(temp_extract_path)
        comic_base_path = temp_extract_path
        comic_name = os.path.splitext(original_filename)[0]

        if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_extract_path, extracted_items[0])):
            comic_name = extracted_items[0]
            processing_statuses[task_id]['filename'] = comic_name
            comic_base_path = os.path.join(temp_extract_path, comic_name)
            logger.info(f"[{task_id}] 检测到单层目录，漫画名称设为: {comic_name}")
        else:
            logger.info(f"[{task_id}] 未检测到单层目录，使用默认漫画名称: {comic_name}")

        # 不再移动源 zip 文件，而是直接删除它
        os.remove(filepath)
        logger.info(f"[{task_id}] 原始 zip 文件已被处理和删除: {filepath}")

        with open(os.path.join(comic_path, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': comic_name}, f, ensure_ascii=False, indent=4)

        pic_storage_path = os.path.join(comic_path, 'pic') # 新的图片存储目录
        pic_detail_base_path = os.path.join(comic_path, 'pic_detail')
        cap_summary_base_path = os.path.join(comic_path, 'cap_summary')
        os.makedirs(pic_storage_path, exist_ok=True)
        os.makedirs(pic_detail_base_path, exist_ok=True)
        os.makedirs(cap_summary_base_path, exist_ok=True)

        potential_chapters = [d for d in os.listdir(comic_base_path) if os.path.isdir(os.path.join(comic_base_path, d))]
        chapters = sorted(potential_chapters, key=natural_sort_key) if potential_chapters else ['.']
        logger.info(f"[{task_id}] 找到章节: {chapters}")

        supported_formats = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
        cover_names = ('cover', 'folder')

        cover_path = os.path.join(comic_path, 'cover.png')
        search_paths = [comic_base_path] + [os.path.join(comic_base_path, d) for d in os.listdir(comic_base_path) if os.path.isdir(os.path.join(comic_base_path, d))]
        
        cover_found = False
        for search_dir in search_paths:
            if cover_found: break
            for item in os.listdir(search_dir):
                if any(name in item.lower() for name in cover_names) and item.lower().endswith(supported_formats):
                    try:
                        with Image.open(os.path.join(search_dir, item)) as img:
                            img.convert('RGB').save(cover_path, 'PNG')
                        logger.info(f"[{task_id}] 找到并保存封面图到: {cover_path}")
                        cover_found = True
                        break
                    except Exception as e:
                        logger.error(f"[{task_id}] 处理封面图 {item} 时出错: {e}")
        
        if not cover_found: logger.warning(f"[{task_id}] 未找到封面图。")

        total_images = sum(len(sorted([f for f in os.listdir(os.path.join(comic_base_path, c)) if f.lower().endswith(supported_formats) and not any(cn in f.lower() for cn in cover_names)], key=natural_sort_key)) for c in chapters)
        if total_images == 0: raise ValueError("漫画中未找到有效图片。")

        processed_images = 0
        total_chapters = len(chapters)
        for i, chapter_name in enumerate(chapters):
            chapter_path = os.path.join(comic_base_path, chapter_name)
            image_files = sorted([f for f in os.listdir(chapter_path) if f.lower().endswith(supported_formats) and not any(cn in f.lower() for cn in cover_names)], key=natural_sort_key)
            
            if not image_files:
                logger.warning(f"[{task_id}] 章节 '{chapter_name}' 中未找到有效图片，跳过。")
                continue

            chapter_pic_storage_path = os.path.join(pic_storage_path, chapter_name) # 为每个章节创建图片存储目录
            chapter_pic_detail_path = os.path.join(pic_detail_base_path, chapter_name)
            chapter_summary_path = os.path.join(cap_summary_base_path, chapter_name)
            os.makedirs(chapter_pic_storage_path, exist_ok=True)
            os.makedirs(chapter_pic_detail_path, exist_ok=True)
            os.makedirs(chapter_summary_path, exist_ok=True)

            manifest_path = os.path.join(chapter_pic_detail_path, 'manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(image_files, f, ensure_ascii=False, indent=4)
            logger.info(f"[{task_id}] 章节 '{chapter_name}' 的文件清单已保存。")

            page_descriptions_map = {}
            max_workers = int(os.getenv("MAX_CONCURRENT_REQUESTS", 4))

            # 将图片文件移动到永久存储位置
            for img_file in image_files:
                src_img_path = os.path.join(chapter_path, img_file)
                dest_img_path = os.path.join(chapter_pic_storage_path, img_file)
                shutil.move(src_img_path, dest_img_path)
            logger.info(f"[{task_id}] 章节 '{chapter_name}' 的所有图片已移动到永久存储位置。")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 更新任务以使用新的图片路径
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
                        processing_statuses[task_id].update({'status': 'AI处理中', 'progress': progress, 'details': details})

                    except Exception as exc:
                        logger.error(f'[{task_id}] 图片 {img_file} 生成时发生错误: {exc}', exc_info=True)

            page_descriptions = [page_descriptions_map[img_file] for img_file in image_files if img_file in page_descriptions_map]

            if page_descriptions:
                details = f'正在为章节 {chapter_name} 生成摘要...'
                processing_statuses[task_id].update({'details': details})
                logger.info(f"[{task_id}] {details}")
                
                full_description_text = "\n\n".join(page_descriptions)
                summary_chunks = list(summarize_text(full_description_text, task_id, chapter_name))
                chapter_summary = "".join(summary_chunks)
                
                with open(os.path.join(chapter_summary_path, 'summary.txt'), 'w', encoding='utf-8') as f:
                    f.write(chapter_summary)
                logger.info(f"[{task_id}] [摘要完成] 章节 {chapter_name} 摘要已保存。")

                embedding = get_embedding(chapter_summary)
                collection.add(embeddings=[embedding], documents=[chapter_summary], metadatas=[{'comic_hash': comic_hash, 'chapter': chapter_name}], ids=[f"{comic_hash}_{chapter_name}"])
                logger.info(f"[{task_id}] 章节 '{chapter_name}' 的 embedding 已存入数据库。")

        processing_statuses[task_id].update({'status': '完成', 'progress': 100, 'details': '所有章节处理完毕。', 'end_time': time.time()})
        logger.info(f"[{task_id}] 漫画 '{comic_name}' 处理完成。")

    except Exception as e:
        logger.error(f"[{task_id}] 处理漫画时发生严重错误: {e}", exc_info=True)
        processing_statuses[task_id].update({'status': '失败', 'details': str(e), 'end_time': time.time()})
    finally:
        if os.path.exists(temp_extract_path):
            shutil.rmtree(temp_extract_path)
            logger.info(f"[{task_id}] 已清理临时文件: {temp_extract_path}")


def worker():
    """后台工作线程"""
    while True:
        task = None
        with queue_lock:
            if processing_queue:
                task = processing_queue.popleft()
        
        if task:
            logger.info(f"工作线程获取到新任务: {task['task_id']}")
            _process_zip_file(task)
        else:
            time.sleep(1)

def get_all_processing_statuses():
    """返回所有任务的状态。"""
    with queue_lock:
        return sorted(processing_statuses.values(), key=lambda x: x['start_time'], reverse=True)

def search_comics_by_embedding(query, k=1000):
    """根据用户查询在 ChromaDB 中执行语义搜索。"""
    if not query: return []
    query_embedding = get_embedding(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=k)
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

def start_worker_thread():
    """启动后台工作线程。"""
    if any(t.name == 'comic-worker' for t in threading.enumerate()): return
    worker_thread = threading.Thread(target=worker, daemon=True, name='comic-worker')
    worker_thread.start()
    logger.info("后台处理工作线程已启动。")

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

def delete_comic(comic_hash):
    """删除指定的漫画及其所有相关数据。"""
    try:
        comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
        if os.path.exists(comic_path):
            shutil.rmtree(comic_path)
            logger.info(f"已从文件系统删除漫画目录: {comic_path}")
        results = collection.get(where={"comic_hash": comic_hash})
        if results and results['ids']:
            collection.delete(ids=results['ids'])
            logger.info(f"已从 ChromaDB 中删除 {len(results['ids'])} 个与漫画 {comic_hash} 相关的条目。")
        
        # 3. 从内存中的任务状态列表中删除
        with queue_lock:
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
        old_pic_path = os.path.join(comic_path, 'pic', old_name) # 新增：旧的图片目录
        new_detail_path = os.path.join(comic_path, 'pic_detail', new_name)
        new_pic_path = os.path.join(comic_path, 'pic', new_name) # 新增：新的图片目录
        if os.path.exists(old_summary_path): os.rename(old_summary_path, new_summary_path)
        if os.path.exists(old_detail_path): os.rename(old_detail_path, new_detail_path)
        if os.path.exists(old_pic_path): os.rename(old_pic_path, new_pic_path) # 新增：重命名图片目录
        old_id = f"{comic_hash}_{old_name}"
        new_id = f"{comic_hash}_{new_name}"
        results = collection.get(ids=[old_id], include=["embeddings", "documents", "metadatas"])
        if results and results['ids']:
            collection.add(ids=[new_id], embeddings=results['embeddings'], documents=results['documents'], metadatas=[{'comic_hash': comic_hash, 'chapter': new_name}])
            collection.delete(ids=[old_id])
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
        collection.delete(ids=[chapter_id])
        logger.info(f"已从 ChromaDB 中删除章节 ID: {chapter_id}")

        return True, f"章节 '{chapter_name}' 删除成功"
    except Exception as e:
        logger.error(f"删除章节 {comic_hash}/{chapter_name} 时出错: {e}", exc_info=True)
        return False, f"删除失败: {e}"
