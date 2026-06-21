import 'package:dio/dio.dart';
import '../../core/api_client.dart';
import '../../core/secure_storage_service.dart';

class AuthRepository {
  final ApiClient _apiClient;
  final SecureStorageService _storageService;

  AuthRepository(this._apiClient, this._storageService);

  ApiClient getApiClient() => _apiClient;
  
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
      
      return data;
    } on DioException catch (e) {
      final errorMsg = e.response?.data['detail'] ?? 'Грешка при връзка със сървъра';
      throw Exception(errorMsg);
    }
  }

  Future<void> changePassword(String newPassword) async {
    try {
      await _apiClient.dio.post(
        '/students/change-password',
        data: {
          'new_password': newPassword,
        },
      );
    } on DioException catch (e) {
      final errorMsg = e.response?.data['detail'] ?? 'Неуспешна смяна на парола';
      throw Exception(errorMsg);
    }
  }
}