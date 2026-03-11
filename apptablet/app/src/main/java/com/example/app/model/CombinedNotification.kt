// NOVO ARQUIVO: CombinedNotification.kt
package com.example.app.model

import com.squareup.moshi.Json

data class CombinedNotification(
    @Json(name="psm") val psm: PsmNotification,
    @Json(name="bsm") val bsm: BsmNotification
)