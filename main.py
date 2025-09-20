#!/usr/bin/env python3
"""
Interactive CLI scraper for https://server.elscione.com/Music/
Usage (with uv):
    uv run main.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import urljoin, unquote

import questionary
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from playwright.sync_api import sync_playwright, Error as PWError

from redis_cache import RedisCache

def get_redis_cache() -> RedisCache:
    """Get a Redis cache instance."""
    return RedisCache()

# Import Redis cache
REDIS_AVAILABLE = True

BASE_URL = "https://server.elscione.com"
ROOT_PATH = "/Music/"
CHUNK = 1024 * 1024  # 1 MB


class MusicScraper:
    def __init__(self, base_url: str = BASE_URL, root: str = ROOT_PATH, redis_cache: Optional[RedisCache] = None) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}
        )
        self.base_url = base_url.rstrip("/")
        self.root = root
        
        # Initialize Redis cache
        self.cache = redis_cache if redis_cache is not None else get_redis_cache()
        
        # Cache configuration
        self.cache_ttl = 3600 * 24 * 7  # 1 week TTL for cached items
        self.cache_prefix = f"flac_scraper:{self.base_url}"

    # ------------------------------------------------------------------ helpers
    # def _soup(self, path: str) -> BeautifulSoup:
    #     url = urljoin(self.base_url, path)
    #     resp = self.session.get(url, timeout=30)
    #     resp.raise_for_status()
    #     return BeautifulSoup(resp.text, "html.parser")

    def _soup(self, path: str) -> BeautifulSoup:
        url = urljoin(self.base_url, path)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                html = page.content()
            except PWError as e:          # network or timeout
                print("Playwright error:", e)
                html = "<html></html>"
            finally:
                browser.close()
        return BeautifulSoup(html, "html.parser")

    def _download(self, file_url: str, dest: Path, max_retries: int = 3) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        # Set up headers to mimic a real browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': self.base_url,
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
        }
        
        for attempt in range(max_retries):
            try:
                with self.session.get(
                    file_url, 
                    stream=True, 
                    timeout=60,
                    headers=headers,
                    allow_redirects=True
                ) as resp:
                    resp.raise_for_status()
                    
                    # Get total size for progress bar
                    total = int(resp.headers.get('content-length', 0))
                    
                    # Save the file
                    with dest.open('wb') as fh, tqdm(
                        total=total, 
                        unit='B', 
                        unit_scale=True, 
                        unit_divisor=1024,
                        desc=dest.name,
                        miniters=1
                    ) as bar:
                        for chunk in resp.iter_content(chunk_size=CHUNK):
                            if chunk:  # filter out keep-alive chunks
                                fh.write(chunk)
                                bar.update(len(chunk))
                    return  # Success, exit the retry loop
                    
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise Exception(f"Failed to download {file_url} after {max_retries} attempts: {e}")
                questionary.print(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(1)  # Wait before retry

    # ------------------------------------------------------------- navigation
    def _get_cache_key(self, prefix: str, path: str) -> str:
        """Generate a cache key with prefix and path."""
        return f"{self.cache_prefix}:{prefix}:{path}"
        
    def list_folders(self, path: str) -> List[Tuple[str, str]]:
        """Get list of folders with Redis caching.
        
        Args:
            path: The path to list folders from
            
        Returns:
            List of (folder_name, folder_path) tuples
        """
        cache_key = self._get_cache_key("folders", path)
        
        # Try to get from cache first
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
            
        # Cache miss - fetch from server
        time.sleep(0.5)  # Rate limiting
        
        soup = self._soup(path)
        # ----  DEBUG: write raw HTML to disk  ----
        Path("debug.html").write_text(str(soup), encoding="utf-8")
        # -----------------------------------------
        folders = []
        for li in soup.select("li.item.folder a"):
            href = li["href"]
            name = li.select_one("span.label").get_text(strip=True)
            folders.append((name, href))
            
        # Cache the result
        if folders:  # Only cache if we got results
            self.cache.set(cache_key, folders, ttl=self.cache_ttl)
            
        return folders

    def list_flac_files(self, path: str) -> List[Tuple[str, str]]:
        """Get list of FLAC files with Redis caching.
        
        Args:
            path: The path to list FLAC files from
            
        Returns:
            List of (file_name, file_url) tuples
        """
        cache_key = self._get_cache_key("flac_files", path)
        
        # Try to get from cache first
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
            
        # Cache miss - fetch from server
        time.sleep(0.5)  # Rate limiting
        
        soup = self._soup(path)
        files = []
        for li in soup.select("li.item.file a"):
            href = li["href"]
            name = li.select_one("span.label").get_text(strip=True)
            if name.lower().endswith(".flac"):
                files.append((name, href))
                
        # Cache the result
        if files:  # Only cache if we got results
            self.cache.set(cache_key, files, ttl=self.cache_ttl)
            
        return files

    # -------------------------------------------------------------- interactive
    def clear_cache(self, path: Optional[str] = None) -> None:
        """Clear the cache for a specific path or all paths.
        
        Args:
            path: If provided, clear cache only for this path. 
                  If None, clear all cached data for this scraper.
        """
        if path:
            # Clear specific path from both caches
            self.cache.delete(
                self._get_cache_key("folders", path),
                self._get_cache_key("flac_files", path)
            )
            print(f"[Cache] Cleared cache for path: {path}")
        else:
            # Clear all cached data for this scraper
            self.cache.clear()
            questionary.print("[Cache] Cleared all cached data for this scraper", style="bold fg:darkred")

    def choose_folder(self, path: str) -> str:
        """Interactive folder navigation with caching support and pagination.
        
        Args:
            path: Starting path
            
        Returns:
            Selected folder path for download
        """
        page_size = 20  # Number of folders to show per page
        current_page = 0
        
        while True:
            folders = self.list_folders(path)
            total_pages = (len(folders) + page_size - 1) // page_size
            
            # Get folders for current page
            start_idx = current_page * page_size
            end_idx = start_idx + page_size
            current_folders = folders[start_idx:end_idx]
            
            # Add navigation options
            choices = []
            
            # Add parent directory option if not at root
            if path != self.root:
                parent_path = str(Path(path).parent)
                if parent_path == '.':
                    parent_path = self.root
                choices.append(questionary.Choice(
                    title="[..] Go Up",
                    value=parent_path,
                    shortcut_key='u'
                ))
            
            # Add folder choices for current page
            for i, (name, folder_path) in enumerate(current_folders, 1):
                shortcut = str(i) if i <= 9 else None
                choices.append(questionary.Choice(
                    title=f"[D] {name}",
                    value=folder_path,
                    shortcut_key=shortcut
                ))
            
            # Add pagination controls if needed
            if total_pages > 1:
                choices.append(questionary.Separator())
                if current_page > 0:
                    choices.append(questionary.Choice(
                        title="[P] Previous Page",
                        value="__prev_page__",
                        shortcut_key='p'
                    ))
                if current_page < total_pages - 1:
                    choices.append(questionary.Choice(
                        title="[N] Next Page",
                        value="__next_page__",
                        shortcut_key='n'
                    ))
            
            # Add action buttons
            choices.extend([
                questionary.Separator(),
                questionary.Choice(
                    title="[C] Clear cache for current path",
                    value="__clear_cache__"
                ),
                questionary.Choice(
                    title="[Q] Quit",
                    value="__quit__"
                )
            ])
            
            try:
                # Show current page info in the prompt
                page_info = f" (Page {current_page + 1}/{total_pages} - {len(folders)} total folders)" if total_pages > 1 else ""
                
                choice = questionary.select(
                    f"\nCurrent path: {path}{page_info}",
                    choices=choices,
                    use_shortcuts=True,
                    use_arrow_keys=True,
                    use_jk_keys=True,
                    use_indicator=True,
                    style=questionary.Style([
                        ('selected', 'fg:red bold'),
                        ('highlighted', 'fg:red'),
                        ('qmark', 'fg:red bold'),
                    ])
                ).ask()
                
                if choice == "__quit__":
                    print("\nGoodbye! 👋")
                    sys.exit(0)
                elif choice == "__clear_cache__":
                    self.clear_cache(path)
                    continue
                elif choice == "__prev_page__" and current_page > 0:
                    current_page = max(0, current_page - 1)
                    continue
                elif choice == "__next_page__" and current_page < total_pages - 1:
                    current_page = min(total_pages - 1, current_page + 1)
                    continue
                else:
                    # Reset page when navigating to a new directory
                    current_page = 0
                    return choice
                    
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                sys.exit(0)
            except Exception as e:
                print(f"\nError: {e}")
                self.clear_cache(path)  # Clear cache on error
                continue
            try:
                # Get folders (from cache if available)
                folders = self.list_folders(path)
                
                # Build menu choices
                choices = [
                    "🔄 Refresh folder list",
                    "🗑️  Clear all cache",
                    "🔙 Go up one level"
                ]
                
                # Add folders to choices
                choices.extend(["📁 " + name for name, _ in folders])
                
                # Add download option if there are FLAC files
                flac_files = self.list_flac_files(path)
                if flac_files:
                    choices.append(f"⬇️  Download {len(flac_files)} FLAC files from here")
                
                # Show menu
                questionary.print(f"\nCurrent path: {path}", style="bold")
                choice = questionary.select(
                    "Select an option:",
                    choices=choices,
                    use_shortcuts=True
                ).ask()
                
                if choice is None:  # User pressed Ctrl+C
                    sys.exit(0)
                
                # Handle menu actions
                if choice == "🔄 Refresh folder list":
                    self.clear_cache(path)
                    questionary.print("✓ Refreshed folder list", style="green")
                    continue
                    
                if choice == "🗑️  Clear all cache":
                    self.clear_cache()
                    questionary.print("✓ Cleared all cache", style="green")
                    continue
                    
                if choice == "🔙 Go up one level":
                    # Go up one directory level
                    path_parts = path.rstrip('/').rsplit('/', 2)  # Split at the last /
                    if len(path_parts) > 1:  # Not at root
                        path = path_parts[0] + '/'
                    continue
                
                if choice.startswith("⬇️"):
                    return path
                
                # Handle folder selection
                name = choice[2:]  # Remove the folder emoji
                _, href = next((n, h) for n, h in folders if n == name)
                path = href
                
            except KeyboardInterrupt:
                questionary.print("\nOperation cancelled by user.", style="red")
                sys.exit(0)
                
            except Exception as e:
                questionary.print(f"Error: {e}", style="red")
                self.clear_cache(path)  # Clear cache on error
                time.sleep(1)  # Prevent tight loop on repeated errors

    def choose_files(self, path: str) -> List[str]:
        """Let the user select which FLAC files to download.
        
        Args:
            path: Path to list FLAC files from
            
        Returns:
            List of selected file URLs
        """
        files = self.list_flac_files(path)
        if not files:
            questionary.print("No FLAC files in this folder.")
            return []
            
        # Sort files by name
        files.sort(key=lambda x: x[0].lower())
        
        # Create a numbered list of files
        choices = [
            questionary.Choice(
                title=f"{i+1:2d}. {name}",
                value=href,
                checked=True  # Pre-select all files by default
            )
            for i, (name, href) in enumerate(files)
        ]
        
        selected = questionary.checkbox(
            "Select FLAC files to download (space to toggle, enter to confirm):",
            choices=choices,
            style=questionary.Style([
                ('selected', 'fg:#d70000 bold'),  # Red for selected items
                ('pointer', 'fg:#d70000 bold'),   # Red pointer
                ('highlighted', 'fg:#d70000'),    # Red highlighted
            ])
        ).ask()
        
        if selected is None:  # User cancelled
            sys.exit(0)
            
        # Return list of selected file URLs
        return selected

    # ------------------------------------------------------------------ runner
    def run(self) -> None:
        """Run the interactive FLAC downloader."""
        try:
            # Show welcome message
            questionary.print(
                "🎵 FLAC Scraper - Download high-quality music",
                style="bold fg:darkblue"
            )
            questionary.print(
                "Navigate folders and select files to download. "
                "Press Ctrl+C to exit at any time.\n",
                style="dim"
            )
            
            while True:
                # Let user choose a folder
                folder_path = self.choose_folder(self.root)
                
                # Let user select files to download
                file_hrefs = self.choose_files(folder_path)
                if not file_hrefs:
                    if questionary.confirm("No files selected. Try another folder?").ask():
                        continue
                    break
                
                # Confirm download
                if not questionary.confirm(
                    f"Download {len(file_hrefs)} file(s)?",
                    default=True
                ).ask():
                    continue
                
                # Download files
                out_root = Path("downloads")
                success_count = 0
                
                with tqdm(total=len(file_hrefs), desc="Downloading", unit="file") as pbar:
                    for href in file_hrefs:
                        try:
                            file_url = urljoin(self.base_url, href)
                            # Build local path: mirror server structure
                            local_path = out_root / unquote(href).lstrip("/")
                            
                            # Create parent directories if they don't exist
                            local_path.parent.mkdir(parents=True, exist_ok=True)
                            
                            # Skip if file already exists
                            if local_path.exists():
                                questionary.print(f"Skipping existing: {local_path}", style="yellow")
                                continue
                                
                            # Download the file
                            self._download(file_url, local_path)
                            success_count += 1
                            
                        except Exception as e:
                            questionary.print(
                                f"Error downloading {file_url}: {e}",
                                style="red"
                            )
                        
                        pbar.update(1)
                
                # Show download summary
                if success_count > 0:
                    questionary.print(
                        f"✓ Successfully downloaded {success_count} file(s)",
                        style="green"
                    )
                
                # Ask to continue or exit
                if not questionary.confirm("\nDownload more files?").ask():
                    break
                    
        except KeyboardInterrupt:
            questionary.print("\nOperation cancelled by user.", style="red")
        except Exception as e:
            questionary.print(f"\nAn error occurred: {e}", style="red")
            raise
        finally:
            questionary.print("\nThank you for using FLAC Scraper! 👋", style="bold")


def cli() -> None:
    scraper = MusicScraper()
    scraper.run()


if __name__ == "__main__":
    cli()