"""A system's profile: its stages, its normalisation, its replay budget.

One TOML file per system or site. A new site of the same system needs only a
new profile; a different system needs a profile and an adapter.
"""

import hashlib
from dataclasses import dataclass, field

import tomllib

from .model import STAGE_KINDS


class ProfileError(ValueError):
    pass


@dataclass
class Stage:
    name: str
    kind: str


@dataclass
class Profile:
    system: str
    stages: list
    section_field: str = "section"
    tag_name: str = "tag"
    same_line: float = 0.72
    fold_accents: bool = True
    strip_punctuation: bool = True
    replay: dict = field(default_factory=dict)
    source_hash: str = ""

    def stage(self, name: str) -> Stage:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(name)

    def capture_stages(self) -> list:
        return [s for s in self.stages if s.kind != "drop"]

    def drop_stages(self) -> list:
        return [s for s in self.stages if s.kind == "drop"]


def parse_profile(data: dict, source_hash: str = "") -> Profile:
    system = str(data.get("system") or "").strip()
    if not system:
        raise ProfileError("profile needs a non-empty 'system'")
    raw_stages = data.get("stages") or []
    if not raw_stages:
        raise ProfileError("profile needs at least one [[stages]] entry")
    stages, seen = [], set()
    for item in raw_stages:
        name = str(item.get("name") or "").strip()
        kind = item.get("kind")
        if not name:
            raise ProfileError("every stage needs a name")
        if kind not in STAGE_KINDS:
            raise ProfileError(f"stage {name!r}: kind must be one of {STAGE_KINDS}")
        if name in seen:
            raise ProfileError(f"stage {name!r} is listed twice")
        seen.add(name)
        stages.append(Stage(name, kind))
    truth = data.get("truth") or {}
    align = data.get("align") or {}
    same_line = float(align.get("same_line", 0.72))
    if not 0.0 < same_line <= 1.0:
        raise ProfileError("align.same_line must be in (0, 1]")
    return Profile(
        system=system,
        stages=stages,
        section_field=str(truth.get("section_field", "section")),
        tag_name=str(truth.get("tag_name", "tag")),
        same_line=same_line,
        fold_accents=bool(align.get("fold_accents", True)),
        strip_punctuation=bool(align.get("strip_punctuation", True)),
        replay=dict(data.get("replay") or {}),
        source_hash=source_hash,
    )


def load_profile(path) -> Profile:
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path}: {exc}") from exc
    return parse_profile(data, source_hash=hashlib.sha256(raw).hexdigest())
