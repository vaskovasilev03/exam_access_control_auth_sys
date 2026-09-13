import 'package:flutter/material.dart';
import 'auth_repository.dart';
import 'change_password_sheet.dart';
import '../../core/theme_tokens.dart';
import '../dashboard/dashboard_screen.dart';

class LoginScreen extends StatefulWidget {
  final AuthRepository authRepository;

  const LoginScreen({super.key, required this.authRepository});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _facNumController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _obscurePassword = true;
  bool _isLoading = false;
  String? _errorText;

  @override
  void initState() {
    super.initState();
    _checkSavedCredentials();
  }

  @override
  void dispose() {
    _facNumController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _checkSavedCredentials() async {
    final creds = await widget.authRepository.getSavedCredentials();
    if (!mounted) return;

    final studentId = creds.studentId;
    final password = creds.password;

    if (studentId != null && studentId.isNotEmpty && password != null && password.isNotEmpty) {
      _facNumController.text = studentId;
      _passwordController.text = password;
      _handleLogin(isAutoLogin: true);
    }
  }

  Future<void> _handleLogin({bool isAutoLogin = false}) async {
    final facNum = _facNumController.text.trim();
    final password = _passwordController.text.trim();

    if (facNum.isEmpty || password.isEmpty) {
      if (!isAutoLogin) {
        setState(() => _errorText = 'Моля попълнете всички полета.');
      }
      return;
    }

    setState(() {
      _isLoading = true;
      _errorText = null;
    });

    try {
      final response = await widget.authRepository.login(facNum, password);
      final status = response['status'];

      if (!mounted) return;

      if (status == 'force_password_change') {
        _showChangePasswordSheet();
      } else if (status == 'success') {
        _navigateToDashboard();
      } else {
        _navigateToDashboard();
      }
    } catch (e) {
      if (mounted) {
        String msg = e.toString().replaceAll('Exception: ', '').trim();
        if (msg.contains('SocketException') ||
            msg.contains('Failed host lookup') ||
            msg.contains('Connection refused') ||
            msg.contains('connection error') ||
            msg.contains('subtype of type') ||
            msg.contains('Network is unreachable')) {
          msg = 'Няма връзка със сървъра!';
        }
        setState(() => _errorText = msg);
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  void _showChangePasswordSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: UiThemeTokens.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.only(
          topLeft: UiThemeTokens.borderRadius.topLeft,
          topRight: UiThemeTokens.borderRadius.topRight,
        ),
      ),
      builder: (context) => ChangePasswordSheet(
        authRepository: widget.authRepository,
        isInitialSetup: true,
        onSuccess: _navigateToDashboard,
      ),
    );
  }

  void _navigateToDashboard() {
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (context) => DashboardScreen(
          authRepository: widget.authRepository,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(28.0),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Icon(
                      Icons.school_rounded,
                      size: 44,
                      color: UiThemeTokens.primary,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Exam Gate: Студенти',
                      textAlign: TextAlign.center,
                      style: UiThemeTokens.getSansFont(
                        fontSize: 22, 
                        fontWeight: FontWeight.bold, 
                        color: UiThemeTokens.primary,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Система за дигитален допуск до зали',
                      textAlign: TextAlign.center,
                      style: UiThemeTokens.getSansFont(
                        fontSize: 13, 
                        color: UiThemeTokens.mutedForeground,
                      ),
                    ),
                    const SizedBox(height: 28),
                    TextField(
                      controller: _facNumController,
                      keyboardType: TextInputType.text,
                      decoration: const InputDecoration(
                        labelText: 'Факултетен номер / Имейл',
                      ),
                    ),

                    const SizedBox(height: 14),
                    TextField(
                      controller: _passwordController,
                      obscureText: _obscurePassword,
                      decoration: InputDecoration(
                        labelText: 'Парола / Временен код',
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscurePassword ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                            size: 20,
                            color: UiThemeTokens.mutedForeground,
                          ),
                          onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                        ),
                      ),
                    ),
                    if (_errorText != null) ...[
                      const SizedBox(height: 14),
                      Text(
                        _errorText!,
                        style: UiThemeTokens.getSansFont(
                          color: UiThemeTokens.destructive, 
                          fontSize: 13, 
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                    const SizedBox(height: 24),
                    ElevatedButton(
                      onPressed: _isLoading ? null : () => _handleLogin(isAutoLogin: false),
                      child: _isLoading
                          ? const SizedBox(
                              height: 20, 
                              width: 20, 
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Text('Вход в системата'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}