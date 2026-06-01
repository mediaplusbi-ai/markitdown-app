# MarkItDown Web App

A clean web interface for converting files to Markdown for use with Claude.

## Deploy to Render (free)

### Step 1 — Push to GitHub
1. Create a new repository on [github.com](https://github.com/new)
2. Upload all files from this folder to the repository

### Step 2 — Deploy on Render
1. Go to [render.com](https://render.com) and sign up (free)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub account and select the repository
4. Render will auto-detect the settings from `render.yaml`
5. Click **"Create Web Service"**
6. Wait ~3 minutes for the first deploy

### Step 3 — Share the URL
Render gives you a free URL like:
`https://markitdown-app.onrender.com`

Share that with anyone — no installation needed!

---

## Supported formats
PDF, DOCX, PPTX, XLSX, CSV, HTML, TXT, JSON, XML, EPUB, ZIP

## Notes
- Files are processed and immediately discarded (not stored)
- 50MB file size limit
- Free Render tier may sleep after 15min of inactivity (first load takes ~30s to wake up)
