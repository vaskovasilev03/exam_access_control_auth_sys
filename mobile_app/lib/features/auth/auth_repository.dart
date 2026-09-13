import 'package:dio/dio.dart';
import '../../core/api_client.dart';
import '../../core/secure_storage_service.dart';
import '../dashboard/models/student_models.dart';

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
      final errorMsg = _extractErrorMessage(e, defaultMessage: 'Няма връзка със сървъра!');
      throw Exception(errorMsg);
    }
  }

  String _extractErrorMessage(DioException e, {String defaultMessage = 'Грешка при връзка със сървъра'}) {
    // 1. При мрежови таймаути или липса на връзка/offline сървър
    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.sendTimeout ||
        e.type == DioExceptionType.receiveTimeout ||
        e.type == DioExceptionType.connectionError ||
        e.type == DioExceptionType.unknown ||
        e.response == null) {
      return 'Няма връзка със сървъра!';
    }

    // 2. Безопасно извличане на съобщение за грешка от сървъра
    final data = e.response?.data;
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is String && detail.trim().isNotEmpty) {
        return detail.trim();
      }
      if (detail is List && detail.isNotEmpty) {
        final first = detail.first;
        if (first is Map && first['msg'] != null) {
          return first['msg'].toString();
        }
        return detail.toString();
      }
      return detail.toString();
    } else if (data is String && data.trim().isNotEmpty) {
      if (data.contains('<html') || data.contains('<body') || data.contains('<!DOCTYPE')) {
        return 'Няма връзка със сървъра!';
      }
      return data.trim();
    }

    return defaultMessage;
  }

  Future<void> changePassword(String newPassword, {String? oldPassword}) async {
    try {
      final response = await _apiClient.dio.post(
        '/students/change-password',
        data: {
          'new_password': newPassword,
          if (oldPassword != null && oldPassword.isNotEmpty) 'old_password': oldPassword,
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
      final errorMsg = _extractErrorMessage(e, defaultMessage: 'Неуспешна смяна на парола');
      throw Exception(errorMsg);
    }
  }

  Future<StudentProfileModel> getStudentProfile({String? impersonateId}) async {
    try {
      final response = await _apiClient.dio.get(
        '/students/profile',
        queryParameters: impersonateId != null ? {'impersonate_id': impersonateId} : null,
      );
      return StudentProfileModel.fromJson(response.data as Map<String, dynamic>);
    } on DioException catch (e) {
      final errorMsg = _extractErrorMessage(e, defaultMessage: 'Грешка при зареждане на профила');
      throw Exception(errorMsg);
    }
  }

  Future<List<ExamItemModel>> getMyExams({String? impersonateId}) async {
    try {
      final response = await _apiClient.dio.get(
        '/students/my-registrations',
        queryParameters: impersonateId != null ? {'impersonate_id': impersonateId} : null,
      );
      final list = response.data as List<dynamic>;
      return list.map((item) => ExamItemModel.fromJson(item as Map<String, dynamic>)).toList();
    } on DioException catch (e) {
      final errorMsg = _extractErrorMessage(e, defaultMessage: 'Грешка при зареждане на изпитния график');
      throw Exception(errorMsg);
    }
  }

  Future<List<StudentSummaryModel>> getImpersonationList() async {
    try {
      final response = await _apiClient.dio.get('/students/impersonate/list');
      final list = response.data as List<dynamic>;
      return list.map((item) => StudentSummaryModel.fromJson(item as Map<String, dynamic>)).toList();
    } on DioException catch (e) {
      final errorMsg = _extractErrorMessage(e, defaultMessage: 'Грешка при зареждане на списъка със студенти');
      throw Exception(errorMsg);
    }
  }

  Future<void> logout() async {
    await _storageService.clearAll();
  }
}