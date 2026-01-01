/// Web implementation of ApiService using HTTP calls to FastAPI backend
library;

import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';

import 'package:http/http.dart' as http;
import 'package:web/web.dart' as web;

import 'api_service.dart';

/// Create the web API service
ApiService createApiService({String? baseUrl, String? apiKey}) {
  return WebApiService(baseUrl: baseUrl ?? '');
}

class WebApiService implements ApiService {
  String _baseUrl;
  String? _authHeader;

  // Cache for SSE streams per session (to allow multiple listeners)
  final Map<String, StreamController<Map<String, dynamic>>> _sseControllers =
      {};

  WebApiService({required String baseUrl}) : _baseUrl = baseUrl;

  @override
  bool get requiresBackendUrl => true;

  @override
  void setBackendUrl(String url) {
    _baseUrl = url.endsWith('/') ? url.substring(0, url.length - 1) : url;
  }

  @override
  void setApiKey(String key) {
    // On web, API key is stored server-side, not needed here
  }

  @override
  void setAuth(String username, String password) {
    final credentials = base64Encode(utf8.encode('$username:$password'));
    _authHeader = 'Basic $credentials';
  }

  Map<String, String> get _headers {
    final headers = <String, String>{'Accept': 'application/json'};
    if (_authHeader != null) {
      headers['Authorization'] = _authHeader!;
    }
    return headers;
  }

  @override
  Future<ProcessingSession> uploadEpub(
    String filePath,
    List<int> fileBytes,
    String fileName,
  ) async {
    final uri = Uri.parse('$_baseUrl/api/upload');

    final request = http.MultipartRequest('POST', uri);
    if (_authHeader != null) {
      request.headers['Authorization'] = _authHeader!;
    }

    request.files.add(
      http.MultipartFile.fromBytes('file', fileBytes, filename: fileName),
    );

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode != 200) {
      throw Exception('Upload failed: ${response.body}');
    }

    final data = json.decode(response.body);
    return ProcessingSession(
      sessionId: data['session_id'],
      filename: data['filename'],
      status: data['status'] ?? 'uploaded',
    );
  }

  @override
  Future<void> startProcessing({
    required String sessionId,
    required int targetAdult,
    required int targetViolence,
    required String model,
  }) async {
    final uri = Uri.parse('$_baseUrl/api/process/$sessionId');

    // UI uses 1-4 where 4="Unfiltered", Python uses 1-5 where 5=X (max)
    // Map UI level 4 to Python level 5 so "Unfiltered" means nothing gets flagged
    final pythonAdult = targetAdult == 4 ? 5 : targetAdult;
    final pythonViolence = targetViolence == 4 ? 5 : targetViolence;

    final response = await http.post(
      uri,
      headers: {
        ..._headers,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: {
        'target_adult': pythonAdult.toString(),
        'target_violence': pythonViolence.toString(),
        'model': model,
      },
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to start processing: ${response.body}');
    }
  }

  @override
  Stream<LogMessage> streamLogs(String sessionId) {
    return _getSharedSSEStream(
      sessionId,
    ).where((event) => event['type'] == 'log').map((event) {
      final log = event['log'] as Map<String, dynamic>;
      return LogMessage.fromJson(log);
    });
  }

  @override
  Stream<ProcessingSession> streamStatus(String sessionId) {
    return _getSharedSSEStream(
      sessionId,
    ).where((event) => event['type'] == 'status').map((event) {
      return ProcessingSession(
        sessionId: sessionId,
        filename: '',
        status: event['status'] ?? '',
        progress: (event['progress'] as num?)?.toDouble() ?? 0.0,
        phase: event['phase'] ?? '',
      );
    });
  }

  /// Get or create a shared broadcast stream for SSE events
  Stream<Map<String, dynamic>> _getSharedSSEStream(String sessionId) {
    if (!_sseControllers.containsKey(sessionId)) {
      final controller = StreamController<Map<String, dynamic>>.broadcast();
      _sseControllers[sessionId] = controller;

      // Start the actual SSE connection using browser's EventSource
      _connectSSE(sessionId, controller);
    }
    return _sseControllers[sessionId]!.stream;
  }

  /// Connect to SSE endpoint using browser's EventSource API
  void _connectSSE(
    String sessionId,
    StreamController<Map<String, dynamic>> controller,
  ) {
    final url = '$_baseUrl/api/logs/$sessionId';
    final eventSource = web.EventSource(url);

    eventSource.onmessage = (web.MessageEvent event) {
      try {
        final dataString = (event.data as JSString?)?.toDart ?? '';
        final data = json.decode(dataString) as Map<String, dynamic>;
        controller.add(data);

        // Check if done
        if (data['type'] == 'done') {
          eventSource.close();
          controller.close();
          _sseControllers.remove(sessionId);
        }
      } catch (e) {
        // Ignore parse errors
      }
    }.toJS;

    eventSource.onerror = (web.Event event) {
      eventSource.close();
      controller.addError(Exception('SSE connection error'));
      controller.close();
      _sseControllers.remove(sessionId);
    }.toJS;
  }

  @override
  Future<ProcessingSession> getSession(String sessionId) async {
    final uri = Uri.parse('$_baseUrl/api/session/$sessionId');
    final response = await http.get(uri, headers: _headers);

    if (response.statusCode != 200) {
      throw Exception('Failed to get session: ${response.body}');
    }

    final data = json.decode(response.body);
    final changes =
        (data['changes'] as List?)
            ?.map((c) => ChangeItem.fromJson(c as Map<String, dynamic>))
            .toList() ??
        [];

    return ProcessingSession(
      sessionId: data['id'],
      filename: data['filename'],
      status: data['status'],
      progress: (data['progress'] as num?)?.toDouble() ?? 0.0,
      phase: data['phase'] ?? '',
      changes: changes,
    );
  }

  @override
  Future<void> updateChange(
    String sessionId,
    String changeId,
    String status,
  ) async {
    final uri = Uri.parse('$_baseUrl/api/session/$sessionId/change/$changeId');

    final response = await http.post(
      uri,
      headers: {
        ..._headers,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: {'status': status},
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to update change: ${response.body}');
    }
  }

  @override
  Future<int> acceptAllChanges(String sessionId) async {
    final uri = Uri.parse('$_baseUrl/api/session/$sessionId/accept-all');
    final response = await http.post(uri, headers: _headers);

    if (response.statusCode != 200) {
      throw Exception('Failed to accept all changes: ${response.body}');
    }

    final data = json.decode(response.body);
    return data['accepted_count'] ?? 0;
  }

  @override
  Future<List<int>> exportEpub(String sessionId) async {
    final uri = Uri.parse('$_baseUrl/api/session/$sessionId/export');
    final response = await http.post(uri, headers: _headers);

    if (response.statusCode != 200) {
      throw Exception('Failed to export: ${response.body}');
    }

    return response.bodyBytes;
  }

  @override
  Future<void> deleteSession(String sessionId) async {
    final uri = Uri.parse('$_baseUrl/api/session/$sessionId');
    await http.delete(uri, headers: _headers);
  }

  @override
  Future<bool> healthCheck() async {
    try {
      final uri = Uri.parse('$_baseUrl/api/health');
      final response = await http.get(uri).timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }
}
