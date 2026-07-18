#!/usr/bin/env python3
"""Script to convert Vietnamese Penal Code PDF to Markdown, chunk it by Article,
and load it into Qdrant vector database using NVIDIA Embeddings and FastEmbed BM25.
"""

import os
# os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import re
import sys
import uuid
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from fastembed import SparseTextEmbedding
import time
import pymupdf4llm

# Setup paths relative to script location
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
ENV_PATH = BACKEND_DIR / ".env"
DATA_DIR = BACKEND_DIR / "data"
PDF_PATH = DATA_DIR / "luat_hinh_su.pdf"
MD_PATH = DATA_DIR / "luat_hinh_su.md"

# Load environment variables
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
    print(f"Loaded environment from: {ENV_PATH}")
else:
    print(f"Warning: .env file not found at {ENV_PATH}")

# Retrieve credentials
QRANT_URL = os.getenv("QRANT_URL") or os.getenv("QDRANT_URL")
QRANT_API = os.getenv("QRANT_API") or os.getenv("QDRANT_API")

if not QRANT_URL or not QRANT_API:
    print("Error: QRANT_URL or QRANT_API environment variables are not set in .env")
    sys.exit(1)


def convert_pdf_to_md(pdf_path: Path, md_path: Path) -> str:
    """Converts a PDF file to a Markdown file using PyMuPDF4LLM."""
    print(f"Converting PDF '{pdf_path.name}' to Markdown...")
    if not pdf_path.exists():
        print(f"Error: PDF file not found at {pdf_path}")
        sys.exit(1)

    # Convert PDF to MD string
    md_content = pymupdf4llm.to_markdown(str(pdf_path))
    
    # Save markdown file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"Successfully saved Markdown to: {md_path}")
    return md_content


def chunk_markdown_by_articles(md_text: str) -> list[dict]:
    """Chunks the Vietnamese Penal Code markdown text by legal Articles (Điều).
    
    Each chunk is enriched with its Chapter (Chương) and Section (Mục) context.
    """
    print("Parsing and chunking Markdown by articles...")
    lines = md_text.split('\n')
    chunks = []
    
    current_chapter = ""
    current_section = ""
    current_article = ""
    current_article_num = None
    
    # Regex patterns
    # Chapter: e.g., "Chương I", "Chương XXV"
    chapter_pat = re.compile(r'^\s*#*\s*(Chương\s+[IVXLCDM\d\-\w]+.*?)(?:\*\*|##|$)', re.IGNORECASE)
    # Section: e.g., "Mục 1", "Mục I"
    section_pat = re.compile(r'^\s*#*\s*(Mục\s+[IVXLCDM\d\-\w]+.*?)(?:\*\*|##|$)', re.IGNORECASE)
    # Article: e.g., "Điều 1.", "Điều 123.", "**Điều 1.**"
    article_pat = re.compile(r'^\s*#*\s*\*?\*?(Điều\s+(\d+)\b.*?)(?:\*\*|##|$)', re.IGNORECASE)
    
    current_chunk_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        
        # Detect Chapter
        chap_match = chapter_pat.match(stripped_line)
        if chap_match:
            # Update chapter context
            current_chapter = re.sub(r'[*#_]', '', chap_match.group(1)).strip()
            # Also clear section and article when entering new chapter
            current_section = ""
            
        # Detect Section
        sec_match = section_pat.match(stripped_line)
        if sec_match:
            # Update section context
            current_section = re.sub(r'[*#_]', '', sec_match.group(1)).strip()
            
        # Detect Article
        art_match = article_pat.match(stripped_line)
        if art_match:
            # If we were processing a previous article, save it
            if current_article and current_chunk_lines:
                chunk_body = "\n".join(current_chunk_lines).strip()
                # Prepend context to help the retriever locate chapter/section details
                enriched_text = f"{current_chapter}\n{current_section}\n{chunk_body}".strip()
                chunks.append({
                    "text": enriched_text,
                    "metadata": {
                        "chapter": current_chapter,
                        "section": current_section,
                        "article": current_article,
                        "article_number": int(current_article_num) if current_article_num else None,
                        "length": len(enriched_text)
                    }
                })
            
            # Start a new article chunk
            current_article = re.sub(r'[*#_]', '', art_match.group(1)).strip()
            current_article_num = art_match.group(2)
            current_chunk_lines = [line]
        else:
            if current_article:
                current_chunk_lines.append(line)
            else:
                # Text before the first article (Preamble / Lời nói đầu)
                current_chunk_lines.append(line)

    # Save the very last chunk
    if current_article and current_chunk_lines:
        chunk_body = "\n".join(current_chunk_lines).strip()
        enriched_text = f"{current_chapter}\n{current_section}\n{chunk_body}".strip()
        chunks.append({
            "text": enriched_text,
            "metadata": {
                "chapter": current_chapter,
                "section": current_section,
                "article": current_article,
                "article_number": int(current_article_num) if current_article_num else None,
                "length": len(enriched_text)
            }
        })
    elif not current_article and current_chunk_lines:
        # Preamble fallback if no articles found yet
        preamble_text = "\n".join(current_chunk_lines).strip()
        if preamble_text:
            chunks.append({
                "text": preamble_text,
                "metadata": {
                    "chapter": "",
                    "section": "",
                    "article": "Lời nói đầu",
                    "article_number": 0,
                    "length": len(preamble_text)
                }
            })

    # Fallback if parsing failed entirely (e.g. no regex matches due to unexpected formatting)
    if not chunks or len(chunks) <= 1:
        print("Warning: Article parsing returned very few chunks. Falling back to paragraph chunking...")
        chunks = []
        paragraphs = md_text.split('\n\n')
        current_chunk = []
        current_len = 0
        chunk_idx = 1
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            current_chunk.append(para)
            current_len += len(para)
            if current_len >= 1000:
                text = "\n\n".join(current_chunk)
                chunks.append({
                    "text": text,
                    "metadata": {
                        "chapter": "N/A",
                        "section": "N/A",
                        "article": f"Phần {chunk_idx}",
                        "article_number": chunk_idx,
                        "length": len(text)
                    }
                })
                current_chunk = []
                current_len = 0
                chunk_idx += 1
                
        if current_chunk:
            text = "\n\n".join(current_chunk)
            chunks.append({
                "text": text,
                "metadata": {
                    "chapter": "N/A",
                    "section": "N/A",
                    "article": f"Phần {chunk_idx}",
                    "article_number": chunk_idx,
                    "length": len(text)
                }
            })

    print(f"Created {len(chunks)} chunks.")
    return chunks


def load_into_qdrant(chunks: list[dict], collection_name: str = "luat_hinh_su"):
    """Connects to Qdrant and uploads the chunks using NVIDIA Embeddings for dense vectors
    and FastEmbed for sparse BM25 vectors.
    """
    print(f"Connecting to Qdrant Vector DB at {QRANT_URL}...")
    
    # Initialize client with a larger timeout of 90 seconds to handle slow network uploads
    client = QdrantClient(url=QRANT_URL, api_key=QRANT_API, timeout=90)
    
    nvidia_api_key = os.getenv("NVIDIA_API") or os.getenv("NVIDIA_API_KEY") or ""
    os.environ["NVIDIA_API_KEY"] = nvidia_api_key
    
    # Initialize NVIDIA Embeddings
    print("Initializing NVIDIA Embeddings (nvidia/nv-embedcode-7b-v1)...")
    nvidia_embeddings = NVIDIAEmbeddings(
        model="nvidia/nv-embedcode-7b-v1",
        api_key=nvidia_api_key,
        truncate="NONE"
    )
    
    # Initialize FastEmbed Sparse BM25
    print("Initializing FastEmbed SparseTextEmbedding (Qdrant/bm25)...")
    sparse_embedding_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    
    # Prepare documents
    documents = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    
    # Check if we have cached dense embeddings to skip calling NVIDIA API again
    import pickle
    cache_file = DATA_DIR / "dense_embeddings_cache.pkl"
    dense_vectors = []
    
    if cache_file.exists():
        print(f"Loading dense embeddings from local cache: '{cache_file}'...")
        try:
            with open(cache_file, "rb") as f:
                dense_vectors = pickle.load(f)
            # Ensure size matches chunks
            if len(dense_vectors) != len(chunks):
                print(f"Cache size mismatch: got {len(dense_vectors)}, expected {len(chunks)}. Re-generating...")
                dense_vectors = []
        except Exception as e:
            print(f"Failed to load cache: {e}. Re-generating...")
            dense_vectors = []
            
    if not dense_vectors:
        print(f"Generating dense embeddings for {len(chunks)} chunks using NVIDIA API...")
        nvidia_batch_size = 10
        for i in range(0, len(documents), nvidia_batch_size):
            # Truncate each document to 4000 characters to keep it well below the 4096 token limit (especially for Vietnamese text)
            batch_docs = [doc[:4000] for doc in documents[i : i + nvidia_batch_size]]
            try:
                batch_vectors = nvidia_embeddings.embed_documents(batch_docs)
                dense_vectors.extend(batch_vectors)
                print(f"Embedded batch {i // nvidia_batch_size + 1}/{((len(documents) - 1) // nvidia_batch_size) + 1}...", flush=True)
            except Exception as e:
                print(f"Error embedding batch starting at index {i}: {e}", flush=True)
                print("Retrying with batch size 1 for this batch...", flush=True)
                for doc_idx, doc in enumerate(batch_docs):
                    try:
                        vec = nvidia_embeddings.embed_query(doc[:4000])
                        dense_vectors.append(vec)
                    except Exception as inner_e:
                        print(f"Failed to embed document {i + doc_idx}: {inner_e}", flush=True)
                        dense_vectors.append([0.0] * 4096)
                    time.sleep(0.5)  # Short sleep between retry queries
            time.sleep(1.0)  # Rate limit sleep between batch requests
        
        # Save to local cache
        print(f"Saving dense embeddings to cache: '{cache_file}'...")
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(dense_vectors, f)
        except Exception as e:
            print(f"Failed to save embeddings cache: {e}")
            
    dense_dim = len(dense_vectors[0])
    print(f"Dense vector dimension: {dense_dim}")
    
    # Generate sparse embeddings (using FastEmbed BM25)
    print(f"Generating sparse BM25 embeddings for {len(chunks)} chunks locally...")
    sparse_vectors = list(sparse_embedding_model.embed(documents))
    
    # Re-create/create the collection
    print(f"Re-creating Qdrant collection: '{collection_name}' with Hybrid config...")
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
        
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "dense": models.VectorParams(
                size=dense_dim,
                distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={
            "sparse-bm25": models.SparseVectorParams()
        }
    )
    
    # Upload chunks in batches using client.upsert()
    print(f"Uploading {len(chunks)} points to Qdrant...")
    points = []
    for i, (doc, dense_vec, sparse_vec, meta) in enumerate(zip(documents, dense_vectors, sparse_vectors, metadatas)):
        # Convert fastembed sparse output to qdrant models.SparseVector
        sparse_val = models.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist()
        )
        
        payload = {
            "document": doc,
            **meta
        }
        
        point_id = str(uuid.uuid4())
        
        points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vec,
                    "sparse-bm25": sparse_val
                },
                payload=payload
            )
        )
        
    # Upsert in batches of 32
    batch_size = 32
    for i in range(0, len(points), batch_size):
        batch_points = points[i : i + batch_size]
        client.upsert(
            collection_name=collection_name,
            points=batch_points
        )
        print(f"Uploaded batch {i // batch_size + 1}/{((len(points) - 1) // batch_size) + 1} ({len(batch_points)} items)...", flush=True)
        
    print(f"Ingestion completed successfully! Loaded collection: '{collection_name}' with Hybrid format.")
    return client


def verify_ingestion(client: QdrantClient, collection_name: str = "luat_hinh_su"):
    """Performs a test dense query using NVIDIA Embeddings to verify Qdrant retrieval."""
    print("\n--- Verifying Ingestion with NVIDIA Embeddings ---")
    test_query = "Tội phạm về rửa tiền hoặc tài trợ khủng bố hình phạt như thế nào?"
    print(f"Search Query: '{test_query}'")
    
    nvidia_api_key = os.getenv("NVIDIA_API") or os.getenv("NVIDIA_API_KEY") or ""
    nvidia_embeddings = NVIDIAEmbeddings(
        model="nvidia/nv-embedcode-7b-v1",
        api_key=nvidia_api_key,
        truncate="NONE"
    )
    
    query_vector = nvidia_embeddings.embed_query(test_query)
    
    search_results = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        using="dense",
        limit=3
    )
    
    for rank, hit in enumerate(search_results.points, 1):
        print(f"\n[Match #{rank}] Score: {hit.score:.4f}")
        print(f"Chapter: {hit.payload.get('chapter', 'N/A')}")
        print(f"Section: {hit.payload.get('section', 'N/A')}")
        print(f"Article: {hit.payload.get('article', 'N/A')}")
        print("-" * 50)
        
        doc_text = hit.payload.get('document', '')
        text_preview = doc_text.split('\n')
        preview_limit = 5
        for line in text_preview[:preview_limit]:
            if line.strip():
                print(f"  {line}")
        if len(text_preview) > preview_limit:
            print("  ...")


def main():
    # Force UTF-8 encoding for stdout on Windows
    if sys.platform.startswith('win'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    # 1. Convert PDF to Markdown
    if not MD_PATH.exists():
        md_text = convert_pdf_to_md(PDF_PATH, MD_PATH)
    else:
        print(f"Markdown file already exists at {MD_PATH}. Reading existing content.")
        with open(MD_PATH, "r", encoding="utf-8") as f:
            md_text = f.read()

    # Normalize unicode to NFC (extremely important for Vietnamese text compatibility)
    import unicodedata
    md_text = unicodedata.normalize("NFC", md_text)

    # 2. Chunk by Articles
    chunks = chunk_markdown_by_articles(md_text)

    # 3. Load into Qdrant
    client = load_into_qdrant(chunks)

    # 4. Verify search
    verify_ingestion(client)


if __name__ == "__main__":
    main()
