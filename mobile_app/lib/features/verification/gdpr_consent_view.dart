import 'package:flutter/material.dart';
import 'package:mobile_app/core/theme_tokens.dart';

class GdprConsentView extends StatefulWidget {
  final VoidCallback onConsentGranted;

  const GdprConsentView({super.key, required this.onConsentGranted});

  @override
  State<GdprConsentView> createState() => _GdprConsentViewState();
}

class _GdprConsentViewState extends State<GdprConsentView> {
  bool _consentGiven = false;

  Widget _buildArticleSection({
    required String articleNumber,
    required String title,
    required String content,
    IconData? icon,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (icon != null) ...[
                Icon(icon, size: 16, color: UiThemeTokens.primary),
                const SizedBox(width: 8),
              ],
              Expanded(
                child: Text(
                  '$articleNumber. $title',
                  style: UiThemeTokens.getSansFont(
                    fontSize: 13,
                    fontWeight: FontWeight.bold,
                    color: UiThemeTokens.foreground,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            content,
            textAlign: TextAlign.justify,
            style: UiThemeTokens.getSansFont(
              fontSize: 12,
              height: 1.45,
              color: UiThemeTokens.mutedForeground,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: UiThemeTokens.background,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(20.0, 16.0, 20.0, 20.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Header step badge
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: UiThemeTokens.input,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: UiThemeTokens.border),
                      ),
                      child: Text(
                        'СТЪПКА 1 ОТ 4 • ПОВЕРИТЕЛНОСТ',
                        style: UiThemeTokens.getSansFont(
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          color: UiThemeTokens.mutedForeground,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Биометрично съгласие & GDPR декларация',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        height: 1.2,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Официално институционално споразумение за обработване на биометрични данни и валидация на студентска книжка.',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 12,
                        color: UiThemeTokens.mutedForeground,
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Unified Official Document Container
                    Container(
                      decoration: BoxDecoration(
                        color: UiThemeTokens.card,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: UiThemeTokens.border, width: 1.2),
                        boxShadow: [
                          BoxShadow(
                            color: Colors.black.withValues(alpha: 0.03),
                            blurRadius: 10,
                            offset: const Offset(0, 4),
                          ),
                        ],
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // Document Letterhead Banner
                          Container(
                            padding: const EdgeInsets.all(14.0),
                            decoration: BoxDecoration(
                              color: UiThemeTokens.input.withValues(alpha: 0.6),
                              borderRadius: const BorderRadius.only(
                                topLeft: Radius.circular(9),
                                topRight: Radius.circular(9),
                              ),
                              border: const Border(
                                bottom: BorderSide(color: UiThemeTokens.border),
                              ),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  Icons.account_balance_outlined,
                                  size: 20,
                                  color: UiThemeTokens.foreground,
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'ТЕХНИЧЕСКИ УНИВЕРСИТЕТ - СОФИЯ',
                                        style: UiThemeTokens.getSansFont(
                                          fontSize: 11,
                                          fontWeight: FontWeight.w800,
                                          letterSpacing: 0.5,
                                          color: UiThemeTokens.foreground,
                                        ),
                                      ),
                                      Text(
                                        'СИСТЕМА ЗА КОНТРОЛ НА ДОСТЪПА ДО ИЗПИТИ (AACAS)',
                                        style: UiThemeTokens.getSansFont(
                                          fontSize: 9,
                                          color: UiThemeTokens.mutedForeground,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: UiThemeTokens.background,
                                    borderRadius: BorderRadius.circular(4),
                                    border: Border.all(color: UiThemeTokens.border),
                                  ),
                                  child: Text(
                                    'v1.2 / GDPR',
                                    style: UiThemeTokens.getSansFont(
                                      fontSize: 9,
                                      fontWeight: FontWeight.bold,
                                      color: UiThemeTokens.mutedForeground,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),

                          // Document Body Articles
                          Padding(
                            padding: const EdgeInsets.all(16.0),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                _buildArticleSection(
                                  articleNumber: 'Чл. 1',
                                  title: 'Правно основание и предназначение',
                                  icon: Icons.gavel_rounded,
                                  content:
                                      'Обработването на специални категории лични данни се осъществява на основание Чл. 6, ал. 1, б. „а“ и Чл. 9, ал. 2, б. „а“ от Регламент (ЕС) 2016/679 (GDPR) единствено за потвърждаване на самоличността при вход в изпитните зали и недопускане на нерегламентирано явяване.',
                                ),
                                const Divider(height: 1, color: UiThemeTokens.border),
                                _buildArticleSection(
                                  articleNumber: 'Чл. 2',
                                  title: 'Биометричен дескриптор и криптиране',
                                  icon: Icons.fingerprint_rounded,
                                  content:
                                      'От заснетия лицеви контур се генерира невъзстановим 128-мерен криптографски математически вектор. При автоматизирания турникетен контрол се сравняват вектори, а не сурови фотографски изображения.',
                                ),
                                const Divider(height: 1, color: UiThemeTokens.border),
                                _buildArticleSection(
                                  articleNumber: 'Чл. 3',
                                  title: 'Двуфакторна верификация на книжка',
                                  icon: Icons.menu_book_rounded,
                                  content:
                                      'Заснемането на първа страница от студентската книжка служи за потвърждаване на факултетен номер, печати и снимка от оторизиран администратор преди активиране на допуска.',
                                ),
                                const Divider(height: 1, color: UiThemeTokens.border),
                                _buildArticleSection(
                                  articleNumber: 'Чл. 4',
                                  title: 'Човешка намеса и защита от грешки (Чл. 22)',
                                  icon: Icons.supervised_user_circle_outlined,
                                  content:
                                      'Не се прилагат изцяло автоматизирани решения със съществени последици. При идентични близнаци или спорни съвпадения достъпът се удостоверява лично от дежурен квестор.',
                                ),
                                const Divider(height: 1, color: UiThemeTokens.border),
                                _buildArticleSection(
                                  articleNumber: 'Чл. 5',
                                  title: 'Срок на съхранение и права на студента',
                                  icon: Icons.shield_outlined,
                                  content:
                                      'Данните се съхраняват в криптиран университетски клъстер за срока на обучението. Имате право на достъп, корекция, оттегляне на съгласието и избор на алтернативен физически контрол.',
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 16),

                    // Official Declaration Checkbox Box
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      decoration: BoxDecoration(
                        color: _consentGiven
                            ? Colors.green.withValues(alpha: 0.06)
                            : UiThemeTokens.card,
                        borderRadius: UiThemeTokens.borderRadius,
                        border: Border.all(
                          color: _consentGiven
                              ? Colors.green.shade400
                              : UiThemeTokens.border,
                          width: 1.5,
                        ),
                      ),
                      child: InkWell(
                        onTap: () {
                          setState(() {
                            _consentGiven = !_consentGiven;
                          });
                        },
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.center,
                          children: [
                            Checkbox(
                              value: _consentGiven,
                              onChanged: (val) {
                                setState(() {
                                  _consentGiven = val ?? false;
                                });
                              },
                              activeColor: UiThemeTokens.primary,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'Декларирам, че съм запознат с условията и давам своето изрично съгласие за обработване на биометричните ми данни и студентска книжка за изпитния контрол.',
                                style: UiThemeTokens.getSansFont(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  height: 1.35,
                                  color: UiThemeTokens.foreground,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // Bottom bar
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
              decoration: const BoxDecoration(
                color: UiThemeTokens.card,
                border: Border(top: BorderSide(color: UiThemeTokens.border)),
              ),
              child: SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: _consentGiven ? widget.onConsentGranted : null,
                  icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                  label: const Text('Продължи към заснемане'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _consentGiven
                        ? UiThemeTokens.primary
                        : UiThemeTokens.mutedForeground.withValues(alpha: 0.3),
                    foregroundColor: UiThemeTokens.primaryForeground,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: UiThemeTokens.borderRadius,
                    ),
                    textStyle: UiThemeTokens.getSansFont(
                      fontSize: 14,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

