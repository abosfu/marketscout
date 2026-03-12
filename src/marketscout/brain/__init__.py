"""Brain module: generate strategy (mock or LLM) with schema validation."""

from marketscout.brain.report_html import strategy_to_html
from marketscout.brain.report_md import strategy_to_markdown
from marketscout.brain.schema import OpportunityBrief, StrategyOutput
from marketscout.brain.strategy import generate_strategy

__all__ = ["OpportunityBrief", "StrategyOutput", "generate_strategy", "strategy_to_markdown", "strategy_to_html"]
