import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:path/path.dart' as path;
import 'package:shared_preferences/shared_preferences.dart';
import 'models/bookwash_file.dart';
import 'services/bookwash_parser.dart';
import 'services/epub_parser.dart';
import 'services/epub_writer.dart';
import 'models/chunk_change.dart';

void main() {
  runApp(const BookWashApp());
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
  int profanityLevel = 2; // Default: PG language
  int sexualContentLevel = 2; // Default: PG sexual content
  int violenceLevel = 5; // Default: Unrated violence (no censorship)
  bool isProcessing = false;
  bool isCancelling = false;
  double progress = 0.0;
  String progressPhase = ''; // 'converting', 'rating', 'cleaning'
  int progressCurrent = 0;
  int progressTotal = 0;
  bool showDetails = false;

  // Gemini API key for Python script
  String geminiApiKey = '';

  // Model selection
  String selectedModel = 'gemini-1.5-flash'; // Default Gemini model

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

  // Debug comparisons (per paragraph)
  // key: unique id "chapterIndex:paragraphIndex"; value: [original, cleaned]
  final Map<String, List<String>> _paraComparisons = {};
  final Set<String> _revealedComparisons = {};

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

  @override
  void initState() {
    super.initState();
    _loadSavedApiKey();
    _loadSavedLevels();
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
      profanityLevel = prefs.getInt('profanity_level') ?? profanityLevel;
      sexualContentLevel = prefs.getInt('sexual_level') ?? sexualContentLevel;
      violenceLevel = prefs.getInt('violence_level') ?? violenceLevel;
    });
  }

  Future<void> _saveLevel(String key, int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(key, value);
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
      withData: true, // Important for web - loads bytes
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
    if (selectedFilePath == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select an EPUB file first')),
      );
      return;
    }

    // Check if Gemini API key is set
    if (geminiApiKey.isEmpty) {
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

    try {
      // Determine bookwash output path
      final epubPath = selectedFilePath!;
      final bookwashPath = epubPath.replaceAll('.epub', '.bookwash');

      _addLogMessage('📚 Starting BookWash processing...');
      _addLogMessage('📖 Input: ${path.basename(epubPath)}');

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
      _addLogMessage(
        'Target levels: Language=${_levelToRating(profanityLevel)}, Adult=${_levelToRating(sexualContentLevel)}, Violence=${_levelToRating(violenceLevel)}',
      );

      final llmResult = await _runPythonScript('scripts/bookwash_llm.py', [
        '--rate',
        '--clean',
        bookwashPath,
        '--api-key',
        geminiApiKey,
        '--model',
        selectedModel,
        '--language',
        profanityLevel.toString(),
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
        if (progressPhase == 'rating') {
          progress = 0.05 + (current / total) * 0.45;
        } else if (progressPhase == 'cleaning') {
          progress = 0.50 + (current / total) * 0.50;
        }
      });
    }

    // Detect phase transitions
    if (line.contains('Rating') && line.contains('chapters...')) {
      final countMatch = RegExp(r'Rating (\d+) chapters').firstMatch(line);
      if (countMatch != null) {
        setState(() {
          progressPhase = 'rating';
          progressTotal = int.tryParse(countMatch.group(1) ?? '0') ?? 0;
          progressCurrent = 0;
        });
      }
    } else if (line.contains('Cleaning') && line.contains('chapters...')) {
      final countMatch = RegExp(r'Cleaning (\d+) chapters').firstMatch(line);
      if (countMatch != null) {
        setState(() {
          progressPhase = 'cleaning';
          progressTotal = int.tryParse(countMatch.group(1) ?? '0') ?? 0;
          progressCurrent = 0;
          progress = 0.50; // Start cleaning at 50%
        });
      }
    } else if (line.contains('No chapters need cleaning')) {
      setState(() {
        progressPhase = 'cleaning';
        progress = 1.0;
      });
    }
  }

  Future<int> _runPythonScript(String scriptPath, List<String> args) async {
    final process = await Process.start(
      'python3',
      ['-u', scriptPath, ...args], // -u for unbuffered output
      workingDirectory: path
          .dirname(Platform.script.toFilePath())
          .replaceAll('/lib', ''),
      environment: {'PYTHONUNBUFFERED': '1'}, // Also set env var for subprocess
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
        });

    return await process.exitCode;
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

  // Get all pending changes across all chapters
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
    return changes;
  }

  // Get all changes (for stats)
  List<MapEntry<int, BookWashChange>> get _allChanges {
    if (bookwashFile == null) return [];
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < bookwashFile!.chapters.length; i++) {
      for (final change in bookwashFile!.chapters[i].changes) {
        changes.add(MapEntry(i, change));
      }
    }
    return changes;
  }

  void _acceptChange(BookWashChange change) {
    setState(() {
      change.status = 'accepted';
    });
    _moveToNextChange();
  }

  void _rejectChange(BookWashChange change) {
    setState(() {
      change.status = 'rejected';
    });
    _moveToNextChange();
  }

  void _moveToNextChange() {
    final pending = _allPendingChanges;
    if (currentReviewChangeIndex < pending.length - 1) {
      setState(() {
        currentReviewChangeIndex++;
        selectedReviewChapter = pending[currentReviewChangeIndex].key;
      });
    } else if (pending.isNotEmpty) {
      setState(() {
        currentReviewChangeIndex = 0;
        selectedReviewChapter = pending[0].key;
      });
    }
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

    _addLogMessage('');
    _addLogMessage('📦 Exporting to EPUB...');

    final result = await _runPythonScript('scripts/bookwash_to_epub.py', [
      generatedBookwashPath!,
    ]);

    if (result == 0) {
      final epubPath = generatedBookwashPath!.replaceAll(
        '.bookwash',
        '_cleaned.epub',
      );
      _addLogMessage('✅ Exported to: ${path.basename(epubPath)}');
    } else {
      _addLogMessage('❌ Export failed (exit code: $result)');
    }
  }

  // Auto-scroll the log to bottom
  void _scrollToBottom() {
    if (!_autoScrollLog) return; // respect user toggle
    if (_scrollController.hasClients) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BookWash - EPUB Content Cleaner'),
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
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Step 1: Select EPUB File',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 12),
                    if (isLoadingFile)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.blue.withOpacity(0.1),
                          border: Border.all(color: Colors.blue),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Row(
                          children: [
                            SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                            SizedBox(width: 12),
                            Text('Loading EPUB...'),
                          ],
                        ),
                      )
                    else if (selectedFileName != null && parsedEpub != null)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.green.withOpacity(0.1),
                          border: Border.all(color: Colors.green),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const Icon(
                                  Icons.check_circle,
                                  color: Colors.green,
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    selectedFileName!,
                                    style: const TextStyle(color: Colors.green),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${parsedEpub!.chapters.length} chapters, ${parsedEpub!.totalParagraphs} paragraphs',
                              style: TextStyle(
                                fontSize: 12,
                                color: Colors.green[300],
                              ),
                            ),
                          ],
                        ),
                      )
                    else
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.grey.withOpacity(0.1),
                          border: Border.all(color: Colors.grey),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'No file selected',
                          style: TextStyle(color: Colors.grey),
                        ),
                      ),
                    const SizedBox(height: 12),
                    ElevatedButton.icon(
                      onPressed: (isProcessing || isLoadingFile)
                          ? null
                          : selectFile,
                      icon: isLoadingFile
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.folder_open),
                      label: Text(
                        isLoadingFile ? 'Loading...' : 'Browse EPUB Files',
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Sensitivity Sliders Section
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Step 2: Set Sensitivity Levels',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Language',
                      profanityLevel,
                      (value) {
                        final v = value.toInt();
                        setState(() => profanityLevel = v);
                        _saveLevel('profanity_level', v);
                      },
                      [
                        '1 - G: No profanity or crude language • Modifies PG and above',
                        '2 - PG: Mild language allowed • Modifies PG-13 and above',
                        '3 - PG-13: Some strong language • Modifies R-rated content only',
                        '4 - Unfiltered: No modifications',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Adult Content',
                      sexualContentLevel,
                      (value) {
                        final v = value.toInt();
                        setState(() => sexualContentLevel = v);
                        _saveLevel('sexual_level', v);
                      },
                      [
                        '1 - G: No adult content allowed • Modifies PG and above',
                        '2 - PG: Light romance only • Modifies PG-13 and above',
                        '3 - PG-13: Romantic scenes allowed • Modifies R-rated content only',
                        '4 - Unfiltered: No modifications',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Violence',
                      violenceLevel,
                      (value) {
                        final v = value.toInt();
                        setState(() => violenceLevel = v);
                        _saveLevel('violence_level', v);
                      },
                      [
                        '1 - G: No violence • Modifies PG and above',
                        '2 - PG: Mild conflict only • Modifies PG-13 and above',
                        '3 - PG-13: Action/combat allowed • Modifies R-rated content only',
                        '4 - Unfiltered: No modifications',
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Debug info (remove after testing)
            Text(
              'State: isProcessing=$isProcessing, cleanedParagraphs=${cleanedParagraphs.length}, isCancelling=$isCancelling',
              style: const TextStyle(fontSize: 10, color: Colors.grey),
            ),
            const SizedBox(height: 8),

            // Process/Cancel Buttons
            if (!isProcessing)
              ElevatedButton.icon(
                onPressed: (parsedEpub == null || isLoadingFile)
                    ? null
                    : processBook,
                icon: const Icon(Icons.cleaning_services),
                label: const Text('Clean Book'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
              )
            else
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: null,
                      icon: const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      label: const Text('Processing...'),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  ElevatedButton.icon(
                    onPressed: isCancelling ? null : cancelProcessing,
                    icon: const Icon(Icons.cancel),
                    label: Text(isCancelling ? 'Cancelling...' : 'Cancel'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      backgroundColor: Colors.red.withOpacity(0.8),
                    ),
                  ),
                ],
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
                      const Text(
                        'Step 3: Processing',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      LinearProgressIndicator(value: progress, minHeight: 8),
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
                                    ? Colors.orange.withOpacity(0.2)
                                    : Colors.grey.withOpacity(0.2),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                progressPhase == 'converting'
                                    ? '📝 Converting...'
                                    : progressPhase == 'rating'
                                    ? '📊 Rating${progressTotal > 0 ? ' $progressCurrent/$progressTotal chapters' : '...'}'
                                    : progressPhase == 'cleaning'
                                    ? '🧹 Cleaning${progressTotal > 0 ? ' $progressCurrent/$progressTotal chapters' : '...'}'
                                    : progressPhase,
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w500,
                                  color: progressPhase == 'rating'
                                      ? Colors.blue
                                      : progressPhase == 'cleaning'
                                      ? Colors.orange
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
                                  int? chapterForLog;
                                  int? paraForLog;
                                  final chMatch = RegExp(
                                    r'Chapter\s+(\d+)',
                                  ).firstMatch(log);
                                  if (chMatch != null) {
                                    chapterForLog = int.tryParse(
                                      chMatch.group(1)!,
                                    );
                                  }
                                  final paraMatch = RegExp(
                                    r'paragraph\s+(\d+)',
                                  ).firstMatch(log.toLowerCase());
                                  if (paraMatch != null) {
                                    paraForLog = int.tryParse(
                                      paraMatch.group(1)!,
                                    );
                                  }
                                  String? key;
                                  if (chapterForLog != null &&
                                      paraForLog != null) {
                                    key =
                                        '${chapterForLog - 1}:${paraForLog - 1}';
                                  }
                                  final hasComparison =
                                      key != null &&
                                      _paraComparisons.containsKey(key);

                                  return Padding(
                                    padding: const EdgeInsets.symmetric(
                                      vertical: 4,
                                    ),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          log,
                                          style: const TextStyle(
                                            fontSize: 11,
                                            fontFamily: 'monospace',
                                            color: Colors.orange,
                                          ),
                                        ),
                                        if (hasComparison)
                                          Row(
                                            children: [
                                              TextButton(
                                                onPressed: () {
                                                  setState(() {
                                                    if (key == null) return;
                                                    if (_revealedComparisons
                                                        .contains(key)) {
                                                      _revealedComparisons
                                                          .remove(key);
                                                    } else {
                                                      _revealedComparisons.add(
                                                        key,
                                                      );
                                                    }
                                                  });
                                                },
                                                child: Text(
                                                  _revealedComparisons.contains(
                                                        key,
                                                      )
                                                      ? 'Hide original content'
                                                      : 'Reveal original content',
                                                ),
                                              ),
                                            ],
                                          ),
                                        if (hasComparison &&
                                            _revealedComparisons.contains(key))
                                          Container(
                                            margin: const EdgeInsets.only(
                                              top: 6,
                                            ),
                                            padding: const EdgeInsets.all(8),
                                            decoration: BoxDecoration(
                                              color: Colors.black.withOpacity(
                                                0.2,
                                              ),
                                              borderRadius:
                                                  BorderRadius.circular(4),
                                              border: Border.all(
                                                color: Colors.orange
                                                    .withOpacity(0.3),
                                              ),
                                            ),
                                            child: Row(
                                              crossAxisAlignment:
                                                  CrossAxisAlignment.start,
                                              children: [
                                                Expanded(
                                                  child: Column(
                                                    crossAxisAlignment:
                                                        CrossAxisAlignment
                                                            .start,
                                                    children: [
                                                      const Text(
                                                        'Original',
                                                        style: TextStyle(
                                                          fontWeight:
                                                              FontWeight.bold,
                                                        ),
                                                      ),
                                                      const SizedBox(height: 4),
                                                      Text(
                                                        _paraComparisons[key]![0],
                                                        style: const TextStyle(
                                                          fontSize: 11,
                                                        ),
                                                      ),
                                                    ],
                                                  ),
                                                ),
                                                const SizedBox(width: 12),
                                                Expanded(
                                                  child: Column(
                                                    crossAxisAlignment:
                                                        CrossAxisAlignment
                                                            .start,
                                                    children: [
                                                      const Text(
                                                        'Cleaned',
                                                        style: TextStyle(
                                                          fontWeight:
                                                              FontWeight.bold,
                                                        ),
                                                      ),
                                                      const SizedBox(height: 4),
                                                      Text(
                                                        _paraComparisons[key]![1],
                                                        style: const TextStyle(
                                                          fontSize: 11,
                                                        ),
                                                      ),
                                                    ],
                                                  ),
                                                ),
                                              ],
                                            ),
                                          ),
                                      ],
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
                          _buildReviewStatChip(
                            'Pending',
                            _allPendingChanges.length,
                            Colors.orange,
                          ),
                          const SizedBox(width: 8),
                          _buildReviewStatChip(
                            'Accepted',
                            _allChanges
                                .where((c) => c.value.status == 'accepted')
                                .length,
                            Colors.green,
                          ),
                          const SizedBox(width: 8),
                          _buildReviewStatChip(
                            'Rejected',
                            _allChanges
                                .where((c) => c.value.status == 'rejected')
                                .length,
                            Colors.red,
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),

                      // Chapter selector and change review
                      if (_allPendingChanges.isNotEmpty) ...[
                        // Current change display
                        _buildCurrentChangeReview(),
                        const SizedBox(height: 16),
                        // Navigation and action buttons
                        Row(
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
                            Text(
                              '${currentReviewChangeIndex + 1} / ${_allPendingChanges.length}',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
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
                            const Spacer(),
                            ElevatedButton.icon(
                              onPressed: () => _rejectChange(
                                _allPendingChanges[currentReviewChangeIndex]
                                    .value,
                              ),
                              icon: const Icon(Icons.close),
                              label: const Text('Reject'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: Colors.red,
                              ),
                            ),
                            const SizedBox(width: 8),
                            ElevatedButton.icon(
                              onPressed: () => _acceptChange(
                                _allPendingChanges[currentReviewChangeIndex]
                                    .value,
                              ),
                              icon: const Icon(Icons.check),
                              label: const Text('Accept'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: Colors.green,
                              ),
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
              ElevatedButton.icon(
                onPressed: _exportToEpub,
                icon: const Icon(Icons.download),
                label: const Text('Export EPUB'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: Colors.teal,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildReviewStatChip(String label, int count, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        '$label: $count',
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  Widget _buildCurrentChangeReview() {
    if (_allPendingChanges.isEmpty ||
        currentReviewChangeIndex >= _allPendingChanges.length) {
      return const SizedBox.shrink();
    }

    final entry = _allPendingChanges[currentReviewChangeIndex];
    final chapterIndex = entry.key;
    final change = entry.value;
    final chapter = bookwashFile!.chapters[chapterIndex];

    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade700),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Chapter header
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.grey.shade800,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(7),
                topRight: Radius.circular(7),
              ),
            ),
            child: Row(
              children: [
                const Icon(Icons.book, size: 16),
                const SizedBox(width: 8),
                Text(
                  'Chapter ${chapterIndex + 1}: ${chapter.title}',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(width: 8),
                Text(
                  '(Change ${change.id})',
                  style: TextStyle(color: Colors.grey.shade400, fontSize: 12),
                ),
              ],
            ),
          ),
          // Side-by-side comparison
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Original
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.withOpacity(0.1),
                      border: Border.all(color: Colors.red.withOpacity(0.3)),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Original',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Colors.red,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          change.original,
                          style: const TextStyle(fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                // Cleaned
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.green.withOpacity(0.1),
                      border: Border.all(color: Colors.green.withOpacity(0.3)),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Cleaned',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Colors.green,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          change.cleaned,
                          style: const TextStyle(fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSliderSection(
    String title,
    int currentValue,
    Function(double) onChanged,
    List<String> labels,
  ) {
    // Extract "G Rated", "PG Rated", etc. from the label.
    final ratingName = labels[currentValue - 1]
        .split(':')[0]
        .substring(4)
        .trim();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
            ),
            Text(
              ratingName,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: Colors.blue[300],
              ),
            ),
          ],
        ),
        Slider(
          value: currentValue.toDouble(),
          min: 1,
          max: 4,
          divisions: 3,
          label: ratingName,
          onChanged: onChanged,
        ),
        Text(
          labels[currentValue - 1],
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey[600],
            fontStyle: FontStyle.italic,
          ),
        ),
      ],
    );
  }
}
