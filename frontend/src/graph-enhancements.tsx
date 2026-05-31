import React, { useEffect, useRef } from 'react'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import type { GraphCanvasRef } from 'reagraph'

// Slow auto-rotate that yields permanently to the user on first interaction.
//
// reagraph's built-in cameraMode="orbit" spins at a hardcoded 20 deg/s and never
// stops for the user, so instead we run cameraMode="pan" and drive a gentle
// azimuth rotation ourselves through the underlying camera-controls instance
// (reagraphRef.getControls()). The instance emits a 'control' event on any user
// drag/zoom/pan; on the first one we cancel the rotation loop for good.
const DEFAULT_ROTATE_DEG_PER_SEC = 4

export function useSlowAutoRotate(
  graphRef: React.MutableRefObject<GraphCanvasRef | null>,
  opts?: { degPerSec?: number; startDelayMs?: number; nodeCount?: number }
): void {
  const degPerSec = opts?.degPerSec ?? DEFAULT_ROTATE_DEG_PER_SEC
  const startDelayMs = opts?.startDelayMs ?? 600
  const nodeCount = opts?.nodeCount ?? 0

  useEffect(() => {
    let rafId = 0
    let startTimer = 0
    let lastTs = 0
    let stopped = false
    let controls: any = null
    const DEG2RAD = Math.PI / 180

    const stop = () => {
      stopped = true
      if (rafId) cancelAnimationFrame(rafId)
      rafId = 0
      if (controls && typeof controls.removeEventListener === 'function') {
        controls.removeEventListener('control', stop)
      }
    }

    const tick = (ts: number) => {
      if (stopped || !controls) return
      const delta = lastTs ? (ts - lastTs) / 1000 : 0
      lastTs = ts
      try {
        controls.azimuthAngle += degPerSec * delta * DEG2RAD
        controls.update(delta)
      } catch {
        stop()
        return
      }
      rafId = requestAnimationFrame(tick)
    }

    const begin = () => {
      const ref = graphRef.current
      controls = ref && typeof ref.getControls === 'function' ? ref.getControls() : null
      if (!controls) {
        // Controls not mounted yet — retry shortly while the canvas initialises.
        startTimer = window.setTimeout(begin, 250)
        return
      }
      // Skip the idle spin on very large graphs where it just adds churn.
      if (nodeCount > 600) return
      if (typeof controls.addEventListener === 'function') {
        controls.addEventListener('control', stop)
      }
      lastTs = 0
      rafId = requestAnimationFrame(tick)
    }

    startTimer = window.setTimeout(begin, startDelayMs)

    return () => {
      window.clearTimeout(startTimer)
      stop()
    }
  }, [graphRef, degPerSec, startDelayMs, nodeCount])
}

// Bloom/glow pass rendered inside reagraph's r3f <Canvas> (passed as children).
// luminanceThreshold below 1 lets the bright node fills bloom while the dark
// background stays clean. mipmapBlur keeps it cheap.
export function GraphGlow(): React.JSX.Element {
  return (
    <EffectComposer>
      <Bloom
        intensity={1.1}
        luminanceThreshold={0.2}
        luminanceSmoothing={0.9}
        mipmapBlur
        radius={0.7}
      />
    </EffectComposer>
  )
}

// Tiny helper to detect when the canvas has produced its first frame, used to
// fade the host in for a smoother entry.
export function useEntryFade(active: boolean): React.CSSProperties {
  const ref = useRef(false)
  useEffect(() => {
    if (active) ref.current = true
  }, [active])
  return {
    opacity: active ? 1 : 0,
    transition: 'opacity 700ms ease',
  }
}
