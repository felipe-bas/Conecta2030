package com.example.app.rules.effects

import android.os.Handler
import android.os.Looper
import com.example.app.ZonaTipo
import com.example.app.rules.context.NotificationContext

/**
 * Ativa um alerta de zona na UI e agenda sua própria desativação após uma duração.
 * Este efeito gerencia seu próprio ciclo de vida.
 */
class ExpiringZoneAlertEffect(
    private val zoneType: ZonaTipo,
    private val durationMs: Long
) : Effect {

    companion object {
        private val handler = Handler(Looper.getMainLooper())
        private var activeRunnable: Runnable? = null
    }

    override fun apply(context: NotificationContext, ui: NotificationUI) {
        // Cancela qualquer alerta de zona anterior para evitar sobreposição
        activeRunnable?.let { handler.removeCallbacks(it) }

        // Ativa o novo alerta
        val message = context.timNotification?.regions?.firstOrNull()?.name
        ui.showZoneAlert(true, zoneType, message)
        ui.playZoneSound(zoneType)

        // Agenda a desativação
        val runnable = Runnable {
            ui.showZoneAlert(false, zoneType, null)
            activeRunnable = null
        }

        handler.postDelayed(runnable, durationMs)
        activeRunnable = runnable
    }
}