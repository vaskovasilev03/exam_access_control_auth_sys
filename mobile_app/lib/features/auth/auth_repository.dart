import 'package:dio/dio.dart';
import '../../core/api_client.dart';
import '../../core/secure_storage_service.dart';

class AuthRepository {
  final ApiClient _apiClient;
  final SecureStorageService _storageService;

  AuthRepository(this._apiClient, this._storageService);

  ApiClient getApiClient() => _apiClient;
  SecureStorageService getStorageService() => _storageService;

  Future<({String? studentId, String? password})> getSavedCredentials() {
    return _storageService.getCredentials();
  }
  
  Future<Map<String, dynamic>> login(String studentId, String password) async {
    try {
      final response = await _apiClient.dio.post(
        '/students/login',
        data: {
          'student_id_number': studentId,
          'password': password,
        },
      );
      
      final data = response.data as Map<String, dynamic>;
      
      // Ако получим токен, го записваме веднага в защитената памет
      if (data['access_token'] != null) {
        await _storageService.saveToken(data['access_token']);
      }

      // Запазваме локалните креденшъли за автоматичен вход при следващо стартиране
      if (data['status'] == 'success' || data['status'] == 'force_password_change') {
        await _storageService.saveCredentials(studentId, password);
      }
      
      return data;
    } on DioException catch (e) {
      final errorMsg = e.response?.data['detail'] ?? 'Грешка при връзка със сървъра';
      throw Exception(errorMsg);
    }
  }

  Future<void> changePassword(String newPassword) async {
    try {
      final response = await _apiClient.dio.post(
        '/students/change-password',
        data: {
          'new_password': newPassword,
        },
      );

      final data = response.data;
      if (data is Map<String, dynamic> && data['access_token'] != null) {
        await _storageService.saveToken(data['access_token']);
      }

      final creds = await _storageService.getCredentials();
      if (creds.studentId != null) {
        await _storageService.saveCredentials(creds.studentId!, newPassword);
      }
    } on DioException catch (e) {
      final errorMsg = e.response?.data['detail'] ?? 'Неуспешна смяна на парола';
      throw Exception(errorMsg);
    }
  }

  Future<void> logout() async {
    await _storageService.clearAll();
  }
}