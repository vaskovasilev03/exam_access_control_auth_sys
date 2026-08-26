import 'package:dio/dio.dart';
import 'secure_storage_service.dart';

class ApiClient {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://192.168.68.53:8000',
  );
  
  final Dio dio;
  final SecureStorageService _storageService;

  ApiClient(this._storageService) : dio = Dio(BaseOptions(baseUrl: baseUrl)) {

    dio.options.connectTimeout = const Duration(seconds: 5);
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _storageService.getToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          return handler.next(options);
        },
        onError: (DioException e, handler) {
          print('Мрежова софтуерна грешка [${e.response?.statusCode}]: ${e.message}');
          return handler.next(e);
        },
      ),
    );
  }
}