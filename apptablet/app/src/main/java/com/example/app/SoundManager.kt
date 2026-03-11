// ARQUIVO ATUALIZADO: SoundManager.kt

package com.example.app

import android.content.Context
import android.media.MediaPlayer
import android.util.Log

object SoundManager {

    private var mediaPlayer: MediaPlayer? = null

    fun playSound(context: Context, direction: Direction, incomingObject: Objects, intensity: Int) {
        // Garantir que qualquer som anterior seja parado e liberado antes de começar um novo.
        // A responsabilidade de parar o som agora está centralizada aqui.
        stop()

        val intensityString = when (intensity) {
            0 -> "low"
            1 -> "medium"
            2 -> "high"
            else -> "low"
        }

        val resName = "${direction.name.lowercase()}_${incomingObject.name.lowercase()}_${intensityString}"
        val resId = context.resources.getIdentifier(resName, "raw", context.packageName)

        if (resId == 0) {
            Log.w("SoundManager", "Recurso de áudio não encontrado para: $resName")
            return
        }

        mediaPlayer = MediaPlayer.create(context, resId).apply {
            isLooping = false
            // O listener agora é mais robusto: ele só limpa a referência se ela ainda for a mesma.
            // Isso previne condições de corrida se um novo som começar antes do antigo terminar.
            setOnCompletionListener { mp ->
                if (mediaPlayer == mp) {
                    mp.release()
                    mediaPlayer = null
                }
            }
            start()
        }
    }

    fun playZoneSound(context: Context, tipo: ZonaTipo) {
        stop() // Garante que nenhum outro som de alerta esteja tocando

        // Escolhe o recurso de áudio baseado no tipo de zona
        val resId = when (tipo) {
            ZonaTipo.CRIANCA -> R.raw.zona_crianca
            ZonaTipo.CICLISTA -> R.raw.zona_ciclista
        }

        if (resId == 0) {
            Log.w("SoundManager", "Recurso de áudio não encontrado para o tipo: $tipo")
            return
        }

        mediaPlayer = MediaPlayer.create(context, resId).apply {
            isLooping = false
            setOnCompletionListener { mp ->
                if (mediaPlayer == mp) {
                    mp.release()
                    mediaPlayer = null
                }
            }
            start()
        }
    }

    fun stop() {
        try {
            mediaPlayer?.let {
                if (it.isPlaying) {
                    it.stop()
                }
                it.release()
                mediaPlayer = null
            }
        } catch (e: IllegalStateException) {
            // Ignora erro se o mediaplayer já estiver em um estado inválido
            Log.w("SoundManager", "Erro ao parar MediaPlayer, provavelmente já parado: ${e.message}")
            mediaPlayer = null
        }
    }
}