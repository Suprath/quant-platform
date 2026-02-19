"""
KnowledgeArchive — Information-Only Inheritance from Extinct Agents

Theory Reference (Section 7.2):
    K = ∪_{extinct i} LifeData(A_i)

When an agent dies:
    - Capital → 0  (DESTROYED — not redistributed)
    - Parameters → Archive  (PRESERVED)
    - Failure patterns → Categorized for guided mutation

Key Innovation: "Learning from the dead" — mutation noise is sampled from
archive distribution D(K) so new agents avoid strategies that led to extinction.
"""

import os
import json
import sqlite3
import time
import torch
import numpy as np
from typing import Optional
from config import setup_logger, ARCHIVE_DB_PATH, BRAIN_DIM

logger = setup_logger("esti.core.knowledge_archive")


class KnowledgeArchive:
    """
    Preserves behavioural information from extinct agents.

    Storage: SQLite database for persistence across container restarts.
    Each entry stores the agent's final parameters, lifetime metrics,
    and categorised failure pattern.
    """

    FAILURE_CATEGORIES = [
        "capital_collapse",    # Blew up on large losses
        "stagnation_death",    # Health decayed from no growth
        "score_extinction",    # Composite Σ ≤ 0
        "drawdown_halt",       # Circuit breaker triggered
    ]

    def __init__(self, db_path: str = ARCHIVE_DB_PATH, brain_dim: int = BRAIN_DIM):
        self.db_path = db_path
        self.brain_dim = brain_dim

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self._init_db()
        count = self.count()
        logger.info(f"📚 KnowledgeArchive opened | db={db_path} | existing_entries={count}")

    # ──────────────────────────────────────────
    #  Database setup
    # ──────────────────────────────────────────

    def _init_db(self):
        """Create the archive table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extinct_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                archived_at REAL NOT NULL,
                lifetime_steps INTEGER,
                final_capital REAL,
                peak_capital REAL,
                final_sharpe REAL,
                failure_category TEXT,
                final_params BLOB,
                embedding BLOB,
                metrics_json TEXT
            )
        """)
        conn.commit()
        conn.close()
        logger.debug("Archive DB schema verified")

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ──────────────────────────────────────────
    #  Archive operations
    # ──────────────────────────────────────────

    def archive_agent(
        self,
        agent_id: int,
        flat_params: torch.Tensor,
        embedding: torch.Tensor,
        lifetime_steps: int,
        final_capital: float,
        peak_capital: float,
        final_sharpe: float,
        failure_category: str,
        extra_metrics: Optional[dict] = None,
    ):
        """
        Preserve an extinct agent's knowledge in the archive.

        Capital is DESTROYED (per ESTI theory), but parameters and
        behavioural information are PRESERVED for future mutation guidance.
        """
        if failure_category not in self.FAILURE_CATEGORIES:
            logger.warning(
                f"⚠️  Unknown failure category '{failure_category}' for agent {agent_id}, "
                f"defaulting to 'score_extinction'"
            )
            failure_category = "score_extinction"

        params_blob = flat_params.numpy().tobytes()
        embed_blob = embedding.numpy().tobytes()
        metrics = json.dumps(extra_metrics or {})

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO extinct_agents
                (agent_id, archived_at, lifetime_steps, final_capital, peak_capital,
                 final_sharpe, failure_category, final_params, embedding, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                time.time(),
                lifetime_steps,
                final_capital,
                peak_capital,
                final_sharpe,
                failure_category,
                params_blob,
                embed_blob,
                metrics,
            ),
        )
        conn.commit()
        conn.close()

        logger.info(
            f"💀 Agent-{agent_id:03d} archived | category={failure_category} "
            f"| lifetime={lifetime_steps} steps | capital=₹{final_capital:,.0f} "
            f"| peak=₹{peak_capital:,.0f} | sharpe={final_sharpe:.3f}"
        )

    # ──────────────────────────────────────────
    #  Knowledge retrieval
    # ──────────────────────────────────────────

    def get_dead_embeddings(self, max_entries: int = 200) -> list[torch.Tensor]:
        """
        Retrieve embeddings from the most recent extinct agents.
        Used by SharedBrain.update_from_population().
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT embedding FROM extinct_agents ORDER BY archived_at DESC LIMIT ?",
            (max_entries,),
        ).fetchall()
        conn.close()

        embeddings = []
        for (blob,) in rows:
            arr = np.frombuffer(blob, dtype=np.float32)
            if len(arr) == self.brain_dim:
                embeddings.append(torch.from_numpy(arr.copy()))
            else:
                logger.warning(
                    f"⚠️  Stale embedding dim mismatch: expected {self.brain_dim}, got {len(arr)} — skipping"
                )

        logger.debug(f"Retrieved {len(embeddings)} dead embeddings from archive")
        return embeddings

    def get_failure_distribution(self) -> dict:
        """
        Count failure categories — used for knowledge-guided mutation.
        Agents should mutate AWAY from common failure patterns.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT failure_category, COUNT(*) FROM extinct_agents GROUP BY failure_category"
        ).fetchall()
        conn.close()

        dist = {cat: 0 for cat in self.FAILURE_CATEGORIES}
        for cat, cnt in rows:
            dist[cat] = cnt

        total = sum(dist.values())
        logger.debug(f"Failure distribution (n={total}): {dist}")
        return dist

    def sample_mutation_guidance(self, n_samples: int = 10) -> Optional[torch.Tensor]:
        """
        Sample parameter vectors from failed agents to compute knowledge-guided
        mutation noise: ε ~ D(K).

        Returns:
            Standard deviation across sampled dead agent params (for guided noise),
            or None if archive is empty.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT final_params FROM extinct_agents ORDER BY RANDOM() LIMIT ?",
            (n_samples,),
        ).fetchall()
        conn.close()

        if not rows:
            logger.debug("Archive empty — no mutation guidance available")
            return None

        param_vecs = []
        for (blob,) in rows:
            arr = np.frombuffer(blob, dtype=np.float32)
            param_vecs.append(torch.from_numpy(arr.copy()))

        # Check all same length
        lengths = set(v.shape[0] for v in param_vecs)
        if len(lengths) > 1:
            logger.warning(f"⚠️  Mixed param lengths in archive: {lengths} — using first match only")
            target_len = param_vecs[0].shape[0]
            param_vecs = [v for v in param_vecs if v.shape[0] == target_len]

        if len(param_vecs) < 2:
            return None

        stacked = torch.stack(param_vecs)
        guidance_std = stacked.std(dim=0)

        logger.debug(
            f"🧬 Mutation guidance from {len(param_vecs)} dead agents | "
            f"mean_std={guidance_std.mean():.6f}"
        )
        return guidance_std

    # ──────────────────────────────────────────
    #  Stats
    # ──────────────────────────────────────────

    def count(self) -> int:
        conn = self._get_conn()
        (cnt,) = conn.execute("SELECT COUNT(*) FROM extinct_agents").fetchone()
        conn.close()
        return cnt

    def get_summary(self) -> dict:
        """Get archive statistics for the API."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT
                COUNT(*),
                AVG(lifetime_steps),
                AVG(final_sharpe),
                MIN(final_capital),
                MAX(peak_capital)
            FROM extinct_agents
        """).fetchone()
        conn.close()

        return {
            "total_extinct": row[0],
            "avg_lifetime_steps": round(row[1], 1) if row[1] else 0,
            "avg_final_sharpe": round(row[2], 3) if row[2] else 0,
            "min_final_capital": round(row[3], 2) if row[3] else 0,
            "max_peak_capital": round(row[4], 2) if row[4] else 0,
            "failure_distribution": self.get_failure_distribution(),
        }
