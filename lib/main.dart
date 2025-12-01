import 'package:bookwash/models/change_detail.dart';
// import 'package:bookwash/models/categorized_changes.dart';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'services/epub_parser.dart';
import 'services/epub_writer.dart';
import 'services/ollama_service.dart';
import 'services/gemini_service.dart';
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
  bool showDetails = false;

  // AI Provider selection
  String selectedProvider = 'gemini'; // 'ollama' or 'gemini'
  String geminiApiKey = ''; // User will need to provide this

  // Service instances
  late OllamaService ollamaService;
  GeminiService? geminiService;

  // Model selection
  List<String> availableModels = [];
  String selectedModel = 'gemini-2.0-flash-exp'; // Default Gemini model
  bool isLoadingModels = false;

  // Processing statistics
  int totalParagraphs = 0;
  int processedParagraphs = 0;
  int modifiedParagraphs = 0;

  // Change details
  List<ChangeDetail> allCategorizedChanges = [];

  // Removal summaries by level
  Map<String, Map<int, int>> removalCounts = {
    'profanity': {1: 0, 2: 0, 3: 0, 4: 0},
    'sexual': {1: 0, 2: 0, 3: 0, 4: 0},
    'violence': {1: 0, 2: 0, 3: 0, 4: 0},
  };

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
    ollamaService = OllamaService(model: selectedModel);
    _loadSavedApiKey();
    _loadSavedLevels();
    _loadAvailableModels();
  }

  Future<void> _loadSavedApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    final savedKey = prefs.getString('gemini_api_key') ?? '';
    if (savedKey.isNotEmpty) {
      setState(() {
        geminiApiKey = savedKey;
        geminiService = GeminiService(apiKey: geminiApiKey);
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

  Future<void> _loadAvailableModels() async {
    setState(() {
      isLoadingModels = true;
    });

    try {
      List<String> models;
      if (selectedProvider == 'ollama') {
        models = await ollamaService.getAvailableModels();
        if (models.isEmpty) {
          models = ['qwen3:8b', 'phi3:mini', 'qwen3-coder:30b'];
        }
      } else {
        // Gemini models - Only free tier models
        models = [
          'gemini-2.0-flash-exp', // Best free tier: 1500 RPD, 10 RPM
          'gemini-1.5-flash', // Good free tier: 1500 RPD, 15 RPM
        ];
      }

      setState(() {
        availableModels = models;
        isLoadingModels = false;
        // If current model not in list, use first available
        if (models.isNotEmpty && !models.contains(selectedModel)) {
          selectedModel = models.first;
          if (selectedProvider == 'ollama') {
            ollamaService = OllamaService(model: selectedModel);
          }
        }
      });
    } catch (e) {
      print('Failed to load models: $e');
      setState(() {
        isLoadingModels = false;
        // Fallback to default models if fetch fails
        if (selectedProvider == 'ollama') {
          availableModels = ['qwen3:8b', 'phi3:mini', 'qwen3-coder:30b'];
        } else {
          availableModels = ['gemini-2.0-flash-exp', 'gemini-1.5-flash'];
        }
      });
    }
  }

  void _onModelChanged(String? newModel) {
    if (newModel != null && newModel != selectedModel) {
      setState(() {
        selectedModel = newModel;
        if (selectedProvider == 'ollama') {
          ollamaService = OllamaService(model: selectedModel);
        } else if (geminiService != null) {
          geminiService = GeminiService(
            apiKey: geminiApiKey,
            model: selectedModel,
          );
        }
      });
    }
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
        geminiService = GeminiService(apiKey: geminiApiKey);
        selectedModel = 'gemini-2.0-flash-exp';
      });
      await _loadAvailableModels();
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
    if (parsedEpub == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select an EPUB file first')),
      );
      return;
    }

    // Check Ollama connection first
    final isConnected = await ollamaService.checkConnection();
    if (!isConnected) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Cannot connect to Ollama. Please ensure Ollama is running (ollama serve)',
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
      totalParagraphs = 0;
      processedParagraphs = 0;
      modifiedParagraphs = 0;
      removalCounts = {
        'profanity': {1: 0, 2: 0, 3: 0, 4: 0},
        'sexual': {1: 0, 2: 0, 3: 0, 4: 0},
        'violence': {1: 0, 2: 0, 3: 0, 4: 0},
      };
      removalDetails = [];
      liveLogMessages = [];
      cleanedParagraphs = [];
      paragraphToChapter = {};
      cleanedParagraphToChapter = {};
      pendingChanges = [];
      currentReviewIndex = 0;
      allCategorizedChanges = [];
    });

    try {
      print(
        'Starting book processing with ${selectedProvider == 'gemini' ? 'Gemini' : 'Ollama'}...',
      );

      setState(() {
        totalParagraphs = parsedEpub!.chapters.fold(
          0,
          (sum, chapter) => sum + chapter.paragraphs.length,
        );
      });

      print('Total paragraphs to process: $totalParagraphs');

      // Determine chunking strategy based on provider
      if (selectedProvider == 'gemini') {
        // Gemini: Process chapter by chapter
        await _processChapterByChapter();
      } else {
        // Ollama: Process paragraph by paragraph (original behavior)
        // Collect all paragraphs first for Ollama
        final allParagraphs = <String>[];
        for (
          int chapterIdx = 0;
          chapterIdx < parsedEpub!.chapters.length;
          chapterIdx++
        ) {
          final chapter = parsedEpub!.chapters[chapterIdx];
          for (final paragraph in chapter.paragraphs) {
            paragraphToChapter[allParagraphs.length] = chapterIdx;
            allParagraphs.add(paragraph);
          }
        }
        await _processParagraphByParagraph(allParagraphs);
      }
      print('Finished processing - Cancelled: $isCancelling');

      // Debug: Show chapter mapping summary
      final chapterCounts = <int, int>{};
      for (final chapterIdx in cleanedParagraphToChapter.values) {
        chapterCounts[chapterIdx] = (chapterCounts[chapterIdx] ?? 0) + 1;
      }
      print('DEBUG: Chapter mapping summary:');
      for (final entry in chapterCounts.entries) {
        print('  Chapter ${entry.key}: ${entry.value} paragraphs');
      }
      print('DEBUG: Total cleaned paragraphs: ${cleanedParagraphs.length}');
      print(
        'DEBUG: Total chapters in original: ${parsedEpub!.chapters.length}',
      );

      // Show summary if changes were made
      if (!isCancelling && allCategorizedChanges.isNotEmpty) {
        _showSummaryDialog();
      }

      // No approval flow - changes already applied during processing
      // Just show completion message

      // Cleaned paragraphs are already stored in the cleanedParagraphs list
      setState(() {
        isProcessing = false;
        if (!isCancelling) {
          progress = 1.0;
        }
      });

      if (mounted) {
        final message = isCancelling
            ? 'Processing cancelled: $processedParagraphs/$totalParagraphs paragraphs processed, $modifiedParagraphs modified'
            : 'Book processed: $processedParagraphs paragraphs filtered, $modifiedParagraphs modified. Ready to save!';

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(message),
            duration: const Duration(seconds: 4),
            backgroundColor: isCancelling ? Colors.orange : null,
            behavior: SnackBarBehavior.floating,
            margin: EdgeInsets.only(
              bottom: MediaQuery.of(context).size.height - 100,
              left: 10,
              right: 10,
            ),
          ),
        );
      }
    } catch (e, stackTrace) {
      print('Error processing book: $e');
      print('Stack trace: $stackTrace');

      setState(() {
        isProcessing = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error processing book: $e'),
            duration: const Duration(seconds: 5),
            backgroundColor: Colors.red,
            behavior: SnackBarBehavior.floating,
            margin: EdgeInsets.only(
              bottom: MediaQuery.of(context).size.height - 100,
              left: 10,
              right: 10,
            ),
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
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      });
    }
  }

  // Check if filtering is needed based on current ratings vs desired levels
  bool _checkIfFilteringNeeded(
    ChapterRatingResponse ratings,
    int desiredProfanityLevel,
    int desiredSexualLevel,
    int desiredViolenceLevel,
  ) {
    // Convert ContentRating enum to numeric level
    int ratingToLevel(ContentRating rating) {
      switch (rating) {
        case ContentRating.G:
          return 1;
        case ContentRating.PG:
          return 2;
        case ContentRating.PG13:
          return 3;
        case ContentRating.R:
          return 4;
        case ContentRating.X:
          return 5;
      }
    }

    final currentProfanity = ratingToLevel(ratings.ratings.language);
    final currentSexual = ratingToLevel(ratings.ratings.sexualContent);
    final currentViolence = ratingToLevel(ratings.ratings.violence);

    // If any rating is higher than desired, filtering is needed
    return currentProfanity > desiredProfanityLevel ||
        currentSexual > desiredSexualLevel ||
        currentViolence > desiredViolenceLevel;
  }

  // Process book chapter by chapter (for Gemini)
  Future<void> _processChapterByChapter() async {
    const maxParagraphsPerChunk = 100; // Max paragraphs to send in one API call

    for (
      int chapterIdx = 0;
      chapterIdx < parsedEpub!.chapters.length;
      chapterIdx++
    ) {
      if (isCancelling) break;

      final chapter = parsedEpub!.chapters[chapterIdx];
      final chapterParagraphs = chapter.paragraphs;

      print(
        'Processing Chapter ${chapterIdx + 1}/${parsedEpub!.chapters.length}: "${chapter.title}" (${chapterParagraphs.length} paragraphs)...',
      );

      try {
        if (geminiService == null) {
          throw Exception('Gemini service not initialized.');
        }

        // FIRST PASS: Rate the chapter for content
        final chapterText = chapterParagraphs.join('\n\n');
        print('  Rating Chapter ${chapterIdx + 1} for content...');
        final ratings = await geminiService!.rateChapter(
          text: chapterText,
          onRateLimit: (delay) {
            setState(() {
              liveLogMessages.add(
                '⏸️ Rate limited. Waiting ${delay.inSeconds}s...',
              );
              _scrollToBottom();
            });
          },
        );

        setState(() {
          liveLogMessages.add(
            '📊 Chapter ${chapterIdx + 1}: Rated language-${ratings.ratings.language.name.toUpperCase()}, sexual-${ratings.ratings.sexualContent.name.toUpperCase()}, violence-${ratings.ratings.violence.name.toUpperCase()}',
          );
        });
        _scrollToBottom();

        // Check if filtering is needed based on ratings vs desired levels
        final needsFiltering = _checkIfFilteringNeeded(
          ratings,
          profanityLevel,
          sexualContentLevel,
          violenceLevel,
        );

        if (needsFiltering) {
          setState(() {
            liveLogMessages.add(
              '🔧 Chapter ${chapterIdx + 1}: Filtering required',
            );
          });
          _scrollToBottom();
        } else {
          setState(() {
            liveLogMessages.add(
              '✓ Chapter ${chapterIdx + 1}: No filtering needed',
            );
          });
          _scrollToBottom();
          // Add original content without filtering
          for (final para in chapterParagraphs) {
            cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
            cleanedParagraphs.add(para);
          }
          setState(() {
            processedParagraphs += chapterParagraphs.length;
            progress = processedParagraphs / totalParagraphs;
          });
          continue;
        }

        // If chapter is small enough, send as one chunk
        if (chapterParagraphs.length <= maxParagraphsPerChunk) {
          final response = await geminiService!.filterParagraph(
            paragraph: chapterText,
            profanityLevel: profanityLevel,
            sexualContentLevel: sexualContentLevel,
            violenceLevel: violenceLevel,
            chapterIndex: chapterIdx,
            onRateLimit: (delay) {
              setState(() {
                liveLogMessages.add(
                  '⏸️ Rate limited. Waiting ${delay.inSeconds}s...',
                );
                _scrollToBottom();
              });
            },
          );

          // Split cleaned text back into paragraphs
          final cleanedChapterParagraphs = response.cleanedText
              .split('\n\n')
              .where((p) => p.trim().isNotEmpty)
              .toList();

          // DEBUG: Log original vs cleaned paragraphs (non-UI)
          final originalParas = chapterText
              .split('\n\n')
              .where((p) => p.trim().isNotEmpty)
              .toList();
          final maxPairs =
              originalParas.length > cleanedChapterParagraphs.length
              ? originalParas.length
              : cleanedChapterParagraphs.length;
          for (int pi = 0; pi < maxPairs; pi++) {
            final orig = pi < originalParas.length
                ? originalParas[pi]
                : '<missing>';
            final cleaned = pi < cleanedChapterParagraphs.length
                ? cleanedChapterParagraphs[pi]
                : '<missing>';
            if (orig.trim() != cleaned.trim()) {
              print(
                'DEBUG: Chapter ${chapterIdx + 1} paragraph ${pi + 1} changed',
              );
              print('  ORIGINAL: ' + orig);
              print('  CLEANED : ' + cleaned);
              _paraComparisons['$chapterIdx:$pi'] = [orig, cleaned];
            } else {
              // unchanged; do not store comparison or log for UI
              print(
                'DEBUG: Chapter ${chapterIdx + 1} paragraph ${pi + 1} unchanged',
              );
            }
          }

          // UI log entries for paragraph-level reveal (first pass)
          final firstPassLogs = <String>[];
          for (int pi = 0; pi < maxPairs; pi++) {
            final key = '$chapterIdx:$pi';
            if (_paraComparisons.containsKey(key)) {
              firstPassLogs.add(
                'Chapter ${chapterIdx + 1} paragraph ${pi + 1} modified',
              );
            }
          }
          if (firstPassLogs.isNotEmpty) {
            setState(() {
              liveLogMessages.addAll(firstPassLogs);
            });
          }

          // Add all cleaned paragraphs to this chapter
          for (final para in cleanedChapterParagraphs) {
            cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
            cleanedParagraphs.add(para);
          }

          if (response.wasModified) {
            setState(() {
              modifiedParagraphs += chapterParagraphs.length;
              allCategorizedChanges.addAll(
                response.categorizedChanges.profanity,
              );
              allCategorizedChanges.addAll(response.categorizedChanges.sexual);
              allCategorizedChanges.addAll(
                response.categorizedChanges.violence,
              );
              final changesToLog = response.detectedChanges
                  .take(3)
                  .map((change) {
                    final parts = change.split(' ');
                    if (parts.isNotEmpty) {
                      final word = parts[0];
                      // Re-add the rest of the change description, e.g., "(removed/changed)"
                      final rest = parts.skip(1).join(' ');
                      return '${_obfuscateWord(word)} $rest';
                    }
                    return change;
                  })
                  .join(', ');

              final logEntry =
                  '• Chapter ${chapterIdx + 1}: "${chapter.title}" - $changesToLog';
              liveLogMessages.add(logEntry);
            });
          }
          _scrollToBottom();

          setState(() {
            processedParagraphs += chapterParagraphs.length;
            progress = processedParagraphs / totalParagraphs;
          });

          // SECOND PASS: Re-rate cleaned chapter; if sexual/violence still above target, run stricter PG cleaning using alternate model
          try {
            final cleanedChapterText = cleanedChapterParagraphs.join('\n\n');
            final postRatings = await geminiService!.rateChapter(
              text: cleanedChapterText,
              onRateLimit: (delay) {
                setState(() {
                  liveLogMessages.add(
                    '⏸️ Rate limited. Waiting ${delay.inSeconds}s...',
                  );
                  _scrollToBottom();
                });
              },
            );

            final targetSex = sexualContentLevel;
            final targetViol = violenceLevel;
            int ratingToLevelLocal(ContentRating rating) {
              switch (rating) {
                case ContentRating.G:
                  return 1;
                case ContentRating.PG:
                  return 2;
                case ContentRating.PG13:
                  return 3;
                case ContentRating.R:
                  return 4;
                case ContentRating.X:
                  return 5;
              }
            }

            final sexTooHigh =
                ratingToLevelLocal(postRatings.ratings.sexualContent) >
                targetSex;
            final violTooHigh =
                ratingToLevelLocal(postRatings.ratings.violence) > targetViol;

            if (sexTooHigh || violTooHigh) {
              setState(() {
                liveLogMessages.add(
                  '🔁 Chapter ${chapterIdx + 1}: Second pass due to residual ${sexTooHigh ? 'sexual ' : ''}${violTooHigh ? 'violence' : ''} content',
                );
              });
              _scrollToBottom();

              // Use alternate Gemini model for second pass if provided via env GEMINI_SECOND_MODEL
              final secondModel = const String.fromEnvironment(
                'GEMINI_SECOND_MODEL',
                defaultValue: 'gemini-2.5-pro',
              );
              final secondService = GeminiService(
                apiKey: geminiApiKey,
                model: secondModel,
              );

              final secondResp = await secondService.filterParagraph(
                paragraph: cleanedChapterText,
                profanityLevel: profanityLevel, // keep language target
                sexualContentLevel: sexualContentLevel,
                violenceLevel: violenceLevel,
                chapterIndex: chapterIdx,
                strictSexualPg: sexTooHigh && sexualContentLevel <= 2,
                strictViolencePg: violTooHigh && violenceLevel <= 2,
                onRateLimit: (delay) {
                  setState(() {
                    liveLogMessages.add(
                      '⏸️ Second pass rate limit. Waiting ${delay.inSeconds}s...',
                    );
                    _scrollToBottom();
                  });
                },
              );

              final reCleanedParas = secondResp.cleanedText
                  .split('\n\n')
                  .where((p) => p.trim().isNotEmpty)
                  .toList();

              // DEBUG: Log original vs second-pass cleaned paragraphs (non-UI)
              final firstPassParas = cleanedChapterText
                  .split('\n\n')
                  .where((p) => p.trim().isNotEmpty)
                  .toList();
              final maxPairs2 = firstPassParas.length > reCleanedParas.length
                  ? firstPassParas.length
                  : reCleanedParas.length;
              for (int pi = 0; pi < maxPairs2; pi++) {
                final orig2 = pi < firstPassParas.length
                    ? firstPassParas[pi]
                    : '<missing>';
                final cleaned2 = pi < reCleanedParas.length
                    ? reCleanedParas[pi]
                    : '<missing>';
                if (orig2.trim() != cleaned2.trim()) {
                  print(
                    'DEBUG: Chapter ${chapterIdx + 1} second-pass paragraph ${pi + 1} changed',
                  );
                  print('  FIRST  : ' + orig2);
                  print('  CLEANED: ' + cleaned2);
                } else {
                  print(
                    'DEBUG: Chapter ${chapterIdx + 1} second-pass paragraph ${pi + 1} unchanged',
                  );
                }
              }

              // Replace last chapter's paragraphs with second pass output
              final startIndex =
                  cleanedParagraphs.length - cleanedChapterParagraphs.length;
              cleanedParagraphs.removeRange(
                startIndex,
                cleanedParagraphs.length,
              );
              for (final para in reCleanedParas) {
                cleanedParagraphToChapter[cleanedParagraphs.length] =
                    chapterIdx;
                cleanedParagraphs.add(para);
              }

              // Update comparisons after second pass
              for (
                int pi = 0;
                pi <
                    (firstPassParas.length > reCleanedParas.length
                        ? firstPassParas.length
                        : reCleanedParas.length);
                pi++
              ) {
                final orig2 = pi < firstPassParas.length
                    ? firstPassParas[pi]
                    : '<missing>';
                final cleaned2 = pi < reCleanedParas.length
                    ? reCleanedParas[pi]
                    : '<missing>';
                final key = '$chapterIdx:$pi';
                final changed = orig2.trim() != cleaned2.trim();
                if (changed) {
                  // Preserve original baseline if this paragraph was previously modified; otherwise use orig2 as baseline.
                  if (_paraComparisons.containsKey(key)) {
                    final originalBaseline = _paraComparisons[key]![0];
                    _paraComparisons[key] = [originalBaseline, cleaned2];
                  } else {
                    _paraComparisons[key] = [orig2, cleaned2];
                  }
                } else {
                  // If previously modified (from first pass) but unchanged now, keep existing comparison.
                }
              }

              // Paragraph-level second-pass diffs omitted unless newly created.
              // (Future enhancement: track previous cleaned version to differentiate.)

              // Add log entries for paragraphs newly modified in second pass
              final newlyModifiedSecondPass = <String>[];
              for (
                int pi = 0;
                pi <
                    (firstPassParas.length > reCleanedParas.length
                        ? firstPassParas.length
                        : reCleanedParas.length);
                pi++
              ) {
                final key = '$chapterIdx:$pi';
                // Newly modified if it wasn't in comparisons before and now exists OR if existing comparison's cleaned text differs from reCleanedParas
                final reCleaned = pi < reCleanedParas.length
                    ? reCleanedParas[pi]
                    : '<missing>';
                final firstPass = pi < firstPassParas.length
                    ? firstPassParas[pi]
                    : '<missing>';
                final comp = _paraComparisons[key];
                // Determine if key added in this pass and firstPass == comp[0] (baseline) and comp[1] == reCleaned
                // We can't directly know if key existed before; approximate: if firstPass.trim() == reCleaned.trim() skip.
                if (firstPass.trim() != reCleaned.trim()) {
                  // Avoid duplicating logs for paragraphs already logged as modified in first pass and unchanged in second pass
                  if (firstPass.trim() == (comp?[0].trim() ?? '') &&
                      reCleaned.trim() == (comp?[1].trim() ?? '')) {
                    // It is a modified paragraph either from first or second; we will log only if it was not logged before second pass.
                    // Without state we skip logging duplicates.
                  }
                  // Log only if paragraph was not previously modified (no existing comparison before pass). We approximate by checking if first pass cleaned matched original baseline (meaning first pass didn't change) but comp exists now.
                  // If it was modified in first pass, do nothing; new modifications get logged below.
                  // Approximation: comp exists AND comp[0] == firstPass (original) indicates second pass changed an unchanged paragraph.
                  if (comp != null && comp[0].trim() == firstPass.trim()) {
                    newlyModifiedSecondPass.add(
                      'Chapter ${chapterIdx + 1} paragraph ${pi + 1} modified (2nd pass)',
                    );
                  }
                }
              }
              if (newlyModifiedSecondPass.isNotEmpty) {
                setState(() {
                  liveLogMessages.addAll(newlyModifiedSecondPass);
                });
              }

              // Log summary of second pass
              setState(() {
                liveLogMessages.add(
                  '✅ Chapter ${chapterIdx + 1}: Second pass applied with model ${secondModel}',
                );
              });
              _scrollToBottom();
            }
          } catch (e) {
            setState(() {
              liveLogMessages.add(
                '⚠️ Second pass failed for Chapter ${chapterIdx + 1}: $e',
              );
            });
            _scrollToBottom();
          }
        } else {
          // Chapter is too large, split into smaller chunks
          print(
            '  Chapter is large (${chapterParagraphs.length} paragraphs), splitting into chunks...',
          );

          for (
            int i = 0;
            i < chapterParagraphs.length;
            i += maxParagraphsPerChunk
          ) {
            if (isCancelling) break;

            final end = (i + maxParagraphsPerChunk).clamp(
              0,
              chapterParagraphs.length,
            );
            final chunkParagraphs = chapterParagraphs.sublist(i, end);
            final chunkText = chunkParagraphs.join('\n\n');

            print(
              '  Processing chunk ${i ~/ maxParagraphsPerChunk + 1} (paragraphs ${i + 1}-$end)...',
            );

            final response = await geminiService!.filterParagraph(
              paragraph: chunkText,
              profanityLevel: profanityLevel,
              sexualContentLevel: sexualContentLevel,
              violenceLevel: violenceLevel,
              chapterIndex: chapterIdx,
              onRateLimit: (delay) {
                setState(() {
                  liveLogMessages.add(
                    '⏸️ Rate limited. Waiting ${delay.inSeconds}s...',
                  );
                  _scrollToBottom();
                });
              },
            );

            // Split cleaned text back into paragraphs
            final cleanedChunkParagraphs = response.cleanedText
                .split('\n\n')
                .where((p) => p.trim().isNotEmpty)
                .toList();

            // Record comparisons & UI log entries for chunk paragraphs
            final origChunkParas = chunkText
                .split('\n\n')
                .where((p) => p.trim().isNotEmpty)
                .toList();
            final chunkLogs = <String>[];
            for (
              int localPi = 0;
              localPi < cleanedChunkParagraphs.length;
              localPi++
            ) {
              final globalPi = i + localPi; // index within chapter
              final origP = localPi < origChunkParas.length
                  ? origChunkParas[localPi]
                  : '<missing>';
              final cleanedP = cleanedChunkParagraphs[localPi];
              if (origP.trim() != cleanedP.trim()) {
                _paraComparisons['$chapterIdx:$globalPi'] = [origP, cleanedP];
                chunkLogs.add(
                  'Chapter ${chapterIdx + 1} paragraph ${globalPi + 1} modified',
                );
              }
            }
            if (chunkLogs.isNotEmpty) {
              setState(() {
                liveLogMessages.addAll(chunkLogs);
              });
            }

            // Add all cleaned paragraphs to this chapter
            for (final para in cleanedChunkParagraphs) {
              cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
              cleanedParagraphs.add(para);
            }

            if (response.wasModified) {
              setState(() {
                modifiedParagraphs += chunkParagraphs.length;
                allCategorizedChanges.addAll(
                  response.categorizedChanges.profanity,
                );
                allCategorizedChanges.addAll(
                  response.categorizedChanges.sexual,
                );
                allCategorizedChanges.addAll(
                  response.categorizedChanges.violence,
                );
              });
            }

            setState(() {
              processedParagraphs += chunkParagraphs.length;
              progress = processedParagraphs / totalParagraphs;
            });
          }

          // Log once for the whole chapter
          setState(() {
            final logEntry =
                '• Chapter ${chapterIdx + 1}: "${chapter.title}" - Processed in multiple chunks';
            liveLogMessages.add(logEntry);
          });
        }
      } catch (e) {
        print('Error processing chapter $chapterIdx: $e');
        // Keep original paragraphs if filtering fails
        for (final para in chapterParagraphs) {
          cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
          cleanedParagraphs.add(para);
        }

        setState(() {
          liveLogMessages.add(
            '⚠️ Error in Chapter ${chapterIdx + 1}: Using original content',
          );
          processedParagraphs += chapterParagraphs.length;
          progress = processedParagraphs / totalParagraphs;
        });
      }
    }
  }

  // Process book paragraph by paragraph (for Ollama)
  Future<void> _processParagraphByParagraph(List<String> allParagraphs) async {
    for (int i = 0; i < allParagraphs.length; i++) {
      // Check for cancellation
      if (isCancelling) {
        print('Processing cancelled by user');
        break;
      }

      final paragraph = allParagraphs[i];
      final chapterIdx = paragraphToChapter[i]!;

      // Skip very short paragraphs (likely formatting elements)
      if (paragraph.trim().length < 10) {
        cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
        cleanedParagraphs.add(paragraph);
        setState(() {
          processedParagraphs++;
          progress = (i + 1) / allParagraphs.length;
        });
        continue;
      }

      print('Processing paragraph ${i + 1}/${allParagraphs.length}...');

      try {
        // Filter the paragraph through Ollama
        final response = await ollamaService.filterParagraph(
          paragraph: paragraph,
          profanityLevel: profanityLevel,
          sexualContentLevel: sexualContentLevel,
          violenceLevel: violenceLevel,
        );

        cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
        cleanedParagraphs.add(response.cleanedText);

        // Track if content was changed
        if (response.wasModified) {
          setState(() {
            modifiedParagraphs++;

            // Add detailed log message
            if (response.removedWords.isNotEmpty) {
              final logMessage = _createLogMessage(
                i + 1,
                response.removedWords,
              );
              liveLogMessages.add(logMessage);

              // Auto-scroll to bottom
              if (_scrollController.hasClients) {
                _scrollController.animateTo(
                  _scrollController.position.maxScrollExtent,
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeOut,
                );
              }
            } else {
              liveLogMessages.add('Paragraph ${i + 1}: Content modified');
            }
          });
          removalDetails.add(
            'Modified paragraph ${i + 1} (Chapter ${paragraphToChapter[i]! + 1})',
          );
        }
      } catch (e) {
        print('Error processing paragraph $i: $e');
        // Keep original paragraph if filtering fails
        cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
        cleanedParagraphs.add(paragraph);
      }

      // Update progress
      setState(() {
        processedParagraphs++;
        progress = (i + 1) / allParagraphs.length;
      });

      // Finish processing message
      setState(() {
        isProcessing = false;
        progress = 1.0;
        liveLogMessages.add(
          '✅ Book processed: ${cleanedParagraphs.length} paragraphs total',
        );
        if (modifiedParagraphs > 0) {
          liveLogMessages.add(
            '📊 Summary: $modifiedParagraphs paragraphs modified',
          );
        }
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              modifiedParagraphs > 0
                  ? 'Book processed: $modifiedParagraphs changes made. Ready to save.'
                  : 'Book processed: No changes needed. Ready to save.',
            ),
            duration: const Duration(seconds: 3),
          ),
        );
      }
    }
  }

  void _showSummaryDialog() {
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Processing Summary'),
          content: SizedBox(
            width: double.maxFinite,
            child: _buildSummaryContent(),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Close'),
            ),
          ],
        );
      },
    );
  }

  Widget _buildSummaryContent() {
    final profanityChanges = allCategorizedChanges
        .where((c) => c.category == 'profanity')
        .toList();
    final sexualChanges = allCategorizedChanges
        .where((c) => c.category == 'sexual')
        .toList();
    final violenceChanges = allCategorizedChanges
        .where((c) => c.category == 'violence')
        .toList();

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (profanityChanges.isNotEmpty)
            _buildSummaryCategory(
              'Profanity Changes',
              profanityChanges,
              Icons.volume_off,
              Colors.orange,
            ),
          if (sexualChanges.isNotEmpty) _buildSexualSummaryCard(sexualChanges),
          if (violenceChanges.isNotEmpty)
            _buildSummaryCategory(
              'Violence Changes',
              violenceChanges,
              Icons.shield_outlined,
              Colors.red,
            ),
        ],
      ),
    );
  }

  Widget _buildSummaryCategory(
    String title,
    List<ChangeDetail> changes,
    IconData icon,
    Color color,
  ) {
    // Group by original word
    final groupedByWord = <String, List<ChangeDetail>>{};
    for (final change in changes) {
      (groupedByWord[change.originalWord] ??= []).add(change);
    }

    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: color),
                const SizedBox(width: 8),
                Text(
                  '$title (${changes.length} total)',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: color,
                  ),
                ),
              ],
            ),
            const Divider(height: 16),
            ...groupedByWord.entries.map((entry) {
              final wordChanges = entry.value;
              final obfuscated = wordChanges.first.obfuscatedWord;
              final count = wordChanges.length;

              // Group by chapter
              final chapters = wordChanges
                  .map((c) => c.chapterIndex + 1)
                  .toSet()
                  .toList();
              chapters.sort();
              final chapterText = chapters.length > 1 ? 'Chapters' : 'Chapter';
              final chapterList = chapters.join(', ');

              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4.0),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$obfuscated ($count):',
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '$chapterText $chapterList',
                        style: TextStyle(color: Colors.grey[400]),
                      ),
                    ),
                  ],
                ),
              );
            }).toList(),
          ],
        ),
      ),
    );
  }

  Widget _buildSexualSummaryCard(List<ChangeDetail> sexualChanges) {
    final affectedChapters =
        sexualChanges.map((c) => c.chapterIndex + 1).toSet().toList()..sort();
    final totalTokens = sexualChanges.length;
    final uniqueTokens =
        sexualChanges.map((c) => c.obfuscatedWord).toSet().toList()..sort();
    final sampleTokens = uniqueTokens.take(10).join(', ');

    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.favorite_border, color: Colors.pink),
                const SizedBox(width: 8),
                Text(
                  'Sexual Content Changes',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            const Divider(height: 16),
            Text(
              'Chapters affected (${affectedChapters.length}): ${affectedChapters.join(', ')}',
              style: TextStyle(color: Colors.grey[300]),
            ),
            const SizedBox(height: 6),
            Text(
              'Total sexual tokens removed/modified: $totalTokens',
              style: TextStyle(color: Colors.grey[300]),
            ),
            if (sampleTokens.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                'Sample tokens: $sampleTokens${uniqueTokens.length > 10 ? ' …' : ''}',
                style: TextStyle(color: Colors.grey[400], fontSize: 12),
              ),
            ],
            const SizedBox(height: 8),
            Text(
              'Note: Sexual content is filtered at chapter granularity; token counts approximate intensity, not precise paragraph attribution.',
              style: TextStyle(color: Colors.grey[500], fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }

  // Note: _applyApprovedChanges removed - changes now applied immediately during processing

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BookWash - EPUB Content Cleaner'),
        centerTitle: true,
        elevation: 0,
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
                    // AI Provider Selector
                    Row(
                      children: [
                        const Text(
                          'AI Provider:',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: DropdownButton<String>(
                            value: selectedProvider,
                            isExpanded: true,
                            items: const [
                              DropdownMenuItem(
                                value: 'ollama',
                                child: Text('Ollama (Local)'),
                              ),
                              DropdownMenuItem(
                                value: 'gemini',
                                child: Text('Google Gemini (Cloud)'),
                              ),
                            ],
                            onChanged: isProcessing
                                ? null
                                : (String? newProvider) {
                                    if (newProvider != null) {
                                      setState(() {
                                        selectedProvider = newProvider;
                                        if (newProvider == 'gemini') {
                                          _showGeminiApiKeyDialog();
                                        } else {
                                          _loadAvailableModels();
                                        }
                                      });
                                    }
                                  },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    // Model Selector
                    Row(
                      children: [
                        const Text(
                          'AI Model:',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: isLoadingModels
                              ? const Row(
                                  children: [
                                    SizedBox(
                                      width: 16,
                                      height: 16,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    ),
                                    SizedBox(width: 8),
                                    Text(
                                      'Loading models...',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ],
                                )
                              : DropdownButton<String>(
                                  value: selectedModel,
                                  isExpanded: true,
                                  items: availableModels
                                      .map(
                                        (model) => DropdownMenuItem(
                                          value: model,
                                          child: Text(model),
                                        ),
                                      )
                                      .toList(),
                                  onChanged: isProcessing
                                      ? null
                                      : _onModelChanged,
                                ),
                        ),
                      ],
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
                        '1 - G Rated: No profanity or crude language (Most censorship)',
                        '2 - PG Rated: Mild language allowed (Heavy censorship)',
                        '3 - PG-13 Rated: Some strong language (Light censorship)',
                        '4 - R Rated: Strong language allowed (Censorship of F word only)',
                        '5 - Unrated: Everything allowed (No censorship)',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Sexual Content',
                      sexualContentLevel,
                      (value) {
                        final v = value.toInt();
                        setState(() => sexualContentLevel = v);
                        _saveLevel('sexual_level', v);
                      },
                      [
                        '1 - G Rated: No sexual content allowed (Most censorship)',
                        '2 - PG Rated: Light romance only (Heavy censorship)',
                        '3 - PG-13 Rated: Romantic scenes allowed (Light censorship)',
                        '4 - R Rated: Suggestive content allowed (Censorship of X rated content only)',
                        '5 - Unrated: Everything allowed (No censorship)',
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
                        '1 - G Rated: No violence (Most censorship)',
                        '2 - PG Rated: Mild conflict only (Heavy censorship)',
                        '3 - PG-13 Rated: Action/combat allowed (Light censorship)',
                        '4 - R Rated: Intense violence allowed (Censorship of intense gore only)',
                        '5 - Unrated: Everything allowed (No censorship)',
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
                      Text(
                        '${(progress * 100).toStringAsFixed(0)}% Complete',
                        style: const TextStyle(
                          fontSize: 14,
                          color: Colors.grey,
                        ),
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

            // Save Edited Book Button (always visible, disabled until processing completes)
            const SizedBox(height: 20),
            ElevatedButton.icon(
              onPressed: cleanedParagraphs.isNotEmpty ? saveCleanedBook : null,
              icon: const Icon(Icons.save),
              label: const Text('Save Edited Book'),
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                backgroundColor: cleanedParagraphs.isNotEmpty
                    ? Colors.green
                    : null,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Obfuscate a word by replacing middle characters with asterisks
  String _obfuscateWord(String word) {
    if (word.length <= 2) {
      return '*' * word.length;
    } else if (word.length == 3) {
      return '${word[0]}*${word[2]}';
    } else {
      final asterisks = '*' * (word.length - 2);
      return '${word[0]}$asterisks${word[word.length - 1]}';
    }
  }

  /// Create log message for removed words
  String _createLogMessage(int paragraphNum, List<String> removedWords) {
    // Categorize words
    final profanityWords = <String>[];
    final sexualWords = <String>[];
    final violenceWords = <String>[];

    // Common profanity keywords
    const profanityKeywords = [
      'damn',
      'shit',
      'bullshit',
      'crap',
      'hell',
      'ass',
      'asshole',
      'bitch',
      'fuck',
      'fucking',
      'fucked',
      'motherfucker',
      'bastard',
    ];

    // Sexual content keywords
    const sexualKeywords = [
      'cleavage',
      'neckline',
      'sexy',
      'passionate',
      'kiss',
      'kissing',
    ];

    // Violence keywords
    const violenceKeywords = [
      'punch',
      'hit',
      'fight',
      'blood',
      'kill',
      'violence',
      'weapon',
    ];

    for (final word in removedWords) {
      final lowerWord = word.toLowerCase();
      if (profanityKeywords.contains(lowerWord)) {
        profanityWords.add(word);
      } else if (sexualKeywords.contains(lowerWord)) {
        sexualWords.add(word);
      } else if (violenceKeywords.contains(lowerWord)) {
        violenceWords.add(word);
      }
    }

    final parts = <String>[];

    // Add profanity with obfuscation
    if (profanityWords.isNotEmpty) {
      final obfuscated = profanityWords.map(_obfuscateWord).join(', ');
      parts.add('profanity ($obfuscated)');
    }

    // Add sexual content with obfuscation
    if (sexualWords.isNotEmpty) {
      final obfuscated = sexualWords.map(_obfuscateWord).join(', ');
      parts.add('sexual ($obfuscated)');
    }

    // Add violence with obfuscation
    if (violenceWords.isNotEmpty) {
      final obfuscated = violenceWords.map(_obfuscateWord).join(', ');
      parts.add('violence ($obfuscated)');
    }

    if (parts.isEmpty) {
      return 'Paragraph $paragraphNum: Content modified';
    }

    return 'Paragraph $paragraphNum: Removed ${parts.join(', ')}';
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
          max: 5,
          divisions: 4,
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
