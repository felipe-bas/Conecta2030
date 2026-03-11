package com.example.app.rules

import com.example.app.rules.effects.Effect
import com.example.app.rules.filters.Filter

/**
 * Associa uma condição (rootFilter) a uma ou mais ações (effects).
 * A prioridade é usada pelo Orquestrador para resolver conflitos
 * quando múltiplas regras são satisfeitas. Maior número = maior prioridade.
 */
data class Rule(
    val name: String,
    val priority: Int,
    val rootFilter: Filter,
    val effects: List<Effect>
)