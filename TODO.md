# BookWash - Development TODO

## Current Status
✅ Flutter UI implemented with mock processing
✅ Test EPUB files created (4 storybooks)
✅ Requirements and testing framework documented

## Next Steps
- Change to 4 paragraphs instead of 8, for ease in reading
- only show the differences in the review panel
- look at all LLM instruction
- make it keep the same voice in the aggressive clean
- the request to not filter on violence isn't working, it is still trying to correct violence
- If we verify the chapters meet rating scale, is it using language MPAA or something else? Also what if we fail the verify? I don't think this is working
- Can we make the reviews go in the right order? Right now chapter 16 is before chapter 5
- I don't have an idea of how many total paragraphs there are to review. I'd like to see an overall percent
- make the right side editable again
- Make the UI a bit more fun, add Icon to the header, with Emojis, fun language, images?
- Make it so it handles if the user starts a book and then comes back
- Update the github readme with more details on what works and doesn't
- Test thoroughly with various EPUB structures
- Add a donation button
- What happens if they leave and come back to the page?
- Post to a few places like Linkedin

## DONE
- Regex prefilter for unambiguous profanity (sh*t→crud,  etc.) - new file: scripts/language_prefilter.py
- Try and rename the chapters based on the actual book chapters
- make the accept button in the same spot every time so I can tap it quuickly
-I don't think the cover image is getting put back together correctly
- the update progress steps are not highlighting
- do an aggressive pass after the verify fail.