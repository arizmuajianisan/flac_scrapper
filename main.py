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
from typing import List
from urllib.parse import urljoin, unquote

import questionary
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from playwright.sync_api import sync_playwright, Error as PWError


BASE_URL = "https://server.elscione.com"
ROOT_PATH = "/Music/"
CHUNK = 1024 * 1024  # 1 MB


class MusicScraper:
    def __init__(self, base_url: str = BASE_URL, root: str = ROOT_PATH) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}
        )
        self.base_url = base_url.rstrip("/")
        self.root = root

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
    def list_folders(self, path: str) -> List[tuple[str, str]]:
        soup = self._soup(path)
        # ----  DEBUG: write raw HTML to disk  ----
        Path("debug.html").write_text(str(soup), encoding="utf-8")
        # -----------------------------------------
        folders = []
        for li in soup.select("li.item.folder a"):
            href = li["href"]
            name = li.select_one("span.label").get_text(strip=True)
            folders.append((name, href))
        return folders

    def list_flac_files(self, path: str) -> List[tuple[str, str]]:
        soup = self._soup(path)
        files = []
        for li in soup.select("li.item.file a"):
            href = li["href"]
            name = li.select_one("span.label").get_text(strip=True)
            if name.lower().endswith(".flac"):
                files.append((name, href))
        return files

    # -------------------------------------------------------------- interactive
    def choose_folder(self, path: str) -> str:
        while True:
            folders = self.list_folders(path)
            if not folders:
                questionary.print("No sub-folders here.")
                return path
            choices = ["📁 " + name for name, _ in folders] + ["⬇️  Download from current folder"]
            choice = questionary.select("Select folder:", choices=choices).ask()
            if choice is None:
                sys.exit(0)
            if choice.startswith("⬇️"):
                return path
            # descend
            name = choice[2:]
            _, href = next((n, h) for n, h in folders if n == name)
            path = href

    def choose_files(self, path: str) -> List[str]:
        files = self.list_flac_files(path)
        if not files:
            questionary.print("No FLAC files in this folder.")
            return []
        names = [n for n, _ in files]
        choices = questionary.checkbox(
            "Select FLAC files (space to toggle, enter to confirm):", choices=names
        ).ask()
        if choices is None:
            sys.exit(0)
        return [href for name, href in files if name in choices]

    # ------------------------------------------------------------------ runner
    def run(self) -> None:
        folder_path = self.choose_folder(self.root)
        file_hrefs = self.choose_files(folder_path)
        if not file_hrefs:
            questionary.print("Nothing selected – exiting.")
            return

        out_root = Path("downloads")
        for href in file_hrefs:
            file_url = urljoin(self.base_url, href)
            # build local path: mirror server structure
            local_path = out_root / unquote(href).lstrip("/")
            if local_path.exists():
                questionary.print(f"Skipping existing: {local_path}")
                continue
            self._download(file_url, local_path)
        questionary.print("All done ✅")


def cli() -> None:
    scraper = MusicScraper()
    scraper.run()


if __name__ == "__main__":
    cli()