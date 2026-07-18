#!/usr/bin/env python3
"""Script to run 3 test queries against the Qdrant hybrid database (Dense + BM25)
and rerank the top candidates using NVIDIARerank (nv-rerank-qa-mistral-4b:1).
"""

import os
import sys
import unicodedata
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import SparseTextEmbedding
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings, NVIDIARerank
from langchain_core.documents import Document

# Force UTF-8 encoding for stdout on Windows
if sys.platform.startswith('win'):
    try:
        # pyrefly: ignore [missing-attribute]
        sys.stdout.reconfigure(encoding='utf-8')
        # pyrefly: ignore [missing-attribute]
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Setup paths
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
ENV_PATH = BACKEND_DIR / ".env"

# Load environment
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

QRANT_URL = os.getenv("QRANT_URL") or os.getenv("QDRANT_URL")
QRANT_API = os.getenv("QRANT_API") or os.getenv("QDRANT_API")
NVIDIA_API_KEY = os.getenv("NVIDIA_API") or os.getenv("NVIDIA_API_KEY") or ""
os.environ["NVIDIA_API_KEY"] = NVIDIA_API_KEY

if not QRANT_URL or not QRANT_API or not NVIDIA_API_KEY:
    print("Error: Missing credentials in .env (QRANT_URL, QRANT_API, or NVIDIA_API)")
    sys.exit(1)


def test_hybrid_rag_and_rerank():
    print(f"Connecting to Qdrant Vector DB at {QRANT_URL}...")
    client = QdrantClient(url=QRANT_URL, api_key=QRANT_API, timeout=30)
    
    # Initialize NVIDIA Embeddings
    print("Initializing NVIDIA Embeddings (nvidia/nv-embedcode-7b-v1)...")
    nvidia_embeddings = NVIDIAEmbeddings(
        model="nvidia/nv-embedcode-7b-v1",
        api_key=NVIDIA_API_KEY,
        truncate="NONE"
    )
    
    # Initialize FastEmbed Sparse BM25
    print("Initializing FastEmbed SparseTextEmbedding (Qdrant/bm25)...")
    sparse_embedding_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    
    # Initialize NVIDIARerank
    print("Initializing NVIDIARerank (nv-rerank-qa-mistral-4b:1)...")
    reranker = NVIDIARerank(
        model="nv-rerank-qa-mistral-4b:1",
        api_key=NVIDIA_API_KEY,
    )
    
    collection_name = "luat_hinh_su"
    
    # 3 Test Queries
    queries = [
        {
            "id": 1,
            "title": "Trường hợp 1: Tội rửa tiền (Money Laundering)",
            "query": "Hành vi hợp pháp hóa tiền, tài sản do phạm tội mà có bị xử lý như thế nào theo tội rửa tiền?"
        },
        {
            "id": 2,
            "title": "Trường hợp 2: Tội trốn thuế (Tax Evasion)",
            "query": "Trốn thuế từ bao nhiêu tiền trở lên thì bị truy cứu trách nhiệm hình sự và hình phạt cao nhất là gì?"
        },
        {
            "id": 3,
            "title": "Trường hợp 3: Tội tài trợ khủng bố (Terrorist Financing)",
            "query": "Hành vi tài trợ tiền hoặc tài sản cho tổ chức, cá nhân khủng bố bị phạt tù bao nhiêu năm?"
        },
        {
            "id": 4,
            "title": "Trường hợp 4: Tội thao túng thị trường chứng khoán (Market Manipulation)",
            "query": "Mức xử phạt hình sự đối với tội thao túng thị trường chứng khoán được quy định như thế nào?"
        }
    ]
    
    print("\n================== BẮT ĐẦU CHẠY THỬ NGHIỆM HYBRID RAG + RERANK ==================\n")
    
    for item in queries:
        # pyrefly: ignore [bad-argument-type, missing-attribute]
        query_text = unicodedata.normalize("NFC", item["query"])
        print(f"--- {item['title']} ---")
        print(f"Câu hỏi: \"{query_text}\"")
        
        # 1. Generate Dense vector query
        dense_vector = nvidia_embeddings.embed_query(query_text)
        
        # 2. Generate Sparse vector query
        # FastEmbed sparse embed returns a generator
        sparse_vector_gen = sparse_embedding_model.embed([query_text])
        sparse_vec = list(sparse_vector_gen)[0]
        
        # Convert to qdrant models.SparseVector
        sparse_qdrant_vec = models.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist()
        )
        
        # 3. Perform Hybrid Search with RRF Fusion (Retrieve Top 30)
        print("  Performing Qdrant Hybrid Search (Dense Cosine + Sparse BM25 via RRF)...")
        prefetch_dense = models.Prefetch(
            query=dense_vector,
            using="dense",
            limit=30
        )
        prefetch_sparse = models.Prefetch(
            query=sparse_qdrant_vec,
            using="sparse-bm25",
            limit=30
        )
        
        hybrid_results = client.query_points(
            collection_name=collection_name,
            prefetch=[prefetch_dense, prefetch_sparse],
            query=models.FusionQuery(
                fusion=models.Fusion.RRF
            ),
            limit=30
        )
        
        # Parse points into LangChain Documents
        documents_to_rerank = []
        for hit in hybrid_results.points:
            # pyrefly: ignore [missing-attribute]
            doc_content = hit.payload.get("document", "")
            meta = {
                # pyrefly: ignore [missing-attribute]
                "chapter": hit.payload.get("chapter", "N/A"),
                # pyrefly: ignore [missing-attribute]
                "section": hit.payload.get("section", "N/A"),
                # pyrefly: ignore [missing-attribute]
                "article": hit.payload.get("article", "N/A"),
                # pyrefly: ignore [missing-attribute]
                "article_number": hit.payload.get("article_number", None),
                "hybrid_score": hit.score
            }
            documents_to_rerank.append(Document(page_content=doc_content, metadata=meta))
            
        print(f"  Retrieved {len(documents_to_rerank)} candidates. Running NVIDIARerank...")
        
        # 4. Rerank candidates using NVIDIARerank
        reranked_docs = reranker.compress_documents(
            query=query_text,
            documents=documents_to_rerank
        )
        
        # 5. Output top 3 results
        print("\n  >>> KẾT QUẢ SAU KHI RERANK (TOP 3): <<<")
        for rank, doc in enumerate(reranked_docs[:3], 1):
            meta = doc.metadata
            relevance_score = meta.get("relevance_score", 0.0)
            
            print(f"\n  [Hạng #{rank}] Relevance Score: {relevance_score:.4f} (Hybrid Score: {meta.get('hybrid_score', 'N/A')})")
            print(f"  Chương: {meta.get('chapter')}")
            print(f"  Mục: {meta.get('section')}")
            print(f"  Điều luật: {meta.get('article')}")
            print("  " + "-" * 55)
            
            # Print preview of document text, skipping prepended chapter/section strings
            text_lines = doc.page_content.split("\n")
            printed_lines = 0
            for line in text_lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("Chương ") or stripped.startswith("Mục "):
                    continue
                print(f"    {line}")
                printed_lines += 1
                if printed_lines >= 6:
                    break
            if len(text_lines) > printed_lines:
                print("    ...")
                
        print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    test_hybrid_rag_and_rerank()
