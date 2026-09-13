import { describe, it, expect, afterEach } from 'vitest'

// Import the component to trigger custom element registration
import '../index.js'

const OPTIONS: [string, string[]][] = [
  ['blues', ['#f7fbff', '#6baed6', '#08306b']],
  ['greens', ['#f7fcf5', '#74c476', '#00441b']],
]

async function createElement(opts?: {
  value?: string
  options?: [string, string[]][]
  name?: string
}) {
  const el = document.createElement('palette-picker')
  if (opts?.options !== undefined) el.setAttribute('options', JSON.stringify(opts.options))
  if (opts?.value !== undefined) el.setAttribute('value', opts.value)
  if (opts?.name !== undefined) el.setAttribute('name', opts.name)
  document.body.appendChild(el)
  await (el as any).updateComplete
  return el as any
}

describe('palette-picker', () => {
  afterEach(() => {
    document.querySelectorAll('palette-picker').forEach((el) => el.remove())
  })

  it('renders a hidden select with an option per palette, plus Manual', async () => {
    const el = await createElement({ options: OPTIONS })
    const select = el.querySelector('select') as HTMLSelectElement
    expect(select.name).toBe('palette_name')
    expect(select.querySelectorAll('option').length).toBe(OPTIONS.length + 1)
  })

  it('defaults to Manual when no value is set', async () => {
    const el = await createElement({ options: OPTIONS })
    const label = el.querySelector('.palette-picker-current-label') as HTMLElement
    expect(label.textContent?.trim()).toBe('Manual')
  })

  it('shows the selected palette name on the toggle', async () => {
    const el = await createElement({ options: OPTIONS, value: 'greens' })
    const label = el.querySelector('.palette-picker-current-label') as HTMLElement
    expect(label.textContent?.trim()).toBe('greens')
    const select = el.querySelector('select') as HTMLSelectElement
    expect(select.value).toBe('greens')
  })

  it('opens the menu when the toggle is clicked', async () => {
    const el = await createElement({ options: OPTIONS })
    const toggle = el.querySelector('.palette-picker-toggle') as HTMLButtonElement
    toggle.click()
    await el.updateComplete
    expect(el.querySelector('.palette-picker-menu')?.classList.contains('is-open')).toBe(true)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
  })

  it('selecting an option updates the hidden select and dispatches change', async () => {
    const el = await createElement({ options: OPTIONS })
    let changeFired = false
    el.querySelector('select')!.addEventListener('change', () => {
      changeFired = true
    })

    const options = el.querySelectorAll('.palette-picker-option')
    // First option is "Manual", second is "blues".
    ;(options[1] as HTMLElement).click()
    await el.updateComplete

    expect(el.querySelector('select').value).toBe('blues')
    expect(changeFired).toBe(true)
    expect(el.querySelector('.palette-picker-menu')?.classList.contains('is-open')).toBe(false)
  })

  it('closing via the backdrop click closes the menu', async () => {
    const el = await createElement({ options: OPTIONS })
    const toggle = el.querySelector('.palette-picker-toggle') as HTMLButtonElement
    toggle.click()
    await el.updateComplete
    ;(el.querySelector('.palette-picker-backdrop') as HTMLElement).click()
    await el.updateComplete
    expect(el.querySelector('.palette-picker-menu')?.classList.contains('is-open')).toBe(false)
  })

  it('closes when a pointerdown lands outside the element, even if the backdrop is bypassed', async () => {
    // Regression test: a stuck-open menu leaves its full-viewport backdrop
    // in place, silently blocking clicks anywhere on the page (e.g. a Save
    // button elsewhere in the form) until the toggle is clicked again.
    const el = await createElement({ options: OPTIONS })
    const toggle = el.querySelector('.palette-picker-toggle') as HTMLButtonElement
    toggle.click()
    await el.updateComplete
    expect(el.querySelector('.palette-picker-menu')?.classList.contains('is-open')).toBe(true)

    const outsideButton = document.createElement('button')
    document.body.appendChild(outsideButton)
    outsideButton.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await el.updateComplete

    expect(el.querySelector('.palette-picker-menu')?.classList.contains('is-open')).toBe(false)
    expect(el.querySelector('.palette-picker-backdrop')).toBeNull()
    outsideButton.remove()
  })

  it('does not close when a pointerdown lands inside the element (e.g. on an option)', async () => {
    const el = await createElement({ options: OPTIONS })
    const toggle = el.querySelector('.palette-picker-toggle') as HTMLButtonElement
    toggle.click()
    await el.updateComplete

    const option = el.querySelector('.palette-picker-option') as HTMLElement
    option.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await el.updateComplete

    expect(el.querySelector('.palette-picker-menu')?.classList.contains('is-open')).toBe(true)
  })
})
