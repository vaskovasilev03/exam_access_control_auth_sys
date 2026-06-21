import 'package:flutter/material.dart';
import 'auth_repository.dart';
import '../../core/theme_tokens.dart';

class ChangePasswordSheet extends StatefulWidget {
  final AuthRepository authRepository;
  final VoidCallback onSuccess;

  const ChangePasswordSheet({
    super.key,
    required this.authRepository,
    required this.onSuccess,
  });

  @override
  State<ChangePasswordSheet> createState() => _ChangePasswordSheetState();
}

class _ChangePasswordSheetState extends State<ChangePasswordSheet> {
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  bool _isLoading = false;
  String? _errorMessage;

  Future<void> _submitChange() async {
    final password = _passwordController.text.trim();
    final confirm = _confirmController.text.trim();

    if (password.length < 8) {
      setState(() => _errorMessage = 'Паролата трябва да е поне 8 символа.');
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
      await widget.authRepository.changePassword(password);
      if (mounted) {
        Navigator.pop(context); // Затваряме модала отдолу
        widget.onSuccess();     // Преминаваме към Liveness потока
      }
    } catch (e) {
      setState(() => _errorMessage = e.toString().replaceAll('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
        top: 24, left: 24, right: 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Смяна на временна парола',
            style: UiThemeTokens.getSansFont(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Text(
            'Това е първият Ви вход. Моля въведете нова, сигурна парола за достъп.',
            style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.mutedForeground),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _passwordController,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Нова парола'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _confirmController,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Повторете новата парола'),
          ),
          if (_errorMessage != null) ...[
            const SizedBox(height: 12),
            Text(
              _errorMessage!,
              style: UiThemeTokens.getSansFont(color: UiThemeTokens.destructive, fontSize: 13, fontWeight: FontWeight.w600),
            ),
          ],
          const SizedBox(height: 20),
          ElevatedButton(
            onPressed: _isLoading ? null : _submitChange,
            child: _isLoading 
                ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Text('Запази и продължи'),
          ),
        ],
      ),
    );
  }
}