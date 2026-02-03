from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IndexMessage:
    vault_name: str
    path: Path


@dataclass
class SearchRequestMessage:
    query: str
    limit: int = 8


@dataclass
class SearchResult:
    vault_name: str
    path: Path
    score: float  # distance (lower = better)
    frontmatter: str  # raw YAML frontmatter (if present)
    outline: list[str] = field(default_factory=list)  # list of headings
    excerpt: str = ""  # truncated content


@dataclass
class SearchResponseMessage:
    results: Sequence[SearchResult]


@dataclass
class ExitMessage:
    pass
