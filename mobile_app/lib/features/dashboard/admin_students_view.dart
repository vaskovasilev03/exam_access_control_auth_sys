import 'package:flutter/material.dart';
import '../../core/theme_tokens.dart';
import 'models/student_models.dart';

class AdminStudentsView extends StatefulWidget {
  final List<StudentSummaryModel> students;
  final bool isLoading;
  final String? errorMessage;
  final StudentSummaryModel? selectedStudent;
  final ValueChanged<StudentSummaryModel?> onStudentSelected;
  final Future<void> Function() onRefresh;

  const AdminStudentsView({
    super.key,
    required this.students,
    required this.isLoading,
    this.errorMessage,
    this.selectedStudent,
    required this.onStudentSelected,
    required this.onRefresh,
  });

  @override
  State<AdminStudentsView> createState() => _AdminStudentsViewState();
}

class _AdminStudentsViewState extends State<AdminStudentsView> {
  final TextEditingController _searchController = TextEditingController();

  String? _selectedFaculty;
  int? _selectedCourse;
  int? _selectedStream;
  int? _selectedGroup;
  String? _selectedStatus;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  List<String> get _availableFaculties {
    final set = widget.students.map((s) => s.faculty).where((f) => f.isNotEmpty).toSet().toList();
    set.sort();
    return set;
  }

  List<int> get _availableCourses {
    final set = widget.students.map((s) => s.course).toSet().toList();
    set.sort();
    return set;
  }

  List<int> get _availableStreams {
    final filtered = widget.students.where((s) {
      if (_selectedFaculty != null && s.faculty != _selectedFaculty) return false;
      if (_selectedCourse != null && s.course != _selectedCourse) return false;
      return true;
    });
    final set = filtered.map((s) => s.stream).toSet().toList();
    set.sort();
    return set;
  }

  List<int> get _availableGroups {
    final filtered = widget.students.where((s) {
      if (_selectedFaculty != null && s.faculty != _selectedFaculty) return false;
      if (_selectedCourse != null && s.course != _selectedCourse) return false;
      if (_selectedStream != null && s.stream != _selectedStream) return false;
      return true;
    });
    final set = filtered.map((s) => s.group).toSet().toList();
    set.sort();
    return set;
  }

  List<StudentSummaryModel> get _filteredStudents {
    final query = _searchController.text.trim().toLowerCase();

    return widget.students.where((student) {
      if (_selectedFaculty != null && student.faculty != _selectedFaculty) return false;
      if (_selectedCourse != null && student.course != _selectedCourse) return false;
      if (_selectedStream != null && student.stream != _selectedStream) return false;
      if (_selectedGroup != null && student.group != _selectedGroup) return false;
      if (_selectedStatus != null && student.status.toUpperCase() != _selectedStatus!.toUpperCase()) {
        return false;
      }
      if (query.isNotEmpty) {
        final matchesName = student.fullName.toLowerCase().contains(query);
        final matchesId = student.studentIdNumber.toLowerCase().contains(query);
        final matchesSpec = student.specialty.toLowerCase().contains(query);
        if (!matchesName && !matchesId && !matchesSpec) return false;
      }
      return true;
    }).toList();
  }

  void _resetFilters() {
    setState(() {
      _searchController.clear();
      _selectedFaculty = null;
      _selectedCourse = null;
      _selectedStream = null;
      _selectedGroup = null;
      _selectedStatus = null;
    });
  }

  Color _getStatusColor(String status) {
    switch (status.toUpperCase()) {
      case 'APPROVED':
        return Colors.green;
      case 'PENDING_APPROVAL':
        return Colors.amber.shade700;
      case 'PENDING_DUPLICATE_REVIEW':
        return Colors.orange.shade800;
      case 'REJECTED':
        return UiThemeTokens.destructive;
      default:
        return UiThemeTokens.mutedForeground;
    }
  }

  String _getStatusLabel(String status) {
    switch (status.toUpperCase()) {
      case 'APPROVED':
        return 'Одобрен';
      case 'PENDING_APPROVAL':
        return 'Чака одобрение';
      case 'PENDING_DUPLICATE_REVIEW':
        return 'Чака преглед (сходство)';
      case 'REJECTED':
        return 'Отхвърлен';
      case 'PENDING':
        return 'Чака сканиране';
      default:
        return status;
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasActiveFilters = _selectedFaculty != null ||
        _selectedCourse != null ||
        _selectedStream != null ||
        _selectedGroup != null ||
        _selectedStatus != null ||
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
                'Грешка при зареждане на студентите',
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
                // Section Header & count
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.people_alt_outlined, size: 20, color: UiThemeTokens.primary),
                        const SizedBox(width: 8),
                        Text(
                          'Студенти в системата',
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
                        '${_filteredStudents.length} / ${widget.students.length}',
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

                // Selected student indicator (if any)
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
                        Icon(Icons.check_circle, size: 18, color: Colors.amber.shade700),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Избран за симулация: ${widget.selectedStudent!.fullName} (${widget.selectedStudent!.studentIdNumber})',
                            style: UiThemeTokens.getSansFont(
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                              color: Colors.amber.shade300,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          visualDensity: VisualDensity.compact,
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(),
                          tooltip: 'Премахни избора',
                          onPressed: () => widget.onStudentSelected(null),
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
                    hintText: 'Търсене по име, фак. № или специалност...',
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
                      _buildStatusFilter(),
                      const SizedBox(width: 6),
                      if (_availableFaculties.isNotEmpty) ...[
                        _buildFacultyFilter(),
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

          // Students list
          Expanded(
            child: _filteredStudents.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(32.0),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.person_search_outlined, size: 48, color: UiThemeTokens.mutedForeground),
                          const SizedBox(height: 12),
                          Text(
                            'Няма намерени студенти',
                            style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            hasActiveFilters
                                ? 'Няма студент, отговарящ на зададените филтри.'
                                : 'В системата все още няма записани студенти.',
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
                    itemCount: _filteredStudents.length,
                    separatorBuilder: (context, index) => const SizedBox(height: 8),
                    itemBuilder: (context, index) {
                      final student = _filteredStudents[index];
                      final isSelected = widget.selectedStudent?.id == student.id;
                      final initials = student.fullName.trim().split(' ').map((e) => e.isNotEmpty ? e[0] : '').take(2).join();

                      return Card(
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                          side: BorderSide(
                            color: isSelected ? Colors.amber.shade700 : UiThemeTokens.border,
                            width: isSelected ? 2.0 : 1.0,
                          ),
                        ),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(10),
                          onTap: () {
                            if (isSelected) {
                              widget.onStudentSelected(null);
                            } else {
                              widget.onStudentSelected(student);
                            }
                          },
                          child: Padding(
                            padding: const EdgeInsets.all(14.0),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.center,
                              children: [
                                CircleAvatar(
                                  radius: 22,
                                  backgroundColor: _getStatusColor(student.status).withValues(alpha: 0.15),
                                  child: Text(
                                    initials.toUpperCase(),
                                    style: TextStyle(
                                      fontSize: 14,
                                      fontWeight: FontWeight.bold,
                                      color: _getStatusColor(student.status),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        children: [
                                          Expanded(
                                            child: Text(
                                              student.fullName,
                                              style: UiThemeTokens.getSansFont(
                                                fontSize: 15,
                                                fontWeight: FontWeight.bold,
                                              ),
                                              maxLines: 1,
                                              overflow: TextOverflow.ellipsis,
                                            ),
                                          ),
                                          Container(
                                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                            decoration: BoxDecoration(
                                              color: _getStatusColor(student.status).withValues(alpha: 0.15),
                                              borderRadius: BorderRadius.circular(4),
                                            ),
                                            child: Text(
                                              _getStatusLabel(student.status),
                                              style: TextStyle(
                                                fontSize: 10,
                                                fontWeight: FontWeight.bold,
                                                color: _getStatusColor(student.status),
                                              ),
                                            ),
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 4),
                                      Row(
                                        children: [
                                          Text(
                                            'Фак. № ${student.studentIdNumber}',
                                            style: UiThemeTokens.getSansFont(
                                              fontSize: 12,
                                              color: UiThemeTokens.mutedForeground,
                                            ),
                                          ),
                                          const SizedBox(width: 8),
                                          if (student.hasFaceEmbedding)
                                            const Icon(Icons.face, size: 14, color: Colors.green)
                                          else
                                            const Icon(Icons.face_retouching_off, size: 14, color: UiThemeTokens.mutedForeground),
                                        ],
                                      ),
                                      const SizedBox(height: 6),
                                      Wrap(
                                        spacing: 6,
                                        runSpacing: 4,
                                        children: [
                                          _buildMiniBadge(student.faculty),
                                          _buildMiniBadge(student.specialty),
                                          _buildMiniBadge('${student.course} курс'),
                                          _buildMiniBadge('${student.stream} поток'),
                                          _buildMiniBadge('${student.group} група'),
                                        ],
                                      ),
                                    ],
                                  ),
                                ),
                                if (isSelected) ...[
                                  const SizedBox(width: 8),
                                  Icon(Icons.check_circle, color: Colors.amber.shade700, size: 22),
                                ],
                              ],
                            ),
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
    if (text.isEmpty) return const SizedBox.shrink();
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

  Widget _buildStatusFilter() {
    return PopupMenuButton<String?>(
      initialValue: _selectedStatus,
      onSelected: (val) => setState(() => _selectedStatus = val),
      itemBuilder: (context) => [
        const PopupMenuItem(value: null, child: Text('Статус: Всички')),
        const PopupMenuItem(value: 'APPROVED', child: Text('Одобрени')),
        const PopupMenuItem(value: 'PENDING_APPROVAL', child: Text('Чакащи одобрение')),
        const PopupMenuItem(value: 'PENDING_DUPLICATE_REVIEW', child: Text('Чакащи преглед (сходство)')),
        const PopupMenuItem(value: 'PENDING', child: Text('Чакащи сканиране')),
        const PopupMenuItem(value: 'REJECTED', child: Text('Отхвърлени')),
      ],
      child: Chip(
        avatar: Icon(Icons.shield_outlined, size: 14, color: _selectedStatus != null ? Colors.amber.shade700 : null),
        label: Text(
          _selectedStatus == null ? 'Статус' : _getStatusLabel(_selectedStatus!),
          style: TextStyle(
            fontSize: 12,
            color: _selectedStatus != null ? Colors.amber.shade700 : null,
            fontWeight: _selectedStatus != null ? FontWeight.bold : FontWeight.normal,
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
        avatar: Icon(Icons.school_outlined, size: 14, color: _selectedFaculty != null ? Colors.amber.shade700 : null),
        label: Text(
          _selectedFaculty ?? 'Факултет',
          style: TextStyle(
            fontSize: 12,
            color: _selectedFaculty != null ? Colors.amber.shade700 : null,
            fontWeight: _selectedFaculty != null ? FontWeight.bold : FontWeight.normal,
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
            color: _selectedCourse != null ? Colors.amber.shade700 : null,
            fontWeight: _selectedCourse != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildStreamFilter() {
    return PopupMenuButton<int?>(
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
            color: _selectedStream != null ? Colors.amber.shade700 : null,
            fontWeight: _selectedStream != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _buildGroupFilter() {
    return PopupMenuButton<int?>(
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
            color: _selectedGroup != null ? Colors.amber.shade700 : null,
            fontWeight: _selectedGroup != null ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        visualDensity: VisualDensity.compact,
      ),
    );
  }
}
