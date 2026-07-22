import re
from typing import List

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ModuleNotFoundError:
    TfidfVectorizer = None
    cosine_similarity = None


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> List[str]:
    """
    Splits text into chunks of `chunk_size` words with an overlap of `overlap` words.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    chunks = []

    if len(words) <= chunk_size:
        return [text]

    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - overlap

    return chunks


def retrieve_relevant_chunks(query: str, text: str, top_k: int = 3) -> List[str]:
    """
    Retrieves the top_k most semantically relevant chunks for a given query using TF-IDF.
    """
    if not text or not text.strip() or not query or not query.strip():
        return []

    chunks = chunk_text(text, chunk_size=300, overlap=50)
    if not chunks:
        return []

    if len(chunks) <= top_k:
        return chunks

    if TfidfVectorizer is None or cosine_similarity is None:
        query_terms = {term.lower() for term in re.findall(r"(?u)\b\w+\b", query)}
        scored_chunks = []
        for idx, chunk in enumerate(chunks):
            chunk_terms = {term.lower() for term in re.findall(r"(?u)\b\w+\b", chunk)}
            scored_chunks.append((len(query_terms & chunk_terms), idx, chunk))
        scored_chunks.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        relevant = [chunk for score, _, chunk in scored_chunks[:top_k] if score > 0]
        return relevant or chunks[:top_k]

    # Fit TF-IDF on chunks + query
    vectorizer = TfidfVectorizer(stop_words=None, token_pattern=r"(?u)\b\w+\b")
    # Prepend query to documents to vectorize them together
    documents = [query] + chunks

    try:
        tfidf_matrix = vectorizer.fit_transform(documents)
    except Exception:
        # Fallback if empty vocabulary or errors
        return chunks[:top_k]

    # Calculate cosine similarity between query (index 0) and all chunks (index 1 onwards)
    cosine_similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

    # Get top_k indices
    top_indices = cosine_similarities.argsort()[-top_k:][::-1]

    # Filter out chunks with 0 similarity if needed, but we can just return the top_k
    return [chunks[i] for i in top_indices if cosine_similarities[i] > 0]
