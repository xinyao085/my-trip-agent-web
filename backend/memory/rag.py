"""
memory/rag.py — 旅行知识库 RAG 模块

特性：
  - 文本切块：RecursiveCharacterTextSplitter，每块 400 字符，重叠 50
  - 文件变更检测：MD5 哈希比对，只对新增或修改的文件增量更新
  - 唯一 Chunk ID：{城市名}_{块序号}，metadata 记录来源、哈希、位置信息

依赖：pip install langchain-chroma chromadb langchain-text-splitters
环境变量：
  EMBED_MODEL_ID  Embedding 模型，默认 text-embedding-v3（DashScope 支持）
"""

import hashlib
import json
import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

_CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
_KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
_HASH_FILE = _CHROMA_DIR / "file_hashes.json"

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=400,
    chunk_overlap=50,
    separators=["\n\n", "\n", "。", "，", " ", ""],
)

_vectorstore: Chroma | None = None
_synced: bool = False


# ---------- 工具函数 ----------

def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=os.getenv("EMBED_MODEL_ID", "text-embedding-v3"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
    )


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _load_hashes() -> dict[str, str]:
    if _HASH_FILE.exists():
        return json.loads(_HASH_FILE.read_text(encoding="utf-8"))
    return {}


def _save_hashes(hashes: dict[str, str]) -> None:
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _HASH_FILE.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 增量同步 ----------

def _sync_knowledge(vs: Chroma) -> None:
    """
    扫描 knowledge/ 目录，与存储的 MD5 哈希比对：
      - 新文件或内容变更 → 删除旧 chunks，重新切块并索引
      - 未变更文件 → 跳过
      - 已删除文件 → 删除对应 chunks（可选，当前仅跳过）
    """
    if not _KNOWLEDGE_DIR.exists():
        return

    saved_hashes = _load_hashes()
    current_hashes: dict[str, str] = {}

    for path in sorted(_KNOWLEDGE_DIR.glob("*.txt")):
        filename = path.name
        stem = path.stem
        file_hash = _md5(path)
        current_hashes[filename] = file_hash

        if saved_hashes.get(filename) == file_hash:
            continue  # 未变更，跳过

        # 删除该文件旧的所有 chunks
        existing = vs.get(where={"source": filename})
        if existing["ids"]:
            vs.delete(ids=existing["ids"])

        # 切块并重新索引
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue

        chunks = _splitter.split_text(text)
        docs = []
        ids = []
        for i, chunk in enumerate(chunks):
            ids.append(f"{stem}_{i}")
            docs.append(Document(
                page_content=chunk,
                metadata={
                    "source": filename,
                    "city": stem,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "file_hash": file_hash,
                },
            ))
        vs.add_documents(docs, ids=ids)

    _save_hashes(current_hashes)


# ---------- 对外接口 ----------

def get_vectorstore() -> Chroma:
    """懒初始化 + 启动时增量同步知识文档（每个进程只同步一次）。"""
    global _vectorstore, _synced
    if _vectorstore is None:
        _vectorstore = Chroma(
            collection_name="travel_knowledge",
            embedding_function=_get_embeddings(),
            persist_directory=str(_CHROMA_DIR),
        )
    if not _synced:
        _sync_knowledge(_vectorstore)
        _synced = True
    return _vectorstore


def retrieve(query: str, k: int = 3) -> str:
    """
    语义检索最相关的 k 个 chunk，拼接后返回。
    出错或无结果时返回空字符串，不影响主流程。
    """
    try:
        results = get_vectorstore().similarity_search(query, k=k)
        if not results:
            return ""
        return "\n\n".join(doc.page_content for doc in results)
    except Exception:
        return ""
