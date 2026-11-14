"""Движки извлечения. Оба возвращают одну и ту же схему InvoiceData, поэтому взаимозаменяемы."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..schemas import EngineMeta, InvoiceData


class EngineError(RuntimeError):
    """Движок не смог обработать документ (нет текстового слоя, нет связи, отказ модели)."""


@dataclass(frozen=True)
class Document:
    path: Path
    kind: str  # pdf | png | jpeg
    filename: str


class Engine(Protocol):
    name: str

    def extract(self, document: Document) -> tuple[InvoiceData, EngineMeta]: ...


def build_engine(kind: str, company: dict, model: str, effort: str) -> Engine:
    """Создаёт движок по имени. SDK Anthropic импортируется только для режима claude."""
    if kind == "claude":
        from .claude import ClaudeEngine

        return ClaudeEngine(company, model=model, effort=effort)
    from .rules import RulesEngine

    return RulesEngine(company)
