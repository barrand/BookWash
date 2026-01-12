"""
BookWash Web API Server

FastAPI backend that wraps the Python scripts and provides a REST API
for the Flutter web frontend.
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import StreamingResponse as SSEStreamingResponse
import queue
import threading

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

# Import bookwash_llm for parsing
import bookwash_llm

app = FastAPI(title="BookWash API", version="1.0.0")

# CORS middleware for Flutter web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sessions storage
SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
sessions: Dict[str, dict] = {}


# Pydantic models
class ProcessRequest(BaseModel):
    language_words: List[str] = []
    adult_level: int = 2
    violence_level: int = 3
    model: str = "gemini-2.0-flash"


class ChangeAction(BaseModel):
    change_id: str
    action: str  # 'accept' or 'reject'
    edited_text: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    status: str
    filename: str
    progress: float = 0.0
    phase: str = ""
    changes: List[dict] = []
    logs: List[dict] = []


# Helper functions
def get_session_path(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def save_session(session_id: str, data: dict):
    session_path = get_session_path(session_id)
    session_path.mkdir(exist_ok=True)
    with open(session_path / "session.json", "w") as f:
        json.dump(data, f)
    sessions[session_id] = data


def load_session(session_id: str) -> Optional[dict]:
    if session_id in sessions:
        return sessions[session_id]
    
    session_path = get_session_path(session_id)
    session_file = session_path / "session.json"
    if session_file.exists():
        with open(session_file) as f:
            data = json.load(f)
            sessions[session_id] = data
            return data
    return None


async def log_message(session_id: str, message: str):
    """Add a log message to the session"""
    session = load_session(session_id)
    if session:
        if "logs" not in session:
            session["logs"] = []
        session["logs"].append({
            "timestamp": datetime.now().isoformat(),
            "message": message
        })
        save_session(session_id, session)


async def process_book(session_id: str, epub_path: Path, request: ProcessRequest):
    """Background task to process the book"""
    print(f"\n=== PROCESS_BOOK BACKGROUND TASK STARTED ===")
    print(f"Session: {session_id}, File: {epub_path.name}")
    try:
        session = load_session(session_id)
        session["status"] = "processing"
        session["phase"] = "converting"
        session["progress"] = 0
        save_session(session_id, session)
        print(f"Phase: converting, Progress: 0%")
        
        await log_message(session_id, "📚 Converting EPUB to BookWash format...")
        
        # Convert EPUB to BookWash using subprocess
        bookwash_path = get_session_path(session_id) / f"{epub_path.stem}.bookwash"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "epub_to_bookwash.py"), str(epub_path), str(bookwash_path)],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise ValueError(f"EPUB conversion failed: {result.stderr}")
        
        # Parse the created bookwash file
        bw = bookwash_llm.parse_bookwash(bookwash_path)
        
        session["progress"] = 10
        save_session(session_id, session)
        
        await log_message(session_id, f"✅ Converted to BookWash format ({len(bw.chapters)} chapters)")
        
        # Get API key
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        # Build language words and filter types for command line
        language_words = request.language_words if request.language_words else []
        filter_types = []
        if language_words:
            filter_types.append("language")
        if request.adult_level < 4:
            filter_types.append("sexual")
        if request.violence_level < 4:
            filter_types.append("violence")
        
        filter_types_str = ",".join(filter_types) if filter_types else "sexual,violence"
        
        # Rate and clean using Python subprocess to capture all output
        await log_message(session_id, "🤖 Starting AI processing...")
        
        session["phase"] = "rating"
        session["progress"] = 20
        save_session(session_id, session)
        
        # Build the command - run bookwash_llm.py as subprocess
        language_words_json = json.dumps(language_words)
        cmd = [
            sys.executable,
            '-u',  # Unbuffered output
            str(SCRIPT_DIR / "bookwash_llm.py"),
            '--rate',
            '--clean-passes',
            str(bookwash_path),
            '--api-key', api_key,
            '--model', request.model,
            '--language-words', language_words_json,
            '--filter-types', filter_types_str,
            '--sexual', str(request.adult_level),
            '--violence', str(request.violence_level),
        ]
        
        # Run subprocess and stream output
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )
        
        # Stream stdout
        async def stream_stdout():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode().rstrip()
                if text:  # Only log non-empty lines
                    await log_message(session_id, text)
                    
                    # Parse phase from log lines (similar to macOS app)
                    if 'PASS A: Rating' in text or 'Starting rating' in text:
                        session["phase"] = "rating"
                        session["progress"] = 20
                        save_session(session_id, session)
                    elif 'CLEANING PIPELINE:' in text:
                        session["phase"] = "cleaning"
                        session["progress"] = 50
                        save_session(session_id, session)
                    elif 'VERIFYING CLEANED CONTENT' in text:
                        session["progress"] = 85
                        save_session(session_id, session)
        
        # Stream stderr
        async def stream_stderr():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                text = line.decode().rstrip()
                if text:
                    await log_message(session_id, f"⚠️ {text}")
        
        # Wait for both streams
        await asyncio.gather(stream_stdout(), stream_stderr())
        await process.wait()
        
        if process.returncode != 0:
            raise ValueError(f"LLM processing failed with code {process.returncode}")
        
        await log_message(session_id, "✅ AI processing complete")
        print("Processing complete, extracting changes...")
        
        # Re-parse the bookwash file after subprocess completed
        bw = bookwash_llm.parse_bookwash(bookwash_path)
        
        # Extract changes for review (parse #CHANGE blocks from content)
        changes = []
        for chapter in bw.chapters:
            # Parse change blocks from content_lines
            in_change = False
            change_id = None
            change_reason = "Content modification"
            change_original = []
            change_cleaned = []
            in_original = False
            in_cleaned = False
            
            for line in chapter.content_lines:
                if line.startswith('#CHANGE:'):
                    in_change = True
                    change_id = line.replace('#CHANGE:', '').strip()
                    change_reason = "Content modification"
                    change_original = []
                    change_cleaned = []
                    in_original = False
                    in_cleaned = False
                elif line.startswith('#REASON:') and in_change:
                    change_reason = line.replace('#REASON:', '').strip()
                elif line == '#END' and in_change:
                    # Save this change
                    changes.append({
                        "id": change_id,
                        "chapter": chapter.number,
                        "chapter_title": chapter.title or f"Chapter {chapter.number}",
                        "original": '\n'.join(change_original),
                        "cleaned": '\n'.join(change_cleaned),
                        "reason": change_reason,
                        "status": "pending"
                    })
                    in_change = False
                elif in_change:
                    if line == '#ORIGINAL':
                        in_original = True
                        in_cleaned = False
                    elif line == '#CLEANED':
                        in_original = False
                        in_cleaned = True
                    elif in_original:
                        change_original.append(line)
                    elif in_cleaned:
                        change_cleaned.append(line)
        
        session["status"] = "review"
        session["phase"] = "complete"
        session["progress"] = 100
        session["changes"] = changes
        session["bookwash_path"] = str(bookwash_path)
        save_session(session_id, session)
        print(f"\n=== PROCESSING COMPLETE ===")
        print(f"Status: review, Changes: {len(changes)}")
        print(f"Session saved successfully\n")
        
        await log_message(session_id, f"✅ Processing complete! {len(changes)} changes to review.")
        
    except Exception as e:
        print(f"\n=== ERROR IN PROCESS_BOOK ===")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        session = load_session(session_id)
        session["status"] = "error"
        session["error"] = str(e)
        save_session(session_id, session)
        await log_message(session_id, f"❌ Error: {str(e)}")


# API Routes
@app.get("/api")
async def api_root():
    return {"message": "BookWash API", "version": "1.0.0"}


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
) -> SessionResponse:
    """Upload an EPUB file and create a processing session"""
    
    if not file.filename.endswith('.epub'):
        raise HTTPException(status_code=400, detail="Only EPUB files are supported")
    
    # Create session
    session_id = str(uuid.uuid4())
    session_path = get_session_path(session_id)
    session_path.mkdir(exist_ok=True)
    
    # Save uploaded file
    epub_path = session_path / file.filename
    with open(epub_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Create session
    session = {
        "session_id": session_id,
        "status": "created",
        "filename": file.filename,
        "epub_path": str(epub_path),
        "created_at": datetime.now().isoformat(),
        "logs": []
    }
    save_session(session_id, session)
    
    return SessionResponse(**session)


@app.post("/api/process/{session_id}")
async def start_processing(
    session_id: str,
    request: ProcessRequest,
    background_tasks: BackgroundTasks
):
    """Start processing a session"""
    print(f"\n=== START PROCESSING CALLED ===")
    print(f"Session ID: {session_id}")
    print(f"Request: adult={request.adult_level}, violence={request.violence_level}, model={request.model}")
    print(f"Language words: {request.language_words}")
    
    session = load_session(session_id)
    if not session:
        print(f"ERROR: Session {session_id} not found")
        raise HTTPException(status_code=404, detail="Session not found")
    
    epub_path = Path(session["epub_path"])
    if not epub_path.exists():
        print(f"ERROR: EPUB not found at {epub_path}")
        raise HTTPException(status_code=404, detail="EPUB file not found")
    
    print(f"Starting background task for {epub_path.name}")
    # Start background processing
    background_tasks.add_task(process_book, session_id, epub_path, request)
    
    session["status"] = "processing"
    session["phase"] = "converting"  # Set initial phase
    session["progress"] = 0
    save_session(session_id, session)
    print(f"Session status set to 'processing', returning response")
    
    return {"message": "Processing started", "session_id": session_id}


@app.get("/api/session/{session_id}/stream")
async def stream_session(session_id: str):
    """Stream session updates via Server-Sent Events"""
    
    async def event_generator():
        """Generate SSE events for session updates"""
        last_log_count = 0
        last_status = None
        
        while True:
            session = load_session(session_id)
            if not session:
                yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
                break
            
            # Send status update if changed
            current_status = {
                'status': session.get('status'),
                'phase': session.get('phase', ''),
                'progress': session.get('progress', 0)
            }
            
            if current_status != last_status:
                yield f"data: {json.dumps({'type': 'status', **current_status})}\n\n"
                last_status = current_status
            
            # Send new log messages
            logs = session.get('logs', [])
            if len(logs) > last_log_count:
                for log in logs[last_log_count:]:
                    yield f"data: {json.dumps({'type': 'log', 'message': log['message']})}\n\n"
                last_log_count = len(logs)
            
            # Stop streaming if processing is complete
            if session.get('status') in ['review', 'complete', 'error']:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            
            await asyncio.sleep(0.1)  # Poll every 100ms
    
    return SSEStreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/session/{session_id}")
async def get_session(session_id: str) -> SessionResponse:
    """Get session status"""
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    print(f"GET /api/session/{session_id}: status={session.get('status')}, changes={len(session.get('changes', []))}, logs={len(session.get('logs', []))}")
    return SessionResponse(**session)


@app.post("/api/session/{session_id}/change/{change_id}")
async def update_change(session_id: str, change_id: str, status: str = Form(...)):
    """Update a specific change status"""
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update change status
    changes = session.get("changes", [])
    for change in changes:
        if change["id"] == change_id:
            if status:
                change["status"] = status
            break
    
    session["changes"] = changes
    save_session(session_id, session)
    
    return {"message": "Change updated"}


@app.post("/api/session/{session_id}/accept-all")
async def accept_all_changes(session_id: str):
    """Accept all pending changes"""
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    changes = session.get("changes", [])
    accepted_count = 0
    for change in changes:
        if change["status"] == "pending":
            change["status"] = "accepted"
            accepted_count += 1
    
    session["changes"] = changes
    save_session(session_id, session)
    
    return {"accepted_count": accepted_count}


@app.post("/api/changes/{session_id}")
async def handle_change(session_id: str, action: ChangeAction):
    """Accept or reject a change"""
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update change status
    changes = session.get("changes", [])
    for change in changes:
        if change["id"] == action.change_id:
            change["status"] = "accepted" if action.action == "accept" else "rejected"
            if action.edited_text:
                change["cleaned"] = action.edited_text
            break
    
    session["changes"] = changes
    save_session(session_id, session)
    
    return {"message": "Change updated"}


@app.post("/api/session/{session_id}/export")
async def export_book(session_id: str):
    """Export the cleaned book as EPUB"""
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    bookwash_path = Path(session.get("bookwash_path", ""))
    if not bookwash_path.exists():
        raise HTTPException(status_code=404, detail="BookWash file not found")
    
    # Generate cleaned EPUB using subprocess
    output_path = bookwash_path.parent / f"{bookwash_path.stem}_cleaned.epub"
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "bookwash_to_epub.py"), str(bookwash_path), "--output", str(output_path), "--apply-all"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"EPUB export failed: {result.stderr}")
    
    # Return the EPUB file
    return FileResponse(
        path=str(output_path),
        media_type="application/epub+zip",
        filename=f"{bookwash_path.stem}_cleaned.epub"
    )
    
    return FileResponse(
        output_path,
        media_type="application/epub+zip",
        filename=output_path.name
    )
    
    return FileResponse(
        output_path,
        media_type="application/epub+zip",
        filename=output_path.name
    )


# Mount static files (Flutter web build)
if Path("build/web").exists():
    app.mount("/", StaticFiles(directory="build/web", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
