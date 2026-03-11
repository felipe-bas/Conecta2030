package com.example.app.ui

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.view.animation.AccelerateInterpolator
import android.view.animation.LinearInterpolator
import androidx.core.content.ContextCompat
import com.example.app.Direction
import com.example.app.Objects
import com.example.app.R
import com.example.app.ZonaTipo
import com.example.app.databinding.ActivityMainBinding
import com.example.app.databinding.NotificationChildZoneBinding

class VisualAlertManager(
    private val context: Context,
    private val binding: ActivityMainBinding,
    private val childZoneBinding: NotificationChildZoneBinding
) {
    private val pulseAnimators = mutableMapOf<Direction, ValueAnimator>()
    private val arrowAnimators = mutableMapOf<Direction, ValueAnimator>()
    private var iconBreathingAnimator: AnimatorSet? = null

    private var standbyAnimator: AnimatorSet? = null

    /**
     * Ponto de entrada principal para exibir um alerta visual completo.
     */
    fun showVisualAlert(direction: Direction, intensity: Int, incomingObject: Objects) {
        stopActiveStandbyAnimation()

        if (direction == Direction.TOP) {
            val translation = 150f
            binding.carImg.translationY = translation
            binding.topArrow.translationY = translation
            childZoneBinding.childZoneNotificationLayout.translationY = translation
        } else if (direction == Direction.BOTTOM) {
            val translation = -150f
            binding.carImg.translationY = translation
            binding.bottomArrow.translationY = translation
            childZoneBinding.childZoneNotificationLayout.translationY = translation
        }

        startArrowBlink(direction, intensity)
        if (intensity != -1) startPulse(direction, intensity)
        if (incomingObject != Objects.NULL) showObject(direction, incomingObject)
    }

    fun showCombinedVisualAlert(
        direction: Direction,
        intensity: Int,
        incomingObject: Objects,
        zoneType: ZonaTipo
    ) {
        // 1. Exibe a placa de zona primeiro
        displayZoneAlert(true, zoneType, null)

        // 2. Executa a lógica de translação do carro (sem esconder a placa)
        if (direction == Direction.TOP) {
            val translation = 150f
            binding.carImg.translationY = translation
            binding.topArrow.translationY = translation
            childZoneBinding.childZoneNotificationLayout.translationY = translation
        } else if (direction == Direction.BOTTOM) {
            val translation = -150f
            binding.carImg.translationY = translation
            binding.bottomArrow.translationY = translation
            childZoneBinding.childZoneNotificationLayout.translationY = translation
        }

        // 3. Exibe os componentes do alerta de colisão
        startArrowBlink(direction, intensity)
        if (intensity != -1) startPulse(direction, intensity)
        if (incomingObject != Objects.NULL) showObject(direction, incomingObject)
    }

    /**
     * Para e esconde todos os elementos visuais de alerta de todas as direções,
     * garantindo que a UI retorne a um estado limpo.
     */
    fun stopAllVisuals() {
        displayZoneAlert(false, ZonaTipo.CRIANCA, null)
        listOf(Direction.TOP, Direction.BOTTOM, Direction.LEFT, Direction.RIGHT).forEach { dir ->
            stopPulse(dir)
            stopArrowBlink(dir)
            removeObjectImg(dir)
        }

        binding.carImg.translationY = 0f
        binding.topArrow.translationY = 0f
        binding.bottomArrow.translationY = 0f
        childZoneBinding.childZoneNotificationLayout.translationY = 0f
        binding.settingsIcon.visibility = View.VISIBLE

        startActiveStandbyAnimation()
    }

    fun startActiveStandbyAnimation() {
        if (standbyAnimator != null) return

        val pulse1 = binding.standbyPulse1
        val pulse2 = binding.standbyPulse2
        val pulse3 = binding.standbyPulse3

        pulse1.visibility = View.VISIBLE
        pulse2.visibility = View.VISIBLE
        pulse3.visibility = View.VISIBLE

        val animationDuration = 3500L
        val delayStep = animationDuration / 3

        val animator1 = AnimatorSet().apply {
            playTogether(
                ObjectAnimator.ofFloat(pulse1, "scaleX", 1f, 5f),
                ObjectAnimator.ofFloat(pulse1, "scaleY", 1f, 5f),
                ObjectAnimator.ofFloat(pulse1, "alpha", 1f, 0f)
            )
            duration = animationDuration
            interpolator = AccelerateInterpolator()
        }

        val animator2 = AnimatorSet().apply {
            playTogether(
                ObjectAnimator.ofFloat(pulse2, "scaleX", 1f, 5f),
                ObjectAnimator.ofFloat(pulse2, "scaleY", 1f, 5f),
                ObjectAnimator.ofFloat(pulse2, "alpha", 1f, 0f)
            )
            duration = animationDuration
            startDelay = delayStep
            interpolator = AccelerateInterpolator()
        }

        val animator3 = AnimatorSet().apply {
            playTogether(
                ObjectAnimator.ofFloat(pulse3, "scaleX", 1f, 5f),
                ObjectAnimator.ofFloat(pulse3, "scaleY", 1f, 5f),
                ObjectAnimator.ofFloat(pulse3, "alpha", 1f, 0f)
            )
            duration = animationDuration
            startDelay = delayStep * 2
            interpolator = AccelerateInterpolator()
        }

        standbyAnimator = AnimatorSet().apply {
            playTogether(animator1, animator2, animator3)
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    if (standbyAnimator != null) {
                        animation.start()
                    }
                }
            })
            start()
        }
    }

    /**
     * Para e limpa a animação de standby.
     */
    fun stopActiveStandbyAnimation() {
        standbyAnimator?.let {
            it.removeAllListeners() // Impede que a animação se reinicie
            it.cancel()
        }
        standbyAnimator = null
        binding.standbyPulse1.visibility = View.GONE
        binding.standbyPulse2.visibility = View.GONE
        binding.standbyPulse3.visibility = View.GONE
        // Reseta as propriedades para o próximo início
        binding.standbyPulse1.apply { scaleX = 1f; scaleY = 1f; alpha = 1f; }
        binding.standbyPulse2.apply { scaleX = 1f; scaleY = 1f; alpha = 1f; }
        binding.standbyPulse3.apply { scaleX = 1f; scaleY = 1f; alpha = 1f; }
    }

    /**
     * Controla a exibição e o ocultamento do alerta de zona (escola, ciclista, etc.).
     */
    fun displayZoneAlert(activate: Boolean, zoneType: ZonaTipo, message: String?) {
        val notificationContentLayout = childZoneBinding.childZoneNotificationLayout
        val iconZone = childZoneBinding.iconSchoolZone

        if (activate) {
            val (iconResId, defaultText) = when (zoneType) {
                ZonaTipo.CRIANCA -> R.drawable.school_zone_sign to "Atenção: Área escolar próxima"
                ZonaTipo.CICLISTA -> R.drawable.cyclist_zone_sign to "Atenção: Ciclistas na via"
            }

            iconZone.setImageResource(iconResId)

            notificationContentLayout.visibility = View.VISIBLE
            notificationContentLayout.bringToFront()

            iconBreathingAnimator?.cancel()

            val scaleX = ObjectAnimator.ofFloat(iconZone, "scaleX", 1.0f, 1.05f, 1.0f)
            val scaleY = ObjectAnimator.ofFloat(iconZone, "scaleY", 1.0f, 1.05f, 1.0f)
            scaleX.duration = 3000
            scaleY.duration = 3000
            scaleX.repeatCount = ValueAnimator.INFINITE
            scaleY.repeatCount = ValueAnimator.INFINITE
            scaleX.interpolator = LinearInterpolator()
            scaleY.interpolator = LinearInterpolator()

            iconBreathingAnimator = AnimatorSet().apply {
                playTogether(scaleX, scaleY)
                start()
            }
        } else {
            notificationContentLayout.visibility = View.GONE
            iconBreathingAnimator?.cancel()
            iconBreathingAnimator = null
        }
    }

    private fun startPulse(direction: Direction, intensity: Int) {
        val view = getViewForDirection(binding.leftPulse, binding.rightPulse, binding.topPulse, binding.bottomPulse, direction)
        pulseAnimators[direction]?.cancel()

        val startColor = when (intensity) {
            0 -> ContextCompat.getColor(context, R.color.alert_gray)
            1 -> ContextCompat.getColor(context, R.color.alert_yellow)
            else -> ContextCompat.getColor(context, R.color.alert_red)
        }
        val endColor = ContextCompat.getColor(context, android.R.color.transparent)

        val gd = (ContextCompat.getDrawable(context, R.drawable.gradient)!!.mutate() as GradientDrawable).apply {
            colors = intArrayOf(startColor, endColor)
            gradientType = GradientDrawable.RADIAL_GRADIENT
            when (direction) {
                Direction.LEFT -> setGradientCenter(0f, 0.5f)
                Direction.RIGHT -> setGradientCenter(1f, 0.5f)
                Direction.TOP -> setGradientCenter(0.5f, 0f)
                Direction.BOTTOM -> setGradientCenter(0.5f, 1f)
                else -> setGradientCenter(0.5f, 1f)
            }
        }
        view.background = gd
        view.visibility = View.VISIBLE

        view.post {
            val (minSize, maxSize) = if (direction == Direction.LEFT || direction == Direction.RIGHT) 350f to 400f else 200f to 300f
            val animTime = when (intensity) {
                0 -> 800L; 1 -> 500L; 2 -> 300L; else -> 800L
            }
            val anim = ValueAnimator.ofFloat(minSize, maxSize).apply {
                duration = animTime
                repeatMode = ValueAnimator.REVERSE
                repeatCount = ValueAnimator.INFINITE
                interpolator = LinearInterpolator()
                addUpdateListener { va ->
                    gd.gradientRadius = va.animatedValue as Float
                    view.invalidate()
                }
                start()
            }
            pulseAnimators[direction] = anim
        }
    }

    private fun stopPulse(direction: Direction) {
        pulseAnimators[direction]?.cancel()
        pulseAnimators.remove(direction)
        val view = getViewForDirection(binding.leftPulse, binding.rightPulse, binding.topPulse, binding.bottomPulse, direction)
        view.visibility = View.GONE
    }

    private fun startArrowBlink(direction: Direction, intensity: Int) {
        val arrowView = getViewForDirection(binding.leftArrow, binding.rightArrow, binding.topArrow, binding.bottomArrow, direction)
        arrowView.apply {
            when (direction) {
                Direction.LEFT -> scaleX = -1f
                Direction.RIGHT -> scaleX = 1f
                Direction.TOP -> { scaleX = 1f; rotation = -90f }
                Direction.BOTTOM -> { scaleX = 1f; rotation = 90f }
                else -> {}
            }
            alpha = 0f
            visibility = View.VISIBLE
        }

        arrowAnimators[direction]?.cancel()
        val animDuration = when (intensity) {
            0 -> 400L; 1 -> 300L; 2 -> 200L; else -> 400L
        }

        val anim = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = animDuration
            repeatMode = ValueAnimator.REVERSE
            repeatCount = ValueAnimator.INFINITE
            interpolator = LinearInterpolator()
            addUpdateListener { va -> arrowView.alpha = va.animatedValue as Float }
            start()
        }
        arrowAnimators[direction] = anim
    }

    private fun stopArrowBlink(direction: Direction) {
        arrowAnimators[direction]?.cancel()
        arrowAnimators.remove(direction)
        val arrowView = getViewForDirection(binding.leftArrow, binding.rightArrow, binding.topArrow, binding.bottomArrow, direction)
        arrowView.visibility = View.GONE
    }

    private fun showObject(direction: Direction, incomingObject: Objects) {
        val objectView = getViewForDirection(binding.leftObject, binding.rightObject, binding.topObject, binding.bottomObject, direction)
        val resId = when (incomingObject) {
            Objects.VEHICLE -> R.drawable.vehicle_icon
            Objects.MOTORCYCLE -> R.drawable.motorcycle
            Objects.BIKE -> R.drawable.cyclist
            Objects.HUMAN -> R.drawable.pedestrian
            else -> 0
        }

        if (resId != 0) {
            objectView.apply {
                setImageResource(resId)
                elevation = 6f
                bringToFront()
                alpha = 0f
                visibility = View.VISIBLE
                animate().alpha(1f).setDuration(250).start()
                scaleX = if (direction == Direction.RIGHT) -1f else 1f
            }
        }
    }

    private fun removeObjectImg(direction: Direction) {
        val objectView = getViewForDirection(binding.leftObject, binding.rightObject, binding.topObject, binding.bottomObject, direction)
        objectView.visibility = View.GONE
    }

    private fun <T : View> getViewForDirection(left: T, right: T, top: T, bottom: T, direction: Direction): T {
        return when (direction) {
            Direction.LEFT -> left
            Direction.RIGHT -> right
            Direction.TOP -> top
            Direction.BOTTOM -> bottom
            Direction.NULL -> bottom
        }
    }

    fun destroy() {
        pulseAnimators.values.forEach { it.cancel() }
        pulseAnimators.clear()
        arrowAnimators.values.forEach { it.cancel() }
        arrowAnimators.clear()
        iconBreathingAnimator?.cancel()
        stopActiveStandbyAnimation()
    }
}