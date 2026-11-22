"""Person 2 Step 5: Stage 1 Hybrid Retriever (Two-Tower + Popularity + Multi-Interest Semantic).

Fuses three complementary Stage 1 retrievers per destination city via Reciprocal Rank Fusion (RRF):
  1. LocalityTwoTower (personalized neural MIPS retriever, Top-100)
  2. Training-fold Tourist Popularity (strictly fold != val_fold, Top-100)
  3. Pretrained BGE-small Semantic Similarity (zero-shot text alignment, Top-100)

Outputs:
  1. `data/preds/hybrid_stage1_fold{val_fold}.parquet`
       Validation predictions (trip_id, poi_id, score) for official `ml/evaluate.py` scoring.
  2. `data/gold/candidates_hybrid_top100_fold{val_fold}.parquet`
       All-folds Top-100 candidate table matching Person 3's `ml/ranking/train_ranker.py` contract,
       including all 4 auto-detected Person 2 features:
         - `two_tower_score`
         - `sem_sim_mean`
         - `sem_sim_max`
         - `sem_sim_top3`

Usage:
    .venv/bin/python -m ml.retrieval.hybrid_retriever --val-fold 0 --top-k 100
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import torch

from ml.config import ARTIFACTS_DIR, DATA_GOLD_DIR, DEFAULT_TOP_K, PREDS_DIR
from ml.retrieval.two_tower import (
    LocalityTwoTower,
    RetrievalWorkspace,
    compute_trip_user_features,
    detect_device,
    encode_all_rec_pois_for_faiss,
    encode_trips_for_faiss,
    load_poi_workspace,
)


def compute_city_popularity_order(ws: RetrievalWorkspace, val_fold: int) -> dict[int, np.ndarray]:
    """Compute exact per-city Top-100 local POI indices matching baseline_popularity.py (fold != val_fold)."""
    con = duckdb.connect()
    pois_path = DATA_GOLD_DIR / "pois_clean.parquet"
    targ_path = DATA_GOLD_DIR / "trip_targets_exploded.parquet"

    pop_df = con.sql(
        f"""
        WITH train_pop AS (
            SELECT poi_id, COUNT(*) AS train_tourist_visits
            FROM '{targ_path}'
            WHERE fold != {val_fold}
            GROUP BY poi_id
        ),
        ranked AS (
            SELECT
                p.region_id,
                p.poi_id,
                ROW_NUMBER() OVER (
                    PARTITION BY p.region_id
                    ORDER BY COALESCE(tp.train_tourist_visits, 0) DESC,
                             p.google_num_reviews DESC,
                             p.n_checkins DESC,
                             p.poi_id ASC
                ) AS pop_rank
            FROM '{pois_path}' p
            LEFT JOIN train_pop tp ON p.poi_id = tp.poi_id
            WHERE p.is_recommendable = TRUE
        )
        SELECT region_id, poi_id, pop_rank
        FROM ranked
        WHERE pop_rank <= 100
        ORDER BY region_id, pop_rank
        """
    ).df()

    rec_lookup = pd.Index(ws.rec_poi_ids)
    pop_df["rec_idx"] = rec_lookup.get_indexer(pop_df["poi_id"].to_numpy())
    pop_df = pop_df[pop_df["rec_idx"] >= 0]

    city_pop_local: dict[int, np.ndarray] = {}
    for region_id, grp in pop_df.groupby("region_id", sort=False):
        cid = ws.city_to_id.get(region_id)
        if cid is None:
            continue
        s = int(ws.city_offset[cid])
        m = int(ws.city_len[cid])
        local_idxs = grp["rec_idx"].to_numpy(dtype=np.int64) - s
        valid = (local_idxs >= 0) & (local_idxs < m)
        city_pop_local[cid] = local_idxs[valid]

    return city_pop_local


@torch.no_grad()
def _hybrid_rrf_city_batch(
    q_tt_np: np.ndarray,
    u_all_np: np.ndarray,
    tt_poi_mat_np: np.ndarray,
    sem_poi_mat_np: np.ndarray,
    pop_local_idx: np.ndarray,
    top_k: int,
    w_pop: float,
    w_sem: float,
    k_rrf: float,
    device: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Exact batched 3-way RRF fusion for all trips going to one destination city.

    Returns (cand_local_idx, rrf_scores, tt_scores_cand, sem_mean_cand), each shape (N_q, kk).
    """
    m = tt_poi_mat_np.shape[0]
    n_q = q_tt_np.shape[0]
    kk = min(top_k, m)
    k_src = min(100, m)

    tt_mat_t = torch.from_numpy(tt_poi_mat_np).to(device)
    sem_mat_t = torch.from_numpy(sem_poi_mat_np).to(device)

    ranks_src = torch.arange(1, k_src + 1, dtype=torch.float32, device=device)
    w_tt_vec = 1.0 / (k_rrf + ranks_src)
    w_sem_vec = w_sem / (k_rrf + ranks_src)

    pop_k = min(len(pop_local_idx), m)
    pop_idx_t = torch.from_numpy(pop_local_idx[:pop_k].astype(np.int64)).to(device)
    w_pop_vec = w_pop / (k_rrf + torch.arange(1, pop_k + 1, dtype=torch.float32, device=device))

    q_batch = 64 if m > 10_000 else (256 if m > 2_500 else 512)

    out_idx = np.empty((n_q, kk), dtype=np.int32)
    out_rrf = np.empty((n_q, kk), dtype=np.float32)
    out_tt = np.empty((n_q, kk), dtype=np.float32)
    out_sem = np.empty((n_q, kk), dtype=np.float32)

    for s in range(0, n_q, q_batch):
        e = min(s + q_batch, n_q)
        b = e - s
        q_t = torch.from_numpy(q_tt_np[s:e]).to(device)
        u_t = torch.from_numpy(u_all_np[s:e].astype(np.float32)).to(device)

        tt_all = q_t @ tt_mat_t.T  # (b, M)
        sem_all = u_t @ sem_mat_t.T  # (b, M)

        _, tt_top_i = torch.topk(tt_all, k=k_src, dim=1, largest=True, sorted=True)
        _, sem_top_i = torch.topk(sem_all, k=k_src, dim=1, largest=True, sorted=True)

        rrf = torch.zeros((b, m), dtype=torch.float32, device=device)
        rrf.scatter_add_(1, tt_top_i, w_tt_vec.unsqueeze(0).expand(b, -1))
        if pop_k > 0:
            rrf[:, pop_idx_t] += w_pop_vec.unsqueeze(0)
        if w_sem > 0.0:
            rrf.scatter_add_(1, sem_top_i, w_sem_vec.unsqueeze(0).expand(b, -1))

        # Tiny deterministic tie-breaker preserving Two-Tower ordering
        rrf = rrf + 1e-7 * torch.sigmoid(tt_all)

        top_vals, top_local = torch.topk(rrf, k=kk, dim=1, largest=True, sorted=True)
        cand_tt = tt_all.gather(1, top_local)
        cand_sem = sem_all.gather(1, top_local)

        out_idx[s:e] = top_local.cpu().numpy().astype(np.int32)
        out_rrf[s:e] = top_vals.cpu().numpy()
        out_tt[s:e] = cand_tt.cpu().numpy()
        out_sem[s:e] = cand_sem.cpu().numpy()

    return out_idx, out_rrf, out_tt, out_sem


def compute_multi_interest_for_city(
    cand_local_idx: np.ndarray,
    sem_poi_mat: np.ndarray,
    history_lists: list,
    all_poi_embs: np.ndarray,
    poi_to_all_idx: dict[str, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Compute exact multi-interest `sem_sim_max` and `sem_sim_top3` for each trip's Top-K candidates."""
    n_q, kk = cand_local_idx.shape
    max_out = np.zeros((n_q, kk), dtype=np.float32)
    top3_out = np.zeros((n_q, kk), dtype=np.float32)

    for i in range(n_q):
        hist_pois = history_lists[i]
        h_idx = [poi_to_all_idx[p] for p in hist_pois if p in poi_to_all_idx]
        if not h_idx:
            continue
        hist_mat = all_poi_embs[h_idx]  # (H, 384)
        cand_mat = sem_poi_mat[cand_local_idx[i]]  # (kk, 384)
        pairwise = cand_mat @ hist_mat.T  # (kk, H)
        max_out[i] = pairwise.max(axis=1)
        h_len = pairwise.shape[1]
        if h_len <= 3:
            top3_out[i] = pairwise.mean(axis=1)
        else:
            top3_out[i] = np.partition(pairwise, -3, axis=1)[:, -3:].mean(axis=1)

    return max_out, top3_out


def run_hybrid_retrieval(
    val_fold: int = 0,
    top_k: int = DEFAULT_TOP_K,
    w_pop: float = 0.40,
    w_sem: float = 0.05,
    k_rrf: float = 40.0,
    val_only: bool = False,
) -> None:
    t_total = time.perf_counter()
    device = detect_device()
    ckpt_path = ARTIFACTS_DIR / f"two_tower_fold{val_fold}.pt"
    if not ckpt_path.exists():
        raise FileNotFoundError(
            f"Missing {ckpt_path}. Run `.venv/bin/python -m ml.retrieval.two_tower --val-fold {val_fold}` first."
        )

    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    ws = load_poi_workspace(
        val_fold=val_fold,
        schema_vocab=ckpt["schema_vocab"],
        num_mean=ckpt["num_mean"],
        num_std=ckpt["num_std"],
    )

    model = LocalityTwoTower(**ckpt["config"]).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    print(
        f"[Hybrid Stage 1] Loaded {ckpt_path.name} (epoch={ckpt['epoch']}, dev_R@100={ckpt['best_dev_recall_100']:.5f}) "
        f"on `{device}` | RRF(w_pop={w_pop}, w_sem={w_sem}, k={k_rrf})"
    )

    # Precompute all recommendable POI vectors once (535K x 129 and 535K x 384)
    tt_poi_vecs = encode_all_rec_pois_for_faiss(model, ws, device)
    rec_sem_embs = ws.all_poi_embs[ws.rec_all_idx]
    city_pop_local = compute_city_popularity_order(ws, val_fold=val_fold)
    poi_to_all_idx = {pid: i for i, pid in enumerate(ws.all_poi_ids.tolist())}

    trips_all = pd.read_parquet(DATA_GOLD_DIR / "trips_multicity.parquet")
    folds_to_run = [val_fold] if val_only else sorted(trips_all["fold"].unique().tolist())

    chunk_dir = DATA_GOLD_DIR / f"_hybrid_chunks_fold{val_fold}"
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    val_preds_out = PREDS_DIR / f"hybrid_stage1_fold{val_fold}.parquet"
    cands_out = DATA_GOLD_DIR / f"candidates_hybrid_top{top_k}_fold{val_fold}.parquet"

    for fold_id in folds_to_run:
        t_f = time.perf_counter()
        trips_f = trips_all[trips_all["fold"] == fold_id].reset_index(drop=True)
        u_all_f, u_trv_f, u_sch_f, cid_f, ctx_f = compute_trip_user_features(trips_f, ws)
        q_tt_f = encode_trips_for_faiss(model, ws, u_all_f, u_trv_f, u_sch_f, cid_f, ctx_f, device)

        trip_ids_arr = trips_f["trip_id"].to_numpy(dtype=np.int64)
        user_ids_arr = trips_f["user_id"].to_numpy(dtype=np.int64)
        fold_arr = trips_f["fold"].to_numpy(dtype=np.int64)
        dest_reg_arr = trips_f["dest_region_id"].to_numpy()
        dest_mon_arr = trips_f["dest_month"].to_numpy(dtype=np.int32)
        nh_city_arr = trips_f["n_history_cities"].to_numpy(dtype=np.int64)
        nh_poi_arr = trips_f["n_history_pois"].to_numpy(dtype=np.int64)
        hist_pois_col = trips_f["history_pois"].tolist()

        out_cols: dict[str, list[np.ndarray]] = {
            "trip_id": [],
            "user_id": [],
            "fold": [],
            "dest_region_id": [],
            "dest_month": [],
            "n_history_cities": [],
            "n_history_pois": [],
            "poi_id": [],
            "stage1_score": [],
            "stage1_rank": [],
            "sem_sim_mean": [],
            "sem_sim_max": [],
            "sem_sim_top3": [],
            "two_tower_score": [],
        }

        df_q = pd.DataFrame({"pos": np.arange(len(trips_f)), "cid": cid_f})
        for cid, grp in df_q.groupby("cid", sort=False):
            cid_int = int(cid)
            if cid_int < 0:
                continue
            s = int(ws.city_offset[cid_int])
            m = int(ws.city_len[cid_int])
            pos_arr = grp["pos"].to_numpy()

            tt_city_mat = np.ascontiguousarray(tt_poi_vecs[s : s + m], dtype=np.float32)
            sem_city_mat = np.ascontiguousarray(rec_sem_embs[s : s + m], dtype=np.float32)
            pop_local = city_pop_local.get(cid_int, np.empty(0, dtype=np.int64))

            cand_local, rrf_s, tt_s, sem_mean_s = _hybrid_rrf_city_batch(
                q_tt_np=q_tt_f[pos_arr],
                u_all_np=u_all_f[pos_arr],
                tt_poi_mat_np=tt_city_mat,
                sem_poi_mat_np=sem_city_mat,
                pop_local_idx=pop_local,
                top_k=top_k,
                w_pop=w_pop,
                w_sem=w_sem,
                k_rrf=k_rrf,
                device=device,
            )

            city_hist_lists = [hist_pois_col[p] for p in pos_arr]
            sem_max_s, sem_top3_s = compute_multi_interest_for_city(
                cand_local_idx=cand_local,
                sem_poi_mat=sem_city_mat,
                history_lists=city_hist_lists,
                all_poi_embs=ws.all_poi_embs,
                poi_to_all_idx=poi_to_all_idx,
            )

            kk = cand_local.shape[1]
            global_rec_idx = (cand_local + s).ravel()
            ranks = np.tile(np.arange(1, kk + 1, dtype=np.int64), len(pos_arr))

            out_cols["trip_id"].append(np.repeat(trip_ids_arr[pos_arr], kk))
            out_cols["user_id"].append(np.repeat(user_ids_arr[pos_arr], kk))
            out_cols["fold"].append(np.repeat(fold_arr[pos_arr], kk))
            out_cols["dest_region_id"].append(np.repeat(dest_reg_arr[pos_arr], kk))
            out_cols["dest_month"].append(np.repeat(dest_mon_arr[pos_arr], kk))
            out_cols["n_history_cities"].append(np.repeat(nh_city_arr[pos_arr], kk))
            out_cols["n_history_pois"].append(np.repeat(nh_poi_arr[pos_arr], kk))
            out_cols["poi_id"].append(ws.rec_poi_ids[global_rec_idx])
            out_cols["stage1_score"].append(rrf_s.ravel().astype(np.float64))
            out_cols["stage1_rank"].append(ranks)
            out_cols["sem_sim_mean"].append(sem_mean_s.ravel().astype(np.float32))
            out_cols["sem_sim_max"].append(sem_max_s.ravel().astype(np.float32))
            out_cols["sem_sim_top3"].append(sem_top3_s.ravel().astype(np.float32))
            out_cols["two_tower_score"].append(tt_s.ravel().astype(np.float32))

        fold_df = pd.DataFrame({k: np.concatenate(v) for k, v in out_cols.items()})
        chunk_path = chunk_dir / f"fold_{fold_id}.parquet"
        fold_df.to_parquet(chunk_path, index=False, compression="zstd")

        if fold_id == val_fold:
            val_preds = fold_df[["trip_id", "poi_id", "stage1_score"]].rename(columns={"stage1_score": "score"})
            val_preds.to_parquet(val_preds_out, index=False, compression="zstd")
            print(f"  [Fold {fold_id}] Saved validation predictions -> {val_preds_out}")

        print(f"  [Fold {fold_id}] Generated {len(fold_df):,} hybrid candidates in {time.perf_counter() - t_f:.1f}s")
        del fold_df, out_cols

    if not val_only:
        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT * FROM '{chunk_dir}/*.parquet'
            ) TO '{cands_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
            """
        )
        shutil.rmtree(chunk_dir, ignore_errors=True)
        print(f"[Hybrid Stage 1] Exported full all-folds handoff table -> {cands_out} (total {time.perf_counter() - t_total:.1f}s)")
    else:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        print(f"[Hybrid Stage 1] Validation-only run finished in {time.perf_counter() - t_total:.1f}s")

    print(
        f"Next: .venv/bin/python -m ml.evaluate --preds {val_preds_out} "
        f"--name hybrid_stage1_v1 --author person2 --fold {val_fold}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Person 2 Hybrid Stage 1 Retriever (Two-Tower + Popularity + Semantic).")
    parser.add_argument("--val-fold", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--w-pop", type=float, default=0.40)
    parser.add_argument("--w-sem", type=float, default=0.05)
    parser.add_argument("--k-rrf", type=float, default=40.0)
    parser.add_argument("--val-only", action="store_true")
    args = parser.parse_args()
    run_hybrid_retrieval(
        val_fold=args.val_fold,
        top_k=args.top_k,
        w_pop=args.w_pop,
        w_sem=args.w_sem,
        k_rrf=args.k_rrf,
        val_only=args.val_only,
    )


if __name__ == "__main__":
    main()
