package com.example.app.model

data class Notification(
    var driver_data: Driver?,
    var location: Location?,
    var driver_speed: Float,
    var timestamp: String
) {
    data class Location(
        var latitude: Double,
        var longitude: Double
    )

    data class Coordinates(
        var latitude:  Double,
        var longitude: Double,
        var speed:     Double? = null
    )

    data class Driver(
        var object_id: String,
        var risk_level: String,
        var object_direction: String,
        var object_type: String,
        var object_coordinates: Coordinates
    )
}