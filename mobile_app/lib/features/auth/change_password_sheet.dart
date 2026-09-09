import 'package:flutter/material.dart';
import 'auth_repository.dart';
import '../../core/theme_tokens.dart';

class ChangePasswordSheet extends StatefulWidget {
  final AuthRepository authRepository;
  final VoidCallback onSuccess;
  final bool isInitialSetup;

  const ChangePasswordSheet({
    super.key,
    required this.authRepository,
    required this.onSuccess,
    this.isInitialSetup = false,
  });

  @override
  State<ChangePasswordSheet> createState() => _ChangePasswordSheetState();
}

class _ChangePasswordSheetState extends State<ChangePasswordSheet> {
  final _currentPasswordController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();

  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;

  bool _isLoading = false;
  String? _errorMessage;

  @override
  void dispose() {
    _currentPasswordController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _submitChange() async {
    final currentPassword = _currentPasswordController.text.trim();
    final password = _passwordController.text.trim();
    final confirm = _confirmController.text.trim();

    if (!widget.isInitialSetup && currentPassword.isEmpty) {
      setState(() => _errorMessage = 'Моля, въведете текущата си парола.');
      return;
    }

    if (password.length < 8) {
      setState(() => _errorMessage = 'Паролата трябва да е поне 8 символа.');
      return;
    }

    if (!RegExp(r'[A-Z]').hasMatch(password)) {
      setState(() => _errorMessage = 'Паролата трябва да съдържа поне една главна буква.');
      return;
    }

    if (!RegExp(r'[a-z]').hasMatch(password)) {
      setState(() => _errorMessage = 'Паролата трябва да съдържа поне една малка буква.');
      return;
    }

    if (!RegExp(r'\d').hasMatch(password)) {
      setState(() => _errorMessage = 'Паролата трябва да съдържа поне едно число.');
      return;
    }

    if (!widget.isInitialSetup && currentPassword == password) {
      setState(() => _errorMessage = 'Новата парола трябва да е различна от текущата.');
      return;
    }

    if (password != confirm) {
      setState(() => _errorMessage = 'Паролите не съвпадат!');
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await widget.authRepository.changePassword(
        password,
        oldPassword: widget.isInitialSetup ? null : currentPassword,
      );
      if (mounted) {
        Navigator.pop(context); // Затваряме модала отдолу
        widget.onSuccess();     // Изпълняваме callback при успех
      }
    } catch (e) {
      setState(() => _errorMessage = e.toString().replaceAll('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isInitial = widget.isInitialSetup;

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
        top: 24,
        left: 24,
        right: 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              isInitial ? 'Смяна на временна парола' : 'Промяна на парола',
              style: UiThemeTokens.getSansFont(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              isInitial
                  ? 'Това е първият Ви вход. Моля въведете нова, сигурна парола за достъп.'
                  : 'Въведете текущата си парола и изберете нова за по-висока сигурност на профила.',
              style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.mutedForeground),
            ),
            const SizedBox(height: 20),

            // Поле за текуща парола (показва се само при последваща смяна от профила)
            if (!isInitial) ...[
              TextField(
                controller: _currentPasswordController,
                obscureText: _obscureCurrent,
                decoration: InputDecoration(
                  labelText: 'Текуща парола',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscureCurrent ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                      size: 20,
                      color: UiThemeTokens.mutedForeground,
                    ),
                    onPressed: () => setState(() => _obscureCurrent = !_obscureCurrent),
                  ),
                ),
              ),
              const SizedBox(height: 12),
            ],

            TextField(
              controller: _passwordController,
              obscureText: _obscureNew,
              decoration: InputDecoration(
                labelText: 'Нова парола',
                suffixIcon: IconButton(
                  icon: Icon(
                    _obscureNew ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                    size: 20,
                    color: UiThemeTokens.mutedForeground,
                  ),
                  onPressed: () => setState(() => _obscureNew = !_obscureNew),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _confirmController,
              obscureText: _obscureConfirm,
              decoration: InputDecoration(
                labelText: 'Повторете новата парола',
                suffixIcon: IconButton(
                  icon: Icon(
                    _obscureConfirm ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                    size: 20,
                    color: UiThemeTokens.mutedForeground,
                  ),
                  onPressed: () => setState(() => _obscureConfirm = !_obscureConfirm),
                ),
              ),
            ),
            if (_errorMessage != null) ...[
              const SizedBox(height: 12),
              Text(
                _errorMessage!,
                style: UiThemeTokens.getSansFont(
                  color: UiThemeTokens.destructive,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            const SizedBox(height: 20),
            ElevatedButton(
              onPressed: _isLoading ? null : _submitChange,
              child: _isLoading
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Text(isInitial ? 'Запази и продължи' : 'Обнови паролата'),
            ),
          ],
        ),
      ),
    );
  }
}