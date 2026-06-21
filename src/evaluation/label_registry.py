"""LabelDefinition registry.

Every label used to train a model is described by a `LabelDefinition` and saved
to `label_registry/<label_id>.json`. At training time the definition is copied
into the model artifact directory as `label_definition.json`. That makes
"which label was this model trained against?" a directly-verifiable question
forever.

`fingerprint()` hashes the canonical form of the definition (sorted keys, no
volatile fields like `generated_at`) so two semantically-identical labels
produce the same hash even if cosmetic fields differ.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# Fields excluded from the fingerprint because they are volatile / cosmetic.
_FINGERPRINT_EXCLUDE = {"generated_at"}


@dataclass(frozen=True)
class LabelDefinition:
    label_id: str
    description: str
    target_col: str
    horizon_days: int
    exit_rule: str
    source_query: str
    git_sha: str
    generated_at: str
    bins: Optional[List[float]] = None

    @classmethod
    def from_json(cls, path: Path) -> "LabelDefinition":
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, sort_keys=True)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        """SHA-256 of the canonical JSON form, excluding volatile fields."""
        payload = {k: v for k, v in asdict(self).items() if k not in _FINGERPRINT_EXCLUDE}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
