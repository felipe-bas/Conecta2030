package com.example.app.model

data class RegisterRequest(
    val name: String,
    val role: String = "driver",
    val model: String,
    val year: Int,
    val plate: String
)