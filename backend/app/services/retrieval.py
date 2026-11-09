"""Local semantic + lexical retrieval with persistent, page-aware policy chunks."""
from __future__ import annotations
import re
import threading
import numpy as np
from sqlalchemy import select, delete
from app.db.models import PolicyChunk, PolicyDocument


class PolicyRetriever:
    def __init__(self, model_name, cache_dir):
        self.model_name, self.cache_dir = model_name, cache_dir
        self._model = None
        self._lock = threading.RLock()

    def embed(self, texts, query=False):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir), threads=2)
            values = list(self._model.query_embed(texts) if query else self._model.passage_embed(texts))
        return np.asarray(values, dtype=np.float32)

    @staticmethod
    def split(text):
        # Form-feed preserves PDF page boundaries; text inputs have no asserted page number.
        pages = text.split('\f')
        chunks = []
        for page, content in enumerate(pages, 1):
            words = content.split()
            for start in range(0, len(words), 140):
                piece = ' '.join(words[start:start + 180])
                if piece:
                    chunks.append((page if len(pages) > 1 else None, piece))
                if start + 180 >= len(words):
                    break
        return chunks

    def index(self, db, document):
        pieces = self.split(document.text_content)
        if not pieces:
            raise ValueError('Document has no extractable text.')
        vectors = self.embed([document.title + '\n' + text for _, text in pieces])
        db.execute(delete(PolicyChunk).where(PolicyChunk.document_id == document.id))
        for i, ((page, text), vector) in enumerate(zip(pieces, vectors)):
            db.add(PolicyChunk(document_id=document.id, position=i, page=page, content=text,
                               embedding=vector.tolist(), embedding_model=self.model_name))
        db.flush()
        return len(pieces)

    def ensure_index(self, db):
        for doc in db.scalars(select(PolicyDocument)).all():
            chunk = db.scalar(select(PolicyChunk).where(PolicyChunk.document_id == doc.id))
            if chunk is None or chunk.embedding_model != self.model_name:
                self.index(db, doc)

    def search(self, db, query, limit=4):
        self.ensure_index(db)
        rows = db.execute(select(PolicyChunk, PolicyDocument).join(PolicyDocument)).all()
        if not rows:
            return []
        q = self.embed([query], query=True)[0]
        vectors = np.asarray([chunk.embedding for chunk, _ in rows], dtype=np.float32)
        similarity = vectors @ q / np.maximum(np.linalg.norm(vectors, axis=1) * np.linalg.norm(q), 1e-9)
        terms = set(re.findall(r'[a-z0-9]{3,}', query.lower()))
        ranked = []
        for i, (chunk, document) in enumerate(rows):
            tokens = set(re.findall(r'[a-z0-9]{3,}', (document.title + ' ' + chunk.content).lower()))
            lexical = len(terms & tokens) / max(len(terms), 1)
            if similarity[i] < .35 and lexical == 0:
                continue
            ranked.append((.8 * float(similarity[i]) + .2 * lexical, chunk, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [{'id': f'P{c.document_id}-{c.position}', 'document_id': d.id, 'title': d.title,
                 'page': c.page, 'source': d.source, 'excerpt': c.content, 'score': round(score, 3),
                 'updated_at': d.updated_at.isoformat(), 'kind': 'policy'}
                for score, c, d in ranked[:limit]]
