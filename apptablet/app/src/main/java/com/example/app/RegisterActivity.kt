package com.example.app

import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.widget.Button
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.edit
import androidx.lifecycle.lifecycleScope
import com.google.android.material.textfield.TextInputEditText
import com.example.app.model.RegisterRequest
import com.example.app.network.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class RegisterActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        goToRadar()

        prefs = getSharedPreferences("driverPref", MODE_PRIVATE)

        // Já existe usuário cadastrado? pula tela
        if (prefs.getInt("userId", -1) != -1) {
            goToRadar()
            return
        }

        setContentView(R.layout.activity_register)

        val etName  = findViewById<TextInputEditText>(R.id.etName)
        val etModel = findViewById<TextInputEditText>(R.id.etModel)
        val etYear  = findViewById<TextInputEditText>(R.id.etYear)
        val etPlate = findViewById<TextInputEditText>(R.id.etPlate)
        val btnReg  = findViewById<Button>(R.id.btnRegister)

        btnReg.setOnClickListener {

            // ---------- validação ----------
            val name  = etName.text?.toString()?.trim().orEmpty()
            val model = etModel.text?.toString()?.trim().orEmpty()
            val year  = etYear.text?.toString()?.trim().orEmpty()
            val plate = etPlate.text?.toString()?.trim().orEmpty()

            if (listOf(name, model, year, plate).any { it.isBlank() }) {
                Toast.makeText(this, "Preencha todos os campos", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // ---------- chamada HTTP ----------
            lifecycleScope.launch {
                try {
                    val body = RegisterRequest(
                        name  = name,
                        model = model,
                        year  = year.toInt(),
                        plate = plate
                    )

                    val user = withContext(Dispatchers.IO) {
                        ApiClient.api.register(body)
                    }

                    // ---------- persiste localmente ----------
                    prefs.edit {
                        putInt("userId", user.id)
                        putString("name", name)
                        putString("model", model)
                        putString("year", year)
                        putString("plate", plate)
                    }

                    goToRadar()

                } catch (e: Exception) {
                    Toast.makeText(
                        this@RegisterActivity,
                        "Erro no cadastro: ${e.localizedMessage}",
                        Toast.LENGTH_LONG
                    ).show()

                    // LOG COMPLETO (adicionado)
                    e.printStackTrace()                 // aparece na aba "Run" e Logcat

                }

            }
        }
    }

    private fun goToRadar() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}