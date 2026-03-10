# Nexus - Browser Extension

A Chrome extension that lets you save job listings directly from supported job sites to your Nexus dashboard.

## Features

- One-click saving of job listings from supported sites
- Automatic extraction of job title, company, location, and description
- Floating "Save to Nexus" button on matching pages
- Quick access to your dashboard from the popup

## Supported Job Sites

- LinkedIn (`linkedin.com/jobs/*`)
- Indeed (`indeed.com`)
- Glassdoor (`glassdoor.com/job-listing/*`)
- Greenhouse (`greenhouse.io`)
- Lever (`lever.co`)
- Dice (`dice.com`)
- Wellfound / AngelList (`wellfound.com`, `angel.co`)
- RemoteOK (`remoteok.com`, `remoteok.io`)
- BuiltIn (`builtin.com`)
- SimplyHired (`simplyhired.com`)
- ZipRecruiter (`ziprecruiter.com`)

## Installation

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in the top-right corner)
3. Click **Load unpacked**
4. Select the `browser-extension` directory
5. The extension icon will appear in your toolbar

**Note:** You will need to add icon PNG files (16x16, 48x48, 128x128) to the `icons/` directory. See `icons/README.md` for details.

## Configuration

1. Click the extension icon in the Chrome toolbar
2. Enter your Nexus server URL (e.g., `http://localhost:5000`)
3. The URL is saved automatically

## Usage

- **From the popup:** Click "Save Current Job" while viewing a job listing to extract and save it
- **From the page:** Click the floating "Save to Nexus" button that appears on supported sites
- **Open Dashboard:** Click "Open Dashboard" in the popup to jump to your Nexus dashboard
