import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:path/path.dart' as path;
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'models/bookwash_file.dart';
import 'services/bookwash_parser.dart';
import 'services/epub_parser.dart';
import 'services/epub_writer.dart';
import 'models/chunk_change.dart';
import 'state/app_state.dart';
import 'widgets/widgets.dart';

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppState()
        ..loadSavedApiKey()
        ..loadSavedLevels(),
      child: const BookWashApp(),
    ),
  );
}

class BookWashApp extends StatelessWidget {
  const BookWashApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BookWash',
      theme: ThemeData.dark(useMaterial3: true),
      themeMode: ThemeMode.dark,
      home: const BookWashHome(),
    );
  }
}

class BookWashHome extends StatefulWidget {
  const BookWashHome({super.key});

  @override
  State<BookWashHome> createState() => _BookWashHomeState();
}

class _BookWashHomeState extends State<BookWashHome> {
  String? selectedFilePath;
  String? selectedFileName;
  ParsedEpub? parsedEpub;
  bool isLoadingFile = false;
  // Language filtering now uses word selection instead of level
  final Map<String, bool> languageWordSelection = {
    // Mild
    'darn': false,
    'gosh': false,
    'heck': false,
    'gee': false,
    'jeez': false,
    'bummer': true,
    // Moderate
    'damn': true,
    'hell': true,
    'crap': true,
    'ass': true,
    'piss': true,
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
    'racial slurs':
        false, // Meta-option: instructs LLM to remove all racial slurs
  };
  int sexualContentLevel = 2; // Default: PG sexual content
  int violenceLevel = 4; // Default: Unfiltered (no censorship)
  bool isProcessing = false;
  bool isCancelling = false;
  double progress = 0.0;
  String progressPhase = ''; // 'converting', 'rating', 'cleaning'
  String cleaningSubPhase = ''; // 'language', 'adult', 'violence'
  int progressCurrent = 0;
  int progressTotal = 0;
  bool showDetails = false;

  // Gemini API key for Python script
  String geminiApiKey = '';

  // Model selection
  String selectedModel = 'gemini-2.5-flash-lite'; // Default Gemini model

  // Bookwash file state
  String? generatedBookwashPath;
  BookWashFile? bookwashFile;
  int selectedReviewChapter = 0;
  int currentReviewChangeIndex = 0;

  // Processing statistics
  int totalParagraphs = 0;
  int processedParagraphs = 0;
  int modifiedParagraphs = 0;

  List<String> removalDetails = [];

  // Real-time logging
  List<String> liveLogMessages = [];
  final _scrollController = ScrollController();
  bool _autoScrollLog = true; // user-controlled auto-scroll for live log

  // Cleaned book data
  List<String> cleanedParagraphs = [];
  Map<int, int> paragraphToChapter =
      {}; // original paragraph index -> chapter index
  Map<int, int> cleanedParagraphToChapter =
      {}; // cleaned paragraph index -> chapter index

  // Change review system
  List<ChunkChange> pendingChanges = [];
  int currentReviewIndex = 0;
  bool isReviewingChanges = false;

  // Build timestamp for debugging
  final String _buildTime = DateTime.now().toString().split(
    '.',
  )[0]; // YYYY-MM-DD HH:mm:ss

  @override
  void initState() {
    super.initState();
    _loadSavedApiKey();
    _loadSavedLevels();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadSavedApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    final savedKey = prefs.getString('gemini_api_key') ?? '';
    if (savedKey.isNotEmpty) {
      setState(() {
        geminiApiKey = savedKey;
      });
    }
  }

  Future<void> _saveApiKey(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('gemini_api_key', key);
  }

  Future<void> _loadSavedLevels() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
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
    });
  }

  Future<void> _saveLevel(String key, int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(key, value);
  }

  Future<void> _saveLanguageWords() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      'language_word_selection',
      jsonEncode(languageWordSelection),
    );
  }

  Future<void> _showGeminiApiKeyDialog() async {
    final controller = TextEditingController(text: geminiApiKey);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Enter Gemini API Key'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Get your free API key from:'),
            const SizedBox(height: 8),
            const Text(
              'https://aistudio.google.com/apikey',
              style: TextStyle(color: Colors.blue, fontSize: 12),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'API Key',
                hintText: 'AIza...',
              ),
              obscureText: true,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (result != null && result.isNotEmpty) {
      await _saveApiKey(result); // Save to persistent storage
      setState(() {
        geminiApiKey = result;
      });
    }
  }

  Future<void> selectFile() async {
    print('DEBUG: Opening file picker...');

    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['epub'],
    );

    print(
      'DEBUG: File picker result: ${result != null ? "Got result" : "null"}',
    );

    if (result == null) {
      print('DEBUG: Result was null, user probably cancelled');
      return;
    }

    print('DEBUG: Files in result: ${result.files.length}');

    if (result.files.isEmpty) {
      print('DEBUG: No files in result');
      return;
    }

    final file = result.files.single;

    print('DEBUG: Selected file - Name: ${file.name}');
    print('DEBUG: Platform - path: ${file.path}, bytes: ${file.bytes?.length}');

    // On web, path is null and we need to use bytes
    // On desktop, path is available
    if (file.path == null && file.bytes == null) {
      print('ERROR: No file path or bytes available!');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Could not access file. Please use desktop app for full functionality.',
            ),
            backgroundColor: Colors.orange,
          ),
        );
      }
      return;
    }

    setState(() {
      selectedFilePath = file.path ?? file.name;
      selectedFileName = file.name;
      isLoadingFile = true;
      parsedEpub = null;
    });

    try {
      // On desktop, use file path. On web, we'd need to modify the parser
      // to accept bytes, but for now, show an error on web
      if (file.path == null) {
        throw Exception(
          'Web platform not yet supported. Please run the desktop app.',
        );
      }

      print('DEBUG: Starting EPUB parse for: ${file.path}');

      // Parse the EPUB file
      final epub = await EpubParser.parseEpub(file.path!);

      print(
        'DEBUG: EPUB parsed successfully - ${epub.metadata.title} by ${epub.metadata.author}',
      );
      print(
        'DEBUG: ${epub.chapters.length} chapters, ${epub.totalParagraphs} paragraphs',
      );

      setState(() {
        parsedEpub = epub;
        isLoadingFile = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Loaded: ${epub.metadata.title} - ${epub.chapters.length} chapters, ${epub.totalParagraphs} paragraphs',
            ),
            duration: const Duration(seconds: 3),
          ),
        );
      }
    } catch (e, stackTrace) {
      print('ERROR: Failed to parse EPUB - $e');
      print('STACKTRACE: $stackTrace');

      setState(() {
        isLoadingFile = false;
        selectedFilePath = null;
        selectedFileName = null;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error loading EPUB: $e'),
            duration: const Duration(seconds: 5),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  void cancelProcessing() {
    setState(() {
      isCancelling = true;
    });
  }

  Future<void> saveCleanedBook() async {
    if (cleanedParagraphs.isEmpty || parsedEpub == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('No cleaned book to save')));
      return;
    }

    try {
      // Let user choose save location
      final outputPath = await FilePicker.platform.saveFile(
        dialogTitle: 'Save Cleaned Book',
        fileName: '${parsedEpub!.metadata.title}_cleaned.epub',
        type: FileType.custom,
        allowedExtensions: ['epub'],
      );

      if (outputPath == null) {
        print('User cancelled save');
        return;
      }

      // Write EPUB file
      final epubWriter = EpubWriter();
      await epubWriter.writeEpub(
        outputPath: outputPath,
        originalEpub: parsedEpub!,
        cleanedParagraphs: cleanedParagraphs,
        paragraphToChapter:
            cleanedParagraphToChapter, // Use the cleaned mapping
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Book saved to: $outputPath'),
            duration: const Duration(seconds: 5),
          ),
        );
      }
    } catch (e) {
      print('Error saving book: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error saving book: $e'),
            duration: const Duration(seconds: 5),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> processBook() async {
    print('════════════════════════════════════════');
    print('🔴 processBook() called - START OF FUNCTION');
    print('════════════════════════════════════════');

    if (selectedFilePath == null) {
      print('⚠️ selectedFilePath is null');
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select an EPUB file first')),
      );
      return;
    }

    print('✓ selectedFilePath: $selectedFilePath');

    // Check if Gemini API key is set
    if (geminiApiKey.isEmpty) {
      print('⚠️ geminiApiKey is empty');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Please set your Gemini API key first (click the key icon in the top right)',
            ),
            duration: Duration(seconds: 5),
            backgroundColor: Colors.red,
          ),
        );
      }
      return;
    }

    setState(() {
      isProcessing = true;
      isCancelling = false;
      progress = 0.0;
      progressPhase = 'converting';
      progressCurrent = 0;
      progressTotal = 0;
      liveLogMessages = [];
      generatedBookwashPath = null;
      bookwashFile = null;
    });

    _addLogMessage('🚀 Process started - debugging enabled');
    print('🚀 Process started - debugging enabled');
    _addLogMessage('');

    try {
      // Determine bookwash output path - save in project directory
      final epubPath = selectedFilePath!;
      _addLogMessage('📂 Creating work directory...');

      // Create a persistent directory in the project for bookwash files
      final workDir = Directory(
        '/Users/bbarrand/Documents/Projects/BookWash/bookwash-files',
      );
      if (!workDir.existsSync()) {
        workDir.createSync(recursive: true);
      }
      _addLogMessage('✓ Work directory: ${workDir.path}');

      final bookwashPath =
          '${workDir.path}/${path.basenameWithoutExtension(epubPath)}.bookwash';

      _addLogMessage('📚 Starting BookWash processing...');
      _addLogMessage('📖 Input: ${path.basename(epubPath)}');
      _addLogMessage('💾 Output: ${path.basename(bookwashPath)}');

      // Step 1: Convert EPUB to .bookwash
      _addLogMessage('');
      _addLogMessage('═══════════════════════════════════════════');
      _addLogMessage('📝 Step 1: Converting EPUB to .bookwash format...');
      _addLogMessage('═══════════════════════════════════════════');

      final epubToBookwashResult = await _runPythonScript(
        'scripts/epub_to_bookwash.py',
        [epubPath, bookwashPath],
      );

      if (epubToBookwashResult != 0) {
        _addLogMessage('❌ EPUB to .bookwash conversion failed');
        _addLogMessage('Check that the EPUB file is valid and not corrupted');
        throw Exception(
          'Failed to convert EPUB to .bookwash (exit code: $epubToBookwashResult)',
        );
      }

      _addLogMessage('✅ EPUB converted to .bookwash format');

      setState(() {
        progress = 0.05; // Small progress for conversion step
        progressPhase = 'rating';
      });

      // Step 2: Rate and clean with LLM
      _addLogMessage('');
      _addLogMessage('═══════════════════════════════════════════');
      _addLogMessage('🤖 Step 2: Rating and cleaning content with AI...');
      _addLogMessage('═══════════════════════════════════════════');
      final selectedWords = languageWordSelection.entries
          .where((e) => e.value)
          .map((e) => e.key)
          .toList();
      _addLogMessage(
        'Target levels: Language: Filtering ${selectedWords.length} words, Adult=${_levelToRating(sexualContentLevel)}, Violence=${_levelToRating(violenceLevel)}',
      );

      final llmResult = await _runPythonScript('scripts/bookwash_llm.py', [
        '--rate',
        '--clean-passes',
        bookwashPath,
        '--api-key',
        geminiApiKey,
        '--model',
        selectedModel,
        '--language-words',
        jsonEncode(selectedWords),
        '--filter-types',
        'language,sexual,violence', // Filter all content types
        '--sexual',
        sexualContentLevel.toString(),
        '--violence',
        violenceLevel.toString(),
      ]);

      if (llmResult != 0) {
        throw Exception('Failed to process with LLM (exit code: $llmResult)');
      }

      _addLogMessage('✅ Content rated and cleaned');

      setState(() {
        progress = 1.0;
        progressPhase = 'complete';
        generatedBookwashPath = bookwashPath;
      });

      // Load the bookwash file for review
      await _loadBookwashFile();

      _addLogMessage('');
      _addLogMessage('═══════════════════════════════════════════');
      _addLogMessage('🎉 Processing complete!');
      _addLogMessage('═══════════════════════════════════════════');
      _addLogMessage('📄 Output: ${path.basename(bookwashPath)}');
      _addLogMessage('');
      _addLogMessage(
        'Review changes below, then click "Export EPUB" when ready.',
      );

      setState(() {
        isProcessing = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Processing complete! Review changes below.'),
            duration: Duration(seconds: 4),
          ),
        );
      }
    } catch (e, stackTrace) {
      print('Error processing book: $e');
      print('Stack trace: $stackTrace');

      _addLogMessage('');
      _addLogMessage('❌ Error: $e');

      setState(() {
        isProcessing = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error processing book: $e'),
            duration: const Duration(seconds: 5),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  String _levelToRating(int level) {
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

  void _addLogMessage(String message) {
    setState(() {
      liveLogMessages.add(message);
    });
    _scrollToBottom();
  }

  void _parseProgressFromLine(String line) {
    // Parse lines like "[1/7] Chapter 1..." to extract progress
    final chapterMatch = RegExp(r'\[(\d+)/(\d+)\]').firstMatch(line);
    if (chapterMatch != null) {
      final current = int.tryParse(chapterMatch.group(1) ?? '0') ?? 0;
      final total = int.tryParse(chapterMatch.group(2) ?? '0') ?? 0;

      setState(() {
        progressCurrent = current;
        progressTotal = total;

        // Calculate progress: 5% for conversion, 45% for rating, 50% for cleaning
        // Cleaning is split: 50-65% language, 65-80% adult, 80-100% violence
        if (progressPhase == 'rating') {
          progress = 0.05 + (current / total) * 0.45;
        } else if (progressPhase == 'cleaning') {
          // Base progress depends on which cleaning sub-phase
          // 4 sub-phases: language, adult, violence, verifying
          // They share the 50% cleaning portion (50% to 100%)
          double baseProgress = 0.50;
          double subPhaseWeight =
              0.125; // Each sub-phase is 12.5% of total (50% / 4)

          if (cleaningSubPhase == 'language') {
            baseProgress = 0.50;
          } else if (cleaningSubPhase == 'adult') {
            baseProgress = 0.625;
          } else if (cleaningSubPhase == 'violence') {
            baseProgress = 0.75;
          } else if (cleaningSubPhase == 'verifying') {
            baseProgress = 0.875;
          }

          progress = baseProgress + (current / total) * subPhaseWeight;
        }
      });
    }

    // Detect phase transitions
    if (line.contains('PASS A: Rating') && line.contains('chapters')) {
      final countMatch = RegExp(r'Rating (\d+) chapters').firstMatch(line);
      if (countMatch != null) {
        setState(() {
          progressPhase = 'rating';
          cleaningSubPhase = '';
          progressTotal = int.tryParse(countMatch.group(1) ?? '0') ?? 0;
          progressCurrent = 0;
        });
      }
    } else if (line.contains('CLEANING PIPELINE:') &&
        line.contains('chapters')) {
      final countMatch = RegExp(r'PIPELINE: (\d+) chapters').firstMatch(line);
      if (countMatch != null) {
        setState(() {
          progressPhase = 'cleaning';
          cleaningSubPhase = 'identifying';
          progressTotal = int.tryParse(countMatch.group(1) ?? '0') ?? 0;
          progressCurrent = 0;
          progress = 0.50; // Start cleaning at 50%
        });
      }
    } else if (line.contains('=== PASS 1: LANGUAGE CLEANING')) {
      setState(() {
        cleaningSubPhase = 'language';
        progressCurrent = 0;
      });
    } else if (line.contains('=== PASS 2: ADULT CONTENT CLEANING')) {
      setState(() {
        cleaningSubPhase = 'adult';
        progressCurrent = 0;
      });
    } else if (line.contains('=== PASS 3: VIOLENCE CLEANING')) {
      setState(() {
        cleaningSubPhase = 'violence';
        progressCurrent = 0;
      });
    } else if (line.contains('=== VERIFYING CLEANED CONTENT')) {
      // Parse count from "=== VERIFYING CLEANED CONTENT (X chapters, Y workers) ==="
      final countMatch = RegExp(r'\((\d+) chapters').firstMatch(line);
      setState(() {
        cleaningSubPhase = 'verifying';
        progressCurrent = 0;
        if (countMatch != null) {
          progressTotal = int.tryParse(countMatch.group(1) ?? '0') ?? 0;
        }
      });
    } else if (line.contains('No chapters need cleaning')) {
      setState(() {
        progressPhase = 'cleaning';
        cleaningSubPhase = '';
        progress = 1.0;
      });
    }
  }

  Future<int> _runPythonScript(String scriptPath, List<String> args) async {
    // Get the project root directory
    // The EPUB file path tells us where the actual project is
    String? workingDir;
    try {
      // Use the EPUB file's parent directory to find the project root
      if (selectedFilePath != null) {
        final epubDir = Directory(path.dirname(selectedFilePath!));
        var current = epubDir;

        // Walk up to find pubspec.yaml (project root)
        while (current.parent.path != current.path) {
          if (File('${current.path}/pubspec.yaml').existsSync()) {
            workingDir = current.path;
            break;
          }
          current = current.parent;
        }
      }

      // Fallback to current directory
      workingDir ??= Directory.current.path;

      // Verify the scripts directory exists
      if (!Directory('$workingDir/scripts').existsSync()) {
        _addLogMessage(
          '⚠️ Scripts directory not found at: $workingDir/scripts',
        );
        _addLogMessage('⚠️ Cannot find project scripts - processing will fail');
      }
    } catch (e) {
      _addLogMessage('⚠️ Working directory error: $e');
      workingDir = Directory.current.path;
    }

    _addLogMessage('🔧 Working directory: $workingDir');
    print('🔧 Working directory: $workingDir');

    // Use full path to python3 to avoid xcrun issues in sandbox
    final python3Path = '/usr/bin/python3';
    try {
      final process = await Process.start(
        python3Path,
        ['-u', scriptPath, ...args], // -u for unbuffered output
        workingDirectory: workingDir,
        environment: {
          'PYTHONUNBUFFERED': '1',
          'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', // Minimal PATH for sandbox
        }, // Also set env var for subprocess
      );

      // Stream stdout to log and parse progress
      process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            _addLogMessage(line);
            _parseProgressFromLine(line);
          });

      // Stream stderr to log
      process.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            _addLogMessage('⚠️ $line');
            print('⚠️ STDERR: $line');
          });
      return await process.exitCode;
    } catch (e) {
      _addLogMessage('❌ Failed to start Python process: $e');
      _addLogMessage(
        '💡 Make sure Python 3 is installed: brew install python3',
      );
      return 1;
    }
  }

  Future<void> _loadBookwashFile() async {
    if (generatedBookwashPath == null) return;

    try {
      final parsed = await BookWashParser.parse(generatedBookwashPath!);
      setState(() {
        bookwashFile = parsed;
        selectedReviewChapter = 0;
        currentReviewChangeIndex = 0;
      });
    } catch (e) {
      _addLogMessage('❌ Failed to load bookwash file: $e');
    }
  }

  // Parse change ID like "1.3" into sortable parts [chapter, change]
  List<int> _parseChangeId(String id) {
    final parts = id.split('.');
    if (parts.length == 2) {
      return [int.tryParse(parts[0]) ?? 0, int.tryParse(parts[1]) ?? 0];
    }
    // Fallback for old c001 format
    final match = RegExp(r'c?(\d+)').firstMatch(id);
    return [0, int.tryParse(match?.group(1) ?? '0') ?? 0];
  }

  // Get all pending changes across all chapters, sorted by ID
  List<MapEntry<int, BookWashChange>> get _allPendingChanges {
    if (bookwashFile == null) return [];
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < bookwashFile!.chapters.length; i++) {
      for (final change in bookwashFile!.chapters[i].changes) {
        if (change.status == 'pending') {
          changes.add(MapEntry(i, change));
        }
      }
    }
    // Sort by change ID (1.1, 1.2, 2.1, etc.)
    changes.sort((a, b) {
      final aId = _parseChangeId(a.value.id);
      final bId = _parseChangeId(b.value.id);
      final chapterCompare = aId[0].compareTo(bId[0]);
      if (chapterCompare != 0) return chapterCompare;
      return aId[1].compareTo(bId[1]);
    });
    return changes;
  }

  // Get all changes (for stats), sorted by ID
  List<MapEntry<int, BookWashChange>> get _allChanges {
    if (bookwashFile == null) return [];
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < bookwashFile!.chapters.length; i++) {
      for (final change in bookwashFile!.chapters[i].changes) {
        changes.add(MapEntry(i, change));
      }
    }
    // Sort by change ID (1.1, 1.2, 2.1, etc.)
    changes.sort((a, b) {
      final aId = _parseChangeId(a.value.id);
      final bId = _parseChangeId(b.value.id);
      final chapterCompare = aId[0].compareTo(bId[0]);
      if (chapterCompare != 0) return chapterCompare;
      return aId[1].compareTo(bId[1]);
    });
    return changes;
  }

  void _acceptChange(BookWashChange change, {String? editedText}) {
    setState(() {
      change.status = 'accepted';
      // If the user edited the text, update the cleaned field
      if (editedText != null && editedText != change.cleaned) {
        change.cleaned = editedText;
      }
    });
    _moveToNextChange();
    // Auto-save after each change
    _saveBookwashFile();
  }

  void _acceptAllChanges() {
    setState(() {
      for (final entry in _allPendingChanges) {
        entry.value.status = 'accepted';
      }
      currentReviewChangeIndex = 0;
    });
    _addLogMessage(
      '✅ Accepted all ${_allPendingChanges.length} pending changes',
    );
    // Auto-save after bulk accept
    _saveBookwashFile();
  }

  void _acceptAllLanguageChanges() {
    int acceptedCount = 0;
    setState(() {
      for (final entry in _allPendingChanges) {
        final change = entry.value;
        // Check if this change has the language cleaning marker
        if (change.reason.contains('language')) {
          change.status = 'accepted';
          acceptedCount++;
        }
      }
      // Reset index to be within bounds of remaining pending changes
      final remaining = _allPendingChanges.length;
      if (currentReviewChangeIndex >= remaining) {
        currentReviewChangeIndex = remaining > 0 ? 0 : 0;
      }
    });
    _addLogMessage('✅ Accepted $acceptedCount language changes');
    // Auto-save after bulk accept
    _saveBookwashFile();
  }

  void _rejectChange(BookWashChange change) {
    setState(() {
      change.status = 'rejected';
    });
    _moveToNextChange();
    // Auto-save after each change
    _saveBookwashFile();
  }

  void _moveToNextChange() {
    final pending = _allPendingChanges;
    if (pending.isEmpty) {
      // No more pending changes
      return;
    }
    // After accept/reject, the current change is removed from pending list,
    // so the same index now points to the next change. Just ensure we're in bounds.
    setState(() {
      if (currentReviewChangeIndex >= pending.length) {
        // Wrap around to start if we were at the end
        currentReviewChangeIndex = 0;
      }
      selectedReviewChapter = pending[currentReviewChangeIndex].key;
    });
  }

  Future<void> _saveBookwashFile() async {
    if (bookwashFile == null || generatedBookwashPath == null) return;

    try {
      await BookWashParser.write(bookwashFile!, generatedBookwashPath!);
      _addLogMessage(
        '💾 Saved changes to ${path.basename(generatedBookwashPath!)}',
      );
    } catch (e) {
      _addLogMessage('❌ Failed to save: $e');
    }
  }

  Future<void> _exportToEpub() async {
    if (generatedBookwashPath == null) return;

    // First save any pending changes
    await _saveBookwashFile();

    // Generate the cleaned EPUB to a temp location first
    _addLogMessage('');
    _addLogMessage('📦 Exporting to EPUB...');

    final result = await _runPythonScript('scripts/bookwash_to_epub.py', [
      generatedBookwashPath!,
    ]);

    if (result == 0) {
      // The script creates the file next to the bookwash file
      final tempEpubPath = generatedBookwashPath!.replaceAll(
        '.bookwash',
        '_cleaned.epub',
      );

      // Prompt user for save location
      final suggestedName = path.basename(tempEpubPath);
      final saveResult = await FilePicker.platform.saveFile(
        dialogTitle: 'Save Cleaned EPUB',
        fileName: suggestedName,
        type: FileType.custom,
        allowedExtensions: ['epub'],
      );

      if (saveResult != null) {
        // Copy the temp file to the chosen location
        final tempFile = File(tempEpubPath);
        if (await tempFile.exists()) {
          String finalPath = saveResult;
          // Ensure .epub extension
          if (!finalPath.toLowerCase().endsWith('.epub')) {
            finalPath = '$finalPath.epub';
          }
          await tempFile.copy(finalPath);
          _addLogMessage('✅ Saved to: $finalPath');

          // Show snackbar
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('📚 EPUB saved to: ${path.basename(finalPath)}'),
                backgroundColor: Colors.green,
                duration: const Duration(seconds: 4),
                action: SnackBarAction(
                  label: 'OK',
                  textColor: Colors.white,
                  onPressed: () {},
                ),
              ),
            );
          }
        }
      } else {
        _addLogMessage('ℹ️ Export cancelled by user');
      }
    } else {
      _addLogMessage('❌ Export failed (exit code: $result)');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('❌ Export failed'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  // Auto-scroll the log to bottom
  void _scrollToBottom() {
    if (!_autoScrollLog) return; // respect user toggle
    if (_scrollController.hasClients) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scrollController.hasClients) {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  /// Compute word-level differences between two strings
  /// Returns list of (word, isChanged) tuples
  // TODO: Remove after testing - currently unused, but may be useful for future features

  // NOTE: _buildOriginalHighlight removed - using OriginalTextHighlight widget instead

  // NOTE: _buildCleanedHighlight removed - using CleanedTextHighlight widget instead

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            const Text('BookWash - EPUB Content Cleaner'),
            Text(
              'Build: $_buildTime',
              style: const TextStyle(fontSize: 10, color: Colors.grey),
            ),
          ],
        ),
        centerTitle: true,
        elevation: 0,
        actions: [
          // Gemini API Key button
          IconButton(
            icon: Icon(
              geminiApiKey.isEmpty ? Icons.key_off : Icons.key,
              color: geminiApiKey.isEmpty ? Colors.red : Colors.green,
            ),
            tooltip: geminiApiKey.isEmpty
                ? 'Set Gemini API Key'
                : 'API Key Set',
            onPressed: _showGeminiApiKeyDialog,
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // File Selection Section
            FileSelectionCard(
              isLoading: isLoadingFile,
              isProcessing: isProcessing,
              fileName: selectedFileName,
              parsedEpub: parsedEpub,
              onSelectFile: selectFile,
            ),
            const SizedBox(height: 20),

            // Sensitivity Sliders Section
            SensitivitySettingsCard(
              languageWordSelection: languageWordSelection,
              isProcessing: isProcessing,
              sexualContentLevel: sexualContentLevel,
              violenceLevel: violenceLevel,
              onWordChanged: (word, value) {
                setState(() {
                  languageWordSelection[word] = value;
                });
              },
              onSaveWords: _saveLanguageWords,
              onSexualLevelChanged: (v) {
                setState(() => sexualContentLevel = v);
                _saveLevel('sexual_level', v);
              },
              onViolenceLevelChanged: (v) {
                setState(() => violenceLevel = v);
                _saveLevel('violence_level', v);
              },
            ),
            const SizedBox(height: 20),

            // Debug info (remove after testing)
            Text(
              'State: isProcessing=$isProcessing, cleanedParagraphs=${cleanedParagraphs.length}, isCancelling=$isCancelling',
              style: const TextStyle(fontSize: 10, color: Colors.grey),
            ),
            const SizedBox(height: 8),

            // Process/Cancel Buttons
            ProcessingButtons(
              isProcessing: isProcessing,
              isCancelling: isCancelling,
              canProcess: parsedEpub != null && !isLoadingFile,
              onProcess: processBook,
              onCancel: cancelProcessing,
            ),

            const SizedBox(height: 20),

            // Progress Section
            if (isProcessing || progress > 0)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        progressPhase == 'converting'
                            ? 'Step 3: Converting to BookWash Format'
                            : progressPhase == 'rating'
                            ? 'Step 3: Rating Chapters'
                            : progressPhase == 'cleaning'
                            ? 'Step 3: Cleaning Chapters'
                            : progressPhase == 'complete'
                            ? 'Step 3: Complete'
                            : 'Step 3: Processing',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      // Segmented progress bar for cleaning
                      if (progressPhase == 'cleaning') ...[
                        // Show 5-segment progress bar for cleaning phases
                        Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      CleaningPhaseSegment(
                                        label: 'Identify',
                                        isActive:
                                            cleaningSubPhase == 'identifying',
                                        isComplete:
                                            cleaningSubPhase == 'language' ||
                                            cleaningSubPhase == 'adult' ||
                                            cleaningSubPhase == 'violence' ||
                                            cleaningSubPhase == 'verifying',
                                        color: Colors.orange,
                                      ),
                                      const SizedBox(width: 4),
                                      CleaningPhaseSegment(
                                        label: 'Language',
                                        isActive:
                                            cleaningSubPhase == 'language',
                                        isComplete:
                                            cleaningSubPhase == 'adult' ||
                                            cleaningSubPhase == 'violence' ||
                                            cleaningSubPhase == 'verifying',
                                        color: Colors.purple,
                                      ),
                                      const SizedBox(width: 4),
                                      CleaningPhaseSegment(
                                        label: 'Adult',
                                        isActive: cleaningSubPhase == 'adult',
                                        isComplete:
                                            cleaningSubPhase == 'violence' ||
                                            cleaningSubPhase == 'verifying',
                                        color: Colors.pink,
                                      ),
                                      const SizedBox(width: 4),
                                      CleaningPhaseSegment(
                                        label: 'Violence',
                                        isActive:
                                            cleaningSubPhase == 'violence',
                                        isComplete:
                                            cleaningSubPhase == 'verifying',
                                        color: Colors.red,
                                      ),
                                      const SizedBox(width: 4),
                                      CleaningPhaseSegment(
                                        label: 'Verify',
                                        isActive:
                                            cleaningSubPhase == 'verifying',
                                        isComplete: false,
                                        color: Colors.teal,
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),
                                  LinearProgressIndicator(
                                    value: progress,
                                    minHeight: 8,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ] else ...[
                        LinearProgressIndicator(value: progress, minHeight: 8),
                      ],
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Text(
                            '${(progress * 100).toStringAsFixed(0)}% Complete',
                            style: const TextStyle(
                              fontSize: 14,
                              color: Colors.grey,
                            ),
                          ),
                          const SizedBox(width: 16),
                          if (progressPhase.isNotEmpty &&
                              progressPhase != 'complete')
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: progressPhase == 'rating'
                                    ? Colors.blue.withOpacity(0.2)
                                    : progressPhase == 'cleaning'
                                    ? _getCleaningSubPhaseColor().withOpacity(
                                        0.2,
                                      )
                                    : Colors.grey.withOpacity(0.2),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                _getProgressStatusText(),
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w500,
                                  color: progressPhase == 'rating'
                                      ? Colors.blue
                                      : progressPhase == 'cleaning'
                                      ? _getCleaningSubPhaseColor()
                                      : Colors.grey,
                                ),
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      // Live logging display
                      if (liveLogMessages.isNotEmpty)
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: const Text(
                                    'Live Processing Log:',
                                    style: TextStyle(
                                      fontSize: 14,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                                Row(
                                  children: [
                                    const Text(
                                      'Auto-scroll',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                    Switch(
                                      value: _autoScrollLog,
                                      onChanged: (val) {
                                        setState(() {
                                          _autoScrollLog = val;
                                        });
                                        if (val) {
                                          // If re-enabled, jump immediately
                                          WidgetsBinding.instance
                                              .addPostFrameCallback((_) {
                                                if (_scrollController
                                                    .hasClients) {
                                                  _scrollController.jumpTo(
                                                    _scrollController
                                                        .position
                                                        .maxScrollExtent,
                                                  );
                                                }
                                              });
                                        }
                                      },
                                      materialTapTargetSize:
                                          MaterialTapTargetSize.shrinkWrap,
                                    ),
                                    TextButton(
                                      onPressed: () {
                                        if (_scrollController.hasClients) {
                                          _scrollController.animateTo(
                                            _scrollController
                                                .position
                                                .maxScrollExtent,
                                            duration: const Duration(
                                              milliseconds: 250,
                                            ),
                                            curve: Curves.easeOut,
                                          );
                                        }
                                      },
                                      child: const Text(
                                        'Jump to bottom',
                                        style: TextStyle(fontSize: 12),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Container(
                              height: 150,
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Colors.black.withOpacity(0.3),
                                borderRadius: BorderRadius.circular(4),
                                border: Border.all(
                                  color: Colors.orange.withOpacity(0.5),
                                ),
                              ),
                              child: ListView.builder(
                                controller: _scrollController,
                                itemCount: liveLogMessages.length,
                                itemBuilder: (context, index) {
                                  final log = liveLogMessages[index];
                                  return Padding(
                                    padding: const EdgeInsets.symmetric(
                                      vertical: 2,
                                    ),
                                    child: SelectableText(
                                      log,
                                      style: const TextStyle(
                                        fontSize: 11,
                                        fontFamily: 'monospace',
                                        color: Colors.orange,
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ),
                            const SizedBox(height: 16),
                          ],
                        ),
                    ],
                  ),
                ),
              ),

            // Review Changes Section - shows after processing with bookwash file
            if (bookwashFile != null && !isProcessing)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.rate_review, size: 24),
                          const SizedBox(width: 8),
                          const Text(
                            'Step 4: Review Changes',
                            style: TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          const Spacer(),
                          // Stats
                          ReviewStatChip(
                            label: 'Pending',
                            count: _allPendingChanges.length,
                            color: Colors.orange,
                          ),
                          const SizedBox(width: 8),
                          ReviewStatChip(
                            label: 'Accepted',
                            count: _allChanges
                                .where((c) => c.value.status == 'accepted')
                                .length,
                            color: Colors.green,
                          ),
                          const SizedBox(width: 8),
                          ReviewStatChip(
                            label: 'Rejected',
                            count: _allChanges
                                .where((c) => c.value.status == 'rejected')
                                .length,
                            color: Colors.red,
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),

                      // Chapter selector and change review
                      if (_allPendingChanges.isNotEmpty) ...[
                        // Current change display
                        ChangeReviewPanel(
                          chapter:
                              bookwashFile!
                                  .chapters[_allPendingChanges[currentReviewChangeIndex]
                                  .key],
                          change: _allPendingChanges[currentReviewChangeIndex]
                              .value,
                          onKeepOriginal: () => _rejectChange(
                            _allPendingChanges[currentReviewChangeIndex].value,
                          ),
                          onKeepCleaned: (editedText) => _acceptChange(
                            _allPendingChanges[currentReviewChangeIndex].value,
                            editedText: editedText,
                          ),
                        ),
                        const SizedBox(height: 16),
                        // Navigation and action buttons - fixed layout to prevent jumping
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            // Left side: Navigation controls with fixed width
                            SizedBox(
                              width: 320,
                              child: Row(
                                children: [
                                  ElevatedButton.icon(
                                    onPressed: currentReviewChangeIndex > 0
                                        ? () {
                                            setState(() {
                                              currentReviewChangeIndex--;
                                              selectedReviewChapter =
                                                  _allPendingChanges[currentReviewChangeIndex]
                                                      .key;
                                            });
                                          }
                                        : null,
                                    icon: const Icon(Icons.arrow_back),
                                    label: const Text('Previous'),
                                  ),
                                  const SizedBox(width: 8),
                                  // Fixed width for counter to prevent shifting
                                  SizedBox(
                                    width: 70,
                                    child: Text(
                                      '${currentReviewChangeIndex + 1} / ${_allPendingChanges.length}',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.bold,
                                      ),
                                      textAlign: TextAlign.center,
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  ElevatedButton.icon(
                                    onPressed:
                                        currentReviewChangeIndex <
                                            _allPendingChanges.length - 1
                                        ? () {
                                            setState(() {
                                              currentReviewChangeIndex++;
                                              selectedReviewChapter =
                                                  _allPendingChanges[currentReviewChangeIndex]
                                                      .key;
                                            });
                                          }
                                        : null,
                                    icon: const Icon(Icons.arrow_forward),
                                    label: const Text('Next'),
                                  ),
                                ],
                              ),
                            ),
                            // Right side: Action buttons - always at same position
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                ElevatedButton.icon(
                                  onPressed: _acceptAllLanguageChanges,
                                  icon: const Text(
                                    '#!@',
                                    style: TextStyle(
                                      fontSize: 14,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                  label: const Text('Accept All Language'),
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: const Color(0xFF7B1FA2),
                                    foregroundColor: Colors.white,
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 16,
                                      vertical: 12,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                ElevatedButton.icon(
                                  onPressed: _acceptAllChanges,
                                  icon: const Icon(Icons.done_all, size: 18),
                                  label: const Text('Accept All'),
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: const Color(0xFF1976D2),
                                    foregroundColor: Colors.white,
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 16,
                                      vertical: 12,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ] else ...[
                        const Center(
                          child: Padding(
                            padding: EdgeInsets.all(24.0),
                            child: Column(
                              children: [
                                Icon(
                                  Icons.check_circle,
                                  size: 48,
                                  color: Colors.green,
                                ),
                                SizedBox(height: 8),
                                Text(
                                  'All changes reviewed!',
                                  style: TextStyle(fontSize: 16),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),

            // Export EPUB Button - shows after processing
            if (bookwashFile != null && !isProcessing) ...[
              const SizedBox(height: 20),
              ExportEpubButton(onExport: _exportToEpub),
            ],
          ],
        ),
      ),
    );
  }

  // NOTE: _buildCleaningPhaseSegment removed - using CleaningPhaseSegment widget instead

  // Helper method to get cleaning sub-phase color
  Color _getCleaningSubPhaseColor() {
    switch (cleaningSubPhase) {
      case 'language':
        return Colors.purple;
      case 'adult':
        return Colors.pink;
      case 'violence':
        return Colors.red;
      case 'identifying':
        return Colors.orange;
      case 'verifying':
        return Colors.teal;
      default:
        return Colors.orange;
    }
  }

  // Helper method to get progress status text
  String _getProgressStatusText() {
    if (progressPhase == 'converting') {
      return '📝 Converting...';
    } else if (progressPhase == 'rating') {
      return '📊 Rating${progressTotal > 0 ? ' $progressCurrent/$progressTotal chapters' : '...'}';
    } else if (progressPhase == 'cleaning') {
      String subPhaseLabel = '';
      switch (cleaningSubPhase) {
        case 'identifying':
          subPhaseLabel = '🔍 Identifying content';
          break;
        case 'language':
          subPhaseLabel = '💬 Language cleaning';
          break;
        case 'adult':
          subPhaseLabel = '🔞 Adult content cleaning';
          break;
        case 'violence':
          subPhaseLabel = '⚔️ Violence cleaning';
          break;
        case 'verifying':
          subPhaseLabel = '✅ Verifying cleaned content';
          break;
        default:
          subPhaseLabel = '🧹 Cleaning';
      }
      return '$subPhaseLabel${progressTotal > 0 ? ' ($progressCurrent/$progressTotal)' : '...'}';
    }
    return progressPhase;
  }

  // NOTE: _buildReviewStatChip removed - using ReviewStatChip widget instead

  // NOTE: _buildCurrentChangeReview removed - using ChangeReviewPanel widget instead

  // NOTE: _buildLanguageWordFilter removed - using LanguageWordFilter widget instead

  // NOTE: _buildWordGroup removed - part of LanguageWordFilter widget

  // NOTE: _buildSliderSection removed - using ContentLevelSlider widget instead
}
