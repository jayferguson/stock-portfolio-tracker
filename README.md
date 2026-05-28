# Portfolio Tracker

A sleek, fully self-contained stock portfolio tracker that runs 100% in the browser. No server, no install — just open the HTML file.

**Standout feature**: Automatic price updates are **paused outside regular US market hours** (9:30 AM – 4:00 PM ET, Monday–Friday). The header pill clearly shows current market status.

## Features

- Beautiful dark modern UI built with Tailwind
- Import holdings directly from Excel (.xlsx) or CSV
- Add, edit, delete positions with live recalculation
- Real-time or delayed price updates
- **Market-hours intelligent auto-refresh**
- Today's P/L, best/worst movers
- Sortable table + search + export to Excel
- Everything persisted in browser localStorage
- Keyboard shortcuts (`/` search, Ctrl/Cmd+R refresh)

## Market Hours Behavior

The app only performs background price fetches during active NYSE/NASDAQ regular trading hours:

- Weekdays only
- 9:30 AM – 4:00 PM Eastern Time

Outside hours (pre-market, after-hours, weekends) it shows a clear status message and skips automatic updates. Manual refresh still works anytime.

## Quick Start

### Run locally
1. Download `index.html`
2. Open it in Chrome, Firefox, Edge, etc.

### GitHub Pages (best experience)
1. Go to repository **Settings → Pages**
2. Source: Deploy from `main` branch, root folder
3. Visit: `https://jayferguson.github.io/stock-portfolio-tracker`

## Optional: Real-time Prices

For near-instant US quotes:

1. Sign up for a free key at [finnhub.io/register](https://finnhub.io/register)
2. In the app, click **API Settings**
3. Paste your key

The app will prefer Finnhub when available and gracefully fall back to the public feed.

## Tech Stack

- Single HTML file (no build step)
- Tailwind CSS (CDN)
- SheetJS (xlsx) for import/export
- Vanilla JS + Fetch
- Finnhub API + custom public market data endpoint

## License

MIT License — free to use and modify.