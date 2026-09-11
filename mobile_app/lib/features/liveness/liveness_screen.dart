import 'package:flutter/material.dart';
import 'package:mobile_app/core/api_client.dart';
import 'package:mobile_app/features/verification/verification_wizard_screen.dart';

/// @deprecated
/// Legacy single-step screen deprecated in favor of [VerificationWizardScreen].
/// This forwarder ensures backward compatibility across imports while eliminating
/// the previous main-thread YUV byte processing bottlenecks.
@Deprecated('Use VerificationWizardScreen in lib/features/verification instead.')
class LivenessScreen extends StatelessWidget {
  final ApiClient apiClient;

  const LivenessScreen({super.key, required this.apiClient});

  @override
  Widget build(BuildContext context) {
    return VerificationWizardScreen(apiClient: apiClient);
  }
}