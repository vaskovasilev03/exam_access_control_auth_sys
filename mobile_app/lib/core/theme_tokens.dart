import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class UiThemeTokens {
  static const Color background = Color(0xFFF0F0F0);
  static const Color card = Color(0xFFF5F5F5);
  static const Color foreground = Color(0xFF333333);
  static const Color mutedForeground = Color(0xFF666666);
  static const Color primary = Color(0xFF606060);
  static const Color primaryForeground = Color(0xFFFFFFFF);
  static const Color input = Color(0xFFE0E0E0);
  static const Color border = Color(0xFFD0D0D0);
  static const Color destructive = Color(0xFFCC3333);
  static const Color ring = Color(0xFF606060);

  static final BorderRadius borderRadius = BorderRadius.circular(6.0);

  static TextStyle getSansFont({
    Color? color,
    double? fontSize,
    FontWeight? fontWeight,
  }) {
    return GoogleFonts.montserrat(
      color: color ?? foreground,
      fontSize: fontSize,
      fontWeight: fontWeight,
    );
  }
}