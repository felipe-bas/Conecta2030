package com.example.app.rules.filters

import com.example.app.rules.context.NotificationContext

/**
 * Filtro Composto que implementa a lógica OR.
 * Retorna 'true' se PELO MENOS UM dos filtros filhos retornar 'true'.
 * Usa o padrão Composite.
 */
class OrFilter(private val filters: List<Filter>) : Filter {

    // Construtor secundário para conveniência
    constructor(vararg filters: Filter) : this(filters.toList())

    override fun isMet(context: NotificationContext): Boolean {
        // A função any() do Kotlin é perfeita para isso.
        // Ela para na primeira vez que encontra 'true'.
        return filters.any { it.isMet(context) }
    }
}