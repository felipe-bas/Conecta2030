package com.example.app.rules.effects

import com.example.app.Direction
import com.example.app.Objects
import com.example.app.ZonaTipo
import com.example.app.rules.context.NotificationContext

/**
 * Efeito que aplica AMBOS os alertas sonoros: o de colisão e o de zona.
 */
class CombinedSoundEffect(private val zoneType: ZonaTipo) : Effect {
    override fun apply(context: NotificationContext, ui: NotificationUI) {
        // --- PARTE 1: Lógica do Som de Zona ---
        ui.playZoneSound(zoneType)

        // --- PARTE 2: Lógica do Som de Colisão (copiada do SoundNotificationEffect) ---
        val notif = context.psmBsmNotification?.driver_data ?: return

        val dir = when (notif.object_direction.lowercase()) {
            "left" -> Direction.LEFT
            "right" -> Direction.RIGHT
            "front" -> Direction.TOP
            "rear" -> Direction.BOTTOM
            else -> Direction.NULL
        }

        val intensity = when (notif.risk_level.lowercase()) {
            "low" -> 0
            "medium" -> 1
            "high" -> 2
            else -> -1
        }

        val obj = when (notif.object_type.lowercase()) {
            "human" -> Objects.HUMAN
            "bike" -> Objects.BIKE
            "vehicle" -> Objects.VEHICLE
            else -> Objects.NULL
        }

        if (dir != Direction.NULL && intensity != -1) {
            ui.playSoundAlert(dir, intensity, obj)
        }
    }
}