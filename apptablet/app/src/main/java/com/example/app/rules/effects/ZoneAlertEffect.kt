// NOVO ARQUIVO: ZoneAlertEffect.kt
package com.example.app.rules.effects

import com.example.app.ZonaTipo
import com.example.app.rules.context.NotificationContext

/**
 * Ativa o alerta de zona na UI com base no tipo de zona.
 */
class ZoneAlertEffect(private val zoneType: ZonaTipo) : Effect {
    override fun apply(context: NotificationContext, ui: NotificationUI) {
        // A lógica de desativação por tempo será tratada de outra forma.
        // O efeito apenas se preocupa em *ativar* o alerta.
        val message = context.timNotification?.regions?.firstOrNull()?.name
        ui.showZoneAlert(true, zoneType, message)
        ui.playZoneSound(zoneType)
    }
}