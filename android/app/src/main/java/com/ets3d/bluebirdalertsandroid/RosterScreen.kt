@file:OptIn(
    androidx.compose.foundation.layout.ExperimentalLayoutApi::class,
    androidx.compose.material3.ExperimentalMaterial3Api::class,
)

package com.ets3d.bluebirdalertsandroid

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.viewmodel.compose.viewModel

private val GRADE_OPTIONS = listOf("PreK", "K") + (1..12).map { it.toString() } + listOf("Other")
private val CLAIM_STATUS_OPTIONS = listOf("present_with_me", "absent", "missing", "injured", "released", "unknown")

private fun statusLabel(s: String) = s.replace("_", " ").split(" ").joinToString(" ") { it.replaceFirstChar(Char::uppercaseChar) }

private fun statusColor(s: String?): Color = when (s) {
    "present_with_me" -> Color(0xFF4ADE80)
    "missing" -> Color(0xFFEF4444)
    "injured" -> Color(0xFFF97316)
    "released" -> Color(0xFF60A5FA)
    "absent" -> Color(0xFFFBBF24)
    else -> Color(0xFF94A3B8)
}

@Composable
fun RosterScreen(
    alertId: Int,
    ctx: Context,
    onDismiss: () -> Unit,
    vm: MainViewModel = viewModel(),
) {
    val state by vm.state.collectAsState()
    val roster = state.incidentRoster
    val isLoading = state.isLoadingRoster

    var searchQuery by remember { mutableStateOf("") }
    var gradeFilter by remember { mutableStateOf("") }   // "" = all grades
    var gradeFilterExpanded by remember { mutableStateOf(false) }
    var showAddSheet by remember { mutableStateOf(false) }
    var pendingClaimRow by remember { mutableStateOf<RosterIncidentRow?>(null) }
    var pendingClaimStatus by remember { mutableStateOf("present_with_me") }
    var conflictMessage by remember { mutableStateOf<String?>(null) }
    var pendingTakeoverRow by remember { mutableStateOf<RosterIncidentRow?>(null) }
    var accountabilityMode by remember { mutableStateOf(false) }
    var markedPresent by remember { mutableStateOf(emptySet<Int>()) }
    var markedMissing by remember { mutableStateOf(emptySet<Int>()) }
    val isSubmittingAccountability = state.isSubmittingAccountability

    LaunchedEffect(accountabilityMode) {
        if (!accountabilityMode) {
            markedPresent = emptySet()
            markedMissing = emptySet()
        }
    }

    LaunchedEffect(alertId) { vm.loadIncidentRoster(ctx, alertId) }

    val filtered = remember(roster, searchQuery, gradeFilter) {
        roster?.students?.filter { row ->
            val matchesSearch = searchQuery.isBlank() || row.fullName.contains(searchQuery, ignoreCase = true)
            val matchesGrade = gradeFilter.isBlank() || row.gradeLevel == gradeFilter
            matchesSearch && matchesGrade
        } ?: emptyList()
    }

    val accountabilityStudents = remember(roster) {
        roster?.students?.filter { !it.isAddition } ?: emptyList()
    }

    val filteredAccountability = remember(accountabilityStudents, searchQuery, gradeFilter) {
        accountabilityStudents.filter { row ->
            val matchesSearch = searchQuery.isBlank() || row.fullName.contains(searchQuery, ignoreCase = true)
            val matchesGrade = gradeFilter.isBlank() || row.gradeLevel == gradeFilter
            matchesSearch && matchesGrade
        }
    }

    // Unique grades present in the loaded roster for the dropdown
    val availableGrades = remember(roster) {
        roster?.students?.map { it.gradeLevel }?.distinct()
            ?.sortedWith(compareBy { GRADE_OPTIONS.indexOf(it).takeIf { i -> i >= 0 } ?: Int.MAX_VALUE })
            ?: emptyList()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Student Roster", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Default.Close, contentDescription = "Close")
                    }
                },
                actions = {
                    TextButton(onClick = { accountabilityMode = !accountabilityMode }) {
                        Text(
                            if (accountabilityMode) "Exit" else "Roll Call",
                            color = if (accountabilityMode) Color(0xFFEF4444) else Color(0xFF4D88FF),
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 14.sp,
                        )
                    }
                },
            )
        },
        bottomBar = {
            if (accountabilityMode) {
                val presentCount = markedPresent.size
                val missingCount = markedMissing.size
                val unmarkedCount = accountabilityStudents.size - presentCount - missingCount
                Surface(
                    color = Color(0xFF1E293B),
                    tonalElevation = 3.dp,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(
                                "$presentCount present · $missingCount missing · $unmarkedCount unmarked",
                                color = Color(0xFFCBD5E1),
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                "Tap Submit to record batch accountability",
                                color = Color(0xFF64748B),
                                fontSize = 11.sp,
                            )
                        }
                        Button(
                            onClick = {
                                vm.submitAccountability(ctx, alertId, markedPresent.toList(), markedMissing.toList()) {
                                    accountabilityMode = false
                                }
                            },
                            enabled = !isSubmittingAccountability && (markedPresent.isNotEmpty() || markedMissing.isNotEmpty()),
                        ) {
                            if (isSubmittingAccountability) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(16.dp),
                                    strokeWidth = 2.dp,
                                    color = Color.White,
                                )
                            } else {
                                Text("Submit")
                            }
                        }
                    }
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            // Summary bar
            roster?.summary?.let { s ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFF1E293B))
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    RosterSummaryChip("Total", s.total, Color(0xFFCBD5E1))
                    RosterSummaryChip("With Me", s.presentWithMe, Color(0xFF4ADE80))
                    RosterSummaryChip("Missing", s.missing, Color(0xFFEF4444))
                    RosterSummaryChip("Unclaimed", s.unclaimed, Color(0xFF94A3B8))
                }
            }

            // Search + grade filter + Add button
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = searchQuery,
                        onValueChange = { searchQuery = it },
                        placeholder = { Text("Search students…") },
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    )
                    Button(onClick = { showAddSheet = true }) { Text("+ Add") }
                }
                if (availableGrades.isNotEmpty()) {
                    ExposedDropdownMenuBox(
                        expanded = gradeFilterExpanded,
                        onExpandedChange = { gradeFilterExpanded = it },
                    ) {
                        OutlinedTextField(
                            value = if (gradeFilter.isBlank()) "All Grades" else "Grade $gradeFilter",
                            onValueChange = {},
                            readOnly = true,
                            label = { Text("Grade Filter") },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = gradeFilterExpanded) },
                            modifier = Modifier.fillMaxWidth().menuAnchor(),
                            singleLine = true,
                        )
                        ExposedDropdownMenu(
                            expanded = gradeFilterExpanded,
                            onDismissRequest = { gradeFilterExpanded = false },
                        ) {
                            DropdownMenuItem(
                                text = { Text("All Grades") },
                                onClick = { gradeFilter = ""; gradeFilterExpanded = false },
                            )
                            availableGrades.forEach { g ->
                                DropdownMenuItem(
                                    text = { Text("Grade $g") },
                                    onClick = { gradeFilter = g; gradeFilterExpanded = false },
                                )
                            }
                        }
                    }
                }
            }

            if (isLoading && roster == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            } else if (accountabilityMode) {
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(filteredAccountability, key = { it.rowId }) { row ->
                        row.studentId?.let { sid ->
                            AccountabilityRowCard(
                                row = row,
                                isPresent = sid in markedPresent,
                                isMissing = sid in markedMissing,
                                onMarkPresent = {
                                    markedPresent = markedPresent + sid
                                    markedMissing = markedMissing - sid
                                },
                                onMarkMissing = {
                                    markedMissing = markedMissing + sid
                                    markedPresent = markedPresent - sid
                                },
                                onClear = {
                                    markedPresent = markedPresent - sid
                                    markedMissing = markedMissing - sid
                                },
                            )
                        }
                    }
                    if (filteredAccountability.isEmpty() && !isLoading) {
                        item {
                            Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                                Text("No students to mark.", color = Color(0xFF94A3B8))
                            }
                        }
                    }
                }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(filtered, key = { it.rowId }) { row ->
                        RosterRowCard(
                            row = row,
                            onClaim = { status ->
                                pendingClaimRow = row
                                pendingClaimStatus = status
                                vm.claimRosterStudent(
                                    ctx, alertId, row.studentId, row.additionId, status,
                                    onConflict = { msg ->
                                        conflictMessage = msg
                                        pendingTakeoverRow = row
                                    }
                                )
                            },
                            onRelease = { claimId ->
                                vm.releaseRosterClaim(ctx, alertId, claimId)
                        },
                        )
                    }
                    if (filtered.isEmpty() && !isLoading) {
                        item {
                            Box(
                                Modifier.fillMaxWidth().padding(32.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    when {
                                        searchQuery.isNotBlank() && gradeFilter.isNotBlank() -> "No results for \"$searchQuery\" in Grade $gradeFilter."
                                        searchQuery.isNotBlank() -> "No results for \"$searchQuery\"."
                                        gradeFilter.isNotBlank() -> "No students in Grade $gradeFilter."
                                        else -> "No students in roster."
                                    },
                                    color = Color(0xFF94A3B8),
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // Add incident student sheet
    if (showAddSheet) {
        AddIncidentStudentDialog(
            onDismiss = { showAddSheet = false },
            onAdd = { fn, ln, gl, note ->
                vm.addIncidentStudent(ctx, alertId, fn, ln, gl, note)
                showAddSheet = false
            },
        )
    }

    // Takeover conflict dialog
    conflictMessage?.let { msg ->
        AlertDialog(
            onDismissRequest = { conflictMessage = null; pendingTakeoverRow = null },
            title = { Text("Claim Conflict") },
            text = { Text(msg) },
            confirmButton = {
                TextButton(onClick = {
                    pendingTakeoverRow?.let { row ->
                        vm.claimRosterStudent(ctx, alertId, row.studentId, row.additionId, pendingClaimStatus, takeoverConfirmed = true, onConflict = {})
                    }
                    conflictMessage = null
                    pendingTakeoverRow = null
                }) { Text("Confirm Takeover") }
            },
            dismissButton = {
                TextButton(onClick = { conflictMessage = null; pendingTakeoverRow = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun RosterSummaryChip(label: String, count: Int, color: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(count.toString(), color = color, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Text(label, color = Color(0xFF94A3B8), fontSize = 11.sp)
    }
}

@Composable
private fun RosterRowCard(
    row: RosterIncidentRow,
    onClaim: (String) -> Unit,
    onRelease: (Int) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val claim = row.claim
    val claimColor = statusColor(claim?.status)

    Card(
        modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded },
        shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E293B)),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(row.fullName, color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        if (row.isAddition) {
                            Text(
                                "added",
                                color = Color(0xFFFBBF24),
                                fontSize = 10.sp,
                                modifier = Modifier
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(Color(0xFF92400E))
                                    .padding(horizontal = 4.dp, vertical = 1.dp),
                            )
                        }
                    }
                    Text("Grade ${row.gradeLevel}", color = Color(0xFF94A3B8), fontSize = 12.sp)
                }
                if (claim != null) {
                    Column(horizontalAlignment = Alignment.End) {
                        Text(
                            statusLabel(claim.status),
                            color = claimColor,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium,
                        )
                        Text(claim.claimedByLabel, color = Color(0xFF64748B), fontSize = 10.sp)
                    }
                } else {
                    Text("Unclaimed", color = Color(0xFF64748B), fontSize = 12.sp)
                }
            }

            if (expanded) {
                Spacer(Modifier.height(10.dp))
                Text("Set status:", color = Color(0xFF94A3B8), fontSize = 12.sp)
                Spacer(Modifier.height(6.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    CLAIM_STATUS_OPTIONS.forEach { status ->
                        val isActive = claim?.status == status
                        OutlinedButton(
                            onClick = { if (!isActive) onClaim(status) },
                            colors = ButtonDefaults.outlinedButtonColors(
                                containerColor = if (isActive) statusColor(status).copy(alpha = 0.2f) else Color.Transparent,
                                contentColor = if (isActive) statusColor(status) else Color(0xFF94A3B8),
                            ),
                            border = androidx.compose.foundation.BorderStroke(
                                1.dp, if (isActive) statusColor(status) else Color(0xFF334155)
                            ),
                            modifier = Modifier.height(32.dp),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                        ) {
                            Text(statusLabel(status), fontSize = 12.sp)
                        }
                    }
                }
                if (claim != null) {
                    Spacer(Modifier.height(8.dp))
                    TextButton(
                        onClick = { onRelease(claim.id) },
                        colors = ButtonDefaults.textButtonColors(contentColor = Color(0xFFEF4444)),
                    ) { Text("Release claim", fontSize = 12.sp) }
                }
                row.note?.let { note ->
                    Spacer(Modifier.height(4.dp))
                    Text("Note: $note", color = Color(0xFF64748B), fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun AccountabilityRowCard(
    row: RosterIncidentRow,
    isPresent: Boolean,
    isMissing: Boolean,
    onMarkPresent: () -> Unit,
    onMarkMissing: () -> Unit,
    onClear: () -> Unit,
) {
    val presentColor = Color(0xFF4ADE80)
    val missingColor = Color(0xFFEF4444)
    val neutralColor = Color(0xFF94A3B8)
    val borderColor = Color(0xFF334155)

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E293B)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(row.fullName, color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                Text("Grade ${row.gradeLevel}", color = Color(0xFF94A3B8), fontSize = 12.sp)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { if (isPresent) onClear() else onMarkPresent() },
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = if (isPresent) presentColor.copy(alpha = 0.18f) else Color.Transparent,
                        contentColor = if (isPresent) presentColor else neutralColor,
                    ),
                    border = BorderStroke(1.dp, if (isPresent) presentColor else borderColor),
                    modifier = Modifier.height(36.dp),
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                ) {
                    Text("✓ Present", fontSize = 12.sp, fontWeight = FontWeight.Medium)
                }
                OutlinedButton(
                    onClick = { if (isMissing) onClear() else onMarkMissing() },
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = if (isMissing) missingColor.copy(alpha = 0.18f) else Color.Transparent,
                        contentColor = if (isMissing) missingColor else neutralColor,
                    ),
                    border = BorderStroke(1.dp, if (isMissing) missingColor else borderColor),
                    modifier = Modifier.height(36.dp),
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                ) {
                    Text("✗ Missing", fontSize = 12.sp, fontWeight = FontWeight.Medium)
                }
            }
        }
    }
}

@Composable
private fun FlowRow(
    modifier: Modifier = Modifier,
    horizontalArrangement: Arrangement.Horizontal = Arrangement.Start,
    verticalArrangement: Arrangement.Vertical = Arrangement.Top,
    content: @Composable () -> Unit,
) {
    androidx.compose.foundation.layout.FlowRow(
        modifier = modifier,
        horizontalArrangement = horizontalArrangement,
        verticalArrangement = verticalArrangement,
    ) { content() }
}

@Composable
private fun AddIncidentStudentDialog(
    onDismiss: () -> Unit,
    onAdd: (firstName: String, lastName: String, gradeLevel: String, note: String?) -> Unit,
) {
    var firstName by remember { mutableStateOf("") }
    var lastName by remember { mutableStateOf("") }
    var gradeLevel by remember { mutableStateOf("K") }
    var note by remember { mutableStateOf("") }
    var gradeExpanded by remember { mutableStateOf(false) }

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = Color(0xFF1E293B),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Add Student to Incident", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                OutlinedTextField(
                    value = firstName,
                    onValueChange = { firstName = it },
                    label = { Text("First name") },
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
                    singleLine = true,
                )
                OutlinedTextField(
                    value = lastName,
                    onValueChange = { lastName = it },
                    label = { Text("Last name") },
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
                    singleLine = true,
                )
                ExposedDropdownMenuBox(
                    expanded = gradeExpanded,
                    onExpandedChange = { gradeExpanded = it },
                ) {
                    OutlinedTextField(
                        value = gradeLevel,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("Grade") },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = gradeExpanded) },
                        modifier = Modifier.fillMaxWidth().menuAnchor(),
                    )
                    ExposedDropdownMenu(
                        expanded = gradeExpanded,
                        onDismissRequest = { gradeExpanded = false },
                    ) {
                        GRADE_OPTIONS.forEach { g ->
                            DropdownMenuItem(
                                text = { Text(g) },
                                onClick = { gradeLevel = g; gradeExpanded = false },
                            )
                        }
                    }
                }
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("Note (optional)") },
                    modifier = Modifier.fillMaxWidth(),
                    maxLines = 2,
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                    TextButton(onClick = onDismiss) { Text("Cancel", color = Color(0xFF94A3B8)) }
                    Button(
                        onClick = {
                            if (firstName.isNotBlank() && lastName.isNotBlank())
                                onAdd(firstName.trim(), lastName.trim(), gradeLevel, note.trim().ifBlank { null })
                        },
                        enabled = firstName.isNotBlank() && lastName.isNotBlank(),
                    ) { Text("Add") }
                }
            }
        }
    }
}

// MARK: - Master Roster Screen (non-alarm, offline-capable)

private val GRADE_ORDER = listOf("PreK", "K") + (1..12).map { it.toString() } + listOf("Other")

@Composable
fun MasterRosterScreen(
    students: List<MasterStudent>,
    isLoading: Boolean,
    lastSyncMs: Long,
    onRefresh: () -> Unit,
    onDismiss: () -> Unit,
) {
    var search by remember { mutableStateOf("") }
    var gradeFilter by remember { mutableStateOf("") }

    val availableGrades = remember(students) {
        val grades = students.map { it.gradeLevel }.toSet()
        GRADE_ORDER.filter { it in grades }
    }

    val filtered = remember(students, search, gradeFilter) {
        students.filter {
            val matchSearch = search.isBlank() || it.fullName.contains(search, ignoreCase = true)
            val matchGrade = gradeFilter.isEmpty() || it.gradeLevel == gradeFilter
            matchSearch && matchGrade
        }
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF0D1220))
            .padding(bottom = 16.dp),
    ) {
        // Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("Student Roster", color = Color(0xFFE8EEFF), fontWeight = FontWeight.Bold, fontSize = 18.sp)
                if (lastSyncMs > 0L) {
                    val syncAgo = (System.currentTimeMillis() - lastSyncMs) / 60_000
                    val label = when {
                        syncAgo < 1 -> "just now"
                        syncAgo < 60 -> "${syncAgo}m ago"
                        syncAgo < 1440 -> "${syncAgo / 60}h ago"
                        else -> "${syncAgo / 1440}d ago"
                    }
                    Text("Synced $label", color = Color(0xFF8FA4C0), fontSize = 12.sp)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (isLoading) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp), color = Color(0xFF4D88FF), strokeWidth = 2.dp)
                } else {
                    IconButton(onClick = onRefresh, modifier = Modifier.size(36.dp)) {
                        Icon(Icons.Default.Refresh, contentDescription = "Sync", tint = Color(0xFF4D88FF))
                    }
                }
                IconButton(onClick = onDismiss, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Default.Close, contentDescription = "Close", tint = Color(0xFF8FA4C0))
                }
            }
        }

        // Search
        OutlinedTextField(
            value = search,
            onValueChange = { search = it },
            placeholder = { Text("Search students…", color = Color(0xFF8FA4C0)) },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null, tint = Color(0xFF8FA4C0)) },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
            singleLine = true,
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Color(0xFF4D88FF),
                unfocusedBorderColor = Color(0xFF1E2D45),
                focusedTextColor = Color(0xFFE8EEFF),
                unfocusedTextColor = Color(0xFFE8EEFF),
                cursorColor = Color(0xFF4D88FF),
            ),
            shape = RoundedCornerShape(10.dp),
        )

        // Grade filter chips
        if (availableGrades.isNotEmpty()) {
            LazyRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                item { GradeChip(label = "All", selected = gradeFilter.isEmpty()) { gradeFilter = "" } }
                items(availableGrades) { g ->
                    GradeChip(label = "Gr $g", selected = gradeFilter == g) { gradeFilter = g }
                }
            }
        }

        // Content
        when {
            students.isEmpty() && !isLoading -> {
                Box(Modifier.fillMaxWidth().padding(vertical = 32.dp), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("No roster downloaded", color = Color(0xFFE8EEFF), fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                        Text("Tap Sync to download from your school's server.", color = Color(0xFF8FA4C0), fontSize = 13.sp)
                        Button(onClick = onRefresh, enabled = !isLoading) {
                            Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("Download Roster")
                        }
                    }
                }
            }
            filtered.isEmpty() -> {
                Box(Modifier.fillMaxWidth().padding(vertical = 24.dp), contentAlignment = Alignment.Center) {
                    Text("No results", color = Color(0xFF8FA4C0), fontSize = 14.sp)
                }
            }
            else -> {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(filtered, key = { it.id }) { student ->
                        MasterStudentRow(student)
                    }
                }
            }
        }
    }
}

@Composable
private fun GradeChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(50),
        color = if (selected) Color(0xFF1B3B72) else Color(0xFF1A2640),
        border = if (selected) androidx.compose.foundation.BorderStroke(1.dp, Color(0xFF4D88FF)) else null,
    ) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp),
            color = if (selected) Color(0xFF4D88FF) else Color(0xFF8FA4C0),
            fontSize = 12.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}

@Composable
private fun MasterStudentRow(student: MasterStudent) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = Color(0xFF1A2640),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(student.fullName, color = Color(0xFFE8EEFF), fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Grade ${student.gradeLevel}", color = Color(0xFF8FA4C0), fontSize = 12.sp)
                    if (!student.studentRef.isNullOrBlank()) {
                        Text("· ${student.studentRef}", color = Color(0xFF566880), fontSize = 12.sp)
                    }
                }
            }
        }
    }
}
