# BookWash Web Backend

FastAPI backend for the BookWash web application.

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variable:
```bash
export GEMINI_API_KEY="your-api-key"
```

3. Run the server:
```bash
cd ..
uvicorn webapp.app:app --reload --port 8000
```

4. Build Flutter web (from project root):
```bash
flutter build web --target lib/main_web.dart --release
```

The server will serve the Flutter web app at http://localhost:8000

## Deployment (Render.com)

The app is configured for automatic deployment via `render.yaml` when you push to your main branch.

Required environment variables on Render:
- `GEMINI_API_KEY` - Your Gemini API key
- `APP_PASSWORD` - Optional password protection

## API Endpoints

- `POST /api/upload` - Upload EPUB file
- `POST /api/process/{session_id}` - Start processing
- `GET /api/session/{session_id}` - Get session status
- `GET /api/logs/{session_id}` - Get processing logs
- `POST /api/changes/{session_id}` - Accept/reject changes
- `POST /api/export/{session_id}` - Export cleaned EPUB
