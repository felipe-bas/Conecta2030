package com.example.app.rules.effects

import com.example.app.rules.context.NotificationContext

/**
 * Efeito simples que limpa qualquer notificação visual/sonora anterior.
 * Útil para garantir um estado limpo antes de mostrar um novo alerta.
 */
class StopPreviousAlertsEffect : Effect {
    override fun apply(context: NotificationContext, ui: NotificationUI) {
        ui.stopAllAlerts()
    }
}