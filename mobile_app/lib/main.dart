import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'core/app_theme.dart';
import 'core/secure_storage_service.dart';
import 'core/api_client.dart';

import 'features/auth/auth_repository.dart';
import 'features/auth/login_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
  ]);
  
  final storageService = SecureStorageService();
  final apiClient = ApiClient(storageService);

  runApp(MyApp(storageService: storageService, apiClient: apiClient));
}

class MyApp extends StatelessWidget {
  final SecureStorageService storageService;
  final ApiClient apiClient;

  const MyApp({
    super.key,
    required this.storageService,
    required this.apiClient,
  });

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Exam Gate Mobile',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
    
      home: LoginScreen(
        authRepository: AuthRepository(apiClient, storageService),
      ),
    );
  }
}