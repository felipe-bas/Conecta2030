package com.example.app.rules.filters

import com.example.app.ZonaTipo
import com.example.app.rules.context.NotificationContext
import android.util.Log

class ZoneTypeFilter(private val targetZoneType: ZonaTipo) : Filter {

    override fun isMet(context: NotificationContext): Boolean {
        val regionName = context.timNotification?.regions?.firstOrNull()?.name
            ?: return false

        Log.d("ZoneTypeFilter", "Analisando nome da região TIM: '$regionName'")

        return when (targetZoneType) {
            ZonaTipo.CRIANCA -> regionName.contains("escolar", ignoreCase = true) ||
                    regionName.contains("criança", ignoreCase = true)

            ZonaTipo.CICLISTA -> regionName.contains("ciclista", ignoreCase = true)
        }
    }
}