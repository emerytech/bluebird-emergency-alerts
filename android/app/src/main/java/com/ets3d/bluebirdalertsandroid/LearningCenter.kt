@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.ets3d.bluebirdalertsandroid

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.launch

// ─────────────────────────────────────────────────────────────────────────────
// Design shortcuts (matches BlueBirdTheme.kt palette)
// ─────────────────────────────────────────────────────────────────────────────
private val LCBlue    = Color(0xFF1B5FE4)
private val LCGreen   = Color(0xFF166534)
private val LCRed     = Color(0xFFDC2626)
private val LCAmber   = Color(0xFFB45309)
private val LCInfo    = Color(0xFF1D4ED8)
private val LCPurple  = Color(0xFF7C3AED)

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Data Model
// ─────────────────────────────────────────────────────────────────────────────

enum class LCGuideID(
    val guideKey: String,
    val title: String,
    val introDescription: String,
    val icon: ImageVector,
    val color: Color,
) {
    INITIATE_EMERGENCY(
        "initiate_emergency",
        "Initiate an Emergency",
        "Learn how to initiate an emergency alert and manage an active incident safely.",
        Icons.Filled.Warning,
        LCRed,
    ),
    VIEW_MESSAGES(
        "view_messages",
        "View Messages",
        "Learn how to send and receive messages during and outside of emergencies.",
        Icons.Filled.Email,
        LCBlue,
    ),
    TEAM_ASSIST(
        "team_assist",
        "Team Assist",
        "Learn how to request team assistance for non-emergency situations.",
        Icons.Filled.People,
        LCAmber,
    ),
    ACCOUNT_FOR_YOURSELF(
        "account_for_yourself",
        "Account for Yourself",
        "Learn how to mark yourself safe during an emergency.",
        Icons.Filled.CheckCircle,
        LCGreen,
    ),
    ACCOUNT_FOR_STUDENTS(
        "account_for_students",
        "Account for Students",
        "Learn how to account for students in your care during an emergency.",
        Icons.Filled.List,
        LCInfo,
    ),
    REUNIFICATION(
        "reunification",
        "Reunification",
        "Learn how to manage the reunification process after an emergency.",
        Icons.Filled.People,
        LCBlue,
    ),
}

sealed class LCStepKind {
    object Info : LCStepKind()
    data class IconGrid(val items: List<Triple<ImageVector, String, Color>>) : LCStepKind()
    data class SlideToConfirm(val label: String, val icon: ImageVector) : LCStepKind()
    data class HoldButton(val emergencyType: String, val color: Color) : LCStepKind()
    object AlarmTakeover : LCStepKind()
    object AcknowledgeButton : LCStepKind()
    data class MockNotification(val appName: String, val title: String, val body: String) : LCStepKind()
    data class VisualCopy(val placeholder: String) : LCStepKind()
}

data class LCStep(
    val title: String,
    val description: String,
    val kind: LCStepKind,
)

data class LCGuide(
    val id: LCGuideID,
    val steps: List<LCStep>,
)

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guide Definitions
// ─────────────────────────────────────────────────────────────────────────────

val LC_ALL_GUIDES: List<LCGuide> = listOf(

    // ── GUIDE 1 — FULLY IMPLEMENTED ──────────────────────────────────────────
    LCGuide(id = LCGuideID.INITIATE_EMERGENCY, steps = listOf(
        LCStep(
            title = "Emergency Types",
            description = "The main screen shows emergency types for your school — Lockdown, Evacuation, Shelter, Secure, or Hold. Each represents a specific protocol.",
            kind = LCStepKind.IconGrid(listOf(
                Triple(Icons.Filled.Lock,         "LOCKDOWN",  LCRed),
                Triple(Icons.Filled.DirectionsRun,"EVACUATE",  LCGreen),
                Triple(Icons.Filled.Home,         "SHELTER",   LCAmber),
                Triple(Icons.Filled.PanTool,      "SECURE",    LCInfo),
                Triple(Icons.Filled.Pause,        "HOLD",      LCPurple),
            )),
        ),
        LCStep(
            title = "Hold to Activate",
            description = "Hold the circular button for your school's configured duration. The ring fills as you hold. All staff receive an immediate alert the moment you release.",
            kind = LCStepKind.HoldButton("LOCKDOWN", LCRed),
        ),
        LCStep(
            title = "Active Alert Screen",
            description = "When an emergency activates, every staff device shows a full-screen takeover. The acknowledgement counter updates in real time as staff tap the button below.",
            kind = LCStepKind.AlarmTakeover,
        ),
        LCStep(
            title = "Acknowledge the Alert",
            description = "Tap Acknowledge to mark yourself safe. The counter above updates instantly. Administrators see who has and hasn't responded in real time.",
            kind = LCStepKind.AcknowledgeButton,
        ),
        LCStep(
            title = "Push Notification",
            description = "Every staff member receives a push notification the instant an emergency activates. The app opens automatically and locks to the alert screen until the emergency is cleared.",
            kind = LCStepKind.MockNotification(
                appName = "BlueBird Alerts",
                title = "🚨 LOCKDOWN — Lincoln Elementary",
                body = "Emergency alert activated. Open the app and follow procedures immediately.",
            ),
        ),
        LCStep(
            title = "You're Ready",
            description = "You now know how to initiate an emergency and what staff will experience. In a real emergency: stay calm, hold the correct button, and follow your school's protocols.",
            kind = LCStepKind.Info,
        ),
    )),

    // ── GUIDES 2–6 — SCAFFOLDED ──────────────────────────────────────────────
    LCGuide(id = LCGuideID.VIEW_MESSAGES, steps = listOf(
        LCStep(
            title = "Messages Overview",
            description = "BlueBird Alerts includes a secure messaging system for communicating with staff before, during, and after emergencies. More training steps coming soon.",
            kind = LCStepKind.Info,
        ),
    )),
    LCGuide(id = LCGuideID.TEAM_ASSIST, steps = listOf(
        LCStep(
            title = "Team Assist Overview",
            description = "Team Assist lets you silently request help from a colleague for non-emergency situations. More steps coming soon.",
            kind = LCStepKind.Info,
        ),
    )),
    LCGuide(id = LCGuideID.ACCOUNT_FOR_YOURSELF, steps = listOf(
        LCStep(
            title = "Account for Yourself",
            description = "During an active emergency, tap Acknowledge on the alert screen to mark yourself safe. More steps coming soon.",
            kind = LCStepKind.Info,
        ),
    )),
    LCGuide(id = LCGuideID.ACCOUNT_FOR_STUDENTS, steps = listOf(
        LCStep(
            title = "Student Accountability",
            description = "Administrators can track student status during an emergency using built-in roster tools. More steps coming soon.",
            kind = LCStepKind.Info,
        ),
    )),
    LCGuide(id = LCGuideID.REUNIFICATION, steps = listOf(
        LCStep(
            title = "Reunification Overview",
            description = "After an emergency, BlueBird Alerts supports the reunification process with tracking and communication tools. More steps coming soon.",
            kind = LCStepKind.Info,
        ),
    )),
)

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Persistence
// ─────────────────────────────────────────────────────────────────────────────

private const val LC_PREFS = "lc_training_v1"
private const val KEY_COMPLETED = "completed_guides"
private const val KEY_LAST_STEP = "last_step_"

class LearningCenterStore(private val prefs: SharedPreferences) {

    fun isComplete(id: LCGuideID): Boolean =
        prefs.getStringSet(KEY_COMPLETED, emptySet())?.contains(id.guideKey) == true

    fun markComplete(id: LCGuideID) {
        val set = prefs.getStringSet(KEY_COMPLETED, emptySet())?.toMutableSet() ?: mutableSetOf()
        set.add(id.guideKey)
        prefs.edit().putStringSet(KEY_COMPLETED, set).apply()
    }

    fun lastStep(id: LCGuideID): Int = prefs.getInt(KEY_LAST_STEP + id.guideKey, 0)

    fun saveProgress(id: LCGuideID, step: Int) {
        prefs.edit().putInt(KEY_LAST_STEP + id.guideKey, step).apply()
    }

    fun reset(id: LCGuideID) {
        val set = prefs.getStringSet(KEY_COMPLETED, emptySet())?.toMutableSet() ?: mutableSetOf()
        set.remove(id.guideKey)
        prefs.edit()
            .putStringSet(KEY_COMPLETED, set)
            .remove(KEY_LAST_STEP + id.guideKey)
            .apply()
    }

    fun resetAll() {
        prefs.edit().clear().apply()
    }

    val completedCount: Int
        get() = prefs.getStringSet(KEY_COMPLETED, emptySet())?.size ?: 0

    val completionFraction: Float
        get() = if (LC_ALL_GUIDES.isEmpty()) 0f else completedCount.toFloat() / LC_ALL_GUIDES.size
}

fun lcStore(ctx: Context) = LearningCenterStore(ctx.getSharedPreferences(LC_PREFS, Context.MODE_PRIVATE))

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Analytics
// ─────────────────────────────────────────────────────────────────────────────

object LCAnalytics {
    fun track(event: String, guideID: String? = null, step: Int? = null) {
        val info = buildString {
            append("[LCAnalytics] event=$event")
            if (guideID != null) append(" guide=$guideID")
            if (step != null) append(" step=$step")
        }
        android.util.Log.d("LCAnalytics", info)
        // TODO: POST to /{tenant}/api/training/event when network available
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Learning Center Menu
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun LearningCenterScreen(
    onDismiss: () -> Unit,
    isAlarmActive: Boolean = false,
) {
    val ctx = LocalContext.current
    val store = remember { lcStore(ctx) }
    var selectedGuide by remember { mutableStateOf<LCGuide?>(null) }
    var completedCount by remember { mutableIntStateOf(store.completedCount) }

    LaunchedEffect(isAlarmActive) { if (isAlarmActive) onDismiss() }

    val guide = selectedGuide
    if (guide != null) {
        LCGuideIntroScreen(
            guide = guide,
            store = store,
            isAlarmActive = isAlarmActive,
            onBack = { selectedGuide = null; completedCount = store.completedCount },
        )
        return
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = { Text("Learning Center", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Filled.Close, contentDescription = "Close")
                    }
                },
                colors = TopAppBarDefaults.centerAlignedTopAppBarColors(
                    containerColor = Color(0xFF0D1424),
                    titleContentColor = Color(0xFFE8EEFF),
                    navigationIconContentColor = LCBlue,
                ),
            )
        },
        containerColor = Color(0xFF0D1424),
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Header
            item {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(72.dp)
                            .clip(CircleShape)
                            .background(LCBlue.copy(alpha = 0.15f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Filled.School, contentDescription = null, tint = LCBlue, modifier = Modifier.size(36.dp))
                    }
                    Text("Learning Center", color = Color(0xFFE8EEFF), fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
                    Text(
                        "Become more familiar with BlueBird Alerts",
                        color = Color(0xFF8899BB),
                        fontSize = 14.sp,
                        textAlign = TextAlign.Center,
                    )
                }
            }

            // Progress
            item {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("Your Progress", color = Color(0xFF8899BB), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        Text(
                            "$completedCount of ${LC_ALL_GUIDES.size} completed",
                            color = Color(0xFF8899BB),
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                    LinearProgressIndicator(
                        progress = { store.completionFraction },
                        modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)),
                        color = LCBlue,
                        trackColor = Color(0xFF1E2D4A),
                    )
                }
            }

            // Guide rows
            items(LC_ALL_GUIDES) { guide ->
                LCGuideRow(guide = guide, store = store, onClick = { selectedGuide = guide })
            }
        }
    }
}

@Composable
private fun LCGuideRow(guide: LCGuide, store: LearningCenterStore, onClick: () -> Unit) {
    val isComplete = store.isComplete(guide.id)
    val lastStep   = store.lastStep(guide.id)
    val hasStarted = lastStep > 0 && !isComplete

    Surface(
        onClick = onClick,
        color = Color(0xFF192132),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Box(
                modifier = Modifier.size(50.dp).clip(CircleShape).background(guide.id.color.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(guide.id.icon, contentDescription = null, tint = guide.id.color, modifier = Modifier.size(24.dp))
            }

            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(guide.id.title, color = Color(0xFFE8EEFF), fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                Text(
                    guide.id.introDescription,
                    color = Color(0xFF8899BB),
                    fontSize = 12.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            when {
                isComplete -> Icon(Icons.Filled.CheckCircle, contentDescription = "Done", tint = LCGreen, modifier = Modifier.size(24.dp))
                hasStarted -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Filled.PlayCircle, contentDescription = "Resume", tint = LCBlue, modifier = Modifier.size(22.dp))
                    Text("Step ${lastStep + 1}", color = Color(0xFF8899BB), fontSize = 10.sp)
                }
                else -> Icon(Icons.Filled.ChevronRight, contentDescription = null, tint = Color(0xFF8899BB))
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guide Intro
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun LCGuideIntroScreen(
    guide: LCGuide,
    store: LearningCenterStore,
    isAlarmActive: Boolean,
    onBack: () -> Unit,
) {
    var showSteps by remember { mutableStateOf(false) }
    var startingStep by remember { mutableIntStateOf(0) }
    val isComplete = store.isComplete(guide.id)
    val lastStep   = store.lastStep(guide.id)
    val hasStarted = lastStep > 0 && !isComplete

    LaunchedEffect(isAlarmActive) { if (isAlarmActive) onBack() }

    if (showSteps) {
        LCGuideStepScreen(
            guide = guide,
            store = store,
            startStep = startingStep,
            isAlarmActive = isAlarmActive,
            onDone = { showSteps = false; onBack() },
        )
        return
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {},
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.centerAlignedTopAppBarColors(
                    containerColor = Color(0xFF0D1424),
                    navigationIconContentColor = LCBlue,
                ),
            )
        },
        containerColor = Color(0xFF0D1424),
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.weight(1f))

            Box(
                modifier = Modifier.size(100.dp).clip(CircleShape).background(guide.id.color.copy(alpha = 0.12f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(guide.id.icon, contentDescription = null, tint = guide.id.color, modifier = Modifier.size(48.dp))
            }

            Spacer(Modifier.height(22.dp))

            Text(
                guide.id.title,
                color = Color(0xFFE8EEFF),
                fontSize = 24.sp,
                fontWeight = FontWeight.ExtraBold,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                guide.id.introDescription,
                color = Color(0xFF8899BB),
                fontSize = 15.sp,
                textAlign = TextAlign.Center,
            )

            if (isComplete) {
                Spacer(Modifier.height(14.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = LCGreen, modifier = Modifier.size(18.dp))
                    Text("Completed", color = LCGreen, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                }
            }

            Spacer(Modifier.height(10.dp))
            Text(
                "${guide.steps.size} steps · ~${guide.steps.size * 30}s",
                color = Color(0xFF8899BB),
                fontSize = 12.sp,
            )

            Spacer(Modifier.weight(1f))

            Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(
                    onClick = {
                        startingStep = if (hasStarted) lastStep else 0
                        LCAnalytics.track("guide_started", guide.id.guideKey)
                        showSteps = true
                    },
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = guide.id.color),
                ) {
                    Text(
                        when {
                            hasStarted  -> "Resume"
                            isComplete  -> "Retake"
                            else        -> "Start"
                        },
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 16.sp,
                    )
                }

                if (hasStarted || isComplete) {
                    TextButton(
                        onClick = { store.reset(guide.id); startingStep = 0; showSteps = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Start Over", color = Color(0xFF8899BB), fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            Spacer(Modifier.height(40.dp))
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guide Step Screen
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun LCGuideStepScreen(
    guide: LCGuide,
    store: LearningCenterStore,
    startStep: Int,
    isAlarmActive: Boolean,
    onDone: () -> Unit,
) {
    var currentStep by remember { mutableIntStateOf(startStep) }
    var interactionDone by remember { mutableStateOf(false) }
    // Simulation state — shared across hold/takeover/ack steps within this guide run
    var simActivated   by remember { mutableStateOf(false) }
    var simAcknowledged by remember { mutableStateOf(false) }
    var simAckCount    by remember { mutableIntStateOf(2) }
    val simTotalUsers  = 14
    val step = guide.steps[currentStep]
    val isFirst = currentStep == 0
    val isLast  = currentStep == guide.steps.size - 1
    val needsInteraction = step.kind is LCStepKind.SlideToConfirm
        || step.kind is LCStepKind.HoldButton
        || step.kind is LCStepKind.AcknowledgeButton

    LaunchedEffect(isAlarmActive) { if (isAlarmActive) onDone() }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Text(
                        "Step ${currentStep + 1} of ${guide.steps.size}",
                        color = Color(0xFF8899BB),
                        fontSize = 13.sp,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onDone) {
                        Icon(Icons.Filled.Close, contentDescription = "Exit")
                    }
                },
                colors = TopAppBarDefaults.centerAlignedTopAppBarColors(
                    containerColor = Color(0xFF0D1424),
                    navigationIconContentColor = LCBlue,
                ),
            )
        },
        containerColor = Color(0xFF0D1424),
        bottomBar = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color(0xFF0D1424))
                    .padding(horizontal = 20.dp, vertical = 16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                // Page dots
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    guide.steps.forEachIndexed { i, _ ->
                        val w = if (i == currentStep) 20.dp else 8.dp
                        val c = if (i == currentStep) LCBlue else Color(0xFF1E2D4A)
                        Box(
                            modifier = Modifier
                                .padding(horizontal = 3.dp)
                                .height(8.dp)
                                .width(w)
                                .clip(RoundedCornerShape(4.dp))
                                .background(c)
                        )
                    }
                }

                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    // Back
                    OutlinedButton(
                        onClick = {
                            currentStep--
                            interactionDone = false
                            simActivated = false; simAcknowledged = false; simAckCount = 2
                        },
                        enabled = !isFirst,
                        modifier = Modifier.weight(1f).height(50.dp),
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, Color(0xFF1E2D4A)),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFF8899BB)),
                    ) {
                        Icon(Icons.Filled.ChevronLeft, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Back", fontWeight = FontWeight.SemiBold)
                    }

                    // Next / Finish
                    Button(
                        onClick = {
                            if (isLast) {
                                store.markComplete(guide.id)
                                store.saveProgress(guide.id, 0)
                                LCAnalytics.track("guide_completed", guide.id.guideKey, currentStep)
                                onDone()
                            } else {
                                LCAnalytics.track("step_completed", guide.id.guideKey, currentStep)
                                store.saveProgress(guide.id, currentStep + 1)
                                currentStep++
                                interactionDone = false
                                simActivated = false; simAcknowledged = false; simAckCount = 2
                            }
                        },
                        enabled = !(needsInteraction && !interactionDone),
                        modifier = Modifier.weight(1f).height(50.dp),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (needsInteraction && !interactionDone) LCBlue.copy(alpha = 0.4f) else LCBlue,
                        ),
                    ) {
                        Text(if (isLast) "Finish" else "Next", fontWeight = FontWeight.SemiBold)
                        Spacer(Modifier.width(4.dp))
                        Icon(
                            if (isLast) Icons.Filled.Check else Icons.Filled.ChevronRight,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(24.dp))

            Box(modifier = Modifier.padding(horizontal = 20.dp)) {
                LCStepContent(
                    step = step,
                    guideColor = guide.id.color,
                    simActivated = simActivated,
                    simAcknowledged = simAcknowledged,
                    simAckCount = simAckCount,
                    simTotalUsers = simTotalUsers,
                    onInteractionComplete = { interactionDone = true },
                    onSimActivate = { simActivated = true },
                    onSimAcknowledge = {
                        simAcknowledged = true
                        simAckCount = (simAckCount + 1).coerceAtMost(simTotalUsers)
                    },
                    onSimAckCountChange = { simAckCount = it },
                )
            }

            Spacer(Modifier.height(24.dp))

            Column(
                modifier = Modifier.padding(horizontal = 24.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    step.title,
                    color = Color(0xFFE8EEFF),
                    fontSize = 20.sp,
                    fontWeight = FontWeight.ExtraBold,
                    textAlign = TextAlign.Center,
                )
                Text(
                    step.description,
                    color = Color(0xFF8899BB),
                    fontSize = 14.sp,
                    textAlign = TextAlign.Center,
                )
            }

            Spacer(Modifier.height(32.dp))
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Step Renderers
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun LCStepContent(
    step: LCStep,
    guideColor: Color,
    simActivated: Boolean,
    simAcknowledged: Boolean,
    simAckCount: Int,
    simTotalUsers: Int,
    onInteractionComplete: () -> Unit,
    onSimActivate: () -> Unit,
    onSimAcknowledge: () -> Unit,
    onSimAckCountChange: (Int) -> Unit,
) {
    when (val kind = step.kind) {
        is LCStepKind.Info             -> LCInfoStep(guideColor)
        is LCStepKind.IconGrid         -> LCIconGridStep(kind.items)
        is LCStepKind.SlideToConfirm   -> LCSlideToConfirmStep(kind.label, kind.icon, onInteractionComplete)
        is LCStepKind.HoldButton       -> LCHoldButtonStep(
            emergencyType = kind.emergencyType,
            color = kind.color,
            onComplete = { onSimActivate(); onInteractionComplete() },
        )
        is LCStepKind.AlarmTakeover    -> LCAlarmTakeoverStep(
            ackCount = simAckCount,
            totalUsers = simTotalUsers,
            onAckCountChange = onSimAckCountChange,
        )
        is LCStepKind.AcknowledgeButton -> LCAcknowledgeButtonStep(
            acknowledged = simAcknowledged,
            ackCount = simAckCount,
            totalUsers = simTotalUsers,
            onAcknowledge = { onSimAcknowledge(); onInteractionComplete() },
        )
        is LCStepKind.MockNotification -> LCMockNotificationStep(kind.appName, kind.title, kind.body)
        is LCStepKind.VisualCopy       -> LCVisualCopyStep(kind.placeholder)
    }
}

@Composable
private fun LCInfoStep(color: Color) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(200.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(color.copy(alpha = 0.08f))
            .border(1.dp, color.copy(alpha = 0.2f), RoundedCornerShape(16.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Filled.School, contentDescription = null, tint = color.copy(alpha = 0.5f), modifier = Modifier.size(72.dp))
    }
}

@Composable
private fun LCIconGridStep(items: List<Triple<ImageVector, String, Color>>) {
    val rowCount = (items.size + 2) / 3
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        for (row in 0 until rowCount) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                for (col in 0..2) {
                    val idx = row * 3 + col
                    if (idx < items.size) {
                        val (icon, label, color) = items[idx]
                        Surface(
                            color = Color(0xFF192132),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.weight(1f),
                        ) {
                            Column(
                                modifier = Modifier.padding(vertical = 14.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Box(
                                    modifier = Modifier.size(52.dp).clip(CircleShape).background(color.copy(alpha = 0.15f)),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(24.dp))
                                }
                                Text(label, color = Color(0xFFE8EEFF), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    } else {
                        Spacer(Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun LCSlideToConfirmStep(label: String, icon: ImageVector, onComplete: () -> Unit) {
    var dragFraction by remember { mutableFloatStateOf(0f) }
    var completed by remember { mutableStateOf(false) }
    val thumbSize = 56.dp

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        // Safety badge
        Row(
            modifier = Modifier
                .align(Alignment.CenterHorizontally)
                .clip(RoundedCornerShape(50))
                .background(LCAmber.copy(alpha = 0.12f))
                .padding(horizontal = 14.dp, vertical = 7.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Shield, contentDescription = null, tint = LCAmber, modifier = Modifier.size(14.dp))
            Text("SIMULATION — no real alert sent", color = LCAmber, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }

        BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
            val totalWidth = maxWidth
            val thumbPx   = with(androidx.compose.ui.platform.LocalDensity.current) { thumbSize.toPx() }
            val padPx     = with(androidx.compose.ui.platform.LocalDensity.current) { 4.dp.toPx() }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(68.dp)
                    .clip(RoundedCornerShape(34.dp))
                    .background(if (completed) LCGreen.copy(alpha = 0.12f) else LCRed.copy(alpha = 0.10f))
                    .border(
                        1.5.dp,
                        if (completed) LCGreen.copy(alpha = 0.4f) else LCRed.copy(alpha = 0.28f),
                        RoundedCornerShape(34.dp),
                    ),
                contentAlignment = Alignment.CenterStart,
            ) {
                // Fill
                Box(
                    modifier = Modifier
                        .fillMaxHeight()
                        .fillMaxWidth(fraction = dragFraction.coerceAtLeast(thumbSize / totalWidth))
                        .clip(RoundedCornerShape(34.dp))
                        .background(if (completed) LCGreen.copy(alpha = 0.22f) else LCRed.copy(alpha = 0.16f))
                )

                // Label
                Text(
                    if (completed) "Simulated ✓" else label,
                    color = if (completed) LCGreen else LCRed.copy(alpha = 0.7f),
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                )

                // Thumb
                Box(
                    modifier = Modifier
                        .padding(start = 4.dp)
                        .offset(x = totalWidth * dragFraction - if (dragFraction > 0f) thumbSize * dragFraction else 0.dp)
                        .size(thumbSize)
                        .clip(CircleShape)
                        .background(if (completed) LCGreen else LCRed)
                        .pointerInput(completed) {
                            if (completed) return@pointerInput
                            detectHorizontalDragGestures(
                                onDragEnd = { if (!completed) dragFraction = 0f },
                                onHorizontalDrag = { _, delta ->
                                    val maxPx = size.width.toFloat() - thumbPx - padPx
                                    val currentOffsetPx = dragFraction * (size.width - thumbPx - padPx * 2)
                                    val newOffsetPx = (currentOffsetPx + delta).coerceIn(0f, maxPx)
                                    dragFraction = newOffsetPx / maxPx
                                    if (dragFraction >= 0.98f && !completed) {
                                        completed = true
                                        dragFraction = 1f
                                        onComplete()
                                    }
                                },
                            )
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        if (completed) Icons.Filled.Check else icon,
                        contentDescription = null,
                        tint = Color.White,
                        modifier = Modifier.size(24.dp),
                    )
                }
            }
        }
    }
}

// TODO(LearningCenter): replace with real CircularEmergencyButton(tutorialMode = true)
@Composable
private fun LCHoldButtonStep(
    emergencyType: String,
    color: Color,
    onComplete: () -> Unit,
) {
    var holdProgress by remember { mutableFloatStateOf(0f) }
    var isHolding by remember { mutableStateOf(false) }
    var completed by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Safety badge
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(50))
                .background(LCAmber.copy(alpha = 0.12f))
                .padding(horizontal = 14.dp, vertical = 7.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Shield, contentDescription = null, tint = LCAmber, modifier = Modifier.size(14.dp))
            Text("SIMULATION — no real alert sent", color = LCAmber, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }

        Surface(
            color = Color(0xFF0D1424),
            shape = RoundedCornerShape(20.dp),
            border = BorderStroke(1.dp, color.copy(alpha = 0.25f)),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(contentAlignment = Alignment.Center, modifier = Modifier.size(130.dp)) {
                    val animProgress by animateFloatAsState(holdProgress, label = "ring")
                    Canvas(modifier = Modifier.fillMaxSize()) {
                        val stroke = androidx.compose.ui.graphics.drawscope.Stroke(
                            width = 10.dp.toPx(),
                            cap = androidx.compose.ui.graphics.StrokeCap.Round,
                        )
                        // Background ring
                        drawArc(
                            color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.24f),
                            startAngle = -90f, sweepAngle = 360f, useCenter = false, style = stroke,
                        )
                        // Progress ring
                        val ringColor = when {
                            animProgress < 0.55f -> androidx.compose.ui.graphics.Color.White
                            animProgress < 0.80f -> LCAmber
                            else -> LCRed
                        }
                        drawArc(
                            color = ringColor,
                            startAngle = -90f, sweepAngle = 360f * animProgress, useCenter = false, style = stroke,
                        )
                    }
                    // Inner circle
                    val scale by animateFloatAsState(
                        if (completed) 1.12f else if (isHolding) 0.97f + holdProgress * 0.11f else 1f,
                        label = "scale",
                    )
                    Box(
                        modifier = Modifier
                            .size(108.dp)
                            .graphicsLayer { scaleX = scale; scaleY = scale }
                            .clip(CircleShape)
                            .background(color),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Filled.Lock, contentDescription = null,
                            tint = androidx.compose.ui.graphics.Color.White,
                            modifier = Modifier.size(30.dp),
                        )
                    }
                }

                Text(
                    emergencyType,
                    color = color,
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 16.sp,
                )
                Text(
                    when {
                        completed -> "Activating…"
                        isHolding -> "Keep Holding…"
                        else -> "Hold to Activate"
                    },
                    color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.88f),
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text("~3s", color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.62f), fontSize = 11.sp)
            }
        }

        // Tap-and-hold simulation button (simpler than gesture on canvas)
        Button(
            onClick = {},
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp)
                .pointerInput(completed) {
                    if (completed) return@pointerInput
                    detectTapGestures(
                        onPress = {
                            isHolding = true
                            val startTime = System.currentTimeMillis()
                            val duration = 3000L
                            scope.launch {
                                while (isHolding && !completed) {
                                    val elapsed = System.currentTimeMillis() - startTime
                                    holdProgress = (elapsed / duration.toFloat()).coerceAtMost(1f)
                                    if (holdProgress >= 1f) {
                                        completed = true
                                        isHolding = false
                                        onComplete()
                                        break
                                    }
                                    kotlinx.coroutines.delay(50)
                                }
                            }
                            val released = tryAwaitRelease()
                            if (!completed) {
                                isHolding = false
                                holdProgress = 0f
                            }
                        },
                    )
                },
            enabled = !completed,
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (completed) LCGreen else color,
                disabledContainerColor = LCGreen,
            ),
        ) {
            Text(
                if (completed) "Simulated ✓" else "Hold Here to Simulate",
                fontWeight = FontWeight.Bold,
                color = androidx.compose.ui.graphics.Color.White,
            )
        }
    }
}

// TODO(LearningCenter): replace with real EmergencyAlarmTakeover(tutorialMode = true)
@Composable
private fun LCAlarmTakeoverStep(
    ackCount: Int,
    totalUsers: Int,
    onAckCountChange: (Int) -> Unit,
) {
    val ackPct = if (totalUsers > 0) ackCount.toFloat() / totalUsers else 0f
    val ackColor = when {
        ackPct < 0.40f -> LCRed
        ackPct < 0.75f -> LCAmber
        else -> LCGreen
    }
    val animPct by animateFloatAsState(ackPct, animationSpec = spring(dampingRatio = 0.75f), label = "ack")

    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(1200)
        onAckCountChange((ackCount + 1).coerceAtMost(totalUsers - 1))
        kotlinx.coroutines.delay(1200)
        onAckCountChange((ackCount + 2).coerceAtMost(totalUsers - 1))
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(
                Brush.verticalGradient(listOf(LCRed, Color(0xFF0A0F1A)))
            ),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // Safety badge
            Row(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(LCAmber.copy(alpha = 0.18f))
                    .padding(horizontal = 14.dp, vertical = 7.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Filled.Shield, contentDescription = null, tint = LCAmber, modifier = Modifier.size(13.dp))
                Text("SIMULATION — no real alert sent", color = LCAmber, fontSize = 10.sp, fontWeight = FontWeight.Bold)
            }

            // Icon
            Box(contentAlignment = Alignment.Center) {
                Box(
                    modifier = Modifier
                        .size(100.dp)
                        .clip(CircleShape)
                        .border(3.dp, Color.White.copy(alpha = 0.22f), CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Box(
                        modifier = Modifier.size(84.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.10f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Filled.Notifications, contentDescription = null,
                            tint = Color.White, modifier = Modifier.size(38.dp),
                        )
                    }
                }
            }

            // Title block
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("EMERGENCY ALERT", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Black, letterSpacing = 1.sp)
                Text("🔒 LOCKDOWN", color = Color.White.copy(alpha = 0.92f), fontSize = 16.sp, fontWeight = FontWeight.Bold)
                Text("Lincoln Elementary", color = Color.White.copy(alpha = 0.65f), fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }

            // Instructions card
            Text(
                "Follow school emergency procedures immediately.",
                color = Color.White.copy(alpha = 0.94f),
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(Color.White.copy(alpha = 0.13f))
                    .padding(horizontal = 14.dp, vertical = 10.dp),
            )

            // Ack progress
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("$ackCount / $totalUsers acknowledged", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Text("${(ackPct * 100).toInt()}%", color = ackColor, fontSize = 14.sp, fontWeight = FontWeight.Black)
                }
                Box(
                    modifier = Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp))
                        .background(Color.White.copy(alpha = 0.18f)),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(animPct)
                            .fillMaxHeight()
                            .clip(RoundedCornerShape(4.dp))
                            .background(ackColor),
                    )
                }
            }
        }
    }
}

@Composable
private fun LCAcknowledgeButtonStep(
    acknowledged: Boolean,
    ackCount: Int,
    totalUsers: Int,
    onAcknowledge: () -> Unit,
) {
    val ackPct = if (totalUsers > 0) ackCount.toFloat() / totalUsers else 0f
    val ackColor = when {
        ackPct < 0.40f -> LCRed
        ackPct < 0.75f -> LCAmber
        else -> LCGreen
    }
    val animPct by animateFloatAsState(ackPct, animationSpec = spring(dampingRatio = 0.75f), label = "ack")

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        // Progress card
        Surface(
            color = Color(0xFF192132),
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("$ackCount / $totalUsers acknowledged", color = Color(0xFFE8EEFF), fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Text("${(ackPct * 100).toInt()}%", color = ackColor, fontSize = 14.sp, fontWeight = FontWeight.Black)
                }
                Box(
                    modifier = Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp))
                        .background(Color(0xFF1E2D4A)),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(animPct)
                            .fillMaxHeight()
                            .clip(RoundedCornerShape(4.dp))
                            .background(ackColor),
                    )
                }
            }
        }

        // Acknowledge button — pixel copy of production
        Button(
            onClick = { if (!acknowledged) onAcknowledge() },
            enabled = !acknowledged,
            modifier = Modifier.fillMaxWidth().height(58.dp),
            shape = RoundedCornerShape(16.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (acknowledged) Color.White.copy(alpha = 0.20f) else LCGreen,
                disabledContainerColor = Color.White.copy(alpha = 0.20f),
                disabledContentColor = Color.White.copy(alpha = 0.70f),
            ),
        ) {
            if (acknowledged) {
                Icon(Icons.Filled.CheckCircle, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
            }
            Text(
                if (acknowledged) "Acknowledged" else "Acknowledge",
                fontSize = 17.sp,
                fontWeight = FontWeight.Black,
                color = if (acknowledged) Color.White.copy(alpha = 0.70f) else Color(0xFF052A1D),
            )
        }
    }
}

@Composable
private fun LCMockNotificationStep(appName: String, title: String, body: String) {
    Surface(
        color = Color(0xFF192132),
        shape = RoundedCornerShape(18.dp),
        shadowElevation = 8.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                modifier = Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)).background(LCRed),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Filled.Notifications, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
            }
            Column(verticalArrangement = Arrangement.spacedBy(3.dp), modifier = Modifier.weight(1f)) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(appName, color = Color(0xFF8899BB), fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                    Text("now", color = Color(0xFF8899BB), fontSize = 11.sp)
                }
                Text(title, color = Color(0xFFE8EEFF), fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text(body, color = Color(0xFF8899BB), fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun LCVisualCopyStep(placeholder: String) {
    // TODO(LearningCenter): replace with real EmergencyAlarmTakeover(tutorialMode = true)
    // when the component supports tutorialMode to disable all side effects and API calls.
    Surface(
        color = LCRed.copy(alpha = 0.07f),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().height(220.dp),
        border = BorderStroke(1.5.dp, LCRed.copy(alpha = 0.22f)),
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(Icons.Filled.Warning, contentDescription = null, tint = LCRed, modifier = Modifier.size(42.dp))
            Spacer(Modifier.height(10.dp))
            Text("🔒 LOCKDOWN", color = LCRed, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold)
            Text("Lincoln Elementary", color = Color(0xFFE8EEFF), fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
            Spacer(Modifier.height(12.dp))
            Row(
                horizontalArrangement = Arrangement.spacedBy(24.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("12 / 28", color = Color(0xFFE8EEFF), fontWeight = FontWeight.ExtraBold, fontSize = 18.sp)
                    Text("Acknowledged", color = Color(0xFF8899BB), fontSize = 11.sp)
                }
                Box(modifier = Modifier.width(1.dp).height(36.dp).background(Color(0xFF1E2D4A)))
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("ACTIVE", color = LCRed, fontWeight = FontWeight.ExtraBold, fontSize = 13.sp)
                    Text("Alert Status", color = Color(0xFF8899BB), fontSize = 11.sp)
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guided Walkthrough Overlay (contextual, first-launch)
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun GuidedWalkthroughOverlay(
    isPresented: Boolean,
    isAlarmActive: Boolean,
    onDismiss: () -> Unit,
) {
    if (!isPresented) return

    LaunchedEffect(isAlarmActive) { if (isAlarmActive) onDismiss() }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.55f)),
        contentAlignment = Alignment.BottomCenter,
    ) {
        Surface(
            color = Color(0xFF192132),
            shape = RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Filled.Star, contentDescription = null, tint = LCBlue, modifier = Modifier.size(18.dp))
                        Text("Quick Tour", color = Color(0xFFE8EEFF), fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Filled.Cancel, contentDescription = "Close", tint = Color(0xFF8899BB))
                    }
                }

                Text(
                    "Welcome to BlueBird Alerts! Tap any button to explore. For a full guided training experience, open Settings → Learning Center.",
                    color = Color(0xFFE8EEFF),
                    fontSize = 14.sp,
                )

                Button(
                    onClick = {
                        onDismiss()
                        LCAnalytics.track("walkthrough_completed")
                    },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = LCBlue),
                ) {
                    Text("Got It", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                }
            }
        }
    }
}
