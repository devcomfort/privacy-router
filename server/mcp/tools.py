"""Privacy Router Server — MCP tools.

FastMCP server exposing ``classify`` and ``route`` tools for
agent integration.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("privacy-router")


@mcp.tool()
def classify(text: str) -> dict:
    """Classify a prompt for sensitive information.

    Runs the full Extractor → Judge pipeline and returns
    sensitivity assessment, extracted records, and policy action.

    Args:
        text: The raw prompt text to classify.

    Returns:
        dict with keys: is_sensitive, records, policy_action, rationale
    """
    from agents.router import PrivacyRouter

    pr = PrivacyRouter()
    pipeline = pr.process(text)

    is_sensitive = (
        pipeline.sensitivity.get("is_sensitive", False)
        if isinstance(pipeline.sensitivity, dict)
        else getattr(pipeline.sensitivity, "is_sensitive", False)
    )

    judgment_data = pipeline.judgment if isinstance(pipeline.judgment, dict) else {}
    records_raw = judgment_data if isinstance(judgment_data, list) else []

    return {
        "is_sensitive": is_sensitive,
        "records": [
            {"category": r.get("category", ""), "span": r.get("span", "")}
            for r in (records_raw if isinstance(records_raw, list) else [])
        ],
        "policy_action": (
            pipeline.route.endpoint
            if hasattr(pipeline.route, "endpoint")
            else str(pipeline.route)
        ),
        "requires_masking": (
            pipeline.route.requires_masking
            if hasattr(pipeline.route, "requires_masking")
            else False
        ),
        "description": (
            pipeline.route.description
            if hasattr(pipeline.route, "description")
            else ""
        ),
    }


@mcp.tool()
def route(text: str) -> dict:
    """Full pipeline: classify + routing decision in one call.

    Args:
        text: The raw prompt text to process.

    Returns:
        dict with full pipeline result including endpoint and masking decision.
    """
    return classify(text)
