# BookWash Confusion Matrix Testing Framework

## Overview
This framework validates that the Ollama LLM correctly identifies and removes content at each specified sensitivity level (1-4) across three content categories: Profanity, Sexual Content, and Violence.

## Test Structure
- **4 Test EPUBs**: Different stories/genres to test LLM robustness across narrative contexts
- **14 Chapters per EPUB**: Intro + 4 profanity levels + 4 sexual levels + 4 violence levels + conclusion
- **Total Test Cases**: 4 books × 3 categories × 4 levels = 48 unique test chapters

## Test Books

### Book 1: BookWash_TestBook.epub
**Narrative**: Maya's breakup journey with escalating emotional trauma
- **Profanity Arc**: Mild venting (jerk, fool) → Scattered swearing (damn, hell) → Increasing intensity (bitch, asshole) → Extreme language (f-words, c-words)
- **Sexual Arc**: Factual relationship facts → Implied intimacy → Detailed descriptions → Graphic explicit content
- **Violence Arc**: Verbal conflict → Physical altercation → Home invasion → Brutal assault

### Book 2: StoryBook2_TechStartup.epub
**Narrative**: Sarah's tech startup journey with corporate conflict and romance
- **Profanity Arc**: Pitch rejection frustration → Investment loss desperation → CTO betrayal anger → Breakdown rage
- **Sexual Arc**: Personal neglect → David connection → Growing intimacy → Explicit passion
- **Violence Arc**: Corporate campaign tactics → Conference confrontation → Office break-in → Parking garage attack

### Book 3: StoryBook3_DragonQuest.epub
**Narrative**: Kael's dragon quest with magical trials and Arden romance
- **Profanity Arc**: Magical curse reactions → Battlefield oaths → Demon summoning → Apocalyptic fury
- **Sexual Arc**: Longing glances → First kiss → Intimate moments → Passionate encounter
- **Violence Arc**: Monster encounters → Dragon combat → Apocalyptic battle → Final sacrifice

### Book 4: StoryBook4_UndoingCrime.epub
**Narrative**: Detective Elena's crime investigation with Marcus relationship
- **Profanity Arc**: Crime scene frustration → Witness interrogation → Corruption discovery → Despair breakdown
- **Sexual Arc**: Professional distance → Personal connection → Romantic escalation → Intimate scenes
- **Violence Arc**: Initial crime evidence → Suspect violence → Serial killer revelations → Final confrontation

## Testing Methodology

### Phase 1: Content Extraction
For each test EPUB:
1. Extract all 14 chapters
2. Chunk into paragraphs (preserve paragraph boundaries per requirements)
3. Send each paragraph to Ollama LLM with prompt: "Identify content type(s) and level(s) present"

### Phase 2: LLM Classification
For each paragraph, LLM should return:
```
{
  "profanity": {
    "detected": boolean,
    "level": 1-4 (if detected),
    "examples": ["word1", "word2"]
  },
  "sexual": {
    "detected": boolean,
    "level": 1-4 (if detected),
    "description": "brief content description"
  },
  "violence": {
    "detected": boolean,
    "level": 1-4 (if detected),
    "description": "brief violence description"
  }
}
```

### Phase 3: Confusion Matrix Generation
Build 3 matrices (one per category):

#### Profanity Confusion Matrix
```
         Predicted Level
         1    2    3    4   None
Actual 1 [ ]  [ ]  [ ]  [ ]  [ ]
Level  2 [ ]  [ ]  [ ]  [ ]  [ ]
       3 [ ]  [ ]  [ ]  [ ]  [ ]
       4 [ ]  [ ]  [ ]  [ ]  [ ]
       None [ ][ ][ ][ ][ ]
```

- **Diagonal (True Positives)**: Correct classifications (1→1, 2→2, 3→3, 4→4)
- **Above Diagonal (False Positives - Over-Aggressive)**: LLM predicts higher level than actual
  - Example: 1→2 (claimed level 2 content in chapter with only level 1 profanity)
- **Below Diagonal (False Negatives - Under-Aggressive)**: LLM misses content or predicts lower level
  - Example: 3→1 (missed level 3 profanity, reported as level 1)
- **Off-Diagonal (Category Errors)**: Complete misclassification

### Phase 4: Metrics Calculation

**Per-Level Performance:**
- **Precision**: TP / (TP + FP) = Correct detections / All positive predictions
- **Recall**: TP / (TP + FN) = Correct detections / All actual instances
- **F1-Score**: 2 × (Precision × Recall) / (Precision + Recall)

**Aggregate Metrics:**
- **Macro Accuracy**: Average accuracy across all levels
- **Weighted Accuracy**: Accuracy weighted by frequency of each level
- **Cross-Book Consistency**: Standard deviation of F1-scores across 4 books

## Expected Behavior

### Strict Filtering (Level 1)
- **Profanity**: Should remove ALL profanity (even mild "jerk", "damn")
- **Sexual**: Should remove ALL sexual content (even factual relationship descriptions)
- **Violence**: Should remove ANY violence depiction (even verbal threats)

### Moderate Filtering (Level 2)
- **Profanity**: Remove level 2+ (scattered swearing like "damn", "hell")
- **Sexual**: Remove level 2+ (implied intimacy descriptions)
- **Violence**: Remove level 2+ (physical altercations)

### Permissive Filtering (Level 3)
- **Profanity**: Remove level 3+ (increasing intensity, "bitch", "asshole")
- **Sexual**: Remove level 3+ (detailed descriptions)
- **Violence**: Remove level 3+ (serious injuries, home invasions)

### Minimal Filtering (Level 4)
- **Profanity**: Remove only level 4 (extreme: f-words, c-words)
- **Sexual**: Remove only level 4 (graphic explicit content)
- **Violence**: Remove only level 4 (brutal assaults, gore, extreme brutality)

## Validation Criteria

**PASS**: All levels achieve:
- ✅ Precision ≥ 0.85
- ✅ Recall ≥ 0.80
- ✅ F1-Score ≥ 0.82
- ✅ Diagonal dominance (>80% of predictions on main diagonal)

**CONDITIONAL PASS**: Some levels below threshold
- ⚠ Identify problematic levels
- ⚠ Refine prompt/examples for those levels
- ⚠ Re-test with revised LLM configuration

**FAIL**: Multiple levels with poor performance
- ❌ Indicates level definitions lack clear distinction
- ❌ May require revised PROJECT_REQUIREMENTS.md
- ❌ Consider reducing to 3 levels or improving examples

## Implementation Notes

### Paragraph Extraction from EPUB
```python
def extract_paragraphs_from_epub(epub_path):
    # 1. Unzip EPUB
    # 2. Find all .html files in OEBPS/chapter_*.html
    # 3. Parse each with BeautifulSoup
    # 4. Extract <p> tags while preserving chapter context
    # 5. Return: [(chapter_name, paragraph_text), ...]
```

### LLM Prompt Template
```
You are content classifier for a book cleaning system. Analyze the following paragraph 
and identify any profanity, sexual content, or violence.

Use these level definitions:
[Include relevant level descriptions from PROJECT_REQUIREMENTS.md]

Paragraph:
"<paragraph_text>"

Respond in JSON format:
{
  "profanity": {"detected": bool, "level": 1-4 or null, "examples": [...]},
  "sexual": {"detected": bool, "level": 1-4 or null, "description": "..."},
  "violence": {"detected": bool, "level": 1-4 or null, "description": "..."}
}
```

### Confusion Matrix Aggregation
```python
def build_confusion_matrices(predictions, actuals):
    # predictions: List of LLM classification results
    # actuals: List of expected classifications from PROJECT_REQUIREMENTS.md
    
    matrices = {
        'profanity': create_matrix(predictions, actuals, 'profanity'),
        'sexual': create_matrix(predictions, actuals, 'sexual'),
        'violence': create_matrix(predictions, actuals, 'violence')
    }
    
    return matrices  # shape: (3, 4×5, 4×5) for 3 categories, 5 rows/cols each
```

## Next Steps

1. **Implement EPUB Paragraph Extractor**: Build tool to extract chapter content with metadata
2. **Configure Ollama Prompt**: Create effective prompt template with level examples
3. **Run Baseline Test**: Execute full matrix on Book 1 (single narrative test)
4. **Analyze Results**: Identify which levels have precision/recall issues
5. **Iterative Refinement**: Adjust prompt/levels based on errors
6. **Cross-Book Validation**: Run on Books 2-4 to confirm consistency
7. **Document Findings**: Create report with recommendations for production system

## Confusion Matrix Interpretation Guide

### High Diagonal, Low Off-Diagonal (IDEAL)
- Strong performance, LLM understands level distinctions
- Ready for production with high confidence

### Systematic Over-Prediction (Above-Diagonal Heavy)
- LLM too aggressive, catches too much
- Increase sensitivity thresholds or clarify "keep" examples

### Systematic Under-Prediction (Below-Diagonal Heavy)
- LLM misses content frequently
- Increase example specificity or adjust prompt emphasis

### Random Errors (Scattered Matrix)
- Poor level definition clarity
- Consider revising PROJECT_REQUIREMENTS.md examples
