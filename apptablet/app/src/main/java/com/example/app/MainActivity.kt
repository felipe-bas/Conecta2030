package com.example.app

import android.content.Intent
import android.os.Bundle
import android.widget.ImageView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.example.app.model.CombinedNotification
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.InputStreamReader
import java.net.Socket
import android.util.Log
import java.io.IOException
import java.lang.StringBuilder
import com.example.app.databinding.ActivityMainBinding
import com.example.app.databinding.NotificationChildZoneBinding
import com.example.app.model.TimNotification
import com.example.app.model.UnifiedNotification
import com.example.app.rules.effects.NotificationUI
import com.example.app.rules.Orchestrator
import com.example.app.rules.Rule
import com.example.app.rules.effects.*
import com.example.app.rules.filters.*
import com.example.app.rules.context.NotificationContext
import com.example.app.ui.VisualAlertManager
import com.example.app.processing.combinedToAppNotification

enum class Direction { LEFT, RIGHT, TOP, BOTTOM, NULL}
enum class Objects {HUMAN, VEHICLE, MOTORCYCLE, BIKE, NULL}
enum class ZonaTipo { CRIANCA, CICLISTA }

class MainActivity : AppCompatActivity(), NotificationUI {

    private lateinit var orchestrator: Orchestrator

    private var tcpSocket: Socket? = null
    private var connectionJob: Job? = null
    private var shouldReconnect = true
    private val reconnectDelayMs = 15000L

    private lateinit var binding: ActivityMainBinding
    private lateinit var visualAlertManager: VisualAlertManager

    private val moshi  = Moshi.Builder()
        .addLast(KotlinJsonAdapterFactory())
        .build()

    private val unifiedNotificationAdapter = moshi.adapter(UnifiedNotification::class.java)

    private val serverIp = "192.168.0.53"
    private val serverPort = 8080

    private var psmPart: String? = null
    private var bsmPart: String? = null
    private var timPart: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        val childZoneBinding = NotificationChildZoneBinding.bind(binding.root.findViewById(R.id.child_zone_notification_layout))

        visualAlertManager = VisualAlertManager(this, binding, childZoneBinding)

        orchestrator = Orchestrator(this)
        setupRules()

        connectToServer()

        val settingsButton = findViewById<ImageView>(R.id.settingsIcon)
        settingsButton.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        orchestrator.start()
    }

    override fun onDestroy() {
        super.onDestroy()
        shouldReconnect = false
        connectionJob?.cancel()
        try {
            tcpSocket?.close()
        } catch (e: IOException) {
            Log.e("MainActivity", "Erro ao fechar o socket", e)
        }

        visualAlertManager.destroy()
    }

    private fun setupRules() {

        val PRIORITY_COMBINED = 40
        val PRIORITY_HIGH = 30
        val PRIORITY_MEDIUM = 20
        val PRIORITY_LOW = 10
        val PRIORITY_ZONE = 30

        // REGRA A: Colisão de ALTO Risco DENTRO de uma Zona Escolar
        val highRiskChildZoneRule = Rule(
            name = "High Risk Collision in Child Zone",
            priority = PRIORITY_COMBINED,
            rootFilter = AndFilter( // Usa AndFilter para combinar as duas condições
                RiskLevelFilter("high"),
                ZoneTypeFilter(ZonaTipo.CRIANCA)
            ),
            effects = listOf(
                StopPreviousAlertsEffect(),
                CombinedVisualEffect(ZonaTipo.CRIANCA),
                CombinedSoundEffect(ZonaTipo.CRIANCA)
            )
        )

        // REGRA B: Colisão de MÉDIO Risco DENTRO de uma Zona Escolar
        val mediumRiskChildZoneRule = Rule(
            name = "Medium Risk Collision in Child Zone",
            priority = PRIORITY_COMBINED,
            rootFilter = AndFilter(
                RiskLevelFilter("medium"),
                ZoneTypeFilter(ZonaTipo.CRIANCA)
            ),
            effects = listOf(
                StopPreviousAlertsEffect(),
                CombinedVisualEffect(ZonaTipo.CRIANCA),
                CombinedSoundEffect(ZonaTipo.CRIANCA)
            )
        )

        // REGRA C: Colisão de BAIXO Risco DENTRO de uma Zona Escolar
        val lowRiskChildZoneRule = Rule(
            name = "Low Risk Collision in Child Zone",
            priority = PRIORITY_COMBINED,
            rootFilter = AndFilter(
                RiskLevelFilter("low"),
                ZoneTypeFilter(ZonaTipo.CRIANCA)
            ),
            effects = listOf(
                StopPreviousAlertsEffect(),
                CombinedVisualEffect(ZonaTipo.CRIANCA),
                CombinedSoundEffect(ZonaTipo.CRIANCA)
            )
        )

        // --- REGRA 1: ALERTA DE COLISÃO DE ALTO RISCO ---
        val highRiskRule = Rule(
            name = "High Risk Collision Alert",
            priority = PRIORITY_HIGH,
            rootFilter = RiskLevelFilter("high"),
            effects = listOf(
                StopPreviousAlertsEffect(),
                VisualNotificationEffect(),
                SoundNotificationEffect()
            )
        )

        // --- REGRA 2: ALERTA DE COLISÃO DE MÉDIO RISCO ---
        val mediumRiskRule = Rule(
            name = "Medium Risk Collision Alert",
            priority = PRIORITY_MEDIUM,
            rootFilter = RiskLevelFilter("medium"),
            effects = listOf(
                StopPreviousAlertsEffect(),
                VisualNotificationEffect(),
                SoundNotificationEffect()
            )
        )

        // --- REGRA 3: ALERTA DE COLISÃO DE BAIXO RISCO ---
        val lowRiskRule = Rule(
            name = "Low Risk Collision Alert",
            priority = PRIORITY_LOW,
            rootFilter = RiskLevelFilter("low"),
            effects = listOf(
                StopPreviousAlertsEffect(),
                VisualNotificationEffect(),
                SoundNotificationEffect()
            )
        )

        // --- REGRA 4: ALERTA DE ZONA ESCOLAR (TIM) ---
        val childZoneRule = Rule(
            name = "Child Zone Alert",
            priority = PRIORITY_ZONE,
            rootFilter = ZoneTypeFilter(ZonaTipo.CRIANCA),
            effects = listOf(
                StopPreviousAlertsEffect(),
                ExpiringZoneAlertEffect(ZonaTipo.CRIANCA, durationMs = 10000L)
            )
        )

        // --- REGRA 5: ALERTA DE CICLISTA (TIM) ---
        val cyclistZoneRule = Rule(
            name = "Cyclist Zone Alert",
            priority = PRIORITY_ZONE,
            rootFilter = ZoneTypeFilter(ZonaTipo.CICLISTA),
            effects = listOf(
                StopPreviousAlertsEffect(),
                ExpiringZoneAlertEffect(ZonaTipo.CICLISTA, durationMs = 10000L)
            )
        )

        orchestrator.addRule(highRiskChildZoneRule)
        orchestrator.addRule(mediumRiskChildZoneRule)
        orchestrator.addRule(lowRiskChildZoneRule)
        orchestrator.addRule(highRiskRule)
        orchestrator.addRule(mediumRiskRule)
        orchestrator.addRule(lowRiskRule)
        orchestrator.addRule(childZoneRule)
        orchestrator.addRule(cyclistZoneRule)

    }

    private fun connectToServer() {
        connectionJob = lifecycleScope.launch(Dispatchers.IO) {
            while (shouldReconnect) {
                try {
                    Log.d("TCP", "Tentando conectar ao servidor unificado em $serverIp:$serverPort...")
                    tcpSocket = Socket(serverIp, serverPort)
                    withContext(Dispatchers.Main) { toast("Conectado ao servidor!") }
                    Log.d("TCP", "Conexão estabelecida.")

                    val reader = InputStreamReader(tcpSocket!!.getInputStream())
                    val buffer = CharArray(4096)
                    val jsonBuilder = StringBuilder()
                    var braceCount = 0
                    var isInsideJson = false
                    var charsRead: Int = 0

                    while (tcpSocket!!.isConnected && reader.read(buffer).also { charsRead = it } != -1) {
                        for (i in 0 until charsRead) {
                            val char = buffer[i]
                            if (!isInsideJson) {
                                if (char == '{') {
                                    isInsideJson = true
                                    braceCount = 1
                                    jsonBuilder.append(char)
                                }
                            } else {
                                jsonBuilder.append(char)
                                if (char == '{') {
                                    braceCount++
                                } else if (char == '}') {
                                    braceCount--
                                }

                                if (braceCount == 0) {
                                    val jsonChunk = jsonBuilder.toString()
                                    jsonBuilder.clear()
                                    isInsideJson = false

                                    processJsonChunk(jsonChunk)
                                }
                            }
                        }
                    }
                } catch (e: Exception) {
                    if (!shouldReconnect) break
                    Log.e("TCP", "Erro de conexão: ${e.message}")
                    withContext(Dispatchers.Main) {
                        toast("Erro de conexão. Reconectando em ${reconnectDelayMs / 1000}s…")
                    }
                    delay(reconnectDelayMs)
                } finally {
                    try {
                        tcpSocket?.close()
                    } catch (e: IOException) {
                        Log.e("TCP", "Erro ao fechar socket na tentativa de reconexão", e)
                    }
                }
            }
        }
    }

    private suspend fun processJsonChunk(jsonChunk: String) {
        try {
            val unifiedMessage = unifiedNotificationAdapter.fromJson(jsonChunk)
            if (unifiedMessage != null && (unifiedMessage.bsm != null || unifiedMessage.psm != null || unifiedMessage.tim != null)) {
                Log.i("TCP_PARSER", ">>> Mensagem UNIFICADA completa recebida e processada! <<<")
                psmPart = null; bsmPart = null; timPart = null
                processCompleteMessage(unifiedMessage)
                return
            }
        } catch (e: Exception) {
            Log.d("TCP_PARSER", "Não é um JSON unificado, tratando como fragmento.")
        }

        var fragmentFound = false
        try {
            val mapAdapter = moshi.adapter<Map<String, Any>>(Map::class.java)
            val parsedChunk = mapAdapter.fromJson(jsonChunk)

            if (parsedChunk != null) {
                when {
                    parsedChunk.containsKey("psm") -> {
                        Log.d("TCP_PARSER", "Fragmento PSM (envelopado) identificado e armazenado.")
                        val psmObject = parsedChunk["psm"]
                        psmPart = moshi.adapter(Any::class.java).toJson(psmObject)
                        fragmentFound = true
                    }

                    parsedChunk.containsKey("messageId") -> {
                        Log.d("TCP_PARSER", "Fragmento BSM identificado e armazenado.")
                        bsmPart = jsonChunk
                        fragmentFound = true
                    }
                    parsedChunk.containsKey("regions") && parsedChunk.containsKey("msgId") -> {
                        Log.d("TCP_PARSER", "Fragmento TIM identificado e armazenado.")
                        timPart = jsonChunk
                        fragmentFound = true
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("TCP_PARSER", "Erro ao analisar fragmento JSON: $jsonChunk", e)
        }


        if (!fragmentFound) {
            Log.w("TCP_PARSER", "Pedaço de JSON não identificado: $jsonChunk")
        }

        if (psmPart != null && bsmPart != null && timPart != null) {
            Log.i("TCP_PARSER", ">>> Todos os 3 FRAGMENTOS recebidos! Montando mensagem unificada. <<<")

            val unifiedJsonString = """
            {
                "psm": $psmPart,
                "bsm": $bsmPart,
                "tim": $timPart
            }
        """.trimIndent()

            psmPart = null; bsmPart = null; timPart = null

            val unifiedMessage = try {
                unifiedNotificationAdapter.fromJson(unifiedJsonString)
            } catch (e: Exception) {
                Log.e("JSON", "Erro ao fazer o parsing do JSON montado a partir de fragmentos.", e)
                null
            }

            if (unifiedMessage != null) {
                processCompleteMessage(unifiedMessage)
            }
        }
    }

    private suspend fun processCompleteMessage(message: UnifiedNotification) {
        var appNotification: com.example.app.model.Notification? = null

        if (message.bsm != null && message.psm != null) {
            val combined = CombinedNotification(message.psm, message.bsm)
            appNotification = combinedToAppNotification(combined)
        }

        val timNotification = message.tim

        val context = NotificationContext(
            psmBsmNotification = appNotification,
            timNotification = timNotification
        )

        withContext(Dispatchers.Main) {
            orchestrator.processContext(context)
        }
    }

    override fun showVisualAlert(direction: Direction, intensity: Int, obj: Objects) {
        visualAlertManager.showVisualAlert(direction, intensity, obj)
    }

    override fun playSoundAlert(direction: Direction, intensity: Int, obj: Objects) {
        SoundManager.playSound(this, direction, obj, intensity)
    }

    override fun showZoneAlert(activate: Boolean, zoneType: ZonaTipo, message: String?) {
        visualAlertManager.displayZoneAlert(activate, zoneType, message)
    }

    override fun showCombinedVisualAlert(direction: Direction, intensity: Int, obj: Objects, zoneType: ZonaTipo) {
        visualAlertManager.showCombinedVisualAlert(direction, intensity, obj, zoneType)
    }

    override fun playZoneSound(zoneType: ZonaTipo) {
        SoundManager.playZoneSound(this, zoneType)
    }

    override fun stopAllAlerts() {
        visualAlertManager.stopAllVisuals()
        SoundManager.stop()
    }


    private fun toast(msg: String) =
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }


