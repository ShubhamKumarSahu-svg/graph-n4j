"""
pipeline.py -- Iterative dual-agent pipeline with token efficiency optimizations.

Per Section 3.2 of the paper, plus B1-B7 token efficiency improvements:
  B1. Repo skeleton injection (--include-skeleton)
  B2. Query/translation caching (--enable-cache)
  B3. Context pruning — seen code replaced with reference tags (--compact-context)
  B4. Result truncation to top-K rows (--truncate-results)
  B5. Cheaper model for Translation Agent (GROQ_MODEL_TRANSLATION)
  B6. Early-stopping on empty/duplicate results (--early-stop)
  B7. All caches keyed by (repo_id, commit_sha)
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient
from graph_n4j.agents.primary_agent import PrimaryAgent
from graph_n4j.agents.translation_agent import TranslationAgent
from graph_n4j.cache import (
    SkeletonCache, QueryCache, ContextTracker,
    truncate_results, should_early_stop,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result from a complete pipeline run."""
    answer: str
    rounds_used: int
    total_queries: int
    neo4j_roundtrips: int = 0              # B2: actual DB hits (excl. cache hits)
    context_history: list[dict] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    cache_stats: dict = field(default_factory=dict)   # B2: hit/miss rates
    errors: list[str] = field(default_factory=list)
    early_stopped: bool = False             # B6: whether early-stop fired
    early_stop_reason: str = ""


class CodexGraphPipeline:
    """
    Orchestrates the iterative dual-agent loop with token efficiency optimizations.

    All B-flags default ON except B5 (cheaper translation model), which is opt-in.
    """

    def __init__(
        self,
        groq_client: GroqClient,
        graph_db: GraphDB,
        max_rounds: int = 5,
        query_mode: str = "single_query",
        task_instruction: str = "",
        no_translation_agent: bool = False,
        no_edges: bool = False,
        # ── B-flag controls ──
        repo_id: str = "",
        commit_sha: str = "",
        include_skeleton: bool = True,      # B1
        enable_cache: bool = True,          # B2
        compact_context: bool = True,       # B3
        truncate_max_rows: int = 15,        # B4 (0 = disabled)
        translation_model: Optional[str] = None,  # B5
        early_stop: bool = True,            # B6
        # Shared cache objects (reuse across pipeline calls in a session)
        skeleton_cache: Optional[SkeletonCache] = None,
        query_cache: Optional[QueryCache] = None,
    ):
        self.client = groq_client
        self.db = graph_db
        self.max_rounds = max_rounds
        self.query_mode = query_mode
        self.no_translation_agent = no_translation_agent
        self.no_edges = no_edges

        # B-flag settings
        self.repo_id = repo_id
        self.commit_sha = commit_sha
        self.include_skeleton = include_skeleton
        self.enable_cache = enable_cache
        self.compact_context = compact_context
        self.truncate_max_rows = truncate_max_rows
        self.translation_model = translation_model or os.getenv("GROQ_MODEL_TRANSLATION")
        self.early_stop = early_stop

        # Cache objects — shared across calls for session-level reuse (B7)
        self.skeleton_cache = skeleton_cache or SkeletonCache()
        self.query_cache = query_cache or QueryCache(enabled=enable_cache)

        # Build task instruction with ablation modifications
        full_instruction = task_instruction
        if no_translation_agent:
            full_instruction += (
                "\n\nIMPORTANT: You must write Cypher queries directly instead of "
                "natural language queries. Output valid Cypher in the 'queries' array."
            )
        if no_edges:
            full_instruction += (
                "\n\nIMPORTANT: You may ONLY query node attributes (properties). "
                "Do NOT traverse any edges/relationships. Only use MATCH on single "
                "node labels with property filters."
            )

        # B1: Build/load skeleton and inject into system prompt
        skeleton_text = ""
        if include_skeleton:
            skeleton = self.skeleton_cache.get(repo_id, commit_sha)
            if not skeleton:
                try:
                    skeleton = self.skeleton_cache.build_from_db(graph_db, repo_id, commit_sha)
                except Exception as e:
                    logger.warning("Failed to build skeleton: %s", e)
            if skeleton:
                skeleton_text = (
                    "\n\n## Repository Structure (skeleton)\n"
                    "Use this overview to plan targeted queries instead of exploring blindly.\n\n"
                    + skeleton.to_prompt_text()
                )
                logger.info("B1: Skeleton injected (%d chars)", len(skeleton_text))

        self.primary_agent = PrimaryAgent(
            groq_client=groq_client,
            query_mode=query_mode,
            task_instruction=full_instruction + skeleton_text,
        )

        self.translation_agent = TranslationAgent(
            groq_client=groq_client,
            model_override=self.translation_model,  # B5
        )

    def run(self, question: str) -> PipelineResult:
        """Execute the full iterative pipeline for a user question."""
        initial_tokens = self.client.usage.total_tokens
        context_history: list[dict] = []
        total_queries = 0
        neo4j_roundtrips = 0
        errors: list[str] = []
        previous_results: list[str] = []

        # B3: Context tracker for this session
        ctx_tracker = ContextTracker(enabled=self.compact_context)

        logger.info("Pipeline started -- question: '%s'", question[:100])

        for round_num in range(1, self.max_rounds + 1):
            logger.info("--- Round %d/%d ---", round_num, self.max_rounds)

            # -- Step 1: Primary Agent generates analysis + queries --
            try:
                primary_response = self.primary_agent.run(question, context_history)
            except Exception as e:
                error_msg = f"Round {round_num}: Primary Agent error -- {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                break

            # Check if sufficient context
            if primary_response.get("sufficient_context", False):
                answer = primary_response.get("final_answer", primary_response.get("analysis", ""))
                logger.info("Primary Agent signals sufficient context at round %d.", round_num)
                return PipelineResult(
                    answer=answer,
                    rounds_used=round_num,
                    total_queries=total_queries,
                    neo4j_roundtrips=neo4j_roundtrips,
                    context_history=context_history,
                    token_usage=self._get_token_delta(initial_tokens),
                    cache_stats=self.query_cache.stats() if self.enable_cache else {},
                    errors=errors,
                )

            queries = primary_response.get("queries", [])
            if not queries:
                logger.warning("No queries generated in round %d. Ending pipeline.", round_num)
                break

            # -- Step 2: Translate + Execute each query --
            round_results: list[str] = []
            for nl_query in queries:
                total_queries += 1

                # Get Cypher (from cache or Translation Agent)
                try:
                    if self.no_translation_agent:
                        cypher = nl_query
                    else:
                        # B2: Check translation cache first
                        cached_cypher = self.query_cache.get_translation(nl_query)
                        if cached_cypher:
                            cypher = cached_cypher
                            logger.info("B2: Translation cache hit for '%s'", nl_query[:50])
                        else:
                            cypher = self.translation_agent.translate(nl_query)
                            self.query_cache.put_translation_with_nl(nl_query, cypher)
                except Exception as e:
                    error_msg = f"Translation error for '{nl_query[:50]}': {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    round_results.append(f"(Translation error: {e})")
                    continue

                # Execute against Neo4j (with B2 result cache)
                try:
                    # B2: Check result cache
                    cached_result = self.query_cache.get_cypher_result(
                        cypher, self.repo_id, self.commit_sha
                    )
                    if cached_result is not None:
                        records = cached_result
                        logger.info("B2: Result cache hit (%d records)", len(records))
                    else:
                        records = self.db.run_query(cypher, parameters={"repo_id": self.repo_id})
                        neo4j_roundtrips += 1
                        # Cache the result
                        try:
                            self.query_cache.put_cypher_result(
                                cypher, self.repo_id, self.commit_sha, records
                            )
                        except Exception:
                            pass  # Don't fail on cache write errors

                    # B4: Truncate large result sets
                    if self.truncate_max_rows > 0:
                        records, truncation_note = truncate_results(
                            records, max_rows=self.truncate_max_rows
                        )
                    else:
                        truncation_note = None

                    formatted = self.db.format_results(records)

                    # B3: Compact already-seen code
                    if self.compact_context:
                        formatted = ctx_tracker.compact_results(formatted, round_num)
                        for rec in records:
                            ctx_tracker.mark_seen(rec, round_num)

                    if truncation_note:
                        formatted += f"\n\n{truncation_note}"

                    round_results.append(formatted)
                    logger.info("Query returned %d records.", len(records))

                except Exception as e:
                    error_msg = f"Neo4j query error -- Cypher: '{cypher[:80]}' -- {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    round_results.append(f"(Query execution error: {e})")

            # B6: Early-stopping heuristic
            if self.early_stop:
                stop, reason = should_early_stop(round_results, previous_results)
                if stop:
                    logger.info("B6: Early stop triggered -- %s", reason)
                    # Store context and break to final synthesis
                    context_history.append({
                        "round": round_num,
                        "queries": queries,
                        "results": round_results,
                    })
                    return PipelineResult(
                        answer=self._synthesize_final(question, context_history),
                        rounds_used=round_num,
                        total_queries=total_queries,
                        neo4j_roundtrips=neo4j_roundtrips,
                        context_history=context_history,
                        token_usage=self._get_token_delta(initial_tokens),
                        cache_stats=self.query_cache.stats() if self.enable_cache else {},
                        errors=errors,
                        early_stopped=True,
                        early_stop_reason=reason,
                    )

            previous_results = round_results

            # -- Step 3: Store round context --
            context_history.append({
                "round": round_num,
                "queries": queries,
                "results": round_results,
            })

        # -- Fallback: max rounds reached --
        logger.info("Max rounds reached. Requesting final synthesis.")
        answer = self._synthesize_final(question, context_history)

        return PipelineResult(
            answer=answer,
            rounds_used=self.max_rounds,
            total_queries=total_queries,
            neo4j_roundtrips=neo4j_roundtrips,
            context_history=context_history,
            token_usage=self._get_token_delta(initial_tokens),
            cache_stats=self.query_cache.stats() if self.enable_cache else {},
            errors=errors,
        )

    def _synthesize_final(self, question: str, context_history: list[dict]) -> str:
        """Ask the LLM for a final answer given all gathered context."""
        try:
            final_messages = [{
                "role": "system",
                "content": (
                    "You have reached the maximum number of retrieval rounds. "
                    "Based on all the context gathered so far, provide your best "
                    "answer to the user's question. Respond with valid JSON: "
                    '{"analysis": "...", "final_answer": "..."}'
                ),
            }, {
                "role": "user",
                "content": f"Question: {question}\n\nContext gathered:\n" +
                    "\n".join(
                        f"Round {e['round']}: {e['results']}"
                        for e in context_history
                    ),
            }]
            final = self.client.chat_json(final_messages, temperature=0.3)
            return final.get("final_answer", final.get("analysis", "Unable to determine answer."))
        except Exception as e:
            logger.error("Final synthesis failed: %s", e)
            return "Unable to synthesize a final answer. See context history for partial results."

    def _get_token_delta(self, initial_total: int) -> dict:
        """Calculate tokens used in this pipeline run."""
        delta = self.client.usage.total_tokens - initial_total
        return {
            "pipeline_total_tokens": delta,
            "cumulative": self.client.usage.to_dict(),
        }
