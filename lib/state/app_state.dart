import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as path;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/bookwash_file.dart';
import '../models/chunk_change.dart';
import '../services/bookwash_parser.dart';
import '../services/epub_parser.dart';

/// Central state management for BookWash app using ChangeNotifier pattern.
/// This allows widgets to listen to state changes and rebuild automatically.
class AppState extends ChangeNotifier {
  // File selection state
  String? selectedFilePath;
  String? selectedFileName;
  ParsedEpub? parsedEpub;
  bool isLoadingFile = false;

  // Language filtering - word-based selection
  final Map<String, bool> languageWordSelection = {
    // Mild
    'darn': false,
    'gosh': false,
    'heck': false,
    'gee': false,
    'jeez': false,
    // Moderate
    'damn': true,
    'hell': true,
    'crap': true,
    'ass': true,
    'piss': true,
    'bummer': true,
    // Strong
    'shit': true,
    'bitch': true,
    'bastard': true,
    'asshole': true,
    'bullshit': true,
    // Severe
    'fuck': true,
    'motherfucker': true,
    // Taking name in vain
    'goddamn': true,
    'jesus christ': true,
    'oh my god': true,
    // Racial slurs
    'racial slurs': false,
  };

  // Content filter levels
  int sexualContentLevel = 2; // Default: PG
  int violenceLevel = 4; // Default: Unfiltered

  // Processing state
  bool isProcessing = false;
  bool isCancelling = false;
  double progress = 0.0;
  String progressPhase = ''; // 'converting', 'rating', 'cleaning'
  String cleaningSubPhase = ''; // 'language', 'adult', 'violence'
  int progressCurrent = 0;
  int progressTotal = 0;

  // API and model settings
  String geminiApiKey = '';
  String selectedModel = 'gemini-2.5-flash-lite';

  // Bookwash file state
  String? generatedBookwashPath;
  BookWashFile? bookwashFile;
  int selectedReviewChapter = 0;
  int currentReviewChangeIndex = 0;

  // Processing statistics
  int totalParagraphs = 0;
  int processedParagraphs = 0;
  int modifiedParagraphs = 0;

  // Real-time logging
  List<String> liveLogMessages = [];
  bool autoScrollLog = true;

  // Debug comparisons (key: "chapterIndex:changeId"; value: [original, cleaned])
  final Map<String, List<String>> paraComparisons = {};

  // Cleaned book data
  List<String> cleanedParagraphs = [];
  Map<int, int> paragraphToChapter = {};
  Map<int, int> cleanedParagraphToChapter = {};

  // Legacy change review system
  List<ChunkChange> pendingChanges = [];
  int currentReviewIndex = 0;
  bool isReviewingChanges = false;

  // Build timestamp
  final String buildTime = DateTime.now().toString().split('.')[0];

  // ============================================================
  // PERSISTENCE METHODS
  // ============================================================

  Future<void> loadSavedApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    final savedKey = prefs.getString('gemini_api_key') ?? '';
    if (savedKey.isNotEmpty) {
      geminiApiKey = savedKey;
      notifyListeners();
    }
  }

  Future<void> saveApiKey(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('gemini_api_key', key);
    geminiApiKey = key;
    notifyListeners();
  }

  Future<void> loadSavedLevels() async {
    final prefs = await SharedPreferences.getInstance();

    // Load language word selections
    final savedWords = prefs.getString('language_word_selection');
    if (savedWords != null) {
      try {
        final Map<String, dynamic> decoded = jsonDecode(savedWords);
        decoded.forEach((key, value) {
          if (languageWordSelection.containsKey(key)) {
            languageWordSelection[key] = value as bool;
          }
        });
      } catch (e) {
        // Use defaults if decode fails
      }
    }

    sexualContentLevel = (prefs.getInt('sexual_level') ?? sexualContentLevel)
        .clamp(1, 4);
    violenceLevel = (prefs.getInt('violence_level') ?? violenceLevel).clamp(
      1,
      4,
    );

    notifyListeners();
  }

  Future<void> saveLevel(String key, int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(key, value);
  }

  Future<void> saveLanguageWords() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      'language_word_selection',
      jsonEncode(languageWordSelection),
    );
  }

  // ============================================================
  // FILE SELECTION
  // ============================================================

  void setLoadingFile(bool loading) {
    isLoadingFile = loading;
    notifyListeners();
  }

  void setSelectedFile(String? filePath, String? fileName) {
    selectedFilePath = filePath;
    selectedFileName = fileName;
    notifyListeners();
  }

  void setParsedEpub(ParsedEpub? epub) {
    parsedEpub = epub;
    isLoadingFile = false;
    notifyListeners();
  }

  void clearFileSelection() {
    selectedFilePath = null;
    selectedFileName = null;
    parsedEpub = null;
    isLoadingFile = false;
    notifyListeners();
  }

  // ============================================================
  // FILTER SETTINGS
  // ============================================================

  void setLanguageWord(String word, bool selected) {
    languageWordSelection[word] = selected;
    saveLanguageWords();
    notifyListeners();
  }

  void setSexualContentLevel(int level) {
    sexualContentLevel = level.clamp(1, 4);
    saveLevel('sexual_level', sexualContentLevel);
    notifyListeners();
  }

  void setViolenceLevel(int level) {
    violenceLevel = level.clamp(1, 4);
    saveLevel('violence_level', violenceLevel);
    notifyListeners();
  }

  void setSelectedModel(String model) {
    selectedModel = model;
    notifyListeners();
  }

  // ============================================================
  // PROCESSING STATE
  // ============================================================

  void startProcessing() {
    isProcessing = true;
    isCancelling = false;
    progress = 0.0;
    progressPhase = 'converting';
    progressCurrent = 0;
    progressTotal = 0;
    liveLogMessages = [];
    generatedBookwashPath = null;
    bookwashFile = null;
    notifyListeners();
  }

  void cancelProcessing() {
    isCancelling = true;
    notifyListeners();
  }

  void setProgress(double value) {
    progress = value;
    notifyListeners();
  }

  void setProgressPhase(String phase, {String? subPhase}) {
    progressPhase = phase;
    if (subPhase != null) {
      cleaningSubPhase = subPhase;
    }
    notifyListeners();
  }

  void setProgressCounts(int current, int total) {
    progressCurrent = current;
    progressTotal = total;
    notifyListeners();
  }

  void finishProcessing(String bookwashPath) {
    progress = 1.0;
    progressPhase = 'complete';
    generatedBookwashPath = bookwashPath;
    isProcessing = false;
    notifyListeners();
  }

  void failProcessing() {
    isProcessing = false;
    notifyListeners();
  }

  // ============================================================
  // LOGGING
  // ============================================================

  void addLogMessage(String message) {
    liveLogMessages.add(message);
    notifyListeners();
  }

  void clearLogs() {
    liveLogMessages.clear();
    notifyListeners();
  }

  void setAutoScrollLog(bool value) {
    autoScrollLog = value;
    notifyListeners();
  }

  // ============================================================
  // BOOKWASH FILE & REVIEW
  // ============================================================

  Future<void> loadBookwashFile() async {
    if (generatedBookwashPath == null) return;

    try {
      final parsed = await BookWashParser.parse(generatedBookwashPath!);
      bookwashFile = parsed;
      selectedReviewChapter = 0;
      currentReviewChangeIndex = 0;

      // Populate comparison map from bookwash changes
      paraComparisons.clear();
      for (
        int chapterIdx = 0;
        chapterIdx < parsed.chapters.length;
        chapterIdx++
      ) {
        final chapter = parsed.chapters[chapterIdx];
        for (final change in chapter.changes) {
          if (change.original.isNotEmpty && change.cleaned.isNotEmpty) {
            final key = '$chapterIdx:${change.id}';
            paraComparisons[key] = [change.original, change.cleaned];
          }
        }
      }
      notifyListeners();
    } catch (e) {
      addLogMessage('❌ Failed to load bookwash file: $e');
    }
  }

  /// Parse change ID like "1.3" into sortable parts [chapter, change]
  List<int> _parseChangeId(String id) {
    final parts = id.split('.');
    if (parts.length == 2) {
      return [int.tryParse(parts[0]) ?? 0, int.tryParse(parts[1]) ?? 0];
    }
    final match = RegExp(r'c?(\d+)').firstMatch(id);
    return [0, int.tryParse(match?.group(1) ?? '0') ?? 0];
  }

  /// Get all pending changes across all chapters, sorted by ID
  List<MapEntry<int, BookWashChange>> get allPendingChanges {
    if (bookwashFile == null) return [];
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < bookwashFile!.chapters.length; i++) {
      for (final change in bookwashFile!.chapters[i].changes) {
        if (change.status == 'pending') {
          changes.add(MapEntry(i, change));
        }
      }
    }
    changes.sort((a, b) {
      final aId = _parseChangeId(a.value.id);
      final bId = _parseChangeId(b.value.id);
      final chapterCompare = aId[0].compareTo(bId[0]);
      if (chapterCompare != 0) return chapterCompare;
      return aId[1].compareTo(bId[1]);
    });
    return changes;
  }

  /// Get all changes (for stats), sorted by ID
  List<MapEntry<int, BookWashChange>> get allChanges {
    if (bookwashFile == null) return [];
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < bookwashFile!.chapters.length; i++) {
      for (final change in bookwashFile!.chapters[i].changes) {
        changes.add(MapEntry(i, change));
      }
    }
    changes.sort((a, b) {
      final aId = _parseChangeId(a.value.id);
      final bId = _parseChangeId(b.value.id);
      final chapterCompare = aId[0].compareTo(bId[0]);
      if (chapterCompare != 0) return chapterCompare;
      return aId[1].compareTo(bId[1]);
    });
    return changes;
  }

  void acceptChange(BookWashChange change) {
    change.status = 'accepted';
    _moveToNextChange();
    notifyListeners();
  }

  void acceptAllChanges() {
    for (final entry in allPendingChanges) {
      entry.value.status = 'accepted';
    }
    addLogMessage('✅ Accepted all ${allPendingChanges.length} pending changes');
  }

  void acceptAllLanguageChanges() {
    int acceptedCount = 0;
    for (final entry in allPendingChanges) {
      final change = entry.value;
      if (_isLanguageChange(change)) {
        change.status = 'accepted';
        acceptedCount++;
      }
    }
    addLogMessage('✅ Accepted $acceptedCount language changes');
    notifyListeners();
  }

  bool _isLanguageChange(BookWashChange change) {
    final original = change.original.toLowerCase();
    final cleaned = change.cleaned.toLowerCase();

    final languageReplacements = [
      'darn',
      'dang',
      'heck',
      'gosh',
      'fudge',
      'shoot',
      'crap',
      'jerk',
      'idiot',
      'fool',
      'moron',
      'butt',
      'rear',
      'behind',
      'curses',
      'blast',
      'confound',
    ];

    for (final replacement in languageReplacements) {
      if (cleaned.contains(replacement) && !original.contains(replacement)) {
        return true;
      }
    }
    return false;
  }

  void rejectChange(BookWashChange change) {
    change.status = 'rejected';
    _moveToNextChange();
    notifyListeners();
  }

  void _moveToNextChange() {
    final pending = allPendingChanges;
    if (currentReviewChangeIndex < pending.length - 1) {
      currentReviewChangeIndex++;
      selectedReviewChapter = pending[currentReviewChangeIndex].key;
    } else if (pending.isNotEmpty) {
      currentReviewChangeIndex = 0;
      selectedReviewChapter = pending[0].key;
    }
  }

  void goToPreviousChange() {
    final pending = allPendingChanges;
    if (currentReviewChangeIndex > 0) {
      currentReviewChangeIndex--;
      selectedReviewChapter = pending[currentReviewChangeIndex].key;
      notifyListeners();
    }
  }

  void goToNextChange() {
    final pending = allPendingChanges;
    if (currentReviewChangeIndex < pending.length - 1) {
      currentReviewChangeIndex++;
      selectedReviewChapter = pending[currentReviewChangeIndex].key;
      notifyListeners();
    }
  }

  Future<void> saveBookwashFile() async {
    if (bookwashFile == null || generatedBookwashPath == null) return;

    try {
      await BookWashParser.write(bookwashFile!, generatedBookwashPath!);
      addLogMessage(
        '💾 Saved changes to ${path.basename(generatedBookwashPath!)}',
      );
    } catch (e) {
      addLogMessage('❌ Failed to save: $e');
    }
  }

  // ============================================================
  // UTILITY METHODS
  // ============================================================

  String levelToRating(int level) {
    switch (level) {
      case 1:
        return 'G';
      case 2:
        return 'PG';
      case 3:
        return 'PG-13';
      case 4:
        return 'R';
      case 5:
        return 'X';
      default:
        return 'PG';
    }
  }

  List<String> get selectedLanguageWords {
    return languageWordSelection.entries
        .where((e) => e.value)
        .map((e) => e.key)
        .toList();
  }
}
