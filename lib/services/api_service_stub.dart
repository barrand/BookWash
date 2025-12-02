/// Stub implementation - should never be used at runtime
/// This file exists for conditional import fallback

import 'api_service.dart';

ApiService createApiService({String? baseUrl, String? apiKey}) {
  throw UnsupportedError(
    'Cannot create ApiService without platform-specific implementation',
  );
}

// Provide a minimal class to satisfy interface lookups when stub is referenced
abstract class ApiServiceBase implements ApiService {
  @override
  bool get requiresBackendUrl => true;

  @override
  void setBackendUrl(String url) {}

  @override
  void setApiKey(String key) {}

  @override
  void setAuth(String username, String password) {}
}
