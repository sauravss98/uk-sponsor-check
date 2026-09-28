"""MCP server exposing the register to Claude Desktop, Claude Code and other MCP clients.

Run with:  sponsor-check-mcp   (stdio transport)
"""

from __future__ import annotations

from functools import lru_cache

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .register import DEFAULT_ROUTE, Register, ensure_database
from .salary import check_salary as _check_salary
from .salary import thresholds as _thresholds

mcp = MCPServer(
    name="sponsor-check",
    instructions=(
        "Tools for checking whether a UK employer holds a Home Office sponsor licence and "
        "whether a salary meets the Skilled Worker requirement. Use check_sponsor for a "
        "yes/no verdict on a named employer. If the verdict is possible_match or not_found, "
        "tell the user the name may differ from the legal entity and suggest search_sponsors "
        "or Companies House. Use check_salary when a salary and an occupation code are known; "
        "it needs the 4-digit SOC 2020 code, so ask for it rather than guessing one. Always "
        "mention the register date or thresholds date, and that a licence does not guarantee "
        "sponsorship of a given role. None of this is immigration advice."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


@lru_cache(maxsize=1)
def _register() -> Register:
    return Register(ensure_database())


@mcp.tool(annotations=READ_ONLY)
def check_sponsor(company: str, route: str = DEFAULT_ROUTE) -> dict:
    """Check whether a UK employer is licensed to sponsor visas on a given route.

    Args:
        company: Employer name as it appears in a job ad (legal or trading name).
        route: Visa route, e.g. "Skilled Worker" (default), "Global Business Mobility:
            Senior or Specialist Worker", "Scale-up", "Creative Worker".

    Returns a verdict (licensed, licensed_other_routes, possible_match, not_found),
    the matching register entries with their routes and A/B ratings, and caveats.
    """
    return _register().check(company, route)


@mcp.tool(annotations=READ_ONLY)
def search_sponsors(query: str, limit: int = 5) -> list[dict]:
    """Fuzzy-search the register and return the closest organisations, best first."""
    return [m.to_dict() for m in _register().search(query, max(1, min(limit, 25)))]


@mcp.tool(annotations=READ_ONLY)
def check_salary(salary: float, soc_code: str, new_entrant: bool = False) -> dict:
    """Check a salary against the Skilled Worker salary requirement for an occupation.

    The requirement is the higher of a general threshold and the occupation's published
    going rate, so both the salary and the occupation code are needed.

    Args:
        salary: Gross annual salary offered, in pounds.
        soc_code: 4-digit SOC 2020 occupation code for the job, e.g. "2136". Ask the user
            or the employer for it; do not guess a code from the job title.
        new_entrant: True if the applicant qualifies for the new entrant rate, e.g. under 26,
            a recent UK student or graduate, in professional training, or in an eligible
            postdoctoral role.

    Returns a verdict (meets, below, occupation_ineligible, going_rate_unavailable,
    unknown_occupation), the required salary and the rule that produced it, the other
    discount options the job could qualify under, and the date the thresholds were published.
    """
    return _check_salary(salary, soc_code, new_entrant)


@mcp.tool(annotations=READ_ONLY)
def register_info() -> dict:
    """Dates and sources of the loaded data: the sponsor register and the salary thresholds."""
    data = _thresholds()
    return {**_register().meta(),
            "thresholds_effective_date": data["effective_date"],
            "thresholds_source_url": data["source_url"]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
