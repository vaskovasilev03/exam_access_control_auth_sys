import 'package:flutter/material.dart';

class FaceOverlayPainter extends CustomPainter {
  final Color borderColor;

  FaceOverlayPainter({required this.borderColor});

  @override
  void paint(Canvas canvas, Size size) {
    // Дефинираме леко затъмнен полупрозрачен слой около лицето
    final backgroundPaint = Paint()..color = Colors.black.withOpacity(0.65);
    
    final screenRect = Rect.fromLTWH(0, 0, size.width, size.height);
    
    // Позиционираме овала в центъра (леко изместен нагоре заради интерфейса)
    final ovalRect = Rect.fromCenter(
      center: Offset(size.width / 2, size.height / 2 - 40),
      width: size.width * 0.72,
      height: size.height * 0.44,
    );

    // Изрязваме овала от общия черен правоъгълник на екрана
    final backgroundPath = Path()..addRect(screenRect);
    final ovalPath = Path()..addOval(ovalRect);
    final finalPath = Path.combine(PathOperation.difference, backgroundPath, ovalPath);

    canvas.drawPath(finalPath, backgroundPaint);

    // Изчертаваме динамичната софтуерна рамка около овала
    final borderPaint = Paint()
      ..color = borderColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.5;
    
    canvas.drawOval(ovalRect, borderPaint);
  }

  @override
  bool shouldRepaint(covariant FaceOverlayPainter oldDelegate) {
    return oldDelegate.borderColor != borderColor;
  }
}