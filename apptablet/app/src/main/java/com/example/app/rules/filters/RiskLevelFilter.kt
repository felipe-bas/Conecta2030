package com.example.app.rules.filters

import com.example.app.rules.context.NotificationContext

/**
 * Filtro que verifica se a notificação de colisão (PSM/BSM)
 * corresponde a um nível de risco específico.
 */
class RiskLevelFilter(private val targetRiskLevel: String) : Filter {

    override fun isMet(context: NotificationContext): Boolean {
        // Se não houver notificação PSM/BSM no contexto, a condição não é atendida.
        val currentRiskLevel = context.psmBsmNotification?.driver_data?.risk_level
            ?: return false

        // Compara o risco atual com o risco alvo (ignorando maiúsculas/minúsculas).
        return currentRiskLevel.equals(targetRiskLevel, ignoreCase = true)
    }
}