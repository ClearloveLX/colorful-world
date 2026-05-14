"""Face detection and clustering using insightface."""

import numpy as np
from PIL import Image

_face_model = None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def init_face_model():
    """Lazy-load the insightface FaceAnalysis model.  Returns it, or None
    if the library / model is unavailable."""
    global _face_model
    if _face_model is not None:
        return _face_model
    try:
        import insightface
        model = insightface.app.FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        model.prepare(ctx_id=0, det_size=(640, 640))
        _face_model = model
        return model
    except Exception:
        _face_model = False  # sentinel – don't retry
        return None


def _load_image(path: str) -> np.ndarray | None:
    try:
        img = Image.open(path).convert("RGB")
        return np.array(img)
    except Exception:
        return None


def detect_faces(image_path: str, model=None):
    """Return a list of face dicts with keys *bbox* and *embedding*.

    Returns an empty list when no faces are found or the model is unavailable.
    """
    if model is None:
        model = init_face_model()
    if model is None or model is False:
        return []
    arr = _load_image(image_path)
    if arr is None:
        return []
    try:
        faces = model.get(arr)
    except Exception:
        return []
    result = []
    for f in faces:
        emb = getattr(f, "embedding", None)
        if emb is not None:
            emb = np.asarray(emb, dtype=np.float64)
        result.append({"bbox": f.bbox, "embedding": emb})
    return result


def cluster_faces(
    image_paths: list[str],
    sim_threshold: float = 0.45,
    progress_callback=None,
) -> list[list[str]]:
    """Group images by face identity.

    Returns groups (list of path-lists) for clusters with ≥ 2 members.
    Groups are sorted largest-first.

    *sim_threshold* — minimum cosine similarity to consider two faces
    the same person.
    """
    model = init_face_model()
    if model is None or model is False:
        return []

    n = len(image_paths)

    # ── Extract all face embeddings ────────────────────────────────
    # For each image store the list of embeddings (one per detected face)
    all_embs: list[list[np.ndarray]] = [[] for _ in range(n)]
    has_faces = [False] * n

    for i, p in enumerate(image_paths):
        faces = detect_faces(p, model=model)
        for f in faces:
            emb = f["embedding"]
            if emb is not None:
                all_embs[i].append(emb)
                has_faces[i] = True
        if progress_callback:
            progress_callback(i + 1)

    # ── Pairwise comparison + Union-Find ───────────────────────────
    parent = list(range(n))
    rank = [0] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px == py:
            return
        if rank[px] < rank[py]:
            parent[px] = py
        elif rank[px] > rank[py]:
            parent[py] = px
        else:
            parent[py] = px
            rank[px] += 1

    for i in range(n):
        if not has_faces[i]:
            continue
        for j in range(i + 1, n):
            if not has_faces[j]:
                continue
            # Check if ANY face in image i matches ANY face in image j
            matched = False
            for ei in all_embs[i]:
                if matched:
                    break
                for ej in all_embs[j]:
                    if _cosine_similarity(ei, ej) >= sim_threshold:
                        union(i, j)
                        matched = True
                        break

    # ── Collect groups (size ≥ 2 only) ─────────────────────────────
    groups: dict[int, list[str]] = {}
    for i, p in enumerate(image_paths):
        if not has_faces[i]:
            continue
        root = find(i)
        groups.setdefault(root, []).append(p)

    result = [g for g in groups.values() if len(g) >= 2]
    result.sort(key=len, reverse=True)
    return result


def face_available() -> bool:
    """Check whether face recognition can be used."""
    return init_face_model() not in (None, False)
