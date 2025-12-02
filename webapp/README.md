# BookWash Web App

A web interface for BookWash - AI-powered content moderation for EPUB books.

## Local Development

1. Install dependencies:
```bash
pip install -r webapp/requirements.txt
```

2. Set environment variables:
```bash
export GEMINI_API_KEY="your-api-key-here"
export APP_PASSWORD="your-password"  # Optional: for basic auth
```

3. Run the server:
```bash
cd webapp
uvicorn app:app --reload
```

4. Open http://localhost:8000

## Deploy to Render

### Option 1: Via Render Dashboard

1. Go to [render.com](https://render.com) and create an account
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: bookwash
   - **Root Directory**: (leave empty)
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r webapp/requirements.txt`
   - **Start Command**: `cd webapp && uvicorn app:app --host 0.0.0.0 --port $PORT`

5. Add Environment Variables:
   - `GEMINI_API_KEY`: Your Google Gemini API key
   - `APP_PASSWORD`: Password for basic auth (optional)
   - `APP_USERNAME`: Username for basic auth (default: "bookwash")

6. Click "Create Web Service"

### Option 2: Via render.yaml (Blueprint)

The repo includes a `render.yaml` file. Just:
1. Push to GitHub
2. Go to Render Dashboard → Blueprints → New Blueprint Instance
3. Connect your repo
4. Add the environment variables when prompted

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Your Google Gemini API key |
| `APP_PASSWORD` | No | Password for basic auth (if not set, no auth required) |
| `APP_USERNAME` | No | Username for basic auth (default: "bookwash") |

## API Endpoints

- `GET /` - Web interface
- `GET /api/health` - Health check
- `GET /api/rating-levels` - Get available rating levels
- `POST /api/rate-only` - Rate an EPUB without cleaning
- `POST /api/process` - Full pipeline: rate, clean, and return cleaned EPUB

## Security

- Your Gemini API key is stored on the server and never exposed to users
- Basic auth protects the app from unauthorized access
- Files are processed in temporary directories and deleted after processing
