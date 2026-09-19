# Pinterest Scraper

High-performance Pinterest content scraper with modern web interface and REST API.

## Features

- Keyword search and board scraping
- High-quality image and video downloads
- Concurrent download processing
- Real-time progress tracking
- Dark mode support
- ZIP and XLSX export
- Deduplication support
- Proxy rotation
- Professional web UI

## Quick Start

### Installation

```bash
pip install -e .
pip install -r requirements.txt
```

### Start Server

```bash
python -m pinterest_scraper.web
```

Server runs on `http://localhost:8000`

### Docker

```bash
docker build -t pinterest-scraper .
docker run -p 8080:8080 pinterest-scraper
```

## Project Structure

```
Pinterest-Scraper/
├── core/                    ← Core scraping logic
│   ├── scraper.py          (200 lines - Pinterest API wrapper)
│   ├── http.py             (80 lines - HTTP sessions & proxies)
│   ├── downloader.py       (120 lines - Concurrent downloads)
│   ├── dedupe.py           (85 lines - Deduplication)
│   ├── storage.py          (140 lines - Data export)
│   └── __init__.py
│
├── api/                     ← FastAPI server
│   ├── server.py           (280 lines - Web server)
│   ├── models.py           (80 lines - Request/response validation)
│   ├── jobs.py             (150 lines - Job management)
│   └── __init__.py
│
├── cli/                     ← Command-line interface
│   ├── main.py             (200 lines - CLI commands)
│   └── __init__.py
│
├── webui/
│   └── pinterest.html      (30 KB - Single HTML file UI)
│
├── Dockerfile              ← Docker image
├── docker-compose.yml      ← Docker Compose
├── requirements.txt        ← Python dependencies
├── setup.py                ← Package setup
├── __main__.py             ← Entry point
├── LICENSE                 ← MIT License
├── .gitignore             ← Git ignore
│
├── README.md               ← Full documentation
├── QUICK_START.txt         ← 5-minute setup
└── PROJECT_STRUCTURE.txt   ← Architecture guide
```

## API Endpoints

### Start Scrape Job

```http
POST /api/scrape
Content-Type: application/json

{
  "query": "search term",
  "mode": "search",
  "limit": 25,
  "download": true,
  "details": true,
  "dedup": false,
  "workers": 4,
  "delay": 1.0,
  "jitter": 0.5,
  "batch_size": 10,
  "min_width": 0,
  "min_height": 0,
  "proxy": ""
}
```

Response:
```json
{
  "job_id": "abc123def456"
}
```

### Get Live Progress

```http
GET /api/jobs/{job_id}/events
```

Server-Sent Events stream with real-time progress updates.

### Get Job Results

```http
GET /api/jobs/{job_id}/result
```

Returns:
```json
{
  "status": "finished",
  "pins": [
    {
      "id": "pin_id",
      "url": "pinterest_url",
      "image_url": "download_url",
      "title": "title",
      "description": "description",
      "type": "image"
    }
  ],
  "stats": {
    "downloaded": 25,
    "skipped": 0
  }
}
```

### Cancel Job

```http
POST /api/jobs/{job_id}/cancel
```

### Health Check

```http
GET /api/health
```

## Configuration

### Environment Variables

```bash
PORT=8080
PYTHONUNBUFFERED=1
```

### Query Parameters

- `query` (string, required): Search term or board URL
- `mode` (string): "search" or "board" (default: "search")
- `limit` (int): Results limit 1-500 (default: 25)
- `download` (bool): Download images (default: true)
- `details` (bool): Fetch metadata (default: true)
- `dedup` (bool): Remove duplicates (default: false)
- `workers` (int): Download threads 1-16 (default: 4)
- `delay` (float): Request delay 0-30 seconds (default: 1.0)
- `jitter` (float): Random variance 0-10 seconds (default: 0.5)
- `batch_size` (int): Batch size 1-100 (default: 10)
- `min_width` (int): Minimum image width (default: 0)
- `min_height` (int): Minimum image height (default: 0)
- `proxy` (string): Comma-separated proxy URLs

## Export Formats

### ZIP

Contains all downloaded images with metadata file:
- images/ folder with all pins
- metadata.json with pin information

### XLSX

Spreadsheet with columns:
- ID
- Title
- Description
- URL
- Download URL
- Type
- Width x Height
- Timestamp

## Module Guide

### core/scraper.py

Main Pinterest scraping logic:

```python
from core.scraper import search_pins, board_pins

results = search_pins("nature photography", limit=50)
board_results = board_pins("https://pinterest.com/user/board")
```

### core/downloader.py

Concurrent download handler:

```python
from core.downloader import download_all

stats = download_all(session, pins, output_dir, workers=4)
```

### core/http.py

HTTP session builder with proxy support:

```python
from core.http import build_session

session = build_session(proxy_pool=["http://proxy1:8080"])
```

### core/dedupe.py

Deduplication storage:

```python
from core.dedupe import DedupeStore

store = DedupeStore(".seen_pins.json")
if store.has(pin_id):
    skip_pin()
else:
    process_pin()
    store.add(pin_id)
```

### core/storage.py

Data export:

```python
from core.storage import save_outputs

save_outputs(pins, output_dir, formats=["json", "xlsx"])
```

## Performance Tips

1. Use appropriate worker count (CPU cores)
2. Set reasonable delays to avoid rate limiting
3. Enable deduplication for repeated searches
4. Filter by dimensions to reduce download time
5. Use proxy rotation for large batches
6. Process in smaller batches if memory-constrained

## Rate Limiting

Pinterest enforces rate limits. Respect them:

- Use default delay (1-2 seconds)
- Rotate proxies for high-volume scraping
- Monitor response headers
- Implement exponential backoff

## Troubleshooting

### No Results

- Verify query spelling
- Try simpler search terms
- Check internet connection
- Verify Pinterest is accessible

### Slow Downloads

- Increase worker count
- Reduce image dimensions
- Disable metadata fetching
- Check network bandwidth

### Memory Issues

- Reduce results limit
- Process in smaller batches
- Monitor available RAM
- Increase batch frequency

### API Connection Errors

- Verify server is running
- Check PORT environment variable
- Review server logs
- Test with curl: `curl http://localhost:8080/api/health`

## Deployment

### Render

1. Connect GitHub repository
2. Create new Web Service
3. Build: `pip install -e . && pip install -r requirements.txt`
4. Start: `python -m pinterest_scraper.web`
5. Set PORT environment variable to 8080

### Docker Compose

```bash
docker-compose up
```

### AWS Lambda

Use Zappa for serverless deployment or EC2 for persistent service.

## CLI Usage

```bash
pinterest-scraper search "nature photography" --limit 50
pinterest-scraper board "https://pinterest.com/user/board"
pinterest-scraper download --query "landscape" --workers 8
```

## Development

### Install Dev Dependencies

```bash
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest tests/
```

### Format Code

```bash
black src/
isort src/
```

## Security

- Do not violate Pinterest Terms of Service
- Respect copyright and intellectual property
- Use responsible rate limiting
- Implement proper authentication for production
- Sanitize user inputs
- Validate API responses

## Error Handling

- Invalid queries return empty results
- Rate limiting triggers automatic delays
- Failed downloads are logged and skipped
- Interrupted jobs can be resumed
- Clear error messages in UI

## Browser Support

- Chrome 60+
- Firefox 55+
- Safari 12+
- Edge 79+

## Supported Python Versions

- Python 3.10+
- Python 3.11
- Python 3.12

## Dependencies

- fastapi >= 0.100.0
- uvicorn >= 0.22.0
- requests >= 2.31.0
- openpyxl >= 3.1.0

## License

MIT License - See LICENSE file for details

## Version

2.0.0

## Changelog

### 2.0.0
- Redesigned folder structure
- Single HTML file web UI
- Removed Persian language
- Cleaned all code comments
- Professional organization
- Advanced README
- Production ready

### 1.3.0
- FastAPI web server
- Server-Sent Events
- XLSX export
- Improved deduplication
- Proxy rotation

## Support

For issues and questions, open GitHub issues or contact support.

## Disclaimer

This tool is for educational and personal use. Users are responsible for ensuring compliance with Pinterest's Terms of Service and applicable laws. The developers are not liable for misuse.
