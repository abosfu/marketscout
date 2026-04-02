"""AI logic layer: strategy generation and report rendering."""

from marketscout.backend.ai.strategy import generate_strategy
from marketscout.backend.ai.report_md import strategy_to_markdown
from marketscout.backend.ai.report_html import strategy_to_html
from marketscout.backend.schema import OpportunityBrief, StrategyOutput

__all__ = ["OpportunityBrief", "StrategyOutput", "generate_strategy", "strategy_to_markdown", "strategy_to_html"]
