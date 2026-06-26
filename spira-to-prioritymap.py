#!/usr/bin/env python3
"""
spira-to-prioritymap.py — SpiraPlan to PriorityMap Exporter

Extracts Requirements (from a project) and/or Capabilities (from a program)
via the SpiraPlan REST API and produces a JSON file that PriorityMap can load.

Configuration
-------------
Connection credentials are read from a spira.cfg file (INI format):

    [connection]
    base_url = https://mycompany.spiraservice.net
    username = fred
    api_key = {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}

Usage
-----
    python spira-to-prioritymap.py --project-id 1 --program-id 2 -o board.json
    python spira-to-prioritymap.py --project-id 1 --requirement-type Initiative
    python spira-to-prioritymap.py --project-id 1 --requirement-type "User Story" --requirement-type Feature

Field mapping
-------------
  Requirements
    title           ← Name
    costComplexity  ← EstimatePoints (story points clamped to 1-10; default 5)
    benefitsImpact  ← ImportanceId   (scaled via template lookup)
    importance      ← ImportanceId   (same scale)
    outcome         ← "Requirement"
    notes           ← Description    (HTML stripped)

  Capabilities
    title           ← Name
    costComplexity  ← 5              (default — no cost field in capabilities)
    benefitsImpact  ← CapabilityPriorityId (scaled via system lookup)
    importance      ← CapabilityPriorityId (same scale)
    outcome         ← "Capability"
    notes           ← Description    (HTML stripped)

No external dependencies — uses only the Python 3 standard library.
"""

import argparse
import configparser
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

API_PATH = "services/v7_0/RestService.svc"
DEFAULT_CONFIG_FILE = "spira.cfg"

OUTCOME_COLORS = {
    "Requirement": "#0077BB",
    "Capability": "#EE7733",
}


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------
def load_config(path):
    """Read settings from an INI config file."""
    cfg = configparser.ConfigParser()
    if not os.path.isfile(path):
        return {}
    cfg.read(path, encoding="utf-8")
    result = {}
    if cfg.has_section("connection"):
        result["base_url"] = cfg.get("connection", "base_url", fallback=None)
        result["username"] = cfg.get("connection", "username", fallback=None)
        result["api_key"] = cfg.get("connection", "api_key", fallback=None)
    if cfg.has_section("requirements"):
        raw = cfg.get("requirements", "types", fallback="")
        types = [t.strip() for t in raw.split(",") if t.strip()]
        if types:
            result["requirement_types"] = types
    return {k: v for k, v in result.items() if v}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def strip_html(text):
    """Remove HTML tags and decode entities to plain text."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def clamp(value, lo=1, hi=10):
    """Clamp a numeric value to [lo, hi]."""
    return max(lo, min(hi, int(round(value))))


# ---------------------------------------------------------------------------
# SpiraPlan REST client (stdlib only)
# ---------------------------------------------------------------------------
class SpiraClient:
    """Thin wrapper around the SpiraPlan v7 REST API."""

    def __init__(self, base_url, username, api_key):
        self.base = base_url.rstrip("/")
        self.svc = f"{self.base}/{API_PATH}"
        self.headers = {
            "username": username,
            "api-key": api_key,
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        self._ctx = ssl.create_default_context()

    def _get(self, path):
        url = f"{self.svc}/{path}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, context=self._ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"API error {exc.code} on GET {url}\n{body}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as exc:
            print(f"Connection error: {exc.reason}", file=sys.stderr)
            sys.exit(1)

    # -- projects / requirements -----------------------------------------------
    def project(self, project_id):
        return self._get(f"projects/{project_id}")

    def requirement_importances(self, template_id):
        return self._get(
            f"project-templates/{template_id}/requirements/importances"
        )

    def requirement_types(self, template_id):
        return self._get(
            f"project-templates/{template_id}/requirements/types"
        )

    def requirements(self, project_id, start=1, count=500):
        return self._get(
            f"projects/{project_id}/requirements"
            f"?starting_row={start}&number_of_rows={count}"
        )

    # -- programs / capabilities -----------------------------------------------
    def capability_priorities(self):
        return self._get("capabilities/priorities")

    def capabilities(self, program_id, page=1, size=500):
        return self._get(
            f"programs/{program_id}/capabilities/search"
            f"?current_page={page}&page_size={size}"
        )


# ---------------------------------------------------------------------------
# Score mapping
# ---------------------------------------------------------------------------
def build_score_map(lookup_items, id_field):
    """
    Convert a SpiraPlan lookup list into {id: score_1_to_10}.

    Uses the Score field when available; otherwise ranks items by list
    position (first item = highest score, matching typical Critical → Low
    ordering in SpiraPlan templates).
    """
    if not lookup_items:
        return {}

    has_score = any(item.get("Score") is not None for item in lookup_items)

    if has_score:
        raw = {item[id_field]: item.get("Score", 0) for item in lookup_items}
        hi = max(raw.values()) or 1
        lo = min(raw.values())
        if hi == lo:
            return {k: 5 for k in raw}
        return {
            k: clamp(1 + (v - lo) / (hi - lo) * 9)
            for k, v in raw.items()
        }

    # Fall back to position-based ranking
    n = len(lookup_items)
    return {
        item[id_field]: clamp(10 - i * 9 / max(n - 1, 1))
        for i, item in enumerate(lookup_items)
    }


# ---------------------------------------------------------------------------
# Mapping functions
# ---------------------------------------------------------------------------
def map_requirements(requirements, score_map):
    """Convert SpiraPlan requirement objects to PriorityMap items."""
    items = []
    for req in requirements:
        imp_id = req.get("ImportanceId")
        benefit = score_map.get(imp_id, 5) if imp_id else 5

        est = req.get("EstimatePoints")
        cost = clamp(est) if est and est > 0 else 5

        items.append(
            {
                "title": req.get("Name", "Untitled"),
                "costComplexity": cost,
                "benefitsImpact": benefit,
                "importance": benefit,
                "outcome": "Requirement",
                "timeline": "6m",
                "notes": strip_html(req.get("Description", "")),
            }
        )
    return items


def map_capabilities(capabilities, score_map):
    """Convert SpiraPlan capability objects to PriorityMap items."""
    items = []
    for cap in capabilities:
        pri_id = cap.get("CapabilityPriorityId")
        benefit = score_map.get(pri_id, 5) if pri_id else 5

        items.append(
            {
                "title": cap.get("Name", "Untitled"),
                "costComplexity": 5,
                "benefitsImpact": benefit,
                "importance": benefit,
                "outcome": "Capability",
                "timeline": "6m",
                "notes": strip_html(cap.get("Description", "")),
            }
        )
    return items


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------
def build_prioritymap_json(items, outcomes):
    """Wrap mapped items in the full PriorityMap file structure."""
    # Assign sequential IDs
    for idx, item in enumerate(items, start=1):
        item["id"] = idx

    return {
        "config": {
            "matrix": {
                "xAxis": {"label": "Cost / Complexity", "min": 1, "max": 10},
                "yAxis": {
                    "label": "Potential Benefits Impact",
                    "min": 1,
                    "max": 10,
                },
                "sizeLabel": "Importance",
            },
            "quadrants": [
                {
                    "name": "STRATEGIC QUICK WINS",
                    "xBounds": [1, 5],
                    "yBounds": [6, 10],
                },
                {
                    "name": "STRATEGIC PRIORITIES",
                    "xBounds": [5, 10],
                    "yBounds": [6, 10],
                },
                {
                    "name": "LOW PRIORITY",
                    "xBounds": [1, 5],
                    "yBounds": [1, 5],
                },
                {
                    "name": "RECONSIDER",
                    "xBounds": [5, 10],
                    "yBounds": [1, 5],
                },
            ],
            "outcomes": outcomes,
        },
        "settings": {
            "textSize": "small",
            "defaultTheme": "light",
            "title": "PriorityMap",
            "subtitle": "SpiraPlan Import",
        },
        "items": items,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Export SpiraPlan Requirements and Capabilities "
            "to a PriorityMap JSON file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  %(prog)s --project-id 1\n"
            "  %(prog)s --project-id 1 --requirement-type Initiative\n"
            "  %(prog)s --project-id 1 --requirement-type \"User Story\" "
            "--requirement-type Feature\n"
            "  %(prog)s --project-id 1 --program-id 2 -o board.json\n"
            "\n"
            "Connection settings are read from spira.cfg (see --config).\n"
            "CLI flags and environment variables override the config file."
        ),
    )
    p.add_argument(
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to config file (default: {DEFAULT_CONFIG_FILE})",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("SPIRA_BASE_URL"),
        help="SpiraPlan instance base URL (overrides config/env)",
    )
    p.add_argument(
        "--username",
        default=os.environ.get("SPIRA_USERNAME"),
        help="SpiraPlan login name (overrides config/env)",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("SPIRA_API_KEY"),
        help="RSS Token / API key from user profile (overrides config/env)",
    )
    p.add_argument(
        "--project-id",
        type=int,
        help="Project ID — fetches requirements from this project",
    )
    p.add_argument(
        "--program-id",
        type=int,
        help="Program ID — fetches capabilities from this program",
    )
    p.add_argument(
        "--requirement-type",
        action="append",
        metavar="TYPE",
        help=(
            "Only include requirements of this type "
            "(e.g. Initiative, Feature, \"User Story\"). "
            "Repeat for multiple types. Omit to include all types."
        ),
    )
    p.add_argument(
        "--include-summary",
        action="store_true",
        help="Include summary/parent requirements (excluded by default)",
    )
    p.add_argument(
        "-o",
        "--output",
        default="prioritymap-data.json",
        help="Output file path (default: prioritymap-data.json)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def resolve_type_ids(client, template_id, type_names):
    """
    Resolve requirement type names to their IDs.

    Fetches the template's requirement types and matches by name
    (case-insensitive). Exits with an error if any name is unrecognized.
    """
    all_types = client.requirement_types(template_id)
    # Build lookup: lowercase name → id
    name_to_id = {
        t["Name"].strip().lower(): t["RequirementTypeId"]
        for t in all_types
    }

    matched_ids = set()
    for name in type_names:
        key = name.strip().lower()
        if key not in name_to_id:
            available = ", ".join(
                t["Name"] for t in all_types if t.get("IsActive", True)
            )
            print(
                f"Error: unknown requirement type '{name}'.\n"
                f"Available types: {available}",
                file=sys.stderr,
            )
            sys.exit(1)
        matched_ids.add(name_to_id[key])
    return matched_ids


def main():
    args = parse_args()

    # --- load config file -----------------------------------------------------
    cfg = load_config(args.config)

    # CLI args override config file; config file fills in gaps
    base_url = args.base_url or cfg.get("base_url")
    username = args.username or cfg.get("username")
    api_key = args.api_key or cfg.get("api_key")

    # --- validate required args -----------------------------------------------
    missing = []
    if not base_url:
        missing.append("base_url (in spira.cfg, --base-url, or SPIRA_BASE_URL)")
    if not username:
        missing.append("username (in spira.cfg, --username, or SPIRA_USERNAME)")
    if not api_key:
        missing.append("api_key (in spira.cfg, --api-key, or SPIRA_API_KEY)")
    if missing:
        print("Missing required connection settings:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        sys.exit(1)

    if not args.project_id and not args.program_id:
        print(
            "Error: provide at least one of --project-id or --program-id",
            file=sys.stderr,
        )
        sys.exit(1)

    client = SpiraClient(base_url, username, api_key)
    all_items = []
    outcomes = {}

    # --- requirements ---------------------------------------------------------
    if args.project_id:
        print(f"Fetching project {args.project_id} ...")
        project = client.project(args.project_id)
        template_id = project.get("ProjectTemplateId")

        print(f"Fetching requirement importances (template {template_id}) ...")
        importances = client.requirement_importances(template_id)
        imp_scores = build_score_map(importances, "ImportanceId")

        # Resolve type filter: CLI overrides config
        type_names = args.requirement_type or cfg.get("requirement_types")
        type_ids = None
        if type_names:
            print(f"Resolving requirement types: {type_names} ...")
            type_ids = resolve_type_ids(client, template_id, type_names)

        print("Fetching requirements ...")
        reqs = client.requirements(args.project_id)

        if type_ids:
            reqs = [r for r in reqs if r.get("RequirementTypeId") in type_ids]
        elif not args.include_summary:
            reqs = [r for r in reqs if not r.get("Summary", False)]

        req_items = map_requirements(reqs, imp_scores)
        all_items.extend(req_items)
        outcomes["Requirement"] = OUTCOME_COLORS["Requirement"]
        print(f"  {len(req_items)} requirements mapped")

    # --- capabilities ---------------------------------------------------------
    if args.program_id:
        print("Fetching capability priorities ...")
        priorities = client.capability_priorities()
        pri_scores = build_score_map(priorities, "CapabilityPriorityId")

        print(f"Fetching capabilities (program {args.program_id}) ...")
        caps = client.capabilities(args.program_id)

        cap_items = map_capabilities(caps, pri_scores)
        all_items.extend(cap_items)
        outcomes["Capability"] = OUTCOME_COLORS["Capability"]
        print(f"  {len(cap_items)} capabilities mapped")

    if not all_items:
        print("No items found — nothing to export.", file=sys.stderr)
        sys.exit(0)

    # --- write output ---------------------------------------------------------
    output = build_prioritymap_json(all_items, outcomes)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(all_items)} items to {args.output}")


if __name__ == "__main__":
    main()
