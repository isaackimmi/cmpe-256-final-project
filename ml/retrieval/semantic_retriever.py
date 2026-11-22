"""Person 2 Track: Stage 1 Semantic Retrieval (Sentence-Transformers + FAISS + Multi-Interest).

North Star Metric: Recall@100 (measured via `python -m ml.evaluate`).

Contract — this script should output a Parquet file with:
    trip_id, user_id, fold, dest_region_id, poi_id,
    stage1_score, stage1_rank,
    sem_sim_mean,   # Cosine sim vs. user's mean home/history embedding
    sem_sim_max,    # Multi-interest max sim (best matching past POI -> snow matches snow, beach matches beach!)
    sem_sim_top3    # Mean of top-3 matching past POIs

Requires optional neural dependencies:
    uv pip install --python .venv/bin/python -r ml/requirements-neural.txt

Usage:
    .venv/bin/python -m ml.retrieval.semantic_retriever --val-fold 0 --top-k 100
"""

from __future__ import annotations

import argparse
import time
import numpy as np
import pandas as pd

from ml.config import DATA_GOLD_DIR, DEFAULT_TOP_K, PREDS_DIR


def build_poi_text(df: pd.DataFrame) -> list[str]:
    """Compose a concise semantic description for each POI."""
    texts = []
    for name, schema, gcats in zip(df["name"], df["venue_schema"], df["google_categories"]):
        clean_schema = str(schema).replace("schema:", "")
        if isinstance(gcats, (list, np.ndarray)) and len(gcats) > 0:
            cat_str = ", ".join(str(x) for x in gcats[:4])
        else:
            cat_str = clean_schema
        texts.append(f"{name} | {clean_schema} | {cat_str}")
    return texts


def encode_pois(
    model_name: str = "BAAI/bge-small-en-v1.5",
    batch_size: int = 256,
    chunk_size: int = 100_000,
    use_fp16: bool = True,
    max_new_chunks: int | None = None,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Encode all POIs (or load cached `poi_embeddings.npy`) with resumable chunk checkpointing."""
    emb_path = DATA_GOLD_DIR / "poi_embeddings.npy"
    idx_path = DATA_GOLD_DIR / "poi_embedding_ids.parquet"
    pois_df = pd.read_parquet(
        DATA_GOLD_DIR / "pois_clean.parquet",
        columns=["poi_id", "region_id", "name", "venue_schema", "google_categories", "is_recommendable"],
    )

    if emb_path.exists() and idx_path.exists():
        print(f"Loaded cached embeddings from {emb_path}")
        return pois_df, np.load(emb_path)

    import shutil
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model_kwargs = {"dtype": torch.float16} if (use_fp16 and device in ("cuda", "mps")) else {}
    dtype_label = "fp16" if model_kwargs else "fp32"

    chunk_dir = DATA_GOLD_DIR / "_poi_emb_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    n_total = len(pois_df)
    n_chunks = (n_total + chunk_size - 1) // chunk_size

    pending = [i for i in range(n_chunks) if not (chunk_dir / f"chunk_{i:03d}.npy").exists()]
    if pending:
        print(
            f"[Person 2] Encoding {n_total:,} POIs in {n_chunks} chunks ({len(pending)} remaining) "
            f"with `{model_name}` on `{device}` ({dtype_label}, bs={batch_size})..."
        )
        model = SentenceTransformer(model_name, device=device, model_kwargs=model_kwargs)
        model.max_seq_length = 64

        encoded_now = 0
        for cid in pending:
            if max_new_chunks is not None and encoded_now >= max_new_chunks:
                print(f"[Person 2] Reached max_new_chunks={max_new_chunks}; checkpoint saved for resume.")
                return pois_df, np.empty((0, 0), dtype=np.float32)

            start = cid * chunk_size
            end = min(start + chunk_size, n_total)
            texts = build_poi_text(pois_df.iloc[start:end])
            t0 = time.perf_counter()
            chunk_embs = model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=True,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).astype(np.float32)
            if device == "mps":
                torch.mps.synchronize()
            elif device == "cuda":
                torch.cuda.synchronize()
            dt = time.perf_counter() - t0
            out_chunk = chunk_dir / f"chunk_{cid:03d}.npy"
            tmp_chunk = chunk_dir / f"chunk_{cid:03d}.tmp.npy"
            np.save(tmp_chunk, chunk_embs)
            tmp_chunk.rename(out_chunk)
            encoded_now += 1
            print(
                f"  [Chunk {cid + 1}/{n_chunks}] {end - start:,} POIs in {dt:.1f}s "
                f"({(end - start) / dt:.0f} POIs/sec) -> saved {out_chunk.name}"
            )

    # Assemble all chunks once every chunk exists
    missing = [i for i in range(n_chunks) if not (chunk_dir / f"chunk_{i:03d}.npy").exists()]
    if missing:
        print(f"[Person 2] {len(missing)} chunk(s) still remaining; re-run to finish assembly.")
        return pois_df, np.empty((0, 0), dtype=np.float32)

    print(f"[Person 2] Assembling {n_chunks} chunks into {emb_path}...")
    embs = np.concatenate([np.load(chunk_dir / f"chunk_{i:03d}.npy") for i in range(n_chunks)], axis=0).astype(np.float32)
    np.save(emb_path, embs)
    pois_df[["poi_id"]].to_parquet(idx_path, index=False)
    shutil.rmtree(chunk_dir, ignore_errors=True)
    print(f"[Person 2] Saved {emb_path} {embs.shape} and cleaned up temporary chunks.")
    return pois_df, embs


def run_semantic_retrieval(val_fold: int = 0, top_k: int = DEFAULT_TOP_K, max_trips: int | None = None) -> None:
    """Retrieve Top-K POIs per destination city using FAISS + Multi-Interest max/top-3 similarity."""
    import faiss

    pois_df, embs = encode_pois()
    poi_to_idx = {pid: i for i, pid in enumerate(pois_df["poi_id"].tolist())}

    # Build one lightweight FAISS inner-product index per destination city (recommendable POIs only)
    rec_mask = pois_df["is_recommendable"].to_numpy()
    city_indices: dict[str, tuple[faiss.IndexFlatIP, list[str], np.ndarray]] = {}
    for region_id, grp in pois_df[rec_mask].groupby("region_id"):
        idxs = grp.index.to_numpy()
        mat = np.ascontiguousarray(embs[idxs], dtype=np.float32)
        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)
        city_indices[region_id] = (index, grp["poi_id"].tolist(), mat)

    trips_df = pd.read_parquet(DATA_GOLD_DIR / "trips_multicity.parquet")
    trips_df = trips_df[trips_df["fold"] == val_fold]
    if max_trips is not None:
        trips_df = trips_df.head(max_trips)

    rows = []
    t0 = time.perf_counter()
    for row in trips_df.itertuples(index=False):
        city_pack = city_indices.get(row.dest_region_id)
        if city_pack is None:
            continue
        index, city_pids, city_mat = city_pack

        hist_idxs = [poi_to_idx[p] for p in row.history_pois if p in poi_to_idx]
        if not hist_idxs:
            continue
        hist_mat = embs[hist_idxs]  # (H, D)

        # Mean-pooled query vector for fast FAISS Top-K retrieval
        query = hist_mat.mean(axis=0, keepdims=True)
        norm = np.linalg.norm(query, axis=1, keepdims=True) + 1e-12
        query = (query / norm).astype(np.float32)

        k = min(top_k, len(city_pids))
        mean_sims, cand_local_idxs = index.search(query, k)
        cand_local_idxs = cand_local_idxs[0]
        mean_sims = mean_sims[0]

        # Multi-Interest Scoring: compare each candidate against EVERY past POI individually!
        # High max_sim means a beach in Madrid matches past beach trips, museum matches past museums.
        cand_mat = city_mat[cand_local_idxs]             # (K, D)
        pairwise = cand_mat @ hist_mat.T                 # (K, H)
        max_sims = pairwise.max(axis=1)
        top3_k = min(3, pairwise.shape[1])
        top3_sims = np.partition(pairwise, -top3_k, axis=1)[:, -top3_k:].mean(axis=1)

        # Blend mean + multi-interest top3 as Stage 1 score (Person 2 can tune or swap in Two-Tower!)
        stage1_scores = 0.5 * mean_sims + 0.5 * top3_sims
        order = np.argsort(-stage1_scores)

        for rank_i, pos in enumerate(order, start=1):
            rows.append((
                row.trip_id,
                row.dest_region_id,
                city_pids[cand_local_idxs[pos]],
                float(stage1_scores[pos]),
                rank_i,
                float(mean_sims[pos]),
                float(max_sims[pos]),
                float(top3_sims[pos]),
            ))

    out_df = pd.DataFrame(
        rows,
        columns=[
            "trip_id", "dest_region_id", "poi_id", "score", "stage1_rank",
            "sem_sim_mean", "sem_sim_max", "sem_sim_top3",
        ],
    )
    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    preds_out = PREDS_DIR / f"semantic_faiss_fold{val_fold}.parquet"
    out_df.to_parquet(preds_out, index=False)
    print(f"[Person 2] Retrieved {len(out_df):,} candidates in {time.perf_counter()-t0:.1f}s -> {preds_out}")
    print(
        f"Next: .venv/bin/python -m ml.evaluate --preds {preds_out} "
        f"--name semantic_faiss_v1 --author person2 --fold {val_fold}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Person 2 Semantic FAISS + Multi-Interest Retriever.")
    parser.add_argument("--val-fold", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--max-trips", type=int, default=None, help="Optional cap for fast iteration")
    args = parser.parse_args()
    run_semantic_retrieval(val_fold=args.val_fold, top_k=args.top_k, max_trips=args.max_trips)


if __name__ == "__main__":
    main()
