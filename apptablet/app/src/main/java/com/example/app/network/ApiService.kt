package com.example.app.network

import com.example.app.model.RegisterRequest
import com.example.app.model.User
import retrofit2.http.Body
import retrofit2.http.POST

interface ApiService {
    @POST("register")
    suspend fun register(@Body body: RegisterRequest): User
}