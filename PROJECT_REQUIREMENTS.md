# BookWash - Project Requirements & Context

## Project Overview
BookWash is a Flutter desktop application that cleans EPUB books by using Ollama LLM (Large Language Model) to remove profanity and sexual content based on user-defined sensitivity levels.

## Core Purpose
- Interface with local Ollama LLM to intelligently clean EPUB books
- Generate a new cleaned EPUB file with content filtered according to user preferences
- Provide real-time feedback on cleaning progress and content removed

## Platform Requirements
- **Desktop Application**: macOS and Windows
- Built with Flutter for cross-platform compatibility
- Uses local Ollama LLM (not cloud-based)

## User Interface Components

### Main Screen
1. **File Selection**
   - Button/widget to allow user to browse and select an EPUB file
   - Display selected file path or name

2. **Sensitivity Sliders** (Two independent sliders)
   
   **Profanity Sensitivity Slider**: Range 1-4
   
   - **Level 1 - Strict**: Remove all profanity and insults
     - **Removes:** jerk, fool, dope, stupid, idiot, dumb, foolish, and all stronger language
     - **Keeps:** Nothing (nearly profanity-free)
     - **Result:** Suitable for young readers/children
   
   - **Level 2 - Moderate**: Remove most profanity, keep mild casual language
     - **Removes:** Level 1 words, plus: crap, sucks, crappy, shitty, bastard, damn, hell
     - **Keeps:** Mild expressions only
     - **Note:** No f-words or any variations of the f-word at this level
   
   - **Level 3 - Permissive**: Remove strong profanity, keep mild curses
     - **Removes:** Level 1-2 words, plus: ass, asshole, bitch, motherfucking, son of a bitch
     - **Keeps:** damn, hell, crap, sucks, bastard (mild curse words)
     - **Note:** No f-words or any variations of the f-word at this level
   
   - **Level 4 - Minimal**: Remove only the most extreme offensive language
     - **Removes:** ALL f-word variations (fuck, fucking, fucked, motherfucker, etc.), c-words, extreme slurs, and other extreme profanity
     - **Keeps:** ass, asshole, bitch, damn, hell, crap, sucks, bastard, motherfucking, son of a bitch
     - **Note:** Any word containing the f-word in any form belongs ONLY at Level 4

   **Sexual Content Sensitivity Slider**: Range 1-4
   - **Level 1 - Strict**: Remove all sexual/romantic content except essential plot
     - Example: Removes all romantic scenes, affectionate descriptions, relationship development beyond plot necessity
     - Result: Completely sanitized, suitable for young children; relationships mentioned factually only
   
   - **Level 2 - Moderate**: Remove suggestive and explicit content, keep light romance
     - Example: Removes detailed romantic scenes, sensual descriptions, sexual implications
     - Keeps: "they fell in love", brief mentions of relationships, hand-holding, basic affection
   
   - **Level 3 - Suggestive**: Remove explicit sexual content, keep suggestive/romantic elements
     - Example: Removes graphic descriptions, explicit language, detailed sexual acts
     - Keeps: "passionate moment", romantic chemistry, innuendo, kissing
   
   - **Level 4 - Graphic Only**: Remove only the most explicit sexual descriptions
     - Example: Removes graphic sex scenes, explicit anatomical details, extreme descriptions
     - Keeps: "They made love", intimate moments, sensual descriptions, most suggestive content

   **Violence Sensitivity Slider**: Range 1-4
   - **Level 1 - Strict**: Remove all depictions of violence except plot-essential references
     - Example: Removes physical fights, weapons usage, injury descriptions, threats, conflict scenes
     - Removes: "He punched him in the face", "stabbed with a knife", "blood dripping", "she threatened to kill him"
     - Keeps: "There was a conflict", "they argued", "the war happened" (abstract/historical)
   
   - **Level 2 - Moderate**: Remove graphic violence, keep mild conflict and emotional harm
     - Example: Removes detailed fight scenes, serious injuries, graphic weapons, explicit threats
     - Removes: "His fist connected, breaking several ribs", "blood poured from the wound", "the gun fired point-blank"
     - Keeps: "They fought", "he was hurt", "there was tension", "mild argument", "accidental bump"
   
   - **Level 3 - Suggestive**: Remove severe violence, keep minor physical conflict and self-defense
     - Example: Removes brutal combat, serious injuries, torture, extreme weapons, lethal threats
     - Removes: "tortured for hours", "dismembered", "shot execution-style", "graphic mutilation"
     - Keeps: "they scuffled", "a black eye formed", "self-defense punch", "serious injury" (without graphic detail)
   
   - **Level 4 - Minimal**: Remove only extreme violence and gore
     - Example: Removes only the most graphic/extreme descriptions of violence, gore, and brutality
     - Removes: "guts spilled across the floor", "flayed skin", "bones crushed to powder", "extreme torture"
     - Keeps: "they fought brutally", "he was badly beaten", "serious wounds", "combat scenes"

3. **Action Button**
   - "Go" / "Clean Book" button to start the cleaning process

4. **Progress Indicators**
   - **Progress Bar**: Shows percentage completion (0-100%)
   - **Running Summary Display**: 
     - Count of profanity instances removed (organized by sensitivity level)
       - Example: "Level 1: 5 | Level 2: 8 | Level 3: 12 | Level 4: 0"
     - Count of sexual content instances removed (organized by sensitivity level)
       - Example: "Level 1: 3 | Level 2: 8 | Level 3: 15 | Level 4: 0"
     - Count of violence instances removed (organized by sensitivity level)
       - Example: "Level 1: 7 | Level 2: 4 | Level 3: 2 | Level 4: 0"
     - Real-time updates as processing continues
   - **"Reveal" Button**: Expandable/collapsible section showing detailed logs of removed content
     - Display each removed text snippet with its categorization level
     - Show original context (surrounding sentence/paragraph)
     - Allow user to verify that filtering is working as expected
     - Can be toggled on/off to reduce visual clutter during processing

## Processing Logic

### Paragraph-Aware Chunking
- Parse EPUB book content into logical paragraph chunks
- Maintain paragraph boundaries (don't split mid-paragraph)
- Preserve formatting and structure

### LLM Integration
- Send chunks to local Ollama LLM for processing
- Process chunks independently (can be done sequentially or with queuing)
- Request: Clean chunk based on profanity, sexual content, and violence sensitivity levels
- LLM should flag/remove content and track what was removed

### Output Generation
- Collect cleaned chunks from LLM responses
- Write cleaned content back to a new EPUB file
- Preserve original book structure, metadata, and formatting
- Output file naming: `[original_filename]_cleaned.epub`

## Data Flow
1. User selects EPUB file
2. User sets sensitivity levels (1-5 for each)
3. User clicks "Go" button
4. App extracts text from EPUB in paragraph chunks
5. App sends each chunk to Ollama with cleaning instructions
6. LLM processes and returns cleaned chunk + removal summary
7. App updates progress bar and running summary
8. After all chunks processed, new EPUB file is written
9. User notified of completion with file location

## Technical Considerations

### File Handling
- Must parse and reconstruct EPUB format correctly
- EPUB files are ZIP archives with specific structure
- Preserve CSS, images, metadata, and document structure

### Performance
- Show progress updates frequently (don't freeze UI)
- Handle large books efficiently with chunk processing
- Consider memory usage with large EPUB files

### User Experience
- Clear visual feedback during processing
- Ability to cancel operation (future consideration)
- Error handling for invalid files or Ollama connection issues
- Clear display of what was removed from the book

## Future Enhancements (Optional)
- Cancel button during processing
- Preview of changes before/after
- Customizable output filename
- Settings for Ollama connection (localhost, custom ports)
- Batch processing multiple books
- Undo/rollback functionality
- Custom filtering rules beyond profanity/sexual content

## Current Status
- Project initialized as Flutter app
- Basic structure in place
- Ready for UI implementation and Ollama integration
