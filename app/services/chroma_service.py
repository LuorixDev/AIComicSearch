import os
import chromadb

from ..utils.logger import logger

# --- 路径和数据库配置 ---
DATA_BASE_PATH = './data/comicdb'
CHROMA_PATH = os.path.join(DATA_BASE_PATH, 'chroma')
os.makedirs(DATA_BASE_PATH, exist_ok=True)
os.makedirs(CHROMA_PATH, exist_ok=True)

# --- ChromaDB 连接 ---
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="comic_chapters")

def add_embedding(comic_hash, chapter_name, chapter_summary, embedding):
    """向 ChromaDB 添加一个新的 embedding。"""
    collection.add(
        embeddings=[embedding],
        documents=[chapter_summary],
        metadatas=[{'comic_hash': comic_hash, 'chapter': chapter_name}],
        ids=[f"{comic_hash}_{chapter_name}"]
    )
    logger.info(f"章节 '{chapter_name}' 的 embedding 已存入数据库。")

def search_by_embedding(embedding, k=1000):
    """通过 embedding 在 ChromaDB 中进行搜索。"""
    return collection.query(query_embeddings=[embedding], n_results=k)

def delete_by_comic_hash(comic_hash):
    """根据 comic_hash 删除 ChromaDB 中的条目。"""
    results = collection.get(where={"comic_hash": comic_hash})
    if results and results['ids']:
        collection.delete(ids=results['ids'])
        logger.info(f"已从 ChromaDB 中删除 {len(results['ids'])} 个与漫画 {comic_hash} 相关的条目。")

def delete_by_chapter_id(chapter_id):
    """根据 chapter_id 删除 ChromaDB 中的条目。"""
    collection.delete(ids=[chapter_id])
    logger.info(f"已从 ChromaDB 中删除章节 ID: {chapter_id}")

def rename_chapter_embedding(comic_hash, old_name, new_name):
    """在 ChromaDB 中重命名一个章节。"""
    old_id = f"{comic_hash}_{old_name}"
    new_id = f"{comic_hash}_{new_name}"
    results = collection.get(ids=[old_id], include=["embeddings", "documents", "metadatas"])
    if results and results['ids']:
        collection.add(
            ids=[new_id],
            embeddings=results['embeddings'],
            documents=results['documents'],
            metadatas=[{'comic_hash': comic_hash, 'chapter': new_name}]
        )
        collection.delete(ids=[old_id])
