# PriorityMap
## Make Better Prioritization Decisions, Together
PriorityMap helps teams align on what to build next by making trade-offs visible. Instead of debating priorities in spreadsheets or slide decks, you see every initiative plotted on a single canvas — where position tells the story.

## The problem it solves
Prioritization discussions often stall because stakeholders weigh different factors. Engineering sees complexity; product sees value; leadership sees strategy. This tool puts all three dimensions on one view so everyone works from the same picture.

## How it helps decision-making
- **Spot misallocations instantly** — high-cost, low-value items stand out in the bottom-right. Quick wins cluster in the top-left.
- **Facilitate live trade-off discussions** — drag bubbles during meetings to test "what if we reduce scope?"
- **Create alignment across roles** — the visual makes it obvious when too many items compete for the same quadrant.
- **Track portfolio balance** — color-coded outcomes show whether you're over-investing in one strategic theme.
- **Reduce recency bias** — seeing all initiatives at once prevents the loudest request from dominating.

## Use cases
- Quarterly planning and roadmap reviews
- Sprint backlog prioritization with engineering leads
- Executive strategy sessions and board prep
- Build-vs-buy and investment trade-off analysis
- Cross-team alignment on shared resources

## Getting started
- Download the `priority-map.html` file
- Open it in your browser (no server required)
- Read the in-app help
- Save your work at any time to a local JSON (and load it next time)

## SpiraPlan Import Utility

`spira-to-prioritymap.py` extracts Requirements and/or Capabilities from Inflectra SpiraPlan and generates a JSON file that PriorityMap can load directly.

### Prerequisites
- Python 3.7+
- A SpiraPlan user account with an RSS Token (API key)

### Setup
1. Copy `spira.cfg.example` to `spira.cfg`
2. Fill in your SpiraPlan connection details:
   ```ini
   [connection]
   base_url = https://mycompany.spiraservice.net
   username = your_username
   api_key = {YOUR-RSS-TOKEN-HERE}

   [requirements]
   types = Initiative, Epic
   ```

### Usage
```bash
# Export requirements from a project (types filtered by spira.cfg)
python3 spira-to-prioritymap.py --project-id 1

# Export capabilities from a program
python3 spira-to-prioritymap.py --program-id 2

# Both, with custom output file
python3 spira-to-prioritymap.py --project-id 1 --program-id 2 -o board.json

# Override config type filter from the command line
python3 spira-to-prioritymap.py --project-id 1 --requirement-type Feature
```

### Options
| Flag | Description |
|------|-------------|
| `--config PATH` | Path to config file (default: `spira.cfg`) |
| `--project-id N` | Project ID — fetches requirements |
| `--program-id N` | Program ID — fetches capabilities |
| `--requirement-type TYPE` | Filter by type name (repeatable; overrides config) |
| `--include-summary` | Include summary/parent requirements when no type filter is set |
| `-o, --output FILE` | Output JSON file (default: `prioritymap-data.json`) |

### Field mapping

| PriorityMap field | Requirements source | Capabilities source |
|-------------------|--------------------|--------------------|
| title | Name | Name |
| costComplexity | EstimatePoints (1-10, default 5) | 5 |
| benefitsImpact | ImportanceId (scaled) | CapabilityPriorityId (scaled) |
| importance | ImportanceId (scaled) | CapabilityPriorityId (scaled) |
| outcome | "Requirement" | "Capability" |
| notes | Description (HTML stripped) | Description (HTML stripped) |

### Loading the output
Open `priority-map.html` in your browser and click **Load** to import the generated `prioritymap-data.json` file.
