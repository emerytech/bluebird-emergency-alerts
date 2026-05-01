package com.ets3d.bluebirdalertsandroid

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
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
    var showAddSheet by remember { mutableStateOf(false) }
    var pendingClaimRow by remember { mutableStateOf<RosterIncidentRow?>(null) }
    var pendingClaimStatus by remember { mutableStateOf("present_with_me") }
    var conflictMessage by remember { mutableStateOf<String?>(null) }
    var pendingTakeoverRow by remember { mutableStateOf<RosterIncidentRow?>(null) }

    LaunchedEffect(alertId) { vm.loadIncidentRoster(ctx, alertId) }

    val filtered = remember(roster, searchQuery) {
        roster?.students?.filter { row ->
            searchQuery.isBlank() ||
                row.fullName.contains(searchQuery, ignoreCase = true) ||
                row.gradeLevel.contains(searchQuery, ignoreCase = true)
        } ?: emptyList()
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
            )
        }
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

            // Search + Add button
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
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

            if (isLoading && roster == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
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
                                    if (searchQuery.isBlank()) "No students in roster." else "No results for "$searchQuery".",
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
