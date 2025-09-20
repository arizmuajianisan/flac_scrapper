# FLAC Scraper

A command-line tool to browse and download FLAC files from music servers.

## Features

- Browse folder structures of music servers
- Download FLAC files with progress bars
- Redis-based caching for faster navigation
- Skip already downloaded files
- Interactive command-line interface

## Installation

1. Make sure you have Python 3.8+ installed
2. Install the package in development mode:
    ```bash
    git clone <repository-url>
    cd flac-scraper
    pip install -e .
    ```
3. Install Playwright browsers:
    ```bash
    playwright install
    ```
4. (Optional) Install Redis for persistent caching:
    ```bash
    # On Ubuntu/Debian
    sudo apt-get install redis-server
    sudo systemctl enable --now redis-server
    ```

## Usage

```bash
# Run the scraper
flac-scraper
```

## Configuration

The tool will automatically use Redis if available, falling back to in-memory caching if not.

## License

MIT
