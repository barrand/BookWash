"""
BookWash Web App - FastAPI backend for content moderation of EPUBs.
Deployed on Render with server-side Gemini API key.

Features:
- Live logging via Server-Sent Events (SSE)
- Session-based processing workflow
- Change review UI before export
"""

import os
import sys
import json
import uuid
import asyncio
import tempfile
import secrets
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware

# Add scripts directory to path for imports
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# Flutter web build path (relative to webapp directory)
FLUTTER_WEB_BUILD = Path(__file__).parent.parent / "build" / "web"

app = FastAPI(
    title="BookWash",
    description="Content moderation for EPUB books using AI",
    version="1.0.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage (for live logs and state)
sessions: Dict[str, Dict[str, Any]] = {}

# Basic auth security (optional)
security = HTTPBasic(auto_error=False)

def verify_credentials(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    """Verify basic auth credentials. Skip if APP_PASSWORD not set."""
    app_password = os.environ.get("APP_PASSWORD")
    
    if not app_password:
        return True
    
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    app_username = os.environ.get("APP_USERNAME", "bookwash")
    correct_username = secrets.compare_digest(credentials.username, app_username)
    correct_password = secrets.compare_digest(credentials.password, app_password)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


# Serve Flutter web build static files
if FLUTTER_WEB_BUILD.exists():
    app.mount("/assets", StaticFiles(directory=str(FLUTTER_WEB_BUILD / "assets")), name="assets")
    app.mount("/icons", StaticFiles(directory=str(FLUTTER_WEB_BUILD / "icons")), name="icons")

# Legacy static files (if Flutter build not available, fall back to webapp/static)
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(authenticated: bool = Depends(verify_credentials)):
    """Serve the main page - Flutter web build or fallback."""
    # Try Flutter web build first
    flutter_index = FLUTTER_WEB_BUILD / "index.html"
    if flutter_index.exists():
        return flutter_index.read_text()
    
    # Fall back to legacy static HTML
    legacy_index = Path(__file__).parent / "static" / "index.html"
    if legacy_index.exists():
        return legacy_index.read_text()
    
    return "<h1>BookWash - No frontend available. Run 'flutter build web --target lib/main_web.dart' first.</h1>"


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/upload")
async def upload_epub(
    file: UploadFile = File(...),
    authenticated: bool = Depends(verify_credentials)
):
    """
    Upload an EPUB file and create a processing session.
    Returns a session ID for subsequent operations.
    """
    if not file.filename.endswith('.epub'):
        raise HTTPException(status_code=400, detail="File must be an EPUB")
    
    # Create session
    session_id = str(uuid.uuid4())
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(exist_ok=True)
    
    # Save uploaded file
    epub_path = session_dir / file.filename
    with open(epub_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    # Initialize session state
    sessions[session_id] = {
        "id": session_id,
        "filename": file.filename,
        "epub_path": str(epub_path),
        "bookwash_path": None,
        "status": "uploaded",
        "logs": [],
        "progress": 0,
        "phase": "idle",
        "changes": [],
        "created": datetime.now().isoformat()
    }
    
    return {
        "session_id": session_id,
        "filename": file.filename,
        "status": "uploaded"
    }


@app.post("/api/process/{session_id}")
async def start_processing(
    session_id: str,
    background_tasks: BackgroundTasks,
    target_language: int = Form(2),
    target_adult: int = Form(2),
    target_violence: int = Form(3),
    model: str = Form("gemini-2.0-flash"),
    authenticated: bool = Depends(verify_credentials)
):
    """
    Start processing an uploaded EPUB. 
    Progress can be monitored via /api/logs/{session_id} SSE endpoint.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session["status"] not in ["uploaded", "error"]:
        raise HTTPException(status_code=400, detail=f"Cannot process session in {session['status']} state")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    # Update session state
    session["status"] = "processing"
    session["logs"] = []
    session["progress"] = 0
    session["phase"] = "converting"
    session["target_language"] = target_language
    session["target_adult"] = target_adult
    session["target_violence"] = target_violence
    session["model"] = model
    
    # Start background processing
    background_tasks.add_task(
        process_book_async,
        session_id,
        api_key,
        target_language,
        target_adult,
        target_violence,
        model
    )
    
    return {"status": "processing", "session_id": session_id}


async def process_book_async(
    session_id: str,
    api_key: str,
    target_language: int,
    target_adult: int,
    target_violence: int,
    model: str
):
    """Background task to process the book."""
    session = sessions.get(session_id)
    if not session:
        return
    
    def add_log(message: str):
        session["logs"].append({
            "time": datetime.now().isoformat(),
            "message": message
        })
    
    try:
        epub_path = Path(session["epub_path"])
        session_dir = epub_path.parent
        bookwash_path = session_dir / f"{epub_path.stem}.bookwash"
        
        add_log("📚 Starting BookWash processing...")
        add_log(f"📖 Input: {epub_path.name}")
        
        # Step 1: Convert EPUB to .bookwash
        add_log("")
        add_log("═══════════════════════════════════════════")
        add_log("📝 Step 1: Converting EPUB to .bookwash format...")
        add_log("═══════════════════════════════════════════")
        session["phase"] = "converting"
        session["progress"] = 5
        
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "epub_to_bookwash.py"),
             str(epub_path), str(bookwash_path)],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode != 0:
            raise Exception(f"EPUB conversion failed: {result.stderr}")
        
        add_log("✅ EPUB converted to .bookwash format")
        session["bookwash_path"] = str(bookwash_path)
        
        # Step 2: Rate and clean with LLM
        add_log("")
        add_log("═══════════════════════════════════════════")
        add_log("🤖 Step 2: Rating and cleaning content with AI...")
        add_log("═══════════════════════════════════════════")
        
        rating_names = {1: "G", 2: "PG", 3: "PG-13", 4: "R", 5: "Unrated"}
        add_log(f"Target levels: Language={rating_names.get(target_language, 'PG')}, "
                f"Adult={rating_names.get(target_adult, 'PG')}, "
                f"Violence={rating_names.get(target_violence, 'PG-13')}")
        
        session["phase"] = "rating"
        session["progress"] = 10
        
        # Run the LLM script and capture output line by line
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = api_key
        env["PYTHONUNBUFFERED"] = "1"
        
        process = subprocess.Popen(
            [sys.executable, "-u", str(SCRIPTS_DIR / "bookwash_llm.py"),
             "--rate", "--clean",
             "--language", str(target_language),
             "--sexual", str(target_adult),
             "--violence", str(target_violence),
             "--model", model,
             str(bookwash_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        
        # Stream output to logs
        for line in process.stdout:
            line = line.rstrip()
            if line:
                add_log(line)
                
                # Parse progress from output
                if "[" in line and "/" in line and "]" in line:
                    try:
                        match = line.split("[")[1].split("]")[0]
                        current, total = match.split("/")
                        progress_pct = int(current) / int(total)
                        if "Rating" in session.get("phase", "") or session["progress"] < 50:
                            session["phase"] = "rating"
                            session["progress"] = 10 + int(progress_pct * 40)
                        else:
                            session["phase"] = "cleaning"
                            session["progress"] = 50 + int(progress_pct * 45)
                    except:
                        pass
                
                if "Cleaning" in line and "chapters" in line:
                    session["phase"] = "cleaning"
                    session["progress"] = 50
                elif "No chapters need cleaning" in line:
                    session["phase"] = "cleaning"
                    session["progress"] = 95
        
        process.wait()
        
        if process.returncode != 0:
            raise Exception("LLM processing failed")
        
        add_log("✅ Content rated and cleaned")
        session["progress"] = 95
        
        # Step 3: Parse the bookwash file to extract changes
        add_log("")
        add_log("═══════════════════════════════════════════")
        add_log("📋 Step 3: Extracting changes for review...")
        add_log("═══════════════════════════════════════════")
        
        changes = parse_bookwash_changes(str(bookwash_path))
        session["changes"] = changes
        
        pending_count = len([c for c in changes if c.get("status") == "pending"])
        add_log(f"✅ Found {pending_count} pending changes to review")
        
        session["progress"] = 100
        session["phase"] = "complete"
        session["status"] = "review"
        
        add_log("")
        add_log("═══════════════════════════════════════════")
        add_log("🎉 Processing complete!")
        add_log("═══════════════════════════════════════════")
        add_log("Review changes below, then export when ready.")
        
    except Exception as e:
        add_log(f"❌ Error: {str(e)}")
        session["status"] = "error"
        session["error"] = str(e)


def parse_bookwash_changes(bookwash_path: str) -> list:
    """Parse a .bookwash file and extract all changes."""
    changes = []
    
    with open(bookwash_path, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    current_chapter = None
    current_chapter_title = ""
    current_change = None
    in_original = False
    in_cleaned = False
    original_lines = []
    cleaned_lines = []
    
    for line in lines:
        if line.startswith('#CHAPTER:'):
            current_chapter = int(line.split(':')[1].strip())
            current_chapter_title = ""
        elif line.startswith('#TITLE:') and current_chapter is not None:
            current_chapter_title = line.split(':', 1)[1].strip()
        elif line.startswith('#CHANGE:'):
            # Save previous change
            if current_change is not None:
                current_change["original"] = '\n'.join(original_lines)
                current_change["cleaned"] = '\n'.join(cleaned_lines)
                changes.append(current_change)
            
            change_id = line.split(':')[1].strip()
            current_change = {
                "id": change_id,
                "chapter": current_chapter,
                "chapter_title": current_chapter_title,
                "status": "pending",
                "reason": "",
                "original": "",
                "cleaned": ""
            }
            in_original = False
            in_cleaned = False
            original_lines = []
            cleaned_lines = []
        elif current_change is not None:
            if line.startswith('#STATUS:'):
                current_change["status"] = line.split(':')[1].strip()
            elif line.startswith('#REASON:'):
                current_change["reason"] = line.split(':', 1)[1].strip()
            elif line.strip() == '#ORIGINAL':
                in_original = True
                in_cleaned = False
            elif line.strip() == '#CLEANED':
                in_original = False
                in_cleaned = True
            elif line.strip() == '#END':
                current_change["original"] = '\n'.join(original_lines)
                current_change["cleaned"] = '\n'.join(cleaned_lines)
                changes.append(current_change)
                current_change = None
                in_original = False
                in_cleaned = False
                original_lines = []
                cleaned_lines = []
            elif in_original:
                original_lines.append(line)
            elif in_cleaned:
                cleaned_lines.append(line)
    
    # Handle last change if file doesn't end with #END
    if current_change is not None:
        current_change["original"] = '\n'.join(original_lines)
        current_change["cleaned"] = '\n'.join(cleaned_lines)
        changes.append(current_change)
    
    return changes


@app.get("/api/logs/{session_id}")
async def stream_logs(session_id: str):
    """
    Stream logs for a session using Server-Sent Events (SSE).
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    async def event_generator():
        last_log_count = 0
        
        while True:
            session = sessions.get(session_id)
            if not session:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Session expired'})}\n\n"
                break
            
            # Send new logs
            current_logs = session.get("logs", [])
            if len(current_logs) > last_log_count:
                for log in current_logs[last_log_count:]:
                    yield f"data: {json.dumps({'type': 'log', 'log': log})}\n\n"
                last_log_count = len(current_logs)
            
            # Send status update
            yield f"data: {json.dumps({'type': 'status', 'status': session['status'], 'progress': session.get('progress', 0), 'phase': session.get('phase', '')})}\n\n"
            
            # Stop if processing is complete or errored
            if session["status"] in ["review", "complete", "error"]:
                yield f"data: {json.dumps({'type': 'done', 'status': session['status']})}\n\n"
                break
            
            await asyncio.sleep(0.5)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/session/{session_id}")
async def get_session(
    session_id: str,
    authenticated: bool = Depends(verify_credentials)
):
    """Get the current state of a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return {
        "id": session["id"],
        "filename": session["filename"],
        "status": session["status"],
        "progress": session.get("progress", 0),
        "phase": session.get("phase", ""),
        "changes": session.get("changes", []),
        "logs": session.get("logs", [])
    }


@app.post("/api/session/{session_id}/change/{change_id}")
async def update_change(
    session_id: str,
    change_id: str,
    status: str = Form(...),
    authenticated: bool = Depends(verify_credentials)
):
    """Accept or reject a specific change."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if status not in ["accepted", "rejected"]:
        raise HTTPException(status_code=400, detail="Status must be 'accepted' or 'rejected'")
    
    session = sessions[session_id]
    
    # Update change in session
    for change in session.get("changes", []):
        if change["id"] == change_id:
            change["status"] = status
            break
    
    # Update the actual bookwash file
    if session.get("bookwash_path"):
        update_bookwash_change_status(session["bookwash_path"], change_id, status)
    
    return {"status": "updated", "change_id": change_id, "new_status": status}


@app.post("/api/session/{session_id}/accept-all")
async def accept_all_changes(
    session_id: str,
    authenticated: bool = Depends(verify_credentials)
):
    """Accept all pending changes."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    count = 0
    
    for change in session.get("changes", []):
        if change["status"] == "pending":
            change["status"] = "accepted"
            count += 1
            if session.get("bookwash_path"):
                update_bookwash_change_status(session["bookwash_path"], change["id"], "accepted")
    
    return {"status": "updated", "accepted_count": count}


def update_bookwash_change_status(bookwash_path: str, change_id: str, new_status: str):
    """Update a change's status in the bookwash file."""
    with open(bookwash_path, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    new_lines = []
    found_change = False
    
    for i, line in enumerate(lines):
        if line.startswith(f'#CHANGE: {change_id}'):
            found_change = True
        elif found_change and line.startswith('#STATUS:'):
            line = f'#STATUS: {new_status}'
            found_change = False
        new_lines.append(line)
    
    with open(bookwash_path, 'w') as f:
        f.write('\n'.join(new_lines))


@app.post("/api/session/{session_id}/export")
async def export_epub(
    session_id: str,
    authenticated: bool = Depends(verify_credentials)
):
    """Export the processed book as an EPUB."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if not session.get("bookwash_path"):
        raise HTTPException(status_code=400, detail="No processed bookwash file")
    
    bookwash_path = Path(session["bookwash_path"])
    epub_path = Path(session["epub_path"])
    output_path = bookwash_path.parent / f"{epub_path.stem}_cleaned.epub"
    
    # Run bookwash_to_epub
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "bookwash_to_epub.py"),
         str(bookwash_path), "-o", str(output_path)],
        capture_output=True, text=True, timeout=120
    )
    
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Export failed: {result.stderr}")
    
    # Read the file
    with open(output_path, 'rb') as f:
        epub_content = f.read()
    
    session["status"] = "complete"
    
    return Response(
        content=epub_content,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f"attachment; filename={epub_path.stem}_cleaned.epub"}
    )


@app.delete("/api/session/{session_id}")
async def delete_session(
    session_id: str,
    authenticated: bool = Depends(verify_credentials)
):
    """Clean up a session and its files."""
    if session_id in sessions:
        session = sessions[session_id]
        
        # Clean up files
        if session.get("epub_path"):
            session_dir = Path(session["epub_path"]).parent
            if session_dir.exists() and session_dir.parent == SESSIONS_DIR:
                shutil.rmtree(session_dir, ignore_errors=True)
        
        del sessions[session_id]
    
    return {"status": "deleted"}


# Legacy endpoint for simple one-shot processing (no live logs)
@app.post("/api/process")
async def process_epub_simple(
    file: UploadFile = File(...),
    target_language: int = Form(2),
    target_adult: int = Form(2),
    target_violence: int = Form(3),
    model: str = Form("gemini-2.0-flash"),
    authenticated: bool = Depends(verify_credentials)
):
    """
    Simple one-shot processing (legacy endpoint).
    For live logs and review UI, use /api/upload + /api/process/{session_id}.
    """
    if not file.filename.endswith('.epub'):
        raise HTTPException(status_code=400, detail="File must be an EPUB")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        epub_path = temp_path / file.filename
        with open(epub_path, 'wb') as f:
            content = await file.read()
            f.write(content)
        
        bookwash_path = temp_path / f"{epub_path.stem}.bookwash"
        
        # Convert
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "epub_to_bookwash.py"),
             str(epub_path), str(bookwash_path)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Conversion failed: {result.stderr}")
        
        # Process
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = api_key
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "bookwash_llm.py"),
             "--rate", "--clean",
             "--language", str(target_language),
             "--sexual", str(target_adult),
             "--violence", str(target_violence),
             "--model", model,
             str(bookwash_path)],
            capture_output=True, text=True, timeout=600, env=env
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Processing failed: {result.stderr}")
        
        # Export
        output_path = temp_path / f"{epub_path.stem}_cleaned.epub"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "bookwash_to_epub.py"),
             str(bookwash_path), "-o", str(output_path)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Export failed: {result.stderr}")
        
        with open(output_path, 'rb') as f:
            epub_content = f.read()
        
        return Response(
            content=epub_content,
            media_type="application/epub+zip",
            headers={"Content-Disposition": f"attachment; filename={epub_path.stem}_cleaned.epub"}
        )


# Serve Flutter web files (main.dart.js, manifest.json, etc.)
# IMPORTANT: This must be the LAST route to avoid catching API routes
@app.get("/{filename:path}")
async def serve_flutter_file(filename: str, authenticated: bool = Depends(verify_credentials)):
    """Serve Flutter web build files."""
    # API routes are handled by specific endpoints above
    if filename.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    
    file_path = FLUTTER_WEB_BUILD / filename
    if file_path.exists() and file_path.is_file():
        # Determine content type
        content_type = "application/octet-stream"
        if filename.endswith(".js"):
            content_type = "application/javascript"
        elif filename.endswith(".json"):
            content_type = "application/json"
        elif filename.endswith(".png"):
            content_type = "image/png"
        elif filename.endswith(".ico"):
            content_type = "image/x-icon"
        elif filename.endswith(".woff2"):
            content_type = "font/woff2"
        elif filename.endswith(".woff"):
            content_type = "font/woff"
        
        return Response(content=file_path.read_bytes(), media_type=content_type)
    
    # For SPA routing, return index.html for non-file routes
    flutter_index = FLUTTER_WEB_BUILD / "index.html"
    if flutter_index.exists():
        return HTMLResponse(content=flutter_index.read_text())
    
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
