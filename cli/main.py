import argparse
import sys
from pathlib import Path

from core.scraper import PinterestScraper
from core.downloader import download_all
from core.dedupe import DedupeStore
from core.storage import StorageManager
from core.http import build_session


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pinterest Scraper - High-performance pin scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    search_parser = subparsers.add_parser("search", help="Search pins by query")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-l", "--limit", type=int, default=25, help="Limit results")
    search_parser.add_argument("-o", "--output", default="downloads", help="Output directory")
    search_parser.add_argument("-w", "--workers", type=int, default=4, help="Download workers")
    search_parser.add_argument("-d", "--delay", type=float, default=1.0, help="Request delay")
    search_parser.add_argument("--no-download", action="store_true", help="Skip download")
    search_parser.add_argument("--dedup", action="store_true", help="Enable deduplication")

    board_parser = subparsers.add_parser("board", help="Scrape board pins")
    board_parser.add_argument("url", help="Board URL")
    board_parser.add_argument("-l", "--limit", type=int, default=25, help="Limit results")
    board_parser.add_argument("-o", "--output", default="downloads", help="Output directory")
    board_parser.add_argument("-w", "--workers", type=int, default=4, help="Download workers")
    board_parser.add_argument("-d", "--delay", type=float, default=1.0, help="Request delay")
    board_parser.add_argument("--no-download", action="store_true", help="Skip download")
    board_parser.add_argument("--dedup", action="store_true", help="Enable deduplication")

    export_parser = subparsers.add_parser("export", help="Export pins to formats")
    export_parser.add_argument("input", help="Input JSON file")
    export_parser.add_argument("-f", "--format", choices=["xlsx", "csv", "json"], default="xlsx")
    export_parser.add_argument("-o", "--output", help="Output file")

    server_parser = subparsers.add_parser("server", help="Start web server")
    server_parser.add_argument("--host", default="0.0.0.0", help="Server host")
    server_parser.add_argument("--port", type=int, default=8080, help="Server port")

    return parser.parse_args()


def cmd_search(args):
    print(f"Searching for: {args.query}")
    
    proxy_list = None
    session = build_session(proxy_pool=proxy_list)
    scraper = PinterestScraper(proxy_pool=proxy_list, delay=args.delay)

    pins = scraper.search(args.query, args.limit)
    print(f"Found {len(pins)} pins")

    if args.dedup:
        dedup = DedupeStore()
        pins, skipped = dedup.deduplicate_pins(pins)
        print(f"After dedup: {len(pins)} unique pins (skipped: {skipped})")

    if pins and not args.no_download:
        print(f"Downloading to {args.output}...")
        stats = download_all(session, pins, args.output, args.workers)
        print(f"Downloaded: {stats['downloaded']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")

    storage = StorageManager()
    storage.save_json(pins, f"search_{args.query.replace(' ', '_')}.json")
    print("Results saved to storage/")


def cmd_board(args):
    print(f"Scraping board: {args.url}")
    
    proxy_list = None
    session = build_session(proxy_pool=proxy_list)
    scraper = PinterestScraper(proxy_pool=proxy_list, delay=args.delay)

    pins = scraper.get_board_pins(args.url, args.limit)
    print(f"Found {len(pins)} pins")

    if args.dedup:
        dedup = DedupeStore()
        pins, skipped = dedup.deduplicate_pins(pins)
        print(f"After dedup: {len(pins)} unique pins (skipped: {skipped})")

    if pins and not args.no_download:
        print(f"Downloading to {args.output}...")
        stats = download_all(session, pins, args.output, args.workers)
        print(f"Downloaded: {stats['downloaded']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")

    storage = StorageManager()
    storage.save_json(pins, "board_pins.json")
    print("Results saved to storage/")


def cmd_export(args):
    print(f"Exporting from {args.input}...")
    
    storage = StorageManager()
    pins = storage.load_json(args.input)

    if not pins:
        print("No data found")
        return

    output = args.output or f"pins.{args.format}"

    if args.format == "xlsx":
        storage.save_xlsx(pins, output)
    elif args.format == "csv":
        storage.save_csv(pins, output)
    else:
        storage.save_json(pins, output)

    print(f"Exported {len(pins)} pins to {output}")


def cmd_server(args):
    print(f"Starting server on {args.host}:{args.port}")
    print(f"Open http://localhost:{args.port}")
    
    from api.server import run_server
    run_server(host=args.host, port=args.port)


def main():
    args = parse_args()

    if not args.command:
        print("No command specified. Use --help for usage information.")
        sys.exit(1)

    try:
        if args.command == "search":
            cmd_search(args)
        elif args.command == "board":
            cmd_board(args)
        elif args.command == "export":
            cmd_export(args)
        elif args.command == "server":
            cmd_server(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
