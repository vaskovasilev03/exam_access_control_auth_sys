import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'theme_tokens.dart';

class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: UiThemeTokens.background,
      fontFamily: GoogleFonts.montserrat().fontFamily,
      fontFamilyFallback: const ['Roboto', 'sans-serif'],
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
          minimumSize: const Size(64, 44),
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 20),
          elevation: 0,
          textStyle: UiThemeTokens.getSansFont(fontWeight: FontWeight.bold, fontSize: 16),
        ),
      ),
    );
  }
}