package com.example.app.util

import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime

data class TimeParts(
    val year:   Int,
    val month:  Int,
    val day:    Int,
    val hour:   Int,
    val minute: Int,
    val second: Int,
    val milli:  Int
)

/**
 * Converte uma String ISO-8601 (“2025-06-09T18:59:21.123Z”)
 * para TimeParts com hora local do dispositivo (ou zona passada).
 */
fun isoToTimeParts(
    iso: String,
    zone: ZoneId = ZoneId.systemDefault()
): TimeParts {
    val zdt: ZonedDateTime = Instant.parse(iso).atZone(zone)
    return TimeParts(
        year   = zdt.year,
        month  = zdt.monthValue,
        day    = zdt.dayOfMonth,
        hour   = zdt.hour,
        minute = zdt.minute,
        second = zdt.second,
        milli  = zdt.nano / 1_000_000
    )
}