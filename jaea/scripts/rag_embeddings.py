from __future__ import annotations

import hashlib
import math
import re
import struct


EMBEDDING_DIM = 128
MAX_CHUNK_CHARS = 700
CHUNK_OVERLAP_CHARS = 120
MAX_FEATURES = 512


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[。．.!?！？])\s*|\n+", normalized)
    return [part.strip() for part in parts if part.strip()]


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap_chars: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(sentence), max_chars - overlap_chars):
                chunks.append(sentence[start : start + max_chars])
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = current[-overlap_chars:].strip()
        current = f"{current} {sentence}".strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


def text_features(text: str) -> list[str]:
    normalized = normalize_text(text).lower()
    if not normalized:
        return []

    features: list[str] = []
    features.extend(re.findall(r"[a-z0-9][a-z0-9+\-_.]{1,}", normalized))
    compact = re.sub(r"\s+", "", normalized)
    for width in (2, 3):
        if len(compact) >= width:
            features.extend(compact[idx : idx + width] for idx in range(len(compact) - width + 1))
    return features[:MAX_FEATURES]


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vector = [0.0] * dim
    for feature in text_features(text):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, byteorder="big", signed=False)
        index = value % dim
        sign = 1.0 if (value >> 8) & 1 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def pack_embedding(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def unpack_embedding(value: bytes | bytearray | memoryview) -> list[float]:
    data = bytes(value)
    if not data:
        return []
    return list(struct.unpack(f"{len(data) // 4}f", data))
