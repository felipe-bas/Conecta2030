package com.example.app.processing

import android.location.Location
import com.example.app.model.CombinedNotification
import com.example.app.model.Notification
import java.time.Instant

fun combinedToAppNotification(data: CombinedNotification): Notification {
    val bsm = data.bsm.value.coreData
    val psm = data.psm

    val userLat = bsm.lat / 10_000_000.0
    val userLon = bsm.long / 10_000_000.0
    val userSpeed = bsm.speed.toFloat() * 0.02f
    val userHeading = bsm.heading * 0.0125

    val objectLat = psm.position.latitude / 10_000_000.0
    val objectLon = psm.position.longitude / 10_000_000.0
    val objectSpeed = psm.speed * 0.02

    val objType = when {
        psm.basicType.contains("PEDESTRIAN", ignoreCase = true) -> "HUMAN"
        psm.basicType.contains("CYCLIST", ignoreCase = true) -> "BIKE"
        else -> "HUMAN"
    }

    val bearingToObject = calculateBearing(userLat, userLon, objectLat, objectLon)
    val relativeAngle = normalizeAngle(bearingToObject - userHeading)

    val dirString = when {
        relativeAngle >= -45 && relativeAngle < 45 -> "front"
        relativeAngle >= 45 && relativeAngle < 135 -> "right"
        relativeAngle >= 135 || relativeAngle < -135 -> "rear"
        else -> "left"
    }

    val userLocation = Notification.Location(latitude = userLat, longitude = userLon)
    val objectCoords = Notification.Coordinates(latitude = objectLat, longitude = objectLon, speed = objectSpeed)
    val driverData = Notification.Driver(
        object_id = psm.id,
        risk_level = "low", // O risco é calculado depois
        object_direction = dirString,
        object_type = objType,
        object_coordinates = objectCoords
    )

    val convertedNotif = Notification(
        driver_data = driverData,
        location = userLocation,
        driver_speed = userSpeed,
        timestamp = Instant.now().toString()
    )

    val ttc = timeToCollision(convertedNotif)
    convertedNotif.driver_data?.risk_level = if (ttc != null) {
        when {
            ttc < 4.0 -> "high"
            ttc <= 8.0 -> "medium"
            else -> "low"
        }
    } else {
        "low"
    }
    return convertedNotif
}

fun timeToCollision(notification: Notification?): Double? {
    val userLocation = notification?.location ?: return null
    val driverData = notification.driver_data ?: return null
    val objectCoords = driverData.object_coordinates
    val objectSpeed = objectCoords.speed ?: return null
    val userSpeed = notification.driver_speed.toDouble()
    val direction = driverData.object_direction.lowercase()

    val dist = distanceMeters(
        userLocation.latitude, userLocation.longitude,
        objectCoords.latitude, objectCoords.longitude
    )

    val vRel = when (direction) {
        "front", "left", "right" -> userSpeed + objectSpeed
        "rear" -> if (objectSpeed > userSpeed) objectSpeed - userSpeed else -1.0
        else -> -1.0
    }

    return if (vRel > 0.0) dist / vRel else null
}

fun distanceMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val res = FloatArray(1)
    Location.distanceBetween(lat1, lon1, lat2, lon2, res)
    return res[0].toDouble()
}

private fun calculateBearing(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val lat1Rad = Math.toRadians(lat1)
    val lat2Rad = Math.toRadians(lat2)
    val deltaLonRad = Math.toRadians(lon2 - lon1)
    val y = Math.sin(deltaLonRad) * Math.cos(lat2Rad)
    val x = Math.cos(lat1Rad) * Math.sin(lat2Rad) - Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(deltaLonRad)
    val bearingRad = Math.atan2(y, x)
    return (Math.toDegrees(bearingRad) + 360) % 360
}

private fun normalizeAngle(angle: Double): Double {
    var a = angle % 360
    if (a > 180) a -= 360
    if (a <= -180) a += 360
    return a
}