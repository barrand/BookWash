#!/bin/bash
# Run BookWash Web Backend Locally

echo "🚀 Starting BookWash Web Backend..."
echo ""
echo "Make sure you have:"
echo "  1. Set GEMINI_API_KEY environment variable"
echo "  2. Built the Flutter web app: flutter build web --target lib/main_web.dart --release"
echo ""
echo "Backend will be available at: http://localhost:8000"
echo ""

cd "$(dirname "$0")"
python3 -m uvicorn webapp.app:app --reload --port 8000 --log-level warning
