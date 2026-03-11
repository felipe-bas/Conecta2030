package com.example.app.rules

import android.os.Handler
import android.os.Looper
import android.util.Log
import com.example.app.rules.context.NotificationContext
import com.example.app.rules.effects.NotificationUI
import com.example.app.rules.effects.ExpiringZoneAlertEffect

class Orchestrator(private val ui: NotificationUI) {

    private val rules = mutableListOf<Rule>()
    private val handler = Handler(Looper.getMainLooper())
    private val NOTIFICATION_TIMEOUT_MS = 5000L

    private var activeRule: Rule? = null
    private var cleanupRunnable: Runnable? = null

    fun start() {
        clearActiveNotification()
    }

    fun addRule(rule: Rule) {
        rules.add(rule)
        rules.sortByDescending { it.priority }
    }

    fun processContext(context: NotificationContext) {
        val bestMatchingRule = rules.firstOrNull { it.rootFilter.isMet(context) }

        if (bestMatchingRule == null) {
            // Nenhuma regra foi satisfeita. Se houver um alerta ativo que não seja do tipo "expiring",
            // devemos limpá-lo, pois a condição de perigo não existe mais.
            val isActiveRuleStateful = activeRule?.effects?.none { it is ExpiringZoneAlertEffect } ?: false
            if (isActiveRuleStateful) {
                Log.d("Orchestrator", "Nenhuma regra satisfeita. Limpando alerta ativo '${activeRule?.name}'.")
                clearActiveNotification()
            }
            return
        }

        val activePriority = activeRule?.priority ?: -1
        val newPriority = bestMatchingRule.priority

        if (newPriority >= activePriority) {
            // A nova regra tem prioridade suficiente para ser exibida.
            displayNotification(bestMatchingRule, context)
        }
        // Se a nova regra tiver prioridade menor, simplesmente a ignoramos.
    }

    private fun displayNotification(rule: Rule, context: NotificationContext) {
        // Se a regra a ser exibida for a mesma que já está ativa, apenas reiniciamos o timeout.
        if (rule == activeRule) {
            Log.d("Orchestrator", "Refrescando timeout para a regra '${rule.name}'.")
            resetCleanupTimer(rule)
            return
        }

        Log.d("Orchestrator", "Exibindo nova regra '${rule.name}'.")

        // Limpa qualquer estado anterior antes de aplicar os novos efeitos.
        clearActiveNotification()

        // Aplica os efeitos da nova regra.
        rule.effects.forEach { effect ->
            effect.apply(context, ui)
        }

        // Define a nova regra como ativa e agenda sua limpeza.
        activeRule = rule
        resetCleanupTimer(rule)
    }

    private fun resetCleanupTimer(rule: Rule) {
        cleanupRunnable?.let { handler.removeCallbacks(it) }
        cleanupRunnable = null

        val requiresCleanup = rule.effects.none { it is ExpiringZoneAlertEffect }
        if (requiresCleanup) {
            cleanupRunnable = Runnable {
                Log.d("Orchestrator", "Timeout para a regra '${rule.name}'. Limpando.")
                clearActiveNotification()
            }
            handler.postDelayed(cleanupRunnable!!, NOTIFICATION_TIMEOUT_MS)
        }
    }

    private fun clearActiveNotification() {
        cleanupRunnable?.let { handler.removeCallbacks(it) }
        ui.stopAllAlerts()
        activeRule = null
        cleanupRunnable = null
    }
}