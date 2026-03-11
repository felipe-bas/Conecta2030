package com.example.app

import android.content.SharedPreferences
import android.os.Bundle
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.switchmaterial.SwitchMaterial
import androidx.core.content.edit
import com.google.android.material.button.MaterialButton

class SettingsActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences

    private lateinit var switchVisualAlto: SwitchMaterial
    private lateinit var switchVibracaoAlto: SwitchMaterial
    private lateinit var switchSonoraAlto: SwitchMaterial

    private lateinit var switchVisualMedio: SwitchMaterial
    private lateinit var switchVibracaoMedio: SwitchMaterial
    private lateinit var switchSonoraMedio: SwitchMaterial

    private lateinit var switchVisualBaixo: SwitchMaterial
    private lateinit var switchVibracaoBaixo: SwitchMaterial
    private lateinit var switchSonoraBaixo: SwitchMaterial

    private lateinit var saveButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        prefs = getSharedPreferences("driverPref", MODE_PRIVATE)

        setContentView(R.layout.activity_settings)

        switchVisualAlto    = findViewById(R.id.switchVisualAlto)
//        switchVibracaoAlto  = findViewById(R.id.switchVibracaoAlto)
        switchSonoraAlto    = findViewById(R.id.switchSonoraAlto)

        switchVisualMedio    = findViewById(R.id.switchVisualMedio)
//        switchVibracaoMedio  = findViewById(R.id.switchVibracaoMedio)
        switchSonoraMedio    = findViewById(R.id.switchSonoraMedio)

        switchVisualBaixo    = findViewById(R.id.switchVisualBaixo)
//        switchVibracaoBaixo  = findViewById(R.id.switchVibracaoBaixo)
        switchSonoraBaixo    = findViewById(R.id.switchSonoraBaixo)

        saveButton      = findViewById(R.id.btnSaveSettings)

        loadPreferences()

        saveButton.setOnClickListener {
            prefs.edit (true) {
                putBoolean("notif_visual-alto", switchVisualAlto.isChecked)
//                putBoolean("notif_vibracao-alto", switchVibracaoAlto.isChecked)
                putBoolean("notif_sonora-alto", switchSonoraAlto.isChecked)

                putBoolean("notif_visual-medio", switchVisualMedio.isChecked)
//                putBoolean("notif_vibracao-medio", switchVibracaoMedio.isChecked)
                putBoolean("notif_sonora-medio", switchSonoraMedio.isChecked)

                putBoolean("notif_visual-baixo", switchVisualBaixo.isChecked)
//                putBoolean("notif_vibracao-baixo", switchVibracaoBaixo.isChecked)
                putBoolean("notif_sonora-baixo", switchSonoraBaixo.isChecked)
            }

            finish()
        }
    }

    private fun loadPreferences() {
        val visualAltoOn   = prefs.getBoolean("notif_visual-alto", true)
//        val vibracaoAltoOn = prefs.getBoolean("notif_vibracao-alto", true)
        val sonoraAltoOn   = prefs.getBoolean("notif_sonora-alto", true)

        val visualMedioOn   = prefs.getBoolean("notif_visual-medio", true)
//        val vibracaoMedioOn = prefs.getBoolean("notif_vibracao-medio", true)
        val sonoraMedioOn   = prefs.getBoolean("notif_sonora-medio", true)

        val visualBaixoOn   = prefs.getBoolean("notif_visual-baixo", true)
//        val vibracaoBaixoOn = prefs.getBoolean("notif_vibracao-baixo", true)
        val sonoraBaixoOn   = prefs.getBoolean("notif_sonora-baixo", true)

        switchVisualAlto.isChecked   = visualAltoOn
//        switchVibracaoAlto.isChecked = vibracaoAltoOn
        switchSonoraAlto.isChecked   = sonoraAltoOn

        switchVisualMedio.isChecked   = visualMedioOn
//        switchVibracaoMedio.isChecked = vibracaoMedioOn
        switchSonoraMedio.isChecked   = sonoraMedioOn

        switchVisualBaixo.isChecked   = visualBaixoOn
//        switchVibracaoBaixo.isChecked = vibracaoBaixoOn
        switchSonoraBaixo.isChecked   = sonoraBaixoOn
    }
}
