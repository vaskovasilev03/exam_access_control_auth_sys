import 'package:flutter/material.dart';
import '../../core/theme_tokens.dart';
import 'models/student_models.dart';

class AdminExamsView extends StatefulWidget {
  final List<ExamItemModel> exams;
  final bool isLoading;
  final String? errorMessage;
  final StudentSummaryModel? selectedStudent;
  final VoidCallback? onClearSelectedStudent;
  final Future<void> Function() onRefresh;

  const AdminExamsView({
    super.key,
    required this.exams,
    required this.isLoading,
    this.errorMessage,
    this.selectedStudent,
    this.onClearSelectedStudent,
    required this.onRefresh,
  });

  @override
  State<AdminExamsView> createState() => _AdminExamsViewState();
}

class _AdminExamsViewState extends State<AdminExamsView> {
  final TextEditingController _searchController = TextEditingController();

  String? _selectedSessionType;
  String? _selectedFaculty;
  String? _selectedSpecialty;
  int? _selectedCourse;
  String? _selectedStream;
  String? _selectedGroup;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  List<String> get _availableFaculties {
    final set = widget.exams
        .map((e) => e.faculty)
        .where((f) => f != null && f.isNotEmpty)
        .cast<String>()
        .toSet()
        .toList();
    set.sort();
    return set;
  }

  List<String> get _availableSpecialties {
    final filtered = widget.exams.where((e) {
      if (_selectedFaculty != null && e.faculty != _selectedFaculty) return false;
      return true;
    });
    final set = filtered
        .map((e) => e.specialty)
        .where((s) => s != null && s.isNotEmpty)
        .cast<String>()
        .toSet()
        .toList();
    set.sort();
    return set;
  }

  List<int> get _availableCourses {
    final set = widget.exams
        .map((e) => e.course)
        .where((c) => c != null && c > 0)
        .cast<int>()
        .toSet()
        .toList();
    set.sort();
    return set;
  }

  List<String> get _availableStreams {
    final filtered = widget.exams.where((e) {
      if (_selectedFaculty != null && e.faculty != _selectedFaculty) return false;
      if (_selectedCourse != null && e.course != _selectedCourse) return false;
      return true;
    });
    final set = filtered
        .map((e) => e.stream)
        .where((s) => s != null && s.isNotEmpty)
        .cast<String>()
        .toSet()
        .toList();
    set.sort();
    return set;
  }

  List<String> get _availableGroups {
    final filtered = widget.exams.where((e) {
      if (_selectedFaculty != null && e.faculty != _selectedFaculty) return false;
      if (_selectedCourse != null && e.course != _selectedCourse) return false;
      if (_selectedStream != null && e.stream != _selectedStream) return false;
      return true;
    });
    final set = filtered
        .map((e) => e.group)
        .where((g) => g != null && g.isNotEmpty)
        .cast<String>()
        .toSet()
        .toList();
    set.sort();
    return set;
  }

  List<ExamItemModel> get _filteredExams {
    final query = _searchController.text.trim().toLowerCase();

    return widget.exams.where((exam) {
      if (_selectedSessionType != null) {
        if (exam.sessionType?.toLowerCase() != _selectedSessionType!.toLowerCase()) {
          return false;
        }
      }
      if (_selectedFaculty != null && exam.faculty != _selectedFaculty) return false;
      if (_selectedSpecialty != null && exam.specialty != _selectedSpecialty) return false;
      if (_selectedCourse != null && exam.course != _selectedCourse) return false;
      if (_selectedStream != null && exam.stream != _selectedStream) return false;
      if (_selectedGroup != null) {
        // Поддържа група разделена със запетая напр. "37, 38"
        final examGroups = (exam.group ?? '').split(',').map((g) => g.trim());
        if (!examGroups.contains(_selectedGroup)) return false;
      }

      if (query.isNotEmpty) {
        final matchesSubject = exam.subject.toLowerCase().contains(query);
        final matchesLecturer = (exam.lecturer ?? '').toLowerCase().contains(query);
        final matchesRoom = exam.roomNumber.toLowerCase().contains(query);
        final matchesSpec = (exam.specialty ?? '').toLowerCase().contains(query);
        if (!matchesSubject && !matchesLecturer && !matchesRoom && !matchesSpec) return false;
      }

      return true;
    }).toList();
  }

  void _resetFilters() {
    setState(() {
      _searchController.clear();
      _selectedSessionType = null;
      _selectedFaculty = null;
      _selectedSpecialty = null;
      _selectedCourse = null;
      _selectedStream = null;
      _selectedGroup = null;
    });
  }

  Color _getSessionTypeColor(String? type) {
    if (type == null) return UiThemeTokens.primary;
    final lower = type.toLowerCase();
    if (lower.contains('летн') || lower.contains('summer')) {
      return Colors.blue.shade600;
    } else if (lower.contains('зимн') || lower.contains('winter')) {
      return Colors.indigo.shade600;
    } else if (lower.contains('поправителн') || lower.contains('resit')) {
      return Colors.orange.shade700;
    } else if (lower.contains('ликвидационн') || lower.contains('liquidation')) {
      return UiThemeTokens.destructive;
    }
    return UiThemeTokens.primary;
  }

  String _formatSessionTypeLabel(String? type) {
    if (type == null || type.isEmpty) return 'Редовна';
    final lower = type.toLowerCase();
    if (lower.contains('летн')) return 'Редовна Лятна';
    if (lower.contains('зимн')) return 'Редовна Зимна';
    if (lower.contains('поправителн')) return 'Поправителна';
    if (lower.contains('ликвидационн')) return 'Ликвидационна';
    return type;
  }

  @override
  Widget build(BuildContext context) {
    final hasActiveFilters = _selectedSessionType != null ||
        _selectedFaculty != null ||
        _selectedSpecialty != null ||
        _selectedCourse != null ||
        _selectedStream != null ||
        _selectedGroup != null ||
        _searchController.text.isNotEmpty;

    if (widget.isLoading) {
      return const Center(child: CircularProgressIndicator(color: UiThemeTokens.primary));
    }

    if (widget.errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 48, color: UiThemeTokens.destructive),
              const SizedBox(height: 12),
              Text(
                'Грешка при зареждане на изпитите',
                style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 6),
              Text(
                widget.errorMessage!,
                textAlign: TextAlign.center,
                style: UiThemeTokens.getSansFont(color: UiThemeTokens.mutedForeground, fontSize: 13),
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: widget.onRefresh,
                child: const Text('Опитай отново'),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: widget.onRefresh,
      color: UiThemeTokens.primary,
      child: Column(
        children: [
          // Top controls bar
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            decoration: const BoxDecoration(
              color: UiThemeTokens.card,
              border: Border(bottom: BorderSide(color: UiThemeTokens.border)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header & Count
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.calendar_month_outlined, size: 20, color: UiThemeTokens.primary),
                        const SizedBox(width: 8),
                        Text(
                          'График на изпитите',
                          style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
                        ),
                      ],
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: UiThemeTokens.input,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        '${_filteredExams.length} / ${widget.exams.length}',
                        style: UiThemeTokens.getSansFont(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: UiThemeTokens.mutedForeground,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),

                // Focused student banner (if any)
                if (widget.selectedStudent != null) ...[
                  Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: Colors.amber.shade900.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.amber.shade700.withValues(alpha: 0.5)),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.person_pin, size: 18, color: Colors.amber.shade700),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Филтрирано за: ${widget.selectedStudent!.fullName} (гр. ${widget.selectedStudent!.group}, ${widget.selectedStudent!.course} к.)',
                            style: UiThemeTokens.getSansFont(
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                              color: Colors.amber.shade300,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (widget.onClearSelectedStudent != null)
                          IconButton(
                            icon: const Icon(Icons.close, size: 16),
                            visualDensity: VisualDensity.compact,
                            padding: EdgeInsets.zero,
                            constraints: const BoxConstraints(),
                            tooltip: 'Покажи всички изпити',
                            onPressed: widget.onClearSelectedStudent,
                          ),
                      ],
                    ),
                  ),
                ],

                // Search field
                TextField(
                  controller: _searchController,
                  onChanged: (_) => setState(() {}),
                  style: UiThemeTokens.getSansFont(fontSize: 13),
                  decoration: InputDecoration(
                    hintText: 'Търсене по предмет, преподавател, зала...',
                    hintStyle: UiThemeTokens.getSansFont(fontSize: 12, color: UiThemeTokens.mutedForeground),
                    prefixIcon: const Icon(Icons.search, size: 18),
                    suffixIcon: _searchController.text.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear, size: 16),
                            onPressed: () {
                              _searchController.clear();
                              setState(() {});
                            },
                          )
                        : null,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
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
                      borderSide: const BorderSide(color: UiThemeTokens.primary, width: 1.5),
                    ),
                  ),
                ),
                const SizedBox(height: 8),

                // Filter chips scrollable row
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      if (hasActiveFilters) ...[
                        ActionChip(
                          avatar: const Icon(Icons.filter_alt_off, size: 13),
                          label: const Text('Изчисти'),
                          onPressed: _resetFilters,
                          visualDensity: VisualDensity.compact,
                        ),
                        const SizedBox(width: 6),
                      ],
                      _buildSessionTypeFilter(),
                      const SizedBox(width: 6),
                      if (_availableFaculties.isNotEmpty) ...[
                        _buildFacultyFilter(),
                        const SizedBox(width: 6),
                      ],
                      if (_availableSpecialties.isNotEmpty) ...[
                        _buildSpecialtyFilter(),
                        const SizedBox(width: 6),
                      ],
                      if (_availableCourses.isNotEmpty) ...[
                        _buildCourseFilter(),
                        const SizedBox(width: 6),
                      ],
                      if (_availableStreams.isNotEmpty) ...[
                        _buildStreamFilter(),
                        const SizedBox(width: 6),
                      ],
                      if (_availableGroups.isNotEmpty) ...[
                        _buildGroupFilter(),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),

          // Exams list
          Expanded(
            child: _filteredExams.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(32.0),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.event_busy_outlined, size: 48, color: UiThemeTokens.mutedForeground),
                          const SizedBox(height: 12),
                          Text(
                            'Няма намерени изпити',
                            style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            hasActiveFilters
                                ? 'Няма изпит, отговарящ на зададените филтри.'
                                : 'В базата данни няма въведени изпити.',
                            textAlign: TextAlign.center,
                            style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.mutedForeground),
                          ),
                          if (hasActiveFilters) ...[
                            const SizedBox(height: 12),
                            OutlinedButton(
                              onPressed: _resetFilters,
                              child: const Text('Изчисти филтрите'),
                            ),
                          ],
                        ],
                      ),
                    ),
                  )
                : ListView.separated(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(16.0),
                    itemCount: _filteredExams.length,
                    separatorBuilder: (context, index) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final exam = _filteredExams[index];
                      final sessionColor = _getSessionTypeColor(exam.sessionType);

                      return Card(
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                          side: const BorderSide(color: UiThemeTokens.border),
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(16.0),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              // Subject & Session Type Badge
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Expanded(
                                    child: Text(
                                      exam.subject,
                                      style: UiThemeTokens.getSansFont(
                                        fontSize: 16,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
                                    decoration: BoxDecoration(
                                      color: sessionColor.withValues(alpha: 0.15),
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(
                                      _formatSessionTypeLabel(exam.sessionType),
                                      style: TextStyle(
                                        fontSize: 10,
                                        fontWeight: FontWeight.bold,
                                        color: sessionColor,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 8),

                              // Date & Time
                              Row(
                                children: [
                                  const Icon(Icons.schedule, size: 15, color: UiThemeTokens.mutedForeground),
                                  const SizedBox(width: 6),
                                  Text(
                                    exam.formattedDateTime,
                                    style: UiThemeTokens.getSansFont(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                      color: UiThemeTokens.foreground,
                                    ),
                                  ),
                                  const Spacer(),
                                  // Room
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: UiThemeTokens.input,
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        const Icon(Icons.meeting_room_outlined, size: 13, color: UiThemeTokens.mutedForeground),
                                        const SizedBox(width: 4),
                                        Text(
                                          'Зала ${exam.roomNumber}',
                                          style: UiThemeTokens.getSansFont(
                                            fontSize: 11,
                                            fontWeight: FontWeight.bold,
                                            color: UiThemeTokens.foreground,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 6),

                              // Lecturer
                              Row(
                                children: [
                                  const Icon(Icons.person_outline, size: 15, color: UiThemeTokens.mutedForeground),
                                  const SizedBox(width: 6),
                                  Expanded(
                                    child: Text(
                                      exam.lecturer ?? 'Не е указан',
                                      style: UiThemeTokens.getSansFont(
                                        fontSize: 12,
                                        color: UiThemeTokens.mutedForeground,
                                      ),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 8),

                              // Audience Badges: Faculty, Specialty, Course, Stream, Groups
                              Wrap(
                                spacing: 6,
                                runSpacing: 4,
                                children: [
                                  if (exam.faculty != null && exam.faculty!.isNotEmpty)
                                    _buildMiniBadge(exam.faculty!),
                                  if (exam.specialty != null && exam.specialty!.isNotEmpty)
                                    _buildMiniBadge(exam.specialty!),
                                  if (exam.course != null && exam.course! > 0)
                                    _buildMiniBadge('${exam.course} курс'),
                                  if (exam.stream != null && exam.stream!.isNotEmpty)
                                    _buildMiniBadge('${exam.stream} поток'),
                                  if (exam.group != null && exam.group!.isNotEmpty)
                                    _buildMiniBadge('гр. ${exam.group}'),
                                ],
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildMiniBadge(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: UiThemeTokens.input,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style: UiThemeTokens.getSansFont(fontSize: 11, color: UiThemeTokens.foreground),
      ),
    );
  }

  Widget _buildSessionTypeFilter() {
    return PopupMenuButton<String?>(
      initialValue: _selectedSessionType,
      onSelected: (val) => setState(() => _selectedSessionType = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Тип: Всички')),
        const PopupMenuItem(value: 'редовна лятна', child: Text('Редовна Лятна')),
        const PopupMenuItem(value: 'редовна зимна', child: Text('Редовна Зимна')),
        const PopupMenuItem(value: 'поправителна', child: Text('Поправителна')),
        const PopupMenuItem(value: 'ликвидационна', child: Text('Ликвидационна')),
      ],
      child: Chip(
        avatar: Icon(Icons.event_note, size: 14, color: _selectedSessionType != null ? UiThemeTokens.primary : null),
        label: Text(
          _selectedSessionType == null ? 'Сесия' : _formatSessionTypeLabel(_selectedSessionType),
          style: TextStyle(
            fontSize: 12,
            color: _selectedSessionType != null ? UiThemeTokens.primary : null,
            fontWeight: _selectedSessionType != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildFacultyFilter() {
    return PopupMenuButton<String?>(
      initialValue: _selectedFaculty,
      onSelected: (val) => setState(() => _selectedFaculty = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Факултет: Всички')),
        ..._availableFaculties.map((f) => PopupMenuItem(value: f, child: Text(f))),
      ],
      child: Chip(
        avatar: Icon(Icons.school_outlined, size: 14, color: _selectedFaculty != null ? UiThemeTokens.primary : null),
        label: Text(
          _selectedFaculty ?? 'Факултет',
          style: TextStyle(
            fontSize: 12,
            color: _selectedFaculty != null ? UiThemeTokens.primary : null,
            fontWeight: _selectedFaculty != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildSpecialtyFilter() {
    return PopupMenuButton<String?>(
      initialValue: _selectedSpecialty,
      onSelected: (val) => setState(() => _selectedSpecialty = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Специалност: Всички')),
        ..._availableSpecialties.map((s) => PopupMenuItem(value: s, child: Text(s))),
      ],
      child: Chip(
        label: Text(
          _selectedSpecialty ?? 'Специалност',
          style: TextStyle(
            fontSize: 12,
            color: _selectedSpecialty != null ? UiThemeTokens.primary : null,
            fontWeight: _selectedSpecialty != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildCourseFilter() {
    return PopupMenuButton<int?>(
      initialValue: _selectedCourse,
      onSelected: (val) => setState(() => _selectedCourse = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Курс: Всички')),
        ..._availableCourses.map((c) => PopupMenuItem(value: c, child: Text('$c курс'))),
      ],
      child: Chip(
        label: Text(
          _selectedCourse == null ? 'Курс' : '$_selectedCourse к.',
          style: TextStyle(
            fontSize: 12,
            color: _selectedCourse != null ? UiThemeTokens.primary : null,
            fontWeight: _selectedCourse != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildStreamFilter() {
    return PopupMenuButton<String?>(
      initialValue: _selectedStream,
      onSelected: (val) => setState(() => _selectedStream = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Поток: Всички')),
        ..._availableStreams.map((s) => PopupMenuItem(value: s, child: Text('$s поток'))),
      ],
      child: Chip(
        label: Text(
          _selectedStream == null ? 'Поток' : '$_selectedStream п.',
          style: TextStyle(
            fontSize: 12,
            color: _selectedStream != null ? UiThemeTokens.primary : null,
            fontWeight: _selectedStream != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildGroupFilter() {
    return PopupMenuButton<String?>(
      initialValue: _selectedGroup,
      onSelected: (val) => setState(() => _selectedGroup = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Група: Всички')),
        ..._availableGroups.map((g) => PopupMenuItem(value: g, child: Text('$g група'))),
      ],
      child: Chip(
        label: Text(
          _selectedGroup == null ? 'Група' : '$_selectedGroup гр.',
          style: TextStyle(
            fontSize: 12,
            color: _selectedGroup != null ? UiThemeTokens.primary : null,
            fontWeight: _selectedGroup != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }
}
