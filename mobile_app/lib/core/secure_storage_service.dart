import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SecureStorageService {
  final _storage = const FlutterSecureStorage();
  static const _tokenKey = 'student_jwt_token';
  static const _studentIdKey = 'student_id_number';
  static const _passwordKey = 'student_password';

  Future<void> saveToken(String token) async {
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<String?> getToken() async {
    return await _storage.read(key: _tokenKey);
  }

  Future<void> deleteToken() async {
    await _storage.delete(key: _tokenKey);
  }

  Future<void> saveCredentials(String studentId, String password) async {
    await _storage.write(key: _studentIdKey, value: studentId);
    await _storage.write(key: _passwordKey, value: password);
  }

  Future<({String? studentId, String? password})> getCredentials() async {
    final studentId = await _storage.read(key: _studentIdKey);
    final password = await _storage.read(key: _passwordKey);
    return (studentId: studentId, password: password);
  }

  Future<void> clearCredentials() async {
    await _storage.delete(key: _studentIdKey);
    await _storage.delete(key: _passwordKey);
  }

  Future<void> clearAll() async {
    await deleteToken();
    await clearCredentials();
  }
}