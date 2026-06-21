import 'package:flutter/material.dart';
import 'theme_tokens.dart';

class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: UiThemeTokens.background,
      colorScheme: const ColorScheme.light(
        primary: UiThemeTokens.primary,
        surface: UiThemeTokens.card,
        error: UiThemeTokens.destructive,
      ),
      
      cardTheme: CardThemeData(
        color: UiThemeTokens.card,
        shape: RoundedRectangleBorder(
          borderRadius: UiThemeTokens.borderRadius,
          side: const BorderSide(color: UiThemeTokens.border),
        ),
        elevation: 0,
      ),

      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: UiThemeTokens.input,
        labelStyle: UiThemeTokens.getSansFont(color: UiThemeTokens.mutedForeground, fontSize: 14),
        border: OutlineInputBorder(
          borderRadius: UiThemeTokens.borderRadius,
          borderSide: const BorderSide(color: UiThemeTokens.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: UiThemeTokens.borderRadius,
          borderSide: const BorderSide(color: UiThemeTokens.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: UiThemeTokens.borderRadius,
          borderSide: const BorderSide(color: UiThemeTokens.ring, width: 1.5),
        ),
      ),

      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: UiThemeTokens.primary,
          foregroundColor: UiThemeTokens.primaryForeground,
          shape: RoundedRectangleBorder(borderRadius: UiThemeTokens.borderRadius),
          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
          elevation: 0,
          textStyle: UiThemeTokens.getSansFont(fontWeight: FontWeight.bold, fontSize: 16),
        ),
      ),
    );
  }
}