# Flac Scrapper

This tools is used to download the file audio from certain web.
Using Puppeteer to handle the automation and interaction with the page.
Also using Axios for downloading the files.

## How To Use
1. Clone this project

2. Install the independency package
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