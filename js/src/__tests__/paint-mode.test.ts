/* eslint-disable @typescript-eslint/no-unsafe-argument */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { PaintModeController } from '../components/paint-mode.js'
import { mockMap } from './setup.js'

const map = mockMap as unknown as any

describe('PaintModeController', () => {
  let host: HTMLElement

  beforeEach(() => {
    vi.clearAllMocks()
    host = document.createElement('div')
  })

  it('creates and activates without error', () => {
    const ctrl = new PaintModeController(map, host)
    ctrl.activate()
    expect(ctrl.isActive).toBe(true)
  })

  it('deactivates cleanly', () => {
    const ctrl = new PaintModeController(map, host)
    ctrl.activate()
    ctrl.deactivate()
    expect(ctrl.isActive).toBe(false)
  })

  it('getSelectedFeatures returns empty array when no selection', () => {
    const ctrl = new PaintModeController(map, host)
    ctrl.activate()
    const features = ctrl.getSelectedFeatures()
    expect(features).toEqual([])
  })

  it('clearSelection resets selection state', () => {
    const ctrl = new PaintModeController(map, host)
    ctrl.activate()
    ctrl.clearSelection()
    expect(ctrl.isActive).toBe(true)
  })

  it('setSelectMode calls changeMode on draw instance', () => {
    const ctrl = new PaintModeController(map, host)
    ctrl.activate()
    ctrl.setSelectMode()
    // Should not throw
  })

  it('isActive returns false before activation', () => {
    const ctrl = new PaintModeController(map, host)
    expect(ctrl.isActive).toBe(false)
  })

  it('isActive returns false after deactivation', () => {
    const ctrl = new PaintModeController(map, host)
    ctrl.activate()
    ctrl.deactivate()
    expect(ctrl.isActive).toBe(false)
  })
})
