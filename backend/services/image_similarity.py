"""Image similarity detection using dHash, HSV histogram, and face clustering."""

import os
import numpy as np
from PIL import Image

from backend.services.face_cluster import detect_faces as _detect_faces
from backend.services.face_cluster import init_face_model as _init_face_model

FACE_SIM_THRESHOLD = 0.45  # cosine similarity for same-person matching


# ── dHash ──────────────────────────────────────────────────────────────

def compute_dhash(image: Image.Image, hash_size: int = 8) -> int:
    """Compute 64-bit difference hash.

    Resizes to (hash_size+1) × hash_size grayscale, then encodes whether
    each pixel is brighter than its right neighbour into a single bit.
    """
    img = image.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = np.array(img, dtype=np.int16)
    diff = pixels[:, 1:] > pixels[:, :-1]
    bits = diff.flatten()
    h = 0
    for i, b in enumerate(bits):
        if b:
            h |= 1 << i
    return h


def hamming_distance(h1: int, h2: int) -> int:
    return (h1 ^ h2).bit_count()


# ── HSV histogram ──────────────────────────────────────────────────────

def compute_hsv_histogram(image: Image.Image, bins: int = 32) -> np.ndarray:
    """Compute normalised 3-channel HSV histogram."""
    hsv = image.convert("HSV")
    arr = np.array(hsv)

    # Downsample large images for speed
    h, w = arr.shape[:2]
    if h * w > 20000:
        scale = (20000 / (h * w)) ** 0.5
        new_size = (int(w * scale), int(h * scale))
        arr = np.array(image.convert("HSV").resize(new_size, Image.LANCZOS))

    hist_h = np.histogram(arr[..., 0], bins=bins, range=(0, 255))[0]
    hist_s = np.histogram(arr[..., 1], bins=bins, range=(0, 255))[0]
    hist_v = np.histogram(arr[..., 2], bins=bins, range=(0, 255))[0]

    hist = np.concatenate([hist_h, hist_s, hist_v]).astype(np.float64)
    hist /= hist.sum() + 1e-8
    return hist


def histogram_correlation(h1: np.ndarray, h2: np.ndarray) -> float:
    """Correlation coefficient between two normalised histograms.

    Returns a value in [-1, 1]; higher means more similar.
    """
    return float(np.corrcoef(h1, h2)[0, 1])


# ── Union-Find ─────────────────────────────────────────────────────────

class _UnionFind:
    __slots__ = ("parent", "rank")

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            self.parent[px] = py
        elif self.rank[px] > self.rank[py]:
            self.parent[py] = px
        else:
            self.parent[py] = px
            self.rank[px] += 1


# ── Main grouping ──────────────────────────────────────────────────────

def _safe_load(path: str):
    """Try to open an image, returning None on failure."""
    try:
        return Image.open(path)
    except Exception:
        return None


def find_similar_groups(
    image_paths: list[str],
    dhash_threshold: int = 10,
    hist_threshold: float = 0.85,
    progress_callback=None,
) -> list[list[str]]:
    """Group visually-similar images.

    Returns a list of groups, each group being a list of file paths.
    Groups are sorted by size (largest first).  Singleton groups
    (images with no similar peer) are omitted.

    *dhash_threshold* — max Hamming distance on the 64-bit dHash.
    *hist_threshold*  — min correlation for the HSV histogram.

    *progress_callback* is called as ``callback(phase, done, total)``
    where *phase* is ``"features"`` or ``"compare"``.
    """
    n = len(image_paths)
    if n < 2:
        return []

    # ── Phase 1: compute features ──────────────────────────────────
    dhashes: list[int | None] = [None] * n
    histograms: list[np.ndarray | None] = [None] * n
    face_embs: list[list[np.ndarray]] = [[] for _ in range(n)]

    face_model = _init_face_model()
    if face_model in (None, False):
        face_model = None

    for i, p in enumerate(image_paths):
        img = _safe_load(p)
        if img is None:
            if progress_callback:
                progress_callback("features", i + 1, n)
            continue
        try:
            dhashes[i] = compute_dhash(img)
            histograms[i] = compute_hsv_histogram(img)
        except Exception:
            pass
        # Face embeddings (separate pass, can fail independently)
        if face_model is not None:
            try:
                for f in _detect_faces(p, model=face_model):
                    emb = f.get("embedding")
                    if emb is not None:
                        face_embs[i].append(np.asarray(emb, dtype=np.float64))
            except Exception:
                pass
        if progress_callback:
            progress_callback("features", i + 1, n)

    # ── Phase 2: pairwise comparison ───────────────────────────────
    uf = _UnionFind(n)
    total_pairs = n * (n - 1) // 2
    done_pairs = 0

    LOW_DETAIL = 10  # max bits for a near-uniform image
    for i in range(n):
        if dhashes[i] is None:
            continue
        dh_i = dhashes[i]
        for j in range(i + 1, n):
            if dhashes[j] is None:
                continue
            dh_j = dhashes[j]
            # Skip dHash for low-detail images — few bits make
            # Hamming distance unreliable
            either_low = (
                dh_i.bit_count() <= LOW_DETAIL
                or dh_j.bit_count() <= LOW_DETAIL
            )
            if (
                not either_low
                and hamming_distance(dh_i, dh_j) <= dhash_threshold
            ):
                uf.union(i, j)
            elif histograms[i] is not None and histograms[j] is not None:
                corr = histogram_correlation(histograms[i], histograms[j])
                if corr >= hist_threshold:
                    uf.union(i, j)
            # Face match: any face in i matches any face in j
            if face_embs[i] and face_embs[j] and uf.find(i) != uf.find(j):
                ei_list = face_embs[i]
                ej_list = face_embs[j]
                matched = False
                for ei in ei_list:
                    if matched:
                        break
                    for ej in ej_list:
                        sim = float(np.dot(ei, ej) / (
                            np.linalg.norm(ei) * np.linalg.norm(ej) + 1e-8
                        ))
                        if sim >= FACE_SIM_THRESHOLD:
                            uf.union(i, j)
                            matched = True
                            break
            done_pairs += 1
        if progress_callback:
            progress_callback("compare", done_pairs, total_pairs)

    # ── Phase 3: collect groups ────────────────────────────────────
    groups: dict[int, list[str]] = {}
    for i, p in enumerate(image_paths):
        root = uf.find(i)
        groups.setdefault(root, []).append(p)

    # Keep groups of size ≥ 2, sort largest first
    result = [g for g in groups.values() if len(g) >= 2]
    result.sort(key=len, reverse=True)

    if progress_callback:
        progress_callback("compare", total_pairs, total_pairs)

    return result


def find_similar_groups_safe(
    image_paths: list[str],
    dhash_threshold: int = 10,
    hist_threshold: float = 0.85,
    progress_callback=None,
) -> list[list[str]]:
    """Thin wrapper that never raises — returns [] on any error."""
    try:
        return find_similar_groups(
            image_paths,
            dhash_threshold=dhash_threshold,
            hist_threshold=hist_threshold,
            progress_callback=progress_callback,
        )
    except Exception:
        return []
