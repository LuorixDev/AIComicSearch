import os
import shutil
from .services.chroma_service import collection, delete_by_chapter_id
from .models import DATA_BASE_PATH, delete_chapter

def get_filesystem_data():
    """获取文件系统中的所有漫画章节数据"""
    fs_data = set()
    if not os.path.exists(DATA_BASE_PATH):
        return fs_data
    for comic_hash in os.listdir(DATA_BASE_PATH):
        comic_path = os.path.join(DATA_BASE_PATH, comic_hash)
        summary_dir = os.path.join(comic_path, 'cap_summary')
        if os.path.isdir(comic_path) and os.path.exists(summary_dir):
            for chapter_name in os.listdir(summary_dir):
                fs_data.add(f"{comic_hash}/{chapter_name}")
    return fs_data

def get_chromadb_data():
    """获取ChromaDB中的所有漫画章节数据"""
    chroma_data = set()
    results = collection.get()
    for i in range(len(results['ids'])):
        meta = results['metadatas'][i]
        comic_hash = meta['comic_hash']
        chapter_name = meta['chapter']
        chroma_data.add(f"{comic_hash}/{chapter_name}")
    return chroma_data

def validate_data_consistency():
    """验证文件系统和ChromaDB之间的数据一致性"""
    fs_data = get_filesystem_data()
    chroma_data = get_chromadb_data()

    extra_in_fs = fs_data - chroma_data
    extra_in_chroma = chroma_data - fs_data

    if not extra_in_fs and not extra_in_chroma:
        print("数据一致性检查通过。")
        return True

    print("检测到数据不一致！")
    if extra_in_fs:
        print("\n以下章节仅存在于文件系统中 (可能需要删除):")
        for item in sorted(list(extra_in_fs)):
            print(f"- {item}")
    
    if extra_in_chroma:
        print("\n以下章节仅存在于数据库中 (可能需要删除):")
        for item in sorted(list(extra_in_chroma)):
            print(f"- {item}")

    while True:
        choice = input("\n是否删除所有异常数据以同步? (Y/N，默认为N): ").strip().upper()
        if choice in ['Y', 'N', '']:
            break
        print("无效输入，请输入 Y 或 N。")

    if choice == 'Y':
        print("\n开始删除操作...")
        # 删除文件系统中多余的数据
        for item in extra_in_fs:
            comic_hash, chapter_name = item.split('/', 1)
            print(f"正在从文件系统删除: {item}")
            chapter_summary_path = os.path.join(DATA_BASE_PATH, comic_hash, 'cap_summary', chapter_name)
            if os.path.exists(chapter_summary_path):
                shutil.rmtree(chapter_summary_path)
            chapter_detail_path = os.path.join(DATA_BASE_PATH, comic_hash, 'pic_detail', chapter_name)
            if os.path.exists(chapter_detail_path):
                shutil.rmtree(chapter_detail_path)

        # 删除ChromaDB中多余的数据
        for item in extra_in_chroma:
            comic_hash, chapter_name = item.split('/', 1)
            chapter_id = f"{comic_hash}_{chapter_name}"
            print(f"正在从数据库删除: {item}")
            delete_by_chapter_id(chapter_id)
        
        print("\n数据同步完成。")
        return True
    else:
        print("\n用户选择不删除异常数据。应用将不会启动。")
        return False
