#!/usr/bin/env python3
"""Script to run 3 test semantic search queries against the Qdrant database
to verify retrieval accuracy for financial and AML crimes.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient

# Force UTF-8 encoding for stdout on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
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

if not QRANT_URL or not QRANT_API:
    print("Error: QRANT_URL or QRANT_API environment variables are not set in .env")
    sys.exit(1)


def run_test_queries():
    print(f"Connecting to Qdrant Vector DB at {QRANT_URL}...")
    client = QdrantClient(url=QRANT_URL, api_key=QRANT_API)
    
    # Set the same embedding model
    embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    client.set_model(embedding_model)
    
    collection_name = "luat_hinh_su"
    
    # 3 Test Queries related to AML, financial crimes, and terrorism financing
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
        }
    ]
    
    print("\n================== BẮT ĐẦU CHẠY THỬ NGHIỆM 3 TRƯỜNG HỢP ==================\n")
    
    for item in queries:
        print(f"--- {item['title']} ---")
        print(f"Câu hỏi: \"{item['query']}\"")
        
        # Search Qdrant
        results = client.query(
            collection_name=collection_name,
            query_text=item["query"],
            limit=2  # Top 2 most similar articles
        )
        
        for rank, hit in enumerate(results, 1):
            print(f"\n[Kết quả #{rank}] Score: {hit.score:.4f}")
            print(f"Chương: {hit.metadata.get('chapter', 'N/A')}")
            print(f"Mục: {hit.metadata.get('section', 'N/A')}")
            print(f"Điều luật: {hit.metadata.get('article', 'N/A')}")
            print("-" * 50)
            
            # Print text preview
            lines = hit.document.split("\n")
            # Skip chapter/section headers in printing if they are prepended in the first 2 lines
            printed_lines = 0
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # Skip lines that are just Chapter/Section names which were prepended
                if stripped.startswith("Chương ") or stripped.startswith("Mục "):
                    continue
                print(f"  {line}")
                printed_lines += 1
                if printed_lines >= 6:  # Print top 6 content lines
                    break
            if len(lines) > printed_lines:
                print("  ...")
        
        print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    run_test_queries()
