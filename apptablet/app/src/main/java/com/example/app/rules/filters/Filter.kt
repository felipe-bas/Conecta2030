package com.example.app.rules.filters

import com.example.app.rules.context.NotificationContext

interface Filter {
    fun isMet(context: NotificationContext): Boolean
}