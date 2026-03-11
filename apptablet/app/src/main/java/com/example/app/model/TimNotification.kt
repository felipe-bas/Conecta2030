package com.example.app.model

import com.squareup.moshi.Json

/**
 * Representa a nova estrutura da mensagem TIM.
 */
data class TimNotification(
    @Json(name = "msgId") val msgId: MsgId?,
    @Json(name = "startTime") val startTime: Int?,
    @Json(name = "durationTime") val durationTime: Int?,
    @Json(name = "priority") val priority: Int?,
    @Json(name = "regions") val regions: List<Region>?
)

data class MsgId(
    @Json(name = "furtherInfoID") val furtherInfoID: String?
)

data class Region(
    @Json(name = "name") val name: String?,
    @Json(name = "id") val id: RegionId?,
    @Json(name = "description") val description: Description?
)

data class RegionId(
    @Json(name = "region") val region: Int?,
    @Json(name = "id") val id: Int?
)

data class Description(
    @Json(name = "path") val path: Path?
)

data class Path(
    @Json(name = "offset") val offset: Offset?
)

data class Offset(
    @Json(name = "ll") val ll: LL?
)

data class LL(
    @Json(name = "nodes") val nodes: List<Node>?
)

data class Node(
    @Json(name = "delta") val delta: Delta?
)

data class Delta(
    @Json(name = "node-LL1") val nodeLL1: NodeLL1?
)

data class NodeLL1(
    @Json(name = "lat") val lat: Int?,
    @Json(name = "lon") val lon: Int?
)