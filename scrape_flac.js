const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const CLIProgress = require('cli-progress');
require('dotenv').config();

// URL of the webpage to scrape
const URL = process.env.FLAC_URL;
const DOWNLOAD_DIR = process.env.DOWNLOAD_DIR;

// Create download directory if it doesn't exist
const createDirectory = (dir) => {
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
};

createDirectory(DOWNLOAD_DIR);

// Function to sanitize filenames by decoding percent-encoded characters and cleaning up special characters
const sanitizeFilename = (name) => {
    try {
        // Extract just the filename from the full path
        const filename = name.split('/').pop();
        // Decode percent-encoded characters
        let decoded = decodeURIComponent(filename);
        // Replace spaces with underscores and remove other special characters
        return decoded
            .replace(/[^\w\s.-]/g, '') // Remove special characters
            .replace(/\s+/g, ' ') // Replace multiple spaces with single space
            .trim() // Trim whitespace
            .replace(/\s/g, '_'); // Replace remaining spaces with underscores
    } catch (e) {
        // Fallback to original name if there's an error
        console.warn(`Error sanitizing filename ${name}:`, e.message);
        return name
            .split('/')
            .pop()
            .replace(/[^\w\s.-]/g, '_');
    }
};

// Function to download files using axios with progress
const downloadFileWithAxios = async (url, filename) => {
    try {
        console.log(`\nDownloading with Axios: ${url}`);

        // Get the total file size
        const headResponse = await axios.head(url, {
            headers: {
                'User-Agent':
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                Referer: URL
            }
        });

        const totalBytes = parseInt(headResponse.headers['content-length'], 10);
        let downloadedBytes = 0;

        // Initialize progress bar
        const progressBar = new CLIProgress.SingleBar(
            {
                format: `Downloading {filename} |{bar}| ETA: {eta}s -- {duration}s | {percentage}%`,
                clearOnComplete: true
            },
            CLIProgress.Presets.shades_classic
        );

        progressBar.start(totalBytes, 0, {
            filename: sanitizeFilename(path.basename(filename))
        });

        const response = await axios.get(url, {
            responseType: 'stream',
            headers: {
                'User-Agent':
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                Referer: URL
            }
        });

        const writer = fs.createWriteStream(filename);
        response.data.pipe(writer);

        response.data.on('data', (chunk) => {
            downloadedBytes += chunk.length;
            progressBar.update(downloadedBytes);
        });

        return new Promise((resolve, reject) => {
            writer.on('finish', () => {
                progressBar.stop();
                console.log(`Downloaded: ${sanitizeFilename(filename)}`);
                resolve();
            });
            writer.on('error', reject);
        });
    } catch (error) {
        console.error(
            `Failed to download with Axios: ${url} (Error: ${error.message})`
        );
    }
};

(async () => {
    const browser = await puppeteer.launch({
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu'
        ]
    });
    const page = await browser.newPage();

    // Set headers to mimic a browser request
    await page.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    );

    console.log(`Navigating to: ${URL}`);
    await page.goto(URL, { waitUntil: 'networkidle2' });

    // Get all .flac links
    const links = await page.evaluate(() => {
        const anchors = Array.from(document.querySelectorAll('a'));
        return anchors
            .map((a) => a.href)
            .filter((href) => href.endsWith('.flac'));
    });

    console.log(`Found ${links.length} .flac links`);

    // Download each file
    for (const link of links) {
        const originalFilename = path.join(DOWNLOAD_DIR, path.basename(link));
        const sanitizedFilename = sanitizeFilename(originalFilename);
        await downloadFileWithAxios(link, sanitizedFilename);
    }

    await browser.close();
})();
