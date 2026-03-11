package com.example.app.model

import com.squareup.moshi.Json

data class PsmNotification(
    @Json(name="basicType") val basicType: String,
    @Json(name="secMark")   val secMark: Int,
    @Json(name="msgCnt")    val msgCnt: Int,
    @Json(name="id")        val id: String,
    @Json(name="position")  val position: Position,
    @Json(name="accuracy")  val accuracy: Accuracy,
    @Json(name="speed")     val speed: Int,
    @Json(name="heading")   val heading: Int,
    @Json(name="pathHistory")   val pathHistory: PathHistory,
    @Json(name="pathPrediction") val pathPrediction: PathPrediction
) {
    data class Position(
        @Json(name="lat" ) val latitude: Long,
        @Json(name="long") val longitude: Long
    )
    data class Accuracy(
        val semiMajor: Int,
        val semiMinor: Int,
        val orientation: Int
    )
    data class PathHistory(
        val crumbData: List<CrumbData>
    ) {
        data class CrumbData(
            val latOffset: Int,
            val lonOffset: Int,
            val elevationOffset: Int,
            val timeOffset: Int
        )
    }
    data class PathPrediction(
        val radiusOfCurve: Int,
        val confidence: Int
    )
}
