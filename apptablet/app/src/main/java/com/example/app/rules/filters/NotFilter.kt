package com.example.app.rules.filters

import com.example.app.rules.context.NotificationContext

/**
 * Filtro Decorator que inverte o resultado de outro filtro.
 */
class NotFilter(private val filter: Filter) : Filter {

    override fun isMet(context: NotificationContext): Boolean {
        return !filter.isMet(context)
    }
}