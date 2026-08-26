"""Skills training / offline improvement jobs (SkillOpt, Sleep). Hot path: never."""

from .proposer import SkillOptProposal, propose_skill_diff, validate_proposal
from .skillopt_job import collect_trajectories_stub, run_offline_job, skillopt_enabled
from .trajectories import (
    TrajectorySample,
    aggregate_evidence,
    evidence_markdown,
    mine_trajectories,
    mine_trajectories_sync,
    read_jsonl,
    write_jsonl,
)

__all__ = [
    "SkillOptProposal",
    "TrajectorySample",
    "aggregate_evidence",
    "collect_trajectories_stub",
    "evidence_markdown",
    "mine_trajectories",
    "mine_trajectories_sync",
    "propose_skill_diff",
    "read_jsonl",
    "run_offline_job",
    "skillopt_enabled",
    "validate_proposal",
    "write_jsonl",
]
