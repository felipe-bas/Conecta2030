package com.example.app.rules.context

import com.example.app.model.Notification
import com.example.app.model.TimNotification


data class NotificationContext(
    val psmBsmNotification: Notification? = null,
    val timNotification: TimNotification? = null
)