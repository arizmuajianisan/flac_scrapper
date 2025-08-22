# Flac Scrapper

This tool is used to download audio files from certain websites.
It uses Puppeteer for web automation and Axios for file downloads.

## Prerequisites

### System Dependencies
Make sure these are installed on your system:

For Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install -y libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libxkbcommon-x11-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64
```

For other Linux distributions, install the equivalent packages.

## Installation

1. Clone this project

2. Install the Node.js dependencies:
```bash
npm install
```

3. Edit the .env, that will be used to store the target URL and folder downloaded
```bash
FLAC_URL="your-target-url"
DOWNLOAD_DIR=your/path/to/download
```

4. Run the script
```bash
node scrape_flac.js
```

5. The files will be downloaded and saved into the target folder

## Usage Example

I found the site that had collection of audio files and I'm going to download them using my script.

First, change the .env
```bash
FLAC_URL="https://server.elscione.com/Music/Arctic%20Monkeys%20-%20AM/"
DOWNLOAD_DIR=flac_files/Arctic Monkeys - 20AM/
```

That's it! Then you need to run the script.
And the folder will be generated automatically.