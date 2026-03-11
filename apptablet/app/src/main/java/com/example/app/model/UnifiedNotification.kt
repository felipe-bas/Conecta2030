package com.example.app.model

import com.squareup.moshi.Json

data class UnifiedNotification(
    @Json(name="bsm") val bsm: BsmNotification?,
    @Json(name="psm") val psm: PsmNotification?,
    @Json(name="tim") val tim: TimNotification?
)