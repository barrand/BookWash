# BookWash - Project Requirements & Context

## Project Overview
BookWash moderates EPUB books using an AI model to remove or adjust language, sexual content, and violence per user-selected sensitivity levels. The system consists of a Flutter Web frontend and a FastAPI backend with persistent sessions, live logs, and review-before-export workflows.

## Core Purpose
- Provide a reviewable moderation workflow for EPUB content.
- Use an AI model (Gemini) to rate/clean content with transparent logs.
- Persist sessions and allow resume after refresh or restarts.
- Export a cleaned EPUB after change review and acceptance.

## Platform Requirements
- **Frontend**: Flutter Web (runs locally or deployed via backend static serving).
- **Backend**: FastAPI server serving API + web assets; SSE for live logs; Basic Auth optional.
- **AI Model**: Google Gemini via API key; with model fallback on rate limits.

## User Interface Components (Web)

### Main Screen
1. **File Selection**
  - Browse/upload an EPUB
  - Shows selected filename

2. **Sensitivity Sliders** (1-5 scale, movie ratings)
   
  **Language Sensitivity Slider**: Range 1-5
   
   - **Level 1 - G Rated**: No profanity or crude language (Most censorship)
     - **Removes:** ALL profanity, insults, and crude language
     - **Examples removed:** jerk, fool, dope, stupid, idiot, dumb, crap, damn, hell, ass, bitch, f-words, all curse words
     - **Keeps:** Clean language only
     - **Result:** Suitable for all ages/young children
   
   - **Level 2 - PG Rated**: Mild language allowed (Heavy censorship)
     - **Removes:** Strong profanity and crude language
     - **Examples removed:** f-words, ass, asshole, bitch, bastard, more intense insults
     - **Keeps:** Very mild expressions (darn, gosh, heck, jeez)
     - **Result:** Family-friendly content
   
   - **Level 3 - PG-13 Rated**: Some strong language (Light censorship)
     - **Removes:** F-words and extreme profanity
     - **Examples removed:** fuck, fucking, fucked, motherfucker, c-words, extreme slurs
     - **Keeps:** Strong language like ass, asshole, bitch, damn, hell, crap, bastard
     - **Result:** Teenage-appropriate content
   
   - **Level 4 - R Rated**: Strong language allowed (Censorship of F-word only)
     - **Removes:** Only f-word variations (fuck, fucking, fucked, motherfucker, etc.)
     - **Keeps:** All other profanity including ass, asshole, bitch, damn, hell, crap, bastard, son of a bitch
     - **Result:** Adult content with extreme profanity removed
   
   - **Level 5 - Unrated**: Everything allowed (No censorship)
     - **Removes:** Nothing
     - **Keeps:** All language including f-words, c-words, all profanity
     - **Result:** Original unmodified content

  **Sexual Content Sensitivity Slider**: Range 1-5
   
   - **Level 1 - G Rated**: No sexual content allowed (Most censorship)
     - **Removes:** ALL romantic and sexual content beyond basic plot necessity
     - **Examples removed:** Kissing, romantic scenes, affection, attraction, relationships beyond friendship
     - **Keeps:** "They were married", "they were friends" (factual relationships only)
     - **Result:** Suitable for young children
   
   - **Level 2 - PG Rated**: Light romance only (Heavy censorship)
     - **Removes:** Suggestive content, sexual implications, detailed romantic scenes
     - **Examples removed:** Passionate kissing, sensual descriptions, sexual tension, innuendo
     - **Keeps:** "They fell in love", hand-holding, basic affection, chaste kissing
     - **Result:** Family-friendly romance
   
   - **Level 3 - PG-13 Rated**: Romantic scenes allowed (Light censorship)
     - **Removes:** Explicit sexual content and graphic descriptions
     - **Examples removed:** Sex scenes, explicit anatomical details, graphic sexual acts
     - **Keeps:** Passionate kissing, romantic chemistry, innuendo, "they spent the night together"
     - **Result:** Teenage-appropriate romantic content
   
   - **Level 4 - R Rated**: Suggestive content allowed (Censorship of X-rated content only)
     - **Removes:** Only extremely graphic sexual descriptions and pornographic content
     - **Examples removed:** Explicit anatomical descriptions, graphic sex acts with extreme detail
     - **Keeps:** "They made love", intimate scenes, sensual descriptions, most sexual content
     - **Result:** Adult romantic/sexual content with extreme pornography removed
   
   - **Level 5 - Unrated**: Everything allowed (No censorship)
     - **Removes:** Nothing
     - **Keeps:** All sexual and romantic content including explicit scenes
     - **Result:** Original unmodified content

  **Violence Sensitivity Slider**: Range 1-5
   
   - **Level 1 - G Rated**: No violence (Most censorship)
     - **Removes:** ALL violence, physical conflict, weapons, injuries, and threats
     - **Examples removed:** Fighting, punching, weapons, blood, injuries, death scenes, threats
     - **Keeps:** "There was a conflict", "they disagreed" (abstract references only)
     - **Result:** Suitable for young children
   
   - **Level 2 - PG Rated**: Mild conflict only (Heavy censorship)
     - **Removes:** Graphic violence, detailed injuries, weapons usage, serious threats
     - **Examples removed:** Blood, detailed fights, stabbings, shootings, severe injuries
     - **Keeps:** "They fought", "he was hurt", mild arguments, tension, accidental bumps
     - **Result:** Family-friendly conflict
   
   - **Level 3 - PG-13 Rated**: Action/combat allowed (Light censorship)
     - **Removes:** Extreme violence, torture, graphic injuries, brutal combat
     - **Examples removed:** Torture scenes, dismemberment, graphic mutilation, execution-style deaths
     - **Keeps:** Fight scenes, combat, "a black eye formed", self-defense, action sequences
     - **Result:** Teenage-appropriate action content
   
   - **Level 4 - R Rated**: Intense violence allowed (Censorship of intense gore only)
     - **Removes:** Only extreme gore and the most graphic descriptions
     - **Examples removed:** "Guts spilled across the floor", "flayed skin", extreme torture with graphic detail
     - **Keeps:** Brutal fights, serious injuries, "he was badly beaten", combat with blood, violent deaths
     - **Result:** Adult violence with extreme gore removed
   
   - **Level 5 - Unrated**: Everything allowed (No censorship)
     - **Removes:** Nothing
     - **Keeps:** All violence including extreme gore and graphic descriptions
     - **Result:** Original unmodified content

3. **Action Button**
  - "Process Book" starts upload + server-side processing

4. **Progress & Logs**
   - Progress bar and phase chips (converting, rating, cleaning, complete)
   - Live logs via SSE; selectable monospace; heartbeat messages during quiet periods
   - URL updates with `?session={id}` for refresh/resume

5. **Change Review**
   - Side-by-side original vs cleaned snippets per change
   - Accept/reject individual changes; accept-all option

6. **Export & Cancel**
   - Export cleaned EPUB
   - Cancel button to stop backend subprocess and delete session

## Processing Logic

### Paragraph-Aware Chunking
- Parse EPUB book content into logical paragraph chunks
- Maintain paragraph boundaries (don't split mid-paragraph)
- Preserve formatting and structure

### LLM Integration
- Send chunks to Gemini via backend script `bookwash_llm.py`
- Process chunks independently (can be done sequentially or with queuing)
- Request: Clean chunk based on profanity, sexual content, and violence sensitivity levels
- LLM should flag/remove content and track what was removed

### Output Generation
- Collect cleaned chunks from LLM responses
- Write cleaned content back to a new EPUB file
- Preserve original book structure, metadata, and formatting
- Output file naming: `[original_filename]_cleaned.epub`

## Data Flow
1. User uploads EPUB via web UI.
2. Backend creates a session and stores files in `webapp/sessions/{id}`.
3. Frontend starts processing via `/api/process/{id}`.
4. Backend converts EPUB → `.bookwash`, runs `bookwash_llm.py` to rate/clean, and logs progress.
5. Frontend subscribes to `/api/logs/{id}` for live status and logs.
6. Backend parses `.bookwash` into changes; frontend reviews accept/reject.
7. Frontend exports via `/api/session/{id}/export` to download cleaned EPUB.
8. Sessions persist on disk for resume via `?session={id}`.

## Technical Considerations

### File Handling
- Must parse and reconstruct EPUB format correctly
- EPUB files are ZIP archives with specific structure
- Preserve CSS, images, metadata, and document structure

### Performance & Reliability
- SSE for frequent progress updates
- Heartbeat log messages every 30s during quiet LLM periods
- Frequent session saves on progress changes to survive restarts
- Daily cleanup task removes sessions inactive > 14 days

### User Experience
- Clear visual feedback with progress/phase chips and logs
- Cancel operation supported; backend kills subprocess
- Error handling with logs and review state
- Auth-aware resume handling in case of Basic Auth enabled

## Backend Services & Endpoints
- `GET /api/health`: Health check.
- `POST /api/upload`: Upload EPUB; returns session ID.
- `POST /api/process/{id}`: Start processing for a session.
- `GET /api/logs/{id}`: SSE logs + status, progress, phase.
- `GET /api/session/{id}`: Session state including changes and logs.
- `POST /api/session/{id}/change/{changeId}`: Set change status to `accepted` or `rejected`.
- `POST /api/session/{id}/accept-all`: Accept all pending changes.
- `POST /api/session/{id}/export`: Export cleaned EPUB download; sets status to `complete`.
- `DELETE /api/session/{id}`: Cancel processing and delete session files.
- `NEW GET /api/sessions`: List sessions (memory + disk) with metadata.
- `NEW GET /api/session/{id}/download`: Download `.bookwash` file for recovery.

## Services
- **FastAPI Backend**: SSE, session persistence, auth, cleanup.
- **Flutter Web Frontend**: Upload, logs, review, export, cancel; build under `build/web`.
- **Gemini API**: Requires `GEMINI_API_KEY`; model fallback ping-pong between `gemini-2.0-flash` and `gemini-1.5-flash` on 429.
- **Render Deployment**: Configure Persistent Disk to preserve `webapp/sessions`. Consider mounting at `/data/sessions` and making it configurable.

## Environment Variables
- `GEMINI_API_KEY` (required)
- `APP_USERNAME` (optional; default `bookwash`)
- `APP_PASSWORD` (optional; when set, all routes require Basic Auth)
- `PORT` (optional; default 8000)

## Current Status
- Web + backend flow implemented with live logs and review.
- Session persistence with frequent saves; daily cleanup task.
- Cancel support, export, and cache-busting for frontend assets.
- New recovery endpoints added for session listing and `.bookwash` download.

## Current Status
- Project initialized as Flutter app
- Basic structure in place
- Ready for UI implementation and Ollama integration
