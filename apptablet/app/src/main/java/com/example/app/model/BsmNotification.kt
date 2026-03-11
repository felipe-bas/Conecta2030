// NOVO ARQUIVO: BsmNotification.kt
package com.example.app.model

import com.squareup.moshi.Json

data class BsmNotification(
    @Json(name = "messageId") val messageId: Int,
    @Json(name = "value") val value: Value
) {
    data class Value(
        @Json(name = "coreData") val coreData: CoreData,
        @Json(name = "partII") val partII: List<PartIIItem>?
    )

    data class CoreData(
        @Json(name = "msgCnt") val msgCnt: Int,
        @Json(name = "id") val id: String,
        @Json(name = "secMark") val secMark: Int,
        @Json(name = "lat") val lat: Long, // Vem como inteiro, precisa de conversão
        @Json(name = "long") val long: Long, // Vem como inteiro, precisa de conversão
        @Json(name = "elev") val elev: Int,
        @Json(name = "accuracy") val accuracy: Accuracy,
        @Json(name = "transmission") val transmission: String,
        @Json(name = "speed") val speed: Int, // Vem como inteiro, precisa de conversão (0.02 m/s)
        @Json(name = "heading") val heading: Int,
        @Json(name = "angle") val angle: Int,
        @Json(name = "accelSet") val accelSet: AccelSet,
        @Json(name = "brakes") val brakes: Brakes,
        @Json(name = "size") val size: Size
    )

    data class Accuracy(
        @Json(name = "semiMajor") val semiMajor: Int,
        @Json(name = "semiMinor") val semiMinor: Int,
        @Json(name = "orientation") val orientation: Int
    )

    data class AccelSet(
        @Json(name = "long") val long: Int,
        @Json(name = "lat") val lat: Int,
        @Json(name = "vert") val vert: Int,
        @Json(name = "yaw") val yaw: Int
    )

    data class Brakes(
        @Json(name = "wheelBrakes") val wheelBrakes: String,
        @Json(name = "traction") val traction: String,
        @Json(name = "abs") val abs: String,
        @Json(name = "scs") val scs: String,
        @Json(name = "brakeBoost") val brakeBoost: String,
        @Json(name = "auxBrakes") val auxBrakes: String
    )

    data class Size(
        @Json(name = "width") val width: Int,
        @Json(name = "length") val length: Int
    )

    data class PartIIItem(
        @Json(name = "partII-Id") val partIIId: Int,
        @Json(name = "partII-Value") val partIIValue: PartIIValue
    )

    data class PartIIValue(
        @Json(name = "pathHistory") val pathHistory: PathHistory,
        @Json(name = "pathPrediction") val pathPrediction: PathPrediction
    )

    data class PathHistory(
        @Json(name = "crumbData") val crumbData: List<CrumbData>
    )

    data class CrumbData(
        @Json(name = "latOffset") val latOffset: Int,
        @Json(name = "lonOffset") val lonOffset: Int,
        @Json(name = "elevationOffset") val elevationOffset: Int,
        @Json(name = "timeOffset") val timeOffset: Int
    )

    data class PathPrediction(
        @Json(name = "radiusOfCurve") val radiusOfCurve: Int,
        @Json(name = "confidence") val confidence: Int
    )
}