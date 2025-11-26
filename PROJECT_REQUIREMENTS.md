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

2. **Sensitivity Sliders** (Three independent sliders, 1-5 scale based on movie ratings)
   
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
