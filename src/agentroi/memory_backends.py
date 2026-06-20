"""
Concrete MemoryBackend implementations.

JSONMemoryBackend    — flat JSON file, exact match, no deps, default
ACEPlaybookBackend   — ACE-style incremental delta bullets, grow-and-refine,
                       trajectory-scoped playbooks, no external deps
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .schemas import (
    AgentRole,
    MemoryEntry,
    MemoryEntryType,
    RetrievalQuery,
    RetrievalStrategy,
    _now_iso,
)

_DEFAULT_BLOCKED: dict[str, list[str]] = {
    AgentRole.LOG_INVESTIGATOR.value: ["file_edit"],
    AgentRole.CODE_INVESTIGATOR.value: ["file_edit"],
    AgentRole.REPRODUCER.value: ["file_edit"],
    AgentRole.PATCH_AGENT.value: ["edit_test_files"],
    AgentRole.VERIFIER.value: ["file_edit"],
}

_DEFAULT_ROUTING = {
    "agent_order": [
        AgentRole.LOG_INVESTIGATOR.value,
        AgentRole.CODE_INVESTIGATOR.value,
        AgentRole.REPRODUCER.value,
        AgentRole.PATCH_AGENT.value,
        AgentRole.VERIFIER.value,
    ],
    "patch_agent_start_condition": "target_repro_confirmed",
    "full_suite_condition": "target_test_passed",
}


# ---------------------------------------------------------------------------
# JSON Memory Backend
# ---------------------------------------------------------------------------

class JSONMemoryBackend:
    """
    Simple flat-JSON backend. Stores all entries in one file.
    Trajectory isolation via trajectory_id field on each entry.
    Exact matching only — no vector ops.

    Good for: development, demos, small runs, no-dep environments.
    """

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, MemoryEntry] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open() as f:
            raw = json.load(f)
        entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
        if isinstance(entries, dict):
            for eid, edata in entries.items():
                if isinstance(edata, dict) and "entry_type" in edata:
                    self._entries[eid] = MemoryEntry.from_dict(edata)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            json.dump(
                {"entries": {eid: e.to_dict() for eid, e in self._entries.items()}},
                f,
                indent=2,
            )

    def store(self, entry: MemoryEntry) -> str:
        self._entries[entry.id] = entry
        self._save()
        return entry.id

    def retrieve(self, query: RetrievalQuery) -> list[MemoryEntry]:
        sig_key = query.signature_key()
        results: list[MemoryEntry] = []

        for entry in self._entries.values():
            if entry.trajectory_id != query.trajectory_id:
                continue
            if sig_key and entry.task_signature_key and entry.task_signature_key != sig_key:
                continue
            if query.entry_types and entry.entry_type not in query.entry_types:
                continue
            if query.agent_role and entry.agent_role and entry.agent_role != query.agent_role:
                continue
            if entry.net_score < query.min_net_score:
                continue
            results.append(entry)

        results.sort(key=lambda e: e.net_score, reverse=True)
        return results[: query.top_k]

    def update(self, entry_id: str, delta: dict[str, Any]) -> MemoryEntry | None:
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        for k, v in delta.items():
            if hasattr(entry, k):
                setattr(entry, k, v)
        entry.updated_at = _now_iso()
        self._save()
        return entry

    def vote(self, entry_id: str, helpful: bool) -> None:
        entry = self._entries.get(entry_id)
        if not entry:
            return
        if helpful:
            entry.vote_helpful()
        else:
            entry.vote_harmful()
        self._save()

    def prune(self, trajectory_id: str | None = None, min_net_score: int = -2) -> int:
        before = len(self._entries)
        to_remove = [
            eid for eid, e in self._entries.items()
            if e.net_score < min_net_score
            and (trajectory_id is None or e.trajectory_id == trajectory_id)
        ]
        for eid in to_remove:
            del self._entries[eid]
        if to_remove:
            self._save()
        return len(to_remove)

    def list_trajectories(self) -> list[str]:
        return list({e.trajectory_id for e in self._entries.values()})

    def snapshot(self, trajectory_id: str) -> list[dict[str, Any]]:
        return [
            e.to_dict() for e in self._entries.values()
            if e.trajectory_id == trajectory_id
        ]


# ---------------------------------------------------------------------------
# ACE Playbook Backend
# ---------------------------------------------------------------------------

class ACEPlaybookBackend:
    """
    ACE-style backend: contexts as structured, itemized playbooks.

    Key properties (from ACE paper):
    - Incremental delta updates — never full rewrites
    - Grow-and-refine — bullets accumulate then deduplicate
    - Per-trajectory playbooks — each trajectory has its own isolated playbook
    - Vote-tracked bullets — helpful/harmful counts guide pruning
    - Global playbook — cross-trajectory learnings optionally shared

    Structure on disk:
    {
      "trajectories": {
        "<trajectory_id>": {
          "description": "...",
          "created_at": "...",
          "playbook": {
            "routing_rules": [ <MemoryEntry dicts> ],
            "prompt_patches": { "<role>": [ <MemoryEntry dicts> ] },
            "waste_patterns": [ <MemoryEntry dicts> ],
            "high_roi_context": [ <MemoryEntry dicts> ],
            "episodic": [ <MemoryEntry dicts> ]
          }
        }
      },
      "global_playbook": {
        "waste_patterns": [ ... ],
        "high_roi_context": [ ... ]
      }
    }
    """

    DEDUP_SIMILARITY_THRESHOLD = 0.85

    def __init__(self, path: Path, share_global: bool = True):
        self.path = path
        self.share_global = share_global
        self._data: dict[str, Any] = {"trajectories": {}, "global_playbook": {}}
        self._index: dict[str, MemoryEntry] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open() as f:
            self._data = json.load(f)
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index = {}
        for traj in self._data.get("trajectories", {}).values():
            pb = traj.get("playbook", {})
            for section in ["routing_rules", "waste_patterns", "high_roi_context", "episodic"]:
                for edict in pb.get(section, []):
                    e = MemoryEntry.from_dict(edict)
                    self._index[e.id] = e
            for role_entries in pb.get("prompt_patches", {}).values():
                for edict in role_entries:
                    e = MemoryEntry.from_dict(edict)
                    self._index[e.id] = e
        for section in ["waste_patterns", "high_roi_context"]:
            for edict in self._data.get("global_playbook", {}).get(section, []):
                e = MemoryEntry.from_dict(edict)
                self._index[e.id] = e

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            json.dump(self._data, f, indent=2)

    def _ensure_trajectory(self, trajectory_id: str, description: str = "") -> dict[str, Any]:
        if trajectory_id not in self._data["trajectories"]:
            self._data["trajectories"][trajectory_id] = {
                "description": description,
                "created_at": _now_iso(),
                "playbook": {
                    "routing_rules": [],
                    "prompt_patches": {},
                    "waste_patterns": [],
                    "high_roi_context": [],
                    "episodic": [],
                },
            }
        return self._data["trajectories"][trajectory_id]

    def _section_for_type(self, entry_type: MemoryEntryType) -> str:
        return {
            MemoryEntryType.ROUTING_RULE: "routing_rules",
            MemoryEntryType.PROMPT_PATCH: "prompt_patches",
            MemoryEntryType.WASTE_PATTERN: "waste_patterns",
            MemoryEntryType.HIGH_ROI_CONTEXT: "high_roi_context",
            MemoryEntryType.EPISODIC_RECORD: "episodic",
        }[entry_type]

    def _simple_similarity(self, a: str, b: str) -> float:
        """Token overlap similarity — no external deps."""
        if not a or not b:
            return 0.0
        tokens_a = set(a.lower().split())
        tokens_b = set(b.lower().split())
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))

    def _is_duplicate(self, entry: MemoryEntry, existing: list[dict[str, Any]]) -> str | None:
        """Return id of duplicate if found, else None."""
        new_text = entry.content if isinstance(entry.content, str) else str(entry.content)
        for edict in existing:
            old_text = edict.get("content", "")
            if isinstance(old_text, dict):
                old_text = str(old_text)
            if self._simple_similarity(new_text, old_text) >= self.DEDUP_SIMILARITY_THRESHOLD:
                return edict["id"]
        return None

    def store(self, entry: MemoryEntry) -> str:
        traj = self._ensure_trajectory(entry.trajectory_id)
        pb = traj["playbook"]
        section = self._section_for_type(entry.entry_type)

        if entry.entry_type == MemoryEntryType.PROMPT_PATCH:
            role = entry.agent_role or "unknown"
            if role not in pb["prompt_patches"]:
                pb["prompt_patches"][role] = []
            bucket = pb["prompt_patches"][role]
            dup_id = self._is_duplicate(entry, bucket)
            if dup_id:
                self.vote(dup_id, helpful=True)
                return dup_id
            bucket.append(entry.to_dict())
        else:
            bucket = pb[section]
            dup_id = self._is_duplicate(entry, bucket)
            if dup_id:
                self.vote(dup_id, helpful=True)
                return dup_id
            bucket.append(entry.to_dict())

            if self.share_global and entry.entry_type in (
                MemoryEntryType.WASTE_PATTERN, MemoryEntryType.HIGH_ROI_CONTEXT
            ):
                global_section = self._data["global_playbook"].setdefault(section, [])
                if not self._is_duplicate(entry, global_section):
                    global_section.append(entry.to_dict())

        self._index[entry.id] = entry
        self._save()
        return entry.id

    def retrieve(self, query: RetrievalQuery) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        traj_data = self._data["trajectories"].get(query.trajectory_id, {})
        pb = traj_data.get("playbook", {})
        sig_key = query.signature_key()

        def _collect(bucket: list[dict[str, Any]]) -> None:
            for edict in bucket:
                e = MemoryEntry.from_dict(edict)
                if sig_key and e.task_signature_key and e.task_signature_key != sig_key:
                    continue
                if query.entry_types and e.entry_type not in query.entry_types:
                    continue
                if e.net_score < query.min_net_score:
                    continue
                results.append(e)

        if not query.entry_types or MemoryEntryType.ROUTING_RULE in query.entry_types:
            _collect(pb.get("routing_rules", []))
        if not query.entry_types or MemoryEntryType.WASTE_PATTERN in query.entry_types:
            _collect(pb.get("waste_patterns", []))
        if not query.entry_types or MemoryEntryType.HIGH_ROI_CONTEXT in query.entry_types:
            _collect(pb.get("high_roi_context", []))
        if not query.entry_types or MemoryEntryType.EPISODIC_RECORD in query.entry_types:
            _collect(pb.get("episodic", []))
        if not query.entry_types or MemoryEntryType.PROMPT_PATCH in query.entry_types:
            patches = pb.get("prompt_patches", {})
            if query.agent_role:
                _collect(patches.get(query.agent_role, []))
            else:
                for role_patches in patches.values():
                    _collect(role_patches)

        if self.share_global and query.strategy != RetrievalStrategy.EXACT:
            global_pb = self._data.get("global_playbook", {})
            for section in ["waste_patterns", "high_roi_context"]:
                _collect(global_pb.get(section, []))

        if query.strategy == RetrievalStrategy.COSINE and query.free_text:
            results.sort(
                key=lambda e: self._simple_similarity(
                    query.free_text,
                    e.content if isinstance(e.content, str) else str(e.content),
                ),
                reverse=True,
            )
        else:
            results.sort(key=lambda e: e.net_score, reverse=True)

        seen: set[str] = set()
        unique: list[MemoryEntry] = []
        for e in results:
            if e.id not in seen:
                seen.add(e.id)
                unique.append(e)

        return unique[: query.top_k]

    def update(self, entry_id: str, delta: dict[str, Any]) -> MemoryEntry | None:
        entry = self._index.get(entry_id)
        if not entry:
            return None
        for k, v in delta.items():
            if hasattr(entry, k):
                setattr(entry, k, v)
        entry.updated_at = _now_iso()
        self._sync_entry_to_data(entry)
        self._save()
        return entry

    def vote(self, entry_id: str, helpful: bool) -> None:
        entry = self._index.get(entry_id)
        if not entry:
            return
        if helpful:
            entry.vote_helpful()
        else:
            entry.vote_harmful()
        self._sync_entry_to_data(entry)
        self._save()

    def _sync_entry_to_data(self, entry: MemoryEntry) -> None:
        """Write updated entry back into the nested data structure."""
        traj = self._data["trajectories"].get(entry.trajectory_id, {})
        pb = traj.get("playbook", {})
        section = self._section_for_type(entry.entry_type)

        if entry.entry_type == MemoryEntryType.PROMPT_PATCH:
            bucket = pb.get("prompt_patches", {}).get(entry.agent_role, [])
        else:
            bucket = pb.get(section, [])

        for i, edict in enumerate(bucket):
            if edict.get("id") == entry.id:
                bucket[i] = entry.to_dict()
                return

    def prune(self, trajectory_id: str | None = None, min_net_score: int = -2) -> int:
        pruned = 0
        trajs = (
            {trajectory_id: self._data["trajectories"].get(trajectory_id, {})}
            if trajectory_id
            else self._data["trajectories"]
        )
        for tid, traj in trajs.items():
            pb = traj.get("playbook", {})
            for section in ["routing_rules", "waste_patterns", "high_roi_context", "episodic"]:
                before = pb.get(section, [])
                after = [e for e in before if e.get("helpful_count", 0) - e.get("harmful_count", 0) >= min_net_score]
                pruned += len(before) - len(after)
                pb[section] = after
            for role, role_entries in pb.get("prompt_patches", {}).items():
                after = [e for e in role_entries if e.get("helpful_count", 0) - e.get("harmful_count", 0) >= min_net_score]
                pruned += len(role_entries) - len(after)
                pb["prompt_patches"][role] = after
        if pruned:
            self._rebuild_index()
            self._save()
        return pruned

    def list_trajectories(self) -> list[str]:
        return list(self._data.get("trajectories", {}).keys())

    def snapshot(self, trajectory_id: str) -> list[dict[str, Any]]:
        traj = self._data["trajectories"].get(trajectory_id, {})
        pb = traj.get("playbook", {})
        result: list[dict[str, Any]] = []
        for section in ["routing_rules", "waste_patterns", "high_roi_context", "episodic"]:
            result.extend(pb.get(section, []))
        for role_entries in pb.get("prompt_patches", {}).values():
            result.extend(role_entries)
        return result

    def get_trajectory_meta(self, trajectory_id: str) -> dict[str, Any]:
        traj = self._data["trajectories"].get(trajectory_id, {})
        return {
            "trajectory_id": trajectory_id,
            "description": traj.get("description", ""),
            "created_at": traj.get("created_at", ""),
            "entry_count": len(self.snapshot(trajectory_id)),
        }

    def create_trajectory(self, trajectory_id: str, description: str = "") -> None:
        self._ensure_trajectory(trajectory_id, description)
        self._save()
