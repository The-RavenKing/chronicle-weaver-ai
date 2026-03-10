"""GraphRAG-lite retrieval — entity-aware graph traversal over the lore knowledge graph.

Design
------
1. Use hybrid retrieval to find seed entities matching the query in the lorebook.
2. Walk ``Lorebook.relations`` up to `max_hops` hops from seed entity IDs.
3. Collect all entity dicts + facts that touch the expanded entity set.
4. Return ranked ``GraphRetrievedItem`` objects (seeds ranked first, then neighbours).

No external dependencies — pure Python, works with the existing ``Lorebook`` model.

Usage
-----
from chronicle_weaver_ai.retrieval.graph_retrieval import GraphRetriever, build_lore_docs
from chronicle_weaver_ai.lore.models import Lorebook

retriever = GraphRetriever(lorebook)
results = retriever.retrieve("Goblin King", k=5, max_hops=2)
"""

from __future__ import annotations

from dataclasses import dataclass

from chronicle_weaver_ai.lore.models import Lorebook
from chronicle_weaver_ai.retrieval.hybrid import HybridDoc, retrieve_hybrid


@dataclass(frozen=True)
class GraphRetrievedItem:
    """A lore entity or fact returned by graph retrieval."""

    item_id: str
    item_type: str  # "entity" | "fact"
    text: str
    score: float
    hop: int  # 0 = seed match, 1+ = graph neighbour


class GraphRetriever:
    """Retrieves lore context using hybrid entity matching + relation graph traversal.

    Parameters
    ----------
    lorebook   — the campaign lorebook with entities, facts, relations.
    """

    def __init__(self, lorebook: Lorebook) -> None:
        self._lorebook = lorebook
        # Build adjacency index: entity_id → set of related entity_ids
        self._adj: dict[str, set[str]] = {}
        for rel in lorebook.relations:
            subj = str(rel.get("subject_entity_id", ""))
            obj = str(rel.get("object_entity_id", ""))
            if subj and obj:
                self._adj.setdefault(subj, set()).add(obj)
                self._adj.setdefault(obj, set()).add(subj)

    def retrieve(
        self,
        query: str,
        k: int = 5,
        max_hops: int = 2,
        seed_k: int = 3,
    ) -> list[GraphRetrievedItem]:
        """Retrieve the top-k most relevant lore items for *query*.

        Parameters
        ----------
        query     — free-text query.
        k         — total items to return.
        max_hops  — how many hops to traverse from seed entities.
        seed_k    — how many seed entities to start graph traversal from.
        """
        if not self._lorebook.entities:
            return []

        # Step 1: build HybridDocs from entities
        entity_docs = _entities_to_docs(self._lorebook.entities)
        seed_results = retrieve_hybrid(query, entity_docs, k=seed_k)
        seed_entity_ids: set[str] = {r.doc_id for r in seed_results}
        seed_scores: dict[str, float] = {r.doc_id: r.score for r in seed_results}

        # Step 2: BFS from seeds up to max_hops
        expanded: dict[str, int] = {}  # entity_id → hop distance
        frontier = set(seed_entity_ids)
        for hop in range(max_hops + 1):
            for eid in frontier:
                if eid not in expanded:
                    expanded[eid] = hop
            if hop < max_hops:
                next_frontier: set[str] = set()
                for eid in frontier:
                    neighbours = self._adj.get(eid, set())
                    for n in neighbours:
                        if n not in expanded:
                            next_frontier.add(n)
                frontier = next_frontier

        # Step 3: build result items from expanded entity set
        entity_map: dict[str, dict] = {
            str(e.get("entity_id", "")): e for e in self._lorebook.entities
        }
        items: list[GraphRetrievedItem] = []
        for eid, hop in expanded.items():
            entity = entity_map.get(eid)
            if entity is None:
                continue
            base_score = seed_scores.get(eid, 0.0)
            # Decay score by hop distance so seeds rank first
            score = base_score if hop == 0 else base_score * (0.5**hop) + 0.01
            name = str(entity.get("name", eid))
            kind = str(entity.get("kind", "entity"))
            description = str(entity.get("description", ""))
            text = f"[{kind}] {name}: {description}".strip()
            items.append(
                GraphRetrievedItem(
                    item_id=eid,
                    item_type="entity",
                    text=text,
                    score=score,
                    hop=hop,
                )
            )

        # Step 4: include facts that mention any expanded entity
        for i, fact in enumerate(self._lorebook.facts):
            fact_text = str(fact.get("content", fact.get("text", "")))
            related_entities = str(fact.get("entity_ids", fact.get("entity_id", "")))
            fact_entity_ids = {
                e.strip() for e in related_entities.split(",") if e.strip()
            }
            overlap = fact_entity_ids & set(expanded.keys())
            if overlap or not fact_entity_ids:
                min_hop = min(
                    (expanded.get(eid, 99) for eid in overlap), default=max_hops
                )
                score = 0.3 * (0.5**min_hop)
                items.append(
                    GraphRetrievedItem(
                        item_id=f"fact:{i}",
                        item_type="fact",
                        text=fact_text,
                        score=score,
                        hop=min_hop,
                    )
                )

        # Step 5: rank and trim
        items.sort(key=lambda x: (-x.score, x.hop, x.item_id))
        return items[:k]


def build_lore_docs(lorebook: Lorebook) -> list[HybridDoc]:
    """Convert lorebook entities to HybridDocs for standalone hybrid retrieval."""
    return _entities_to_docs(lorebook.entities)


def _entities_to_docs(entities: list[dict]) -> list[HybridDoc]:
    docs: list[HybridDoc] = []
    for entity in entities:
        eid = str(entity.get("entity_id", ""))
        name = str(entity.get("name", eid))
        kind = str(entity.get("kind", "entity"))
        description = str(entity.get("description", ""))
        aliases = entity.get("aliases", [])
        alias_str = " ".join(str(a) for a in aliases) if aliases else ""
        text = f"{name} {kind} {description} {alias_str}".strip()
        if eid and text:
            docs.append(HybridDoc(doc_id=eid, source="lorebook", text=text))
    return docs


__all__ = [
    "GraphRetriever",
    "GraphRetrievedItem",
    "build_lore_docs",
]
