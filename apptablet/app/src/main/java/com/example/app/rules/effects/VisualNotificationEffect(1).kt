package com.example.app.rules.effects

import com.example.app.Direction
import com.example.app.Objects
import com.example.app.rules.context.NotificationContext

/**
 * Aciona a notificação visual na UI.
 */
class VisualNotificationEffect : Effect {
    override fun apply(context: NotificationContext, ui: NotificationUI) {
        val notif = context.psmBsmNotification?.driver_data ?: return

        // Converte os dados do contexto para os enums que a UI espera
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
            ui.showVisualAlert(dir, intensity, obj)
        }
    }
}