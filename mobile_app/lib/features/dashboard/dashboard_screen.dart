import 'package:flutter/material.dart';
import '../../../core/theme_tokens.dart';

import '../auth/auth_repository.dart';

class DashboardScreen extends StatelessWidget {
  final AuthRepository? authRepository;

  const DashboardScreen({super.key, this.authRepository});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  'Основно табло',
                  style: UiThemeTokens.getSansFont(fontSize: 24, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                Text(
                  'Добре дошли в системата за достъп Exam Gate.',
                  textAlign: TextAlign.center,
                  style: UiThemeTokens.getSansFont(color: UiThemeTokens.mutedForeground),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}