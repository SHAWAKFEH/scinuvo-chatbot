"""
Session 4 — Ingesting the real Scinuvo data into a vector database.

WHAT CHANGES FROM THE TOY VERSION
1. Multilingual embeddings: we use 'paraphrase-multilingual-MiniLM-L12-v2'
   instead of the English-only model, so Arabic questions work.
2. A real vector database (ChromaDB) instead of a NumPy array: it stores the
   vectors on DISK, so we embed once and reuse them, and it does fast search.

We store BOTH the English and Arabic text of each product as separate entries,
so a question in either language finds the right product. Each entry keeps its
product title, price, and a source so answers can cite where they came from.

Setup:
    pip install chromadb sentence-transformers

Run:
    python ingest.py
This creates a folder called 'scinuvo_db' holding the vector database.
"""

import json
import chromadb
from sentence_transformers import SentenceTransformer

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def load_kb(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def main():
    print("Loading multilingual embedding model (first run downloads it)...")
    model = SentenceTransformer(MODEL_NAME)

    print("Loading Scinuvo knowledge base...")
    items = load_kb("scinuvo_knowledge.jsonl")

    # Build one searchable entry per language per product. Each entry is a
    # "document" (the text we embed and search) plus "metadata" (extra facts
    # we want to keep alongside it, like price and source).
    # We embed three text variants per product where available:
    #   text_en        -> formal English
    #   text_ar        -> formal Arabic
    #   text_ar_casual -> everyday Jordanian dialect (how customers really type)
    # Each becomes its own searchable entry, all pointing at the same product.
    variants = ("en", "ar", "ar_casual")
    documents, metadatas, ids = [], [], []
    for item in items:
        for variant in variants:
            text = item.get(f"text_{variant}")
            if not text:
                continue
            # 'lang' groups casual + formal Arabic together as "ar" for the answer.
            lang = "ar" if variant.startswith("ar") else "en"
            documents.append(text)
            metadatas.append({
                "title": item["title"],
                "lang": lang,
                "variant": variant,
                "price_jod": item["price_jod"] if item["price_jod"] is not None else "",
                "concern": item["concern"],
                "source": "scinuvo.com",
            })
            ids.append(f"{item['id']}_{variant}")

    print(f"Prepared {len(documents)} entries "
          f"({len(items)} products x up to 3 text variants).")

    # Embed everything.
    print("Embedding...")
    vectors = model.encode(documents, normalize_embeddings=True).tolist()

    # Create (or reset) the Chroma database on disk.
    print("Writing to the vector database (folder: scinuvo_db)...")
    client = chromadb.PersistentClient(path="scinuvo_db")

    # If we've run before, delete the old collection so we start clean.
    try:
        client.delete_collection("scinuvo")
    except Exception:
        pass

    collection = client.create_collection("scinuvo")
    collection.add(
        documents=documents,
        embeddings=vectors,
        metadatas=metadatas,
        ids=ids,
    )

    print(f"Done. Stored {collection.count()} entries in scinuvo_db.")
    print("Session 5 will read from this database to answer questions.")


if __name__ == "__main__":
    main()
