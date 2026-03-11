// NOVO ARQUIVO: Effect.kt
package com.example.app.rules.effects

import com.example.app.rules.context.NotificationContext

/**
 * Interface base para todas as ações (Efeitos).
 * Executa uma ação com base no contexto e na interface da UI.
 */
interface Effect {
    fun apply(context: NotificationContext, ui: NotificationUI)
}