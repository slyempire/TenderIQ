# TenderIQ

> AI-powered tender management for African procurement markets

TenderIQ is a [Frappe](https://frappeframework.com/) app that helps procurement teams discover, track and respond to public tenders across East Africa. It integrates with the PPRA portal, uses Claude AI for document analysis, and sends WhatsApp alerts via AfricasTalking.

---

## Features

- **Automated tender discovery** – Scrapes PPRA and other portals every 6 hours
- **AI-powered document analysis** – Claude extracts key requirements, deadlines and red flags from tender PDFs
- **Deadline tracking** – Hourly countdown alerts for approaching submission deadlines
- **Daily digest emails** – Morning summary of active tenders sorted by urgency
- **WhatsApp alerts** – Instant notifications via AfricasTalking when matched tenders are found
- **Bid team management** – Assign team members to specific tenders
- **Compliance checklists** – Pre-loaded compliance items seeded from fixtures

---

## Requirements

| Dependency | Version |
|------------|---------|
| Python | ≥ 3.10 |
| Frappe Framework | 15.x |
| Anthropic API key | Required for AI features |
| AfricasTalking account | Optional – for WhatsApp alerts |

---

## Installation

### Self-hosted (bench)

```bash
# From your bench directory
bench get-app https://github.com/slyempire/tenderiq
bench --site your-site.localhost install-app tenderiq
bench --site your-site.localhost migrate
```

### Frappe Cloud

1. In your Frappe Cloud dashboard, create a new site or select an existing one.
2. Go to **Apps → Add App from GitHub**.
3. Enter the repository URL: `https://github.com/slyempire/tenderiq`
4. Select the `main` branch and click **Install**.
5. After installation, run migrations: **Site → Actions → Migrate**.
6. Navigate to **TenderIQ Settings** and configure your API keys.

---

## Configuration

After installation, open **TenderIQ Settings** (search in the Frappe toolbar):

| Setting | Description |
|---------|-------------|
| `anthropic_api_key` | Your Anthropic API key (required for AI features) |
| `anthropic_model` | Claude model to use (default: `claude-3-5-haiku-20241022`) |
| `enable_ppra_scraper` | Toggle automated PPRA scraping on/off |
| `africastalking_api_key` | AfricasTalking API key for WhatsApp alerts |
| `africastalking_username` | Your AfricasTalking username |
| `enable_whatsapp_alerts` | Enable WhatsApp notification delivery |
| `watch_keywords` | Comma-separated keywords to filter tenders (e.g. `construction,IT,health`) |
| `watch_categories` | Comma-separated category codes to watch |

Use the **Test API Connection** button to verify your Anthropic credentials.

---

## Development

```bash
# Clone for local development
git clone https://github.com/slyempire/tenderiq
cd tenderiq

# Install Python dependencies
pip install -e ".[dev]"

# Run syntax checks
python3 -m py_compile tenderiq/**/*.py
```

---

## Architecture

```
tenderiq/
├── tenderiq/               # Main app package
│   ├── api/                # Whitelisted API endpoints
│   ├── calendar/           # Scheduler jobs (deadlines, digest)
│   │   ├── deadlines.py    # Hourly countdown computation
│   │   └── digest.py       # Daily email digest
│   ├── doctype/
│   │   ├── tender/         # Main Tender document
│   │   ├── tender_document/ # Attached PDFs – AI analysis triggers here
│   │   ├── tender_checklist/ # Compliance checklist
│   │   ├── bid_team/        # Bid team assignment
│   │   ├── pricing_sheet/   # Bid pricing
│   │   ├── submission_record/ # Submission tracking
│   │   └── tenderiq_settings/ # Singleton settings
│   ├── integrations/       # Anthropic (Claude) + AfricasTalking wrappers
│   └── scrapers/           # Web scrapers (PPRA, AGPO, county portals)
│       └── runner.py       # Scheduler entry point
├── requirements.txt
├── setup.py
└── apps.json               # Frappe Cloud deployment manifest
```

---

## License

MIT
