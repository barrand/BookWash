# BookWash - Development TODO

## Current Status
✅ Flutter UI implemented with mock processing
✅ Test EPUB files created (4 storybooks)
✅ Requirements and testing framework documented

## Next Steps

### Phase 1: EPUB Parsing & Writing
- [ ] **Add EPUB dependencies to pubspec.yaml**
  - Research and add EPUB parsing library (e.g., `epub_view`, `epub_parser`, or `archive` for manual parsing)
  - Add `archive` package for ZIP handling
  - Add `xml` package for XML/HTML manipulation
  - Add `path` package for file path handling

- [ ] **Implement EPUB Parser**
  - Extract EPUB structure (unzip archive)
  - Parse `content.opf` to get chapter manifest
  - Parse `toc.ncx` for table of contents
  - Extract chapter HTML/XHTML files
  - Parse chapters into paragraph chunks (preserve boundaries)
  - Maintain metadata (author, title, ISBN, etc.)

- [ ] **Implement EPUB Writer**
  - Reconstruct EPUB directory structure
  - Preserve original metadata and manifest
  - Write cleaned content back to chapter files
  - Maintain CSS, images, and formatting
  - Generate valid ZIP archive as EPUB
  - Name output file: `[original]_cleaned.epub`

- [ ] **Test EPUB Round-Trip**
  - Load test EPUB → extract → write → verify readable
  - Ensure no data loss in metadata/formatting
  - Test with all 4 test storybooks

### Phase 2: Ollama Integration
- [ ] **Add HTTP client dependencies**
  - Add `http` or `dio` package for API calls

- [ ] **Create Ollama Service Class**
  - Build HTTP client for Ollama API
  - Implement connection testing (check if Ollama is running)
  - Handle connection errors gracefully
  - Configure endpoint (default: localhost:11434)

- [ ] **Design LLM Prompt System**
  - Create prompt template with level definitions
  - Include examples from PROJECT_REQUIREMENTS.md
  - Design JSON response format for:
    - Cleaned text
    - Removal counts by level (profanity, sexual, violence)
    - Details of what was removed

- [ ] **Implement Chunk Processing**
  - Send paragraph chunks to Ollama with sensitivity settings
  - Parse LLM response (cleaned text + metadata)
  - Handle errors and retries
  - Track processing progress

- [ ] **Update Progress Tracking**
  - Replace simulated progress with real progress
  - Update removal counts from actual LLM responses
  - Populate removal details from LLM metadata
  - Stream progress updates to UI

### Phase 3: End-to-End Processing
- [ ] **Wire Up Complete Flow**
  - File selection → EPUB parsing → chunk extraction
  - Chunk processing → Ollama cleaning → response parsing
  - Cleaned chunks → EPUB reconstruction → file writing
  - Progress updates throughout entire flow

- [ ] **Add Error Handling**
  - Invalid EPUB file errors
  - Ollama connection failures
  - LLM timeout/error handling
  - File write permission errors
  - Display user-friendly error messages

- [ ] **Test with Real EPUBs**
  - Process all 4 test storybooks
  - Verify cleaned EPUBs are readable
  - Check that content was actually cleaned
  - Validate removal counts are accurate

### Phase 4: Confusion Matrix Testing
- [ ] **Create Testing Script/Tool**
  - Build paragraph extractor from test EPUBs
  - Map chapters to expected levels (from chapter names)
  - Send paragraphs to Ollama for classification

- [ ] **Implement Classification Logic**
  - Create LLM prompt for content classification (not cleaning)
  - Parse classification responses (profanity/sexual/violence levels)
  - Store predictions with actual labels

- [ ] **Build Confusion Matrix Generator**
  - Aggregate predictions vs actuals
  - Generate 3 matrices (profanity, sexual, violence)
  - Calculate precision, recall, F1-score per level
  - Compute overall accuracy metrics

- [ ] **Run Baseline Tests**
  - Test with Book 1 (heart broken story)
  - Analyze results, identify problem areas
  - Document which levels have poor performance

- [ ] **Iterative Refinement**
  - Adjust prompts based on confusion matrix results
  - Re-test and measure improvement
  - Cross-validate with Books 2-4
  - Document final prompt configuration

- [ ] **Create Testing Report**
  - Document confusion matrix results
  - Show precision/recall by level and category
  - Identify any systematic errors (over/under filtering)
  - Recommendations for production deployment

### Phase 5: Polish & Enhancement
- [ ] **UI Improvements**
  - Add cancel button during processing
  - Show current chapter/paragraph being processed
  - Add file save location picker
  - Display estimated time remaining

- [ ] **Settings/Configuration**
  - Ollama endpoint configuration (host/port)
  - Model selection (which Ollama model to use)
  - Customizable output filename
  - Save/load sensitivity presets

- [ ] **Performance Optimization**
  - Implement chunk queuing/batching
  - Add caching if appropriate
  - Optimize memory usage for large EPUBs
  - Consider parallel chunk processing

- [ ] **Documentation**
  - User guide for installation and usage
  - How to install and run Ollama locally
  - Troubleshooting common issues
  - API documentation for developers

## Future Enhancements (Optional)
- [ ] Batch processing (multiple EPUBs at once)
- [ ] Preview changes before saving
- [ ] Undo/rollback functionality
- [ ] Custom filtering rules (user-defined word lists)
- [ ] Export removal report as separate file
- [ ] Support for other formats (PDF, MOBI)

## Notes
- Keep UI responsive during processing (use async/await, isolates if needed)
- Maintain EPUB specification compliance
- Test thoroughly with various EPUB structures
- Document any Ollama model requirements or recommendations
