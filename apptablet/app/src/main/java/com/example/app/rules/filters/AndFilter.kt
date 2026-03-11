package com.example.app.rules.filters

import com.example.app.rules.context.NotificationContext

/**
 * Filtro Composto que implementa a lógica AND.
 * Retorna 'true' somente se TODOS os filtros filhos retornarem 'true'.
 * Usa o padrão Composite.
 */
class AndFilter(private val filters: List<Filter>) : Filter {

    // Construtor secundário para conveniência (aceita vararg)
    constructor(vararg filters: Filter) : this(filters.toList())

    override fun isMet(context: NotificationContext): Boolean {
        // A função all() do Kotlin é perfeita para isso.
        // Ela para na primeira vez que encontra 'false'.
        return filters.all { it.isMet(context) }
    }
}