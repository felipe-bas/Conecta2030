package com.example.app.rules.effects

import com.example.app.Direction
import com.example.app.Objects
import com.example.app.ZonaTipo

/**
 * Interface que desacopla os Effects da MainActivity.
 * A MainActivity implementará esta interface, fornecendo as implementações concretas
 * para manipular a UI.
 */
interface NotificationUI {
    fun showVisualAlert(direction: Direction, intensity: Int, obj: Objects)
    fun playSoundAlert(direction: Direction, intensity: Int, obj: Objects)
    fun stopAllAlerts()
    fun showZoneAlert(activate: Boolean, zoneType: ZonaTipo, message: String?)
    fun playZoneSound(zoneType: ZonaTipo)
    fun showCombinedVisualAlert(direction: Direction, intensity: Int, obj: Objects, zoneType: ZonaTipo)
}