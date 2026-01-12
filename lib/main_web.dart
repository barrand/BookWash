/// BookWash Web Entry Point
///
/// This is the web-specific entry point that uses the API service
/// to communicate with the FastAPI backend.
library;

import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

import 'models/bookwash_file.dart';
import 'services/api_service.dart';
import 'widgets/widgets.dart';

void main() {
  runApp(const BookWashWebApp());
}

class BookWashWebApp extends StatelessWidget {
  const BookWashWebApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BookWash',
      theme: ThemeData.dark(useMaterial3: true),
      themeMode: ThemeMode.dark,
      home: const BookWashWebHome(),
    );
  }
}

class BookWashWebHome extends StatefulWidget {
  const BookWashWebHome({super.key});

  @override
  State<BookWashWebHome> createState() => _BookWashWebHomeState();
}

class _BookWashWebHomeState extends State<BookWashWebHome> {
  late final ApiService _api;
  // Build time injected via --dart-define BUILD_TIME
  static const String buildTime = String.fromEnvironment(
    'BUILD_TIME',
    defaultValue: '',
  );

  // File selection
  String? selectedFileName;
  List<int>? selectedFileBytes;

  // Session state
  ProcessingSession? _session;

  // Processing state
  bool isProcessing = false;
  bool isCancelling = false;
  double progress = 0.0;
  String progressPhase = '';

  // Language word filtering
  final Map<String, bool> languageWordSelection = {
    'fuck': true,
    'shit': true,
    'damn': true,
    'hell': true,
    'ass': true,
    'bitch': true,
    'bastard': true,
  };

  // Content levels
  int sexualContentLevel = 2; // Default: PG
  int violenceLevel = 4; // Default: Unfiltered
  String selectedModel = 'gemini-2.5-flash-lite';

  // Logs
  final List<String> logs = [];
  final ScrollController _logScrollController = ScrollController();
  bool _autoScroll = true;

  // Change review
  int currentChangeIndex = 0;
  bool _isAcceptingLanguage = false;

  @override
  void initState() {
    super.initState();
    _api = ApiService();

    // Set backend URL from current location (same origin)
    final origin = web.window.location.origin;
    _api.setBackendUrl(origin);

    // Check URL for session parameter and auto-resume
    _checkAndResumeSession();
  }

  @override
  void dispose() {
    _logScrollController.dispose();
    super.dispose();
  }

  Future<void> _checkAndResumeSession() async {
    // Parse URL query params
    final search = web.window.location.search;
    if (search.isEmpty || !search.contains('session=')) return;

    final params = Uri.parse(web.window.location.href).queryParameters;
    final sessionId = params['session'];
    if (sessionId == null || sessionId.isEmpty) return;

    // Try to load the session
    try {
      final session = await _api.getSession(sessionId);
      setState(() {
        _session = session;
        selectedFileName = session.filename;
      });

      // If still processing, resume SSE streams
      if (session.status == 'processing') {
        _addLog('📡 Resuming session...');
        setState(() {
          isProcessing = true;
          progress = session.progress / 100;
          progressPhase = session.phase;
        });

        // Stream logs
        final logSub = _api.streamLogs(sessionId).listen((log) {
          _addLog(log.message);
        });

        // Stream status
        final statusSub = _api.streamStatus(sessionId).listen((status) {
          setState(() {
            progress = status.progress / 100;
            progressPhase = status.phase;
            _session = status;
          });
        });

        // Wait for completion
        await statusSub.asFuture<void>().catchError((_) {});
        await logSub.cancel();

        // Fetch final session
        final finalSession = await _api.getSession(sessionId);
        setState(() {
          _session = finalSession;
          isProcessing = false;
          currentChangeIndex = 0;
        });
      } else if (session.status == 'review' || session.status == 'complete') {
        // Already done, show review UI
        setState(() {
          progress = 1.0;
          progressPhase = 'complete';
          currentChangeIndex = 0;
        });
        _addLog('✅ Session loaded (already complete)');
      }
    } catch (e) {
      final msg = e.toString();
      // If auth required, prompt credentials and retry once
      if (msg.contains('401') || msg.contains('Authentication')) {
        final creds = await _promptForCredentials(context);
        if (creds != null) {
          _api.setAuth(creds.$1, creds.$2);
          try {
            final session = await _api.getSession(sessionId);
            setState(() {
              _session = session;
              selectedFileName = session.filename;
            });

            if (session.status == 'processing') {
              _addLog('📡 Resuming session...');
              setState(() {
                isProcessing = true;
                progress = session.progress / 100;
                progressPhase = session.phase;
              });

              final logSub = _api.streamLogs(sessionId).listen((log) {
                _addLog(log.message);
              });
              final statusSub = _api.streamStatus(sessionId).listen((status) {
                setState(() {
                  progress = status.progress / 100;
                  progressPhase = status.phase;
                  _session = status;
                });
              });

              await statusSub.asFuture<void>().catchError((_) {});
              await logSub.cancel();

              final finalSession = await _api.getSession(sessionId);
              setState(() {
                _session = finalSession;
                isProcessing = false;
                currentChangeIndex = 0;
              });
            } else if (session.status == 'review' ||
                session.status == 'complete') {
              setState(() {
                progress = 1.0;
                progressPhase = 'complete';
                currentChangeIndex = 0;
              });
              _addLog('✅ Session loaded (already complete)');
            }
            return;
          } catch (e2) {
            _addLog('❌ Resume failed after auth: $e2');
          }
        }
      } else {
        _addLog('⚠️  Could not resume session: $e');
      }
    }
  }

  void _addLog(String message) {
    setState(() {
      logs.add(message);
    });
    if (_autoScroll) {
      Future.delayed(const Duration(milliseconds: 50), () {
        if (_logScrollController.hasClients) {
          _logScrollController.animateTo(
            _logScrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 100),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  // Parse log lines to extract sub-phase information (like macOS app)
  String _cleaningSubPhase = '';

  void _parseLogForPhase(String line) {
    if (line.contains('CLEANING PIPELINE:')) {
      setState(() {
        progressPhase = 'cleaning';
        _cleaningSubPhase = 'identifying';
      });
    } else if (line.contains('=== PASS 1: LANGUAGE CLEANING')) {
      setState(() => _cleaningSubPhase = 'language');
    } else if (line.contains('=== PASS 2: ADULT CONTENT CLEANING')) {
      setState(() => _cleaningSubPhase = 'adult');
    } else if (line.contains('=== PASS 3: VIOLENCE CLEANING')) {
      setState(() => _cleaningSubPhase = 'violence');
    } else if (line.contains('=== VERIFYING CLEANED CONTENT')) {
      setState(() => _cleaningSubPhase = 'verifying');
    }
  }

  void _saveLanguageWords() {
    // Web client does not persist selections locally yet.
  }

  Future<void> _pickFile() async {
    // Create a file input element using package:web
    final input = web.HTMLInputElement()
      ..type = 'file'
      ..accept = '.epub';

    input.click();

    // Wait for file selection
    final completer = Completer<void>();
    input.onChange.listen((_) => completer.complete());
    await completer.future;

    final files = input.files;
    if (files != null && files.length > 0) {
      final file = files.item(0)!;

      // Read file as ArrayBuffer
      final reader = web.FileReader();
      final readCompleter = Completer<void>();
      reader.onload = (web.Event event) {
        readCompleter.complete();
      }.toJS;
      reader.readAsArrayBuffer(file);
      await readCompleter.future;

      final result = reader.result;
      if (result != null) {
        final arrayBuffer = result as JSArrayBuffer;
        final bytes = arrayBuffer.toDart.asUint8List();

        setState(() {
          selectedFileName = file.name;
          selectedFileBytes = bytes;
        });
      }
    }
  }

  Future<void> _startProcessing() async {
    if (selectedFileBytes == null || selectedFileName == null) return;

    setState(() {
      isProcessing = true;
      progress = 0;
      progressPhase = 'uploading';
      logs.clear();
      _session = null;
    });

    _addLog('📤 Uploading file...');

    try {
      // Upload
      final session = await _api.uploadEpub(
        '',
        selectedFileBytes!,
        selectedFileName!,
      );
      setState(() {
        _session = session;
        progressPhase = 'processing';
      });

      // Update URL to include session ID (respect current path for subpaths)
      final newUrl =
          '${web.window.location.pathname}?session=${session.sessionId}';
      web.window.history.pushState(null, '', newUrl);

      _addLog('✅ File uploaded');

      // Start processing
      final selectedWords = languageWordSelection.entries
          .where((e) => e.value)
          .map((e) => e.key)
          .toList();

      await _api.startProcessing(
        sessionId: session.sessionId,
        languageWords: selectedWords,
        targetAdult: sexualContentLevel,
        targetViolence: violenceLevel,
        model: selectedModel,
      );

      // Subscribe to SSE stream for real-time updates
      final stream = _api.streamStatus(session.sessionId);

      await for (final status in stream) {
        setState(() {
          progress = status.progress / 100;
          progressPhase = status.phase;
          _session = status;
        });

        // Parse logs for sub-phase information (like macOS app does)
        for (final log in status.logs) {
          if (!logs.contains(log.message)) {
            _addLog(log.message);
            _parseLogForPhase(log.message);
          }
        }

        // Stop when complete
        if (status.status == 'review' ||
            status.status == 'complete' ||
            status.status == 'error') {
          break;
        }
      }

      // Fetch final session with changes
      final finalSession = await _api.getSession(session.sessionId);
      setState(() {
        _session = finalSession;
        isProcessing = false;
        currentChangeIndex = 0;
      });
    } catch (e) {
      // If auth is required, prompt for credentials and retry once
      final msg = e.toString();
      if (msg.contains('401') || msg.contains('Authentication')) {
        final creds = await _promptForCredentials(context);
        if (creds != null) {
          _api.setAuth(creds.$1, creds.$2);
          try {
            final session = await _api.uploadEpub(
              '',
              selectedFileBytes!,
              selectedFileName!,
            );
            setState(() {
              _session = session;
              progressPhase = 'processing';
            });
            _addLog('✅ File uploaded');

            final selectedWords = languageWordSelection.entries
                .where((e) => e.value)
                .map((e) => e.key)
                .toList();

            await _api.startProcessing(
              sessionId: session.sessionId,
              languageWords: selectedWords,
              targetAdult: sexualContentLevel,
              targetViolence: violenceLevel,
              model: selectedModel,
            );

            // Stream logs (subscription)
            final logSub = _api
                .streamLogs(session.sessionId)
                .listen((log) => _addLog(log.message));

            // Stream status (subscription)
            final statusSub = _api.streamStatus(session.sessionId).listen((
              status,
            ) {
              setState(() {
                progress = status.progress / 100;
                progressPhase = status.phase;
                _session = status;
              });
            });

            await statusSub.asFuture<void>().catchError((_) {});
            await logSub.cancel();

            final finalSession = await _api.getSession(session.sessionId);
            setState(() {
              _session = finalSession;
              isProcessing = false;
              currentChangeIndex = 0;
            });
            return;
          } catch (e2) {
            _addLog('❌ Error after auth: $e2');
          }
        }
      } else {
        _addLog('❌ Error: $e');
      }
      setState(() {
        isProcessing = false;
      });
    }
  }

  // Prompt for basic auth credentials
  Future<(String, String)?> _promptForCredentials(BuildContext context) async {
    final userController = TextEditingController(text: 'bookwash');
    final passController = TextEditingController();
    final result = await showDialog<(String, String)?>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Authentication Required'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: userController,
              decoration: const InputDecoration(labelText: 'Username'),
            ),
            TextField(
              controller: passController,
              decoration: const InputDecoration(labelText: 'Password'),
              obscureText: true,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(null),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(
              ctx,
            ).pop((userController.text, passController.text)),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    return result;
  }

  Future<void> _acceptChange(ChangeItem change) async {
    if (_session == null) return;

    await _api.updateChange(_session!.sessionId, change.id, 'accepted');
    setState(() {
      change.status = 'accepted';
      _moveToNextPendingChange();
    });
  }

  Future<void> _cancelProcessing() async {
    if (_session == null) return;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancel Processing?'),
        content: const Text(
          'This will stop processing the book. Progress will be lost.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Continue Processing'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Cancel Book'),
          ),
        ],
      ),
    );

    if (confirm == true) {
      try {
        await _api.deleteSession(_session!.sessionId);
        setState(() {
          isProcessing = false;
          _session = null;
          selectedFileName = null;
          selectedFileBytes = null;
          logs.clear();
          progress = 0;
          progressPhase = '';
        });
        _addLog('❌ Processing cancelled by user');
      } catch (e) {
        _addLog('⚠️  Cancel failed: $e');
      }
    }
  }

  Future<void> _rejectChange(ChangeItem change) async {
    if (_session == null) return;

    await _api.updateChange(_session!.sessionId, change.id, 'rejected');
    setState(() {
      change.status = 'rejected';
      _moveToNextPendingChange();
    });
  }

  Future<void> _acceptAllChanges() async {
    if (_session == null) return;

    await _api.acceptAllChanges(_session!.sessionId);
    setState(() {
      for (final change in _session!.changes) {
        if (change.status == 'pending') {
          change.status = 'accepted';
        }
      }
    });
  }

  Future<void> _acceptAllLanguageChanges() async {
    if (_session == null) return;

    final languageChanges = _session!.changes.where((change) {
      if (change.status != 'pending') return false;
      final reason = change.reason.toLowerCase();
      return reason.contains('language');
    }).toList();

    if (languageChanges.isEmpty) return;

    setState(() => _isAcceptingLanguage = true);
    try {
      for (final change in languageChanges) {
        await _api.updateChange(_session!.sessionId, change.id, 'accepted');
        change.status = 'accepted';
      }
      setState(() {
        _moveToNextPendingChange();
      });
    } finally {
      if (mounted) {
        setState(() => _isAcceptingLanguage = false);
      }
    }
  }

  void _moveToNextPendingChange() {
    final changes = _session?.changes ?? [];
    for (int i = 0; i < changes.length; i++) {
      if (changes[i].status == 'pending') {
        currentChangeIndex = i;
        return;
      }
    }
    // No more pending changes
    currentChangeIndex = changes.length;
  }

  Future<void> _exportEpub() async {
    if (_session == null) return;

    try {
      _addLog('📦 Exporting EPUB...');
      final bytes = await _api.exportEpub(_session!.sessionId);

      // Download the file using package:web
      final jsArray = Uint8List.fromList(bytes).toJS;
      final blob = web.Blob(
        [jsArray].toJS,
        web.BlobPropertyBag(type: 'application/epub+zip'),
      );
      final url = web.URL.createObjectURL(blob);

      final anchor = web.HTMLAnchorElement()
        ..href = url
        ..download =
            '${selectedFileName?.replaceAll('.epub', '')}_cleaned.epub';
      anchor.click();

      web.URL.revokeObjectURL(url);

      _addLog('✅ Download started');
    } catch (e) {
      _addLog('❌ Export failed: $e');
    }
  }

  // Helper getters to map progressPhase to CleaningProgressIndicator format
  String get _indicatorPhase {
    // progressPhase in web is simpler: 'converting', 'rating', 'cleaning', 'complete'
    // The CleaningProgressIndicator expects: 'converting', 'rating', 'cleaning'
    return progressPhase;
  }

  String get _indicatorSubPhase {
    // Return the parsed sub-phase from log lines
    return _cleaningSubPhase;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('📚 BookWash'),
        centerTitle: true,
        actions: [
          if (buildTime.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Chip(
                label: Text(
                  buildTime,
                  style: const TextStyle(fontSize: 12, color: Colors.white70),
                ),
                backgroundColor: Colors.blueGrey.withValues(alpha: 0.2),
              ),
            ),
          TextButton.icon(
            onPressed: () async {
              final creds = await _promptForCredentials(context);
              if (creds != null) {
                _api.setAuth(creds.$1, creds.$2);
                _addLog('🔐 Signed in as ${creds.$1}');
              }
            },
            icon: const Icon(Icons.lock_open, color: Colors.white70),
            label: const Text(
              'Sign In',
              style: TextStyle(color: Colors.white70),
            ),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 800),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Step 1: File Selection
                _buildCard(
                  title: '1. Select EPUB File',
                  child: Column(
                    children: [
                      if (selectedFileName != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Row(
                            children: [
                              const Icon(Icons.book, color: Colors.green),
                              const SizedBox(width: 8),
                              Expanded(child: Text(selectedFileName!)),
                            ],
                          ),
                        ),
                      ElevatedButton.icon(
                        onPressed: isProcessing ? null : _pickFile,
                        icon: const Icon(Icons.upload_file),
                        label: Text(
                          selectedFileName == null
                              ? 'Choose File'
                              : 'Change File',
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // Step 2: Sensitivity Settings
                SensitivitySettingsCard(
                  languageWordSelection: languageWordSelection,
                  isProcessing: isProcessing,
                  sexualContentLevel: sexualContentLevel,
                  violenceLevel: violenceLevel,
                  onWordChanged: (word, value) {
                    setState(() => languageWordSelection[word] = value);
                  },
                  onSaveWords: _saveLanguageWords,
                  onSexualLevelChanged: (v) =>
                      setState(() => sexualContentLevel = v),
                  onViolenceLevelChanged: (v) =>
                      setState(() => violenceLevel = v),
                ),

                const SizedBox(height: 16),

                // Step 3: Process Button
                _buildCard(
                  title: '3. Process',
                  child: ElevatedButton.icon(
                    onPressed: (selectedFileBytes != null && !isProcessing)
                        ? _startProcessing
                        : null,
                    icon: const Icon(Icons.play_arrow),
                    label: const Text('Process Book'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 32,
                        vertical: 16,
                      ),
                    ),
                  ),
                ),

                // Step 4: Processing / Logs
                if (isProcessing || logs.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  _buildCard(
                    title: '4. Processing',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (isProcessing) ...[
                          // Debug: Show current phase
                          Text(
                            'Phase: $_indicatorPhase | SubPhase: $_indicatorSubPhase | Progress: ${(progress * 100).toInt()}%',
                            style: const TextStyle(
                              fontSize: 10,
                              color: Colors.grey,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              Expanded(
                                child: CleaningProgressIndicator(
                                  progress: progress,
                                  phase: _indicatorPhase,
                                  subPhase: _indicatorSubPhase,
                                  current: 0,
                                  total: 0,
                                ),
                              ),
                              const SizedBox(width: 12),
                              TextButton.icon(
                                onPressed: _cancelProcessing,
                                icon: const Icon(Icons.cancel, size: 20),
                                label: const Text('Cancel'),
                                style: TextButton.styleFrom(
                                  foregroundColor: Colors.red,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 16),
                        ],
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text(
                              'Live Log',
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            Row(
                              children: [
                                const Text('Auto-scroll'),
                                Switch(
                                  value: _autoScroll,
                                  onChanged: (v) =>
                                      setState(() => _autoScroll = v),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Container(
                          height: 300,
                          decoration: BoxDecoration(
                            color: Colors.black87,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: ListView.builder(
                            controller: _logScrollController,
                            padding: const EdgeInsets.all(12),
                            itemCount: logs.length,
                            itemBuilder: (context, index) => SelectableText(
                              logs[index],
                              style: const TextStyle(
                                fontFamily: 'monospace',
                                fontSize: 12,
                                color: Colors.white70,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                // Step 5: Review Changes
                if (_session?.status == 'review' &&
                    (_session?.changes.isNotEmpty ?? false)) ...[
                  const SizedBox(height: 16),
                  ChangeReviewCard(
                    pendingChanges: _session!.changes
                        .where((c) => c.status == 'pending')
                        .map(
                          (c) => PendingChangeEntry(
                            chapter: _createAdapterChapter(c),
                            change: _createAdapterChange(c),
                          ),
                        )
                        .toList(),
                    totalPendingCount: _session!.changes
                        .where((c) => c.status == 'pending')
                        .length,
                    totalAcceptedCount: _session!.changes
                        .where((c) => c.status == 'accepted')
                        .length,
                    totalRejectedCount: _session!.changes
                        .where((c) => c.status == 'rejected')
                        .length,
                    currentChangeIndex: currentChangeIndex,
                    isAcceptingLanguage: _isAcceptingLanguage,
                    onPrevious: () => setState(() => currentChangeIndex--),
                    onNext: () => setState(() => currentChangeIndex++),
                    onAcceptAllLanguage: _acceptAllLanguageChanges,
                    onAcceptAll: _acceptAllChanges,
                    onExport: _exportEpub,
                    onKeepCleaned: (editedText) async {
                      final pendingChanges = _session!.changes
                          .where((c) => c.status == 'pending')
                          .toList();
                      final change = pendingChanges[currentChangeIndex];
                      await _api.updateChange(
                        _session!.sessionId,
                        change.id,
                        'accepted',
                      );
                      setState(() {
                        change.status = 'accepted';
                        _moveToNextPendingChange();
                      });
                    },
                    onKeepOriginal: () {
                      final pendingChanges = _session!.changes
                          .where((c) => c.status == 'pending')
                          .toList();
                      _rejectChange(pendingChanges[currentChangeIndex]);
                    },
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCard({required String title, required Widget child}) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            child,
          ],
        ),
      ),
    );
  }

  Widget _buildSlider({
    required String label,
    required int value,
    required ValueChanged<double>? onChanged,
  }) {
    const labels = {1: 'G', 2: 'PG', 3: 'PG-13', 4: 'Unfiltered'};
    const descriptions = {
      1: 'Most strict • Modifies PG and above',
      2: 'Moderate • Modifies PG-13 and above',
      3: 'Light • Modifies R-rated content only',
      4: 'No modifications',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label),
            Text(
              labels[value] ?? '',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                color: Colors.blue[300],
              ),
            ),
          ],
        ),
        Slider(
          value: value.toDouble(),
          min: 1,
          max: 4,
          divisions: 3,
          onChanged: onChanged,
        ),
        Text(
          descriptions[value] ?? '',
          style: TextStyle(fontSize: 12, color: Colors.grey[400]),
        ),
      ],
    );
  }

  // Create adapter objects for ChangeReviewPanel
  BookWashChapter _createAdapterChapter(ChangeItem change) {
    return BookWashChapter(
      number: change.chapter + 1,
      title: change.chapterTitle,
      rating: null,
      contentLines: [],
    );
  }

  BookWashChange _createAdapterChange(ChangeItem change) {
    return BookWashChange(
      id: change.id,
      original: change.original,
      cleaned: change.cleaned,
      cleanedFor: [change.reason], // Convert reason to cleanedFor list
    );
  }
}
