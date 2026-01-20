#!/bin/bash
ts=$(TZ="America/Denver" date +"%m/%d/%y %I:%M%p MT" | sed -e 's/AM/am/' -e 's/PM/pm/')
flutter build web --target lib/main_web.dart --dart-define=BUILD_TIME="$ts" && \
lsof -ti:8000 | xargs kill -9 2>/dev/null; \
GEMINI_API_KEY="$GEMINI_API_KEY" python3 -m uvicorn webapp.app:app --reload --port 8000 --log-level warning
